"""scale-v1: the reduce-v1 structure at any size up to 2^24 cells, plus symbolic sums.

Members are proved by template (scale_checker) over loop plans, so proof cost
does not grow with the data. Recognition works on the normalized profile and
runs after the canonical, window and reduce-v1 families, which keep their own
admission and identities for programs within 256 input cells. Bounds of every
read, including those indexed by sum variables, were already proved by
frontend validation. See docs/superpowers/specs/2026-10-19-scale-design.md.
"""
import hashlib
import json

from .model import (AdmittedKernel, DiagnosticError, SCALE_PROFILE, SCALE_SEMANTICS_VERSION,
                    SCALE_WIDE_SEMANTICS_VERSION, STORAGE_BOUNDS)
from .reduce_family import _dimension

MAX_CELLS = 1 << 24


def _index_terms(node, bound):
    """(axes, sum variables, literal total) of a `+` tree, else None."""
    axes, sums, total, pending = [], [], 0, [node]
    while pending:
        node = pending.pop()
        if node[0] == 'integer':
            total += node[1]
        elif node in (['name', 'axis0'], ['name', 'axis1']):
            axes.append(node[1])
        elif node[0] == 'name' and node[1] in bound:
            sums.append(node[1])
        elif node[0] == '+':
            pending.extend((node[1], node[2]))
        else:
            return None
    return axes, sums, total


def _producer_index(node, bound):
    """Literals, sum variables and at most one axis."""
    terms = _index_terms(node, bound)
    return terms is not None and len(terms[0]) <= 1


def _output_index(axis):
    def check(node, bound):
        terms = _index_terms(node, bound)
        return terms is not None and terms[0] == [axis]
    return check


def _reads_ok(expression, tensors, checks):
    """Every read is of `tensors` with indices passing `checks`; at least one read."""
    reads = 0
    pending = [(expression, frozenset())]
    while pending:
        node, bound = pending.pop()
        kind = node[0]
        if kind == 'integer':
            continue
        if kind in ('+', '*', 'min', 'max', 'shr', 'shr_round'):
            pending.extend(((node[1], bound), (node[2], bound)))
        elif kind == 'sum':
            pending.append((node[4], bound | {node[1]}))
        elif kind == 'read' and node[1] in tensors and len(node[2]) == 2:
            if not all(check(index, bound) for check, index in zip(checks, node[2])):
                return False
            reads += 1
        else:
            return False
    return reads > 0


def scale_shape(profile, height, width):
    """Input and producer shapes of a scale-v1 profile, or None."""
    shapes = {'shape0': height, 'shape1': width}
    try:
        (producer_axes, producer), (output_axes, output) = profile['equations']
        inputs = profile['inputs']
    except (KeyError, TypeError, ValueError):
        return None
    if not 1 <= len(inputs) <= 2:
        return None
    input_shapes = []
    for element, dimensions, interval in inputs:
        # Any i32 range per input (the frontend keeps it inside i32 and inside
        # a narrow storage type); the checker bounds each read by its own range.
        if element not in ('i32', *STORAGE_BOUNDS) or len(dimensions) != 2:
            return None
        sizes = tuple(_dimension(d, shapes) for d in dimensions)
        if None in sizes:
            return None
        input_shapes.append(sizes)
    if len(producer_axes) != 2 or output_axes != [[['integer', 0], ['name', 'shape0']],
                                                  [['integer', 0], ['name', 'shape1']]]:
        return None
    producer_shape = []
    for (lower, upper), base in zip(producer_axes, ('shape0', 'shape1')):
        size = None if upper[0] == 'integer' else _dimension(upper, {base: shapes[base]})
        if lower != ['integer', 0] or size is None:
            return None
        producer_shape.append(size)
    names = {f'input{index}' for index in range(len(inputs))}
    if not _reads_ok(producer, names, (_producer_index, _producer_index)):
        return None
    if not _reads_ok(output, {'producer0'}, (_output_index('axis0'), _output_index('axis1'))):
        return None
    return dict(input_shapes=tuple(input_shapes), producer_shape=tuple(producer_shape))


def admit_scale(module, height, width, objective, profile, shape):
    input_shapes, producer_shape = shape['input_shapes'], shape['producer_shape']
    for label, cells in (('inputs', sum(r * c for r, c in input_shapes)),
                         ('the producer', producer_shape[0] * producer_shape[1]),
                         ('the output', height * width)):
        if cells > MAX_CELLS:
            raise DiagnosticError('UNSUPPORTED_PROFILE', module.span,
                                  f'{label} exceed {MAX_CELLS} cells')
    semantics = {
        'semantics_version': SCALE_SEMANTICS_VERSION, 'family': SCALE_PROFILE,
        'height': height, 'width': width, 'profile': profile,
        'input_shapes': [list(s) for s in input_shapes], 'producer_shape': list(producer_shape),
        'input_layout': 'declaration-order-concatenation',
        'arithmetic': 'exact-i32-per-scalar-node',
        'symbolic_sum': 'exact-sum-every-partial-sum-in-i32',
        'boundary': 'row-major-preflight-preserve-output-first-invalid',
    }
    types = [decl.element_type for decl in (*module.producers, *module.outputs)]
    version = SCALE_SEMANTICS_VERSION
    if 'i64' in types:
        # Programs without i64 keep the identity above unchanged.
        version = SCALE_WIDE_SEMANTICS_VERSION
        semantics.update(semantics_version=version, value_types=types,
                         arithmetic='exact-declared-type-per-scalar-node',
                         symbolic_sum='exact-sum-every-partial-sum-in-declared-type')
    storage = {'input': module.inputs[0].element_type, 'output': module.outputs[0].element_type}
    if set(storage.values()) & STORAGE_BOUNDS.keys():
        # Programs with only i32 and i64 storage keep the identities above.
        semantics.update(storage=storage, stored_value='output-proved-to-fit-its-storage-type')
    canonical = json.dumps(semantics, sort_keys=True, separators=(',', ':'),
                           ensure_ascii=False, allow_nan=False).encode('utf-8')
    return AdmittedKernel(height, width, module.cap, module.inputs[0].input_interval,
                          objective, module.source_digest, hashlib.sha256(canonical).hexdigest(),
                          (module.producers[0].expression, module.outputs[0].expression),
                          version, module, SCALE_PROFILE,
                          input_shapes[0], producer_shape, input_shapes)
