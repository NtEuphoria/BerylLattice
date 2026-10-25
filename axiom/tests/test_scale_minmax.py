"""min, max and clamp in scale-v1: exact integer meaning, proved bounds, native C."""
from pathlib import Path
import random
import subprocess
import tempfile
import unittest

from axiom.frontend import admit_source, parse_source
from axiom.model import DiagnosticError
from axiom.reference import evaluate_source
from axiom.scale_c import compile_scale_native
from axiom.scale_checker import check_loop_plan
from axiom.scale_plan import LoopPlan, Stage, make_scale_plan
from axiom.scale_runtime import execute_loop_plan
from tests.test_scale_ranges import data_for

# A quantized dense layer cell: int8 dot product, then ReLU.
RELU_DOT = '''module reludot;
shape H = 1;
shape W = 1;
input a: i32[1,{n}] in 0..=255;
input w: i32[1,{n}] in -128..=127;
let t[r in 0..H,c in 0..W] = sum(k in 0..{n}: a[0,k]*w[0,k]);
output y[r in 0..H,c in 0..W] = max(t[r,c], 0);
'''
# A signed 3-tap vertical filter clamped back into 0..255.
CLAMP_BOX = '''module clampbox;
shape H = {h};
shape W = {w};
input x: i32[H+2,W+2] in -1000..=1000;
let p[r in 0..H+2,c in 0..W] = (x[r,c]+2*x[r,c+1])+x[r,c+2];
output o[r in 0..H,c in 0..W] = clamp(4*p[r+1,c] - p[r,c] - p[r+2,c], 0, 255);
'''
# The checker bounds a sum by its terms' interval, so capping each term lets more terms fit i32.
CAPPED_SUM = '''module capped;
shape H = 1;
shape W = 1;
input x: i32[1,{n}] in 0..=1023;
let t[r in 0..H,c in 0..W] = sum(k in 0..{n}: {term});
output s[r in 0..H,c in 0..W] = t[r,c];
'''
WIDE_MIN = '''module widemin;
shape H = 1;
shape W = {w};
input x: i32[1,W] in -2147483648..=2147483647;
let t: i64[r in 0..H,c in 0..W] = min(x[r,c]*x[r,c], 2000000000) + max(x[r,c], -5);
output y: i64[r in 0..H,c in 0..W] = t[r,c];
'''


def _admit(text):
    return admit_source(parse_source(text.encode()))


class MinMaxSyntaxTests(unittest.TestCase):
    def test_min_and_max_take_exactly_two_arguments(self):
        for call in ('min(x[r,c])', 'max(x[r,c], 1, 2)', 'min()', 'clamp(x[r,c], 1)'):
            with self.subTest(call=call), self.assertRaises(DiagnosticError) as caught:
                _admit(CLAMP_BOX.format(h=4, w=4).replace('clamp(4*p[r+1,c] - p[r,c] - p[r+2,c], 0, 255)',
                                                         call.replace('x[r,c]', 'p[r,c]')))
            self.assertEqual(caught.exception.code, 'SYNTAX_ERROR')

    def test_clamp_means_exactly_min_of_max(self):
        written = CLAMP_BOX.format(h=6, w=5).replace(
            'clamp(4*p[r+1,c] - p[r,c] - p[r+2,c], 0, 255)', 'min(max(4*p[r+1,c] - p[r,c] - p[r+2,c], 0), 255)')
        self.assertEqual(_admit(CLAMP_BOX.format(h=6, w=5)).semantic_digest, _admit(written).semantic_digest)

    def test_clamp_with_inverted_literal_bounds_is_refused(self):
        with self.assertRaises(DiagnosticError) as caught:
            _admit(CLAMP_BOX.format(h=4, w=4).replace(', 0, 255)', ', 255, 0)'))
        self.assertEqual(caught.exception.code, 'INVALID_EXPRESSION')

    def test_min_is_not_an_index(self):
        with self.assertRaises(DiagnosticError) as caught:
            _admit(CLAMP_BOX.format(h=4, w=4).replace('p[r+1,c]', 'p[min(r,1),c]'))
        self.assertEqual(caught.exception.code, 'SYNTAX_ERROR')

    def test_small_programs_with_min_or_max_are_scale_v1(self):
        kernel = _admit(CLAMP_BOX.format(h=4, w=4))
        self.assertEqual(kernel.profile, 'scale-v1')
        self.assertEqual(_admit(RELU_DOT.format(n=10)).profile, 'scale-v1')


class MinMaxProofTests(unittest.TestCase):
    def test_capping_terms_lets_a_longer_sum_fit_i32(self):
        n = 4_000_000  # 4e6 * 1023 > 2^31, but 4e6 * 255 < 2^31
        self.assertEqual(compile_scale_native(CAPPED_SUM.format(n=n, term='x[0,k]').encode()).reason,
                         'ARITHMETIC_OVERFLOW')
        self.assertEqual(compile_scale_native(CAPPED_SUM.format(n=n, term='min(x[0,k], 255)').encode()).reason,
                         'VALID')
        # max raises the low end only; the high end, and the overflow, stay.
        self.assertEqual(compile_scale_native(CAPPED_SUM.format(n=n, term='max(x[0,k], 255)').encode()).reason,
                         'ARITHMETIC_OVERFLOW')

    def test_operands_of_min_must_still_fit(self):
        bad = CAPPED_SUM.format(n=1, term='min(x[0,k]*x[0,k]*x[0,k]*x[0,k], 5)')
        self.assertEqual(compile_scale_native(bad.encode()).reason, 'ARITHMETIC_OVERFLOW')

    def test_swapping_min_and_max_is_rejected(self):
        source = CLAMP_BOX.format(h=6, w=5).encode()
        plan = make_scale_plan(admit_source(parse_source(source)))
        self.assertTrue(check_loop_plan(source, plan).valid)
        swap = {'min': 'max', 'max': 'min'}

        def flipped(e):
            if e[0] in swap:
                return (swap[e[0]], e[1], e[2])
            if e[0] in ('add', 'mul'):
                return (e[0], flipped(e[1]), flipped(e[2]))
            return e
        stage = plan.stages[0]
        bad = LoopPlan(plan.semantic_digest, plan.plan_id, (Stage(stage.loops, stage.index, flipped(stage.value)),))
        self.assertEqual(check_loop_plan(source, bad).reason, 'STRUCTURAL_MISMATCH')

    def test_plans_compute_the_reference(self):
        for text in (RELU_DOT.format(n=300), CLAMP_BOX.format(h=9, w=7),
                     CAPPED_SUM.format(n=500, term='max(min(x[0,k], 700), 100)'), WIDE_MIN.format(w=40)):
            source = text.encode()
            kernel = admit_source(parse_source(source))
            for plan_id in ('direct-v1', 'carry-v1'):
                try:
                    plan = make_scale_plan(kernel, plan_id)
                except ValueError:
                    continue  # carry-v1 needs window reads of the producer
                for seed, extreme in ((0, 'low'), (1, 'high'), (2, None), (3, None)):
                    data = data_for(kernel, seed, extreme)
                    initial = [-9] * kernel.output_count
                    with self.subTest(module=text.split(';')[0], plan=plan_id, seed=seed):
                        ref = evaluate_source(kernel.source_module, data, initial)
                        self.assertEqual(ref.status.value, 'success')
                        self.assertEqual(execute_loop_plan(source, plan, data, initial), ref)

    def test_reference_meaning_of_min_max_and_clamp(self):
        kernel = _admit(CLAMP_BOX.format(h=1, w=1))
        # p = x0 + 2*x1 + x2 per row; output = clamp(4*p1 - p0 - p2, 0, 255).
        # With x[i,0] = v_i and every other cell 0, p_i = v_i.
        for values, expected in (([0, 0, 0], 0), ([0, 10, 0], 40), ([0, 100, 0], 255), ([5, 0, 5], 0),
                                 ([-7, 3, 1], 18)):
            data = [v for value in values for v in (value, 0, 0)]
            with self.subTest(values=values):
                self.assertEqual(evaluate_source(kernel.source_module, data, [-9]).output, (expected,))


class MinMaxMutationTests(unittest.TestCase):
    def test_accepted_mutants_compute_the_reference(self):
        from tests.test_scale_oracle import _mutate
        rng = random.Random(2027)
        rejected = 0
        for text in (RELU_DOT.format(n=400), CLAMP_BOX.format(h=12, w=11),
                     CAPPED_SUM.format(n=300, term='max(min(x[0,k], 700), 100)')):
            source = text.encode()
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


class MinMaxNativeTests(unittest.TestCase):
    def test_native_c_matches_the_reference(self):
        harness = Path(__file__).parent / 'fixtures' / 'scale_harness.c'
        sources = [RELU_DOT.format(n=40000), RELU_DOT.format(n=200), CLAMP_BOX.format(h=120, w=100),
                   CLAMP_BOX.format(h=30, w=25), CAPPED_SUM.format(n=2_200_000, term='min(x[0,k], 255)'),
                   CAPPED_SUM.format(n=3000, term='max(min(x[0,k], 700), 100)'), WIDE_MIN.format(w=5000)]
        with tempfile.TemporaryDirectory() as tmp:
            for number, text in enumerate(sources):
                source = text.encode()
                kernel = admit_source(parse_source(source))
                compiled = compile_scale_native(source)
                self.assertIsNotNone(compiled.artifact, compiled.reason)
                c = Path(tmp) / f'k{number}.c'
                c.write_bytes(compiled.artifact.c_source.replace(b'int main(void)', b'int beryl_unused_main(void)'))
                exe = Path(tmp) / f'k{number}.exe'
                try:
                    out = 'int64_t' if kernel.output_type == 'i64' else 'int32_t'
                    built = subprocess.run(['clang', '-O2', '-std=c11', '-Wall', '-Werror', f'-DBERYL_OUT={out}',
                                            str(c), str(harness), '-o', str(exe)], capture_output=True, text=True)
                except OSError as error:
                    self.skipTest(f'no C compiler: {error}')
                self.assertEqual(built.returncode, 0, built.stderr)
                n = kernel.input_count
                # The reference interprets every term, so the largest case runs one full set.
                cases = ((None, None), (None, n - 1)) if n > 1 << 20 else (
                    (None, None), ('low', None), ('high', None), (None, n - 1))
                for extreme, bad in cases:
                    data = data_for(kernel, number, extreme)
                    if bad is not None and kernel.input_intervals[-1][1] < 2 ** 31 - 1:
                        data[bad] = kernel.input_intervals[-1][1] + 1
                    ref = evaluate_source(kernel.source_module, data, [-9] * kernel.output_count)
                    for threads in ('1', '4'):
                        try:
                            ran = subprocess.run([str(exe), str(n), str(kernel.output_count)],
                                                 input=' '.join(map(str, data)), capture_output=True, text=True,
                                                 check=True, env={'BERYL_THREADS': threads, 'SYSTEMROOT': 'C:\\Windows'})
                        except OSError as error:  # Windows Application Control; never bypassed
                            self.skipTest(f'executable launch refused: {error}')
                        status, *values = map(int, ran.stdout.split())
                        with self.subTest(case=number, threads=threads, extreme=extreme, bad=bad):
                            self.assertEqual(status, 0 if ref.first_bad_index is None else ref.first_bad_index + 1)
                            self.assertEqual(tuple(values), ref.output)


if __name__ == '__main__':
    unittest.main()
