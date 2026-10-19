"""Untrusted compact loop hints for window-stencil plans (window-stencil-v1).

Each hint mirrors window_planner's operation order exactly, with row and
column positions kept symbolic. A hint grants nothing: compilation expands it
and requires an exact match with the freshly checked finite plan (opcode,
destination, operands, index and value of every operation); any difference
falls back to finite emission. rows-v1 unrolls its outer row loop because the
v1 index format has only parity (% 2), not % K, for rolling slots.
"""
from .bounded_loop_model import FORMAT_VERSION, IndexExpr, IndexTerm, Loop, LoopProgram, Primitive
from .model import BinaryExpression, GroupExpression, IntegerLiteral, NameReference, ReadExpression, WINDOW_PROFILE
from .window_planner import WINDOW_PLAN_IDS, consumer_rows


def _ungroup(node):
    while isinstance(node, GroupExpression):
        node = node.expression
    return node


def _position(node, env):
    """(variable or None, offset) for an index of the form axis + literal."""
    node = _ungroup(node)
    if isinstance(node, IntegerLiteral):
        return None, node.value
    if isinstance(node, NameReference):
        return env[node.name]
    if isinstance(node, BinaryExpression) and node.operator == '+':
        (lv, lo), (rv, ro) = _position(node.left, env), _position(node.right, env)
        if lv is not None and rv is not None:
            raise ValueError('index uses two loop variables')
        return lv if lv is not None else rv, lo + ro
    raise ValueError('index outside the window family')


def _index(rows, cols, stride, base=0):
    """IndexExpr for base + rows*stride + cols, each a (variable|None, offset) pair."""
    constant, terms = base, []
    for (variable, offset), coefficient in ((rows, stride), (cols, 1)):
        if variable is None:
            constant += coefficient * offset
        else:
            terms.append(IndexTerm(coefficient, variable, offset))
    return IndexExpr(constant, tuple(terms))


def make_window_loop_program(kernel, plan_id):
    if kernel.profile != WINDOW_PROFILE or plan_id not in WINDOW_PLAN_IDS:
        raise ValueError('expected a window-stencil kernel and portfolio schedule')
    module = kernel.source_module
    producer_decl, output_decl = module.producers[0], module.outputs[0]
    producer_expr, output_expr = kernel.source_expressions
    pcols, prows = kernel.producer_cols, kernel.producer_rows
    serial = 0
    constants = {}

    def name():
        nonlocal serial
        serial += 1
        return f'v{serial}'

    def prim(opcode, origin, *, operands=(), index=None, value=None, store=False):
        dst = None if store else name()
        return dst, Primitive(opcode, dst, operands, index, value, (origin.span.offset,))

    prologue = []
    for expression in (producer_expr, output_expr):
        pending = [expression]
        while pending:
            node = _ungroup(pending.pop())
            if isinstance(node, IntegerLiteral):
                if node.value not in constants:
                    dst, p = prim('const', node, value=node.value)
                    constants[node.value] = dst
                    prologue.append(p)
            elif isinstance(node, BinaryExpression):
                pending.extend((node.right, node.left))

    def lower(expression, env, read, out):
        memo = {}

        def visit(node):
            node = _ungroup(node)
            if isinstance(node, IntegerLiteral):
                return ('const', node.value), constants[node.value]
            if isinstance(node, ReadExpression):
                row, col = (_position(i, env) for i in node.indices)
                key = ('read', node.name, row, col)
                if key not in memo:
                    memo[key] = read(node, row, col, out)
                return key, memo[key]
            if isinstance(node, BinaryExpression) and node.operator in ('+', '*'):
                left_key, left = visit(node.left)
                right_key, right = visit(node.right)
                key = (node.operator, left_key, right_key)
                if key not in memo:
                    dst, p = prim('add' if node.operator == '+' else 'mul', node, operands=(left, right))
                    out.append(p)
                    memo[key] = dst
                return key, memo[key]
            raise ValueError('expression outside the window family')
        return visit(expression)[1]

    def produce(row, col, out):
        env = {producer_decl.axes[0].name: row, producer_decl.axes[1].name: col}

        def read_input(node, r, c, out):
            dst, p = prim('input_load', node, index=_index(r, c, kernel.input_cols))
            out.append(p)
            return dst
        return lower(producer_expr, env, read_input, out)

    def consume(row, col, read_producer, out):
        env = {output_decl.axes[0].name: row, output_decl.axes[1].name: col}
        value = lower(output_expr, env, read_producer, out)
        out.append(prim('output_store', output_expr, operands=(value,),
                        index=_index(row, col, kernel.width), store=True)[1])

    def shift(position, offset):
        return position[0], position[1] + offset

    body = list(prologue)
    if plan_id == 'inline-v1':
        capacity = 0
        inner = []
        consume(('r', 0), ('c', 0), lambda node, r, c, out: produce(r, c, out), inner)
        body.append(Loop('r', 0, kernel.height, (Loop('c', 0, kernel.width, tuple(inner)),)))
    elif plan_id == 'materialize-v1':
        capacity = prows * pcols
        stage = []
        value = produce(('s', 0), ('t', 0), stage)
        stage.append(prim('scratch_store', producer_expr, operands=(value,),
                          index=_index(('s', 0), ('t', 0), pcols), store=True)[1])
        body.append(Loop('s', 0, prows, (Loop('t', 0, pcols, tuple(stage)),)))

        def load(node, r, c, out):
            dst, p = prim('scratch_load', node, index=_index(r, c, pcols))
            out.append(p)
            return dst
        inner = []
        consume(('r', 0), ('c', 0), load, inner)
        body.append(Loop('r', 0, kernel.height, (Loop('c', 0, kernel.width, tuple(inner)),)))
    else:
        window = consumer_rows(kernel)
        capacity = window * pcols

        def stage_row(row):
            stage = []
            value = produce((None, row), ('t', 0), stage)
            stage.append(prim('scratch_store', producer_expr, operands=(value,),
                              index=_index((None, 0), ('t', 0), pcols, base=(row % window) * pcols), store=True)[1])
            return Loop('t', 0, pcols, tuple(stage))

        for row in range(min(window, prows)):
            body.append(stage_row(row))
        for row in range(kernel.height):
            def load(node, r, c, out, row=row):
                # r is (None, row + i): a fixed producer row, so its slot is a constant.
                slot = (r[1] % window) * pcols
                dst, p = prim('scratch_load', node, index=_index((None, 0), c, pcols, base=slot))
                out.append(p)
                return dst
            inner = []
            consume((None, row), ('c', 0), load, inner)
            body.append(Loop('c', 0, kernel.width, tuple(inner)))
            if row + window < prows:
                body.append(stage_row(row + window))
    return LoopProgram(FORMAT_VERSION, kernel.source_digest, kernel.semantic_digest,
                       kernel.height, kernel.width, capacity, tuple(body), plan_id)
