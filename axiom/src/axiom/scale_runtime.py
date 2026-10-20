"""Checked Python execution of scale-v1 loop plans (reference speed, for testing).

Like runtime.execute_plan, every call re-proves the plan against fresh source
before touching data, preflights the whole input, and preserves the initial
output on rejection.
"""
from .model import DiagnosticError, Limits, Span
from .reference import ExecutionResult, ExecutionStatus, _boundary_values
from .scale_checker import check_loop_plan
from .frontend import admit_source, parse_source


def _value(expr, env, data):
    kind = expr[0]
    if kind == 'const':
        return expr[1]
    if kind == 'load':
        constant, terms = expr[1]
        return data[constant + sum(k * env[var] for var, k in terms)]
    if kind == 'add':
        return _value(expr[1], env, data) + _value(expr[2], env, data)
    if kind == 'mul':
        return _value(expr[1], env, data) * _value(expr[2], env, data)
    _, var, lower, upper, body = expr
    total = 0
    for term in range(lower, upper):
        env[var] = term
        total += _value(body, env, data)
    del env[var]
    return total


def execute_loop_plan(source: bytes, plan, data, initial_output, limits: Limits = Limits()) -> ExecutionResult:
    check = check_loop_plan(source, plan, limits)
    if not check.valid:
        raise DiagnosticError('PLAN_NOT_PROVED', Span(0, 0), f'{check.reason}: {check.detail}')
    kernel = admit_source(parse_source(source, limits))
    module = kernel.source_module
    inputs = _boundary_values(data, kernel.input_count, 'input', module.inputs[0].span)
    output = list(_boundary_values(initial_output, kernel.output_count, 'output', module.outputs[0].span))
    lower, upper = kernel.input_interval
    for index, value in enumerate(inputs):
        if not lower <= value <= upper:
            return ExecutionResult(ExecutionStatus.INPUT_PRECONDITION_FAILED, index, tuple(output), inputs)
    (stage,) = plan.stages
    (v0, h), (v1, w) = stage.loops
    env = {}
    for row in range(h):
        env[v0] = row
        for col in range(w):
            env[v1] = col
            constant, terms = stage.index
            output[constant + sum(k * env[var] for var, k in terms)] = _value(stage.value, env, inputs)
    return ExecutionResult(ExecutionStatus.SUCCESS, None, tuple(output), inputs)
