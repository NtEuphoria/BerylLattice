"""Per-input declared ranges in scale-v1: any i32 interval, signed included, per input."""
from pathlib import Path
import random
import subprocess
import tempfile
import unittest

from axiom.frontend import admit_source, parse_source
from axiom.model import DiagnosticError
from axiom.reference import evaluate_source
from axiom.scale_c import compile_scale_native
from axiom.scale_plan import make_scale_plan
from axiom.scale_runtime import execute_loop_plan
from tests.helpers import stencil_source
from tests.test_scale_family import BOX, SUM

# A quantized dot product: unsigned 8-bit activations times signed 8-bit weights,
# accumulated exactly in 32 bits (40,000 * 255 * 128 < 2^31).
INT8_DOT = '''module int8dot;
shape H = 1;
shape W = 1;
input a: i32[1,{n}] in 0..=255;
input w: i32[1,{n}] in -128..=127;
let t[r in 0..H,c in 0..W] = sum(k in 0..{n}: a[0,k]*w[0,k]);
output d[r in 0..H,c in 0..W] = t[r,c];
'''
SIGNED_BOX = BOX.replace('in 0..=1023', 'in -1000..=1000')
SQUARE = SUM.replace('in 0..=1023', 'in -46340..=46340').replace('x[0,k])', 'x[0,k]*x[0,k])')


def data_for(kernel, seed, extreme=None):
    """Values inside each input's range: random, or every value at its low or high end."""
    rng, data = random.Random(seed), []
    for (rows, cols), (low, high) in zip(kernel.all_input_shapes, kernel.input_intervals):
        pick = {'low': lambda: low, 'high': lambda: high}.get(extreme, lambda: rng.randint(low, high))
        data += [pick() for _ in range(rows * cols)]
    return data


class RangeAdmissionTests(unittest.TestCase):
    def test_any_i32_range_per_input_is_admitted(self):
        kernel = admit_source(parse_source(INT8_DOT.format(n=4000).encode()))
        self.assertEqual((kernel.profile, kernel.input_intervals), ('scale-v1', ((0, 255), (-128, 127))))
        small = admit_source(parse_source(stencil_source(5, 7).replace(b'0..=1023', b'0..=1022')))
        self.assertEqual((small.profile, small.input_intervals), ('scale-v1', ((0, 1022),)))

    def test_ranges_outside_i32_are_refused(self):
        for bad in (b'in -2147483649..=0', b'in 0..=2147483648'):
            with self.subTest(range=bad), self.assertRaises(DiagnosticError) as caught:
                admit_source(parse_source(SUM.format(n=5000).replace('in 0..=1023', bad.decode()).encode()))
            self.assertEqual(caught.exception.code, 'INVALID_RANGE')

    def test_ranges_are_part_of_the_identity(self):
        digests = {admit_source(parse_source(SUM.format(n=5000).replace('0..=1023', r).encode())).semantic_digest
                   for r in ('0..=1023', '0..=1022', '-5..=5')}
        self.assertEqual(len(digests), 3)


class RangeProofTests(unittest.TestCase):
    def test_overflow_proof_uses_each_declared_range(self):
        self.assertEqual(compile_scale_native(INT8_DOT.format(n=40000).encode()).reason, 'VALID')
        self.assertEqual(compile_scale_native(INT8_DOT.format(n=70000).encode()).reason, 'ARITHMETIC_OVERFLOW')
        # Signed squares: 46340^2 fits i32, and the product's interval is taken over both signs.
        self.assertEqual(compile_scale_native(SQUARE.format(n=1).encode()).reason, 'VALID')
        widened = SQUARE.replace('46340', '46341')
        self.assertEqual(compile_scale_native(widened.format(n=1).encode()).reason, 'ARITHMETIC_OVERFLOW')

    def test_each_input_is_checked_against_its_own_range(self):
        source = INT8_DOT.format(n=300).encode()
        kernel = admit_source(parse_source(source))
        plan = make_scale_plan(kernel)
        base = data_for(kernel, 1)
        for index, value, first_bad in ((5, 200, None), (300 + 5, 200, 305), (300 + 7, -128, None),
                                        (3, -1, 3), (300 + 9, -129, 309)):
            data = list(base)
            data[index] = value
            initial = [-9]
            with self.subTest(index=index, value=value):
                ref = evaluate_source(kernel.source_module, data, initial)
                self.assertEqual(ref.first_bad_index, first_bad)
                self.assertEqual(execute_loop_plan(source, plan, data, initial), ref)


class RangeMutationTests(unittest.TestCase):
    def test_accepted_mutants_compute_the_reference_at_the_range_edges(self):
        from axiom.scale_plan import LoopPlan, Stage
        from axiom.scale_checker import check_loop_plan
        from tests.test_scale_oracle import _mutate
        rng = random.Random(1025)
        rejected = 0
        for source in (INT8_DOT.format(n=600).encode(), SIGNED_BOX.format(h=20, w=19).encode(),
                       SQUARE.format(n=1).encode()):
            kernel = admit_source(parse_source(source))
            plan = make_scale_plan(kernel)
            stage = plan.stages[0]
            for _ in range(80):
                mutant = LoopPlan(plan.semantic_digest, plan.plan_id,
                                  (Stage(stage.loops, stage.index, _mutate(stage.value, rng)),))
                if not check_loop_plan(source, mutant).valid:
                    rejected += 1
                    continue
                for seed, extreme in ((0, 'low'), (1, 'high'), (2, None)):
                    data = data_for(kernel, seed, extreme)
                    initial = [-9] * kernel.output_count
                    self.assertEqual(execute_loop_plan(source, mutant, data, initial),
                                     evaluate_source(kernel.source_module, data, initial))
        self.assertGreater(rejected, 150)


class RangeNativeTests(unittest.TestCase):
    def test_native_c_matches_the_reference(self):
        harness = Path(__file__).parent / 'fixtures' / 'scale_harness.c'
        sources = [INT8_DOT.format(n=40000).encode(), INT8_DOT.format(n=200).encode(),
                   SIGNED_BOX.format(h=120, w=100).encode(), SIGNED_BOX.format(h=30, w=25).encode(),
                   SQUARE.format(n=1).encode(), stencil_source(40, 30).replace(b'0..=1023', b'-3..=900')]
        with tempfile.TemporaryDirectory() as tmp:
            for number, source in enumerate(sources):
                kernel = admit_source(parse_source(source))
                c = Path(tmp) / f'k{number}.c'
                c.write_bytes(compile_scale_native(source).artifact.c_source
                              .replace(b'int main(void)', b'int beryl_unused_main(void)'))
                exe = Path(tmp) / f'k{number}.exe'
                try:
                    built = subprocess.run(['clang', '-O2', '-std=c11', '-Wall', '-Werror', str(c), str(harness),
                                            '-o', str(exe)], capture_output=True, text=True)
                except OSError as error:
                    self.skipTest(f'no C compiler: {error}')
                self.assertEqual(built.returncode, 0, built.stderr)
                n = kernel.input_count
                for threads in ('1', '4'):
                    for extreme, bad in ((None, None), ('low', None), ('high', None), (None, 0), (None, n - 1)):
                        data = data_for(kernel, number, extreme)
                        if bad is not None:
                            data[bad] = kernel.input_intervals[-1 if bad else 0][1] + 1
                        try:
                            ran = subprocess.run([str(exe), str(n), str(kernel.output_count)],
                                                 input=' '.join(map(str, data)), capture_output=True, text=True,
                                                 check=True, env={'BERYL_THREADS': threads, 'SYSTEMROOT': 'C:\\Windows'})
                        except OSError as error:  # Windows Application Control; never bypassed
                            self.skipTest(f'executable launch refused: {error}')
                        status, *values = map(int, ran.stdout.split())
                        ref = evaluate_source(kernel.source_module, data, [-9] * kernel.output_count)
                        with self.subTest(case=number, threads=threads, extreme=extreme, bad=bad):
                            self.assertEqual(status, 0 if ref.first_bad_index is None else ref.first_bad_index + 1)
                            self.assertEqual(tuple(values), ref.output)


if __name__ == '__main__':
    unittest.main()
