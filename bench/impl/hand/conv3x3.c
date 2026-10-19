/* Hand-written control: the obvious C for this kernel under Beryl's terms -
   beryl_kernel ABI, compile-time shape (-DBERYL_H, -DBERYL_W), int32 input
   and output, the same input precondition, timed by the same harness. */
#include <stdint.h>
#if !defined(BERYL_H) || !defined(BERYL_W)
#error "compile with -DBERYL_H=<height> -DBERYL_W=<width> (bench/axiom_native.py does this)"
#endif

int32_t beryl_kernel(const int32_t *input, int32_t *output) {
    enum { N = (BERYL_H + 2) * (BERYL_W + 2) };
    for (int32_t i = 0; i < N; ++i)
        if (input[i] < 0 || input[i] > 1023) return i + 1;
    enum { H = BERYL_H, W = BERYL_W, C = BERYL_W + 2 };
    for (int32_t r = 0; r < H; ++r)
        for (int32_t c = 0; c < W; ++c) {
            const int32_t *a = input + r * C + c, *b = a + C, *d = b + C;
            output[r * W + c] = a[0] + 2*a[1] + a[2] + 2*b[0] + 4*b[1] + 2*b[2] + d[0] + 2*d[1] + d[2];
        }
    return 0;
}
