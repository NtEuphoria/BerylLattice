"""Explain why a source is outside the admitted forms, with its location.

This module never admits anything: window_family.window_shape decides on the
normalized profile. After a rejection, this walks the retained AST (which still
has byte spans) for the first broken window-stencil rule and words it with a
fix. When no specific rule is found it returns a general message.
"""
from .model import BinaryExpression, GroupExpression, IntegerLiteral, NameReference, ReadExpression, Span

FORMS = 'the canonical stencil or a two-stage window stencil (see the window-stencil guide)'
MAX_OFFSET = 8


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


def _scalar_problem(expression, tensor, axes, role):
    """First node breaking `role` reads (only `tensor`, indices axis + k)."""
    pending = [expression]
    while pending:
        node = _ungroup(pending.pop())
        if isinstance(node, IntegerLiteral):
            continue
        if isinstance(node, BinaryExpression):
            pending.extend((node.right, node.left))
            continue
        if isinstance(node, ReadExpression):
            if node.name != tensor:
                return node.name_span, f'the {role} may only read `{tensor}`, not `{node.name}`'
            if len(node.indices) != 2:
                return node.span, f'reads of `{tensor}` need two indices'
            for position, (index, axis) in enumerate(zip(node.indices, axes)):
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
    source = module.inputs[0]
    producer, output = module.producers[0], module.outputs[0]
    if source.element_type != 'i32' or tuple(source.input_interval) != (0, 1023):
        return source.span, f'inputs must be declared `{source.name}: i32[...] in 0..=1023`'
    if len(source.dimensions) != 2:
        return source.span, 'the input must have exactly two dimensions'
    for dimension, shape in zip(source.dimensions, shape_names):
        if _offset(dimension, shape) is None:
            return dimension.span, f'input dimensions must be `{shape}` or `{shape} + k` with a literal 0 < k <= {MAX_OFFSET}'
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
    problem = _scalar_problem(producer.expression, source.name, [a.name for a in producer.axes], 'producer')
    if problem:
        return problem
    problem = _scalar_problem(output.expression, producer.name, [a.name for a in output.axes], 'output')
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
    return Span(0, 0), f'requires exactly two shapes, one input, one producer and one output ({found}){hint}'
