"""The input range check: one unsigned maximum per value, and still the exact first bad index."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from axiom.frontend import admit_source, parse_source
from axiom.model import C_TYPES, TYPE_BOUNDS
from axiom.reference import evaluate_source
from axiom.scale_c import compile_scale_native
from tests.test_scale_family import BOX, SUM
from tests.test_scale_i64 import DOT, wide
from tests.test_scale_ranges import data_for
from tests.test_scale_shift import EDGE_I32
from tests.test_scale_storage import BLUR, BLUR_OUT, DENSE

# Two inputs with different signed ranges: the check differs per input.
SPLIT = '''module split;
shape H = 1;
shape W = {w};
input a: i32[1,W] in -5..=7;
input b: i32[1,W] in 100..=2000;
let t[r in 0..H,c in 0..W] = a[r,c]*b[r,c];
output y[r in 0..H,c in 0..W] = t[r,c];
'''


def _c(text):
    compiled = compile_scale_native(text.encode() if isinstance(text, str) else text)
    assert compiled.artifact is not None, compiled.reason
    return compiled.artifact.c_source


class CheckEmissionTests(unittest.TestCase):
    def test_the_preflight_is_one_unsigned_maximum_per_value(self):
        for text in (BOX.format(h=200, w=180), SPLIT.format(w=100000), BLUR.format(h=40, w=30, lo=16, hi=235, out=BLUR_OUT)):
            c = _c(text)
            with self.subTest(text=text.split(';')[0]):
                self.assertIn(b'beryl_outside(input, ', c)
                self.assertIn(b'top = v > top ? v : top;', c)
                self.assertNotIn(b'ax_invalid |= (uint32_t)(input[i]', c)

    def test_a_range_covering_its_type_has_no_check(self):
        for text in (EDGE_I32.format(w=300), BLUR.format(h=40, w=30, lo=0, hi=255, out=BLUR_OUT)):
            c = _c(text)
            with self.subTest(text=text.split(';')[0]):
                self.assertNotIn(b'beryl_outside(input,', c)

    def test_only_inputs_narrower_than_their_type_are_checked(self):
        # DENSE's activations cover i8; its weights are -127..=127, so only they are checked.
        c = _c(DENSE.format(w=8, n=64))
        self.assertIn(b', -127, 254u)', c)
        self.assertNotIn(b', -128, 255u)', c)

    def test_fused_sums_track_an_unsigned_maximum(self):
        for source in (SUM.format(n=1 << 20).encode(), wide(DOT.format(n=1 << 19))):
            c = _c(source)
            with self.subTest(source=source[:12]):
                self.assertIn(b'uint32_t *bad)', c)
                self.assertIn(b'ax_u0 = ax_v > ax_u0 ? ax_v : ax_u0;', c)
                self.assertNotIn(b'ax_bad |= (uint32_t)(input[', c)


class CheckNativeTests(unittest.TestCase):
    def test_first_bad_index_at_every_edge(self):
        harness = Path(__file__).parent / 'fixtures' / 'scale_harness.c'
        programs = [BOX.format(h=200, w=180), SUM.format(n=1 << 17), wide(DOT.format(n=1 << 16)).decode(),
                    SPLIT.format(w=100000), SPLIT.format(w=50), BLUR.format(h=60, w=50, lo=16, hi=235, out=BLUR_OUT),
                    BLUR.format(h=60, w=50, lo=0, hi=200, out=BLUR_OUT), DENSE.format(w=8, n=2048)]
        with tempfile.TemporaryDirectory() as tmp:
            for number, text in enumerate(programs):
                source = text.encode()
                kernel = admit_source(parse_source(source))
                c = Path(tmp) / f'k{number}.c'
                c.write_bytes(_c(source).replace(b'int main(void)', b'int beryl_unused_main(void)'))
                exe = Path(tmp) / f'k{number}.exe'
                initial = -9 if TYPE_BOUNDS[kernel.output_type][0] <= -9 else 7
                try:
                    built = subprocess.run(['clang', '-O2', '-std=c11', '-Wall', '-Werror',
                                            f'-DBERYL_IN={C_TYPES[kernel.input_type]}',
                                            f'-DBERYL_OUT={C_TYPES[kernel.output_type]}', f'-DBERYL_INIT={initial}',
                                            str(c), str(harness), '-o', str(exe)], capture_output=True, text=True)
                except OSError as error:
                    self.skipTest(f'no C compiler: {error}')
                self.assertEqual(built.returncode, 0, built.stderr)
                n, type_low, type_high = kernel.input_count, *TYPE_BOUNDS[kernel.input_type]
                cases = [()]
                start = 0
                for (rows, cols), (low, high) in zip(kernel.all_input_shapes, kernel.input_intervals):
                    end = start + rows * cols
                    for value in (low - 1, high + 1, type_low, type_high):
                        if type_low <= value <= type_high and not low <= value <= high:
                            cases += [((start, value),), ((end - 1, value),), (((start + end) // 2, value),
                                                                                ((start + end) // 2 + 3, low))]
                    start = end
                # Two bad values: the first one is reported.
                cases.append(((n - 2, kernel.input_intervals[-1][1] + 1), (n - 1, kernel.input_intervals[-1][1] + 1)))
                for bad in cases:
                    data = data_for(kernel, number)
                    for index, value in bad:
                        data[index] = value
                    if not all(type_low <= v <= type_high for v in data):
                        continue
                    ref = evaluate_source(kernel.source_module, data, [initial] * kernel.output_count)
                    for threads in ('1', '4'):
                        try:
                            ran = subprocess.run([str(exe), str(n), str(kernel.output_count)],
                                                 input=' '.join(map(str, data)), capture_output=True, text=True,
                                                 check=True, env={'BERYL_THREADS': threads, 'SYSTEMROOT': 'C:\\Windows'})
                        except OSError as error:  # Windows Application Control; never bypassed
                            self.skipTest(f'executable launch refused: {error}')
                        status, *values = map(int, ran.stdout.split())
                        with self.subTest(program=number, bad=bad, threads=threads):
                            self.assertEqual(status, 0 if ref.first_bad_index is None else ref.first_bad_index + 1)
                            self.assertEqual(tuple(values), ref.output)


if __name__ == '__main__':
    unittest.main()
