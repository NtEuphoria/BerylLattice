"""u8 x i8 dot products through AVX2's saturating pair multiply-add, used only where every
pair of products provably fits i16."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from axiom.model import C_TYPES
from axiom.reference import evaluate_cells
from axiom.scale_c import compile_scale_native
from tests.test_scale_abi2 import HARNESS, QLINEAR
from tests.test_scale_large import generator, kernel_of

# Activations in 0..=A, i8 weights stored [out, in], an i32 bias. A pair of products reaches
# 2 * A * 127, which fits i16 up to A = 129.
LAYER = QLINEAR.replace('in 0..=255', 'in 0..={a}')


def dot_used(text, **options):
    artifact = compile_scale_native(text.encode(), **options).artifact
    return b'beryl_dot_u8i8(' in artifact.c_source, artifact


class EmissionTests(unittest.TestCase):
    def test_used_exactly_while_every_pair_fits_i16(self):
        for a, expected in ((127, True), (129, True), (130, False), (255, False)):
            with self.subTest(a=a):
                used, artifact = dot_used(LAYER.format(a=a, w=37, n=300))
                self.assertEqual(used, expected)
                self.assertEqual('madd' in artifact.codegen_version, expected)

    def test_only_u8_by_i8_contiguous_sums(self):
        # Both signed, both unsigned, and weights stored [in, out] (strided along the sum).
        signed = LAYER.format(a=127, w=37, n=300).replace('input a: u8[1,300] in 0..=127',
                                                         'input a: i8[1,300] in -64..=63')
        unsigned = LAYER.format(a=127, w=37, n=300).replace('input k: i8[W,300] in -127..=127',
                                                           'input k: u8[W,300] in 0..=127')
        strided = (LAYER.format(a=127, w=37, n=300).replace('input k: i8[W,300]', 'input k: i8[300,W]')
                   .replace('k[c,j]', 'k[j,c]'))
        for text in (signed, unsigned, strided):
            with self.subTest(text=text.split('\n')[3:5]):
                self.assertFalse(dot_used(text)[0])

    def test_the_helper_keeps_a_portable_fallback(self):
        code = dot_used(LAYER.format(a=127, w=37, n=300))[1].c_source
        self.assertIn(b'#if defined(__AVX2__)', code)
        self.assertIn(b'_mm256_maddubs_epi16(', code)
        self.assertIn(b'for (; i < n; ++i) total += p[i] * q[i];', code)


class NativeTests(unittest.TestCase):
    """Against the sampled reference, on hashed data and at the pair bound's extremes."""

    def run_layer(self, text, segments, value_at, tmp, threads=('1', '4')):
        kernel = kernel_of(text)
        artifact = compile_scale_native(text.encode()).artifact
        self.assertIn(b'beryl_dot_u8i8(', artifact.c_source)
        c, exe = Path(tmp) / 'k.c', Path(tmp) / 'k.exe'
        c.write_bytes(artifact.c_source.replace(b'int main(void)', b'int beryl_unused_main(void)'))
        types = [C_TYPES[t] for t in kernel.input_types]
        try:
            built = subprocess.run(['clang', '-O2', '-march=native', '-std=c11', '-Wall', '-Werror',
                                    f'-DBERYL_NIN={len(types)}', *(f'-DBERYL_IN{k}={t}' for k, t in enumerate(types)),
                                    f'-DBERYL_OUT={C_TYPES[kernel.output_type]}', str(c), str(HARNESS),
                                    '-o', str(exe)], capture_output=True, text=True)
        except OSError as error:
            self.skipTest(f'no C compiler: {error}')
        self.assertEqual(built.returncode, 0, built.stderr)
        n_out = kernel.output_count
        samples = sorted(set(range(min(n_out, 40))) | {n_out // 2, n_out - 1})
        expected = list(evaluate_cells(kernel.source_module, value_at, samples))
        spec, start = [], 0
        for end, lo, hi in segments:
            spec += [end - start, lo, hi]
            start = end
        for thread_count in threads:
            try:
                ran = subprocess.run([str(exe), str(n_out), '-1', '0', *map(str, spec), *map(str, samples)],
                                     capture_output=True, text=True, check=True, timeout=120,
                                     env={'BERYL_THREADS': thread_count, 'SYSTEMROOT': 'C:\\Windows'})
            except OSError as error:  # Windows Application Control; never bypassed
                self.skipTest(f'executable launch refused: {error}')
            with self.subTest(threads=thread_count):
                self.assertEqual(list(map(int, ran.stdout.split())), [0, *expected])

    def test_hashed_data(self):
        # 300 terms leave a 12-term tail after the 32-wide steps; 2048 outputs run in parallel.
        for text in (LAYER.format(a=127, w=37, n=300), LAYER.format(a=129, w=2048, n=64),
                     LAYER.format(a=127, w=11, n=31)):
            kernel = kernel_of(text)
            segments, value_at = generator(kernel)
            with self.subTest(size=text.split('\n')[2]), tempfile.TemporaryDirectory() as tmp:
                self.run_layer(text, segments, value_at, tmp)

    def test_every_pair_at_the_bound(self):
        # Every activation 129 and every weight +-127: each pair is +-32766, one short of
        # saturating. Wrong pairing or saturation would change every output.
        text = LAYER.format(a=129, w=37, n=300)
        kernel = kernel_of(text)
        n_a, n_k = 300, 37 * 300
        for weight in (127, -127):
            segments = [(n_a, 129, 129), (n_a + n_k, weight, weight), (kernel.input_count, -100000, 100000)]

            def value_at(i, segments=segments):
                for end, lo, hi in segments:
                    if i < end:
                        return lo if lo == hi else generator(kernel)[1](i)
                raise IndexError(i)
            with self.subTest(weight=weight), tempfile.TemporaryDirectory() as tmp:
                self.run_layer(text, segments, value_at, tmp)


if __name__ == '__main__':
    unittest.main()
