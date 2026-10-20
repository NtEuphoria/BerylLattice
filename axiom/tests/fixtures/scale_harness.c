/* Test harness for scale-v1 kernels: read n_in inputs, print status and outputs. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
int32_t beryl_kernel(const int32_t *input, int32_t *output);
int main(int argc, char **argv) {
    if (argc != 3) return 2;
    long n_in = atol(argv[1]), n_out = atol(argv[2]);
    int32_t *in = malloc((size_t)n_in * sizeof *in), *out = malloc((size_t)n_out * sizeof *out);
    if (!in || !out) return 3;
    for (long i = 0; i < n_in; i++) if (scanf("%d", &in[i]) != 1) return 4;
    for (long i = 0; i < n_out; i++) out[i] = -9;
    printf("%d", beryl_kernel(in, out));
    for (long i = 0; i < n_out; i++) printf(" %d", out[i]);
    printf("\n");
    return 0;
}
