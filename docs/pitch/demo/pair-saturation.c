/* standalone intrinsics test, not beryl output, not PyTorch.

   What the AVX2 u8 x i8 pair multiply-add (vpmaddubsw + vpmaddwd) returns
   when nothing checks the pair bound: 300 activations of 255 times 300
   weights of 127. vpmaddubsw adds each pair of products into a signed
   16-bit lane and silently clips at 32,767; 2 x 255 x 127 = 64,770 does
   not fit, so the fast result is about half the exact one. With inputs
   to 127 the pair is 32,258, which fits, and both results agree.

   Build: gcc -O2 -mavx2 pair-saturation.c -o sat */
#include <immintrin.h>
#include <stdint.h>
#include <stdio.h>

static int32_t dot_madd(const uint8_t *p, const int8_t *q, int n) {
    __m256i acc = _mm256_setzero_si256(), ones = _mm256_set1_epi16(1);
    int i = 0;
    for (; i + 32 <= n; i += 32) {
        __m256i a = _mm256_loadu_si256((const __m256i *)(p + i));
        __m256i b = _mm256_loadu_si256((const __m256i *)(q + i));
        acc = _mm256_add_epi32(acc, _mm256_madd_epi16(_mm256_maddubs_epi16(a, b), ones));
    }
    int32_t lanes[8], total = 0;
    _mm256_storeu_si256((__m256i *)lanes, acc);
    for (int k = 0; k < 8; ++k) total += lanes[k];
    for (; i < n; ++i) total += p[i] * q[i];
    return total;
}

static int64_t dot_exact(const uint8_t *p, const int8_t *q, int n) {
    int64_t total = 0;
    for (int i = 0; i < n; ++i) total += (int64_t)p[i] * q[i];
    return total;
}

int main(void) {
    enum { N = 300 };
    uint8_t a[N];
    int8_t w[N];
    for (int i = 0; i < N; ++i) { a[i] = 255; w[i] = 127; }
    printf("right answer                         %lld\n", (long long)dot_exact(a, w, N));
    printf("fast instruction, no range check     %d\n", dot_madd(a, w, N));
    for (int i = 0; i < N; ++i) a[i] = 127;
    printf("inputs to 127, right answer          %lld\n", (long long)dot_exact(a, w, N));
    printf("inputs to 127, fast instruction      %d\n", dot_madd(a, w, N));
    return 0;
}
