"""ABI v2: one pointer per input, mixed storage, up to four inputs, an int64_t status."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from axiom.model import C_TYPES, DiagnosticError, TYPE_BOUNDS
from axiom.reference import ExecutionStatus, evaluate_cells, evaluate_source
from axiom.scale_c import compile_scale_native
from axiom.scale_runtime import execute_loop_plan
from tests.test_scale_family import BOX, MATMUL, ROWSUM, SUM, TRANSPOSE
from tests.test_scale_large import COPY, generator, kernel_of
from tests.test_scale_storage import DENSE
from tests.test_scale_tiles import LINEAR

# A quantized dense layer: u8 activations, i8 weights stored [out, in], i32 bias.
QLINEAR = '''module qlinear;
shape H = 1;
shape W = {w};
input a: u8[1,{n}] in 0..=255;
input k: i8[W,{n}] in -127..=127;
input b: i32[1,W] in -100000..=100000;
let t[r in 0..H,c in 0..W] = sum(j in 0..{n}: a[0,j]*k[c,j]) + b[0,c];
output y[r in 0..H,c in 0..W] = t[r,c];
'''
# Four inputs: the layer above, then a per-channel i16 scale.
REQUANT = '''module requant;
shape H = 1;
shape W = {w};
input a: u8[1,{n}] in 0..=255;
input k: i8[W,{n}] in -127..=127;
input b: i32[1,W] in -100000..=100000;
input s: i16[1,W] in 1..=32767;
let t: i64[r in 0..H,c in 0..W] = (sum(j in 0..{n}: a[0,j]*k[c,j]) + b[0,c]) * s[0,c];
output y: i64[r in 0..H,c in 0..W] = t[r,c];
'''
# One cell, a u8 by i8 dot product: split across threads, checked as it sums.
QDOT = '''module qdot;
shape H = 1;
shape W = 1;
input a: u8[1,{n}] in 0..=255;
input k: i8[1,{n}] in -127..=127;
let t[r in 0..H,c in 0..W] = sum(j in 0..{n}: a[0,j]*k[0,j]);
output d[r in 0..H,c in 0..W] = t[r,c];
'''
# Two i8 inputs of 2^30 cells: more than 2^31 - 1 together.
PAIR = '''module pair;
shape H = 1;
shape W = 1073741824;
input x: i8[1,W] in 0..=1;
input y: i8[1,W] in 0..=1;
let t[r in 0..H,c in 0..W] = x[r,c]+y[r,c];
output o[r in 0..H,c in 0..W] = t[r,c];
'''
# y[0, j + -1] reads y, though its constant term (299) is a cell of x. y's
# range allows one term per exact int32_t block; x's would allow 2^31 - 1.
SHIFTED = '''module shifted;
shape H = 1;
shape W = 1;
input x: i32[1,300] in 0..=1;
input y: i32[1,300] in 0..=2147483647;
let t: i64[r in 0..H,c in 0..W] = sum(j in 1..301: y[0,j+-1]);
output o: i64[r in 0..H,c in 0..W] = t[r,c];
'''
HARNESS = Path(__file__).parent / 'fixtures' / 'scale_v2_harness.c'


class AdmissionTests(unittest.TestCase):
    def test_each_input_keeps_its_own_storage_type(self):
        kernel = kernel_of(QLINEAR.format(w=5, n=9))
        self.assertEqual((kernel.profile, kernel.input_types), ('scale-v1', ('u8', 'i8', 'i32')))

    def test_up_to_four_inputs(self):
        self.assertEqual(len(kernel_of(REQUANT.format(w=3, n=4)).input_types), 4)
        five = REQUANT.format(w=3, n=4).replace('input s:', 'input z: i32[1,1] in 0..=1;\ninput s:')
        with self.assertRaises(DiagnosticError) as raised:
            kernel_of(five)
        self.assertEqual(raised.exception.code, 'UNSUPPORTED_PROFILE')

    def test_the_cell_limit_is_per_tensor(self):
        self.assertEqual(kernel_of(PAIR).input_count, 2 ** 31)

    def test_mixed_storage_still_needs_scale_v1(self):
        # A program no family admits is refused with the scale-v1 hint.
        text = QLINEAR.format(w=2, n=3).replace('sum(j in 0..3: a[0,j]*k[c,j])', 'a[0,c+c]')
        with self.assertRaises(DiagnosticError):
            kernel_of(text)


class ReferenceTests(unittest.TestCase):
    def data(self, kernel):
        _, value_at = generator(kernel)
        return [value_at(i) for i in range(kernel.input_count)]

    def test_each_input_is_checked_against_its_own_storage_type(self):
        kernel = kernel_of(QLINEAR.format(w=2, n=3))  # a: 0..3, k: 3..9, b: 9..11
        initial = [5, 6]
        for index, value, code in ((0, 256, 'BOUNDARY_U8'), (0, -1, 'BOUNDARY_U8'),
                                   (3, 128, 'BOUNDARY_I8'), (10, 2 ** 31, 'BOUNDARY_I32')):
            data = self.data(kernel)
            data[index] = value
            with self.subTest(index=index, value=value), self.assertRaises(DiagnosticError) as raised:
                evaluate_source(kernel.source_module, data, initial)
            self.assertEqual(raised.exception.code, code)
        # 128 fits i32, so a u8-range check of the third input would wrongly refuse it.
        data = self.data(kernel)
        data[9] = 100000
        self.assertEqual(evaluate_source(kernel.source_module, data, initial).status, ExecutionStatus.SUCCESS)
        data[8] = -128  # fits i8, outside -127..=127
        result = evaluate_source(kernel.source_module, data, initial)
        self.assertEqual((result.status, result.first_bad_index, result.output),
                         (ExecutionStatus.INPUT_PRECONDITION_FAILED, 8, (5, 6)))

    def test_the_loop_plan_runtime_agrees(self):
        for text in (QLINEAR.format(w=3, n=5), REQUANT.format(w=3, n=5), QDOT.format(n=300)):
            kernel = kernel_of(text)
            plan = compile_scale_native(text.encode()).plan
            initial = [7] * kernel.output_count
            segments, _ = generator(kernel)
            for bad in (None, segments[0][0], kernel.input_count - 1):  # the second input's first cell, the last
                data = self.data(kernel)
                if bad is not None:
                    k = next(k for k, (end, _, _) in enumerate(segments) if bad < end)
                    data[bad] = bad_value(kernel.input_types[k], *segments[k][1:])
                with self.subTest(program=text.split(';')[0], bad=bad):
                    self.assertEqual(execute_loop_plan(text.encode(), plan, data, initial),
                                     evaluate_source(kernel.source_module, data, initial))

    def test_the_sampled_reference_agrees(self):
        for text in (QLINEAR.format(w=4, n=6), REQUANT.format(w=4, n=6), QDOT.format(n=50)):
            kernel = kernel_of(text)
            _, value_at = generator(kernel)
            full = evaluate_source(kernel.source_module, self.data(kernel), [0] * kernel.output_count).output
            with self.subTest(program=text.split(';')[0]):
                self.assertEqual(evaluate_cells(kernel.source_module, value_at, range(kernel.output_count)), full)


class EmissionTests(unittest.TestCase):
    def test_single_type_programs_keep_the_joined_interface(self):
        artifact = compile_scale_native(MATMUL.format(n=20).encode()).artifact
        self.assertNotIn(b'beryl_kernel_v2', artifact.c_source)
        self.assertNotIn('abi2', artifact.codegen_version)

    def test_abi2_on_request_keeps_a_joined_wrapper(self):
        artifact = compile_scale_native(MATMUL.format(n=20).encode(), abi=2).artifact
        self.assertIn('abi2', artifact.codegen_version)
        self.assertIn(b'int64_t beryl_kernel_v2(const int32_t *restrict in0, const int32_t *restrict in1, '
                      b'int32_t *restrict output) {', artifact.c_source)
        self.assertIn(b'int32_t beryl_kernel(const int32_t *restrict input, int32_t *restrict output) {\n'
                      b'    return (int32_t)beryl_kernel_v2(input, input + 400, output);\n}', artifact.c_source)

    def test_mixed_storage_needs_abi2(self):
        source = QLINEAR.format(w=5, n=9).encode()
        artifact = compile_scale_native(source).artifact
        self.assertIn(b'int64_t beryl_kernel_v2(const uint8_t *restrict in0, const int8_t *restrict in1, '
                      b'const int32_t *restrict in2, int32_t *restrict output) {', artifact.c_source)
        self.assertNotIn(b'int32_t beryl_kernel(', artifact.c_source)
        with self.assertRaises(ValueError):
            compile_scale_native(source, abi=1)

    def test_a_load_is_bounded_by_the_input_it_reads(self):
        code = compile_scale_native(SHIFTED.encode()).artifact.c_source
        self.assertIn(b'ax_s0_k += 1) {', code)
        self.assertIn(b'in1[(int64_t)-1 + (int64_t)1 * s0]', compile_scale_native(SHIFTED.encode(), abi=2).artifact.c_source)

    def test_inputs_past_int32_in_total_report_an_int64_status(self):
        artifact = compile_scale_native(PAIR.encode()).artifact
        self.assertIn('abi2', artifact.codegen_version)
        self.assertNotIn(b'int32_t beryl_kernel(', artifact.c_source)
        # The second input's first cell is 2^30 in the concatenation.
        self.assertIn(b'return (int64_t)i + 1073741825;', artifact.c_source)
        with tempfile.TemporaryDirectory() as tmp:
            c, exe = Path(tmp) / 'k.c', Path(tmp) / 'k.exe'
            c.write_bytes(artifact.c_source)
            try:
                built = subprocess.run(['clang', '-O1', '-std=c11', '-Wall', '-Werror', str(c), '-o', str(exe)],
                                       capture_output=True, text=True)
            except OSError as error:
                self.skipTest(f'no C compiler: {error}')
            self.assertEqual(built.returncode, 0, built.stderr)


def bad_value(storage, lo, hi):
    """A value its storage type holds but its range refuses, or None."""
    low, high = TYPE_BOUNDS[storage]
    return hi + 1 if hi < high else lo - 1 if lo > low else None


class _Native(unittest.TestCase):
    """Runs generated ABI v2 kernels through scale_v2_harness.c against the sampled reference."""
    PROGRAMS = ()

    def test_programs_match_the_sampled_reference(self):
        for text, abi in self.PROGRAMS:
            with self.subTest(program=text.split(';')[0], size=text.split('\n')[2]), \
                    tempfile.TemporaryDirectory() as tmp:
                self.run_program(text, abi, tmp)

    def run_program(self, text, abi, tmp):
        kernel = kernel_of(text)
        compiled = compile_scale_native(text.encode(), **({'abi': abi} if abi else {}))
        self.assertIsNotNone(compiled.artifact, compiled.reason)
        n_in, n_out = kernel.input_count, kernel.output_count
        types = [C_TYPES[t] for t in kernel.input_types]
        c, exe = Path(tmp) / 'k.c', Path(tmp) / 'k.exe'
        c.write_bytes(compiled.artifact.c_source.replace(b'int main(void)', b'int beryl_unused_main(void)'))
        flags = [f'-DBERYL_NIN={len(types)}', f'-DBERYL_OUT={C_TYPES[kernel.output_type]}',
                 *(f'-DBERYL_IN{k}={t}' for k, t in enumerate(types))]
        try:
            built = subprocess.run(['clang', '-O2', '-std=c11', '-Wall', '-Werror', *flags, str(c), str(HARNESS),
                                    '-o', str(exe)], capture_output=True, text=True)
        except OSError as error:
            self.skipTest(f'no C compiler: {error}')
        self.assertEqual(built.returncode, 0, built.stderr)
        segments, value_at = generator(kernel)
        samples = sorted(set(range(min(n_out, 40))) | {n_out // 2, n_out - 2, n_out - 1} - {-1})
        expected = list(evaluate_cells(kernel.source_module, value_at, samples))
        spec, start = [], 0
        for end, lo, hi in segments:
            spec += [end - start, lo, hi]
            start = end
        cases = [(-1, 0, [0, *expected])]
        start = 0
        for (end, lo, hi), storage in zip(segments, kernel.input_types):
            value = bad_value(storage, lo, hi)
            if value is not None:
                cases += [(index, value, [index + 1] + [7] * len(samples)) for index in (start, end - 1)]
            start = end
        for bad, value, want in cases:
            for threads in ('1', '4'):
                try:
                    ran = subprocess.run([str(exe), str(n_out), str(bad), str(value), *map(str, spec),
                                          *map(str, samples)], capture_output=True, text=True, check=True,
                                         timeout=120, env={'BERYL_THREADS': threads, 'SYSTEMROOT': 'C:\\Windows'})
                except OSError as error:  # Windows Application Control; never bypassed
                    self.skipTest(f'executable launch refused: {error}')
                with self.subTest(program=text.split(';')[0], bad=bad, threads=threads):
                    self.assertEqual(list(map(int, ran.stdout.split())), want)


class NativeTests(_Native):
    """Every emission path."""
    PROGRAMS = (
        (QLINEAR.format(w=37, n=300), None),        # mixed: per-cell sums
        (QLINEAR.format(w=2048, n=64), None),       # mixed: parallel, parallel input check
        (REQUANT.format(w=33, n=257), None),        # four inputs, i64
        (QDOT.format(n=65536), None),               # one cell, split and checked as it sums
        (BOX.format(h=60, w=50), 2),                # carry
        (BOX.format(h=400, w=300), 2),              # carry, parallel
        (MATMUL.format(n=64), 2),                   # row accumulation
        (TRANSPOSE, 2),                             # tiles
        (ROWSUM, 2),
        (SUM.format(n=300000), 2),                  # one cell, fused check
        (COPY.format(w=1 << 21), 2),                # streaming stores
        (DENSE.format(w=64, n=512), 2),             # i8, i64 equations, i8 output
        (LINEAR.format(t='i8', w=300, n=700), 2),
        (SHIFTED, 2),
    )

    def test_the_standalone_driver_reads_each_input_as_its_own_type(self):
        text = QLINEAR.format(w=3, n=4)
        kernel = kernel_of(text)
        artifact = compile_scale_native(text.encode()).artifact
        data = [255, 0, 7, 1, *range(-6, 6), 100000, -100000, 5]  # a, k (3 x 4), b
        want = evaluate_source(kernel.source_module, data, [0] * 3).output
        with tempfile.TemporaryDirectory() as tmp:
            c, exe = Path(tmp) / 'k.c', Path(tmp) / 'k.exe'
            c.write_bytes(artifact.c_source)
            try:
                built = subprocess.run(['clang', '-O2', '-std=c11', '-Wall', '-Werror', str(c), '-o', str(exe)],
                                       capture_output=True, text=True)
            except OSError as error:
                self.skipTest(f'no C compiler: {error}')
            self.assertEqual(built.returncode, 0, built.stderr)
            for tokens, code, stdout in ((data, 0, '[' + ','.join(map(str, want)) + ']'),
                                         ([256, *data[1:]], 65, ''),      # does not fit u8
                                         ([*data[:4], 128, *data[5:]], 65, ''),  # does not fit i8
                                         ([*data[:4], -128, *data[5:]], 66, '')):  # outside -127..=127
                try:
                    ran = subprocess.run([str(exe)], input=' '.join(map(str, [1, 3, *tokens])),
                                         capture_output=True, text=True, timeout=60)
                except OSError as error:  # Windows Application Control; never bypassed
                    self.skipTest(f'executable launch refused: {error}')
                with self.subTest(tokens=tokens[:6]):
                    self.assertEqual((ran.returncode, ran.stdout.strip()), (code, stdout))



class FullSizeTests(_Native):
    """A 4096 -> 11008 layer of u8 activations, i8 weights and an i32 bias: 45 million weights."""
    PROGRAMS = ((QLINEAR.format(w=11008, n=4096), None),)


if __name__ == '__main__':
    unittest.main()
