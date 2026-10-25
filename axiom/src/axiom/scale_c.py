"""C11 loops for checked scale-v1 loop plans.

Emission happens only after scale_checker proves the plan against fresh
source. Arithmetic is plain int32_t: the checker's interval proof shows no +,
* or partial sum (in any order) leaves i32, so nothing overflows and the C
compiler may vectorize and reassociate accumulations. A program with an i64
equation computes every value in int64_t instead (each node is proved to fit
its own equation's type, so i32 nodes keep their exact values), and an i64
output is an int64_t array. Index arithmetic is int64_t. The branch-free input preflight runs before any output is written;
on rejection the first invalid index plus one is returned.

Large kernels split their cells across a persistent worker pool. The proved
store index v0*W + v1 writes every cell exactly once, the producer is inlined
and sum accumulators are locals, so disjoint cell ranges never share a written
location, inputs are only read, and the result does not depend on the thread
count. The parallel preflight completes before any cell is computed.
"""
from dataclasses import dataclass
from hashlib import sha256

from .model import Limits
from .native_codegen import _FAST_DRIVER, NativeArtifact
from .scale_carry import c_types, carry_eligible, carry_rows_c, plan_costs, rank_key
from .scale_plan import SCALE_PLAN_IDS
from .scale_pool import _POOL
from .scale_checker import check_loop_plan
from .scale_plan import make_scale_plan
from .frontend import admit_source, parse_source

SCALE_CODEGEN_VERSION = 'beryl-loop-c-v1'
SCALE_PARALLEL_CODEGEN_VERSION = 'beryl-loop-c-parallel-v1'
# Below this many estimated scalar operations a call stays single-threaded:
# a pool dispatch costs about a microsecond, so tiny kernels would lose.
PARALLEL_MIN_WORK = 1 << 16
PARALLEL_MIN_INPUT = 1 << 16
# Outputs at least this large bypass the cache with non-temporal stores.
STREAM_MIN_BYTES = 8 << 20

_HEADER = '''/* Generated from a template-checked scale-v1 loop plan (PLAN_ID). */
#include <ctype.h>
#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

_Static_assert(sizeof(int32_t) == 4, "four-byte i32 required");
_Static_assert(sizeof(int64_t) == 8, "eight-byte i64 required");
'''




_PUT_I64 = '''static int beryl_put_i64(int64_t value) {
    char digits[20];
    int count = 0;
    uint64_t magnitude = value < 0 ? 0u - (uint64_t)value : (uint64_t)value;
    do { digits[count++] = (char)('0' + magnitude % 10); magnitude /= 10; } while (magnitude);
    if (value < 0 && !beryl_put('-')) return 0;
    while (count)
        if (!beryl_put(digits[--count])) return 0;
    return 1;
}
'''


def _affine(value):
    constant, terms = value
    parts = [f'(int64_t){constant}'] + [f'(int64_t){k} * {var}' for var, k in terms]
    return ' + '.join(parts)


def _literal(value):
    return '(-2147483647 - 1)' if value == -2147483648 else f'{value}'


_I32_MIN, _I32_MAX = -2 ** 31, 2 ** 31 - 1


def _narrow_block(expr, lower, upper, prod_interval=None):
    """Terms per exact int32_t block of the sum `expr` in a wide program, or None.

    The plan expression equals the checked source template, so these are the
    checker's intervals. When every node of the body fits i32, the body
    evaluates exactly in int32_t, and any run of I32_MAX // max|term|
    consecutive terms sums exactly in int32_t too. Each block is widened
    before it is added, so the sum vectorizes like an i32 sum. For an
    expression that is not a sum, returns its interval when every node fits
    i32 (the producer interval for ('prod', i, j) leaves), else None.
    """
    def interval(e):
        kind = e[0]
        if kind == 'const':
            result = (e[1], e[1])
        elif kind == 'load':
            result = (lower, upper)
        elif kind == 'prod':
            result = prod_interval
        elif kind in ('add', 'mul'):
            a, b = interval(e[1]), interval(e[2])
            if a is None or b is None:
                return None
            ends = (a[0] * b[0], a[0] * b[1], a[1] * b[0], a[1] * b[1])
            result = (a[0] + b[0], a[1] + b[1]) if kind == 'add' else (min(ends), max(ends))
        else:
            body = interval(e[4])
            if body is None or (e[3] - e[2]) * max(abs(body[0]), abs(body[1])) > _I32_MAX:
                return None
            result = ((e[3] - e[2]) * body[0], (e[3] - e[2]) * body[1])
        if result is None or result[0] < _I32_MIN or result[1] > _I32_MAX:
            return None
        return result
    if expr[0] != 'sum':
        return interval(expr)
    body = interval(expr[4])
    return None if body is None else max(1, _I32_MAX // max(1, abs(body[0]), abs(body[1])))


def _lower(expr, statements, counter, prod=None, wide=False, narrow=None):
    """C for a plan expression; `wide` computes in int64_t (loads and literals widened).

    `narrow(sum_expr)`, when given, returns the exact int32_t block length of a
    wide sum (see _narrow_block) or None. A narrow sum's body is lowered as
    plain int32_t, which _narrow_block showed exact for every node.
    """
    kind = expr[0]
    if kind == 'prod':
        return prod(expr[1], expr[2])
    if kind == 'const':
        return f'((int64_t){_literal(expr[1])})' if wide else _literal(expr[1])
    if kind == 'load':
        return f'(int64_t)input[{_affine(expr[1])}]' if wide else f'input[{_affine(expr[1])}]'
    if kind in ('add', 'mul'):
        operator = '+' if kind == 'add' else '*'
        left = _lower(expr[1], statements, counter, prod, wide, narrow)
        right = _lower(expr[2], statements, counter, prod, wide, narrow)
        return f'({left} {operator} {right})'
    _, var, lower, upper, body = expr
    name = f'ax_s{next(counter)}'
    block = narrow(expr) if wide and narrow else None
    inner = []
    if block is not None:
        # Exact int32_t blocks of `block` terms, each widened once (_narrow_block).
        value = _lower(body, inner, counter, prod)
        loop = [f'int32_t {name}_b = 0;',
                f'for (int32_t {var} = {name}_k; {var} < {name}_e; ++{var}) {{',
                *('    ' + line for line in inner), f'    {name}_b += {value};', '}']
        if upper - lower <= block:
            statements.extend(line.replace(f'{name}_k', str(lower)).replace(f'{name}_e', str(upper))
                              for line in loop)
            return f'((int64_t){name}_b)'
        statements.append(f'int64_t {name} = 0;')
        statements.append(f'for (int32_t {name}_k = {lower}; {name}_k < {upper}; {name}_k += {block}) {{')
        statements.append(f'    int32_t {name}_e = {upper} - {name}_k < {block} ? {upper} : {name}_k + {block};')
        statements.extend('    ' + line for line in loop)
        statements.append(f'    {name} += {name}_b;')
        statements.append('}')
        return name
    value = _lower(body, inner, counter, prod, wide, narrow)
    statements.append(f'{"int64_t" if wide else "int32_t"} {name} = 0;')
    statements.append(f'for (int32_t {var} = {lower}; {var} < {upper}; ++{var}) {{')
    statements.extend('    ' + line for line in inner)
    statements.append(f'    {name} += {value};')
    statements.append('}')
    return name


def _work_estimate(expr):
    """Scalar operations per output cell, with sum ranges multiplied out."""
    kind = expr[0]
    if kind in ('const', 'load'):
        return 1
    if kind in ('add', 'mul'):
        return 1 + _work_estimate(expr[1]) + _work_estimate(expr[2])
    return (expr[3] - expr[2]) * (1 + _work_estimate(expr[4]))


def _has_sum(expr):
    if expr[0] == 'sum':
        return True
    return expr[0] in ('add', 'mul') and (_has_sum(expr[1]) or _has_sum(expr[2]))


def _reads_var(expr, var):
    if expr[0] == 'load':
        return any(name == var for name, _ in expr[1][1])
    if expr[0] in ('add', 'mul'):
        return _reads_var(expr[1], var) or _reads_var(expr[2], var)
    return expr[0] == 'sum' and _reads_var(expr[4], var)


def _row_accumulation(stage, v0, v1, w, wide=False, value='int32_t', out='int32_t'):
    """Cells loop for a value that is one sum with a sum-free body reading v1.

    Each row segment keeps one accumulator per cell; the sum variable runs in
    the outer loop and the columns in the inner one, so loads along v1 are
    contiguous and vectorize. Every cell still adds its terms in ascending
    sum-variable order, exactly as the direct loop does. Segments wider than
    the stack buffer use a heap buffer, or the direct loop if that fails.
    """
    _, var, lower, upper, body = stage.value
    term = _lower(body, [], iter(range(1 << 30)), None, wide)
    direct = _lower(stage.value, statements := [], iter(range(1 << 30)), None, wide)
    direct_body = '\n'.join('                ' + line for line in statements)
    index = _affine(stage.index)
    return ('\n/* Compute cells [from, to): one sum per cell, accumulated a row segment at a time. */\n'
            f'static void beryl_cells(const int32_t *restrict input, {out} *restrict output,\n'
            '                        int64_t from, int64_t to) {\n'
            f'    {value} stack[1024];\n'
            f'    {value} *acc = {w} <= 1024 ? stack : malloc(sizeof({value}) * (size_t){w});\n'
            f'    int32_t {v0} = (int32_t)(from / {w}), first = (int32_t)(from % {w});\n'
            f'    for (int64_t at = from; at < to; ++{v0}, first = 0) {{\n'
            f'        int32_t last = (to - at < (int64_t)({w} - first)) ? first + (int32_t)(to - at) : {w};\n'
            '        if (acc) {\n'
            f'            for (int32_t {v1} = first; {v1} < last; ++{v1}) acc[{v1} - first] = 0;\n'
            f'            for (int32_t {var} = {lower}; {var} < {upper}; ++{var})\n'
            f'                for (int32_t {v1} = first; {v1} < last; ++{v1}) acc[{v1} - first] += {term};\n'
            f'            for (int32_t {v1} = first; {v1} < last; ++{v1}) output[{index}] = acc[{v1} - first];\n'
            '        } else {\n'
            f'            for (int32_t {v1} = first; {v1} < last; ++{v1}) {{\n'
            f'{direct_body}\n'
            f'                output[{index}] = {direct};\n'
            '            }\n'
            '        }\n'
            '        at += last - first;\n'
            '    }\n'
            '    if (acc != stack) free(acc);\n'
            '}\n')


def _streaming_cells(stage, v0, v1, w, body, value):
    """Cells loop for outputs too large for cache.

    Each block of up to 64 cells of a row is computed into an aligned stack
    buffer by a loop that still vectorizes, then copied to the output with
    SSE2 non-temporal stores, which skip reading the output lines first. The
    proved store index v0*W + v1 makes a block contiguous in the output. An
    sfence at the end of every chunk orders those stores before the chunk is
    reported done, so whoever reads the output next sees every value.
    Without SSE2 the copy uses ordinary stores.
    """
    inner = '\n'.join('    ' + line for line in body.splitlines())
    return ('\n#if defined(__SSE2__)\n#include <emmintrin.h>\n#endif\n'
            '/* Copy n cells to dst, streaming every aligned group of four. */\n'
            'static void beryl_stream(int32_t *restrict dst, const int32_t *restrict src, int32_t n) {\n'
            '    int32_t k = 0;\n'
            '#if defined(__SSE2__)\n'
            '    for (; k < n && ((uintptr_t)(dst + k) & 15u); ++k) dst[k] = src[k];\n'
            '    for (; k + 4 <= n; k += 4)\n'
            '        _mm_stream_si128((__m128i *)(void *)(dst + k), _mm_loadu_si128((const __m128i *)(const void *)(src + k)));\n'
            '#endif\n'
            '    for (; k < n; ++k) dst[k] = src[k];\n'
            '}\n'
            '\n/* Compute cells [from, to) in row-major order, 64-cell blocks streamed out. */\n'
            'static void beryl_cells(const int32_t *restrict input, int32_t *restrict output,\n'
            '                        int64_t from, int64_t to) {\n'
            '    int32_t block[64] __attribute__((aligned(16)));\n'
            f'    int32_t {v0} = (int32_t)(from / {w}), first = (int32_t)(from % {w});\n'
            f'    for (int64_t at = from; at < to; ++{v0}, first = 0) {{\n'
            f'        int32_t last = (to - at < (int64_t)({w} - first)) ? first + (int32_t)(to - at) : {w};\n'
            '        for (int32_t start = first; start < last; start += 64) {\n'
            '            int32_t end = last - start < 64 ? last : start + 64;\n'
            f'            for (int32_t {v1} = start; {v1} < end; ++{v1}) {{\n'
            f'{inner}\n'
            f'                block[{v1} - start] = {value};\n'
            '            }\n'
            f'            beryl_stream(output + (int64_t){w} * {v0} + start, block, end - start);\n'
            '        }\n'
            '        at += last - first;\n'
            '    }\n'
            '#if defined(__SSE2__)\n'
            '    _mm_sfence();\n'
            '#endif\n'
            '}\n')


def emit_scale_c(kernel, plan, source_digest, plan_digest) -> NativeArtifact:
    """Emit C for a plan that check_loop_plan has just proved for `kernel`."""
    stage = plan.stages[-1]
    carry = len(plan.stages) == 2
    wide = kernel.wide
    val, out = c_types(kernel)
    (v0, h), (v1, w) = stage.loops
    statements = []
    counter = iter(range(1 << 30))
    lower, upper = kernel.input_interval
    prod_interval = _narrow_block(plan.stages[0].value, lower, upper) if carry else None
    narrow = (lambda e: _narrow_block(e, lower, upper, prod_interval)) if wide else None
    value = None if carry else _lower(stage.value, statements, counter, None, wide, narrow)
    n_in, n_out = kernel.input_count, kernel.height * kernel.width
    body = '\n'.join('            ' + line for line in statements)
    # A single cell whose value is one large sum: split the sum range instead.
    # Any subset of its terms is bounded by the same proof as the whole sum.
    split = (not carry and n_out == 1 and stage.value[0] == 'sum' and not _has_sum(stage.value[4])
             and _work_estimate(stage.value) >= PARALLEL_MIN_WORK)
    per_cell = plan_costs(plan, kernel)[1] if carry else _work_estimate(stage.value)
    parallel = split or (n_out >= 32 and h >= 2 and n_out * per_cell >= PARALLEL_MIN_WORK) or (
        not carry and n_out >= 32 and n_out * per_cell >= PARALLEL_MIN_WORK)
    parallel_preflight = parallel and n_in >= PARALLEL_MIN_INPUT
    invalid = f'(uint32_t)(input[i] < {lower} || input[i] > {upper})'
    rows = (not carry and stage.value[0] == 'sum' and not _has_sum(stage.value[4])
            and _reads_var(stage.value[4], v1) and w >= 8)
    # Single-row outputs larger than the last-level cache: write through
    # non-temporal stores, which skip reading each output line before
    # overwriting it. Measured 1.5x on 4M-cell maps and 1-D stencils; 2-D
    # stencils read several input rows per output row and gained nothing
    # (sq2x2 lost), so they keep ordinary stores.
    # The streaming copy moves int32_t cells, so i64 programs keep ordinary stores.
    stream = not carry and not rows and not wide and h == 1 and n_out * 4 >= STREAM_MIN_BYTES
    if carry:
        cells = carry_rows_c(plan, kernel, lambda e, s, c, p: _lower(e, s, c, p, wide, narrow))
    elif stream:
        cells = _streaming_cells(stage, v0, v1, w, body, value)
    else:
        cells = _row_accumulation(stage, v0, v1, w, wide, val, out) if rows else (
        '\n/* Compute cells [from, to) in row-major order. */\n'
        f'static void beryl_cells(const int32_t *restrict input, {out} *restrict output,\n'
        '                        int64_t from, int64_t to) {\n'
        f'    int32_t {v0} = (int32_t)(from / {w}), first = (int32_t)(from % {w});\n'
        f'    for (int64_t at = from; at < to; ++{v0}, first = 0) {{\n'
        f'        int32_t last = (to - at < (int64_t)({w} - first)) ? first + (int32_t)(to - at) : {w};\n'
        f'        for (int32_t {v1} = first; {v1} < last; ++{v1}) {{\n'
        f'{body}\n'
        f'            output[{_affine(stage.index)}] = {value};\n'
        '        }\n'
        '        at += last - first;\n'
        '    }\n'
        '}\n')
    parts = [_HEADER.replace('PLAN_ID', plan.plan_id),
             f'enum {{ BERYL_HEIGHT = {kernel.height}, BERYL_WIDTH = {kernel.width},\n'
             f'       BERYL_INPUT_COUNT = {n_in}, BERYL_OUTPUT_COUNT = {n_out} }};\n',
             cells]
    split_chunk = ''
    if split:
        _, var, s_lo, s_hi, s_body = stage.value
        block = narrow(stage.value) if narrow else None
        if block is None:
            term = _lower(s_body, [], iter(range(1 << 30)), None, wide)
            loop = f'    for (int32_t {var} = (int32_t)from; {var} < (int32_t)to; ++{var}) acc += {term};\n'
        else:
            # Exact int32_t blocks, each widened once (_narrow_block).
            term = _lower(s_body, [], iter(range(1 << 30)))
            loop = (f'    for (int64_t ax_k = from; ax_k < to; ax_k += {block}) {{\n'
                    f'        int64_t ax_e = to - ax_k < {block} ? to : ax_k + {block};\n'
                    '        int32_t ax_b = 0;\n'
                    f'        for (int32_t {var} = (int32_t)ax_k; {var} < (int32_t)ax_e; ++{var}) ax_b += {term};\n'
                    '        acc += ax_b;\n'
                    '    }\n')
        parts.append('\n/* Partial sum of the single cell over [from, to) of its sum range. */\n'
                     f'static {val} beryl_partial(const int32_t *restrict input, int64_t from, int64_t to) {{\n'
                     f'    const int32_t {v0} = 0, {v1} = 0;\n'
                     f'    (void){v0}; (void){v1};\n'
                     f'    {val} acc = 0;\n'
                     + loop +
                     '    return acc;\n'
                     '}\n')
        split_chunk = ('    } else if (beryl_job_phase == 2) {\n'
                       f'        beryl_job_partial[c] = from < to ? beryl_partial(input, {s_lo} + from, {s_lo} + to) : 0;\n')
    if parallel:
        parts.append(_POOL.replace('static int32_t *beryl_job_output;', f'static {out} *beryl_job_output;')
                     .replace('static int32_t beryl_job_partial', f'static {val} beryl_job_partial')
                     .replace('const int32_t *input, int32_t *output)', f'const int32_t *input, {out} *output)'))
        parts.append('\nstatic void beryl_run_chunk(int c) {\n'
                     '    int64_t from = beryl_job_begin[c], to = beryl_job_begin[c + 1];\n'
                     '    const int32_t *input = beryl_job_input;\n'
                     '    if (beryl_job_phase == 0) {\n'
                     '        uint32_t invalid = 0;\n'
                     f'        for (int64_t i = from; i < to; ++i) invalid |= {invalid};\n'
                     '        beryl_job_invalid[c] = invalid;\n'
                     + split_chunk +
                     '    } else if (from < to) {\n'
                     + ('        beryl_rows(input, beryl_job_output, from, to);\n' if carry else
                        '        beryl_cells(input, beryl_job_output, from, to);\n') +
                     '    }\n'
                     '}\n')
    parts.append('\n/* Caller owns disjoint initialized arrays of the exact compiled counts. */\n'
                 f'int32_t beryl_kernel(const int32_t *restrict input, {out} *restrict output) {{\n')
    if parallel:
        parts.append('    int threads = beryl_pool();\n')
    parts.append('    uint32_t ax_invalid = 0;\n')
    if parallel_preflight:
        parts.append('    if (threads > 1) {\n'
                     f'        beryl_dispatch(0, {n_in}, 16, 4, input, output);\n'
                     '        for (int c = 0; c < beryl_job_chunks; ++c) ax_invalid |= beryl_job_invalid[c];\n'
                     '    } else {\n'
                     f'        for (int64_t i = 0; i < {n_in}; ++i) ax_invalid |= {invalid};\n'
                     '    }\n')
    else:
        parts.append(f'    for (int64_t i = 0; i < {n_in}; ++i) ax_invalid |= {invalid};\n')
    parts.append('    if (ax_invalid) {\n'
                 f'        for (int64_t i = 0; i < {n_in}; ++i)\n'
                 f'            if (input[i] < {lower} || input[i] > {upper}) return (int32_t)(i + 1);\n'
                 '    }\n')
    if split:
        parts.append('    if (threads > 1) {\n'
                     f'        beryl_dispatch(2, {s_hi - s_lo}, 16, 4, input, output);\n'
                     f'        {val} total = 0;\n'
                     '        for (int c = 0; c < beryl_job_chunks; ++c) total += beryl_job_partial[c];\n'
                     f'        output[{stage.index[0]}] = total;\n'
                     f'    }} else beryl_cells(input, output, 0, {n_out});\n')
    elif parallel and carry:
        parts.append(f'    if (threads > 1) beryl_dispatch(1, {h}, 1, 1, input, output);\n'
                     f'    else beryl_rows(input, output, 0, {h});\n')
    elif parallel:
        parts.append(f'    if (threads > 1) beryl_dispatch(1, {n_out}, 16, 4, input, output);\n'
                     f'    else beryl_cells(input, output, 0, {n_out});\n')
    elif carry:
        parts.append(f'    beryl_rows(input, output, 0, {h});\n')
    else:
        parts.append(f'    beryl_cells(input, output, 0, {n_out});\n')
    parts.append('    return 0;\n}\n')
    # Large buffers live in static storage, not on the driver's stack.
    assert '= {0};' in _FAST_DRIVER
    driver = (_FAST_DRIVER.replace('    int32_t input[BERYL_INPUT_COUNT] = {0};',
                                   '    static int32_t input[BERYL_INPUT_COUNT];')
              .replace('    int32_t output[BERYL_OUTPUT_COUNT] = {0};',
                       f'    static {out} output[BERYL_OUTPUT_COUNT];'))
    if out == 'int64_t':
        # i64 outputs print through a 64-bit formatter in place of the i32 one.
        start = driver.index('static int beryl_put_i32(int32_t value) {')
        end = driver.index('\n}\n', start) + 3
        driver = (driver[:start] + _PUT_I64 + driver[end:]).replace(
            'beryl_put_i32(output[i])', 'beryl_put_i64(output[i])')
    generated = (''.join(parts) + driver).encode('ascii')
    version = SCALE_PARALLEL_CODEGEN_VERSION if parallel else SCALE_CODEGEN_VERSION
    return NativeArtifact(generated, kernel.height, kernel.width, n_in, n_out, source_digest,
                          plan_digest, sha256(generated).hexdigest(), version, None, plan.format)


@dataclass(frozen=True, slots=True)
class ScaleCompilation:
    kernel: object
    check: object
    artifact: NativeArtifact | None
    reason: str
    plan: object = None


def compile_scale_native(source: bytes, limits: Limits = Limits()) -> ScaleCompilation:
    """Fresh admission; every portfolio plan generated and template-checked; the
    best proved plan by the program's objective emitted (see scale_carry.rank_key)."""
    kernel = admit_source(parse_source(source, limits))
    proved, first_failure = [], None
    for order, plan_id in enumerate(SCALE_PLAN_IDS):
        try:
            plan = make_scale_plan(kernel, plan_id, max_nodes=limits.plan_operations)
        except Exception as error:  # an untrusted generator may fail in any way
            failure = ScaleCompilation(kernel, None, None, getattr(error, 'code', type(error).__name__))
            first_failure = first_failure or failure
            continue
        check = check_loop_plan(source, plan, limits)
        if not check.valid:
            first_failure = first_failure or ScaleCompilation(kernel, check, None, check.reason, plan)
            continue
        if carry_eligible(plan, kernel):
            proved.append((rank_key(plan, kernel, order), plan, check))
    if not proved:
        return first_failure
    _, plan, check = min(proved, key=lambda item: item[0])
    return ScaleCompilation(kernel, check, emit_scale_c(kernel, plan, sha256(source).hexdigest(),
                                                        check.plan_digest), 'VALID', plan)
