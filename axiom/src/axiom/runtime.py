"""Freshly checked execution of finite Axiom plans on owned Python buffers.

This interpreter executes physical operations independently of the source-AST
evaluator. The plan's scratch metric remains its declared logical reservation;
only touched scratch cells are stored here, so a large unused reservation cannot
cause an unbounded allocation. Neither metric describes Python heap usage.
"""
from .checker import check_plan
from .codec import decode_plan
from .frontend import admit_source, parse_source
from .model import DiagnosticError, Limits, Span
from .reference import ExecutionResult, ExecutionStatus

_I32_MIN = -(2 ** 31)
_I32_MAX = 2 ** 31 - 1


def _snapshot(values, count, label, span):
    if type(values) not in (tuple, list):
        raise DiagnosticError('BOUNDARY_TYPE', span, f'{label} must be an owned list or tuple')
    if len(values) != count:
        raise DiagnosticError('BOUNDARY_LENGTH', span, f'{label} requires exactly {count} scalars')
    snapshot = tuple(values)
    for index, value in enumerate(snapshot):
        if type(value) is not int:
            raise DiagnosticError('BOUNDARY_TYPE', span, f'{label}[{index}] must be an exact integer')
        if not _I32_MIN <= value <= _I32_MAX:
            raise DiagnosticError('BOUNDARY_I32', span, f'{label}[{index}] must fit i32')
    return snapshot


def _checked_plan(source_bytes: bytes, plan_bytes: bytes, limits: Limits):
    """Fresh source/plan admission shared by interpreting and compiling."""
    if type(source_bytes) is not bytes or type(plan_bytes) is not bytes or type(limits) is not Limits:
        raise DiagnosticError('INVALID_EXECUTION_ARGUMENT', Span(0, 0),
                              'execution requires immutable source/plan bytes and Limits')
    module = parse_source(source_bytes, limits)
    kernel = admit_source(module)
    plan = decode_plan(plan_bytes, limits)
    checked = check_plan(kernel, plan, limits)
    if not checked.eligible:
        reason = 'CONSTRAINT_VIOLATED' if checked.reason == 'VALID' else checked.reason
        raise DiagnosticError(reason, module.span,
                              'plan did not pass fresh semantic and constraint checks')
    return kernel, plan, checked


def execute_plan(source_bytes: bytes, plan_bytes: bytes, data, initial_output,
                 limits: Limits = Limits()) -> ExecutionResult:
    """Re-admit and freshly check exact bytes before any plan interpretation.

    Caller buffers remain unchanged. Every input and initialized destination
    scalar is validated before the complete row-major precondition scan. Failed
    input preconditions return the original complete destination; no operation
    is executed. Saved checks and plan labels never grant execution authority.
    """
    kernel, plan, checked = _checked_plan(source_bytes, plan_bytes, limits)
    return _execute_finite(kernel, plan, data, initial_output)


def _execute_checked(owned, data, initial_output):
    from .compilation import _require_owned
    _require_owned(owned)
    return _execute_finite(owned.kernel, owned.plan, data, initial_output)


def _execute_finite(kernel, plan, data, initial_output):
    module = kernel.source_module

    if data is initial_output:
        raise DiagnosticError('BOUNDARY_ALIAS', module.span, 'input and output must be disjoint')
    inputs = _snapshot(data, (kernel.height + 1) * (kernel.width + 1),
                       'input', module.inputs[0].span)
    initial = _snapshot(initial_output, kernel.height * kernel.width,
                        'output', module.outputs[0].span)
    lower, upper = kernel.input_interval
    for index, value in enumerate(inputs):
        if not lower <= value <= upper:
            return ExecutionResult(ExecutionStatus.INPUT_PRECONDITION_FAILED, index, initial, inputs)

    values = []
    scratch = {}
    output = [None] * len(initial)
    for operation in plan.operations:
        opcode = operation.opcode
        if opcode == 'const':
            value = operation.value
        elif opcode == 'input_load':
            value = inputs[operation.index]
        elif opcode == 'add':
            value = values[operation.operands[0]] + values[operation.operands[1]]
        elif opcode == 'mul':
            value = values[operation.operands[0]] * values[operation.operands[1]]
        elif opcode == 'scratch_store':
            scratch[operation.index] = values[operation.operands[0]]
            continue
        elif opcode == 'scratch_load':
            if operation.index not in scratch:
                raise DiagnosticError('RUNTIME_INVALID_PLAN', module.span, 'uninitialized scratch read')
            value = scratch[operation.index]
        elif opcode == 'output_store':
            if output[operation.index] is not None:
                raise DiagnosticError('RUNTIME_INVALID_PLAN', module.span, 'duplicate output write')
            output[operation.index] = values[operation.operands[0]]
            continue
        else:
            raise DiagnosticError('RUNTIME_INVALID_PLAN', module.span, 'unsupported operation')
        if type(value) is not int or not _I32_MIN <= value <= _I32_MAX:
            raise DiagnosticError('RUNTIME_I32', module.span, 'physical operation does not fit exact i32')
        if operation.dst != len(values):
            raise DiagnosticError('RUNTIME_INVALID_PLAN', module.span, 'SSA definitions are not dense')
        values.append(value)
    if any(value is None for value in output):
        raise DiagnosticError('RUNTIME_INVALID_PLAN', module.span, 'incomplete output coverage')
    return ExecutionResult(ExecutionStatus.SUCCESS, None, tuple(output), inputs)
