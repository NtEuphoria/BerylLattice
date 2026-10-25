"""Untrusted candidate loop plans, for example written by AI agents.

Each candidate is JSON bytes in the beryl-loop-plan-v1 shape that plan_json
writes. load_plan decodes it defensively (bounded size and depth, integers
only); the template checker then decides it. Every accepted plan is also run
against the source's reference meaning on seeded inputs before anyone sees a
timing: a mismatch there would mean the checker accepted a wrong plan, so it
raises SoundnessAlarm instead of reporting.
"""
from dataclasses import dataclass
import json
import random

from .frontend import admit_source, parse_source
from .reference import evaluate_source
from .scale_checker import check_loop_plan
from .scale_plan import LoopPlan, Stage
from .scale_runtime import execute_loop_plan


class SoundnessAlarm(Exception):
    def __init__(self, name, seed):
        super().__init__(f'SOUNDNESS ALARM: accepted plan {name!r} differs from the reference (seed {seed})')
        self.name, self.seed = name, seed


@dataclass(frozen=True)
class CandidateResult:
    name: str
    accepted: bool
    reason: str
    detail: str | None
    plan: LoopPlan | None


def _reject(_text):
    raise ValueError('only integers are allowed')


def _tuples(value, depth, max_depth):
    if depth > max_depth:
        raise ValueError('nested too deeply')
    if isinstance(value, list):
        return tuple(_tuples(item, depth + 1, max_depth) for item in value)
    return value


def load_plan(data: bytes, max_bytes: int = 1 << 20, max_depth: int = 512) -> LoopPlan | None:
    """The LoopPlan in `data`, or None for anything malformed."""
    if type(data) is not bytes or len(data) > max_bytes:
        return None
    try:
        record = json.loads(data, parse_float=_reject, parse_constant=_reject)
        if type(record) is not dict or set(record) != {'format', 'semantic_digest', 'plan_id', 'stages'}:
            return None
        stages = record['stages']
        if type(stages) is not list or any(type(s) is not dict or set(s) != {'loops', 'index', 'value'}
                                           for s in stages):
            return None
        return LoopPlan(record['semantic_digest'], record['plan_id'],
                        tuple(Stage(*(_tuples(s[key], 0, max_depth) for key in ('loops', 'index', 'value')))
                              for s in stages),
                        record['format'])
    except (ValueError, RecursionError, UnicodeDecodeError):
        return None


def _samples(count, seed_base, size):
    for seed in range(count):
        if seed == 0:
            yield seed, [1023] * size
        else:
            rng = random.Random(seed_base + seed)
            yield seed, [rng.randrange(1024) for _ in range(size)]


def review_candidates(source: bytes, candidates: list[tuple[str, bytes]], samples: int = 3) -> list[CandidateResult]:
    """Check every candidate; verify each accepted one against the reference."""
    kernel = admit_source(parse_source(source))
    results = []
    for name, data in candidates:
        plan = load_plan(data)
        if plan is None:
            results.append(CandidateResult(name, False, 'INVALID_PLAN',
                                           'not a beryl-loop-plan-v1 JSON record', None))
            continue
        check = check_loop_plan(source, plan)
        if not check.valid:
            results.append(CandidateResult(name, False, check.reason, check.detail, None))
            continue
        for seed, data_in in _samples(samples, 20261029, kernel.input_count):
            initial = [-9] * kernel.output_count
            if execute_loop_plan(source, plan, data_in, initial) != \
                    evaluate_source(kernel.source_module, data_in, initial):
                raise SoundnessAlarm(name, seed)
        results.append(CandidateResult(name, True, 'VALID', None, plan))
    return results
