"""Checked fixed-case witnesses and independently observed, manifest-last capsules.

Production consumes explicit case/source bytes. Corpus generators are test-only.
Execution uses a retained private work directory; export uses pinned dirfds so a
changed output ancestor cannot redirect compiler or publication writes.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import fields, is_dataclass
from enum import Enum
from hashlib import sha256
import os
from pathlib import Path
import tempfile

from .checker import check_plan
from .codec import canonical_json, decode_plan, encode_plan, strict_json_loads
from .core_emit import emit_core
from .core_observe import Observation, decode_observation
from .core_runner import run_core
from .core_toolchain import ToolchainError, build_core, inspect_toolchain, prepare_snapshot
from .evidence import _directory, _directory_unchanged, _publish_content, _read_exact_at
from .frontend import admit_source, parse_source
from .model import Limits
from .planner import make_plan
from .reference import evaluate_source

MANIFEST_LIMIT = 8*1024*1024
_PLAN_IDS = ('inline-v1', 'materialize-v1', 'rows2-v1')


def _jsonable(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return value.decode('utf-8', 'strict')
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _read(path, maximum):
    with Path(path).open('rb') as stream:
        raw = stream.read(maximum+1)
    if len(raw)>maximum:
        raise ValueError('File exceeds byte quota: '+str(path))
    return raw


def _object(value, names, label):
    if type(value) is not dict or set(value) != set(names):
        raise ValueError(label+': missing or unknown fields')


def _vector(value, count, label):
    if (type(value) is not list or len(value) != count or
            any(type(item) is not int or not -(2**31) <= item < 2**31 for item in value)):
        raise ValueError(f'{label}: expected exactly {count} signed i32 scalars')
    return tuple(value)


def decode_case(raw, kernel):
    value = strict_json_loads(raw, max_bytes=65536, max_items=1024, max_depth=3)
    _object(value, ('schema_version', 'input', 'initial_output'), 'case')
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('case: unsupported schema_version')
    data = _vector(value['input'], (kernel.height+1)*(kernel.width+1), 'case.input')
    initial = _vector(value['initial_output'], kernel.height*kernel.width, 'case.initial_output')
    return value, data, initial


def decode_conformance(raw):
    value = strict_json_loads(raw, max_bytes=MANIFEST_LIMIT, max_items=300000, max_depth=8)
    _object(value, ('schema_version', 'artifact_kind', 'plans', 'lanes', 'cases'), 'conformance manifest')
    if type(value['schema_version']) is not int or value['schema_version'] != 1 or value['artifact_kind'] != 'core_correspondence_manifest':
        raise ValueError('conformance manifest: unsupported version/kind')
    plans, lanes, cases = value['plans'], value['lanes'], value['cases']
    if type(plans) is not list or not 1 <= len(plans) <= 3 or any(type(item) is not str or item not in _PLAN_IDS for item in plans) or len(set(plans)) != len(plans):
        raise ValueError('conformance plans: expected distinct known plan IDs')
    if type(lanes) is not list or not 1 <= len(lanes) <= 6:
        raise ValueError('conformance lanes: expected nonempty bounded lanes')
    seen = set()
    for item in lanes:
        _object(item, ('lane', 'release'), 'conformance lane')
        if type(item['lane']) is not str or item['lane'] not in ('reference', 'ast', 'ir') or type(item['release']) is not bool:
            raise ValueError('conformance lane: invalid lane/release')
        key = (item['lane'], item['release'])
        if key in seen:
            raise ValueError('conformance lane: duplicate lane/release')
        seen.add(key)
    if type(cases) is not list or not 1 <= len(cases) <= 512:
        raise ValueError('conformance cases: expected 1 through 512 cases')
    seen = set()
    admitted = []
    for case in cases:
        _object(case, ('case_id', 'shape', 'pattern', 'source_utf8', 'source_sha256', 'input', 'initial_output'), 'conformance case')
        for key in ('case_id', 'pattern', 'source_utf8'):
            if type(case[key]) is not str or not case[key] or len(case[key]) > (Limits().source_bytes if key == 'source_utf8' else 256):
                raise ValueError('conformance case: invalid '+key)
        if case['case_id'] in seen:
            raise ValueError('conformance case: duplicate case_id')
        seen.add(case['case_id'])
        source = case['source_utf8'].encode('utf-8', 'strict')
        if case['source_sha256'] != sha256(source).hexdigest():
            raise ValueError('conformance case: source SHA-256 differs from exact embedded bytes')
        module = parse_source(source)
        kernel = admit_source(module)
        if type(case['shape']) is not list or any(type(n) is not int for n in case['shape']) or case['shape'] != [kernel.height, kernel.width]:
            raise ValueError('conformance case: shape differs from admitted source')
        _, data, initial = decode_case(canonical_json(dict(schema_version=1, input=case['input'], initial_output=case['initial_output'])), kernel)
        admitted.append((case, source, module, kernel, data, initial))
    return value, admitted


def _write(root, name, value):
    path = root/name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else canonical_json(_jsonable(value)))
    return path


def _expected(module, data, initial):
    result = evaluate_source(module, data, initial)
    return Observation(-1 if result.first_bad_index is None else result.first_bad_index, result.input_after, result.output)


def _bundle_files(root, bundle, case):
    _write(root, 'source.ax', bundle.axiom_source_bytes)
    _write(root, 'plan.json', bundle.plan_bytes)
    _write(root, 'case.json', case)
    _write(root, 'kernel.be', bundle.kernel_source_bytes)
    _write(root, 'witness.be', bundle.source_bytes)
    _write(root, 'emission.json', dict(artifact_kind='core_emission_receipt',
        source_digest=bundle.source_digest, semantic_digest=bundle.semantic_digest,
        plan_digest=bundle.plan_digest, plan_bytes_sha256=bundle.plan_bytes_sha256,
        generated_source_sha256=bundle.generated_source_sha256, kernel_source_sha256=bundle.kernel_source_sha256,
        case_digest=bundle.case_digest, emitter_digest=bundle.emitter_digest, emitter_version=bundle.emitter_version,
        mappings=bundle.mappings, observation_layout=bundle.observation_layout,
        kernel_artifact_kind='core_kernel_source', witness_artifact_kind=bundle.artifact_kind))


def _compare(bundle, kernel, expected, toolchain, lane, release, work):
    run = run_core(bundle, toolchain, lane, work/'runs', release=release)
    observed = {}
    comparisons = {}
    if run.classification == 'success':
        for label, path in (('reference', run.reference_stdout_path), ('native', run.native_stdout_path)):
            if path is not None:
                actual = decode_observation(path.read_bytes(), kernel)
                observed[label] = actual
                comparisons[label] = dict(status=actual.status == expected.status,
                    input=actual.input == expected.input, output=actual.output == expected.output,
                    complete_observation=actual == expected)
    expected_labels = {'reference'} if lane == 'reference' else {'reference', 'native'}
    matched = set(observed) == expected_labels and all(item['complete_observation'] for item in comparisons.values())
    classification = ('matched' if matched else 'semantic_mismatch') if run.classification == 'success' else run.classification
    row = dict(lane=lane, release=release, classification=classification,
        source_emission='success', build_status='not_applicable' if lane == 'reference' else 'success' if run.native_status == 'exited' else 'failed_or_unavailable',
        conformance_status='matched' if matched else 'mismatch' if run.classification == 'success' else 'not_observed',
        expected=expected, observations=observed, comparisons=comparisons, run=run)
    return _jsonable(row)


def _inventory(root):
    result = []
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise OSError('Capsule contains a symlink: '+str(path))
        if path.is_file():
            raw = path.read_bytes()
            result.append(dict(path=path.relative_to(root).as_posix(), original_path=str(path), sha256=sha256(raw).hexdigest(), size=len(raw)))
    return result


def _export_file(root_fd, name, raw):
    parts = Path(name).parts
    descriptor = os.dup(root_fd)
    try:
        for component in parts[:-1]:
            try:
                os.mkdir(component, mode=0o700, dir_fd=descriptor)
            except FileExistsError:
                pass
            child = os.open(component, os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        _publish_content(descriptor, parts[-1], raw)
        _read_exact_at(descriptor, parts[-1], raw)
    finally:
        os.close(descriptor)


def _publish(work, output, summary, external_references=()):
    """No output manifest exists until the complete exported inventory validates."""
    inventory = _inventory(work)
    manifest = dict(schema_version=1, artifact_kind='core_reproducibility_capsule',
                    work_directory=str(work), summary=summary, files=inventory, external_references=list(external_references),
                    limitations=['Retained absolute work/toolchain paths bind receipts; export is not a relocatable native ABI.',
                                 'Known SDK/linker/transitive library identity is incomplete; tested cases establish no universal proof or throughput result.'])
    raw_manifest = canonical_json(manifest)
    with _directory(output, create=True) as descriptor:
        try:
            os.stat('manifest.json', dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError('Capsule output already has an immutable manifest')
        for item in inventory:
            raw = (work/item['path']).read_bytes()
            if len(raw) != item['size'] or sha256(raw).hexdigest() != item['sha256']:
                raise OSError('Capsule source bytes changed during export')
            _export_file(descriptor, item['path'], raw)
        # Reopen and verify all references after the final export, before manifest.
        for item in inventory:
            raw = (work/item['path']).read_bytes()
            if len(raw) != item['size'] or sha256(raw).hexdigest() != item['sha256']:
                raise OSError('Capsule source changed before manifest publication')
            with _directory(Path(output)/Path(item['path']).parent) as parent:
                _read_exact_at(parent, Path(item['path']).name, raw)
        for item in external_references:
            path = Path(item['path'])
            raw = path.read_bytes()
            if path.resolve(strict=True) != Path(item['resolved_path']) or len(raw) != item['size'] or sha256(raw).hexdigest() != item['sha256']:
                raise OSError('External capsule reference changed before publication')
        _directory_unchanged(output, descriptor)
        _publish_content(descriptor, 'manifest.json', raw_manifest)
        os.fsync(descriptor)
        _directory_unchanged(output, descriptor)
    return Path(output).absolute()/'manifest.json'


def _external_references(toolchain, work):
    """Bind retained toolchain dependencies which live outside this working capsule."""
    paths = {toolchain.compiler, toolchain.clang, toolchain.receipt_path,
             toolchain.receipt_path.parent/'build.json', toolchain.receipt_path.parent/'unit.json',
             toolchain.receipt_path.parent/'native.json', toolchain.snapshot/'.axiom-source.json'}
    for item in (*toolchain.clang_config, *toolchain.clang_components, *toolchain.native_artifacts):
        paths.add(item.lookup_path or item.path)
    paths.update(toolchain.source_repository/name for name, _, _ in toolchain.source_inventory)
    paths.update(toolchain.snapshot/name for name, _, _ in toolchain.snapshot_inventory)
    # Qualification metadata refers to more than native_artifacts: retain the
    # fixed witness, all stage stdout/stderr logs, argv files, generated runtime
    # and C/native outputs. Transient preflight probes are historical receipts,
    # not retained dependencies and are deliberately absent from this closure.
    qualification = toolchain.receipt_path.parent/'native-probe'
    paths.add(qualification/'witness.be')
    jobs = list((qualification/'.beryl-cache').glob('job-*'))
    if len(jobs) != 1 or not jobs[0].is_dir():
        raise OSError('Expected one retained qualification job')
    for stage in ('version', 'llvm-ir', 'assembly', 'driver-jobs', 'compile', 'run'):
        for stream in ('stdout', 'stderr'):
            paths.add(jobs[0]/f'{stage}.{stream}.log')
    for path in qualification.rglob('*'):
        if path.is_symlink():
            raise OSError('Retained qualification contains a symlink')
        if path.is_file():
            paths.add(path)
    result = []
    for path in sorted(paths):
        raw = path.read_bytes()
        result.append(dict(path=str(path), resolved_path=str(path.resolve(strict=True)),
                           reference_scope='working_capsule' if work in path.parents else 'external', sha256=sha256(raw).hexdigest(), size=len(raw)))
    return result


def _finish(work, output, rows, toolchain, retained_references=None):
    rows.sort(key=lambda row: (row['case_id'], row['plan_id'], row['lane'], row['release']))
    _write(work, 'lane-matrix.json', rows)
    toolchain.revalidate_identity()
    mismatch = any(row['classification'] == 'semantic_mismatch' for row in rows)
    errors = any(row['classification'] not in ('matched', 'semantic_mismatch') for row in rows)
    summary = dict(status='infrastructure_failure' if errors else 'semantic_mismatch' if mismatch else 'matched',
                   matched=sum(row['classification'] == 'matched' for row in rows), expected=len(rows),
                   toolchain_receipt=str(toolchain.receipt_path), work_directory=str(work))
    references = _external_references(toolchain, work) if retained_references is None else retained_references
    manifest = _publish(work, output, summary, references)
    return (5 if errors else 6 if mismatch else 0), dict(summary, manifest=str(manifest))


def witness_command(args):
    limits = Limits()
    source = _read(args.source, limits.source_bytes)
    plan_raw = _read(args.plan, limits.plan_bytes)
    module = parse_source(source, limits)
    kernel = admit_source(module)
    case_raw = _read(args.case, 65536)
    case, data, initial = decode_case(case_raw, kernel)
    plan = decode_plan(plan_raw, limits)
    checked = check_plan(kernel, plan, limits)
    if not checked.eligible:
        if checked.reason == 'SOURCE_DIGEST_MISMATCH':
            raise ValueError(checked.reason)
        return 4, dict(status='no_eligible_plan', check=_jsonable(checked))
    bundle = emit_core(source, plan_raw, limits, data, initial)
    expected = _expected(module, data, initial)
    preflight = inspect_toolchain(Path(args.core), Path(args.clang))
    if not preflight.available:
        return 5, dict(status='unavailable' if preflight.status == 'unavailable' else 'infrastructure_failure', reason=preflight.reason)
    work = Path(tempfile.mkdtemp(prefix='axiom-core-capsule-'))
    _bundle_files(work/'fixed', bundle, case)
    _write(work, 'case-input.json', case_raw)
    _write(work, 'request.json', dict(command='witness', source_sha256=sha256(source).hexdigest(),
        plan_sha256=sha256(plan_raw).hexdigest(), case_sha256=sha256(canonical_json(case)).hexdigest(), case_exact_sha256=sha256(case_raw).hexdigest(),
        core=str(Path(args.core).absolute()), clang=str(Path(args.clang).absolute()), lane=args.lane, release=args.release))
    try:
        snapshot = prepare_snapshot(Path(args.core), work/'core-snapshot')
        toolchain = build_core(snapshot, Path(args.clang), work/'toolchain')
    except ToolchainError as error:
        _write(work, 'toolchain-failure.json', dict(reason=str(error), receipts=error.receipts))
        summary = dict(status='infrastructure_failure', source_emission='success', build_status='failed', conformance_status='not_observed', work_directory=str(work))
        manifest = _publish(work, args.out, summary)
        return 5, dict(summary, manifest=str(manifest))
    retained_references = _external_references(toolchain, work)
    _write(work, 'retained-toolchain-references.json', retained_references)
    row = _compare(bundle, kernel, expected, toolchain, args.lane, args.release, work)
    row.update(case_id='fixed', plan_id=plan.plan_id)
    return _finish(work, args.out, [row], toolchain, retained_references)


def _run_tasks(tasks, execute, workers=4):
    """Cancel queued cells on interruption; join every already active invocation."""
    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='axiom-conformance')
    futures = []
    try:
        futures = [pool.submit(execute, task) for task in tasks]
        # Completion order exposes later-task failures immediately; _finish
        # performs deterministic row sorting after every active worker joins.
        return [future.result() for future in as_completed(futures)]
    except BaseException:
        for future in futures:
            future.cancel()
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


def conformance_command(args):
    raw = _read(args.manifest, MANIFEST_LIMIT)
    manifest, cases = decode_conformance(raw)
    # Import lazily so portable witness validation does not require receipt loading.
    from .core_toolchain import load_toolchain
    toolchain = load_toolchain(Path(args.toolchain))
    work = Path(tempfile.mkdtemp(prefix='axiom-core-capsule-'))
    _write(work, 'request.json', raw)
    _write(work, 'execution-config.json', dict(workers=args.workers, stage_timeout_ms=120000, pipeline_timeout_ms=1200000))
    _write(work, 'toolchain.json', _read(args.toolchain, 32*1024*1024))
    retained_references = _external_references(toolchain, work)
    _write(work, 'retained-toolchain-references.json', retained_references)
    tasks = []
    for index, (case, source, module, kernel, data, initial) in enumerate(cases):
        expected = _expected(module, data, initial)
        for plan_id in manifest['plans']:
            plan_raw = encode_plan(make_plan(kernel, plan_id))
            bundle = emit_core(source, plan_raw, Limits(), data, initial)
            _bundle_files(work/'cases'/f'{index:04d}'/plan_id, bundle,
                          dict(schema_version=1, input=list(data), initial_output=list(initial)))
            for lane in manifest['lanes']:
                tasks.append((case['case_id'], plan_id, bundle, kernel, expected, lane))
    def execute(task):
        case_id, plan_id, bundle, kernel, expected, lane = task
        row = _compare(bundle, kernel, expected, toolchain, lane['lane'], lane['release'], work)
        row.update(case_id=case_id, plan_id=plan_id)
        return row
    rows = _run_tasks(tasks, execute, args.workers)
    return _finish(work, args.out, rows, toolchain, retained_references)
