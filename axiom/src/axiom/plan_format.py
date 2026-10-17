"""Immutable records for the finite, unrolled physical plan format v1.

Construction grants no trust: call codec.validate_plan at every checked boundary.
"""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Operation:
    opcode: str
    dst: int | None = None
    operands: tuple[int, ...] = ()
    index: int | None = None
    value: int | None = None
    origins: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class Plan:
    format_version: int
    semantic_digest: str
    plan_id: str
    scratch_capacity_cells: int
    operations: tuple[Operation, ...]
