"""The hand-written AVX2 sum and dot controls agree with plain integer arithmetic.

Each is built at fixed input counts that cover the vector tail and the points where the
32-bit lane totals are flushed to 64 bits, with every value at the 1023 limit so totals
pass int32. Rejections must return the first bad index plus one and leave the output
untouched. Builds with and without AVX2 run the same cases.
"""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
HAND = HERE / 'impl' / 'hand'
CC = os.environ.get('BENCH_CC') or shutil.which('gcc') or shutil.which('clang')
SENTINEL = 77

DRIVER = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
int32_t beryl_kernel(const int32_t *input, int64_t *output);
int main(int argc, char **argv) {
    int64_t n = atoll(argv[1]), bad_at = atoll(argv[3]);
    int32_t *x = malloc((size_t)n * sizeof *x);
    for (int64_t i = 0; i < n; i++)
        x[i] = argv[2][0] == 'm' ? 1023 : (int32_t)((uint32_t)(i * 2654435761u) >> 22);
    if (bad_at >= 0) x[bad_at] = atoi(argv[4]);
    int64_t out = 77;
    int32_t status = beryl_kernel(x, &out);
    printf("%d %lld\n", status, (long long)out);
    return 0;
}
'''


def values(n, fill):
    return [1023] * n if fill == 'max' else [(i * 2654435761 % 2**32) >> 22 for i in range(n)]


def expected(kernel, n, fill):
    x = values(n, fill)
    if kernel == 'sum':
        return sum(x)
    half = n // 2
    return sum(a * b for a, b in zip(x[:half], x[half:]))


@unittest.skipUnless(CC, 'no C compiler')
class HandAvx2Tests(unittest.TestCase):
    # sum flushes every 2^21 cells, dot every 2^15 cells of each input. The largest dot
    # case would overflow a 32-bit lane (4096 products near 2^20) without its flushes.
    COUNTS = {'sum': (256, 1000, 2**21 + 37), 'dot': (256, 2002, 2 * (2**17 + 19))}

    def run_case(self, exe, n, fill='hash', bad_at=-1, bad_value=0):
        try:
            out = subprocess.run([str(exe), str(n), fill, str(bad_at), str(bad_value)],
                                 capture_output=True, text=True, timeout=120)
        except OSError as error:  # e.g. Windows Application Control; never bypassed
            self.skipTest(f'cannot launch the test build: {error}')
        self.assertEqual(out.returncode, 0, out.stderr)
        status, value = out.stdout.split()
        return int(status), int(value)

    def build(self, tmp, kernel, n, flags):
        driver = tmp / 'driver.c'
        driver.write_text(DRIVER)
        exe = tmp / f'{kernel}-{n}-{len(flags)}.exe'
        built = subprocess.run([CC, '-O2', *flags, '-std=c11', f'-DBERYL_CELLS={n}', '-DBERYL_H=1',
                                '-DBERYL_W=1', str(HAND / f'{kernel}.c'), str(driver), '-o', str(exe)],
                               capture_output=True, text=True, timeout=300)
        self.assertEqual(built.returncode, 0, built.stderr)
        return exe

    def check(self, kernel, flags):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            for n in self.COUNTS[kernel]:
                exe = self.build(tmp, kernel, n, flags)
                for fill in ('hash', 'max'):
                    with self.subTest(n=n, fill=fill):
                        self.assertEqual(self.run_case(exe, n, fill), (0, expected(kernel, n, fill)))
                for at in (0, n // 2 + 3, n - 1):
                    for value in (1024, -1, 2**31 - 1):
                        with self.subTest(n=n, at=at, value=value):
                            self.assertEqual(self.run_case(exe, n, 'max', at, value), (at + 1, SENTINEL))

    def test_sum_avx2(self):
        self.check('sum', ['-mavx2'])

    def test_sum_portable(self):
        self.check('sum', ['-mno-avx2'])

    def test_dot_avx2(self):
        self.check('dot', ['-mavx2'])

    def test_dot_portable(self):
        self.check('dot', ['-mno-avx2'])


if __name__ == '__main__':
    unittest.main()
