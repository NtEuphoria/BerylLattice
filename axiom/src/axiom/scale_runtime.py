"""Checked Python execution of scale-v1 loop plans (reference speed, for testing).

Like runtime.execute_plan, every call re-proves the plan against fresh source
before touching data, preflights the whole input, and preserves the initial
output on rejection.
"""
from .model import DiagnosticError, Limits, Span
from .reference import ExecutionResult, ExecutionStatus, _boundary_values, first_bad_input, input_storage
from .scale_checker import check_loop_plan
from .frontend import admit_source, parse_source


def _value(expr, env, data, produce=None):
    kind = expr[0]
    if kind == 'prod':
        # carry-v1: the producer stage evaluated at (r + i, c + j).
        stage, (row_var, col_var), (u0, u1) = produce
        return _value(stage.value, {u0: env[row_var] + expr[1], u1: env[col_var] + expr[2]}, data)
    if kind == 'const':
        return expr[1]
    if kind == 'load':
        constant, terms = expr[1]
        return data[constant + sum(k * env[var] for var, k in terms)]
    if kind == 'add':
        return _value(expr[1], env, data, produce) + _value(expr[2], env, data, produce)
    if kind == 'mul':
        return _value(expr[1], env, data, produce) * _value(expr[2], env, data, produce)
    if kind == 'min':
        return min(_value(expr[1], env, data, produce), _value(expr[2], env, data, produce))
    if kind == 'max':
        return max(_value(expr[1], env, data, produce), _value(expr[2], env, data, produce))
    if kind == 'shr':
        return _value(expr[1], env, data, produce) >> _value(expr[2], env, data, produce)
    if kind == 'shr_round':
        value, k = _value(expr[1], env, data, produce), _value(expr[2], env, data, produce)
        return (value >> k) + ((value >> (k - 1)) & 1)
    _, var, lower, upper, body = expr
    total = 0
    for term in range(lower, upper):
        env[var] = term
        total += _value(body, env, data, produce)
    del env[var]
    return total


def execute_loop_plan(source: bytes, plan, data, initial_output, limits: Limits = Limits()) -> ExecutionResult:
    check = check_loop_plan(source, plan, limits)
    if not check.valid:
        raise DiagnosticError('PLAN_NOT_PROVED', Span(0, 0), f'{check.reason}: {check.detail}')
    kernel = admit_source(parse_source(source, limits))
    module = kernel.source_module
    inputs = _boundary_values(data, kernel.input_count, 'input', module.inputs[0].span, input_storage(kernel))
    output = list(_boundary_values(initial_output, kernel.output_count, 'output', module.outputs[0].span,
                                   kernel.output_type))
    bad = first_bad_input(kernel, inputs)
    if bad is not None:
        return ExecutionResult(ExecutionStatus.INPUT_PRECONDITION_FAILED, bad, tuple(output), inputs)
    stage = plan.stages[-1]
    (v0, h), (v1, w) = stage.loops
    produce = None
    if len(plan.stages) == 2:
        first = plan.stages[0]
        produce = (first, (v0, v1), (first.loops[0][0], first.loops[1][0]))
    env = {}
    for row in range(h):
        env[v0] = row
        for col in range(w):
            env[v1] = col
            constant, terms = stage.index
            output[constant + sum(k * env[var] for var, k in terms)] = _value(stage.value, env, inputs, produce)
    return ExecutionResult(ExecutionStatus.SUCCESS, None, tuple(output), inputs)
