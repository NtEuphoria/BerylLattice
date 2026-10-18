"""Private bounded hints lowered only after fresh, owned stream correspondence.

The finite checker proves all primitive arithmetic, including dead operations.
Independent hint traversal proves each index intermediate and final arena bound
for every executed iteration. Thus i32 arithmetic is exact after preflight;
index byte scaling cannot overflow because the shared layout fits one page.
This is a bounded v1 optimization, not scalable loop-proof authority.
"""
from hashlib import sha256

from .bounded_loop_correspondence import validate_loop_correspondence
from .bounded_loop_model import CORRESPONDENCE_VERSION, HintLimits, Loop
from .compilation import _require_owned
from .wasm import WasmArtifact, _MEMORY_BYTES, _const, _get, _layout, _module, _uleb

CODEGEN_VERSION = 'beryl-bounded-loop-wasm-v1'


def _set(index):
    return b'\x21' + _uleb(index)


def _loop(index, start, stop, body):
    """Each loop has its own break block (depth 1) and continue loop (0)."""
    return (_const(start) + _set(index) + b'\x02\x40\x03\x40'
            + _get(index) + _const(stop) + b'\x4e\x0d\x01'  # ge_s; br_if break
            + body + _get(index) + _const(1) + b'\x6a' + _set(index)
            + b'\x0c\x00\x0b\x0b')  # br continue; end loop; end block


def _index(expr, variables):
    # Keep the model's constant, offset, parity, multiply, accumulate order.
    result = bytearray(_const(expr.constant))
    for term in expr.terms:
        result.extend(_get(variables[term.variable]) + _const(term.offset) + b'\x6a')
        if term.modulo2:
            result.extend(_const(1) + b'\x71')  # mathematical parity, including negatives
        result.extend(_const(term.coefficient) + b'\x6c\x6a')
    return bytes(result)


def _address(expr, variables, base):
    return _index(expr, variables) + _const(4) + b'\x6c' + _const(base) + b'\x6a'


class _Locals:
    """Reuse only locals whose validated lexical scope has ended."""
    def __init__(self):
        self.free = []
        self.count = 0

    def acquire(self):
        if self.free:
            return self.free.pop()
        result = self.count
        self.count += 1
        return result

    def release(self, index):
        self.free.append(index)


def _body(kernel, program, input_count, output_offset, scratch_offset):
    pool = _Locals()
    scan = pool.acquire()
    lower, upper = kernel.input_interval
    load = _get(scan) + _const(4) + b'\x6c\x28\x02\x00'
    # The complete increasing scan precedes every output or scratch store.
    preflight = (load + _const(lower) + b'\x48' + load + _const(upper) + b'\x4a'
                 + b'\x72\x04\x40' + _get(scan) + _const(1) + b'\x6a\x0f\x0b')
    emitted = bytearray(_loop(scan, 0, input_count, preflight))
    pool.release(scan)
    scalars, variables = {}, {}

    def block(nodes):
        code = bytearray()
        definitions = []
        for node in nodes:
            if type(node) is Loop:
                local = pool.acquire()
                variables[node.variable] = local
                child = block(node.body)
                code.extend(_loop(local, node.start, node.stop, child))
                del variables[node.variable]
                pool.release(local)
                continue
            opcode = node.opcode
            if opcode == 'const':
                code.extend(_const(node.value))
            elif opcode in ('input_load', 'scratch_load'):
                base = 0 if opcode == 'input_load' else scratch_offset
                code.extend(_address(node.index, variables, base) + b'\x28\x02\x00')
            elif opcode in ('add', 'mul'):
                code.extend(_get(scalars[node.operands[0]]) + _get(scalars[node.operands[1]]))
                code.append(0x6a if opcode == 'add' else 0x6c)
            else:
                base = scratch_offset if opcode == 'scratch_store' else output_offset
                code.extend(_address(node.index, variables, base))
                code.extend(_get(scalars[node.operands[0]]) + b'\x36\x02\x00')
                continue
            local = pool.acquire()
            scalars[node.dst] = local
            definitions.append(node.dst)
            code.extend(_set(local))
        for name in definitions:
            pool.release(scalars.pop(name))
        return bytes(code)

    emitted.extend(block(program.body))
    emitted.extend(_const(0) + b'\x0b')
    return b'\x01' + _uleb(pool.count) + b'\x7f' + bytes(emitted), pool.count


def _compile_wasm_compact(owned, hint_bytes, *, hint_limits=HintLimits()):
    """Never accept caller-created correspondence as emission authority."""
    _require_owned(owned)
    with owned.owner.phase('loop_correspondence'):
        correspondence = validate_loop_correspondence(
            owned.kernel, owned.plan, hint_bytes, owned.limits, hint_limits)
        owned.owner.count('loop_correspondences')
        owned.owner.count('loop_correspondence_work', correspondence.work_steps)
    with owned.owner.phase('code_emission'):
        input_count, output_count, output_offset, scratch_offset = _layout(owned.kernel, owned.plan)
        body, local_count = _body(owned.kernel, correspondence.program,
                                  input_count, output_offset, scratch_offset)
        module = _module(body)
        return WasmArtifact(module, owned.kernel.height, owned.kernel.width, 0,
                            output_offset, _MEMORY_BYTES, input_count, output_count,
                            owned.kernel.input_interval, owned.checked.source_digest,
                            owned.checked.plan_digest, sha256(module).hexdigest(),
                            CODEGEN_VERSION, correspondence.hint_digest, local_count,
                            CORRESPONDENCE_VERSION)
