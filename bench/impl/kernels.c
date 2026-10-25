/* C11 baseline. Build: clang -O3 -std=c11 kernels.c -o kernels
   argv: kernel pattern a b min_ms max_reps -> one JSON line on stdout. */
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

typedef int32_t i32; typedef int64_t i64;
static i64 A, B;

static i32 value(const char *p, i64 i) {
    if (!strcmp(p, "hash")) return (i32)(((uint32_t)i * 2654435761u) >> 22);
    if (!strcmp(p, "ramp")) return (i32)(i % 1024);
    if (!strcmp(p, "alt")) return 1023 * (i32)(i & 1);
    if (!strcmp(p, "zeros")) return 0;
    if (!strcmp(p, "max")) return 1023;
    fprintf(stderr, "unknown pattern\n"); exit(2);
}

static void sq2x2(const i32 *x, i64 *o) {
    i64 h = A, w = B, cols = w + 1;
    for (i64 r = 0; r < h; r++) for (i64 c = 0; c < w; c++) {
        i64 i = r * cols + c;
        i64 p0 = (i64)(x[i] + 1) * (x[i] + 1), p1 = (i64)(x[i+1] + 1) * (x[i+1] + 1);
        i64 p2 = (i64)(x[i+cols] + 1) * (x[i+cols] + 1), p3 = (i64)(x[i+cols+1] + 1) * (x[i+cols+1] + 1);
        o[r * w + c] = p0 + p1 + p2 + p3;
    }
}
static void stencil1d3(const i32 *x, i64 *o) {
    for (i64 i = 0; i < A; i++) o[i] = (i64)x[i] + 2 * (i64)x[i+1] + x[i+2];
}
#define WINDOW(BODY) \
    i64 h = A, w = B, cols = w + 2; \
    for (i64 r = 0; r < h; r++) { \
        const i32 *a = x + r * cols, *b = a + cols, *c = b + cols; \
        for (i64 j = 0; j < w; j++) o[r * w + j] = (BODY); }
static void box3x3(const i32 *x, i64 *o) {
    WINDOW((i64)a[j] + a[j+1] + a[j+2] + b[j] + b[j+1] + b[j+2] + c[j] + c[j+1] + c[j+2])
}
static void laplace5(const i32 *x, i64 *o) {
    WINDOW(4 * (i64)b[j+1] - a[j+1] - c[j+1] - b[j] - b[j+2])
}
static void conv3x3(const i32 *x, i64 *o) {
    WINDOW((i64)a[j] + 2*a[j+1] + a[j+2] + 2*b[j] + 4*b[j+1] + 2*b[j+2] + c[j] + 2*c[j+1] + c[j+2])
}
static void life(const i32 *x, i64 *o) {
    i64 h = A, w = B, cols = w + 2;
    for (i64 r = 0; r < h; r++) {
        const i32 *a = x + r * cols, *b = a + cols, *c = b + cols;
        for (i64 j = 0; j < w; j++) {
            int n = (a[j]&1) + (a[j+1]&1) + (a[j+2]&1) + (b[j]&1) + (b[j+2]&1)
                  + (c[j]&1) + (c[j+1]&1) + (c[j+2]&1);
            o[r * w + j] = (n == 3) || (n == 2 && (b[j+1] & 1));
        }
    }
}
static void polymap(const i32 *x, i64 *o) {
    for (i64 i = 0; i < A; i++) { i64 v = x[i]; o[i] = v * v * v + 3 * v + 7; }
}
static void transpose(const i32 *x, i64 *o) {
    for (i64 r = 0; r < A; r++) for (i64 c = 0; c < B; c++) o[c * A + r] = x[r * B + c];
}
static void maxpool2(const i32 *x, i64 *o) {
    i64 cols = 2 * B;
    for (i64 r = 0; r < A; r++) for (i64 c = 0; c < B; c++) {
        const i32 *t = x + 2 * r * cols + 2 * c, *u = t + cols;
        i32 m = t[0]; if (t[1] > m) m = t[1]; if (u[0] > m) m = u[0]; if (u[1] > m) m = u[1];
        o[r * B + c] = m;
    }
}
static void sum(const i32 *x, i64 *o) { i64 s = 0; for (i64 i = 0; i < A; i++) s += x[i]; o[0] = s; }
static void dot(const i32 *x, i64 *o) {
    i64 s = 0; for (i64 i = 0; i < A; i++) s += (i64)x[i] * x[A + i]; o[0] = s;
}
static void scan(const i32 *x, i64 *o) { i64 s = 0; for (i64 i = 0; i < A; i++) { s += x[i]; o[i] = s; } }
static void hist(const i32 *x, i64 *o) {
    memset(o, 0, 64 * sizeof *o); for (i64 i = 0; i < A; i++) o[x[i] >> 4]++;
}
static void matmul(const i32 *x, i64 *o) {
    i64 n = A; const i32 *P = x, *Q = x + n * n;
    memset(o, 0, (size_t)(n * n) * sizeof *o);
    for (i64 i = 0; i < n; i++) for (i64 k = 0; k < n; k++) {
        i64 p = P[i * n + k]; const i32 *q = Q + k * n; i64 *row = o + i * n;
        for (i64 j = 0; j < n; j++) row[j] += p * q[j];
    }
}

static int cmp(const void *p, const void *q) {
    i64 a = *(const i64 *)p, b = *(const i64 *)q; return (a > b) - (a < b);
}

int main(int argc, char **argv) {
    if (argc != 7) { fprintf(stderr, "usage: kernel pattern a b min_ms max_reps\n"); return 2; }
    const char *k = argv[1], *pat = argv[2];
    A = atoll(argv[3]); B = atoll(argv[4]);
    i64 min_ns = atoll(argv[5]) * 1000000, max_reps = atoll(argv[6]);
    struct { const char *name; void (*fn)(const i32 *, i64 *); i64 n_in, n_out; } t[] = {
        {"sq2x2", sq2x2, (A+1)*(B+1), A*B}, {"stencil1d3", stencil1d3, A+2, A},
        {"box3x3", box3x3, (A+2)*(B+2), A*B}, {"laplace5", laplace5, (A+2)*(B+2), A*B},
        {"conv3x3", conv3x3, (A+2)*(B+2), A*B}, {"life", life, (A+2)*(B+2), A*B},
        {"polymap", polymap, A, A}, {"transpose", transpose, A*B, A*B},
        {"maxpool2", maxpool2, 4*A*B, A*B}, {"sum", sum, A, 1}, {"dot", dot, 2*A, 1},
        {"scan", scan, A, A}, {"hist", hist, A, 64}, {"matmul", matmul, 2*A*A, A*A},
    };
    int which = -1;
    for (int i = 0; i < (int)(sizeof t / sizeof t[0]); i++) if (!strcmp(k, t[i].name)) which = i;
    if (which < 0) { printf("{\"impl\":\"c\",\"kernel\":\"%s\",\"status\":\"unsupported\"}\n", k); return 0; }
    i64 n_in = t[which].n_in, n_out = t[which].n_out;
    i32 *x = malloc((size_t)n_in * sizeof *x); i64 *o = malloc((size_t)n_out * sizeof *o);
    if (!x || !o) return 3;
    for (i64 i = 0; i < n_in; i++) x[i] = value(pat, i);
    volatile i64 sink = 0;
    t[which].fn(x, o); sink += o[0];  /* untimed warm-up */
    /* Calibrate calls per sample so one sample spans >= 1 ms of timer ticks. */
    i64 inner = 1;
    for (;;) {
        i64 start = now_ns();
        for (i64 i = 0; i < inner; i++) { t[which].fn(x, o); sink += o[n_out - 1]; }
        if (now_ns() - start >= 1000000 || inner >= (1 << 22)) break;
        inner *= 2;
    }
    i64 cap = max_reps < 3 ? 3 : max_reps, reps = 0, total = 0;
    i64 *s = malloc((size_t)cap * sizeof *s);
    while (reps < 3 || (total < min_ns && reps < cap)) {
        i64 start = now_ns();
        for (i64 i = 0; i < inner; i++) { t[which].fn(x, o); sink += o[n_out - 1]; }
        i64 batch = now_ns() - start;
        s[reps++] = batch / inner; total += batch;
    }
    const i64 M = 1000000007; i64 acc = 0;
    for (i64 i = 0; i < n_out; i++) acc = (acc + (((o[i] % M) + M) % M) * (i % 65521 + 1)) % M;
    qsort(s, (size_t)reps, sizeof *s, cmp);
    i64 med = reps % 2 ? s[reps / 2] : (s[reps / 2 - 1] + s[reps / 2]) / 2;
    printf("{\"impl\":\"c\",\"kernel\":\"%s\",\"status\":\"ok\",\"n_out\":%lld,\"checksum\":%lld,"
           "\"reps\":%lld,\"inner\":%lld,\"ns_min\":%lld,\"ns_median\":%lld,\"ns_total\":%lld}\n",
           k, (long long)n_out, (long long)acc, (long long)reps, (long long)inner, (long long)s[0],
           (long long)med, (long long)total);
    return 0;
}