"""Lower freshly checked finite plans to ordinary, fully admitted Core source.

These are source artifacts, not a reusable native ABI or an admission certificate.
The Core driver must still perform its complete frontend and backend admission.
"""
from dataclasses import dataclass, fields, is_dataclass
from hashlib import sha256
from pathlib import Path

from .checker import check_plan
from .codec import canonical_json, decode_plan, plan_digest
from .frontend import admit_source, parse_source
from .model import (BinaryExpression, GroupExpression, IntegerLiteral, Limits,
                    NameReference, ReadExpression, Span)

EMITTER_VERSION = 'axiom-core-emitter-v1'
# Bind implementation bytes as well as the explicit source/observation protocol.
EMITTER_DIGEST = sha256(canonical_json({
    'version': EMITTER_VERSION, 'implementation_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
    'entry': 'checked_preflight_first_invalid_v1',
    'observation': 'status_then_all_input_then_all_output_v1',
    'aggregate_limit': 256,
})).hexdigest()


class CoreEmissionError(ValueError):
    """Source/plan/boundary rejection, or unsupported adapter specialization."""
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f'{code}: {message}')


@dataclass(frozen=True, slots=True)
class MappingEntry:
    generated_source_sha256: str
    generated_file_key: str
    generated_offset: int
    generated_length: int
    origins: tuple[Span, ...]
    operation_index: int | None
    role: str
    synthetic: bool


@dataclass(frozen=True, slots=True)
class ObservationLayout:
    status_index: int
    input_start: int
    input_count: int
    output_start: int
    output_count: int

    @property
    def scalar_count(self) -> int:
        return 1 + self.input_count + self.output_count


@dataclass(frozen=True, slots=True)
class CoreKernelBundle:
    artifact_kind: str
    source_bytes: bytes
    source_sha256: str
    mappings: tuple[MappingEntry, ...]
    axiom_source_bytes: bytes
    plan_bytes: bytes
    source_digest: str
    semantic_digest: str
    plan_digest: str
    plan_bytes_sha256: str
    emitter_version: str
    emitter_digest: str

    @property
    def generated_source_sha256(self) -> str:
        return self.source_sha256


@dataclass(frozen=True, slots=True)
class CoreBundle(CoreKernelBundle):
    kernel_source_bytes: bytes
    kernel_source_sha256: str
    data: tuple[int, ...]
    initial_output: tuple[int, ...]
    case_digest: str
    observation_layout: ObservationLayout


def _origin_table(module):
    """Resolve an origin offset to a complete retained expression-node span.

    Binary/read nodes can share their start; choose the widest actual node at
    that offset, deterministically. Bounds-valid interior token offsets fail.
    """
    result = {}
    stack = [module]
    expression_types = (IntegerLiteral, NameReference, BinaryExpression,
                        ReadExpression, GroupExpression)
    while stack:
        item = stack.pop()
        if isinstance(item, expression_types):
            span = item.span
            if (span.offset < 0 or span.length <= 0
                    or span.offset+span.length > len(module.source_bytes)):
                raise CoreEmissionError('INVALID_SOURCE_ORIGIN', 'invalid retained AST span')
            if span.offset not in result or result[span.offset].length < span.length:
                result[span.offset] = span
        if is_dataclass(item):
            stack.extend(getattr(item, field.name) for field in fields(item))
        elif isinstance(item, tuple):
            stack.extend(item)
    return result


def _checked(source, plan_bytes, limits):
    if type(source) is not bytes or type(plan_bytes) is not bytes or type(limits) is not Limits:
        raise CoreEmissionError('INVALID_EMISSION_ARGUMENT', 'expected exact bytes and Limits')
    kernel = admit_source(parse_source(source, limits))
    plan = decode_plan(plan_bytes, limits)
    result = check_plan(kernel, plan, limits)
    if not result.eligible:
        reason = result.reason if result.reason != 'VALID' else 'CONSTRAINT_VIOLATED'
        raise CoreEmissionError(reason, 'plan did not pass fresh semantic and constraint checks')
    n, m = (kernel.height+1)*(kernel.width+1), kernel.height*kernel.width
    if max(n, m, plan.scratch_capacity_cells) > 256:
        raise CoreEmissionError('CORE_AGGREGATE_LIMIT', 'fixed aggregate exceeds 256 scalar cells')
    table = _origin_table(kernel.source_module)
    operation_origins = []
    for i, operation in enumerate(plan.operations):
        if not operation.origins or any(offset not in table for offset in operation.origins):
            raise CoreEmissionError('INVALID_PLAN_ORIGIN', f'operation {i} has no exact source AST origin')
        operation_origins.append(tuple(table[offset] for offset in operation.origins))
    return kernel, plan, tuple(operation_origins)


class _Writer:
    def __init__(self):
        self.parts = []
        self.ranges = []
        self.length = 0

    def add(self, text, origins, role, operation_index=None):
        encoded = text.encode('utf-8')
        if not encoded or not origins:
            raise CoreEmissionError('INVALID_MAPPING', 'empty generated range or source origins')
        self.parts.append(encoded)
        self.ranges.append((self.length, len(encoded), origins, operation_index, role))
        self.length += len(encoded)

    def finish(self, file_key):
        source = b''.join(self.parts)
        digest = sha256(source).hexdigest()
        mappings = tuple(MappingEntry(digest, file_key, offset, length, origins,
                                     operation, role, operation is None)
                         for offset, length, origins, operation, role in self.ranges)
        return source, digest, mappings


def _kernel_writer(kernel, plan, operation_origins):
    writer = _Writer()
    module = kernel.source_module
    n, m = (kernel.height+1)*(kernel.width+1), kernel.height*kernel.width
    writer.add('module axiom_generated\n\n', (module.span,), 'wrapper')
    writer.add(f'fn ax_kernel(input: [i32; {n}], inout output: [i32; {m}]) -> i32 {{\n',
               (module.inputs[0].span, module.outputs[0].span), 'wrapper')
    lower, upper = kernel.input_interval
    for i in range(n):
        writer.add(f'    if input[{i}] < {lower} || input[{i}] > {upper} {{ return {i} }}\n',
                   (module.inputs[0].span,), 'preflight')
    if plan.scratch_capacity_cells:
        capacity = plan.scratch_capacity_cells
        zeros = ', '.join('0' for _ in range(capacity))
        writer.add(f'    var scratch: [i32; {capacity}] = [{zeros}]\n',
                   (module.producers[0].span,), 'scratch_initialization')
    for i, operation in enumerate(plan.operations):
        opcode = operation.opcode
        prefix = f'    let ax_v{operation.dst}: i32 = '
        if opcode == 'const':
            statement = prefix + str(operation.value)
        elif opcode == 'input_load':
            statement = prefix + f'input[{operation.index}]'
        elif opcode in ('add', 'mul'):
            left, right = operation.operands
            operator = '+' if opcode == 'add' else '*'
            statement = prefix + f'ax_v{left} {operator} ax_v{right}'
        elif opcode == 'scratch_load':
            statement = prefix + f'scratch[{operation.index}]'
        elif opcode in ('scratch_store', 'output_store'):
            root = 'scratch' if opcode == 'scratch_store' else 'output'
            statement = f'    {root}[{operation.index}] = ax_v{operation.operands[0]}'
        else:
            # Defense in depth: structural admission is not a catch-all store.
            raise CoreEmissionError('UNSUPPORTED_OPERATION', opcode)
        writer.add(statement+'\n', operation_origins[i], 'user_equation', i)
    writer.add('    return -1\n}\n', (module.outputs[0].span,), 'wrapper')
    return writer


def _metadata(source, plan_bytes, kernel, plan, limits):
    return dict(axiom_source_bytes=source, plan_bytes=plan_bytes,
                source_digest=kernel.source_digest, semantic_digest=kernel.semantic_digest,
                plan_digest=plan_digest(plan, limits=limits),
                plan_bytes_sha256=sha256(plan_bytes).hexdigest(),
                emitter_version=EMITTER_VERSION, emitter_digest=EMITTER_DIGEST)


def emit_core_kernel(source: bytes, plan_bytes: bytes, limits: Limits) -> CoreKernelBundle:
    """Produce a kernel-only artifact after independently rechecking exact bytes."""
    kernel, plan, origins = _checked(source, plan_bytes, limits)
    generated, digest, mappings = _kernel_writer(kernel, plan, origins).finish('kernel.be')
    return CoreKernelBundle('core_kernel_source', generated, digest, mappings,
                            **_metadata(source, plan_bytes, kernel, plan, limits))


def _boundary(values, count, label):
    if type(values) is not tuple or len(values) != count:
        raise CoreEmissionError('BOUNDARY_LENGTH_OR_TYPE', f'{label} requires an exact tuple of {count} scalars')
    if any(type(value) is not int or not -2147483648 <= value <= 2147483647 for value in values):
        raise CoreEmissionError('BOUNDARY_I32', f'{label} scalars must be exact i32 integers')


def emit_core(source: bytes, plan_bytes: bytes, limits: Limits,
              data: tuple[int, ...], initial_output: tuple[int, ...]) -> CoreBundle:
    """Emit one isolated literal case; runtime preflight is never elided.

    Do not use fixed-case witness binaries as native throughput workloads.
    There is no public unchecked path and no caller-supplied success record.
    """
    kernel, plan, origins = _checked(source, plan_bytes, limits)
    n, m = (kernel.height+1)*(kernel.width+1), kernel.height*kernel.width
    _boundary(data, n, 'input')
    _boundary(initial_output, m, 'output')
    writer = _kernel_writer(kernel, plan, origins)
    kernel_source, kernel_digest, _ = writer.finish('kernel.be')
    module = kernel.source_module
    writer.add('\ntest "axiom witness" {\n', (module.span,), 'harness')
    writer.add(f'    let input: [i32; {n}] = [{", ".join(map(str, data))}]\n',
               (module.inputs[0].span,), 'harness_initialization')
    writer.add(f'    var output: [i32; {m}] = [{", ".join(map(str, initial_output))}]\n',
               (module.outputs[0].span,), 'harness_initialization')
    writer.add('    let status: i32 = ax_kernel(input, inout output)\n',
               (module.inputs[0].span, module.outputs[0].span), 'harness')
    writer.add('    println(status)\n', (module.span,), 'observation_status')
    for i in range(n):
        writer.add(f'    println(input[{i}])\n', (module.inputs[0].span,), 'observation_input')
    for i in range(m):
        writer.add(f'    println(output[{i}])\n', (module.outputs[0].span,), 'observation_output')
    writer.add('}\n', (module.span,), 'harness')
    generated, digest, mappings = writer.finish('witness.be')
    metadata = _metadata(source, plan_bytes, kernel, plan, limits)
    case_digest = sha256(canonical_json({
        'version': 1, 'artifact_kind': 'core_witness_source',
        'source_digest': metadata['source_digest'], 'plan_digest': metadata['plan_digest'],
        'plan_bytes_sha256': metadata['plan_bytes_sha256'], 'emitter_digest': EMITTER_DIGEST,
        'generated_source_sha256': digest, 'data': list(data), 'initial_output': list(initial_output),
    })).hexdigest()
    return CoreBundle('core_witness_source', generated, digest, mappings,
                      **metadata, kernel_source_bytes=kernel_source,
                      kernel_source_sha256=kernel_digest, data=data,
                      initial_output=initial_output, case_digest=case_digest,
                      observation_layout=ObservationLayout(0, 1, n, 1+n, m))
