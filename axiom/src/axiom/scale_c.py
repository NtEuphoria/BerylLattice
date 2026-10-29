"""C11 loops for checked scale-v1 loop plans.

Emission happens only after scale_checker proves the plan against fresh
source. Arithmetic is plain int32_t: the checker's interval proof shows no +,
* or partial sum (in any order) leaves i32, so nothing overflows and the C
compiler may vectorize and reassociate accumulations. A program with an i64
equation computes every value in int64_t instead (each node is proved to fit
its own equation's type, so i32 nodes keep their exact values), and an i64
output is an int64_t array. A u8, i8 or i16 input or output is an array of
that C type: loads promote to int, and a stored value is proved to fit.
Index arithmetic is int64_t. The branch-free input preflight runs before any output is written;
on rejection the first invalid index plus one is returned.

ABI 1 takes the inputs joined in declaration order through one pointer and
returns an int32_t status. ABI 2 takes one pointer per input, each of its own
storage type, and returns an int64_t status that means the same; it is
required for mixed storage types and for more than 2^31 - 1 input cells (see
emit_scale_c).

Large kernels split their cells across a persistent worker pool. The proved
store index v0*W + v1 writes every cell exactly once, the producer is inlined
and sum accumulators are locals, so disjoint cell ranges never share a written
location, inputs are only read, and the result does not depend on the thread
count. The parallel preflight completes before any cell is computed.
"""
from dataclasses import dataclass
from hashlib import sha256

from .model import C_TYPES, STORAGE_BOUNDS, TYPE_BOUNDS, Limits
from .native_codegen import _FAST_DRIVER, NativeArtifact
from .scale_carry import c_types, carry_eligible, carry_rows_c, plan_costs, rank_key
from .scale_plan import BINARY_KINDS, SCALE_PLAN_IDS
from .scale_pool import _POOL
from .scale_checker import check_loop_plan
from .scale_plan import make_scale_plan
from .frontend import admit_source, parse_source

# v2: the input check is one unsigned maximum per value (see _OUTSIDE).
SCALE_CODEGEN_VERSION = 'beryl-loop-c-v2'
SCALE_PARALLEL_CODEGEN_VERSION = 'beryl-loop-c-parallel-v2'
# ABI 2: one pointer per input and an int64_t status (see emit_scale_c).
SCALE_ABI2_CODEGEN_VERSION = 'beryl-loop-c-abi2-v1'
SCALE_ABI2_PARALLEL_CODEGEN_VERSION = 'beryl-loop-c-parallel-abi2-v1'
# Below this many estimated scalar operations a call stays single-threaded:
# a pool dispatch costs about a microsecond, so tiny kernels would lose.
PARALLEL_MIN_WORK = 1 << 16
PARALLEL_MIN_INPUT = 1 << 16
# Outputs at least this large bypass the cache with non-temporal stores.
STREAM_MIN_BYTES = 8 << 20
# Side of the square tiles for column-strided loads (see _tiled_rows).
TILE = 16
# The standalone driver allocates buffers larger than this on the heap.
HEAP_DRIVER_BYTES = 1 << 30
_C_BYTES = {'uint8_t': 1, 'int8_t': 1, 'int16_t': 2, 'int32_t': 4, 'int64_t': 8}

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

# Exact min and max; operands are already proved to fit the value type.
_MINMAX = '''
static inline int32_t __attribute__((unused)) beryl_min_i32(int32_t a, int32_t b) { return a < b ? a : b; }
static inline int32_t __attribute__((unused)) beryl_max_i32(int32_t a, int32_t b) { return a > b ? a : b; }
static inline int64_t __attribute__((unused)) beryl_min_i64(int64_t a, int64_t b) { return a < b ? a : b; }
static inline int64_t __attribute__((unused)) beryl_max_i64(int64_t a, int64_t b) { return a > b ? a : b; }
'''

# shr is floor(a / 2^k) and shr_round is floor(a / 2^k + 1/2), for every a and
# 0 <= k <= 63 (1 <= k for shr_round). Only nonnegative values are shifted, and
# never by the type's width or more, so no shift is undefined or
# implementation-defined. Neither result can overflow.
_SHIFTS = '''
static inline int32_t __attribute__((unused)) beryl_shr_i32(int32_t a, int k) {
    return k > 30 ? -(int32_t)(a < 0) : (a >= 0 ? a >> k : ~(~a >> k));
}
static inline int32_t __attribute__((unused)) beryl_shr_round_i32(int32_t a, int k) {
    return beryl_shr_i32(a, k) + (beryl_shr_i32(a, k - 1) & 1);
}
static inline int64_t __attribute__((unused)) beryl_shr_i64(int64_t a, int k) {
    return k > 62 ? -(int64_t)(a < 0) : (a >= 0 ? a >> k : ~(~a >> k));
}
static inline int64_t __attribute__((unused)) beryl_shr_round_i64(int64_t a, int k) {
    return beryl_shr_i64(a, k) + (beryl_shr_i64(a, k - 1) & 1);
}
'''


def _uses(expr, kinds):
    if expr[0] in kinds:
        return True
    if expr[0] in BINARY_KINDS:
        return _uses(expr[1], kinds) or _uses(expr[2], kinds)
    return expr[0] == 'sum' and _uses(expr[4], kinds)


def _affine(value):
    constant, terms = value
    parts = [f'(int64_t){constant}'] + [f'(int64_t){k} * {var}' for var, k in terms]
    return ' + '.join(parts)


def _literal(value):
    return '(-2147483647 - 1)' if value == -2147483648 else f'{value}'


_I32_MIN, _I32_MAX = -2 ** 31, 2 ** 31 - 1


def _counter(bound, step):
    """C type of a loop counter stepped by `step` while below `bound`: int32_t
    unless one step past its last value below `bound` could pass INT32_MAX."""
    return 'int64_t' if bound > _I32_MAX - step else 'int32_t'


def _segments(kernel):
    """(start, end, lower, upper) of each input's cells in the buffer, in declaration order."""
    out, start = [], 0
    for (rows, cols), (lower, upper) in zip(kernel.all_input_shapes, kernel.input_intervals):
        out.append((start, start + rows * cols, lower, upper))
        start += rows * cols
    return out


def _sum_lowers(plan):
    """Each sum variable's lower bound. A plan binds every sum variable once (scale_plan)."""
    lows, pending = {}, [stage.value for stage in plan.stages]
    while pending:
        e = pending.pop()
        if e[0] == 'sum':
            if lows.setdefault(e[1], e[2]) != e[2]:
                raise ValueError(f'the sum variable {e[1]!r} is bound twice')
            pending.append(e[4])
        elif e[0] in BINARY_KINDS:
            pending.extend((e[1], e[2]))
    return lows


def _first_cell(affine, lows):
    """The cell a load reads with every axis at 0 and every sum variable at its lower bound.

    Admitted reads stay inside their own input at every point of their
    domain, so this cell names the input a load reads. The constant term
    alone does not: in y[0, j + -1] with j from 1, it is the cell before y.
    """
    constant, terms = affine
    return constant + sum(k * lows.get(var, 0) for var, k in terms)


def _load_range(segments, lows=None):
    """Declared range of the input a load reads (see _first_cell)."""
    def lookup(affine):
        cell = _first_cell(affine, lows or {})
        return next((lo, hi) for start, end, lo, hi in segments if start <= cell < end)
    return lookup


def _outside(ref, lo, hi, storage='i32', literal=str):
    """C condition that `ref` is outside lo..hi.

    For a u8, i8 or i16 input a bound at the type's limit is left out: no
    stored value can fail it, and compilers warn about the always-false test.
    """
    if storage == 'i32':
        return f'{ref} < {literal(lo)} || {ref} > {literal(hi)}'
    low, high = STORAGE_BOUNDS[storage]
    return ' || '.join([f'{ref} < {lo}'] * (lo > low) + [f'{ref} > {hi}'] * (hi < high)) or '0'


# (uint32_t)(v - lo) exceeds hi - lo for exactly the v outside lo..hi (both in
# i32), so one unsigned maximum per value decides a whole range and vectorizes;
# measured 4.0 -> 2.9 us on a 65,536-value sum whose unchecked time is 2.8 us.
_OUTSIDE = '''
/* 1 if some input[from..to) lies outside lo..lo + width. */
static inline uint32_t __attribute__((unused)) beryl_outside(const int32_t *restrict input, int64_t from, int64_t to,
                                                             int32_t lo, uint32_t width) {
    uint32_t top = 0;
    for (int64_t i = from; i < to; ++i) {
        uint32_t v = (uint32_t)input[i] - (uint32_t)lo;
        top = v > top ? v : top;
    }
    return (uint32_t)(top > width);
}
'''


def _needs_check(lo, hi, storage):
    """No value of the storage type can lie outside a range that covers the type."""
    return (lo, hi) != TYPE_BOUNDS[storage]


def _range_check(start, end, lo, hi, storage):
    """C for 1 when some input[start..end) lies outside lo..hi, or '0'."""
    if not _needs_check(lo, hi, storage):
        return '0'
    return f'beryl_outside(input, {start}, {end}, {_literal(lo)}, {hi - lo}u)'


def _check_c(segments, storage='i32'):
    """C that checks cells [from, to) of the buffer, each against its own input's range."""
    loops = ''.join(f'    {{\n        int64_t a = from > {s} ? from : {s}, b = to < {e} ? to : {e};\n'
                    f'        if (a < b) invalid |= {_range_check("a", "b", lo, hi, storage)};\n    }}\n'
                    for s, e, lo, hi in segments if _needs_check(lo, hi, storage))
    return ('\n/* Each input checked against its own declared range. */\n'
            'static uint32_t beryl_check(const int32_t *restrict input, int64_t from, int64_t to) {\n'
            '    uint32_t invalid = 0;\n' + loops + '    return invalid;\n}\n')


def _narrow_block(expr, load_range, prod_interval=None):
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
            result = load_range(e[1])
        elif kind == 'prod':
            result = prod_interval
        elif kind in BINARY_KINDS:
            a, b = interval(e[1]), interval(e[2])
            if a is None or b is None:
                return None
            if kind in ('shr', 'shr_round'):
                half = 1 << (b[0] - 1) if kind == 'shr_round' else 0
                result = ((a[0] + half) >> b[0], (a[1] + half) >> b[0])
            else:
                ends = (a[0] * b[0], a[0] * b[1], a[1] * b[0], a[1] * b[1])
                result = {'add': (a[0] + b[0], a[1] + b[1]), 'mul': (min(ends), max(ends)),
                          'min': (min(a[0], b[0]), min(a[1], b[1])),
                          'max': (max(a[0], b[0]), max(a[1], b[1]))}[kind]
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


@dataclass(frozen=True, slots=True)
class _Buffers:
    """The pointers through which the kernel's functions read the inputs.

    ABI 1 passes one pointer, `input`, to every input joined in declaration
    order. ABI 2 passes one pointer per input, `in0` to `in3`, each of its own
    storage type. A load reads the input holding its first cell (see
    _first_cell), at its offset within that input.
    """
    names: tuple[str, ...]
    types: tuple[str, ...]  # C types
    starts: tuple[int, ...]  # each pointer's first cell in the joined order
    lows: tuple[tuple[str, int], ...] = ()  # sum variables' lower bounds

    @property
    def params(self) -> str:
        return ', '.join(f'const {t} *restrict {n}' for n, t in zip(self.names, self.types))

    @property
    def args(self) -> str:
        return ', '.join(self.names)

    def at(self, cell):
        """The pointer holding `cell` of the joined order."""
        return max(k for k, start in enumerate(self.starts) if start <= cell)

    def load(self, affine):
        constant, terms = affine
        k = self.at(_first_cell(affine, dict(self.lows)))
        return f'{self.names[k]}[{_affine((constant - self.starts[k], terms))}]'


_JOINED = _Buffers(('input',), ('int32_t',), (0,))


def _lower(expr, statements, counter, prod=None, wide=False, narrow=None, buffers=_JOINED):
    """C for a plan expression; `wide` computes in int64_t (loads and literals widened).

    `narrow(sum_expr)`, when given, returns the exact int32_t block length of a
    wide sum (see _narrow_block) or None. A narrow sum's body is lowered as
    plain int32_t, which _narrow_block showed exact for every node. Loads read
    through `buffers`.
    """
    kind = expr[0]
    if kind == 'prod':
        return prod(expr[1], expr[2])
    if kind == 'const':
        return f'((int64_t){_literal(expr[1])})' if wide else _literal(expr[1])
    if kind == 'load':
        return f'(int64_t){buffers.load(expr[1])}' if wide else buffers.load(expr[1])
    if kind in ('shr', 'shr_round'):
        if expr[2][0] != 'const':
            raise ValueError('a shift amount is a literal')
        left = _lower(expr[1], statements, counter, prod, wide, narrow, buffers)
        return f'beryl_{kind}_{"i64" if wide else "i32"}({left}, {expr[2][1]})'
    if kind in BINARY_KINDS:
        left = _lower(expr[1], statements, counter, prod, wide, narrow, buffers)
        right = _lower(expr[2], statements, counter, prod, wide, narrow, buffers)
        if kind in ('min', 'max'):
            return f'beryl_{kind}_{"i64" if wide else "i32"}({left}, {right})'
        return f'({left} {"+" if kind == "add" else "*"} {right})'
    _, var, lower, upper, body = expr
    name = f'ax_s{next(counter)}'
    block = narrow(expr) if wide and narrow else None
    inner = []
    if block is not None:
        # Exact int32_t blocks of `block` terms, each widened once (_narrow_block).
        value = _lower(body, inner, counter, prod, buffers=buffers)
        loop = [f'int32_t {name}_b = 0;',
                f'for (int32_t {var} = {name}_k; {var} < {name}_e; ++{var}) {{',
                *('    ' + line for line in inner), f'    {name}_b += {value};', '}']
        if upper - lower <= block:
            statements.extend(line.replace(f'{name}_k', str(lower)).replace(f'{name}_e', str(upper))
                              for line in loop)
            return f'((int64_t){name}_b)'
        statements.append(f'int64_t {name} = 0;')
        statements.append(f'for ({_counter(upper, block)} {name}_k = {lower}; {name}_k < {upper}; {name}_k += {block}) {{')
        statements.append(f'    int32_t {name}_e = {upper} - {name}_k < {block} ? {upper} : {name}_k + {block};')
        statements.extend('    ' + line for line in loop)
        statements.append(f'    {name} += {name}_b;')
        statements.append('}')
        return name
    value = _lower(body, inner, counter, prod, wide, narrow, buffers)
    statements.append(f'{"int64_t" if wide else "int32_t"} {name} = 0;')
    statements.append(f'for (int32_t {var} = {lower}; {var} < {upper}; ++{var}) {{')
    statements.extend('    ' + line for line in inner)
    statements.append(f'    {name} += {value};')
    statements.append('}')
    return name


def _whole_input_loads(body, var, lower, upper, n_in):
    """The load offsets of a sum body when its loads, over the whole sum range, read every input.

    Each load must be input[c + var]. Their ranges [c + lower, c + upper) must
    cover [0, n_in): checking exactly the values the sum reads then checks the
    whole input, so the separate preflight pass can be fused into the sum.
    """
    loads, pending = set(), [body]
    while pending:
        e = pending.pop()
        if e[0] == 'load':
            constant, terms = e[1]
            if terms != ((var, 1),):
                return None
            loads.add(constant)
        elif e[0] in BINARY_KINDS:
            pending.extend((e[1], e[2]))
        elif e[0] != 'const':
            return None
    reach = 0
    for c in sorted(loads):
        if c + lower > reach:
            return None
        reach = max(reach, c + upper)
    return sorted(loads) if loads and reach >= n_in and min(loads) + lower <= 0 else None


def _work_estimate(expr):
    """Scalar operations per output cell, with sum ranges multiplied out."""
    kind = expr[0]
    if kind in ('const', 'load'):
        return 1
    if kind in BINARY_KINDS:
        return 1 + _work_estimate(expr[1]) + _work_estimate(expr[2])
    return (expr[3] - expr[2]) * (1 + _work_estimate(expr[4]))


def _has_sum(expr):
    if expr[0] == 'sum':
        return True
    return expr[0] in BINARY_KINDS and (_has_sum(expr[1]) or _has_sum(expr[2]))


def _strided_in(expr, var):
    """Some load outside any sum moves more than one cell as `var` steps by one."""
    if expr[0] == 'load':
        return any(name == var and abs(k) > 1 for name, k in expr[1][1])
    return expr[0] in BINARY_KINDS and (_strided_in(expr[1], var) or _strided_in(expr[2], var))


def _tiled_rows(stage, v0, v1, w, statements, value, out, buffers=_JOINED):
    """Rows loop that computes output rows [r0, r1) in TILE x TILE tiles.

    For a load strided along the columns (a transpose), a tile reuses every
    cache line it brings in. Edge tiles are clamped, so each (v0, v1) with v0 in
    [r0, r1) and v1 in [0, W) is computed exactly once. Every cell is a pure
    function of its position, so this order stores exactly what row-major
    order does. Measured 34.4 -> 9.0 ms on a 2048 x 2048 transpose (gcc,
    AVX2, one thread); 16 beat 8, 32 and 64.
    """
    inner = ''.join(f'                {line}\n' for line in statements)
    return (f'\n/* Compute output rows [r0, r1) in {TILE} x {TILE} tiles. */\n'
            f'static void beryl_rows({buffers.params}, {out} *restrict output, int64_t r0, int64_t r1) {{\n'
            f'    for (int32_t ax_rb = (int32_t)r0; ax_rb < (int32_t)r1; ax_rb += {TILE}) {{\n'
            f'        int32_t ax_re = (int32_t)r1 - ax_rb < {TILE} ? (int32_t)r1 : ax_rb + {TILE};\n'
            f'        for (int32_t ax_cb = 0; ax_cb < {w}; ax_cb += {TILE}) {{\n'
            f'            int32_t ax_ce = {w} - ax_cb < {TILE} ? {w} : ax_cb + {TILE};\n'
            f'            for (int32_t {v0} = ax_rb; {v0} < ax_re; ++{v0})\n'
            f'            for (int32_t {v1} = ax_cb; {v1} < ax_ce; ++{v1}) {{\n'
            f'{inner}'
            f'                output[{_affine(stage.index)}] = {value};\n'
            '            }\n'
            '        }\n'
            '    }\n'
            '}\n')


def _reads_var(expr, var):
    if expr[0] == 'load':
        return any(name == var for name, _ in expr[1][1])
    if expr[0] in BINARY_KINDS:
        return _reads_var(expr[1], var) or _reads_var(expr[2], var)
    return expr[0] == 'sum' and _reads_var(expr[4], var)


def _row_accumulation(stage, v0, v1, w, wide=False, value='int32_t', out='int32_t', buffers=_JOINED):
    """Cells loop for a value that is one sum with a sum-free body reading v1.

    Each row segment keeps one accumulator per cell; the sum variable runs in
    the outer loop and the columns in the inner one, so loads along v1 are
    contiguous and vectorize. Every cell still adds its terms in ascending
    sum-variable order, exactly as the direct loop does. Segments wider than
    the stack buffer use a heap buffer, or the direct loop if that fails.
    """
    _, var, lower, upper, body = stage.value
    term = _lower(body, [], iter(range(1 << 30)), None, wide, buffers=buffers)
    direct = _lower(stage.value, statements := [], iter(range(1 << 30)), None, wide, buffers=buffers)
    direct_body = '\n'.join('                ' + line for line in statements)
    index = _affine(stage.index)
    return ('\n/* Compute cells [from, to): one sum per cell, accumulated a row segment at a time. */\n'
            f'static void beryl_cells({buffers.params}, {out} *restrict output,\n'
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


def _streaming_cells(stage, v0, v1, w, body, value, buffers=_JOINED):
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
            f'static void beryl_cells({buffers.params}, int32_t *restrict output,\n'
            '                        int64_t from, int64_t to) {\n'
            '    int32_t block[64] __attribute__((aligned(16)));\n'
            f'    int32_t {v0} = (int32_t)(from / {w}), first = (int32_t)(from % {w});\n'
            f'    for (int64_t at = from; at < to; ++{v0}, first = 0) {{\n'
            f'        int32_t last = (to - at < (int64_t)({w} - first)) ? first + (int32_t)(to - at) : {w};\n'
            f'        for ({_counter(w, 64)} start = first; start < last; start += 64) {{\n'
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


def _abi(kernel, abi):
    """The interface to emit: ABI 2 when the inputs cannot share one array and one int32_t status."""
    needs = len(set(kernel.input_types)) > 1 or kernel.input_count > _I32_MAX
    if abi is None:
        return 2 if needs else 1
    if abi not in (1, 2) or (abi == 1 and needs):
        raise ValueError(f'ABI {abi} cannot pass these inputs: ABI 1 needs one storage type '
                         f'and at most {_I32_MAX} input cells')
    return abi


def _v2_driver(kernel, buffers, segments, out):
    """Standalone driver for ABI 2 without a joined wrapper: each input is read as its own type."""
    lines = []
    for k, ((s, e, *_), storage, c_type) in enumerate(zip(segments, kernel.input_types, buffers.types)):
        lines.append(f'    {c_type} *in{k} = calloc(BERYL_INPUT{k}_COUNT, sizeof *in{k});')
    lines.append(f'    {out} *output = calloc(BERYL_OUTPUT_COUNT, sizeof *output);')
    lines.append('    if (' + ' || '.join(f'!{n}' for n in (*buffers.names, 'output')) + ') return 71;')
    for k, storage in enumerate(kernel.input_types):
        lines.append(f'    for (int64_t i = 0; i < BERYL_INPUT{k}_COUNT; ++i)\n'
                     f'        if (!beryl_read_{storage}(&in{k}[i])) return 65;')
    lines.append('    if (!beryl_end_of_input()) return 65;')
    lines.append(f'    if (beryl_kernel_v2({buffers.args}, output) != 0) return 66;')
    return '\n'.join(lines) + '\n'


def emit_scale_c(kernel, plan, source_digest, plan_digest, abi=None) -> NativeArtifact:
    """Emit C for a plan that check_loop_plan has just proved for `kernel`.

    ABI 1, the default where it fits, is `int32_t beryl_kernel(const T *input,
    OUT *output)` over the inputs joined in declaration order. ABI 2 is
    `int64_t beryl_kernel_v2(const T0 *in0, ..., OUT *output)`, one pointer
    per input. It is required for mixed storage types or more than 2^31 - 1
    input cells, and keeps an ABI 1 wrapper when the inputs share one type
    and fit. The status means the same either way: 0, or the first bad cell's
    index in the joined order plus one.
    """
    abi = _abi(kernel, abi)
    stage = plan.stages[-1]
    carry = len(plan.stages) == 2
    wide = kernel.wide
    val, out = c_types(kernel)
    (v0, h), (v1, w) = stage.loops
    statements = []
    counter = iter(range(1 << 30))
    segments = _segments(kernel)
    lows = _sum_lowers(plan)
    load_range = _load_range(segments, lows)
    buffers = _JOINED if abi == 1 else _Buffers(
        tuple(f'in{k}' for k in range(len(segments))), tuple(C_TYPES[t] for t in kernel.input_types),
        tuple(s for s, *_ in segments), tuple(sorted(lows.items())))
    # Each input that some value of its storage type can fail: (k, start, end, lo, hi, storage).
    checks = [(k, s, e, lo, hi, t) for k, ((s, e, lo, hi), t) in enumerate(zip(segments, kernel.input_types))
              if _needs_check(lo, hi, t)]
    # One shared range: a single check over the whole buffer.
    uniform =len({(lo, hi) for _, _, lo, hi in segments}) == 1
    lower, upper = segments[0][2], segments[0][3]
    prod_interval = _narrow_block(plan.stages[0].value, load_range) if carry else None
    narrow = (lambda e: _narrow_block(e, load_range, prod_interval)) if wide else None
    value = None if carry else _lower(stage.value, statements, counter, None, wide, narrow, buffers)
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
    storage = kernel.input_type
    checked = bool(checks)
    # Row accumulation makes the column loop innermost, so it suits bodies whose
    # loads are contiguous in v1 (matmul). A load strided in v1, such as weights
    # stored [out, in], is contiguous in the sum variable instead, so each cell
    # keeps its own inner sum: measured 12.6 -> 0.71 ms on a 1024 x 4096 int8
    # dense layer (gcc, AVX2, one thread).
    rows = (not carry and stage.value[0] == 'sum' and not _has_sum(stage.value[4])
            and _reads_var(stage.value[4], v1) and not _strided_in(stage.value[4], v1) and w >= 8)
    # Single-row outputs larger than the last-level cache: write through
    # non-temporal stores, which skip reading each output line before
    # overwriting it. Measured 1.5x on 4M-cell maps and 1-D stencils; 2-D
    # stencils read several input rows per output row and gained nothing
    # (sq2x2 lost), so they keep ordinary stores.
    # The streaming copy moves int32_t cells, so other outputs keep ordinary stores.
    stream = (not carry and not rows and not wide and out == 'int32_t' and h == 1
              and n_out * 4 >= STREAM_MIN_BYTES)
    tiled = (not carry and not split and not rows and not stream and h >= TILE and w >= TILE
             and _strided_in(stage.value, v1))
    params, args = buffers.params, buffers.args
    if carry:
        cells = carry_rows_c(plan, kernel, lambda e, s, c, p: _lower(e, s, c, p, wide, narrow, buffers),
                             params, args)
    elif tiled:
        cells = _tiled_rows(stage, v0, v1, w, statements, value, out, buffers)
    elif stream:
        cells = _streaming_cells(stage, v0, v1, w, body, value, buffers)
    else:
        cells = _row_accumulation(stage, v0, v1, w, wide, val, out, buffers) if rows else (
        '\n/* Compute cells [from, to) in row-major order. */\n'
        f'static void beryl_cells({params}, {out} *restrict output,\n'
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
    if abi == 1:
        counts = f'       BERYL_INPUT_COUNT = {n_in}, BERYL_OUTPUT_COUNT = {n_out} }};\n'
        outside = (_OUTSIDE,) if checked else ()
    else:
        # Enumeration constants are ints: the joined count only when it fits.
        counts = ''.join(f'       BERYL_INPUT{k}_COUNT = {e - s},\n' for k, (s, e, *_) in enumerate(segments)) + (
            f'       BERYL_INPUT_COUNT = {n_in}, ' if n_in <= _I32_MAX else '       ') + f'BERYL_OUTPUT_COUNT = {n_out} }};\n'
        # One unsigned-maximum check per storage type that needs one (see _OUTSIDE).
        outside = tuple(_OUTSIDE.replace('beryl_outside(const int32_t *restrict input',
                                         f'beryl_outside_{t}(const {C_TYPES[t]} *restrict input')
                        for t in dict.fromkeys(t for *_, t in checks))
    parts = [_HEADER.replace('PLAN_ID', plan.plan_id),
             f'enum {{ BERYL_HEIGHT = {kernel.height}, BERYL_WIDTH = {kernel.width},\n' + counts,
             *((_MINMAX,) if any(_uses(s.value, ('min', 'max')) for s in plan.stages) else ()),
             *((_SHIFTS,) if any(_uses(s.value, ('shr', 'shr_round')) for s in plan.stages) else ()),
             *outside,
             cells]
    split_chunk = ''
    fused = None
    if split:
        _, var, s_lo, s_hi, s_body = stage.value
        # Fused check: the sum reads every input, so checking the values it adds
        # checks the whole input in the same pass. Nothing is written until every
        # partial is in; on any bad value the first-bad-index scan runs as before.
        fused = _whole_input_loads(s_body, var, s_lo, s_hi, n_in)
        # One unsigned maximum per load that needs a check (see _OUTSIDE).
        tracked = [(j, c, *load_range((c + s_lo, ()))) for j, c in enumerate(fused or ())
                   if _needs_check(*load_range((c + s_lo, ())), kernel.input_types[buffers.at(c + s_lo)]
                                   if abi == 2 else storage)]
        check = ''.join(f' {{ uint32_t ax_v = (uint32_t){buffers.names[buffers.at(c + s_lo)]}'
                        f'[{c - buffers.starts[buffers.at(c + s_lo)]} + {var}] - (uint32_t){_literal(lo)};'
                        f' ax_u{j} = ax_v > ax_u{j} ? ax_v : ax_u{j}; }}' for j, c, lo, hi in tracked)
        block = narrow(stage.value) if narrow else None
        if block is None:
            term = _lower(s_body, [], iter(range(1 << 30)), None, wide, buffers=buffers)
            loop = f'    for (int32_t {var} = (int32_t)from; {var} < (int32_t)to; ++{var}) {{ acc += {term};{check} }}\n'
        else:
            # Exact int32_t blocks, each widened once (_narrow_block).
            term = _lower(s_body, [], iter(range(1 << 30)), buffers=buffers)
            loop = (f'    for (int64_t ax_k = from; ax_k < to; ax_k += {block}) {{\n'
                    f'        int64_t ax_e = to - ax_k < {block} ? to : ax_k + {block};\n'
                    '        int32_t ax_b = 0;\n'
                    f'        for (int32_t {var} = (int32_t)ax_k; {var} < (int32_t)ax_e; ++{var}) {{ ax_b += {term};{check} }}\n'
                    '        acc += ax_b;\n'
                    '    }\n')
        bad_param, bad_init, bad_out = (
            (', uint32_t *bad)', ''.join(f'    uint32_t ax_u{j} = 0;\n' for j, *_ in tracked),
             '    *bad = ' + (' | '.join(f'(uint32_t)(ax_u{j} > {hi - lo}u)' for j, _, lo, hi in tracked) or '0') + ';\n')
            if fused else (')', '', ''))
        parts.append('\n/* Partial sum of the single cell over [from, to) of its sum range'
                     + (', checking each value it adds' if fused else '') + '. */\n'
                     f'static {val} beryl_partial({params}, int64_t from, int64_t to{bad_param} {{\n'
                     f'    const int32_t {v0} = 0, {v1} = 0;\n'
                     f'    (void){v0}; (void){v1};\n'
                     f'    {val} acc = 0;\n'
                     + bad_init + loop + bad_out +
                     '    return acc;\n'
                     '}\n')
        split_chunk = ('    } else if (beryl_job_phase == 2) {\n'
                       + (f'        beryl_job_invalid[c] = 0;\n'
                          f'        beryl_job_partial[c] = from < to ? beryl_partial({args}, {s_lo} + from, {s_lo} + to,'
                          ' &beryl_job_invalid[c]) : 0;\n' if fused else
                          f'        beryl_job_partial[c] = from < to ? beryl_partial({args}, {s_lo} + from, {s_lo} + to) : 0;\n'))
    if abi == 2:
        # Cells [from, to) of the joined order, each input against its own range.
        parts.append('\n/* Each input checked against its own declared range. */\n'
                     f'static uint32_t __attribute__((unused)) beryl_check({params}, int64_t from, int64_t to) {{\n'
                     '    uint32_t invalid = 0;\n'
                     + ''.join(f'    {{\n        int64_t a = from > {s} ? from : {s}, b = to < {e} ? to : {e};\n'
                               f'        if (a < b) invalid |= beryl_outside_{t}(in{k}, a - {s}, b - {s}, '
                               f'{_literal(lo)}, {hi - lo}u);\n    }}\n' for k, s, e, lo, hi, t in checks)
                     + '    return invalid;\n}\n')
        serial_check = f'    ax_invalid = beryl_check({args}, 0, {n_in});\n'
        chunk_check = f'        beryl_job_invalid[c] = beryl_check({args}, from, to);\n'
    else:
        if not uniform:
            parts.append(_check_c(segments, storage).replace('static uint32_t beryl_check(',
                                                    'static uint32_t __attribute__((unused)) beryl_check('))
        serial_check = (f'    ax_invalid = {_range_check(0, n_in, lower, upper, storage)};\n' if uniform else
                        f'    ax_invalid = beryl_check(input, 0, {n_in});\n')
        chunk_check = (f'        beryl_job_invalid[c] = {_range_check("from", "to", lower, upper, storage)};\n'
                       if uniform else '        beryl_job_invalid[c] = beryl_check(input, from, to);\n')
    # The pool takes the inputs as one pointer (ABI 1) or as an array of them (ABI 2).
    pooled = 'input' if abi == 1 else 'ax_in'
    if parallel:
        pool = (_POOL.replace('static int32_t *beryl_job_output;', f'static {out} *beryl_job_output;')
                .replace('static int32_t beryl_job_partial', f'static {val} beryl_job_partial'))
        if abi == 1:
            pool = pool.replace('const int32_t *input, int32_t *output)', f'const int32_t *input, {out} *output)')
            unpack = '    const int32_t *input = beryl_job_input;\n'
        else:
            n = len(segments)
            pool = (pool.replace('static const int32_t *beryl_job_input;', f'static const void *beryl_job_input[{n}];')
                    .replace('const int32_t *input, int32_t *output)', f'const void *const *input, {out} *output)')
                    .replace('    beryl_job_input = input;\n',
                             f'    for (int k = 0; k < {n}; ++k) beryl_job_input[k] = input[k];\n'))
            unpack = ''.join(f'    const {t} *{name} = beryl_job_input[{k}];\n'
                             for k, (name, t) in enumerate(zip(buffers.names, buffers.types)))
        parts.append(pool)
        parts.append('\nstatic void beryl_run_chunk(int c) {\n'
                     '    int64_t from = beryl_job_begin[c], to = beryl_job_begin[c + 1];\n'
                     + unpack +
                     '    if (beryl_job_phase == 0) {\n'
                     + chunk_check + split_chunk +
                     '    } else if (from < to) {\n'
                     + (f'        beryl_rows({args}, beryl_job_output, from, to);\n' if carry or tiled else
                        f'        beryl_cells({args}, beryl_job_output, from, to);\n') +
                     '    }\n'
                     '}\n')
    if abi == 1:
        parts.append('\n/* Caller owns disjoint initialized arrays of the exact compiled counts. */\n'
                     f'int32_t beryl_kernel(const int32_t *restrict input, {out} *restrict output) {{\n')
    else:
        parts.append('\n/* ABI 2: one array per input. The caller owns initialized arrays of the\n'
                     ' * exact compiled counts, the output disjoint from every input. */\n'
                     f'int64_t beryl_kernel_v2({params}, {out} *restrict output) {{\n')
    if parallel:
        parts.append('    int threads = beryl_pool();\n')
        if abi == 2:
            parts.append(f'    const void *ax_in[{len(segments)}] = {{{args}}};\n')
    parts.append('    uint32_t ax_invalid = 0;\n')
    if abi == 1:
        scan = ('    if (ax_invalid) {\n'
                + (f'        for (int64_t i = 0; i < {n_in}; ++i)\n'
                   f'            if ({_outside("input[i]", lower, upper, storage)}) return (int32_t)(i + 1);\n' if uniform else
                   ''.join(f'        for (int64_t i = {s}; i < {e}; ++i)\n'
                           f'            if ({_outside("input[i]", lo, hi, storage, _literal)}) return (int32_t)(i + 1);\n'
                           for s, e, lo, hi in segments))
                + '    }\n')
    else:
        scan = ('    if (ax_invalid) {\n'
                + ''.join(f'        for (int64_t i = 0; i < {e - s}; ++i)\n'
                          f'            if ({_outside(f"in{k}[i]", lo, hi, t, _literal)}) return (int64_t)i + {s + 1};\n'
                          for k, s, e, lo, hi, t in checks)
                + '    }\n')
    if fused:
        parts.append(f'    {val} total = 0;\n'
                     '    if (threads > 1) {\n'
                     f'        beryl_dispatch(2, {s_hi - s_lo}, 16, 4, {pooled}, output);\n'
                     '        for (int c = 0; c < beryl_job_chunks; ++c) {\n'
                     '            ax_invalid |= beryl_job_invalid[c];\n'
                     '            total += beryl_job_partial[c];\n'
                     '        }\n'
                     f'    }} else total = beryl_partial({args}, {s_lo}, {s_hi}, &ax_invalid);\n'
                     + scan +
                     f'    output[{stage.index[0]}] = total;\n')
    elif parallel_preflight:
        parts.append('    if (threads > 1) {\n'
                     f'        beryl_dispatch(0, {n_in}, 16, 4, {pooled}, output);\n'
                     '        for (int c = 0; c < beryl_job_chunks; ++c) ax_invalid |= beryl_job_invalid[c];\n'
                     '    } else {\n'
                     '    ' + serial_check +
                     '    }\n')
    else:
        parts.append(serial_check)
    if not fused:
        parts.append(scan)
    if fused:
        pass  # checked, summed and written above
    elif split:
        parts.append('    if (threads > 1) {\n'
                     f'        beryl_dispatch(2, {s_hi - s_lo}, 16, 4, {pooled}, output);\n'
                     f'        {val} total = 0;\n'
                     '        for (int c = 0; c < beryl_job_chunks; ++c) total += beryl_job_partial[c];\n'
                     f'        output[{stage.index[0]}] = total;\n'
                     f'    }} else beryl_cells({args}, output, 0, {n_out});\n')
    elif parallel and carry:
        parts.append(f'    if (threads > 1) beryl_dispatch(1, {h}, 1, 1, {pooled}, output);\n'
                     f'    else beryl_rows({args}, output, 0, {h});\n')
    elif parallel and tiled:
        # Chunks of whole tile rows, about four per thread.
        parts.append(f'    if (threads > 1) beryl_dispatch(1, {h}, {TILE}, 4, {pooled}, output);\n'
                     f'    else beryl_rows({args}, output, 0, {h});\n')
    elif parallel:
        parts.append(f'    if (threads > 1) beryl_dispatch(1, {n_out}, 16, 4, {pooled}, output);\n'
                     f'    else beryl_cells({args}, output, 0, {n_out});\n')
    elif carry or tiled:
        parts.append(f'    beryl_rows({args}, output, 0, {h});\n')
    else:
        parts.append(f'    beryl_cells({args}, output, 0, {n_out});\n')
    parts.append('    return 0;\n}\n')
    in_t = C_TYPES[kernel.input_type]
    # ABI 2 keeps the joined ABI 1 entry point when the inputs share one type
    # and the status fits int32_t: each input is an offset into the buffer.
    wrapper = abi == 2 and len(set(kernel.input_types)) == 1 and n_in <= _I32_MAX
    if wrapper:
        parts.append('\n/* ABI 1: the inputs joined in declaration order. */\n'
                     f'int32_t beryl_kernel(const {in_t} *restrict input, {out} *restrict output) {{\n'
                     '    return (int32_t)beryl_kernel_v2('
                     + ', '.join('input' if s == 0 else f'input + {s}' for s, *_ in segments) + ', output);\n}\n')
    # Large buffers live in static storage, not on the driver's stack. Past
    # HEAP_DRIVER_BYTES they go on the heap: static arrays that large do not
    # link on Windows, nor on Linux without -mcmodel=medium.
    if n_in * _C_BYTES[in_t] + n_out * _C_BYTES[out] > HEAP_DRIVER_BYTES:
        buffers_c = (f'    {in_t} *input = calloc(BERYL_INPUT_COUNT, sizeof *input);',
                     f'    {out} *output = calloc(BERYL_OUTPUT_COUNT, sizeof *output);\n'
                     '    if (!input || !output) return 71;')
    else:
        buffers_c = (f'    static {in_t} input[BERYL_INPUT_COUNT];', f'    static {out} output[BERYL_OUTPUT_COUNT];')
    assert '= {0};' in _FAST_DRIVER
    driver = (_FAST_DRIVER.replace('    int32_t input[BERYL_INPUT_COUNT] = {0};', buffers_c[0])
              .replace('    int32_t output[BERYL_OUTPUT_COUNT] = {0};', buffers_c[1]))
    if abi == 2 and not wrapper:
        # From the buffers to the kernel call: one array per input, each read as its own type.
        start = driver.index(buffers_c[0])
        end = driver.index('    if (beryl_kernel(input, output) != 0) return 66;\n')
        end += len('    if (beryl_kernel(input, output) != 0) return 66;\n')
        driver = driver[:start] + _v2_driver(kernel, buffers, segments, out) + driver[end:]
    if out == 'int64_t':
        # i64 outputs print through a 64-bit formatter in place of the i32 one.
        start = driver.index('static int beryl_put_i32(int32_t value) {')
        end = driver.index('\n}\n', start) + 3
        driver = (driver[:start] + _PUT_I64 + driver[end:]).replace(
            'beryl_put_i32(output[i])', 'beryl_put_i64(output[i])')
    code = ''.join(parts)
    if abi == 1 and in_t != 'int32_t':
        # A u8, i8 or i16 input buffer: every pointer to it takes the narrow
        # type. Loads promote to int, so the arithmetic above is unchanged.
        code = (code.replace('const int32_t *restrict input', f'const {in_t} *restrict input')
                .replace('const int32_t *input', f'const {in_t} *input')
                .replace('static const int32_t *beryl_job_input;', f'static const {in_t} *beryl_job_input;'))
        assert 'int32_t *restrict input' not in code
    # A token must also fit its input's storage type; it is refused, never wrapped.
    for storage_type in dict.fromkeys(t for t in (kernel.input_types if abi == 2 and not wrapper else (kernel.input_type,))
                                      if t != 'i32'):
        c_type = C_TYPES[storage_type]
        low, high = STORAGE_BOUNDS[storage_type]
        reader = (f'/* A token must also fit {storage_type}; it is refused, never wrapped. */\n'
                  f'static int beryl_read_{storage_type}({c_type} *value) {{\n'
                  '    int32_t parsed;\n'
                  f'    if (!beryl_read_i32(&parsed) || parsed < {low} || parsed > {high}) return 0;\n'
                  f'    *value = ({c_type})parsed;\n'
                  '    return 1;\n'
                  '}\n\n')
        anchor = 'static int beryl_end_of_input(void) {'
        assert driver.count(anchor) == 1
        driver = (driver.replace(anchor, reader + anchor)
                  .replace('if (!beryl_read_i32(&input[i])) return 65;',
                           f'if (!beryl_read_{storage_type}(&input[i])) return 65;'))
        assert f'beryl_read_{storage_type}(&' in driver
    generated = (code + driver).encode('ascii')
    version = ((SCALE_PARALLEL_CODEGEN_VERSION if parallel else SCALE_CODEGEN_VERSION) if abi == 1 else
               (SCALE_ABI2_PARALLEL_CODEGEN_VERSION if parallel else SCALE_ABI2_CODEGEN_VERSION))
    return NativeArtifact(generated, kernel.height, kernel.width, n_in, n_out, source_digest,
                          plan_digest, sha256(generated).hexdigest(), version, None, plan.format)


@dataclass(frozen=True, slots=True)
class ScaleCompilation:
    kernel: object
    check: object
    artifact: NativeArtifact | None
    reason: str
    plan: object = None


def compile_scale_native(source: bytes, limits: Limits = Limits(), abi: int | None = None) -> ScaleCompilation:
    """Fresh admission; every portfolio plan generated and template-checked; the
    best proved plan by the program's objective emitted (see scale_carry.rank_key)
    with the interface `abi` (see emit_scale_c; None picks ABI 1 where it fits)."""
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
                                                        check.plan_digest, abi), 'VALID', plan)
