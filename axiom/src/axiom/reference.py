"""Checked execution of original source equations, independent of physical plans.

The boundary accepts owned tuples/lists, snapshots their scalar values, and
returns immutable observations. It makes no claim about foreign memory.
"""
from dataclasses import dataclass
from enum import StrEnum
from itertools import product

from .frontend import admit_source
from .model import (
    BinaryExpression, DiagnosticError, EquationDeclaration, Expression,
    GroupExpression, IntegerLiteral, NameReference, ReadExpression,
    SourceModule, Span, SumExpression, VALUE_BOUNDS,
)


class ExecutionStatus(StrEnum):
    SUCCESS = 'success'
    INPUT_PRECONDITION_FAILED = 'input_precondition_failed'


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    status: ExecutionStatus
    first_bad_index: int | None
    output: tuple[int, ...]
    input_after: tuple[int, ...]


def _checked(value: int, span: Span, element_type: str) -> int:
    low, high = VALUE_BOUNDS[element_type]
    if type(value) is not int or not low <= value <= high:
        raise DiagnosticError(f'EVALUATION_{element_type.upper()}', span,
                              f'source scalar node is outside exact {element_type}')
    return value


def first_bad_input(kernel, values) -> int | None:
    """Row-major index of the first value outside its own input's declared range.

    Inputs occupy the buffer in declaration order, each row-major, and each
    has its own range (scale-v1); the small families declare one shared range.
    """
    start = 0
    for (rows, cols), (lower, upper) in zip(kernel.all_input_shapes, kernel.input_intervals):
        for index in range(start, start + rows * cols):
            if not lower <= values[index] <= upper:
                return index
        start += rows * cols
    return None


def _boundary_values(values, length: int, label: str, span: Span,
                     element_type: str = 'i32') -> tuple[int, ...]:
    if type(values) not in (tuple, list):
        raise DiagnosticError('BOUNDARY_TYPE', span, f'{label} must be an owned tuple or list')
    if len(values) != length:
        raise DiagnosticError('BOUNDARY_LENGTH', span, f'{label} requires exactly {length} scalars')
    snapshot = tuple(values)
    for index, value in enumerate(snapshot):
        if type(value) is not int:
            raise DiagnosticError('BOUNDARY_TYPE', span, f'{label}[{index}] must be an exact integer')
        low, high = VALUE_BOUNDS[element_type]
        if not low <= value <= high:
            raise DiagnosticError(f'BOUNDARY_{element_type.upper()}', span,
                                  f'{label}[{index}] must fit {element_type}')
    return snapshot


def _evaluate_expression(expression: Expression, scalars: dict[str, int],
                         tensors: dict[str, dict[tuple[int, ...], int]], element_type: str = 'i32') -> int:
    """Evaluate each original scalar node with unbounded host arithmetic first,
    then require it to fit its equation's declared type."""
    if isinstance(expression, IntegerLiteral):
        value = expression.value
    elif isinstance(expression, NameReference):
        value = scalars[expression.name]
    elif isinstance(expression, GroupExpression):
        value = _evaluate_expression(expression.expression, scalars, tensors, element_type)
    elif isinstance(expression, BinaryExpression):
        left = _evaluate_expression(expression.left, scalars, tensors, element_type)
        right = _evaluate_expression(expression.right, scalars, tensors, element_type)
        if expression.operator == '+':
            value = left + right
        elif expression.operator == '*':
            value = left * right
        elif expression.operator == 'min':
            value = min(left, right)
        elif expression.operator == 'max':
            value = max(left, right)
        else:
            raise DiagnosticError('INVALID_EXPRESSION', expression.span, 'unsupported scalar operator')
    elif isinstance(expression, ReadExpression):
        indices = tuple(_evaluate_expression(index, scalars, tensors) for index in expression.indices)
        value = tensors[expression.name][indices]
    elif isinstance(expression, SumExpression):
        # The exact integer sum; only the total is a typed node (admission's
        # checker proves every partial sum fits, in any order).
        inner = dict(scalars)
        value = 0
        for term in range(expression.lower, expression.upper):
            inner[expression.variable] = term
            value += _evaluate_expression(expression.body, inner, tensors, element_type)
    else:
        raise DiagnosticError('INVALID_EXPRESSION', Span(0, 0), 'unknown source expression')
    return _checked(value, expression.span, element_type)


def _evaluate_equation(equation: EquationDeclaration, shapes: dict[str, int],
                       tensors: dict[str, dict[tuple[int, ...], int]]) -> tuple[int, ...]:
    bounds = tuple(range(_evaluate_expression(axis.lower, shapes, tensors),
                         _evaluate_expression(axis.upper, shapes, tensors))
                   for axis in equation.axes)
    cells = {}
    for indices in product(*bounds):
        scalars = dict(shapes)
        scalars.update((axis.name, index) for axis, index in zip(equation.axes, indices))
        cells[indices] = _evaluate_expression(equation.expression, scalars, tensors, equation.element_type)
    tensors[equation.name] = cells
    return tuple(cells.values())


def evaluate_source(module: SourceModule, data: tuple[int, ...] | list[int],
                    initial_output: tuple[int, ...] | list[int]) -> ExecutionResult:
    """Admit source, preflight all input, then interpret its retained equations.

    Caller buffers remain unchanged. On precondition failure, ``output`` is the
    complete original destination and ``first_bad_index`` is its row-major
    input offset. Boundary type/extent/i32 errors are typed diagnostics.
    """
    kernel = admit_source(module)
    if data is initial_output:
        raise DiagnosticError('BOUNDARY_ALIAS', module.span, 'input and output must be disjoint')
    input_values = _boundary_values(data, kernel.input_count,
                                    'input', module.inputs[0].span)
    output_values = _boundary_values(initial_output, kernel.height * kernel.width,
                                     'output', module.outputs[0].span, kernel.output_type)
    bad = first_bad_input(kernel, input_values)
    if bad is not None:
        return ExecutionResult(ExecutionStatus.INPUT_PRECONDITION_FAILED, bad,
                               output_values, input_values)

    # No equation or destination computation occurs above this complete scan.
    tensors = {}
    shapes = {}
    for declaration in module.shapes:
        shapes[declaration.name] = _evaluate_expression(declaration.value, shapes, tensors)
    # Inputs occupy the buffer in declaration order, each row-major.
    offset = 0
    for input_declaration in module.inputs:
        dimensions = tuple(_evaluate_expression(dimension, shapes, tensors)
                           for dimension in input_declaration.dimensions)
        cells = list(product(*(range(size) for size in dimensions)))
        tensors[input_declaration.name] = dict(zip(cells, input_values[offset:offset + len(cells)]))
        offset += len(cells)
    if offset != len(input_values):
        raise DiagnosticError('BOUNDARY_LENGTH', module.span, 'input layout does not cover the buffer')
    for equation in module.producers:
        _evaluate_equation(equation, shapes, tensors)
    output = _evaluate_equation(module.outputs[0], shapes, tensors)
    return ExecutionResult(ExecutionStatus.SUCCESS, None, output, input_values)
