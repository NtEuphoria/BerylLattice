"""Whole-input reductions check their inputs in the same pass that sums them."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from axiom.frontend import admit_source, parse_source
from axiom.reference import evaluate_source
from axiom.scale_c import compile_scale_native
from tests.test_scale_family import SUM
from tests.test_scale_i64 import DOT, wide

HALF = '''module half;
shape H = 1;
shape W = 1;
input x: i32[1,{n}] in 0..=1023;
let t[r in 0..H,c in 0..W] = sum(k in 0..{m}: x[0,k]);
output s[r in 0..H,c in 0..W] = t[r,c];
'''


def preflight_loop(n_in):
    return f'ax_invalid = beryl_outside(input, 0, {n_in},'.encode()


class FusedCheckTests(unittest.TestCase):
    def test_whole_input_sums_have_no_separate_preflight(self):
        for source, n_in in ((SUM.format(n=1 << 20).encode(), 1 << 20), (wide(SUM.format(n=1 << 20)), 1 << 20),
                             (wide(DOT.format(n=1 << 19)), 1 << 20)):
            c = compile_scale_native(source).artifact.c_source
            with self.subTest(source=source[:12]):
                self.assertIn(b'uint32_t *bad)', c)
                self.assertNotIn(preflight_loop(n_in), c)

    def test_partial_sums_keep_the_preflight(self):
        # The sum reads only half the input, so the other half still needs its own check.
        c = compile_scale_native(HALF.format(n=1 << 20, m=1 << 19).encode()).artifact.c_source
        self.assertNotIn(b'uint32_t *bad)', c)
        self.assertIn(preflight_loop(1 << 20), c)

    def test_native_results_and_first_bad_index(self):
        harness = Path(__file__).parent / 'fixtures' / 'scale_harness.c'
        cases = [(SUM.format(n=1 << 17).encode(), 'int32_t'), (wide(SUM.format(n=1 << 17)), 'int64_t'),
                 (wide(DOT.format(n=1 << 16)), 'int64_t')]
        with tempfile.TemporaryDirectory() as tmp:
            for number, (source, out) in enumerate(cases):
                kernel = admit_source(parse_source(source))
                n = kernel.input_count
                c = Path(tmp) / f'k{number}.c'
                c.write_bytes(compile_scale_native(source).artifact.c_source
                              .replace(b'int main(void)', b'int beryl_unused_main(void)'))
                exe = Path(tmp) / f'k{number}.exe'
                try:
                    built = subprocess.run(['clang', '-O2', '-std=c11', '-Wall', '-Werror', f'-DBERYL_OUT={out}',
                                            str(c), str(harness), '-o', str(exe)], capture_output=True, text=True)
                except OSError as error:
                    self.skipTest(f'no C compiler: {error}')
                self.assertEqual(built.returncode, 0, built.stderr)  # a compile error is a failure, not a skip
                for threads in ('1', '4'):
                    for bad in ((), (0,), (n // 2,), (n - 1,), (n - 5, 7)):
                        data = [(i * 2654435761 & 0xFFFFFFFF) >> 22 for i in range(n)]
                        for index in bad:
                            data[index] = 1024 if index % 2 else -1
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
