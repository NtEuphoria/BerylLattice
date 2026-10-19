"""Two-stage window stencils: the admitted family beyond the canonical stencil.

    input x: i32[H+a, W+b] in 0..=1023;
    let p[r in 0..H+pa, c in 0..W+pb] = f(x[r+i, c+j], literals, +, *);
    output o[r in 0..H, c in 0..W]    = g(p[r+i, c+j], literals, +, *);

Recognition works on the frontend's normalized profile, so tensor and axis
names, redundant parentheses and declaration spelling never matter, while
the original association of + and * is retained exactly. Bounds of every
read were already proved by frontend validation. The canonical stencil is a
member, but keeps its historical admission and semantic identity; this
module only admits the other members.
"""
import hashlib
import json

from .model import (AdmittedKernel, DiagnosticError, WINDOW_PROFILE,
                    WINDOW_SEMANTICS_VERSION)

MAX_INPUT_CELLS = 256
MAX_OFFSET = 8


def _offset(dimension, base):
    """k for `base` or `base + k` (literal k >= 1); None otherwise."""
    if dimension == ['name', base]:
        return 0
    if (type(dimension) is list and len(dimension) == 3 and dimension[0] == '+'
            and dimension[1] == ['name', base] and dimension[2][0] == 'integer'
            and 1 <= dimension[2][1] <= MAX_OFFSET):
        return dimension[2][1]
    return None


def _scalar_reads(expression, tensor):
    """Read offsets of a scalar expression that only reads `tensor`, else None."""
    reads = []
    pending = [expression]
    while pending:
        node = pending.pop()
        kind = node[0]
        if kind == 'integer':
            continue
        if kind in ('+', '*'):
            pending.extend((node[1], node[2]))
        elif kind == 'read' and node[1] == tensor and len(node[2]) == 2:
            row, col = _offset(node[2][0], 'axis0'), _offset(node[2][1], 'axis1')
            if row is None or col is None:
                return None
            reads.append((row, col))
        else:
            return None
    return reads or None


def window_shape(profile):
    """Shape facts for a two-stage window stencil profile, or None."""
    try:
        (element, dimensions, interval), = profile['inputs']
        (producer_axes, producer), (output_axes, output) = profile['equations']
    except (KeyError, TypeError, ValueError):
        return None
    if element != 'i32' or interval != [0, 1023] or len(dimensions) != 2:
        return None
    input_offsets = (_offset(dimensions[0], 'shape0'), _offset(dimensions[1], 'shape1'))
    if len(producer_axes) != 2 or len(output_axes) != 2:
        return None
    producer_offsets = []
    for (lower, upper), base in zip(producer_axes, ('shape0', 'shape1')):
        producer_offsets.append(_offset(upper, base) if lower == ['integer', 0] else None)
    if output_axes != [[['integer', 0], ['name', 'shape0']], [['integer', 0], ['name', 'shape1']]]:
        return None
    if None in input_offsets or None in producer_offsets:
        return None
    producer_reads = _scalar_reads(producer, 'input0')
    output_reads = _scalar_reads(output, 'producer0')
    if producer_reads is None or output_reads is None:
        return None
    return dict(input_offsets=input_offsets, producer_offsets=tuple(producer_offsets),
                producer_reads=sorted(set(producer_reads)), output_reads=sorted(set(output_reads)))


def admit_window(module, height, width, objective, profile, window):
    a, b = window['input_offsets']
    pa, pb = window['producer_offsets']
    if (height + a) * (width + b) > MAX_INPUT_CELLS:
        raise DiagnosticError('UNSUPPORTED_PROFILE', module.span, 'input exceeds 256 cells')
    semantics = {
        'semantics_version': WINDOW_SEMANTICS_VERSION, 'family': WINDOW_PROFILE,
        'height': height, 'width': width, 'profile': profile,
        'input_shape': [height + a, width + b], 'producer_shape': [height + pa, width + pb],
        'arithmetic': 'exact-i32-per-scalar-node',
        'boundary': 'row-major-preflight-preserve-output-first-invalid',
    }
    canonical = json.dumps(semantics, sort_keys=True, separators=(',', ':'),
                           ensure_ascii=False, allow_nan=False).encode('utf-8')
    return AdmittedKernel(height, width, module.cap, module.inputs[0].input_interval,
                          objective, module.source_digest, hashlib.sha256(canonical).hexdigest(),
                          (module.producers[0].expression, module.outputs[0].expression),
                          WINDOW_SEMANTICS_VERSION, module, WINDOW_PROFILE,
                          (height + a, width + b), (height + pa, width + pb))
