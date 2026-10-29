"""Large data: 2^31 - 1 cell limits, the sampled reference, and a full-size int8 dense layer."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from axiom.frontend import admit_source, parse_source
from axiom.model import C_TYPES, DiagnosticError
from axiom.reference import evaluate_cells, evaluate_source
from axiom.scale_c import compile_scale_native
from tests.test_scale_family import BOX, MATMUL, ROWSUM, SUM, TRANSPOSE
from tests.test_scale_storage import BLUR, BLUR_OUT, DENSE
from tests.test_scale_tiles import LINEAR

LIMIT = 2 ** 31 - 1
# One output cell per input cell, at any width.
COPY = '''module copy;
shape H = 1;
shape W = {w};
input x: i8[1,W] in -100..=100;
let t[r in 0..H,c in 0..W] = x[r,c];
output y[r in 0..H,c in 0..W] = t[r,c];
'''
# A sum of n terms of a one-cell input, in exact int32_t blocks of 2^31 // 200 terms.
LONG_SUM = '''module long;
shape H = 1;
shape W = 1;
input x: u8[1,1] in 0..=200;
let t: i64[r in 0..H,c in 0..W] = sum(k in 0..{n}: x[0,0]);
output s: i64[r in 0..H,c in 0..W] = t[r,c];
'''


def hashed(i, lo, hi):
    """The value scale_sampled_harness.c generates at buffer position i."""
    x = (i * 2654435761) & 0xFFFFFFFF
    x ^= x >> 15
    return lo + x % (hi - lo + 1)


def generator(kernel):
    """value_at(i) over the input buffer, each input in its own declared range."""
    segments, start = [], 0
    for (rows, cols), (lo, hi) in zip(kernel.all_input_shapes, kernel.input_intervals):
        segments.append((start + rows * cols, lo, hi))
        start += rows * cols

    def value_at(i):
        for end, lo, hi in segments:
            if i < end:
                return hashed(i, lo, hi)
        raise IndexError(i)
    return segments, value_at


def kernel_of(text):
    return admit_source(parse_source(text.encode()))


class LimitTests(unittest.TestCase):
    def test_tensors_up_to_the_limit_are_admitted(self):
        kernel = kernel_of(COPY.format(w=LIMIT))
        self.assertEqual((kernel.input_count, kernel.output_count), (LIMIT, LIMIT))

    def test_one_cell_past_the_limit_is_refused(self):
        with self.assertRaises(DiagnosticError) as raised:
            kernel_of(COPY.format(w=LIMIT + 1))
        self.assertIn(str(LIMIT), str(raised.exception))

    def test_the_limit_is_per_input(self):
        # Two inputs of 2^30 cells each: past the limit together, which ABI 2's
        # int64_t status covers (tests/test_scale_abi2.py).
        text = ('module pair;\nshape H = 1;\nshape W = 1073741824;\n'
                'input x: i8[1,W] in 0..=1;\ninput y: i8[1,W] in 0..=1;\n'
                'let t[r in 0..H,c in 0..W] = x[r,c]+y[r,c];\n'
                'output o[r in 0..H,c in 0..W] = t[r,c];\n')
        self.assertEqual(kernel_of(text).input_count, 2 ** 31)
        with self.assertRaises(DiagnosticError):
            kernel_of(text.replace('input y: i8[1,W]', 'input y: i8[2,W]'))

    def test_sums_up_to_the_limit_are_admitted(self):
        kernel_of(LONG_SUM.format(n=LIMIT))
        with self.assertRaises(DiagnosticError):
            kernel_of(LONG_SUM.format(n=LIMIT + 1))

    def test_proof_and_emission_stay_flat_at_the_limit(self):
        compiled = compile_scale_native(COPY.format(w=LIMIT).encode())
        self.assertIsNotNone(compiled.artifact, compiled.reason)
        self.assertIn(f'BERYL_INPUT_COUNT = {LIMIT}'.encode(), compiled.artifact.c_source)

    def test_the_driver_allocates_large_buffers_on_the_heap(self):
        # 10 GB of buffers: static arrays this large do not link on Windows,
        # nor on Linux without -mcmodel=medium.
        large = compile_scale_native(COPY.format(w=LIMIT).encode()).artifact.c_source
        self.assertIn(b'int8_t *input = calloc(BERYL_INPUT_COUNT, sizeof *input);', large)
        self.assertIn(b'int32_t *output = calloc(BERYL_OUTPUT_COUNT, sizeof *output);', large)
        self.assertNotIn(b'static int8_t input[', large)
        small = compile_scale_native(COPY.format(w=1000).encode()).artifact.c_source
        self.assertIn(b'static int8_t input[BERYL_INPUT_COUNT];', small)
        self.assertNotIn(b'calloc(', small)
        with tempfile.TemporaryDirectory() as tmp:
            c, exe = Path(tmp) / 'k.c', Path(tmp) / 'k.exe'
            c.write_bytes(large)
            try:
                built = subprocess.run(['clang', '-O1', '-std=c11', '-Wall', '-Werror', str(c), '-o', str(exe)],
                                       capture_output=True, text=True)
            except OSError as error:
                self.skipTest(f'no C compiler: {error}')
            self.assertEqual(built.returncode, 0, built.stderr)


class SteppedCounterTests(unittest.TestCase):
    """A counter stepped by k past a bound within k of 2^31 would overflow int32_t."""

    def test_counters_widen_only_near_the_limit(self):
        long_copy = compile_scale_native(COPY.format(w=LIMIT).encode()).artifact.c_source
        self.assertIn(b'for (int64_t start = first; start < last; start += 64)', long_copy)
        short_copy = compile_scale_native(COPY.format(w=1 << 22).encode()).artifact.c_source
        self.assertIn(b'for (int32_t start = first; start < last; start += 64)', short_copy)
        self.assertRegex(compile_scale_native(LONG_SUM.format(n=LIMIT).encode()).artifact.c_source,
                         rb'for \(int64_t ax_s\d+_k = 0;')
        self.assertRegex(compile_scale_native(LONG_SUM.format(n=1 << 24).encode()).artifact.c_source,
                         rb'for \(int32_t ax_s\d+_k = 0;')

    def test_a_sum_of_the_limit_terms_runs_natively(self):
        # One input cell, 2^31 - 1 terms in exact int32_t blocks: no memory, every block.
        text = LONG_SUM.format(n=LIMIT)
        kernel = kernel_of(text)
        compiled = compile_scale_native(text.encode())
        harness = Path(__file__).parent / 'fixtures' / 'scale_harness.c'
        with tempfile.TemporaryDirectory() as tmp:
            c, exe = Path(tmp) / 'k.c', Path(tmp) / 'k.exe'
            c.write_bytes(compiled.artifact.c_source.replace(b'int main(void)', b'int beryl_unused_main(void)'))
            try:
                built = subprocess.run(['clang', '-O2', '-std=c11', '-Wall', '-Werror',
                                        f'-DBERYL_IN={C_TYPES[kernel.input_type]}',
                                        f'-DBERYL_OUT={C_TYPES[kernel.output_type]}',
                                        str(c), str(harness), '-o', str(exe)], capture_output=True, text=True)
            except OSError as error:
                self.skipTest(f'no C compiler: {error}')
            self.assertEqual(built.returncode, 0, built.stderr)
            for value, threads in ((1, '1'), (200, '1'), (200, '4'), (0, '1'), (201, '1')):
                try:
                    ran = subprocess.run([str(exe), '1', '1'], input=str(value), capture_output=True, text=True,
                                         check=True, timeout=120,
                                         env={'BERYL_THREADS': threads, 'SYSTEMROOT': 'C:\\Windows'})
                except OSError as error:  # Windows Application Control; never bypassed
                    self.skipTest(f'executable launch refused: {error}')
                with self.subTest(value=value, threads=threads):
                    self.assertEqual(ran.stdout.split(), ['1', '-9'] if value == 201 else ['0', str(value * LIMIT)])


class SampledReferenceTests(unittest.TestCase):
    PROGRAMS = (BOX.format(h=5, w=7), MATMUL.format(n=6), ROWSUM, TRANSPOSE, SUM.format(n=300),
                BLUR.format(h=4, w=6, lo=0, hi=255, out=BLUR_OUT), DENSE.format(w=5, n=9),
                LINEAR.format(t='i8', w=4, n=11))

    def test_agrees_with_the_full_reference_on_every_cell(self):
        for text in self.PROGRAMS:
            kernel = kernel_of(text)
            _, value_at = generator(kernel)
            data = [value_at(i) for i in range(kernel.input_count)]
            full = evaluate_source(kernel.source_module, data, [0] * kernel.output_count).output
            cells = list(range(kernel.output_count))
            with self.subTest(program=text.split(';')[0]):
                self.assertEqual(evaluate_cells(kernel.source_module, value_at, cells), full)
                self.assertEqual(evaluate_cells(kernel.source_module, value_at, cells[::-3]), full[::-3])

    def test_refuses_a_value_outside_its_declared_range(self):
        kernel = kernel_of(MATMUL.format(n=4))
        with self.assertRaises(DiagnosticError):
            evaluate_cells(kernel.source_module, lambda i: 1024 if i == 21 else 1, [5])

    def test_refuses_a_cell_outside_the_output(self):
        kernel = kernel_of(MATMUL.format(n=4))
        with self.assertRaises(DiagnosticError):
            evaluate_cells(kernel.source_module, lambda i: 1, [16])


class FullSizeDenseLayerTests(unittest.TestCase):
    """A 4096 -> 11008 int8 layer: 45 million weights, past the old 2^24 limit."""

    def test_native_run_matches_the_sampled_reference(self):
        text = LINEAR.format(t='i8', w=11008, n=4096)
        kernel = kernel_of(text)
        compiled = compile_scale_native(text.encode())
        self.assertIsNotNone(compiled.artifact, compiled.reason)
        segments, value_at = generator(kernel)
        n_in, n_out = kernel.input_count, kernel.output_count
        self.assertGreater(n_in, 1 << 24)
        samples = [0, 1, 4095, 4096, 5503, 8191, n_out - 2, n_out - 1]
        expected = evaluate_cells(kernel.source_module, value_at, samples)
        harness = Path(__file__).parent / 'fixtures' / 'scale_sampled_harness.c'
        with tempfile.TemporaryDirectory() as tmp:
            c, exe = Path(tmp) / 'k.c', Path(tmp) / 'k.exe'
            c.write_bytes(compiled.artifact.c_source.replace(b'int main(void)', b'int beryl_unused_main(void)'))
            try:
                built = subprocess.run(['clang', '-O2', '-std=c11', '-Wall', '-Werror',
                                        f'-DBERYL_IN={C_TYPES[kernel.input_type]}',
                                        f'-DBERYL_OUT={C_TYPES[kernel.output_type]}',
                                        str(c), str(harness), '-o', str(exe)], capture_output=True, text=True)
            except OSError as error:
                self.skipTest(f'no C compiler: {error}')
            self.assertEqual(built.returncode, 0, built.stderr)
            spec = [str(len(segments))] + [str(v) for segment in segments for v in segment]
            # The last weight is -128: it fits i8 but lies outside -127..=127.
            for bad, want in ((-1, [0, *expected]), (n_in - 1, [n_in] + [7] * len(samples))):
                for threads in ('1', '4'):
                    try:
                        ran = subprocess.run([str(exe), str(n_in), str(n_out), str(bad), '-128', *spec,
                                              *map(str, samples)], capture_output=True, text=True, check=True,
                                             env={'BERYL_THREADS': threads, 'SYSTEMROOT': 'C:\\Windows'})
                    except OSError as error:  # Windows Application Control; never bypassed
                        self.skipTest(f'executable launch refused: {error}')
                    with self.subTest(bad=bad, threads=threads):
                        self.assertEqual(list(map(int, ran.stdout.split())), want)


if __name__ == '__main__':
    unittest.main()
