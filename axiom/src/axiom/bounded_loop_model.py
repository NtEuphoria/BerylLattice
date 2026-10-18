"""Untrusted bounded v1 hints, never a scalable loop proof or eligibility.

Index evaluation order is part of this format: start at ``constant``; for each
term in order evaluate ``variable + offset``, optionally ``% 2``, multiply by
``coefficient``, then add to the accumulator. Modulo two is nonnegative
mathematical parity, including for negative components (use ``& 1`` when
lowering to C or Wasm). Every intermediate must fit i32.
The final index must be nonnegative. Backends must preserve this exact order.
"""
from dataclasses import dataclass

FORMAT_VERSION = 'beryl-bounded-loop-v1'
CORRESPONDENCE_VERSION = 'beryl-bounded-correspondence-v1'
I32_MIN, I32_MAX = -2147483648, 2147483647


class HintError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(f'{code}: {message}')


@dataclass(frozen=True, slots=True)
class HintLimits:
    encoded_bytes: int = 65536
    syntax_nodes: int = 4096
    nesting_depth: int = 16
    work_steps: int = 100000

    def __post_init__(self):
        ceilings = (65536, 4096, 16, 100000)
        for name, ceiling in zip(self.__slots__, ceilings):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ValueError(f'{name} must be an exact positive integer <= {ceiling}')


@dataclass(frozen=True, slots=True)
class IndexTerm:
    coefficient: int
    variable: str
    offset: int = 0
    modulo2: bool = False


@dataclass(frozen=True, slots=True)
class IndexExpr:
    constant: int = 0
    terms: tuple[IndexTerm, ...] = ()


@dataclass(frozen=True, slots=True)
class Primitive:
    opcode: str
    dst: str | None = None
    operands: tuple[str, ...] = ()
    index: IndexExpr | None = None
    value: int | None = None
    origins: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class Loop:
    variable: str
    start: int
    stop: int
    body: tuple['Loop | Primitive', ...]


@dataclass(frozen=True, slots=True)
class LoopProgram:
    format_version: str
    source_digest: str
    semantic_digest: str
    height: int
    width: int
    scratch_capacity_cells: int
    body: tuple[Loop | Primitive, ...]
    label: str = 'bounded hint'
