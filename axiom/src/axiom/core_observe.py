"""Exact successful Core witness stdout framing, independent of CLI diagnostics."""
from dataclasses import dataclass
import re

from .model import AdmittedKernel


class ObservationError(ValueError):
    """The complete scalar observation protocol was not present."""


@dataclass(frozen=True, slots=True)
class Observation:
    status: int
    input: tuple[int, ...]
    output: tuple[int, ...]


def decode_observation(stdout: bytes, kernel: AdmittedKernel) -> Observation:
    """Accept exactly status, all input/output i32s and the zero-assertion summary."""
    inputs = (kernel.height + 1) * (kernel.width + 1)
    outputs = kernel.height * kernel.width
    lines = stdout.split(b'\n')
    if len(lines) != 1 + inputs + outputs + 2 or lines[-2:] != [b'ok  1 test, 0 assertions', b'']:
        raise ObservationError('Incomplete or altered Core scalar observation framing')
    values = []
    for line in lines[:-2]:
        if len(line) > 11 or re.fullmatch(rb'(?:0|-?[1-9][0-9]*)', line) is None:
            raise ObservationError('Expected canonical signed i32 scalar line')
        value = int(line)
        if not -(2**31) <= value < 2**31:
            raise ObservationError('Scalar observation is outside signed i32')
        values.append(value)
    return Observation(values[0], tuple(values[1:1 + inputs]), tuple(values[1 + inputs:]))
