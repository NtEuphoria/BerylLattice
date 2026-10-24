"""Private C11 lowering of freshly checked bounded Axiom physical plans.

This backend implements the finite Axiom plan directly; it is independent of
the Core language, its compiler, and its native qualification protocols. Native
stack usage is not the plan's reserved logical scratch metric.
"""
from dataclasses import dataclass
from hashlib import sha256

from .model import DiagnosticError, Limits, REDUCE_PROFILE, WINDOW_PROFILE
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
    codegen_version: str = 'beryl-finite-c-v1'
    hint_digest: str | None = None
    loop_version: str | None = None


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

# Non-canonical and compact artifacts: one bulk read, strict hand parsing and
# buffered output, with the same token rules and exit codes as _DRIVER, whose
# canonical finite bytes are published and stay unchanged.
_FAST_DRIVER = r'''
/* Standalone driver. Standard input is read in one bulk pass, then parsed with
 * the same strict token rules as before: whitespace-separated tokens of at most
 * 63 bytes, an optional sign then decimal digits only, values within i32, the
 * exact count, and nothing but whitespace after the last value. NUL and every
 * other byte that is not whitespace belong to a token, so they reject it. */
static unsigned char *beryl_in;
static size_t beryl_len, beryl_pos;

static int beryl_space(unsigned char c) {
    return c == ' ' || c == '\t' || c == '\n' || c == '\v' || c == '\f' || c == '\r';
}

static int beryl_load(void) {
    size_t cap = 4096;
    beryl_in = malloc(cap);
    if (!beryl_in) return 0;
    for (;;) {
        if (beryl_len == cap) {
            if (cap > SIZE_MAX / 2) return 0;
            unsigned char *grown = realloc(beryl_in, cap * 2);
            if (!grown) return 0;
            beryl_in = grown;
            cap *= 2;
        }
        size_t got = fread(beryl_in + beryl_len, 1, cap - beryl_len, stdin);
        beryl_len += got;
        if (got == 0) return !ferror(stdin);
    }
}

static int beryl_read_i32(int32_t *value) {
    while (beryl_pos < beryl_len && beryl_space(beryl_in[beryl_pos])) ++beryl_pos;
    size_t start = beryl_pos;
    while (beryl_pos < beryl_len && !beryl_space(beryl_in[beryl_pos])) ++beryl_pos;
    size_t length = beryl_pos - start;
    if (length == 0 || length > 63) return 0;
    const unsigned char *token = beryl_in + start;
    size_t index = (token[0] == '+' || token[0] == '-') ? 1 : 0;
    if (index == length) return 0;
    int64_t magnitude = 0;
    for (; index < length; ++index) {
        if (token[index] < '0' || token[index] > '9') return 0;
        magnitude = magnitude * 10 + (token[index] - '0');
        if (magnitude > (int64_t)INT32_MAX + 1) return 0;
    }
    int64_t parsed = token[0] == '-' ? -magnitude : magnitude;
    if (parsed < INT32_MIN || parsed > INT32_MAX) return 0;
    *value = (int32_t)parsed;
    return 1;
}

static int beryl_end_of_input(void) {
    while (beryl_pos < beryl_len)
        if (!beryl_space(beryl_in[beryl_pos++])) return 0;
    return 1;
}

static char beryl_out[1 << 16];
static size_t beryl_used;

static int beryl_flush(void) {
    if (beryl_used && fwrite(beryl_out, 1, beryl_used, stdout) != beryl_used) return 0;
    beryl_used = 0;
    return 1;
}

static int beryl_put(char c) {
    if (beryl_used == sizeof beryl_out && !beryl_flush()) return 0;
    beryl_out[beryl_used++] = c;
    return 1;
}

static int beryl_put_i32(int32_t value) {
    char digits[11];
    int count = 0;
    uint32_t magnitude = value < 0 ? 0u - (uint32_t)value : (uint32_t)value;
    do { digits[count++] = (char)('0' + magnitude % 10); magnitude /= 10; } while (magnitude);
    if (value < 0 && !beryl_put('-')) return 0;
    while (count)
        if (!beryl_put(digits[--count])) return 0;
    return 1;
}

int main(void) {
    int32_t height, width;
    if (!beryl_load()) return 65;
    if (!beryl_read_i32(&height) || !beryl_read_i32(&width) ||
        height != BERYL_HEIGHT || width != BERYL_WIDTH) return 64;
    int32_t input[BERYL_INPUT_COUNT] = {0};
    int32_t output[BERYL_OUTPUT_COUNT] = {0};
    for (int32_t i = 0; i < BERYL_INPUT_COUNT; ++i)
        if (!beryl_read_i32(&input[i])) return 65;
    if (!beryl_end_of_input()) return 65;
    if (beryl_kernel(input, output) != 0) return 66;
    if (!beryl_put('[')) return 74;
    for (int32_t i = 0; i < BERYL_OUTPUT_COUNT; ++i) {
        if (i && !beryl_put(',')) return 74;
        if (!beryl_put_i32(output[i])) return 74;
    }
    if (!beryl_put(']') || !beryl_put('\n') || !beryl_flush() || fflush(stdout) == EOF) return 74;
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
    return _emit_finite(kernel, plan, sha256(source).hexdigest(), sha256(plan_bytes).hexdigest())


def _emit_native_c_checked(owned):
    """Lower only a live successful result retained by its compilation owner."""
    from .compilation import _require_owned
    _require_owned(owned)
    with owned.owner.phase('code_emission'):
        return _emit_finite(owned.kernel, owned.plan, owned.checked.source_digest,
                            owned.checked.plan_digest)


def _emit_finite(kernel, plan, source_digest, plan_digest):
    # Window-stencil and reduce-v1 kernels have no legacy published bytes: give them the
    # compact path's reduction preflight and restrict-qualified contract.
    window = kernel.profile in (WINDOW_PROFILE, REDUCE_PROFILE)
    parts = _native_kernel_parts(kernel, plan, disjoint_parameters=window, reduction_preflight=window)
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
    return _finish_native(parts, kernel, source_digest, plan_digest,
                          driver=_FAST_DRIVER if window else _DRIVER)


def _native_kernel_parts(kernel, plan, *, comment=None, disjoint_parameters=False,
                         reduction_preflight=False):
    """Shared preflight and storage contract; keep legacy emitted bytes stable."""
    input_count = kernel.input_count
    output_count = kernel.height * kernel.width
    if max(input_count, output_count, plan.scratch_capacity_cells) > 256:
        raise DiagnosticError('BACKEND_STORAGE_LIMIT', kernel.source_module.span,
                              'native fixed storage exceeds 256 scalar cells')

    qualifier = 'restrict ' if disjoint_parameters else ''

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
int32_t beryl_kernel(const int32_t *{qualifier}input, int32_t *{qualifier}output) {{
''']
    if comment is not None:
        parts[0] = comment + '\n' + parts[0].partition('\n')[2]
    lower, upper = kernel.input_interval
    if reduction_preflight:
        # Every borrowed input cell is initialized and stable for this call.
        # Reduce validity without scalar early exits on the success path; on
        # rejection recover the same first invalid index before any effects.
        parts.append(f'''    uint32_t ax_invalid = 0;
    for (int32_t i = 0; i < {input_count}; ++i)
        ax_invalid |= (uint32_t)(input[i] < {lower} || input[i] > {upper});
    if (ax_invalid) {{
        for (int32_t i = 0; i < {input_count}; ++i)
            if (input[i] < {lower} || input[i] > {upper}) return i + 1;
    }}
''')
    else:
        parts.append(f'''    for (int32_t i = 0; i < {input_count}; ++i)
        if (input[i] < {lower} || input[i] > {upper}) return i + 1;
''')
    if plan.scratch_capacity_cells:
        parts.append(f'    int32_t scratch[{plan.scratch_capacity_cells}] = {{0}};\n'
                     '    (void)scratch;\n')
    return parts


def _finish_native(parts, kernel, source_digest, plan_digest, *,
                   codegen_version='beryl-finite-c-v1', hint_digest=None,
                   loop_version=None, driver=None):
    """Share the bounded token driver and exact artifact byte identities."""
    parts.append('    return 0;\n}\n')
    parts.append(_FAST_DRIVER if driver is None else driver)
    generated = ''.join(parts).encode('ascii')
    return NativeArtifact(generated, kernel.height, kernel.width,
                          kernel.input_count, kernel.height*kernel.width,
                          source_digest, plan_digest, sha256(generated).hexdigest(),
                          codegen_version, hint_digest, loop_version)
