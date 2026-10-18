"""Private C11 lowering of freshly checked bounded Axiom physical plans.

This backend implements the finite Axiom plan directly; it is independent of
the Core language, its compiler, and its native qualification protocols. Native
stack usage is not the plan's reserved logical scratch metric.
"""
from dataclasses import dataclass
from hashlib import sha256

from .model import DiagnosticError, Limits
from .runtime import _checked_plan


@dataclass(frozen=True, slots=True)
class NativeArtifact:
    c_source: bytes
    height: int
    width: int
    input_count: int
    output_count: int
    source_digest: str
    plan_digest: str
    c_digest: str


_DRIVER = r'''
/* Read a bounded token before numeric conversion. %n counts at most 63 bytes;
 * whitespace is consumed separately so embedded NUL bytes cannot hide a suffix.
 * Reading one separator also prevents a long token from becoming two numbers. */
static int beryl_read_i32(int32_t *value) {
    char token[64];
    int length = 0;
    int next;
    do { next = fgetc(stdin); }
    while (next != EOF && isspace((unsigned char)next));
    if (next == EOF || ungetc(next, stdin) == EOF) return 0;
    if (scanf("%63s%n", token, &length) != 1) return 0;
    next = fgetc(stdin);
    if ((next != EOF && !isspace((unsigned char)next)) || ferror(stdin)) return 0;
    int index = (token[0] == '+' || token[0] == '-') ? 1 : 0;
    if (index == length) return 0;
    for (; index < length; ++index)
        if (token[index] < '0' || token[index] > '9') return 0;
    errno = 0;
    char *end;
    long long parsed = strtoll(token, &end, 10);
    if (errno == ERANGE || end != token + length ||
        parsed < INT32_MIN || parsed > INT32_MAX) return 0;
    *value = (int32_t)parsed;
    return 1;
}

static int beryl_end_of_input(void) {
    int next;
    while ((next = fgetc(stdin)) != EOF)
        if (!isspace((unsigned char)next)) return 0;
    return !ferror(stdin);
}

int main(void) {
    int32_t height, width;
    if (!beryl_read_i32(&height) || !beryl_read_i32(&width) ||
        height != BERYL_HEIGHT || width != BERYL_WIDTH) return 64;
    int32_t input[BERYL_INPUT_COUNT] = {0};
    int32_t output[BERYL_OUTPUT_COUNT] = {0};
    for (int32_t i = 0; i < BERYL_INPUT_COUNT; ++i)
        if (!beryl_read_i32(&input[i])) return 65;
    if (!beryl_end_of_input()) return 65;
    if (beryl_kernel(input, output) != 0) return 66;
    if (putchar('[') == EOF) return 74;
    for (int32_t i = 0; i < BERYL_OUTPUT_COUNT; ++i) {
        if (i && putchar(',') == EOF) return 74;
        if (printf("%" PRId32, output[i]) < 0) return 74;
    }
    if (puts("]") == EOF || fflush(stdout) == EOF) return 74;
    return 0;
}
'''


def emit_native_c(source: bytes, plan_bytes: bytes,
                  limits: Limits = Limits()) -> NativeArtifact:
    """Emit a reusable program only after fresh source/plan/proof admission.

    ``beryl_kernel`` borrows exclusively owned, disjoint, initialized int32_t
    arrays of the emitted exact counts for the entire synchronous call. Raw
    pointers do not establish this contract; the standalone driver owns those
    arrays. Success returns zero; rejection returns the first invalid index
    plus one, preserving all input and initialized output cells.

    All seven physical opcodes are lowered in their actual plan order. Checked
    i32 interval proofs cover every operation, including dead operations. Add
    and multiply first evaluate in int64_t, where any two i32 operands fit,
    before the proved in-range conversion to int32_t.
    """
    kernel, plan, checked = _checked_plan(source, plan_bytes, limits)
    input_count = (kernel.height + 1) * (kernel.width + 1)
    output_count = kernel.height * kernel.width
    if max(input_count, output_count, plan.scratch_capacity_cells) > 256:
        raise DiagnosticError('BACKEND_STORAGE_LIMIT', kernel.source_module.span,
                              'native fixed storage exceeds 256 scalar cells')

    parts = ['''/* Generated from a freshly checked finite Axiom physical plan. */
#include <ctype.h>
#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

_Static_assert(CHAR_BIT == 8, "eight-bit bytes required");
_Static_assert(sizeof(int32_t) == 4, "four-byte i32 required");
_Static_assert(sizeof(int64_t) == 8, "eight-byte i64 required");
''', f'''enum {{ BERYL_HEIGHT = {kernel.height}, BERYL_WIDTH = {kernel.width},
       BERYL_INPUT_COUNT = {input_count}, BERYL_OUTPUT_COUNT = {output_count} }};

/* Caller owns disjoint initialized arrays of the exact compiled counts.
 * No alias, offset view, concurrent access, or lifetime change is permitted. */
int32_t beryl_kernel(const int32_t *input, int32_t *output) {{
''']
    lower, upper = kernel.input_interval
    parts.append(f'''    for (int32_t i = 0; i < {input_count}; ++i)
        if (input[i] < {lower} || input[i] > {upper}) return i + 1;
''')
    if plan.scratch_capacity_cells:
        parts.append(f'    int32_t scratch[{plan.scratch_capacity_cells}] = {{0}};\n'
                     '    (void)scratch;\n')
    for operation in plan.operations:
        opcode = operation.opcode
        if opcode in ('scratch_store', 'output_store'):
            destination = 'scratch' if opcode == 'scratch_store' else 'output'
            parts.append(f'    {destination}[{operation.index}] = ax_v{operation.operands[0]};\n')
            continue
        if opcode == 'const':
            expression = f'(int32_t)({operation.value}LL)'
        elif opcode == 'input_load':
            expression = f'input[{operation.index}]'
        elif opcode == 'scratch_load':
            expression = f'scratch[{operation.index}]'
        elif opcode in ('add', 'mul'):
            left, right = operation.operands
            operator = '+' if opcode == 'add' else '*'
            expression = f'(int32_t)((int64_t)ax_v{left} {operator} (int64_t)ax_v{right})'
        else:
            raise DiagnosticError('BACKEND_UNSUPPORTED_OPERATION', kernel.source_module.span,
                                  'native backend cannot lower the checked opcode')
        parts.append(f'    const int32_t ax_v{operation.dst} = {expression};\n'
                     f'    (void)ax_v{operation.dst};\n')
    parts.append('    return 0;\n}\n')
    parts.append(_DRIVER)
    generated = ''.join(parts).encode('ascii')
    return NativeArtifact(generated, kernel.height, kernel.width, input_count,
                          output_count, sha256(source).hexdigest(), sha256(plan_bytes).hexdigest(),
                          sha256(generated).hexdigest())
