/* Hand-written AVX2 control: what a careful programmer writes for this kernel under
   Beryl's terms - beryl_kernel ABI, the input count fixed at compile time
   (-DBERYL_CELLS: x then y, half each), int32 input in 0..=1023, an int64 output, timed
   by the same harness. One pass checks and multiplies.
   - The check is one OR per vector: values lie in 0..=1023 exactly when their OR does.
   - Values in that range have a zero upper 16 bits, so vpmaddwd on the 32-bit lanes
     gives each exact product x*y (the upper halves add 0*0). That is one multiply
     instruction where vpmulld costs two on Zen 2.
   The output is written only after the whole input passed; on a bad value a plain scan
   finds the first one. */
#include <stdint.h>
#if defined(__AVX2__)
#include <immintrin.h>
#endif
#ifndef BERYL_CELLS
#error "compile with -DBERYL_CELLS=<input count> (bench/axiom_native.py does this)"
#endif

#define N ((int64_t)BERYL_CELLS)
#define L (N / 2)
/* Products per input before a flush to 64 bits: each 32-bit lane then holds at most
   2^10 products below 2^20. */
#define BLOCK (INT64_C(1) << 15)

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

static __m256i load(const int32_t *p) { return _mm256_loadu_si256((const __m256i *)p); }
#endif

int32_t beryl_kernel(const int32_t *input, int64_t *output) {
    const int32_t *x = input, *y = input + L;
    int64_t total = 0, i = 0;
    uint32_t seen = 0;
#if defined(__AVX2__)
    __m256i any = _mm256_setzero_si256();
    while (i + 32 <= L) {
        int64_t stop = L - i > BLOCK ? i + BLOCK : L;
        __m256i a0 = _mm256_setzero_si256(), a1 = a0, a2 = a0, a3 = a0;
        for (; i + 32 <= stop; i += 32) {
            __m256i x0 = load(x + i), x1 = load(x + i + 8), x2 = load(x + i + 16), x3 = load(x + i + 24);
            __m256i y0 = load(y + i), y1 = load(y + i + 8), y2 = load(y + i + 16), y3 = load(y + i + 24);
            __m256i o = _mm256_or_si256(_mm256_or_si256(x0, x1), _mm256_or_si256(x2, x3));
            o = _mm256_or_si256(o, _mm256_or_si256(_mm256_or_si256(y0, y1), _mm256_or_si256(y2, y3)));
            any = _mm256_or_si256(any, o);
            a0 = _mm256_add_epi32(a0, _mm256_madd_epi16(x0, y0));
            a1 = _mm256_add_epi32(a1, _mm256_madd_epi16(x1, y1));
            a2 = _mm256_add_epi32(a2, _mm256_madd_epi16(x2, y2));
            a3 = _mm256_add_epi32(a3, _mm256_madd_epi16(x3, y3));
        }
        total += lanes(a0) + lanes(a1) + lanes(a2) + lanes(a3);
    }
    int32_t l[8];
    _mm256_storeu_si256((__m256i *)l, any);
    for (int k = 0; k < 8; ++k) seen |= (uint32_t)l[k];
#endif
    for (; i < L; ++i) {
        seen |= (uint32_t)x[i] | (uint32_t)y[i];
        total += (int64_t)x[i] * y[i];
    }
    if (seen > 1023u) return first_bad(input);
    *output = total;
    return 0;
}
