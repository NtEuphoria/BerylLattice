/* Hand-written C for the canonical stencil under the generated kernel's own
   terms: compile-time shape (-DBERYL_H, -DBERYL_W), int32 input/output, the
   beryl_kernel ABI, and the same input precondition. Timed by the same
   harness as the Axiom-generated kernel, so the comparison is like for like. */
#include <stdint.h>
#if !defined(BERYL_H) || !defined(BERYL_W)
#error "compile with -DBERYL_H=<height> -DBERYL_W=<width> (bench/axiom_native.py does this)"
#endif

int32_t beryl_kernel(const int32_t *input, int32_t *output) {
    enum { H = BERYL_H, W = BERYL_W, N = (BERYL_H + 1) * (BERYL_W + 1) };
    for (int32_t i = 0; i < N; ++i)
        if (input[i] < 0 || input[i] > 1023) return i + 1;  /* preserve output on failure */
    for (int32_t r = 0; r < H; ++r)
        for (int32_t c = 0; c < W; ++c) {
            int32_t i = r * (W + 1) + c;
            int32_t x = input[i] + 1, y = input[i + 1] + 1;
            int32_t z = input[i + W + 1] + 1, t = input[i + W + 2] + 1;
            output[r * W + c] = ((x * x + y * y) + z * z) + t * t;
        }
    return 0;
}
