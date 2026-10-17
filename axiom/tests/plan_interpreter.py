"""Test-only numeric operation interpretation, independent of all compiler logic.

This is not a public unchecked execution entry. Callers in tests separately check
plans and obtain expected observations from the source-AST evaluator.
"""


def interpret_plan(plan, data, output_cells):
    values = []
    scratch = [None] * plan.scratch_capacity_cells
    output = [None] * output_cells
    for op in plan.operations:
        if op.opcode == 'const':
            result = op.value
        elif op.opcode == 'input_load':
            result = data[op.index]
        elif op.opcode in ('add', 'mul'):
            a, b = (values[index] for index in op.operands)
            result = a + b if op.opcode == 'add' else a * b
        elif op.opcode == 'scratch_store':
            scratch[op.index] = values[op.operands[0]]
            continue
        elif op.opcode == 'scratch_load':
            result = scratch[op.index]
            if result is None:
                raise ValueError('uninitialized scratch')
        elif op.opcode == 'output_store':
            if output[op.index] is not None:
                raise ValueError('output written twice')
            output[op.index] = values[op.operands[0]]
            continue
        else:
            raise ValueError('unknown operation')
        if type(result) is not int or not -(2**31) <= result < 2**31:
            raise ValueError('scalar is not exact i32')
        if op.dst != len(values):
            raise ValueError('SSA definitions are not dense')
        values.append(result)
    if any(value is None for value in output):
        raise ValueError('missing output')
    return tuple(output)
