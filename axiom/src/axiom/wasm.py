"""Compile freshly checked finite operation streams to import-free Wasm.

Each module owns one fixed memory page. The input and initialized output occupy
disjoint i32 ranges, followed by the plan's declared scratch reservation. Callers
must validate and snapshot their scalar buffers before copying into these ranges;
the exported function scans the complete input precondition before any store.
The module returns zero on success, or the first rejected input index plus one.

Checking proves that every scalar operation fits exact i32 on admitted inputs.
The generated add/mul instructions therefore agree with exact signed arithmetic
after preflight; their wrapping behavior grants no authority for other inputs.
"""
from dataclasses import dataclass
from hashlib import sha256

from .model import DiagnosticError, Limits
from .runtime import _checked_plan

_MEMORY_BYTES = 65536
_MAX_SCRATCH_CELLS = 256


@dataclass(frozen=True, slots=True)
class WasmArtifact:
    module_bytes: bytes
    height: int
    width: int
    input_offset: int
    output_offset: int
    memory_bytes: int
    input_count: int
    output_count: int
    input_interval: tuple[int, int]
    source_digest: str
    plan_digest: str
    module_digest: str
    codegen_version: str = 'beryl-finite-wasm-v1'
    hint_digest: str | None = None
    local_count: int = 0
    loop_version: str | None = None


def _uleb(value):
    """Encode a nonnegative section size, index, or count."""
    encoded = bytearray()
    while True:
        byte = value & 0x7f
        value >>= 7
        encoded.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(encoded)


def _sleb(value):
    """Encode a signed i32 immediate, retaining its final sign bit."""
    encoded = bytearray()
    while True:
        byte = value & 0x7f
        value >>= 7
        finished = ((value == 0 and not byte & 0x40)
                    or (value == -1 and byte & 0x40))
        encoded.append(byte if finished else byte | 0x80)
        if finished:
            return bytes(encoded)


def _section(identifier, payload):
    return bytes((identifier,)) + _uleb(len(payload)) + payload


def _const(value):
    return b'\x41' + _sleb(value)


def _load(address):
    # i32.load: natural alignment 2**2, zero additional byte offset.
    return _const(address) + b'\x28\x02\x00'


def _get(index):
    return b'\x20' + _uleb(index)


def _body(kernel, plan, input_count, output_offset, scratch_offset):
    locals_count = sum(operation.dst is not None for operation in plan.operations)
    # One group of zero-initialized i32 locals, addressed by the dense SSA IDs.
    body = bytearray(b'\x01' + _uleb(locals_count) + b'\x7f')
    lower, upper = kernel.input_interval
    for index in range(input_count):
        body.extend(_load(4 * index) + _const(lower) + b'\x48')  # i32.lt_s
        body.extend(_load(4 * index) + _const(upper) + b'\x4a')  # i32.gt_s
        body.extend(b'\x72\x04\x40')  # i32.or; if (no result)
        body.extend(_const(index + 1) + b'\x0f\x0b')  # return first failure; end if

    for operation in plan.operations:
        opcode = operation.opcode
        if opcode == 'const':
            body.extend(_const(operation.value))
        elif opcode == 'input_load':
            body.extend(_load(4 * operation.index))
        elif opcode in ('add', 'mul'):
            left, right = operation.operands
            body.extend(_get(left) + _get(right))
            body.append(0x6a if opcode == 'add' else 0x6c)
        elif opcode == 'scratch_load':
            body.extend(_load(scratch_offset + 4 * operation.index))
        else:  # The checked decoder admits only scratch_store/output_store here.
            base = scratch_offset if opcode == 'scratch_store' else output_offset
            body.extend(_const(base + 4 * operation.index))
            body.extend(_get(operation.operands[0]) + b'\x36\x02\x00')
            continue
        body.extend(b'\x21' + _uleb(operation.dst))  # local.set
    body.extend(_const(0) + b'\x0b')  # success; end function
    return bytes(body)


def compile_wasm(source_bytes: bytes, plan_bytes: bytes,
                 limits: Limits = Limits()) -> WasmArtifact:
    """Re-admit exact source/plan bytes and emit only a fully eligible plan.

    No saved receipt, plan label, or caller-supplied record authorizes emission.
    Reusing the returned module skips compilation and symbolic checking; every
    invocation still enforces the admitted input interval before any mutation.
    Logical workspace remains the checked plan's declared reservation. This
    bounded backend rejects reservations above 256 cells instead of allocating
    arbitrary arenas or silently weakening that metric.
    """
    kernel, plan, checked = _checked_plan(source_bytes, plan_bytes, limits)
    return _emit_finite(kernel, plan, sha256(source_bytes).hexdigest(), sha256(plan_bytes).hexdigest())


def _compile_wasm_checked(owned):
    """Lower only a live successful result retained by its compilation owner."""
    from .compilation import _require_owned
    _require_owned(owned)
    with owned.owner.phase('code_emission'):
        return _emit_finite(owned.kernel, owned.plan, owned.checked.source_digest,
                            owned.checked.plan_digest)


def _layout(kernel, plan):
    input_count = (kernel.height + 1) * (kernel.width + 1)
    output_count = kernel.height * kernel.width
    output_offset = 4 * input_count
    scratch_offset = output_offset + 4 * output_count
    if (plan.scratch_capacity_cells > _MAX_SCRATCH_CELLS
            or scratch_offset + 4 * plan.scratch_capacity_cells > _MEMORY_BYTES):
        raise DiagnosticError('BACKEND_STORAGE_LIMIT', kernel.source_module.span,
                              'bounded Wasm storage requires at most 256 scratch cells in one page')

    return input_count, output_count, output_offset, scratch_offset


def _module(body):
    # Single function () -> i32, no imports, single fixed memory, two exports.
    return b''.join((
        b'\x00asm\x01\x00\x00\x00',
        _section(1, b'\x01\x60\x00\x01\x7f'),
        _section(3, b'\x01\x00'),
        _section(5, b'\x01\x01\x01\x01'),
        _section(7, b'\x02\x06memory\x02\x00\x03run\x00\x00'),
        _section(10, b'\x01' + _uleb(len(body)) + body),
    ))


def _emit_finite(kernel, plan, source_digest, plan_digest):
    input_count, output_count, output_offset, scratch_offset = _layout(kernel, plan)
    body = _body(kernel, plan, input_count, output_offset, scratch_offset)
    module = _module(body)
    return WasmArtifact(module, kernel.height, kernel.width, 0, output_offset,
                        _MEMORY_BYTES, input_count, output_count, kernel.input_interval,
                        source_digest, plan_digest,
                        sha256(module).hexdigest(),
                        local_count=sum(op.dst is not None for op in plan.operations))
