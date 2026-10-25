/* Test harness for scale-v1 kernels: read n_in inputs, print status and outputs.
   Compile with -DBERYL_OUT=int64_t for kernels with an i64 output, -DBERYL_IN
   and -DBERYL_OUT for u8, i8 or i16 storage, and -DBERYL_INIT for an initial
   output value that fits a narrow output. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#ifndef BERYL_IN
#define BERYL_IN int32_t
#endif
#ifndef BERYL_OUT
#define BERYL_OUT int32_t
#endif
#ifndef BERYL_INIT
#define BERYL_INIT -9
#endif
int32_t beryl_kernel(const BERYL_IN *input, BERYL_OUT *output);
int main(int argc, char **argv) {
    if (argc != 3) return 2;
    long n_in = atol(argv[1]), n_out = atol(argv[2]);
    BERYL_IN *in = malloc((size_t)n_in * sizeof *in);
    BERYL_OUT *out = malloc((size_t)n_out * sizeof *out);
    if (!in || !out) return 3;
    for (long i = 0; i < n_in; i++) {
        int value;
        if (scanf("%d", &value) != 1) return 4;
        in[i] = (BERYL_IN)value;
    }
    for (long i = 0; i < n_out; i++) out[i] = BERYL_INIT;
    printf("%d", beryl_kernel(in, out));
    for (long i = 0; i < n_out; i++) printf(" %lld", (long long)out[i]);
    printf("\n");
    free(in);
    free(out);
    return 0;
}
