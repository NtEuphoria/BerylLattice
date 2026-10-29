"""Explain why a source is outside the admitted forms, with its location.

This module never admits anything: window_family.window_shape decides on the
normalized profile. After a rejection, this walks the retained AST (which still
has byte spans) for the first broken window-stencil rule and words it with a
fix. When no specific rule is found it returns a general message.
"""
from .model import BinaryExpression, GroupExpression, IntegerLiteral, NameReference, ReadExpression, Span

FORMS = ('the canonical stencil, a two-stage window stencil or a reduce-v1 kernel '
         '(see the window-stencil guide)')
MAX_OFFSET = 8
# Rules are the union of the window-stencil and reduce-v1 families: the most
# permissive reading of each, so no message rejects what one family admits.


def _ungroup(node):
    while isinstance(node, GroupExpression):
        node = node.expression
    return node


def _offset(node, base):
    """k for `base` or `base + k` (literal 1..MAX_OFFSET); None otherwise."""
    node = _ungroup(node)
    if isinstance(node, NameReference) and node.name == base:
        return 0
    if (isinstance(node, BinaryExpression) and node.operator == '+'
            and isinstance(_ungroup(node.left), NameReference) and _ungroup(node.left).name == base
            and isinstance(_ungroup(node.right), IntegerLiteral) and 1 <= _ungroup(node.right).value <= MAX_OFFSET):
        return _ungroup(node.right).value
    return None


def _terms(node, axes):
    """(axes used, literal total) of a `+` tree of axes and literals, else None."""
    used, total, pending = [], 0, [node]
    while pending:
        node = _ungroup(pending.pop())
        if isinstance(node, IntegerLiteral):
            total += node.value
        elif isinstance(node, NameReference) and node.name in axes:
            used.append(node.name)
        elif isinstance(node, BinaryExpression) and node.operator == '+':
            pending.extend((node.left, node.right))
        else:
            return None
    return used, total


def _gather(node, axes):
    """Literals plus at most one axis: the reduce-v1 input index."""
    terms = _terms(node, axes)
    return terms is not None and len(terms[0]) <= 1


def _scalar_problem(expression, tensors, axes, role):
    """First node breaking `role` reads (only `tensors`; window indices for the
    output, gather indices for the producer)."""
    pending = [expression]
    while pending:
        node = _ungroup(pending.pop())
        if isinstance(node, IntegerLiteral):
            continue
        if isinstance(node, BinaryExpression):
            pending.extend((node.right, node.left))
            continue
        if isinstance(node, ReadExpression):
            if node.name not in tensors:
                allowed = ' or '.join(f'`{t}`' for t in tensors)
                return node.name_span, f'the {role} may only read {allowed}, not `{node.name}`'
            if len(node.indices) != 2:
                return node.span, f'reads of `{node.name}` need two indices'
            for position, (index, axis) in enumerate(zip(node.indices, axes)):
                if role == 'producer':
                    if not _gather(index, axes):
                        return index.span, ('producer indices must be an axis, `axis + k` with a literal '
                                            'k >= 0, or a literal (no shapes)')
                    continue
                terms = _terms(index, axes)
                if terms is not None and terms[0] == [axis] and 0 <= terms[1] <= MAX_OFFSET:
                    continue  # reduce-v1 also groups offsets freely: `r + 1 + 2`
                if _offset(index, axis) is None:
                    which = 'first' if position == 0 else 'second'
                    return index.span, (f'the {which} index must be `{axis}` or `{axis} + k` with a literal '
                                        f'0 < k <= {MAX_OFFSET} (no other axis, shape or reversed order)')
            continue
        return node.span, 'scalar expressions may use only literals, reads, +, - and *'
    return None


def explain(module):
    """(span, message) for the first broken rule; never None."""
    shape_names = [decl.name for decl in module.shapes]
    producer, output = module.producers[0], module.outputs[0]
    for source in module.inputs:
        if source.element_type != 'i32' or tuple(source.input_interval) != (0, 1023):
            return source.span, f'inputs must be declared `{source.name}: i32[...] in 0..=1023`'
        if len(source.dimensions) != 2:
            return source.span, 'each input must have exactly two dimensions'
        for dimension in source.dimensions:
            literal = isinstance(_ungroup(dimension), IntegerLiteral)
            if not literal and all(_offset(dimension, shape) is None for shape in shape_names):
                return dimension.span, ('input dimensions must be a literal, a shape, or a shape + k '
                                        f'with a literal 0 < k <= {MAX_OFFSET}')
    if len(producer.axes) != 2 or len(output.axes) != 2:
        return producer.span, 'the producer (`let`) and the output each need exactly two axes'
    for axis, shape in zip(producer.axes, shape_names):
        lower = _ungroup(axis.lower)
        if not (isinstance(lower, IntegerLiteral) and lower.value == 0) or _offset(axis.upper, shape) is None:
            return axis.span, f'producer axes must be `{axis.name} in 0..{shape}` or `0..{shape} + k`'
    for axis, shape in zip(output.axes, shape_names):
        lower, upper = _ungroup(axis.lower), _ungroup(axis.upper)
        if not (isinstance(lower, IntegerLiteral) and lower.value == 0) or not (
                isinstance(upper, NameReference) and upper.name == shape):
            return axis.span, f'output axes must be exactly `{axis.name} in 0..{shape}`'
    problem = _scalar_problem(producer.expression, [i.name for i in module.inputs],
                              [a.name for a in producer.axes], 'producer')
    if problem:
        return problem
    problem = _scalar_problem(output.expression, [producer.name], [a.name for a in output.axes], 'output')
    if problem:
        return problem
    return module.span, f'source is outside the admitted forms: {FORMS}'


def explain_counts(module):
    found = (f'found {len(module.shapes)} shape(s), {len(module.inputs)} input(s), '
             f'{len(module.producers)} producer(s) (`let`) and {len(module.outputs)} output(s)')
    if len(module.producers) == 0 and len(module.outputs) == 1 and module.inputs:
        hint = (f'; add a producer, for example `let p[r in 0..H+k, c in 0..W+k] = {module.inputs[0].name}[r,c];`, '
                'and have the output read `p`')
    else:
        hint = ''
    return Span(0, 0), (f'requires exactly two shapes, one to four inputs, one producer and one output '
                        f'({found}){hint}')
