"""reduce-v1: reductions, gathers and a second input, within 256 input cells.

    input x: i32[d0, d1] in 0..=1023;            one or two inputs; each dimension
    input y: i32[d2, d3] in 0..=1023;            a literal, a shape or shape + k
    let p[r in 0..H+pa, c in 0..W+pb] = f(...);  input reads indexed by an axis,
                                                 axis + k or a literal
    output o[r in 0..H, c in 0..W] = g(p[r+i, c+j]);

`sum(k in L..U: e)` means exactly a balanced `+` tree of the terms
e[k := L] .. e[k := U-1] in these families (see docs/superpowers/specs/2026-10-19-reductions-design.md).
Recognition works on the normalized profile, after the canonical stencil and
the window family, which keep their own admission and identities. Bounds of
every read were already proved by frontend validation.
"""
import dataclasses
import hashlib
import json

from .model import (AdmittedKernel, BinaryExpression, DiagnosticError, GroupExpression,
                    IntegerLiteral, NameReference, ReadExpression, REDUCE_PROFILE, SumExpression,
                    REDUCE_SEMANTICS_VERSION, Span)

MAX_INPUT_CELLS = 256
MAX_TERMS = 256          # small families: expanded into a balanced tree
MAX_SYMBOLIC_TERMS = 2 ** 31 - 1  # scale-v1: an exact sum, kept as a loop
MAX_OFFSET = 8


def parse_sum(parser, keyword, nesting):
    """Parse `sum(k in L..U: e)` after `keyword` into a SumExpression.

    Admission expands sums of at most MAX_TERMS terms into their balanced `+`
    trees for the small families (expand_small_sums); scale-v1 keeps every
    sum as a loop.
    """
    parser.take('(')
    name = parser.identifier()
    if name.text in parser.reserved or name.text in parser.sum_names:
        raise DiagnosticError('DUPLICATE_NAME', name.span,
                              f'`{name.text}` is already a shape, axis or sum variable')
    parser.take('in')
    lower = parser.integer()
    parser.take('..')
    upper = parser.integer()
    if not 1 <= upper.value - lower.value <= MAX_SYMBOLIC_TERMS:
        raise DiagnosticError('INVALID_RANGE', Span(lower.span.offset, upper.span.offset
                              + upper.span.length - lower.span.offset),
                              f'a sum needs between 1 and {MAX_SYMBOLIC_TERMS} terms')
    parser.take(':')
    parser.sum_names.append(name.text)
    body = parser.expression(True, nesting + 1)
    parser.sum_names.pop()
    parser.take(')')
    span = parser.span_from(keyword.span)
    return parser.node(SumExpression(name.text, lower.value, upper.value, body, span, name.span), (body,))


class _TooLarge(Exception):
    pass


def _has_sum(node):
    pending = [node]
    while pending:
        node = pending.pop()
        if isinstance(node, SumExpression):
            return True
        if isinstance(node, GroupExpression):
            pending.append(node.expression)
        elif isinstance(node, BinaryExpression):
            pending.extend((node.left, node.right))
        elif isinstance(node, ReadExpression):
            pending.extend(node.indices)
    return False


def expand_small_sums(module, max_nodes=100000, max_depth=32):
    """The module with every sum expanded to its balanced `+` tree, or None.

    None when a sum has more than MAX_TERMS terms or the expansion exceeds the
    parser's node or depth quota; such programs can only be scale-v1.
    """
    nodes = 0

    def made(value, depth):
        nonlocal nodes
        nodes += 1
        if nodes > max_nodes or depth > max_depth:
            raise _TooLarge
        return value, depth

    def expand(node, env):
        """(expanded node, depth), with sum variables in `env` as literals."""
        if isinstance(node, IntegerLiteral):
            return made(IntegerLiteral(node.value, node.span), 1)
        if isinstance(node, NameReference):
            if node.name in env:
                return made(IntegerLiteral(env[node.name], node.span), 1)
            return made(NameReference(node.name, node.span), 1)
        if isinstance(node, GroupExpression):
            child, depth = expand(node.expression, env)
            return made(GroupExpression(child, node.span), depth + 1)
        if isinstance(node, BinaryExpression):
            (left, a), (right, b) = expand(node.left, env), expand(node.right, env)
            return made(BinaryExpression(node.operator, left, right, node.span), max(a, b) + 1)
        if isinstance(node, ReadExpression):
            pairs = [expand(index, env) for index in node.indices]
            return made(ReadExpression(node.name, tuple(i for i, _ in pairs), node.span, node.name_span),
                        max(d for _, d in pairs) + 1)
        if node.upper - node.lower > MAX_TERMS:
            raise _TooLarge

        def tree(lo, hi):
            if hi - lo == 1:
                return expand(node.body, {**env, node.variable: lo})
            mid = (lo + hi) // 2
            (left, a), (right, b) = tree(lo, mid), tree(mid, hi)
            return made(BinaryExpression('+', left, right, node.span), max(a, b) + 1)
        return tree(node.lower, node.upper)

    replaced = {}
    try:
        for decl in (*module.producers, *module.outputs):
            if _has_sum(decl.expression):
                replaced[id(decl)] = dataclasses.replace(decl, expression=expand(decl.expression, {})[0])
    except _TooLarge:
        return None
    if not replaced:
        return module
    swap = lambda decl: replaced.get(id(decl), decl)
    return dataclasses.replace(module, producers=tuple(map(swap, module.producers)),
                               outputs=tuple(map(swap, module.outputs)),
                               declarations=tuple(map(swap, module.declarations)))


def _dimension(node, shapes):
    """Value of a literal, `shape` or `shape + k` (1..8) dimension; None otherwise."""
    if node[0] == 'integer':
        return node[1] if node[1] >= 1 else None
    if node[0] == 'name' and node[1] in shapes:
        return shapes[node[1]]
    if (node[0] == '+' and node[1][0] == 'name' and node[1][1] in shapes
            and node[2][0] == 'integer' and 1 <= node[2][1] <= MAX_OFFSET):
        return shapes[node[1][1]] + node[2][1]
    return None


def _index_terms(node):
    """(axes, literal total) of a `+` tree of axes and literals, else None.

    Nested sums produce indices such as `r + 1 + 2` or `0 + 1`; any grouping
    is accepted because index arithmetic is exact and never an i32 node.
    """
    axes, total, pending = [], 0, [node]
    while pending:
        node = pending.pop()
        if node[0] == 'integer':
            total += node[1]
        elif node in (['name', 'axis0'], ['name', 'axis1']):
            axes.append(node[1])
        elif node[0] == '+':
            pending.extend((node[1], node[2]))
        else:
            return None
    return axes, total


def _gather_index(node):
    """Literals plus at most one axis (any axis, in any position)."""
    terms = _index_terms(node)
    return terms is not None and len(terms[0]) <= 1


def _window_index(node, axis):
    """Exactly `axis` plus literals totalling 0..8, in its own position."""
    terms = _index_terms(node)
    return terms is not None and terms[0] == [axis] and 0 <= terms[1] <= MAX_OFFSET


def _reads_ok(expression, tensors, index_ok):
    reads = 0
    pending = [expression]
    while pending:
        node = pending.pop()
        if node[0] == 'integer':
            continue
        if node[0] in ('+', '*'):
            pending.extend((node[1], node[2]))
        elif node[0] == 'read' and node[1] in tensors and len(node[2]) == 2:
            if not index_ok(node[2]):
                return False
            reads += 1
        else:
            return False
    return reads > 0


def reduce_shape(profile, height, width):
    """Input and producer shapes of a reduce-v1 profile, or None."""
    shapes = {'shape0': height, 'shape1': width}
    try:
        (producer_axes, producer), (output_axes, output) = profile['equations']
        inputs = profile['inputs']
    except (KeyError, TypeError, ValueError):
        return None
    if not 1 <= len(inputs) <= 2:
        return None
    input_shapes = []
    for element, dimensions, interval in inputs:
        if element != 'i32' or interval != [0, 1023] or len(dimensions) != 2:
            return None
        sizes = tuple(_dimension(d, shapes) for d in dimensions)
        if None in sizes:
            return None
        input_shapes.append(sizes)
    if len(producer_axes) != 2 or output_axes != [[['integer', 0], ['name', 'shape0']],
                                                  [['integer', 0], ['name', 'shape1']]]:
        return None
    producer_shape = []
    for (lower, upper), base in zip(producer_axes, ('shape0', 'shape1')):
        # `0..base` or `0..base + k`: a literal or the other shape is refused.
        size = None if upper[0] == 'integer' else _dimension(upper, {base: shapes[base]})
        if lower != ['integer', 0] or size is None:
            return None
        producer_shape.append(size)
    names = {f'input{index}' for index in range(len(inputs))}
    if not _reads_ok(producer, names, lambda ix: all(map(_gather_index, ix))):
        return None
    if not _reads_ok(output, {'producer0'},
                     lambda ix: _window_index(ix[0], 'axis0') and _window_index(ix[1], 'axis1')):
        return None
    return dict(input_shapes=tuple(input_shapes), producer_shape=tuple(producer_shape))


def admit_reduce(module, height, width, objective, profile, shape):
    input_shapes = shape['input_shapes']
    if sum(rows * cols for rows, cols in input_shapes) > MAX_INPUT_CELLS:
        raise DiagnosticError('UNSUPPORTED_PROFILE', module.span, 'inputs exceed 256 cells in total')
    semantics = {
        'semantics_version': REDUCE_SEMANTICS_VERSION, 'family': REDUCE_PROFILE,
        'height': height, 'width': width, 'profile': profile,
        'input_shapes': [list(s) for s in input_shapes],
        'producer_shape': list(shape['producer_shape']),
        'input_layout': 'declaration-order-concatenation',
        'arithmetic': 'exact-i32-per-scalar-node',
        'boundary': 'row-major-preflight-preserve-output-first-invalid',
    }
    canonical = json.dumps(semantics, sort_keys=True, separators=(',', ':'),
                           ensure_ascii=False, allow_nan=False).encode('utf-8')
    return AdmittedKernel(height, width, module.cap, module.inputs[0].input_interval,
                          objective, module.source_digest, hashlib.sha256(canonical).hexdigest(),
                          (module.producers[0].expression, module.outputs[0].expression),
                          REDUCE_SEMANTICS_VERSION, module, REDUCE_PROFILE,
                          input_shapes[0], shape['producer_shape'], input_shapes)
