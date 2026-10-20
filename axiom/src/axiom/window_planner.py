"""Candidate plans for two-stage window stencils (window-stencil-v1 kernels).

Three schedules, mirroring the canonical portfolio:
  inline-v1       recompute every producer value a consumer reads; no scratch.
  rows-v1         keep a rolling buffer of K producer rows, K = 1 + the largest
                  consumer row offset; each producer value is computed once.
  materialize-v1  compute the whole producer into scratch, then consume.

Plans are lowered directly from the retained source ASTs in their original
association, so the independent checker can prove them structurally. Within
one producer or consumer evaluation, structurally identical subterms share
one SSA value (for example both factors of (x+1)*(x+1)); sharing never
crosses evaluations, and it does not change any source value. These
generators supply candidates only; eligibility always comes from checking.
"""
from .model import (AdmittedKernel, BinaryExpression, GroupExpression, IntegerLiteral,
                    NameReference, ReadExpression, WINDOW_PLANNED_PROFILES)
from .codec import DecodeError
from .plan_format import Operation, Plan

WINDOW_PLAN_IDS = ('inline-v1', 'rows-v1', 'materialize-v1')


def _ungroup(node):
    while isinstance(node, GroupExpression):
        node = node.expression
    return node


def _index(node, env):
    node = _ungroup(node)
    if isinstance(node, IntegerLiteral):
        return node.value
    if isinstance(node, NameReference):
        return env[node.name]
    if isinstance(node, BinaryExpression) and node.operator == '+':
        return _index(node.left, env) + _index(node.right, env)
    raise ValueError('index outside the window family')


def consumer_rows(kernel):
    """K: rows of producer a single output row reads, from the retained AST."""
    output = kernel.source_module.outputs[0]
    env = {output.axes[0].name: 0, output.axes[1].name: 0}
    rows, pending = [], [kernel.source_expressions[1]]
    while pending:
        node = _ungroup(pending.pop())
        if isinstance(node, BinaryExpression):
            pending.extend((node.left, node.right))
        elif isinstance(node, ReadExpression):
            rows.append(_index(node.indices[0], env))
    return max(rows) + 1


def make_window_plan(kernel: AdmittedKernel, plan_id: str, *, max_operations: int | None = None) -> Plan:
    """With `max_operations`, stop as soon as the stream exceeds it (the same
    OPERATION_LIMIT validation would report), never building an oversized plan."""
    if type(kernel) is not AdmittedKernel or kernel.profile not in WINDOW_PLANNED_PROFILES:
        raise TypeError('expected an admitted window-stencil or reduce-v1 kernel')
    if type(plan_id) is not str or plan_id not in WINDOW_PLAN_IDS:
        raise ValueError('unsupported plan generator ID')
    module = kernel.source_module
    producer_decl, output_decl = module.producers[0], module.outputs[0]
    producer_expr, output_expr = kernel.source_expressions
    # Input base offsets in the shared buffer, in declaration order.
    bases, offset = {}, 0
    for declaration, (rows, cols) in zip(module.inputs, kernel.all_input_shapes):
        bases[declaration.name] = (offset, cols)
        offset += rows * cols
    pcols, prows = kernel.producer_cols, kernel.producer_rows
    operations = []
    next_dst = 0
    constants = {}

    def emit(opcode, origin, *, operands=(), index=None, value=None):
        nonlocal next_dst
        dst = None
        if opcode not in ('scratch_store', 'output_store'):
            dst = next_dst
            next_dst += 1
        if max_operations is not None and len(operations) >= max_operations:
            raise DecodeError('OPERATION_LIMIT', '$.operations', 'physical operation quota exceeded')
        operations.append(Operation(opcode, dst, operands, index, value, (origin.span.offset,)))
        return dst

    # Prologue: every distinct literal once, in first-appearance order of a
    # left-to-right walk of the producer then the output AST. Evaluations then
    # contain no constants, so the stream is expressible as a loop program.
    for expression in (producer_expr, output_expr):
        pending = [expression]
        while pending:
            node = _ungroup(pending.pop())
            if isinstance(node, IntegerLiteral):
                if node.value not in constants:
                    constants[node.value] = emit('const', node, value=node.value)
            elif isinstance(node, BinaryExpression):
                pending.extend((node.right, node.left))

    def lower(expression, env, read):
        """Post-order lowering; structurally identical subterms share one value."""
        memo = {}

        def visit(node):
            node = _ungroup(node)
            if isinstance(node, IntegerLiteral):
                key = ('const', node.value)
                if node.value not in constants:
                    constants[node.value] = emit('const', node, value=node.value)
                return key, constants[node.value]
            if isinstance(node, ReadExpression):
                row, col = (_index(i, env) for i in node.indices)
                key = ('read', node.name, row, col)
                if key not in memo:
                    memo[key] = read(node, row, col)
                return key, memo[key]
            if isinstance(node, BinaryExpression) and node.operator in ('+', '*'):
                left_key, left = visit(node.left)
                right_key, right = visit(node.right)
                key = (node.operator, left_key, right_key)
                if key not in memo:
                    memo[key] = emit('add' if node.operator == '+' else 'mul', node,
                                     operands=(left, right))
                return key, memo[key]
            raise ValueError('expression outside the window family')

        return visit(expression)[1]

    def produce(row, col):
        env = {producer_decl.axes[0].name: row, producer_decl.axes[1].name: col}

        def read_input(node, r, c):
            if node.name not in bases:
                raise ValueError('producer may only read the inputs')
            base, cols = bases[node.name]
            return emit('input_load', node, index=base + r * cols + c)
        return lower(producer_expr, env, read_input)

    def consume(row, col, read_producer):
        env = {output_decl.axes[0].name: row, output_decl.axes[1].name: col}

        def read(node, r, c):
            if node.name != producer_decl.name:
                raise ValueError('output may only read the producer')
            return read_producer(node, r, c)
        value = lower(output_expr, env, read)
        emit('output_store', output_expr, index=row * kernel.width + col, operands=(value,))

    if plan_id == 'inline-v1':
        capacity = 0
        for row in range(kernel.height):
            for col in range(kernel.width):
                consume(row, col, lambda node, r, c: produce(r, c))
    else:
        window = consumer_rows(kernel) if plan_id == 'rows-v1' else prows
        capacity = window * pcols
        slot = (lambda r: r % window) if plan_id == 'rows-v1' else (lambda r: r)

        def stage(row):
            for col in range(pcols):
                emit('scratch_store', producer_expr, index=slot(row) * pcols + col,
                     operands=(produce(row, col),))

        def load(node, r, c):
            return emit('scratch_load', node, index=slot(r) * pcols + c)

        staged = min(window, prows)
        for row in range(staged):
            stage(row)
        for row in range(kernel.height):
            for col in range(kernel.width):
                consume(row, col, load)
            # Rows row+1 .. row+window-1 stay intact; only row's slot is reused.
            if plan_id == 'rows-v1' and row + window < prows:
                stage(row + window)
    return Plan(1, kernel.semantic_digest, plan_id, capacity, tuple(operations))
