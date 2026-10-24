"""Normalized source profiles, and the profile of the original 2x2 stencil.

Normalization renames declarations, axes and sum variables by position and
drops parentheses, keeping the exact operator tree. Family recognizers work
on profiles; canonical admission compares one to the exact record below.
"""
from .model import (BinaryExpression, Expression, GroupExpression, IntegerLiteral,
                    NameReference, ReadExpression, Span, SumExpression, DiagnosticError)


def _ungroup(expression):
    while isinstance(expression, GroupExpression):
        expression = expression.expression
    return expression


def _fail(code, span, message):
    raise DiagnosticError(code, span, message)


def _normalized(expression: Expression, index_names: dict[str, str],
                tensor_names: dict[str, str]):
    node = _ungroup(expression)
    if isinstance(node, IntegerLiteral):
        return ['integer', node.value]
    if isinstance(node, NameReference):
        return ['name', index_names.get(node.name, node.name)]
    if isinstance(node, BinaryExpression):
        return [node.operator, _normalized(node.left, index_names, tensor_names),
                _normalized(node.right, index_names, tensor_names)]
    if isinstance(node, ReadExpression):
        return ['read', tensor_names.get(node.name, node.name),
                [_normalized(i, index_names, tensor_names) for i in node.indices]]
    if isinstance(node, SumExpression):
        # Sum variables are named by nesting depth, like axes by position.
        depth = sum(1 for value in index_names.values() if value.startswith('sumvar'))
        inner = {**index_names, node.variable: f'sumvar{depth}'}
        return ['sum', f'sumvar{depth}', node.lower, node.upper, _normalized(node.body, inner, tensor_names)]
    _fail('INVALID_EXPRESSION', node.span, 'unknown expression record')


def _profile(module):
    """Normalize tensor bases independently from locally scoped axis names."""
    shapes = {decl.name: f'shape{index}' for index, decl in enumerate(module.shapes)}
    tensors = {decl.name: f'input{index}' for index, decl in enumerate(module.inputs)}
    tensors.update({decl.name: f'producer{index}' for index, decl in enumerate(module.producers)})
    tensors.update({decl.name: f'output{index}' for index, decl in enumerate(module.outputs)})
    equations = []
    for decl in (*module.producers, *module.outputs):
        local = dict(shapes)
        local.update({axis.name: f'axis{index}' for index, axis in enumerate(decl.axes)})
        equations.append([
            [[_normalized(axis.lower, shapes, tensors), _normalized(axis.upper, shapes, tensors)]
             for axis in decl.axes],
            _normalized(decl.expression, local, tensors),
        ])
    return {
        'inputs': [[decl.element_type, [_normalized(d, shapes, tensors) for d in decl.dimensions],
                    list(decl.input_interval)] for decl in module.inputs],
        'equations': equations,
    }


def _canonical_profile():
    integer = lambda value: ['integer', value]
    name = lambda value: ['name', value]
    add = lambda a, b: ['+', a, b]
    row, col = name('axis0'), name('axis1')
    height, width = name('shape0'), name('shape1')
    read = lambda tensor, r, c: ['read', tensor, [r, c]]
    increment = add(read('input0', row, col), integer(1))
    consumer = add(add(add(read('producer0', row, col),
                           read('producer0', row, add(col, integer(1)))),
                       read('producer0', add(row, integer(1)), col)),
                   read('producer0', add(row, integer(1)), add(col, integer(1))))
    return {'inputs': [['i32', [add(height, integer(1)), add(width, integer(1))], [0, 1023]]],
            'equations': [
                [[[integer(0), add(height, integer(1))], [integer(0), add(width, integer(1))]], ['*', increment, increment]],
                [[[integer(0), height], [integer(0), width]], consumer],
            ]}
