/* Test harness for ABI v2 scale-v1 kernels: one array per input, generated in
   place; prints the int64_t status and only the sampled outputs.

   argv: n_out bad_index bad_value {count lo hi}... sample...
   with one {count lo hi} per input. Cell i of the inputs concatenated in
   declaration order holds lo + hash(i) % (hi - lo + 1), with hash as in
   tests/test_scale_large.py; bad_index >= 0 overwrites one such cell.
   Compile with -DBERYL_NIN=1..4, -DBERYL_IN0.. -DBERYL_IN3 for the inputs'
   C types, and -DBERYL_OUT. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#ifndef BERYL_OUT
#define BERYL_OUT int32_t
#endif
#if BERYL_NIN == 1
int64_t beryl_kernel_v2(const BERYL_IN0 *, BERYL_OUT *);
#define BERYL_CALL(in, out) beryl_kernel_v2(in[0], out)
#elif BERYL_NIN == 2
int64_t beryl_kernel_v2(const BERYL_IN0 *, const BERYL_IN1 *, BERYL_OUT *);
#define BERYL_CALL(in, out) beryl_kernel_v2(in[0], in[1], out)
#elif BERYL_NIN == 3
int64_t beryl_kernel_v2(const BERYL_IN0 *, const BERYL_IN1 *, const BERYL_IN2 *, BERYL_OUT *);
#define BERYL_CALL(in, out) beryl_kernel_v2(in[0], in[1], in[2], out)
#elif BERYL_NIN == 4
int64_t beryl_kernel_v2(const BERYL_IN0 *, const BERYL_IN1 *, const BERYL_IN2 *, const BERYL_IN3 *, BERYL_OUT *);
#define BERYL_CALL(in, out) beryl_kernel_v2(in[0], in[1], in[2], in[3], out)
#else
#error "BERYL_NIN must be 1 to 4"
#endif

static int64_t value_at(int64_t i, int64_t lo, int64_t hi) {
    uint32_t x = (uint32_t)((uint64_t)i * 2654435761u);
    x ^= x >> 15;
    return lo + (int64_t)(x % (uint64_t)(hi - lo + 1));
}

/* Fill input k (count cells from global cell `start`) as type T. */
#define BERYL_FILL(T)                                                         \
    do {                                                                      \
        T *p = malloc((size_t)(count ? count : 1) * sizeof *p);               \
        if (!p) return 3;                                                     \
        for (int64_t i = 0; i < count; i++) p[i] = (T)value_at(start + i, lo, hi); \
        if (bad >= start && bad < start + count) p[bad - start] = (T)bad_value; \
        in[k] = p;                                                            \
    } while (0)

int main(int argc, char **argv) {
    int first_sample = 4 + 3 * BERYL_NIN;
    if (argc < first_sample) return 2;
    int64_t n_out = atoll(argv[1]), bad = atoll(argv[2]), bad_value = atoll(argv[3]);
    void *in[4] = {0};
    int64_t start = 0;
    for (int k = 0; k < BERYL_NIN; k++) {
        int64_t count = atoll(argv[4 + 3 * k]), lo = atoll(argv[5 + 3 * k]), hi = atoll(argv[6 + 3 * k]);
        switch (k) {
        case 0: BERYL_FILL(BERYL_IN0); break;
#if BERYL_NIN > 1
        case 1: BERYL_FILL(BERYL_IN1); break;
#endif
#if BERYL_NIN > 2
        case 2: BERYL_FILL(BERYL_IN2); break;
#endif
#if BERYL_NIN > 3
        case 3: BERYL_FILL(BERYL_IN3); break;
#endif
        }
        start += count;
    }
    BERYL_OUT *out = malloc((size_t)n_out * sizeof *out);
    if (!out) return 3;
    for (int64_t i = 0; i < n_out; i++) out[i] = 7;
    printf("%lld", (long long)BERYL_CALL(in, out));
    for (int a = first_sample; a < argc; a++) printf(" %lld", (long long)out[atoll(argv[a])]);
    printf("\n");
    for (int k = 0; k < BERYL_NIN; k++) free(in[k]);
    free(out);
    return 0;
}
