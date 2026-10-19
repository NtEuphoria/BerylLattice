/* Hand-written control: the obvious C for this kernel under Beryl's terms -
   beryl_kernel ABI, compile-time shape (-DBERYL_H, -DBERYL_W), int32 input
   and output, the same input precondition, timed by the same harness. */
#include <stdint.h>
#if !defined(BERYL_H) || !defined(BERYL_W)
#error "compile with -DBERYL_H=<height> -DBERYL_W=<width> (bench/axiom_native.py does this)"
#endif

int32_t beryl_kernel(const int32_t *input, int32_t *output) {
    enum { N = BERYL_H * BERYL_W };
    for (int32_t i = 0; i < N; ++i)
        if (input[i] < 0 || input[i] > 1023) return i + 1;
    enum { W = BERYL_W };
    for (int32_t i = 0; i < W; ++i) {
        int32_t x = input[i];
        output[i] = x * x * x + 3 * x + 7;
    }
    return 0;
}
