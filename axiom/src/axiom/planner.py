"""Expand exactly three fixed-shape schedules into explicit physical operations.

These constructors supply candidates, never eligibility or a correctness proof.
Origins identify UTF-8 byte offsets in the admitted, retained scalar ASTs.
"""
from .model import AdmittedKernel, GroupExpression, WINDOW_PROFILE
from .plan_format import Operation, Plan

PLAN_IDS = ('inline-v1', 'rows2-v1', 'materialize-v1')


def plan_ids(kernel: AdmittedKernel) -> tuple[str, ...]:
    """The candidate portfolio for an admitted kernel, in ranking tie-break order."""
    if isinstance(kernel, AdmittedKernel) and kernel.profile == WINDOW_PROFILE:
        from .window_planner import WINDOW_PLAN_IDS
        return WINDOW_PLAN_IDS
    return PLAN_IDS


def _ungroup(expression):
    while isinstance(expression, GroupExpression):
        expression = expression.expression
    return expression


def make_plan(kernel: AdmittedKernel, plan_id: str) -> Plan:
    """Specialize an admitted stencil, retaining its exact addition grouping."""
    if not isinstance(kernel, AdmittedKernel):
        raise TypeError('kernel must be an AdmittedKernel')
    if kernel.profile == WINDOW_PROFILE:
        from .window_planner import make_window_plan
        return make_window_plan(kernel, plan_id)
    if type(plan_id) is not str or plan_id not in PLAN_IDS:
        raise ValueError('unsupported plan generator ID')
    h, w = kernel.height, kernel.width
    stride = w + 1
    producer, consumer = (_ungroup(e) for e in kernel.source_expressions)
    increment = _ungroup(producer.left)
    literal = _ungroup(increment.right)
    input_read = _ungroup(increment.left)
    middle = _ungroup(consumer.left)
    first = _ungroup(middle.left)
    operations = []
    next_dst = 0

    def emit(opcode, origin, *, operands=(), index=None, value=None):
        nonlocal next_dst
        dst = None
        if opcode not in ('scratch_store', 'output_store'):
            dst = next_dst
            next_dst += 1
        operations.append(Operation(opcode, dst, operands, index, value,
                                    (origin.span.offset,)))
        return dst

    one = emit('const', literal, value=1)

    def produce(row, column):
        loaded = emit('input_load', input_read, index=row*stride+column)
        increased = emit('add', increment, operands=(loaded, one))
        return emit('mul', producer, operands=(increased, increased))

    def consume(row, column, values):
        a, b, c, d = values
        total = emit('add', first, operands=(a, b))
        total = emit('add', middle, operands=(total, c))
        total = emit('add', consumer, operands=(total, d))
        emit('output_store', consumer, index=row*w+column, operands=(total,))

    if plan_id == 'inline-v1':
        capacity = 0
        for row in range(h):
            for column in range(w):
                consume(row, column,
                        (produce(row, column), produce(row, column+1),
                         produce(row+1, column), produce(row+1, column+1)))
    else:
        capacity = 2*stride if plan_id == 'rows2-v1' else (h+1)*stride

        def stage(row):
            slot_row = row % 2 if plan_id == 'rows2-v1' else row
            for column in range(stride):
                value = produce(row, column)
                emit('scratch_store', producer, index=slot_row*stride+column,
                     operands=(value,))

        for row in range(2 if plan_id == 'rows2-v1' else h+1):
            stage(row)
        for row in range(h):
            upper = (row % 2 if plan_id == 'rows2-v1' else row)*stride
            lower = ((row+1) % 2 if plan_id == 'rows2-v1' else row+1)*stride
            for column in range(w):
                values = tuple(emit('scratch_load', consumer, index=index)
                               for index in (upper+column, upper+column+1,
                                             lower+column, lower+column+1))
                consume(row, column, values)
            # Both rows remain intact until every consuming column has finished.
            if plan_id == 'rows2-v1' and row+2 <= h:
                stage(row+2)
    return Plan(1, kernel.semantic_digest, plan_id, capacity, tuple(operations))
