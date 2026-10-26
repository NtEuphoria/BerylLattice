"""Cell orders: tiles for column-strided loads, per-cell sums for column-strided sum bodies."""
import unittest

from axiom.frontend import admit_source, parse_source
from axiom.scale_c import compile_scale_native
from tests.test_scale_family import BOX, MATMUL
from tests.test_scale_minmax import assert_native_matches

# The output is H x W and reads the W x H input across its rows.
TRANSPOSE = '''module transpose;
shape H = {h};
shape W = {w};
input m: i32[W,H] in -1000..=1000;
let t[r in 0..H,c in 0..W] = m[c,r];
output o[r in 0..H,c in 0..W] = {out};
'''


# Weights stored [out, in], as torch.nn.Linear stores them: each output is a
# dot product of two arrays contiguous in j.
LINEAR = '''module linear;
shape H = 1;
shape W = {w};
input a: {t}[1,{n}] in -128..=127;
input k: {t}[W,{n}] in -127..=127;
let t[r in 0..H,c in 0..W] = sum(j in 0..{n}: a[0,j]*k[c,j]);
output y[r in 0..H,c in 0..W] = t[r,c];
'''


def _c(text):
    compiled = compile_scale_native(text.encode())
    assert compiled.artifact is not None, compiled.reason
    return compiled.artifact.c_source


class TileEmissionTests(unittest.TestCase):
    def test_a_column_strided_load_is_tiled(self):
        for h, w in ((2048, 2048), (37, 53), (300, 17)):
            c = _c(TRANSPOSE.format(h=h, w=w, out='t[r,c]'))
            with self.subTest(shape=(h, w)):
                self.assertIn(b'16 x 16 tiles', c)

    def test_contiguous_programs_keep_their_order(self):
        for text in (BOX.format(h=200, w=180), MATMUL.format(n=64)):
            with self.subTest(text=text.split(';')[0]):
                self.assertNotIn(b'16 x 16 tiles', _c(text))

    def test_tiny_outputs_are_not_tiled(self):
        self.assertNotIn(b'16 x 16 tiles', _c(TRANSPOSE.format(h=20, w=1, out='t[r,c]')))


class SumOrderTests(unittest.TestCase):
    def test_a_column_strided_sum_body_is_summed_per_cell(self):
        for t in ('i8', 'i32'):
            with self.subTest(t=t):
                self.assertNotIn(b'row segment', _c(LINEAR.format(w=1024, n=4096, t=t)))

    def test_matmul_keeps_row_accumulation(self):
        self.assertIn(b'row segment', _c(MATMUL.format(n=64)))

    def test_native_c_matches_the_reference(self):
        assert_native_matches(self, [LINEAR.format(w=64, n=1024, t='i8'), LINEAR.format(w=40, n=300, t='i32'),
                                     LINEAR.format(w=9, n=5000, t='i8')])


class TileNativeTests(unittest.TestCase):
    def test_native_c_matches_the_reference(self):
        # Edge tiles in both directions, a single partial tile, serial and parallel sizes.
        kernels = [TRANSPOSE.format(h=h, w=w, out=out) for h, w, out in (
            (37, 53, 't[r,c]'), (300, 17, '2*t[r,c] + 1'), (15, 15, 't[r,c]'), (512, 384, 'max(t[r,c], 0)'),
            (1024, 1000, 't[r,c]'))]
        for text in kernels:
            self.assertEqual(admit_source(parse_source(text.encode())).profile, 'scale-v1')
        assert_native_matches(self, kernels)


if __name__ == '__main__':
    unittest.main()
