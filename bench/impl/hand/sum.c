/* Hand-written AVX2 control: what a careful programmer writes for this kernel under
   Beryl's terms - beryl_kernel ABI, the input count fixed at compile time
   (-DBERYL_CELLS), int32 input in 0..=1023, an int64 output, timed by the same harness.
   One pass checks and sums. Values lie in 0..=1023 exactly when their bitwise OR does,
   so the check is one OR per vector. The output is written only after the whole input
   passed; on a bad value a plain scan finds the first one. */
#include <stdint.h>
#if defined(__AVX2__)
#include <immintrin.h>
#endif
#ifndef BERYL_CELLS
#error "compile with -DBERYL_CELLS=<input count> (bench/axiom_native.py does this)"
#endif

#define N ((int64_t)BERYL_CELLS)
/* Cells per flush to 64 bits: each 32-bit lane then holds at most 2^16 values of 1023. */
#define BLOCK (INT64_C(1) << 21)

static int32_t first_bad(const int32_t *x) {
    for (int64_t i = 0; i < N; ++i)
        if ((uint32_t)x[i] > 1023u) return (int32_t)(i + 1);
    return 0;
}

#if defined(__AVX2__)
static int64_t lanes(__m256i v) {
    int32_t l[8];
    _mm256_storeu_si256((__m256i *)l, v);
    return (int64_t)l[0] + l[1] + l[2] + l[3] + l[4] + l[5] + l[6] + l[7];
}
#endif

int32_t beryl_kernel(const int32_t *input, int64_t *output) {
    int64_t total = 0, i = 0;
    uint32_t seen = 0;
#if defined(__AVX2__)
    __m256i any = _mm256_setzero_si256();
    while (i + 32 <= N) {
        int64_t stop = N - i > BLOCK ? i + BLOCK : N;
        __m256i a0 = _mm256_setzero_si256(), a1 = a0, a2 = a0, a3 = a0;
        for (; i + 32 <= stop; i += 32) {
            __m256i v0 = _mm256_loadu_si256((const __m256i *)(input + i));
            __m256i v1 = _mm256_loadu_si256((const __m256i *)(input + i + 8));
            __m256i v2 = _mm256_loadu_si256((const __m256i *)(input + i + 16));
            __m256i v3 = _mm256_loadu_si256((const __m256i *)(input + i + 24));
            any = _mm256_or_si256(any, _mm256_or_si256(_mm256_or_si256(v0, v1), _mm256_or_si256(v2, v3)));
            a0 = _mm256_add_epi32(a0, v0);
            a1 = _mm256_add_epi32(a1, v1);
            a2 = _mm256_add_epi32(a2, v2);
            a3 = _mm256_add_epi32(a3, v3);
        }
        total += lanes(a0) + lanes(a1) + lanes(a2) + lanes(a3);
    }
    int32_t l[8];
    _mm256_storeu_si256((__m256i *)l, any);
    for (int k = 0; k < 8; ++k) seen |= (uint32_t)l[k];
#endif
    for (; i < N; ++i) {
        seen |= (uint32_t)input[i];
        total += input[i];
    }
    if (seen > 1023u) return first_bad(input);
    *output = total;
    return 0;
}
