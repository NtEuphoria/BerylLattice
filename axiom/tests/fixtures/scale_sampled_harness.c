/* Test harness for large scale-v1 kernels: generate the inputs in place, print
   the status and only the sampled outputs.

   argv: n_in n_out bad_index bad_value n_segments {end lo hi}... sample...
   Input i of the segment [start, end) holds lo + hash(i) % (hi - lo + 1), with
   hash as in tests/test_scale_large.py; bad_index >= 0 overwrites one value.
   Compile with -DBERYL_IN and -DBERYL_OUT as for scale_harness.c. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#ifndef BERYL_IN
#define BERYL_IN int32_t
#endif
#ifndef BERYL_OUT
#define BERYL_OUT int32_t
#endif
int32_t beryl_kernel(const BERYL_IN *input, BERYL_OUT *output);

static int64_t value_at(int64_t i, int64_t lo, int64_t hi) {
    uint32_t x = (uint32_t)((uint64_t)i * 2654435761u);
    x ^= x >> 15;
    return lo + (int64_t)(x % (uint64_t)(hi - lo + 1));
}

int main(int argc, char **argv) {
    if (argc < 6) return 2;
    int64_t n_in = atoll(argv[1]), n_out = atoll(argv[2]), bad = atoll(argv[3]), bad_value = atoll(argv[4]);
    int segments = atoi(argv[5]), first_sample = 6 + 3 * segments;
    if (argc < first_sample) return 2;
    BERYL_IN *in = malloc((size_t)n_in * sizeof *in);
    BERYL_OUT *out = malloc((size_t)n_out * sizeof *out);
    if (!in || !out) return 3;
    int64_t start = 0;
    for (int s = 0; s < segments; s++) {
        int64_t end = atoll(argv[6 + 3 * s]), lo = atoll(argv[7 + 3 * s]), hi = atoll(argv[8 + 3 * s]);
        for (int64_t i = start; i < end; i++) in[i] = (BERYL_IN)value_at(i, lo, hi);
        start = end;
    }
    if (start != n_in) return 4;
    if (bad >= 0) in[bad] = (BERYL_IN)bad_value;
    for (int64_t i = 0; i < n_out; i++) out[i] = 7;
    printf("%d", beryl_kernel(in, out));
    for (int a = first_sample; a < argc; a++) printf(" %lld", (long long)out[atoll(argv[a])]);
    printf("\n");
    free(in);
    free(out);
    return 0;
}
