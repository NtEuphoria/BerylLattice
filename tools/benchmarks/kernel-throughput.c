/* Standalone callable-kernel driver. Compile separately, without LTO.
 * Timed: one input mutation, external call, status and one output capture.
 * Untimed: initialization, checksums, direct-formula reference, full replay.
 * The first call is measured separately and is the single warmup call.
 */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#ifdef _WIN32
#include <windows.h>
#endif

extern int32_t beryl_kernel(const int32_t *, int32_t *);

static void fail(const char *message) {
    fprintf(stderr, "kernel audit/driver failure: %s\n", message);
    exit(1);
}

static uint64_t number(const char *text) {
    char *end;
    errno = 0;
    if (!*text || *text == '-') fail("invalid argument");
    unsigned long long value = strtoull(text, &end, 10);
    if (errno || *end) fail("invalid argument");
    return (uint64_t)value;
}

static uint64_t now_ns(void) {
#ifdef _WIN32
    /* MinGW links no clock_gettime; QueryPerformanceCounter is monotonic. */
    LARGE_INTEGER count, frequency;
    if (!QueryPerformanceCounter(&count) || !QueryPerformanceFrequency(&frequency))
        fail("monotonic clock");
    uint64_t ticks = (uint64_t)count.QuadPart, hz = (uint64_t)frequency.QuadPart;
    return ticks / hz * UINT64_C(1000000000) + ticks % hz * UINT64_C(1000000000) / hz;
#else
    struct timespec time;
    if (clock_gettime(CLOCK_MONOTONIC, &time)) fail("monotonic clock");
    return (uint64_t)time.tv_sec * UINT64_C(1000000000) + (uint64_t)time.tv_nsec;
#endif
}

static void initialize(int32_t *input, int32_t *output, size_t n, size_t m,
                       uint64_t seed) {
    for (size_t i = 0; i < n; ++i)
        input[i] = (int32_t)((seed * UINT64_C(2654435761) + i * 73 + i * i * 19) & 1023);
    for (size_t i = 0; i < m; ++i) output[i] = -12345;
}

/* Each mutation changes exactly one cell, remains bounded, and is O(1). */
static void mutate(int32_t *input, size_t index, uint64_t iteration) {
    input[index] = (input[index] + 1 + (int32_t)(iteration & 31)) & 1023;
}

/* Independent original direct stencil formula; never calls compiler code. */
static void reference(const int32_t *input, int32_t *output, size_t h, size_t w) {
    for (size_t r = 0; r < h; ++r) for (size_t c = 0; c < w; ++c) {
        size_t i = r * (w + 1) + c;
        int32_t x = input[i] + 1, y = input[i + 1] + 1;
        int32_t z = input[i + w + 1] + 1, t = input[i + w + 2] + 1;
        output[r * w + c] = ((x * x + y * y) + z * z) + t * t;
    }
}

static uint64_t consume(uint64_t checksum, int32_t value) {
    return (checksum ^ (uint32_t)value) * UINT64_C(1099511628211);
}

int main(int argc, char **argv) {
    if (argc != 5) fail("expected height width iterations seed");
    uint64_t h64 = number(argv[1]), w64 = number(argv[2]);
    uint64_t iterations = number(argv[3]), seed = number(argv[4]);
    if (!h64 || !w64 || h64 > 255 || w64 > 255 ||
        (h64 + 1) * (w64 + 1) > 256 || !iterations ||
        iterations > SIZE_MAX / sizeof(int32_t)) fail("argument outside bounds");
    size_t h = (size_t)h64, w = (size_t)w64;
    size_t n = (h + 1) * (w + 1), m = h * w;
    /* Separate initialized buffers; input/output never alias. */
    int32_t input[256], output[256], expected_input[256], expected[256];
    int32_t replay_input[256], replay_output[256];
    int32_t *statuses = malloc((size_t)iterations * sizeof(*statuses));
    int32_t *observed = malloc((size_t)iterations * sizeof(*observed));
    if (!statuses || !observed) fail("capture allocation");
    /* Pre-touch capture storage so first-touch allocation is not timed. */
    /* Volatile stores prevent dead-store elimination of this pre-touch. */
    for (uint64_t i = 0; i < iterations; ++i) {
        ((volatile int32_t *)statuses)[i] = 0;
        ((volatile int32_t *)observed)[i] = 0;
    }
    initialize(input, output, n, m, seed);
    initialize(expected_input, expected, n, m, seed);
    uint64_t first_start = now_ns();
    int32_t first_status = beryl_kernel(input, output);
    uint64_t first_ns = now_ns() - first_start;
    reference(expected_input, expected, h, w);
    if (first_status || memcmp(input, expected_input, n * sizeof(*input)) ||
        memcmp(output, expected, m * sizeof(*output))) fail("first call");

    initialize(input, output, n, m, seed);
    size_t in_index = 0, out_index = 0;
    uint64_t start = now_ns();
    for (uint64_t i = 0; i < iterations; ++i) {
        mutate(input, in_index, i);
        statuses[i] = beryl_kernel(input, output);
        observed[i] = output[out_index];
        if (++in_index == n) in_index = 0;
        if (++out_index == m) out_index = 0;
    }
    uint64_t elapsed_ns = now_ns() - start;

    /* Audit the identical sequence, including every replay output cell. The
     * sampled timed observations bind the measured execution to this audit. */
    initialize(expected_input, expected, n, m, seed);
    initialize(replay_input, replay_output, n, m, seed);
    uint64_t checksum = UINT64_C(14695981039346656037);
    uint64_t reference_checksum = checksum;
    in_index = out_index = 0;
    for (uint64_t i = 0; i < iterations; ++i) {
        mutate(expected_input, in_index, i);
        mutate(replay_input, in_index, i);
        reference(expected_input, expected, h, w);
        int32_t replay_status = beryl_kernel(replay_input, replay_output);
        if (statuses[i] || replay_status || observed[i] != expected[out_index] ||
            memcmp(replay_input, expected_input, n * sizeof(*input)) ||
            memcmp(replay_output, expected, m * sizeof(*output)))
            fail("changing-input status/output/input replay");
        checksum = consume(consume(checksum, statuses[i]), observed[i]);
        reference_checksum = consume(consume(reference_checksum, 0), expected[out_index]);
        if (++in_index == n) in_index = 0;
        if (++out_index == m) out_index = 0;
    }
    if (checksum != reference_checksum ||
        memcmp(input, expected_input, n * sizeof(*input)) ||
        memcmp(output, expected, m * sizeof(*output))) fail("final complete state/checksum");
    for (size_t i = 0; i < m; ++i) checksum = consume(checksum, output[i]);
    printf("{\"audit_ok\":true,\"warmup_calls\":1,\"first_call_ns\":%" PRIu64
           ",\"elapsed_ns\":%" PRIu64 ",\"ns_per_run\":%.9f,\"seed\":%" PRIu64
           ",\"checksum\":\"%016" PRIx64 "\",\"final_output\":[",
           first_ns, elapsed_ns, (double)elapsed_ns / (double)iterations, seed, checksum);
    for (size_t i = 0; i < m; ++i) printf("%s%" PRId32, i ? "," : "", output[i]);
    puts("]}");
    free(statuses);
    free(observed);
    return 0;
}
