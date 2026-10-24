"""C11 loops for checked scale-v1 loop plans.

Emission happens only after scale_checker proves the plan against fresh
source. Arithmetic is plain int32_t: the checker's interval proof shows no +,
* or partial sum (in any order) leaves i32, so nothing overflows and the C
compiler may vectorize and reassociate accumulations. Index arithmetic is
int64_t. The branch-free input preflight runs before any output is written;
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

_POOL = r'''
/* Persistent worker pool. Workers start on the first parallel call, then wait
 * for work. A dispatch cuts its range into about four chunks per thread; every
 * thread, the caller included, claims chunks from one atomic counter until
 * none are left, and the dispatch returns once every chunk has finished. A
 * preempted worker therefore delays a dispatch only while holding a chunk.
 * Chunks are disjoint ranges of output cells (or inputs, for the preflight).
 * The claim counter holds (chunk count << 32 | next index), so a worker always
 * reads the count of the dispatch whose job it then runs. BERYL_THREADS=n caps
 * the pool; 1 disables it. */
#include <stdatomic.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <pthread.h>
#include <sched.h>
#include <unistd.h>
#endif
#define BERYL_MAX_THREADS 16
#define BERYL_MAX_CHUNKS 64
static const int32_t *beryl_job_input;
static int32_t *beryl_job_output;
static int beryl_job_phase;
static int beryl_job_chunks;
static int64_t beryl_job_begin[BERYL_MAX_CHUNKS + 1];
static uint32_t beryl_job_invalid[BERYL_MAX_CHUNKS];
static int32_t beryl_job_partial[BERYL_MAX_CHUNKS] __attribute__((unused));
static atomic_ullong beryl_claim;
static atomic_uint beryl_generation;
static atomic_uint beryl_done;
static int beryl_threads = 1;
static int beryl_pool_ready;

static void beryl_pause(void) {
#if defined(__x86_64__) || defined(__i386__)
    __builtin_ia32_pause();
#endif
}

static void beryl_yield(void) {
#ifdef _WIN32
    SwitchToThread();
#else
    sched_yield();
#endif
}

static void beryl_run_chunk(int c);

/* Claim and run chunks of the current dispatch until none are left. */
static void beryl_claim_chunks(void) {
    for (;;) {
        unsigned long long v = atomic_fetch_add_explicit(&beryl_claim, 1ull, memory_order_acq_rel);
        unsigned index = (unsigned)(v & 0xffffffffull), count = (unsigned)(v >> 32);
        if (index >= count) return;
        beryl_run_chunk((int)index);
        atomic_fetch_add_explicit(&beryl_done, 1u, memory_order_release);
    }
}

#ifdef _WIN32
static DWORD WINAPI beryl_worker(LPVOID arg)
#else
static void *beryl_worker(void *arg)
#endif
{
    unsigned seen = (unsigned)(uintptr_t)arg;
    for (;;) {
        unsigned spins = 0, now;
        while ((now = atomic_load_explicit(&beryl_generation, memory_order_acquire)) == seen) {
            if (++spins < (1u << 14)) beryl_pause(); else beryl_yield();
        }
        seen = now;
        beryl_claim_chunks();
    }
#ifndef _WIN32
    return NULL;
#endif
}

static int beryl_pool(void) {
    if (beryl_pool_ready) return beryl_threads;
    beryl_pool_ready = 1;
    long logical;
#ifdef _WIN32
    SYSTEM_INFO info;
    GetSystemInfo(&info);
    logical = (long)info.dwNumberOfProcessors;
#else
    logical = sysconf(_SC_NPROCESSORS_ONLN);
#endif
    /* Leave one logical processor for the rest of the system. */
    long want = logical > 2 ? logical - 1 : logical;
    const char *cap = getenv("BERYL_THREADS");
    if (cap && *cap) {
        long c = strtol(cap, NULL, 10);
        if (c >= 1 && c <= logical) want = c;
    }
    if (want < 1) want = 1;
    if (want > BERYL_MAX_THREADS) want = BERYL_MAX_THREADS;
    /* Workers start from the generation before any dispatch, so a worker that
     * starts late still runs the first dispatch. */
    unsigned start = atomic_load_explicit(&beryl_generation, memory_order_relaxed);
    for (long t = 1; t < want; ++t) {
#ifdef _WIN32
        HANDLE h = CreateThread(NULL, 0, beryl_worker, (LPVOID)(uintptr_t)start, 0, NULL);
        if (!h) break;
        CloseHandle(h);
#else
        pthread_t h;
        if (pthread_create(&h, NULL, beryl_worker, (void *)(uintptr_t)start) != 0) break;
        pthread_detach(h);
#endif
        beryl_threads = (int)t + 1;
    }
    return beryl_threads;
}

/* Cut [0, total) into 16-aligned chunks, run them on the pool, wait for all. */
static void beryl_dispatch(int phase, int64_t total, const int32_t *input, int32_t *output) {
    int chunks = beryl_threads * 4;
    if (chunks > BERYL_MAX_CHUNKS) chunks = BERYL_MAX_CHUNKS;
    int64_t step = (total + chunks - 1) / chunks;
    step = (step + 15) & ~(int64_t)15;
    if (step < 16) step = 16;
    chunks = (int)((total + step - 1) / step);
    if (chunks < 1) chunks = 1;
    for (int c = 0; c <= chunks; ++c) {
        int64_t at = (int64_t)c * step;
        beryl_job_begin[c] = at < total ? at : total;
    }
    beryl_job_input = input;
    beryl_job_output = output;
    beryl_job_phase = phase;
    beryl_job_chunks = chunks;
    atomic_store_explicit(&beryl_done, 0u, memory_order_relaxed);
    atomic_store_explicit(&beryl_claim, (unsigned long long)chunks << 32, memory_order_release);
    atomic_fetch_add_explicit(&beryl_generation, 1u, memory_order_release);
    beryl_claim_chunks();
    unsigned spins = 0;
    while (atomic_load_explicit(&beryl_done, memory_order_acquire) < (unsigned)chunks) {
        if (++spins < (1u << 14)) beryl_pause(); else beryl_yield();
    }
}
'''


def _affine(value):
    constant, terms = value
    parts = [f'(int64_t){constant}'] + [f'(int64_t){k} * {var}' for var, k in terms]
    return ' + '.join(parts)


def _literal(value):
    return '(-2147483647 - 1)' if value == -2147483648 else f'{value}'


def _lower(expr, statements, counter):
    kind = expr[0]
    if kind == 'const':
        return _literal(expr[1])
    if kind == 'load':
        return f'input[{_affine(expr[1])}]'
    if kind in ('add', 'mul'):
        operator = '+' if kind == 'add' else '*'
        left, right = _lower(expr[1], statements, counter), _lower(expr[2], statements, counter)
        return f'({left} {operator} {right})'
    _, var, lower, upper, body = expr
    name = f'ax_s{next(counter)}'
    inner = []
    value = _lower(body, inner, counter)
    statements.append(f'int32_t {name} = 0;')
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


def _row_accumulation(stage, v0, v1, w):
    """Cells loop for a value that is one sum with a sum-free body reading v1.

    Each row segment keeps one accumulator per cell; the sum variable runs in
    the outer loop and the columns in the inner one, so loads along v1 are
    contiguous and vectorize. Every cell still adds its terms in ascending
    sum-variable order, exactly as the direct loop does. Segments wider than
    the stack buffer use a heap buffer, or the direct loop if that fails.
    """
    _, var, lower, upper, body = stage.value
    term = _lower(body, [], iter(range(1 << 30)))
    direct = _lower(stage.value, statements := [], iter(range(1 << 30)))
    direct_body = '\n'.join('                ' + line for line in statements)
    index = _affine(stage.index)
    return ('\n/* Compute cells [from, to): one sum per cell, accumulated a row segment at a time. */\n'
            'static void beryl_cells(const int32_t *restrict input, int32_t *restrict output,\n'
            '                        int64_t from, int64_t to) {\n'
            '    int32_t stack[1024];\n'
            f'    int32_t *acc = {w} <= 1024 ? stack : malloc(sizeof(int32_t) * (size_t){w});\n'
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
    (stage,) = plan.stages
    (v0, h), (v1, w) = stage.loops
    statements = []
    counter = iter(range(1 << 30))
    value = _lower(stage.value, statements, counter)
    n_in, n_out = kernel.input_count, kernel.height * kernel.width
    lower, upper = kernel.input_interval
    body = '\n'.join('            ' + line for line in statements)
    # A single cell whose value is one large sum: split the sum range instead.
    # Any subset of its terms is bounded by the same proof as the whole sum.
    split = (n_out == 1 and stage.value[0] == 'sum' and not _has_sum(stage.value[4])
             and _work_estimate(stage.value) >= PARALLEL_MIN_WORK)
    parallel = split or (n_out >= 32 and n_out * _work_estimate(stage.value) >= PARALLEL_MIN_WORK)
    parallel_preflight = parallel and n_in >= PARALLEL_MIN_INPUT
    invalid = f'(uint32_t)(input[i] < {lower} || input[i] > {upper})'
    rows = (stage.value[0] == 'sum' and not _has_sum(stage.value[4])
            and _reads_var(stage.value[4], v1) and w >= 8)
    # Single-row outputs larger than the last-level cache: write through
    # non-temporal stores, which skip reading each output line before
    # overwriting it. Measured 1.5x on 4M-cell maps and 1-D stencils; 2-D
    # stencils read several input rows per output row and gained nothing
    # (sq2x2 lost), so they keep ordinary stores.
    stream = not rows and h == 1 and n_out * 4 >= STREAM_MIN_BYTES
    if stream:
        cells = _streaming_cells(stage, v0, v1, w, body, value)
    else:
        cells = _row_accumulation(stage, v0, v1, w) if rows else (
        '\n/* Compute cells [from, to) in row-major order. */\n'
        'static void beryl_cells(const int32_t *restrict input, int32_t *restrict output,\n'
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
        term = _lower(s_body, [], iter(range(1 << 30)))
        parts.append('\n/* Partial sum of the single cell over [from, to) of its sum range. */\n'
                     'static int32_t beryl_partial(const int32_t *restrict input, int64_t from, int64_t to) {\n'
                     f'    const int32_t {v0} = 0, {v1} = 0;\n'
                     f'    (void){v0}; (void){v1};\n'
                     '    int32_t acc = 0;\n'
                     f'    for (int32_t {var} = (int32_t)from; {var} < (int32_t)to; ++{var}) acc += {term};\n'
                     '    return acc;\n'
                     '}\n')
        split_chunk = ('    } else if (beryl_job_phase == 2) {\n'
                       f'        beryl_job_partial[c] = from < to ? beryl_partial(input, {s_lo} + from, {s_lo} + to) : 0;\n')
    if parallel:
        parts.append(_POOL)
        parts.append('\nstatic void beryl_run_chunk(int c) {\n'
                     '    int64_t from = beryl_job_begin[c], to = beryl_job_begin[c + 1];\n'
                     '    const int32_t *input = beryl_job_input;\n'
                     '    if (beryl_job_phase == 0) {\n'
                     '        uint32_t invalid = 0;\n'
                     f'        for (int64_t i = from; i < to; ++i) invalid |= {invalid};\n'
                     '        beryl_job_invalid[c] = invalid;\n'
                     + split_chunk +
                     '    } else if (from < to) {\n'
                     '        beryl_cells(input, beryl_job_output, from, to);\n'
                     '    }\n'
                     '}\n')
    parts.append('\n/* Caller owns disjoint initialized arrays of the exact compiled counts. */\n'
                 'int32_t beryl_kernel(const int32_t *restrict input, int32_t *restrict output) {\n')
    if parallel:
        parts.append('    int threads = beryl_pool();\n')
    parts.append('    uint32_t ax_invalid = 0;\n')
    if parallel_preflight:
        parts.append('    if (threads > 1) {\n'
                     f'        beryl_dispatch(0, {n_in}, input, output);\n'
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
                     f'        beryl_dispatch(2, {s_hi - s_lo}, input, output);\n'
                     '        int32_t total = 0;\n'
                     '        for (int c = 0; c < beryl_job_chunks; ++c) total += beryl_job_partial[c];\n'
                     f'        output[{stage.index[0]}] = total;\n'
                     f'    }} else beryl_cells(input, output, 0, {n_out});\n')
    elif parallel:
        parts.append(f'    if (threads > 1) beryl_dispatch(1, {n_out}, input, output);\n'
                     f'    else beryl_cells(input, output, 0, {n_out});\n')
    else:
        parts.append(f'    beryl_cells(input, output, 0, {n_out});\n')
    parts.append('    return 0;\n}\n')
    # Large buffers live in static storage, not on the driver's stack.
    assert '= {0};' in _FAST_DRIVER
    driver = (_FAST_DRIVER.replace('    int32_t input[BERYL_INPUT_COUNT] = {0};',
                                   '    static int32_t input[BERYL_INPUT_COUNT];')
              .replace('    int32_t output[BERYL_OUTPUT_COUNT] = {0};',
                       '    static int32_t output[BERYL_OUTPUT_COUNT];'))
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
    """Fresh admission, plan generation, template proof, then C emission."""
    kernel = admit_source(parse_source(source, limits))
    try:
        plan = make_scale_plan(kernel, max_nodes=limits.plan_operations)
    except Exception as error:  # an untrusted generator may fail in any way
        return ScaleCompilation(kernel, None, None, getattr(error, 'code', type(error).__name__))
    check = check_loop_plan(source, plan, limits)
    if not check.valid:
        return ScaleCompilation(kernel, check, None, check.reason, plan)
    return ScaleCompilation(kernel, check, emit_scale_c(kernel, plan, sha256(source).hexdigest(),
                                                        check.plan_digest), 'VALID', plan)
