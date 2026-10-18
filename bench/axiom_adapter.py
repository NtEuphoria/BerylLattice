"""Axiom adapter for the benchmark protocol, with per-phase timing.

argv: kernel pattern a b min_ms max_reps [cap] [objective]

Each repetition runs the full checked pipeline on the local interpreter
backend: parse -> admit -> select (generate + independently check plans) ->
execute the selected plan -> independent source evaluation -> comparison.
`ns_median` is the execute phase alone (the closest analogue of a baseline's
kernel time); `phases` holds every phase so pipeline cost stays visible.

Kernels Axiom cannot accept are still attempted from their draft source when
one exists, so the log records the real diagnostic, not an assumption.
Special kernels: reject_range (out-of-range input), reject_shape (257+ input
cells) and reject_profile (well-formed source outside the admitted profile)
measure how quickly Axiom refuses bad requests.
"""
import json
import re
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'axiom' / 'src'))

from catalog import KERNELS, checksum, gen_input  # noqa: E402
from axiom.frontend import admit_source, parse_source  # noqa: E402
from axiom.model import DiagnosticError, Limits  # noqa: E402
from axiom.reference import evaluate_source  # noqa: E402
from axiom.runtime import execute_plan  # noqa: E402
from axiom.selection import select_plan  # noqa: E402

CHECK_STEPS = 100000
PHASES = ('parse', 'admit', 'select', 'execute', 'reference')


def draft_source(name, shapes, cap=None, objective=None):
    text = (HERE / 'axiom_drafts' / name).read_text(encoding='utf-8')
    values = iter(shapes)
    text = re.sub(r'shape (\w+) = \d+;', lambda m: f'shape {m.group(1)} = {next(values)};', text)
    if cap is not None:
        text = re.sub(r'plan_workspace_bytes <= \d+;', f'plan_workspace_bytes <= {cap};', text)
    if objective is not None:
        text = re.sub(r'prefer \w+;', f'prefer {objective};', text)
    return text.encode('utf-8')


def pipeline(source, data, n_out):
    """One checked run. Returns (phase times, result dict) or raises DiagnosticError."""
    limits = Limits()
    t = {}
    start = time.perf_counter_ns()
    module = parse_source(source, limits)
    t['parse'] = time.perf_counter_ns() - start
    start = time.perf_counter_ns()
    kernel = admit_source(module)
    t['admit'] = time.perf_counter_ns() - start
    start = time.perf_counter_ns()
    search = select_plan(kernel, limits, CHECK_STEPS, kernel.objective)
    t['select'] = time.perf_counter_ns() - start
    if search.selected_plan is None:
        return t, dict(status='no_eligible_plan', attempts=len(search.attempts),
                       termination=search.termination_reason.value)
    initial = [-9] * n_out
    start = time.perf_counter_ns()
    observed = execute_plan(source, search.selected_plan_bytes, data, initial, limits)
    t['execute'] = time.perf_counter_ns() - start
    start = time.perf_counter_ns()
    expected = evaluate_source(module, data, initial)
    t['reference'] = time.perf_counter_ns() - start
    check = search.selected_check
    return t, dict(status=observed.status.value, matches=observed == expected,
                   output=list(observed.output), first_bad_index=observed.first_bad_index,
                   plan=dict(id=search.selected_plan.plan_id, workspace_bytes=check.workspace_bytes,
                             multiplication_ops=check.multiplication_ops,
                             candidates=len(search.attempts),
                             eligible=sum(1 for x in search.attempts if x.check is not None and x.check.eligible)))


def request(kernel, pattern, a, b, cap, objective):
    """Return (source bytes, input data, output count, note) for a benchmark case."""
    if kernel == 'reject_range':
        data = gen_input(pattern, (a + 1) * (b + 1))
        data[len(data) // 2] = 1024
        return draft_source('sq2x2.ax', (a, b), cap, objective), data, a * b, 'one input is 1024'
    if kernel == 'reject_shape':
        return draft_source('sq2x2.ax', (16, 16), cap, objective), gen_input(pattern, 289), 256, '17x17 input'
    if kernel == 'reject_profile':
        return draft_source('box3x3.ax', (a, b)), gen_input(pattern, (a + 2) * (b + 2)), a * b, 'box3x3 draft'
    spec = KERNELS[kernel]
    n_in, n_out = spec['io'](a, b)
    if spec['axiom_draft'] is None:
        return None, None, n_out, None
    shapes = (a,) if spec['family'] in ('stencil-1d', 'elementwise') else (a, b)
    return draft_source(spec['axiom_draft'], shapes, cap, objective), gen_input(pattern, n_in), n_out, None


def main():
    kernel, pattern = sys.argv[1], sys.argv[2]
    a, b, min_ms, max_reps = (int(v) for v in sys.argv[3:7])
    cap = int(sys.argv[7]) if len(sys.argv) > 7 else None
    objective = sys.argv[8] if len(sys.argv) > 8 else None
    base = dict(impl='axiom', kernel=kernel, backend='checked-plan-interpreter-v1', cap=cap, objective=objective)
    source, data, n_out, note = request(kernel, pattern, a, b, cap, objective)
    if source is None:
        spec = KERNELS[kernel]
        print(json.dumps(dict(base, status='unsupported', diagnostic=dict(
            stage='grammar', code='NOT_EXPRESSIBLE', missing=spec['missing']))))
        return 0
    try:
        times, result = pipeline(source, data, n_out)  # warm-up; also classifies the case
    except DiagnosticError as error:
        # Time the rejection itself: how fast Axiom says no.
        samples = []
        while len(samples) < 3 or (sum(samples) < min_ms * 1_000_000 and len(samples) < max_reps):
            start = time.perf_counter_ns()
            try:
                pipeline(source, data, n_out)
            except DiagnosticError:
                pass
            samples.append(time.perf_counter_ns() - start)
        stage = 'parse' if error.code in ('SYNTAX_ERROR', 'INVALID_TOKEN') else 'admit'
        status = 'rejected' if kernel.startswith('reject_') else 'unsupported'
        print(json.dumps(dict(base, status=status, note=note, reps=len(samples),
                              reject_ns_median=int(statistics.median(samples)),
                              diagnostic=dict(stage=stage, code=error.code, message=error.message,
                                              missing=KERNELS.get(kernel, {}).get('missing')))))
        return 0
    if result['status'] != 'success':
        print(json.dumps(dict(base, status='rejected' if kernel.startswith('reject_') else 'error',
                              note=note, result_status=result['status'],
                              first_bad_index=result.get('first_bad_index'),
                              matches_reference=result.get('matches'), reps=1,
                              phases_ns=times)))
        return 0
    if not result['matches']:
        print(json.dumps(dict(base, status='mismatch', diagnostic=dict(
            stage='reference', code='INDEPENDENT_COMPARISON_FAILED'))))
        return 1
    phase_samples = {name: [] for name in PHASES}
    totals = []
    while len(totals) < 3 or (sum(totals) < min_ms * 1_000_000 and len(totals) < max_reps):
        times, result = pipeline(source, data, n_out)
        if not result['matches']:
            raise AssertionError('Axiom plan disagreed with the reference during timing')
        for name in PHASES:
            phase_samples[name].append(times[name])
        totals.append(sum(times.values()))
    execute = phase_samples['execute']
    print(json.dumps(dict(base, status='ok', n_out=len(result['output']), checksum=checksum(result['output']),
                          reps=len(totals), ns_min=min(execute), ns_median=int(statistics.median(execute)),
                          ns_total=sum(execute), pipeline_ns_median=int(statistics.median(totals)),
                          phases_ns_median={k: int(statistics.median(v)) for k, v in phase_samples.items()},
                          plan=result['plan'])))
    return 0


if __name__ == '__main__':
    sys.exit(main())