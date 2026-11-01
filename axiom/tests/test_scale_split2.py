"""Whole-input sums check by bitwise OR where the range allows it, and hint an unroll.

A value v = x - lo lies in 0..=span exactly when the OR of all such values does, if
span + 1 is a power of two. The OR is cheaper than the unsigned maximum used otherwise,
and the final test (`ax_u > span`) is the same. The sum's inner loop also gets
`_Pragma("GCC unroll 4")`. Both change the generated C, so these programs carry the
`beryl-loop-c-split2` codegen version.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from axiom.frontend import admit_source, parse_source
from axiom.reference import evaluate_source
from axiom.scale_c import compile_scale_native
from tests.test_scale_family import MATMUL, SUM
from tests.test_scale_i64 import DOT, wide

CC = os.environ.get('CC', 'clang')
OR = b'ax_u0 |= ax_v;'
MAXIMUM = b'ax_u0 = ax_v > ax_u0 ? ax_v : ax_u0;'
HINT = b'_Pragma("GCC unroll 4")'


def ranged(text, lo, hi):
    return text.replace('in 0..=1023', f'in {lo}..={hi}')


class SplitCheckTests(unittest.TestCase):
    def test_power_of_two_spans_check_by_or(self):
        for source in (SUM.format(n=1 << 20).encode(), wide(DOT.format(n=1 << 19)),
                       ranged(SUM.format(n=1 << 20), -512, 511).encode(), ranged(SUM.format(n=1 << 20), 3, 3).encode()):
            c = compile_scale_native(source).artifact.c_source
            with self.subTest(source=source[:40]):
                self.assertIn(OR, c)
                self.assertNotIn(b'ax_v > ax_u', c)

    def test_other_spans_keep_the_maximum(self):
        for lo, hi in ((0, 1000), (-512, 512), (1, 1023)):
            c = compile_scale_native(ranged(SUM.format(n=1 << 20), lo, hi).encode()).artifact.c_source
            with self.subTest(lo=lo, hi=hi):
                self.assertIn(MAXIMUM, c)
                self.assertNotIn(OR, c)

    def test_split_sums_carry_the_hint_and_version(self):
        artifact = compile_scale_native(SUM.format(n=1 << 20).encode()).artifact
        self.assertEqual(artifact.c_source.count(HINT), 1)
        self.assertTrue(artifact.codegen_version.startswith('beryl-loop-c-split2-'), artifact.codegen_version)
        # Programs without a split sum are untouched.
        other = compile_scale_native(MATMUL.format(n=64).encode()).artifact
        self.assertNotIn(HINT, other.c_source)
        self.assertNotIn('split2', other.codegen_version)

    def test_fused_sums_add_in_wrapping_arithmetic(self):
        # The sum adds each value before the check has rejected it, so an out-of-range
        # value (2^31 - 1, say) must wrap, never overflow a signed type (undefined in C).
        for source, adds in ((SUM.format(n=1 << 20).encode(), (b'acc = (int32_t)((uint32_t)acc + ',)),
                             (wide(SUM.format(n=1 << 20)), (b'ax_b = (int32_t)((uint32_t)ax_b + ',
                                                            b'acc = (int64_t)((uint64_t)acc + (uint64_t)ax_b)')),
                             (wide(DOT.format(n=1 << 19)), (b'ax_b = (int32_t)((uint32_t)ax_b + ',
                                                            b'(int32_t)((uint32_t)input['))):
            c = compile_scale_native(source).artifact.c_source
            partial = c[c.index(b'static int32_t beryl_partial') if b'static int32_t beryl_partial' in c
                        else c.index(b'static int64_t beryl_partial'):]
            partial = partial[:partial.index(b'\n}\n')]
            with self.subTest(source=source[:12]):
                for add in adds:
                    self.assertIn(add, partial)
                self.assertNotIn(b'acc += ', partial)
                self.assertNotIn(b'ax_b += ', partial)

    def test_native_results_and_first_bad_index(self):
        harness = Path(__file__).parent / 'fixtures' / 'scale_harness.c'
        cases = [(SUM.format(n=1 << 17).encode(), 'int32_t', 0, 1023),
                 (wide(DOT.format(n=1 << 16)), 'int64_t', 0, 1023),
                 (ranged(SUM.format(n=1 << 17), -512, 511).encode(), 'int32_t', -512, 511),
                 (ranged(SUM.format(n=1 << 17), 0, 1000).encode(), 'int32_t', 0, 1000)]
        with tempfile.TemporaryDirectory() as tmp:
            for number, (source, out, lo, hi) in enumerate(cases):
                kernel = admit_source(parse_source(source))
                n = kernel.input_count
                c = Path(tmp) / f'k{number}.c'
                c.write_bytes(compile_scale_native(source).artifact.c_source
                              .replace(b'int main(void)', b'int beryl_unused_main(void)'))
                exe = Path(tmp) / f'k{number}.exe'
                try:
                    built = subprocess.run([CC, '-O2', '-march=native', '-std=c11', '-Wall', '-Werror', '-pthread',
                                            f'-DBERYL_OUT={out}', str(c), str(harness), '-o', str(exe)],
                                           capture_output=True, text=True)
                except OSError as error:
                    self.skipTest(f'no C compiler: {error}')
                self.assertEqual(built.returncode, 0, built.stderr)  # a compile error is a failure, not a skip
                span = hi - lo + 1
                for threads in ('1', '4'):
                    # Bad values just past each end, and the extremes of int32.
                    for bad in ((), ((0, hi + 1),), ((n // 2, lo - 1),), ((n - 1, -2**31),),
                                ((n - 5, 2**31 - 1), (n - 3, hi + 1))):
                        data = [lo + ((i * 2654435761 & 0xFFFFFFFF) % span) for i in range(n)]
                        data[1], data[2] = lo, hi
                        for index, value in bad:
                            data[index] = value
                        try:
                            ran = subprocess.run([str(exe), str(n), '1'], input=' '.join(map(str, data)),
                                                 capture_output=True, text=True, check=True,
                                                 env={'BERYL_THREADS': threads, 'SYSTEMROOT': 'C:\\Windows'})
                        except OSError as error:  # Windows Application Control; never bypassed
                            self.skipTest(f'executable launch refused: {error}')
                        status, *values = map(int, ran.stdout.split())
                        ref = evaluate_source(kernel.source_module, data, [-9])
                        with self.subTest(case=number, threads=threads, bad=bad):
                            self.assertEqual(status, 0 if ref.first_bad_index is None else ref.first_bad_index + 1)
                            self.assertEqual(tuple(values), ref.output)


if __name__ == '__main__':
    unittest.main()
