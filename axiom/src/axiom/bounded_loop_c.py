"""Private lexical C lowering of freshly matched bounded beryl loop hints.

Hints are scheduling intent only. Each emission requires a live owned successful
finite check and independently expands the exact hint bytes against that plan.
The finite backend remains the fallback for arbitrary admitted finite programs.
"""
from hashlib import sha256

from .bounded_loop_model import HintLimits, Loop
from .native_codegen import _native_kernel_parts, _finish_native

CODEGEN_VERSION = 'beryl-bounded-loop-c-v1'


def _emit_native_c_compact(owned, hint_bytes, *, hint_limits=HintLimits()):
    """Emit only the exact structured program validated in this same call.

    A caller-created correspondence record is deliberately not an argument.
    Native pointer ownership, full preflight and rejection state preservation
    have the same contract as the straight-stream emitter.
    """
    from .compilation import _require_owned
    from .bounded_loop_correspondence import validate_loop_correspondence
    _require_owned(owned)
    with owned.owner.phase('loop_correspondence'):
        correspondence = validate_loop_correspondence(
            owned.kernel, owned.plan, hint_bytes, owned.limits, hint_limits)
        owned.owner.count('loop_correspondences')
        owned.owner.count('loop_correspondence_work', correspondence.work_steps)
    with owned.owner.phase('code_emission'):
        parts = _native_kernel_parts(
            owned.kernel, owned.plan,
            comment='/* Generated from a freshly checked beryl bounded loop program. */')
        serial = 0

        def index(expr, indent):
            """Preserve offset, parity, multiply, accumulation order exactly.

            Fresh correspondence checks every reached intermediate and counter
            bound in i32. Widen before each arithmetic operation in C anyway;
            unsigned parity gives mathematical modulo two for negative values.
            """
            nonlocal serial
            serial += 1
            name = f'ax_index_{serial}'
            parts.append(f'{indent}int32_t {name} = (int32_t)({expr.constant}LL);\n')
            for number, term in enumerate(expr.terms):
                component = f'ax_term_{serial}_{number}'
                parts.append(f'{indent}int32_t {component} = (int32_t)((int64_t)ax_i_{term.variable} + {term.offset}LL);\n')
                if term.modulo2:
                    parts.append(f'{indent}{component} = (int32_t)((uint32_t){component} & UINT32_C(1));\n')
                parts.append(f'{indent}{component} = (int32_t)({term.coefficient}LL * (int64_t){component});\n')
                parts.append(f'{indent}{name} = (int32_t)((int64_t){name} + (int64_t){component});\n')
            return name

        def block(body, depth):
            indent = '    '*depth
            for node in body:
                if type(node) is Loop:
                    # Fresh correspondence already validated this entire body.
                    # Zero iterations expand to no finite primitives; emitting
                    # the body could mention an arena with no reservation.
                    if node.start == node.stop:
                        continue
                    variable = f'ax_i_{node.variable}'
                    parts.append(f'{indent}for (int32_t {variable} = {node.start}; {variable} < {node.stop}; ++{variable}) {{\n')
                    block(node.body, depth+1)
                    parts.append(f'{indent}}}\n')
                    continue
                operands = tuple(f'ax_v_{name}' for name in node.operands)
                address = index(node.index, indent) if node.index is not None else None
                if node.opcode in ('scratch_store', 'output_store'):
                    arena = 'scratch' if node.opcode == 'scratch_store' else 'output'
                    parts.append(f'{indent}{arena}[{address}] = {operands[0]};\n')
                    continue
                if node.opcode == 'const':
                    expression = f'(int32_t)({node.value}LL)'
                elif node.opcode in ('input_load', 'scratch_load'):
                    arena = 'input' if node.opcode == 'input_load' else 'scratch'
                    expression = f'{arena}[{address}]'
                else:
                    # The fresh strict hint decoder admits precisely add/mul
                    # here, and correspondence includes dead operations too.
                    operator = '+' if node.opcode == 'add' else '*'
                    expression = f'(int32_t)((int64_t){operands[0]} {operator} (int64_t){operands[1]})'
                parts.append(f'{indent}const int32_t ax_v_{node.dst} = {expression};\n'
                             f'{indent}(void)ax_v_{node.dst};\n')

        block(correspondence.program.body, 1)
        artifact = _finish_native(parts, owned.kernel, owned.checked.source_digest,
                                  owned.checked.plan_digest, codegen_version=CODEGEN_VERSION,
                                  hint_digest=sha256(hint_bytes).hexdigest(),
                                  loop_version=correspondence.version)
        owned.owner.count('code_emissions')
        return artifact
