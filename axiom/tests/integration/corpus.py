"""Explicit native sampling and complete independent source observations.

All evidence is retained outside the checkout. No compiler receipt or agreement
between Core lanes supplies the expected result: only evaluate_source does.
"""
from dataclasses import asdict, dataclass
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import os
from pathlib import Path
import random
import tempfile
import threading
import unittest

from axiom.codec import encode_plan
from axiom.core_emit import emit_core
from axiom.core_observe import Observation, decode_observation
from axiom.core_runner import run_core
from axiom.core_toolchain import build_core, inspect_toolchain, prepare_snapshot
from axiom.frontend import admit_source, parse_source
from axiom.model import Limits
from axiom.planner import make_plan
from axiom.reference import evaluate_source
from tests.helpers import stencil_source

QUICK_SHAPES = ((1, 1), (1, 7), (7, 1), (2, 3), (3, 2), (5, 7))
PLAN_IDS = ('inline-v1', 'materialize-v1', 'rows2-v1')
LANES = (('reference', False), ('ast', False), ('ir', False), ('ast', True), ('ir', True))
SEEDS = (1729, 8675309)


@dataclass(frozen=True)
class Case:
    shape: tuple[int, int]
    pattern: str
    data: tuple[int, ...]
    initial_output: tuple[int, ...]

    @property
    def case_id(self):
        return f'h{self.shape[0]}-w{self.shape[1]}/{self.pattern}'

    def as_dict(self):
        source = source_for(self)
        return dict(case_id=self.case_id, shape=list(self.shape), pattern=self.pattern,
                    source_utf8=source.decode('utf-8'), source_sha256=sha256(source).hexdigest(),
                    input=list(self.data), initial_output=list(self.initial_output))


def _case(shape, pattern, data):
    # Distinct nonzero sentinels reveal omitted stores and partial rejection writes.
    h, w = shape
    return Case(shape, pattern, tuple(data), tuple(-700000-i for i in range(h*w)))


def _shape_cases(shape, seeds=SEEDS):
    h, w = shape
    n = (h+1)*(w+1)
    yield _case(shape, 'all-zero', [0]*n)
    yield _case(shape, 'all-1023', [1023]*n)
    yield _case(shape, 'alternating-extremes', [1023*(i % 2) for i in range(n)])
    yield _case(shape, 'coordinate-ramp', [(r*31+c) % 1024 for r in range(h+1) for c in range(w+1)])
    for label, index in (('top-left', 0), ('top-right', w),
                         ('bottom-left', h*(w+1)), ('bottom-right', n-1)):
        values = [0]*n
        values[index] = 1023
        yield _case(shape, 'corner-'+label, values)
    for seed in seeds:
        rng = random.Random(seed)
        yield _case(shape, f'random-{seed}', [rng.randrange(1024) for _ in range(n)])
    for value in (-1, 1024):
        for label, index in (('first', 0), ('middle', n//2), ('last', n-1)):
            values = [17]*n
            values[index] = value
            yield _case(shape, f'invalid-{value}-{label}', values)
    for label, first, last in (('first-middle', 0, n//2), ('middle-last', n//2, n-1)):
        values = [17]*n
        values[first], values[last] = 1024, -1
        yield _case(shape, 'two-invalid-'+label, values)


def quick_cases():
    for shape in QUICK_SHAPES:
        yield from _shape_cases(shape)


def nightly_cases():
    for index in range(48):
        values = [0]*48
        values[index] = 1023
        yield _case((5, 7), f'impulse-{index}', values)
    for shape in ((7, 7), (9, 9)):
        yield from _shape_cases(shape, seeds=(11, 23, 47, 97))


def source_for(case):
    # No workspace cap is asserted by this corpus: exercise every intended plan.
    # Core's fixed aggregate/storage limits and normal Axiom limits still apply.
    return stencil_source(*case.shape, cap=None)


def expected_observation(case):
    result = evaluate_source(parse_source(source_for(case)), case.data, case.initial_output)
    return Observation(-1 if result.first_bad_index is None else result.first_bad_index,
                       result.input_after, result.output)


def conformance_manifest(cases=None):
    """Self-contained exact UTF-8 sources for the production CLI consumer."""
    entries = []
    for case in quick_cases() if cases is None else cases:
        entries.append(case.as_dict())
    return dict(schema_version=1, artifact_kind='core_correspondence_manifest',
                plans=list(PLAN_IDS), lanes=[dict(lane=lane, release=release) for lane, release in LANES],
                cases=entries)


def _jsonable(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return value.decode('utf-8', 'replace')
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


_ACTIVE_CAMPAIGN = None


def worker_limit(environment=None):
    environment = os.environ if environment is None else environment
    value = environment.get('AXIOM_CORE_WORKERS', '4')
    if value not in ('1', '2', '3', '4'):
        raise ValueError('AXIOM_CORE_WORKERS must be an integer from 1 through 4')
    return int(value)


class CorpusMismatch(AssertionError):
    pass


class Campaign:
    def __init__(self, root, toolchain):
        self.root, self.toolchain = root, toolchain
        self.records = []
        self._bundles = {}
        self._record_lock = threading.Lock()

    @classmethod
    def from_environment(cls, environment=None):
        global _ACTIVE_CAMPAIGN
        environment = os.environ if environment is None else environment
        names = ('AXIOM_CORE_SOURCE', 'AXIOM_CLANG', 'AXIOM_CORE_EVIDENCE_DIR')
        missing = [name for name in names if not environment.get(name)]
        if missing:
            raise unittest.SkipTest('native unavailable: configure '+', '.join(missing)+'; skips do not establish native conformance')
        if _ACTIVE_CAMPAIGN is not None:
            return _ACTIVE_CAMPAIGN
        source, clang = Path(environment[names[0]]), Path(environment[names[1]])
        preflight = inspect_toolchain(source, clang)
        if not preflight.available:
            raise unittest.SkipTest('native unavailable: '+preflight.reason)
        evidence = Path(environment[names[2]]).resolve()
        checkout = Path(__file__).resolve().parents[3]
        if evidence == checkout or checkout in evidence.parents:
            raise ValueError('Evidence must live outside the checkout')
        evidence.mkdir(parents=True, exist_ok=True)
        root = Path(tempfile.mkdtemp(prefix='axiom-correspondence-', dir=evidence))
        snapshot = prepare_snapshot(source, root/'core-snapshot')
        toolchain = build_core(snapshot, clang, root/'toolchain')
        campaign = cls(root, toolchain)
        (root/'quick-manifest.json').write_text(json.dumps(conformance_manifest(), indent=2)+'\n')
        (root/'campaign.json').write_text(json.dumps(dict(schema_version=1,
            toolchain_receipt=str(toolchain.receipt_path), plans=PLAN_IDS, lanes=LANES,
            limitation='SDK/linker/transitive libraries are not completely identified; no throughput claim.'))+'\n')
        _ACTIVE_CAMPAIGN = campaign
        print('Native correspondence evidence: '+str(root), flush=True)
        return campaign

    def bundle(self, case, plan_id):
        key = (case.case_id, plan_id)
        if key not in self._bundles:
            source = source_for(case)
            kernel = admit_source(parse_source(source))
            plan = make_plan(kernel, plan_id)
            self._bundles[key] = emit_core(source, encode_plan(plan), Limits(), case.data, case.initial_output)
        return self._bundles[key]

    def check(self, case, plan_id, bundle, lane, release=False, *, mutation=None):
        expected = expected_observation(case)
        run = run_core(bundle, self.toolchain, lane, self.root/'runs', release=release)
        row = dict(schema_version=1, case_id=case.case_id, plan_id=plan_id, lane=lane,
                   release=release, mutation=mutation, expected=asdict(expected),
                   classification=run.classification, reason=run.reason, run=asdict(run))
        observations = {}
        mismatch = None
        if run.classification == 'success':
            kernel = admit_source(parse_source(source_for(case)))
            for label, path in (('reference', run.reference_stdout_path), ('native', run.native_stdout_path)):
                if path is not None:
                    actual = decode_observation(path.read_bytes(), kernel)
                    observations[label] = asdict(actual)
                    if actual != expected:
                        mismatch = f'{case.case_id} {plan_id} {lane}: {label} differs from independent source oracle'
            row['classification'] = 'semantic_mismatch' if mismatch else 'matched'
        row['observations'] = observations
        with self._record_lock:
            self.records.append(row)
            with (self.root/'lane-matrix.jsonl').open('a') as stream:
                stream.write(json.dumps(_jsonable(row), sort_keys=True)+'\n')
        if run.classification != 'success':
            raise AssertionError(f'{case.case_id} {plan_id} {lane}: {run.classification}: {run.reason}; {run.cwd}')
        if mismatch:
            raise CorpusMismatch(mismatch)
        return row

    def run_matrix(self, cases):
        """Join every private invocation before returning errors to unittest.

        Bundle construction is sequential; workers only share immutable qualified
        bytes. map returns manifest order even when subprocesses finish out of order.
        """
        workers = worker_limit()
        tasks = []
        for case in cases:
            for plan_id in PLAN_IDS:
                bundle = self.bundle(case, plan_id)
                tasks.extend((case, plan_id, bundle, lane, release) for lane, release in LANES)

        def execute(task):
            case, plan_id, bundle, lane, release = task
            label = (case.case_id, plan_id, lane, release)
            try:
                self.check(case, plan_id, bundle, lane, release)
                return label, None
            except Exception as exc:
                return label, exc

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='axiom-core') as pool:
            results = list(pool.map(execute, tasks))
        # Stable published ordering; the append-only live matrix remains useful
        # during execution and is rewritten only after all workers have joined.
        self.records.sort(key=lambda row: (row['case_id'], row['plan_id'], row['lane'],
                                           row['release'], row['mutation'] or ''))
        with (self.root/'lane-matrix.jsonl').open('w') as stream:
            for row in self.records:
                stream.write(json.dumps(_jsonable(row), sort_keys=True)+'\n')
        return results

    def complete(self, name, expected_count):
        case_ids = {case.case_id for case in (quick_cases() if name == 'quick' else nightly_cases())}
        rows = [row for row in self.records if row['mutation'] is None and row['case_id'] in case_ids]
        required = {(case_id, plan_id, lane, release) for case_id in case_ids
                    for plan_id in PLAN_IDS for lane, release in LANES}
        actual = {(row['case_id'], row['plan_id'], row['lane'], row['release']) for row in rows}
        if (len(rows) != expected_count or actual != required or
                any(row['classification'] != 'matched' for row in rows)):
            raise AssertionError('Incomplete native campaign; unavailable/skipped/error cases cannot satisfy the milestone')
        (self.root/(name+'-complete.json')).write_text(json.dumps(dict(
            schema_version=1, campaign=name, matched=len(rows), expected=expected_count,
            matrix=str(self.root/'lane-matrix.jsonl'), toolchain_receipt=str(self.toolchain.receipt_path)))+'\n')
