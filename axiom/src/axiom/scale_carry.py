"""carry-v1 emission and the ranking of checked scale-v1 candidates.

A carry-v1 plan (see scale_plan) has a producer stage and an output stage
whose producer reads are ('prod', i, j). Its meaning is the direct plan's:
out[r, c] is the output expression with every ('prod', i, j) replaced by the
producer expression at (r + i, c + j). The checker proves both stages against
the source. The producer value is a pure function of its position, so the
emitter may compute each producer cell once and reuse it.

The emitter keeps a ring of the last K producer rows (K = 1 + largest i) on
the stack. For a range of output rows [r0, r1) it computes producer rows
r0 .. r0 + K - 2 first, then before output row r computes row r + K - 1 into
slot (r + K - 1) mod K; rows r .. r + K - 1 are then all present. The checker
proved r + i < producer rows and c + j < producer columns for every read.
"""
from .scale_plan import BINARY_KINDS

# The ring lives on each worker's stack; larger producer rows keep direct-v1.
MAX_RING_CELLS = 32768


def c_types(kernel):
    """C types of values and of output cells: int64_t once any equation is i64.

    The checker proves every node fits its own equation's type, so computing
    an i32 node in int64_t gives the same exact value.
    """
    value = 'int64_t' if kernel.wide else 'int32_t'
    return value, 'int64_t' if kernel.output_type == 'i64' else 'int32_t'


def value_bytes(kernel):
    return 8 if kernel.wide else 4


def _muls(expr):
    """Multiplications evaluated per value of `expr` (sum ranges multiplied out)."""
    kind = expr[0]
    if kind in ('const', 'load', 'prod'):
        return 0
    if kind in BINARY_KINDS:
        return (kind == 'mul') + _muls(expr[1]) + _muls(expr[2])
    return (expr[3] - expr[2]) * _muls(expr[4])


def _ops(expr):
    kind = expr[0]
    if kind in ('const', 'load', 'prod'):
        return 1
    if kind in BINARY_KINDS:
        return 1 + _ops(expr[1]) + _ops(expr[2])
    return (expr[3] - expr[2]) * (1 + _ops(expr[4]))


def window_rows(expr):
    """K: 1 + the largest row offset i of any ('prod', i, j)."""
    kind = expr[0]
    if kind == 'prod':
        return expr[1] + 1
    if kind in BINARY_KINDS:
        return max(window_rows(expr[1]), window_rows(expr[2]))
    if kind == 'sum':
        return window_rows(expr[4])
    return 0


def plan_costs(plan, kernel):
    """(multiplications per output cell, operations per output cell, workspace bytes)."""
    cells = kernel.height * kernel.width
    output = plan.stages[-1].value
    if len(plan.stages) == 1:
        return _muls(output), _ops(output), 0
    produce = plan.stages[0].value
    prows, pcols = kernel.producer_shape
    share = prows * pcols / cells
    workspace = value_bytes(kernel) * window_rows(output) * pcols
    return _muls(produce) * share + _muls(output), _ops(produce) * share + _ops(output), workspace


def carry_eligible(plan, kernel):
    """The emitter supports this carry plan (ring on the stack, within any cap)."""
    if len(plan.stages) != 2:
        return True
    k = window_rows(plan.stages[-1].value)
    if k < 1 or k * kernel.producer_shape[1] > MAX_RING_CELLS:
        return False
    return kernel.cap is None or value_bytes(kernel) * k * kernel.producer_shape[1] <= kernel.cap


def rank_key(plan, kernel, order):
    """Ranking by the program's objective, then the other costs, then portfolio order."""
    muls, ops, workspace = plan_costs(plan, kernel)
    if kernel.objective.value == 'plan_workspace_bytes':
        return (workspace, muls, ops, order)
    return (muls, ops, workspace, order)


def carry_rows_c(plan, kernel, lower):
    """C for `static void beryl_rows(input, output, r0, r1)` of a checked carry plan.

    `lower(expr, statements, counter, prod)` lowers a plan expression; `prod`
    formats a ('prod', i, j) leaf.
    """
    produce, stage = plan.stages
    value, out = c_types(kernel)
    (u0, prows), (u1, pcols) = produce.loops
    (v0, _), (v1, w) = stage.loops
    k = window_rows(stage.value)
    counter = iter(range(1 << 30))
    p_statements = []
    p_value = lower(produce.value, p_statements, counter, None)
    p_body = '\n'.join('        ' + line for line in p_statements)
    offsets = sorted({i for i in range(k) if _uses_row(stage.value, i)})
    o_statements = []
    o_value = lower(stage.value, o_statements, counter, lambda i, j: f'ax_row{i}[{v1} + {j}]')
    o_body = '\n'.join('            ' + line for line in o_statements)
    rows = '\n'.join(f'        const {value} *ax_row{i} = ring + (({v0} + {i}) % {k}) * {pcols};'
                     for i in offsets)
    return (f'\n/* Producer row {u0} into dst (carry-v1). */\n'
            f'static void beryl_produce_row(const int32_t *restrict input, {value} *restrict dst, int32_t {u0}) {{\n'
            f'    for (int32_t {u1} = 0; {u1} < {pcols}; ++{u1}) {{\n'
            f'{p_body}\n'
            f'        dst[{u1}] = {p_value};\n'
            '    }\n'
            '}\n'
            f'\n/* Output rows [r0, r1), keeping the last {k} producer rows in a ring. */\n'
            f'static void beryl_rows(const int32_t *restrict input, {out} *restrict output,\n'
            '                       int64_t r0, int64_t r1) {\n'
            f'    {value} ring[{k} * {pcols}];\n'
            f'    for (int32_t ax_p = (int32_t)r0; ax_p < (int32_t)r0 + {k - 1}; ++ax_p)\n'
            f'        beryl_produce_row(input, ring + (ax_p % {k}) * {pcols}, ax_p);\n'
            f'    for (int32_t {v0} = (int32_t)r0; {v0} < (int32_t)r1; ++{v0}) {{\n'
            f'        beryl_produce_row(input, ring + (({v0} + {k - 1}) % {k}) * {pcols}, {v0} + {k - 1});\n'
            f'{rows}\n'
            f'        {out} *restrict ax_out = output + (int64_t){w} * {v0};\n'
            f'        for (int32_t {v1} = 0; {v1} < {w}; ++{v1}) {{\n'
            f'{o_body}\n'
            f'            ax_out[{v1}] = {o_value};\n'
            '        }\n'
            '    }\n'
            '}\n')


def _uses_row(expr, i):
    kind = expr[0]
    if kind == 'prod':
        return expr[1] == i
    if kind in BINARY_KINDS:
        return _uses_row(expr[1], i) or _uses_row(expr[2], i)
    if kind == 'sum':
        return _uses_row(expr[4], i)
    return False
