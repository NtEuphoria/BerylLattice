/* Timing harness for Axiom-generated native kernels (bench protocol).
   Link with the generated C compiled separately as its own translation unit,
   with its driver renamed (-Dmain=beryl_generated_main) and without LTO, so
   beryl_kernel stays an opaque external call that cannot be folded away.
   argv: pattern a b min_ms max_reps input_count output_count
   -> one JSON line on stdout, same fields as impl/kernels.c.
   Compiled with -DBERYL_OUT=int64_t for programs with an i64 output. */
#if !defined(_WIN32) && !defined(_POSIX_C_SOURCE)
#define _POSIX_C_SOURCE 199309L  /* clock_gettime under strict -std=c11 */
#endif
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
static int64_t now_ns(void) {
    static LARGE_INTEGER f; LARGE_INTEGER t;
    if (!f.QuadPart) QueryPerformanceFrequency(&f);
    QueryPerformanceCounter(&t);
    return (int64_t)((double)t.QuadPart * 1e9 / (double)f.QuadPart);
}
#else
#include <time.h>
static int64_t now_ns(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return (int64_t)t.tv_sec * 1000000000 + t.tv_nsec;
}
#endif

#ifndef BERYL_OUT
#define BERYL_OUT int32_t
#endif

extern int32_t beryl_kernel(const int32_t *input, BERYL_OUT *output);

static int32_t value(const char *p, int64_t i) {
    if (!strcmp(p, "hash")) return (int32_t)(((uint32_t)i * 2654435761u) >> 22);
    if (!strcmp(p, "ramp")) return (int32_t)(i % 1024);
    if (!strcmp(p, "alt")) return 1023 * (int32_t)(i & 1);
    if (!strcmp(p, "zeros")) return 0;
    if (!strcmp(p, "max")) return 1023;
    fprintf(stderr, "unknown pattern\n"); exit(2);
}

static int cmp(const void *p, const void *q) {
    int64_t a = *(const int64_t *)p, b = *(const int64_t *)q; return (a > b) - (a < b);
}

int main(int argc, char **argv) {
    if (argc != 8) { fprintf(stderr, "usage: pattern a b min_ms max_reps n_in n_out\n"); return 2; }
    const char *pat = argv[1];
    int64_t min_ns = atoll(argv[4]) * 1000000, max_reps = atoll(argv[5]);
    int64_t n_in = atoll(argv[6]), n_out = atoll(argv[7]);
    int32_t *x = malloc((size_t)n_in * sizeof *x);
    BERYL_OUT *o = malloc((size_t)n_out * sizeof *o);
    if (!x || !o) return 3;
    for (int64_t i = 0; i < n_in; i++) x[i] = value(pat, i);
    for (int64_t i = 0; i < n_out; i++) o[i] = -12345;
    volatile int64_t sink = 0;
    int32_t status = beryl_kernel(x, o);  /* untimed warm-up */
    if (status != 0) { printf("{\"impl\":\"axiom-native\",\"status\":\"error\",\"kernel_status\":%d}\n", (int)status); return 1; }
    int64_t inner = 1;  /* calibrate calls per sample so one sample spans >= 1 ms */
    for (;;) {
        int64_t start = now_ns();
        for (int64_t i = 0; i < inner; i++) { sink += beryl_kernel(x, o); sink += o[n_out - 1]; }
        if (now_ns() - start >= 1000000 || inner >= (1 << 22)) break;
        inner *= 2;
    }
    int64_t cap = max_reps < 3 ? 3 : max_reps, reps = 0, total = 0;
    int64_t *s = malloc((size_t)cap * sizeof *s);
    while (reps < 3 || (total < min_ns && reps < cap)) {
        int64_t start = now_ns();
        for (int64_t i = 0; i < inner; i++) { sink += beryl_kernel(x, o); sink += o[n_out - 1]; }
        int64_t batch = now_ns() - start;
        s[reps++] = batch / inner; total += batch;
    }
    const int64_t M = 1000000007; int64_t acc = 0;
    for (int64_t i = 0; i < n_out; i++) acc = (acc + ((((int64_t)o[i] % M) + M) % M) * (i % 65521 + 1)) % M;
    qsort(s, (size_t)reps, sizeof *s, cmp);
    int64_t med = reps % 2 ? s[reps / 2] : (s[reps / 2 - 1] + s[reps / 2]) / 2;
    printf("{\"impl\":\"axiom-native\",\"status\":\"ok\",\"n_out\":%lld,\"checksum\":%lld,"
           "\"reps\":%lld,\"inner\":%lld,\"ns_min\":%lld,\"ns_median\":%lld,\"ns_total\":%lld}\n",
           (long long)n_out, (long long)acc, (long long)reps, (long long)inner,
           (long long)s[0], (long long)med, (long long)total);
    return 0;
}
