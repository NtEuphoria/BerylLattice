"""Bounded presentation requests over the existing Axiom v1 implementation.

The fixed worker reads one JSON request from stdin and emits one JSON response.
It accepts neither commands nor filesystem paths. Successful observations are
demo reports, not native execution or scalable-oracle qualification receipts.
"""
import base64
from contextlib import nullcontext
from dataclasses import dataclass
import sys

from .codec import DecodeError, canonical_json, strict_json_loads
from .frontend import admit_source, parse_source
from .model import DiagnosticError, Limits, Span
from .reference import ExecutionResult, ExecutionStatus, evaluate_source
from .runtime import _snapshot, execute_plan
from .selection import select_plan
from .source_compilation import compile_wasm_source

REQUEST_BYTES = 131072
_BACKEND = 'checked-plan-interpreter-v1'
_COMPILED_BACKEND = 'checked-plan-wasm-v2'
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


@dataclass(frozen=True, slots=True)
class _PreparedDemo:
    """Privately owned authority, never reconstructed from request records."""
    source: bytes
    module: object
    kernel: object
    search: object
    compilation: object


_active_preparation = None


_CONV_SOURCE = '''module blur;
shape H = 6;
shape W = 8;
input image: i32[H+2,W+2] in 0..=1023;
let rows[r in 0..H+2,c in 0..W] =
  (image[r,c]+2*image[r,c+1])+image[r,c+2];
output result[r in 0..H,c in 0..W] =
  (rows[r,c]+2*rows[r+1,c])+rows[r+2,c];
require plan_workspace_bytes <= 128;
prefer multiplication_ops;
'''
_LAPLACE_SOURCE = '''module edges;
shape H = 6;
shape W = 8;
input image: i32[H+2,W+2] in 0..=1023;
let p[r in 0..H+2,c in 0..W+2] = image[r,c];
output result[r in 0..H,c in 0..W] =
  4*p[r+1,c+1] - p[r,c+1] - p[r+2,c+1] - p[r+1,c] - p[r+1,c+2];
prefer multiplication_ops;
'''


def get_examples() -> dict:
    """Return fresh, complete source examples without accessing the filesystem."""
    definitions = (
        ('balanced', 'Reuse two rows', 'Reduce multiplication with a 64-byte plan scratch limit.',
         _SOURCE.format(cap=64, objective='multiplication_ops')),
        ('no-scratch', 'No plan scratch', 'Recompute producer values with a zero-byte scratch limit.',
         _SOURCE.format(cap=0, objective='multiplication_ops')),
        ('small-memory', 'Prefer less scratch', 'Rank scratch first, even when more scratch is permitted.',
         _SOURCE.format(cap=64, objective='plan_workspace_bytes')),
        ('separable-blur', 'Separable 3x3 blur', 'A two-stage window stencil: row sums, then a column sum of row sums.',
         _CONV_SOURCE),
        ('laplacian', 'Edge detector', 'A 5-point Laplacian written with subtraction.', _LAPLACE_SOURCE),
    )
    return {'examples': [dict(id=identifier, title=title, description=description, source=source)
                         for identifier, title, description, source in definitions]}


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
    count = kernel.input_count
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
                for row in range(kernel.input_rows) for column in range(kernel.input_cols)]
    return [0] * count


def _report(kernel, search, data, backend):
    """Build a fresh presentation record without exposing retained state."""
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
    result = dict(schema_version=1, status='no_eligible_plan', backend=backend,
        source_digest=kernel.source_digest,
        shape=dict(height=kernel.height, width=kernel.width,
                   input_height=kernel.input_rows, input_width=kernel.input_cols),
        objective=kernel.objective.value, workspace_cap=kernel.cap, selected=None,
        attempts=attempts,
        search=dict(termination_reason=search.termination_reason.value, work_used=search.total_work_used),
        input=data, output=None, comparison=None, first_bad_index=None, diagnostic=None)
    if search.selected_plan is not None:
        checked = search.selected_check
        result['selected'] = dict(plan_id=search.selected_plan.plan_id,
            workspace_bytes=checked.workspace_bytes, multiplication_ops=checked.multiplication_ops,
            plan_digest=checked.plan_digest)
    return result


def _compiled_report(compilation, data):
    """Report exact structural costs separately from semantic proof states."""
    kernel, search, artifact = compilation.kernel, compilation.search, compilation.artifact
    result = _report(kernel, search, data, _COMPILED_BACKEND)
    result['schema_version'] = 2
    for record, attempt in zip(result['attempts'], search.attempts):
        record.update(state=attempt.state.value,
            eligible=None if attempt.check is None else attempt.check.eligible,
            multiplication_ops=attempt.multiplication_ops,
            workspace_bytes=attempt.workspace_bytes, operation_count=attempt.operation_count)
        if attempt.state.value == 'constraint_rejected':
            record['constraint_status'] = 'violated'
    result['search'].update(report_version=search.report_version, policy_id=search.policy_id,
        policy_digest=search.policy_digest, portfolio_optimal=search.portfolio_optimal)
    result['lowering'] = None if artifact is None else dict(
        codegen_version=artifact.codegen_version, hint_digest=artifact.hint_digest,
        loop_version=artifact.loop_version, local_count=artifact.local_count,
        module_digest=artifact.module_digest, hint_failure=compilation.hint_failure)
    return result


def _compared_report(result, observed, expected):
    if observed != expected:
        return _error('INDEPENDENT_COMPARISON_FAILED',
                      'Plan execution disagreed with the independent source evaluation.')
    result.update(status=observed.status.value, output=list(observed.output),
        # Equality checks input, boundary status and first-failure position too.
        comparison=dict(matches=True, cells_compared=len(observed.output)),
        first_bad_index=observed.first_bad_index)
    return result


def _first_out_of_range(kernel, data):
    """Row-major index of the first out-of-range input, or None.

    Only a well-formed boundary qualifies: any wrong length, non-int or non-i32
    value leaves the request on the normal path, so malformed-boundary errors
    keep their precedence over the source precondition.
    """
    if (len(data) != kernel.input_count
            or any(type(v) is not int or not -2147483648 <= v <= 2147483647 for v in data)):
        return None
    lower, upper = kernel.input_interval
    return next((i for i, v in enumerate(data) if not lower <= v <= upper), None)


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
            result = dict(schema_version=1, status='no_eligible_plan', backend=_BACKEND,
                source_digest=kernel.source_digest,
                shape=dict(height=kernel.height, width=kernel.width,
                           input_height=kernel.input_rows, input_width=kernel.input_cols),
                objective=kernel.objective.value, workspace_cap=kernel.cap, selected=None,
                attempts=[], search=None, input=data, output=None, comparison=None,
                first_bad_index=None, diagnostic=None)
            return _compared_report(result, observed, expected)
        # Disagreement: fall through so the full checked path decides.
    search = select_plan(kernel, limits, 100000, kernel.objective)
    result = _report(kernel, search, data, _BACKEND)
    if search.selected_plan is None:
        return result
    observed = execute_plan(source, search.selected_plan_bytes, data, initial, limits)
    expected = evaluate_source(module, data, initial)
    return _compared_report(result, observed, expected)


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


def compiled_request_source(request: dict) -> dict:
    """Validate the request envelope before choosing a compiled preparation."""
    try:
        _request_source(request, Limits())
        return dict(status='valid', source=request['source'])
    except DiagnosticError as error:
        return _error(error.code, error.message, error.span.offset)
    except DecodeError as error:
        return _error(error.code, str(error))
    except _RequestError as error:
        return _error('INVALID_REQUEST', str(error))
    except Exception:
        return _error('INTERNAL_ERROR', 'The demo could not complete.')


def prepare_compiled_demo(source: str, *, trace=None) -> dict:
    """Replace the single source preparation after fresh checking and compilation.

    Only this module's retained original AST and exact admitted source bytes
    authorize later comparisons. Public metadata never acts as a receipt.
    Every attempt clears the previous preparation, including failed attempts.
    """
    with (nullcontext() if trace is None else trace.phase('total_fresh_source_preparation')):
        return _prepare_compiled_demo(source, trace)


def _prepare_compiled_demo(source, trace):
    global _active_preparation
    _active_preparation = None
    try:
        limits = Limits()
        source_bytes = _request_source(dict(source=source, input_mode='ramp'), limits)
        compilation = compile_wasm_source(source_bytes, limits, trace=trace)
        kernel, search, artifact = compilation.kernel, compilation.search, compilation.artifact
        result = _compiled_report(compilation, [])
        if artifact is None:
            return result
        result.update(status='prepared',
            wasm_base64=base64.b64encode(artifact.module_bytes).decode('ascii'),
            memory_bytes=artifact.memory_bytes, input_offset=artifact.input_offset,
            output_offset=artifact.output_offset, input_count=artifact.input_count,
            output_count=artifact.output_count, module_digest=artifact.module_digest,
            source_digest=artifact.source_digest, plan_digest=artifact.plan_digest)
        _active_preparation = _PreparedDemo(source_bytes, kernel.source_module, kernel, search, compilation)
        return result
    except DiagnosticError as error:
        return _error(error.code, error.message, error.span.offset)
    except DecodeError as error:
        return _error(error.code, str(error))
    except _RequestError as error:
        return _error('INVALID_REQUEST', str(error))
    except Exception:
        return _error('INTERNAL_ERROR', 'The demo could not complete.')


def _compiled_boundaries(request):
    source = _request_source(request, Limits())
    prepared = _active_preparation
    if prepared is None:
        raise DiagnosticError('NOT_PREPARED', Span(0, 0),
                              'Prepare the source before compiled execution.')
    if source != prepared.source:
        raise DiagnosticError('PREPARED_SOURCE_MISMATCH', Span(0, 0),
                              'The request source does not match the active preparation.')
    kernel, module = prepared.kernel, prepared.module
    data = _snapshot(_inputs(request, kernel), kernel.input_count,
                     'input', module.inputs[0].span)
    initial = _snapshot([-9] * (kernel.height * kernel.width), kernel.height * kernel.width,
                        'output', module.outputs[0].span)
    return prepared, data, initial


def compiled_request_inputs(request: dict) -> dict:
    """Validate exact Python scalars before any JavaScript typed-array coercion."""
    try:
        _, data, initial = _compiled_boundaries(request)
        return dict(status='ready', input=list(data), initial_output=list(initial))
    except DiagnosticError as error:
        return _error(error.code, error.message, error.span.offset)
    except DecodeError as error:
        return _error(error.code, str(error))
    except _RequestError as error:
        return _error('INVALID_REQUEST', str(error))
    except Exception:
        return _error('INTERNAL_ERROR', 'The demo could not complete.')


def finish_compiled_demo(request: dict, observation: dict) -> dict:
    """Compare every compiled observation with fresh retained-AST evaluation."""
    try:
        prepared, data, initial = _compiled_boundaries(request)
        if (type(observation) is not dict or set(observation) != {'status', 'input', 'output'}
                or type(observation['input']) is not list or type(observation['output']) is not list):
            raise _RequestError('observation requires exactly status, input, and output fields')
        module = prepared.module
        status = _snapshot([observation['status']], 1, 'status', module.span)[0]
        input_after = _snapshot(observation['input'], len(data), 'input', module.inputs[0].span)
        output = _snapshot(observation['output'], len(initial), 'output', module.outputs[0].span)
        observed = ExecutionResult(
            ExecutionStatus.SUCCESS if status == 0 else ExecutionStatus.INPUT_PRECONDITION_FAILED,
            None if status == 0 else status - 1, output, input_after)
        expected = evaluate_source(module, data, initial)
        result = _compiled_report(prepared.compilation, list(data))
        return _compared_report(result, observed, expected)
    except DiagnosticError as error:
        return _error(error.code, error.message, error.span.offset)
    except DecodeError as error:
        return _error(error.code, str(error))
    except _RequestError as error:
        return _error('INVALID_REQUEST', str(error))
    except Exception:
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
