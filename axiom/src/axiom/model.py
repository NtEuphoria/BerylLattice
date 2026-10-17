"""Immutable source records shared by the frontend and independent evaluator."""
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias

SEMANTICS_VERSION = 'axiom-stencil-i32-v1'


class Objective(StrEnum):
    MULTIPLICATION_OPS = 'multiplication_ops'
    PLAN_WORKSPACE_BYTES = 'plan_workspace_bytes'


class SemanticStatus(StrEnum):
    VALID = 'valid'
    INVALID = 'invalid'
    UNKNOWN = 'unknown'


class ConstraintStatus(StrEnum):
    SATISFIED = 'satisfied'
    VIOLATED = 'violated'
    UNKNOWN = 'unknown'


@dataclass(frozen=True, slots=True)
class Span:
    offset: int
    length: int


class DiagnosticError(ValueError):
    """A stable diagnostic code with a span in the original UTF-8 bytes."""
    def __init__(self, code: str, span: Span, message: str):
        self.code = code
        self.span = span
        self.message = message
        super().__init__(f'{code} at byte {span.offset}: {message}')


@dataclass(frozen=True, slots=True)
class Limits:
    source_bytes: int = 65536
    plan_bytes: int = 2097152
    plan_operations: int = 20000
    expression_nodes: int = 100000
    check_steps: int = 100000

    def __post_init__(self):
        for name in ('source_bytes', 'plan_bytes', 'plan_operations',
                     'expression_nodes', 'check_steps'):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f'{name} must be a positive exact integer')


@dataclass(frozen=True, slots=True)
class IntegerLiteral:
    value: int
    span: Span


@dataclass(frozen=True, slots=True)
class NameReference:
    name: str
    span: Span


@dataclass(frozen=True, slots=True)
class BinaryExpression:
    operator: str
    left: 'Expression'
    right: 'Expression'
    span: Span


@dataclass(frozen=True, slots=True)
class ReadExpression:
    name: str
    indices: tuple['Expression', ...]
    span: Span
    name_span: Span


@dataclass(frozen=True, slots=True)
class GroupExpression:
    expression: 'Expression'
    span: Span


Expression: TypeAlias = IntegerLiteral | NameReference | BinaryExpression | ReadExpression | GroupExpression


@dataclass(frozen=True, slots=True)
class ShapeDeclaration:
    name: str
    value: Expression
    span: Span
    name_span: Span


@dataclass(frozen=True, slots=True)
class InputDeclaration:
    name: str
    element_type: str
    dimensions: tuple[Expression, ...]
    input_interval: tuple[int, int]
    span: Span
    name_span: Span


@dataclass(frozen=True, slots=True)
class AxisBinding:
    name: str
    lower: Expression
    upper: Expression
    span: Span
    name_span: Span


@dataclass(frozen=True, slots=True)
class EquationDeclaration:
    name: str
    axes: tuple[AxisBinding, ...]
    expression: Expression
    span: Span
    name_span: Span
    kind: str


@dataclass(frozen=True, slots=True)
class ConstraintDeclaration:
    property_name: str
    value: int
    span: Span


Declaration: TypeAlias = ShapeDeclaration | InputDeclaration | EquationDeclaration | ConstraintDeclaration


@dataclass(frozen=True, slots=True)
class SourceModule:
    source_bytes: bytes
    source_digest: str
    module_name: str
    shapes: tuple[ShapeDeclaration, ...]
    inputs: tuple[InputDeclaration, ...]
    producers: tuple[EquationDeclaration, ...]
    outputs: tuple[EquationDeclaration, ...]
    cap: int | None
    objective: Objective | str
    span: Span
    declarations: tuple[Declaration, ...]
    constraints: tuple[ConstraintDeclaration, ...]


@dataclass(frozen=True, slots=True)
class AdmittedKernel:
    height: int
    width: int
    cap: int | None
    input_interval: tuple[int, int]
    objective: Objective
    source_digest: str
    semantic_digest: str
    source_expressions: tuple[Expression, Expression]
    semantics_version: str
    source_module: SourceModule
