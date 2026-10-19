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
    SourceModule, Span,
)

_I32_MIN = -(2 ** 31)
_I32_MAX = 2 ** 31 - 1


class ExecutionStatus(StrEnum):
    SUCCESS = 'success'
    INPUT_PRECONDITION_FAILED = 'input_precondition_failed'


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    status: ExecutionStatus
    first_bad_index: int | None
    output: tuple[int, ...]
    input_after: tuple[int, ...]


def _checked_i32(value: int, span: Span) -> int:
    if type(value) is not int or not _I32_MIN <= value <= _I32_MAX:
        raise DiagnosticError('EVALUATION_I32', span, 'source scalar node is outside exact i32')
    return value


def _boundary_values(values, length: int, label: str, span: Span) -> tuple[int, ...]:
    if type(values) not in (tuple, list):
        raise DiagnosticError('BOUNDARY_TYPE', span, f'{label} must be an owned tuple or list')
    if len(values) != length:
        raise DiagnosticError('BOUNDARY_LENGTH', span, f'{label} requires exactly {length} scalars')
    snapshot = tuple(values)
    for index, value in enumerate(snapshot):
        if type(value) is not int:
            raise DiagnosticError('BOUNDARY_TYPE', span, f'{label}[{index}] must be an exact integer')
        if not _I32_MIN <= value <= _I32_MAX:
            raise DiagnosticError('BOUNDARY_I32', span, f'{label}[{index}] must fit i32')
    return snapshot


def _evaluate_expression(expression: Expression, scalars: dict[str, int],
                         tensors: dict[str, dict[tuple[int, ...], int]]) -> int:
    """Evaluate each original scalar node with unbounded host arithmetic first."""
    if isinstance(expression, IntegerLiteral):
        value = expression.value
    elif isinstance(expression, NameReference):
        value = scalars[expression.name]
    elif isinstance(expression, GroupExpression):
        value = _evaluate_expression(expression.expression, scalars, tensors)
    elif isinstance(expression, BinaryExpression):
        left = _evaluate_expression(expression.left, scalars, tensors)
        right = _evaluate_expression(expression.right, scalars, tensors)
        if expression.operator == '+':
            value = left + right
        elif expression.operator == '*':
            value = left * right
        else:
            raise DiagnosticError('INVALID_EXPRESSION', expression.span, 'unsupported scalar operator')
    elif isinstance(expression, ReadExpression):
        indices = tuple(_evaluate_expression(index, scalars, tensors) for index in expression.indices)
        value = tensors[expression.name][indices]
    else:
        raise DiagnosticError('INVALID_EXPRESSION', Span(0, 0), 'unknown source expression')
    return _checked_i32(value, expression.span)


def _evaluate_equation(equation: EquationDeclaration, shapes: dict[str, int],
                       tensors: dict[str, dict[tuple[int, ...], int]]) -> tuple[int, ...]:
    bounds = tuple(range(_evaluate_expression(axis.lower, shapes, tensors),
                         _evaluate_expression(axis.upper, shapes, tensors))
                   for axis in equation.axes)
    cells = {}
    for indices in product(*bounds):
        scalars = dict(shapes)
        scalars.update((axis.name, index) for axis, index in zip(equation.axes, indices))
        cells[indices] = _evaluate_expression(equation.expression, scalars, tensors)
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
                                     'output', module.outputs[0].span)
    lower, upper = kernel.input_interval
    for index, value in enumerate(input_values):
        if value < lower or value > upper:
            return ExecutionResult(ExecutionStatus.INPUT_PRECONDITION_FAILED, index,
                                   output_values, input_values)

    # No equation or destination computation occurs above this complete scan.
    tensors = {}
    shapes = {}
    for declaration in module.shapes:
        shapes[declaration.name] = _evaluate_expression(declaration.value, shapes, tensors)
    input_declaration = module.inputs[0]
    dimensions = tuple(_evaluate_expression(dimension, shapes, tensors)
                       for dimension in input_declaration.dimensions)
    tensors[input_declaration.name] = dict(zip(product(*(range(size) for size in dimensions)), input_values))
    for equation in module.producers:
        _evaluate_equation(equation, shapes, tensors)
    output = _evaluate_equation(module.outputs[0], shapes, tensors)
    return ExecutionResult(ExecutionStatus.SUCCESS, None, output, input_values)
