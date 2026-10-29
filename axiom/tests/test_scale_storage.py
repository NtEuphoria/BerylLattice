"""u8, i8 and i16 storage in scale-v1: narrow inputs and outputs, arithmetic in i32 or i64."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from axiom.frontend import admit_source, parse_source
from axiom.model import DiagnosticError
from axiom.reference import evaluate_source
from axiom.scale_c import compile_scale_native
from axiom.scale_checker import check_loop_plan
from axiom.scale_plan import make_scale_plan
from axiom.scale_runtime import execute_loop_plan
from tests.test_scale_minmax import assert_native_matches
from tests.test_scale_ranges import data_for

# A [1,2,1] x [1,2,1] blur of 8-bit pixels, divided by 16 with rounding, stored as u8.
BLUR = '''module blur;
shape H = {h};
shape W = {w};
input x: u8[H+2,W+2] in {lo}..={hi};
let p[r in 0..H+2,c in 0..W] = (x[r,c]+2*x[r,c+1])+x[r,c+2];
output o: u8[r in 0..H,c in 0..W] = {out};
'''
BLUR_OUT = 'shr_round(p[r,c] + 2*p[r+1,c] + p[r+2,c], 4)'
# A quantized dense layer: int8 activations and weights, one output channel per
# column, requantized with a fixed-point multiplier and saturated to int8.
DENSE = '''module dense;
shape H = 1;
shape W = {w};
input a: i8[1,{n}] in -128..=127;
input k: i8[W,{n}] in -127..=127;
let t: i64[r in 0..H,c in 0..W] = shr_round(sum(j in 0..{n}: a[0,j]*k[c,j]) * 1518500250, 40);
output y: i8[r in 0..H,c in 0..W] = clamp(t[r,c] + 3, -128, 127);
'''
# A gain on 16-bit audio samples, in Q15.
GAIN = '''module gain;
shape H = 1;
shape W = {w};
input s: i16[1,W] in -32768..=32767;
let t[r in 0..H,c in 0..W] = s[r,c];
output y: i16[r in 0..H,c in 0..W] = {out};
'''


def _admit(text):
    return admit_source(parse_source(text.encode()))


def _fails(test, text, code):
    with test.assertRaises(DiagnosticError) as caught:
        _admit(text)
    test.assertEqual(caught.exception.code, code, caught.exception.message)
    return caught.exception.message


def _check(text):
    source = text.encode()
    kernel = _admit(text)
    return check_loop_plan(source, make_scale_plan(kernel, 'direct-v1'))


class StorageAdmissionTests(unittest.TestCase):
    def test_narrow_inputs_and_outputs_are_scale_v1(self):
        for text, types in ((BLUR.format(h=40, w=30, lo=0, hi=255, out=BLUR_OUT), ('u8', 'u8')),
                            (DENSE.format(w=8, n=64), ('i8', 'i8')),
                            (GAIN.format(w=100, out='shr_round(t[r,c]*23170, 15)'), ('i16', 'i16'))):
            kernel = _admit(text)
            with self.subTest(types=types):
                self.assertEqual(kernel.profile, 'scale-v1')
                self.assertEqual((kernel.input_type, kernel.output_type), types)

    def test_small_programs_with_narrow_storage_are_scale_v1(self):
        # Within 256 input cells the small families would apply, but they store i32.
        kernel = _admit(BLUR.format(h=3, w=3, lo=0, hi=255, out=BLUR_OUT))
        self.assertEqual(kernel.profile, 'scale-v1')

    def test_a_range_must_lie_within_its_storage_type(self):
        message = _fails(self, BLUR.format(h=4, w=4, lo=0, hi=256, out=BLUR_OUT), 'INVALID_RANGE')
        self.assertIn('0..=255', message)
        _fails(self, BLUR.format(h=4, w=4, lo=-1, hi=255, out=BLUR_OUT), 'INVALID_RANGE')
        _fails(self, GAIN.format(w=4, out='t[r,c]').replace('-32768..=32767', '-32769..=0'), 'INVALID_RANGE')

    def test_inputs_may_mix_storage_types(self):
        # Each input keeps its own type; the kernel takes one pointer per input (ABI 2).
        mixed = DENSE.format(w=4, n=8).replace('input k: i8', 'input k: u8').replace('-127..=127', '0..=255')
        self.assertEqual(_admit(mixed).input_types, ('i8', 'u8'))

    def test_a_let_equation_is_not_narrow(self):
        narrow = BLUR.format(h=4, w=4, lo=0, hi=255, out=BLUR_OUT).replace('let p[', 'let p: u8[')
        self.assertIn('storage', _fails(self, narrow, 'UNSUPPORTED_TYPE'))

    def test_storage_types_are_part_of_the_identity(self):
        u8 = _admit(BLUR.format(h=40, w=30, lo=0, hi=255, out=BLUR_OUT))
        i32_in = _admit(BLUR.format(h=40, w=30, lo=0, hi=255, out=BLUR_OUT).replace('x: u8', 'x: i32'))
        i32_out = _admit(BLUR.format(h=40, w=30, lo=0, hi=255, out=BLUR_OUT).replace('o: u8', 'o'))
        self.assertEqual(len({u8.semantic_digest, i32_in.semantic_digest, i32_out.semantic_digest}), 3)
        self.assertEqual((i32_in.input_type, i32_out.output_type), ('i32', 'i32'))


class StorageMeaningTests(unittest.TestCase):
    def test_reference_blur_rounds_and_fits(self):
        text = BLUR.format(h=1, w=1, lo=0, hi=255, out=BLUR_OUT)
        result = evaluate_source(parse_source(text.encode()), [255] * 9, [0])
        self.assertEqual(result.output, (255,))
        result = evaluate_source(parse_source(text.encode()), [0, 0, 0, 0, 1, 0, 0, 0, 0], [0])
        self.assertEqual(result.output, (0,))  # 4/16 rounds to 0
        result = evaluate_source(parse_source(text.encode()), [0, 0, 0, 0, 2, 0, 0, 0, 0], [0])
        self.assertEqual(result.output, (1,))  # 8/16 rounds half up

    def test_reference_refuses_a_value_that_does_not_fit_storage(self):
        text = GAIN.format(w=1, out='t[r,c]*2')
        with self.assertRaises(DiagnosticError) as caught:
            evaluate_source(parse_source(text.encode()), [20000], [0])
        self.assertEqual(caught.exception.code, 'EVALUATION_I16')
        self.assertEqual(evaluate_source(parse_source(text.encode()), [-16384], [0]).output, (-32768,))

    def test_boundaries_follow_the_storage_types(self):
        module = parse_source(BLUR.format(h=1, w=1, lo=16, hi=235, out=BLUR_OUT).encode())
        for data, initial, code in (([256] + [16] * 8, [0], 'BOUNDARY_U8'), ([16] * 9, [-1], 'BOUNDARY_U8')):
            with self.subTest(code=code), self.assertRaises(DiagnosticError) as caught:
                evaluate_source(module, data, initial)
            self.assertEqual(caught.exception.code, code)
        # Inside u8 but outside the declared range is the usual precondition failure.
        result = evaluate_source(module, [16] * 4 + [240] + [16] * 4, [7])
        self.assertEqual((result.first_bad_index, result.output), (4, (7,)))


class StorageProofTests(unittest.TestCase):
    def test_outputs_are_proved_to_fit_their_storage(self):
        for text in (BLUR.format(h=200, w=180, lo=0, hi=255, out=BLUR_OUT), DENSE.format(w=16, n=4096),
                     GAIN.format(w=1000, out='shr_round(t[r,c]*23170, 15)'),
                     GAIN.format(w=1000, out='clamp(t[r,c]*2, -32768, 32767)')):
            check = _check(text)
            with self.subTest(text=text.splitlines()[0]):
                self.assertTrue(check.valid, f'{check.reason}: {check.detail}')

    def test_an_output_that_may_not_fit_is_refused(self):
        for text, storage in ((BLUR.format(h=20, w=20, lo=0, hi=255, out='shr(p[r,c] + 2*p[r+1,c] + p[r+2,c], 3)'), 'u8'),
                              (GAIN.format(w=10, out='t[r,c]*2'), 'i16'),
                              (DENSE.format(w=4, n=64).replace('clamp(t[r,c] + 3, -128, 127)', 't[r,c] + 3'), 'i8')):
            check = _check(text)
            with self.subTest(storage=storage):
                self.assertEqual(check.reason, 'ARITHMETIC_OVERFLOW')
                self.assertIn(storage, check.detail)

    def test_the_interior_arithmetic_is_not_narrow(self):
        # 4080 does not fit u8, but only the stored result must.
        self.assertTrue(_check(BLUR.format(h=20, w=20, lo=0, hi=255, out=BLUR_OUT)).valid)

    def test_plans_match_the_reference(self):
        for number, text in enumerate((BLUR.format(h=9, w=7, lo=16, hi=235, out=BLUR_OUT), DENSE.format(w=5, n=300),
                                       GAIN.format(w=40, out='clamp(t[r,c]*2, -32768, 32767)'))):
            source = text.encode()
            kernel = _admit(text)
            for extreme in (None, 'low', 'high'):
                data = data_for(kernel, number, extreme)
                ref = evaluate_source(kernel.source_module, data, [0] * kernel.output_count)
                for plan_id in ('direct-v1', 'carry-v1'):
                    try:
                        plan = make_scale_plan(kernel, plan_id)
                    except ValueError:  # carry-v1 needs window reads of the producer
                        continue
                    if not check_loop_plan(source, plan).valid:
                        continue
                    ran = execute_loop_plan(source, plan, data, [0] * kernel.output_count)
                    with self.subTest(number=number, extreme=extreme, plan=plan_id):
                        self.assertEqual(ran.output, ref.output)


class StorageEmissionTests(unittest.TestCase):
    def test_the_kernel_takes_narrow_arrays(self):
        for text, signature in (
                (BLUR.format(h=40, w=30, lo=0, hi=255, out=BLUR_OUT),
                 b'int32_t beryl_kernel(const uint8_t *restrict input, uint8_t *restrict output)'),
                (DENSE.format(w=8, n=64), b'int32_t beryl_kernel(const int8_t *restrict input, int8_t *restrict output)'),
                (GAIN.format(w=100, out='shr_round(t[r,c]*23170, 15)'),
                 b'int32_t beryl_kernel(const int16_t *restrict input, int16_t *restrict output)')):
            compiled = compile_scale_native(text.encode())
            with self.subTest(signature=signature):
                self.assertIsNotNone(compiled.artifact, compiled.reason)
                self.assertIn(signature, compiled.artifact.c_source)
                self.assertNotIn(b'int32_t *restrict input', compiled.artifact.c_source)

    def test_a_full_range_input_needs_no_check(self):
        c = compile_scale_native(BLUR.format(h=40, w=30, lo=0, hi=255, out=BLUR_OUT).encode()).artifact.c_source
        self.assertNotIn(b'input[i] < 0', c)
        self.assertNotIn(b'input[i] > 255', c)
        c = compile_scale_native(BLUR.format(h=40, w=30, lo=16, hi=235, out=BLUR_OUT).encode()).artifact.c_source
        self.assertIn(b'input[i] < 16', c)
        self.assertIn(b'input[i] > 235', c)


class StorageNativeTests(unittest.TestCase):
    def test_native_c_matches_the_reference(self):
        assert_native_matches(self, [
            BLUR.format(h=200, w=180, lo=0, hi=255, out=BLUR_OUT), BLUR.format(h=9, w=7, lo=16, hi=235, out=BLUR_OUT),
            DENSE.format(w=64, n=2048), DENSE.format(w=5, n=300),
            GAIN.format(w=300000, out='clamp(t[r,c]*2, -32768, 32767)'),
            GAIN.format(w=50, out='shr_round(t[r,c]*23170, 15)')])

    def test_the_driver_refuses_tokens_outside_the_storage_type(self):
        compiled = compile_scale_native(BLUR.format(h=1, w=1, lo=16, hi=235, out=BLUR_OUT).encode())
        with tempfile.TemporaryDirectory() as tmp:
            c, exe = Path(tmp) / 'k.c', Path(tmp) / 'k.exe'
            c.write_bytes(compiled.artifact.c_source)
            try:
                built = subprocess.run(['clang', '-O2', '-std=c11', '-Wall', '-Werror', str(c), '-o', str(exe)],
                                       capture_output=True, text=True)
            except OSError as error:
                self.skipTest(f'no C compiler: {error}')
            self.assertEqual(built.returncode, 0, built.stderr)
            # 300 would wrap to 44, inside the declared range; it must be refused, not narrowed.
            for values, status in (([100] * 9, 0), ([300] + [100] * 8, 65), ([-1] + [100] * 8, 65),
                                   ([240] + [100] * 8, 66)):
                try:
                    ran = subprocess.run([str(exe)], input='1 1 ' + ' '.join(map(str, values)),
                                         capture_output=True, text=True, env={'SYSTEMROOT': 'C:\\Windows'})
                except OSError as error:  # Windows Application Control; never bypassed
                    self.skipTest(f'executable launch refused: {error}')
                with self.subTest(values=values[0]):
                    self.assertEqual(ran.returncode, status, ran.stderr)
            self.assertEqual(ran.stdout, '')


if __name__ == '__main__':
    unittest.main()
