"""Bounded presentation requests over the existing Axiom v1 implementation.

The fixed worker reads one JSON request from stdin and emits one JSON response.
It accepts neither commands nor filesystem paths. Successful observations are
demo reports, not native execution or scalable-oracle qualification receipts.
"""
import sys

from .codec import DecodeError, canonical_json, strict_json_loads
from .frontend import admit_source, parse_source
from .model import DiagnosticError, Limits, Span
from .reference import ExecutionResult, ExecutionStatus, evaluate_source
from .runtime import execute_plan
from .selection import select_plan

REQUEST_BYTES = 131072
_BACKEND = 'checked-plan-interpreter-v1'
_SOURCE = '''module demo;
shape H = 5;
shape W = 7;
input image: i32[H+1,W+1] in 0..=1023;
let p[r in 0..H+1,c in 0..W+1] =
  (image[r,c]+1)*(image[r,c]+1);
output result[r in 0..H,c in 0..W] =
  ((p[r,c]+p[r,c+1])+p[r+1,c])+p[r+1,c+1];
require plan_workspace_bytes <= {cap};
prefer {objective};
'''


class _RequestError(ValueError):
    pass


def get_examples() -> dict:
    """Return fresh, complete source examples without accessing the filesystem."""
    definitions = (
        ('balanced', 'Reuse two rows', 'Reduce multiplication with a 64-byte plan scratch limit.',
         64, 'multiplication_ops'),
        ('no-scratch', 'No plan scratch', 'Recompute producer values with a zero-byte scratch limit.',
         0, 'multiplication_ops'),
        ('small-memory', 'Prefer less scratch', 'Rank scratch first, even when more scratch is permitted.',
         64, 'plan_workspace_bytes'),
    )
    return {'examples': [dict(id=identifier, title=title, description=description,
                              source=_SOURCE.format(cap=cap, objective=objective))
                         for identifier, title, description, cap, objective in definitions]}


def _error(code, message, offset=None):
    return {'schema_version': 1, 'status': 'error',
            'diagnostic': {'code': code, 'message': message, 'offset': offset}}


def _request_source(request, limits):
    if type(request) is not dict:
        raise _RequestError('request must be an object')
    if type(request.get('source')) is not str or type(request.get('input_mode')) is not str:
        raise _RequestError('source and input_mode must be strings')
    mode = request['input_mode']
    if mode not in ('ramp', 'zeros', 'checkerboard', 'custom'):
        raise _RequestError('input_mode must be ramp, zeros, checkerboard, or custom')
    expected = {'source', 'input_mode', 'inputs'} if mode == 'custom' else {'source', 'input_mode'}
    if set(request) != expected or (mode == 'custom' and type(request['inputs']) is not list):
        raise _RequestError('request has missing, unknown, or invalid input fields')
    text = request['source']
    if len(text) > limits.source_bytes:
        raise DiagnosticError('SOURCE_BYTES_LIMIT', Span(0, len(text)), 'source byte quota exceeded')
    try:
        return text.encode('utf-8')
    except UnicodeEncodeError as error:
        # Encoder positions count Unicode characters; diagnostics count UTF-8
        # bytes. The invalid character has no UTF-8 width, so mark its boundary.
        offset = len(text[:error.start].encode('utf-8'))
        raise DiagnosticError('INVALID_SOURCE_ENCODING', Span(offset, 0),
                              'source must encode as valid UTF-8') from None


def _inputs(request, kernel):
    count = (kernel.height + 1) * (kernel.width + 1)
    mode = request['input_mode']
    if mode == 'custom':
        if len(request['inputs']) != count:
            raise DiagnosticError('BOUNDARY_LENGTH', kernel.source_module.inputs[0].span,
                                  f'input requires exactly {count} scalars')
        return list(request['inputs'])
    if mode == 'ramp':
        return list(range(count))
    if mode == 'checkerboard':
        return [1023 * ((row + column) % 2)
                for row in range(kernel.height + 1) for column in range(kernel.width + 1)]
    return [0] * count


def _first_out_of_range(kernel, data):
    """Row-major index of the first out-of-range input, or None.

    Only a well-formed boundary qualifies: any wrong length, non-int or non-i32
    value leaves the request on the normal path, so malformed-boundary errors
    keep their precedence over the source precondition.
    """
    if (len(data) != (kernel.height + 1) * (kernel.width + 1)
            or any(type(v) is not int or not -2147483648 <= v <= 2147483647 for v in data)):
        return None
    lower, upper = kernel.input_interval
    return next((i for i, v in enumerate(data) if not lower <= v <= upper), None)


def _report(kernel, data):
    return dict(schema_version=1, status='no_eligible_plan', backend=_BACKEND,
        source_digest=kernel.source_digest,
        shape=dict(height=kernel.height, width=kernel.width,
                   input_height=kernel.height + 1, input_width=kernel.width + 1),
        objective=kernel.objective.value, workspace_cap=kernel.cap, selected=None,
        attempts=[], search=None,
        input=data, output=None, comparison=None, first_bad_index=None, diagnostic=None)


def _run(request):
    limits = Limits()
    source = _request_source(request, limits)
    module = parse_source(source, limits)
    kernel = admit_source(module)
    data = _inputs(request, kernel)
    initial = [-9] * (kernel.height * kernel.width)
    bad = _first_out_of_range(kernel, data)
    if bad is not None:
        # The input precondition is plan-independent, so refuse before planning:
        # no plan is selected or run. The independent source evaluation must
        # report the same failure, index, unchanged output and unchanged input.
        observed = ExecutionResult(ExecutionStatus.INPUT_PRECONDITION_FAILED, bad,
                                   tuple(initial), tuple(data))
        expected = evaluate_source(module, data, initial)
        if observed == expected:
            result = _report(kernel, data)
            result.update(status=observed.status.value, output=list(observed.output),
                          comparison=dict(matches=True, cells_compared=len(observed.output)),
                          first_bad_index=bad)
            return result
        # Disagreement: fall through so the full checked path decides.
    search = select_plan(kernel, limits, 100000, kernel.objective)
    attempts = []
    for attempt in search.attempts:
        checked = attempt.check
        attempts.append(dict(plan_id=attempt.candidate_id,
            eligible=checked.eligible if checked is not None else False,
            semantic_status=checked.semantic_status.value if checked is not None else 'unknown',
            constraint_status=checked.constraint_status.value if checked is not None else 'unknown',
            reason=attempt.reason,
            workspace_bytes=checked.workspace_bytes if checked is not None else None,
            multiplication_ops=checked.multiplication_ops if checked is not None else None))
    result = _report(kernel, data)
    result.update(attempts=attempts,
        search=dict(termination_reason=search.termination_reason.value, work_used=search.total_work_used))
    if search.selected_plan is None:
        return result
    checked = search.selected_check
    result['selected'] = dict(plan_id=search.selected_plan.plan_id,
        workspace_bytes=checked.workspace_bytes, multiplication_ops=checked.multiplication_ops,
        plan_digest=checked.plan_digest)
    observed = execute_plan(source, search.selected_plan_bytes, data, initial, limits)
    expected = evaluate_source(module, data, initial)
    if observed != expected:
        return _error('INDEPENDENT_COMPARISON_FAILED',
                      'Plan execution disagreed with the independent source evaluation.')
    result.update(status=observed.status.value, output=list(observed.output),
        # The displayed count names output cells; equality above also checks
        # every input cell, the boundary status, and first-failure position.
        comparison=dict(matches=True, cells_compared=len(observed.output)),
        first_bad_index=observed.first_bad_index)
    return result


def run_demo(request) -> dict:
    """Select, freshly check, execute, and independently compare a bounded demo."""
    try:
        return _run(request)
    except DiagnosticError as error:
        return _error(error.code, error.message, error.span.offset)
    except DecodeError as error:
        return _error(error.code, str(error))
    except _RequestError as error:
        return _error('INVALID_REQUEST', str(error))
    except Exception:
        # Unexpected implementation faults are never returned as successful
        # reports, and exception strings must not expose runtime filesystem data.
        return _error('INTERNAL_ERROR', 'The demo could not complete.')


def main() -> int:
    """Process exactly one bounded request; structured rejections still exit 0."""
    raw = sys.stdin.buffer.read(REQUEST_BYTES + 1)
    try:
        request = strict_json_loads(raw, max_bytes=REQUEST_BYTES, max_items=512, max_depth=4)
        result = run_demo(request)
    except DecodeError as error:
        result = _error(error.code, str(error))
    print(canonical_json(result).decode('utf-8'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
