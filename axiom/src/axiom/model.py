"""Immutable source records shared by the frontend and independent evaluator."""
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias

SEMANTICS_VERSION = 'axiom-stencil-i32-v1'
CANONICAL_PROFILE = 'canonical-stencil-v1'
WINDOW_PROFILE = 'window-stencil-v1'
WINDOW_SEMANTICS_VERSION = 'window-stencil-i32-v1'
REDUCE_PROFILE = 'reduce-v1'
REDUCE_SEMANTICS_VERSION = 'reduce-i32-v1'
# scale-v1 kernels are proved by template (scale_checker) over loop plans,
# never by the finite checker, so their version is not in SEMANTICS_VERSIONS.
SCALE_PROFILE = 'scale-v1'
SCALE_SEMANTICS_VERSION = 'scale-i32-v1'
# scale-v1 programs with an i64 equation: each scalar node is exact in its
# equation's declared type (the i32 identity above is unchanged).
SCALE_WIDE_SEMANTICS_VERSION = 'scale-i64-v1'
# Value types an equation may declare (`let t: i64[...]`); i32 when omitted.
VALUE_BOUNDS = {'i32': (-2 ** 31, 2 ** 31 - 1), 'i64': (-2 ** 63, 2 ** 63 - 1)}
SEMANTICS_VERSIONS = (SEMANTICS_VERSION, WINDOW_SEMANTICS_VERSION, REDUCE_SEMANTICS_VERSION)
# Families whose candidate plans come from window_planner.
WINDOW_PLANNED_PROFILES = (WINDOW_PROFILE, REDUCE_PROFILE)


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
    operator: str  # '+', '*', or 'min'/'max'/'shr'/'shr_round' (scale-v1 only)
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


@dataclass(frozen=True, slots=True)
class SumExpression:
    """A symbolic sum (more than 256 terms): the exact integer sum of `body`
    for `variable` in lower..upper-1. Admitted only when no partial sum, in
    any order, can leave i32 (see docs/superpowers/specs/2026-10-19-scale-design.md)."""
    variable: str
    lower: int
    upper: int
    body: 'Expression'
    span: Span
    variable_span: Span


Expression: TypeAlias = (IntegerLiteral | NameReference | BinaryExpression | ReadExpression
                         | GroupExpression | SumExpression)


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
    element_type: str = 'i32'


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
    # The canonical stencil keeps its historical implicit shapes (input
    # (H+1)x(W+1), producer the same). Two-stage window stencils state them.
    profile: str = 'canonical-stencil-v1'
    input_shape: tuple[int, int] | None = None
    producer_shape: tuple[int, int] | None = None
    # reduce-v1 may declare two inputs; the runtime buffer is their row-major
    # contents concatenated in declaration order. input_shape is the first.
    input_shapes: tuple[tuple[int, int], ...] | None = None

    @property
    def all_input_shapes(self) -> tuple[tuple[int, int], ...]:
        return self.input_shapes or ((self.input_rows, self.input_cols),)

    @property
    def input_rows(self) -> int:
        return self.height + 1 if self.input_shape is None else self.input_shape[0]

    @property
    def input_cols(self) -> int:
        return self.width + 1 if self.input_shape is None else self.input_shape[1]

    @property
    def input_count(self) -> int:
        return sum(rows * cols for rows, cols in self.all_input_shapes)

    @property
    def producer_rows(self) -> int:
        return self.height + 1 if self.producer_shape is None else self.producer_shape[0]

    @property
    def producer_cols(self) -> int:
        return self.width + 1 if self.producer_shape is None else self.producer_shape[1]

    @property
    def output_count(self) -> int:
        return self.height * self.width

    @property
    def input_intervals(self) -> tuple[tuple[int, int], ...]:
        """Each input's declared (lower, upper), in declaration (buffer) order."""
        return tuple(tuple(decl.input_interval) for decl in self.source_module.inputs)

    @property
    def value_types(self) -> tuple[str, ...]:
        """Declared types of the producer and output equations, in order."""
        module = self.source_module
        return tuple(eq.element_type for eq in (*module.producers, *module.outputs))

    @property
    def output_type(self) -> str:
        return self.source_module.outputs[0].element_type

    @property
    def wide(self) -> bool:
        """Some equation is i64, so the emitted arithmetic is int64_t."""
        return 'i64' in self.value_types
