"""shr and shr_round in scale-v1: exact floor and round-half-up shifts, proved bounds, native C."""
import random
import unittest

from axiom.frontend import admit_source, parse_source
from axiom.model import DiagnosticError
from axiom.reference import evaluate_source
from axiom.scale_c import compile_scale_native
from axiom.scale_checker import check_loop_plan
from axiom.scale_plan import LoopPlan, Stage, make_scale_plan
from axiom.scale_runtime import execute_loop_plan
from tests.test_scale_minmax import assert_native_matches
from tests.test_scale_ranges import data_for

# A quantized dense layer cell: int8 dot product, requantized with a fixed-point
# multiplier and a rounding shift, then saturated to int8.
REQUANT = '''module requant;
shape H = 1;
shape W = 1;
input a: i32[1,{n}] in 0..=255;
input w: i32[1,{n}] in -128..=127;
let t: i64[r in 0..H,c in 0..W] = shr_round(sum(k in 0..{n}: a[0,k]*w[0,k]) * 1518500250, 40);
output y[r in 0..H,c in 0..W] = clamp(t[r,c] + 3, -128, 127);
'''
# A signed vertical filter divided by 16, rounding toward minus infinity.
SHIFT_BOX = '''module shiftbox;
shape H = {h};
shape W = {w};
input x: i32[H+2,W+2] in -1000..=1000;
let p[r in 0..H+2,c in 0..W] = (x[r,c]+2*x[r,c+1])+x[r,c+2];
output o[r in 0..H,c in 0..W] = shr(p[r,c] + 2*p[r+1,c] + p[r+2,c], 4);
'''
# Shift amounts at and past the width of i32, over the whole i32 range.
EDGE_I32 = '''module edge32;
shape H = 1;
shape W = {w};
input x: i32[1,W] in -2147483648..=2147483647;
let t[r in 0..H,c in 0..W] = shr(x[r,c], 31) + shr_round(x[r,c], 32) + shr(x[r,c], 63) + shr_round(x[r,c], 1);
output y[r in 0..H,c in 0..W] = t[r,c];
'''
EDGE_I64 = '''module edge64;
shape H = 1;
shape W = {w};
input x: i32[1,W] in -2147483648..=2147483647;
let t: i64[r in 0..H,c in 0..W] = shr(x[r,c]*x[r,c], 33) + shr_round(x[r,c]*65536, 47) + shr(x[r,c], 0)
    + shr_round(x[r,c]*x[r,c], 63);
output y: i64[r in 0..H,c in 0..W] = t[r,c];
'''
SHIFTED_SUM = '''module shifted;
shape H = 1;
shape W = 1;
input x: i32[1,{n}] in 0..=1023;
let t[r in 0..H,c in 0..W] = sum(k in 0..{n}: {term});
output s[r in 0..H,c in 0..W] = t[r,c];
'''


def _admit(text):
    return admit_source(parse_source(text.encode()))


def _box(call):
    return SHIFT_BOX.format(h=4, w=4).replace('shr(p[r,c] + 2*p[r+1,c] + p[r+2,c], 4)', call)


class ShiftSyntaxTests(unittest.TestCase):
    def test_shifts_take_exactly_two_arguments(self):
        for call in ('shr(p[r,c])', 'shr(p[r,c], 1, 2)', 'shr_round()', 'shr_round(p[r,c], 1, 2)'):
            with self.subTest(call=call), self.assertRaises(DiagnosticError) as caught:
                _admit(_box(call))
            self.assertEqual(caught.exception.code, 'SYNTAX_ERROR')

    def test_shift_amount_is_an_integer_literal(self):
        for call in ('shr(p[r,c], p[r,c])', 'shr(p[r,c], 1+1)', 'shr_round(p[r,c], sum(k in 0..2: 1))'):
            with self.subTest(call=call), self.assertRaises(DiagnosticError) as caught:
                _admit(_box(call))
            self.assertEqual(caught.exception.code, 'SYNTAX_ERROR')

    def test_shift_amount_range(self):
        for call in ('shr(p[r,c], -1)', 'shr(p[r,c], 64)', 'shr_round(p[r,c], 0)', 'shr_round(p[r,c], 64)'):
            with self.subTest(call=call), self.assertRaises(DiagnosticError) as caught:
                _admit(_box(call))
            self.assertEqual(caught.exception.code, 'INVALID_EXPRESSION')
        for call in ('shr(p[r,c], 0)', 'shr(p[r,c], 63)', 'shr_round(p[r,c], 1)', 'shr_round(p[r,c], (63))'):
            with self.subTest(call=call):
                self.assertEqual(_admit(_box(call)).profile, 'scale-v1')

    def test_shr_is_not_an_index(self):
        with self.assertRaises(DiagnosticError) as caught:
            _admit(SHIFT_BOX.format(h=4, w=4).replace('p[r+1,c]', 'p[shr(r,1),c]'))
        self.assertEqual(caught.exception.code, 'SYNTAX_ERROR')

    def test_small_programs_with_shifts_are_scale_v1(self):
        self.assertEqual(_admit(SHIFT_BOX.format(h=4, w=4)).profile, 'scale-v1')
        self.assertEqual(_admit(REQUANT.format(n=10)).profile, 'scale-v1')

    def test_shift_kind_and_amount_are_part_of_the_identity(self):
        digests = {_admit(_box(call)).semantic_digest
                   for call in ('shr(p[r,c], 4)', 'shr(p[r,c], 5)', 'shr_round(p[r,c], 4)')}
        self.assertEqual(len(digests), 3)


class ShiftMeaningTests(unittest.TestCase):
    def test_shr_floors_and_shr_round_rounds_half_up(self):
        # o = shr(p0 + 2*p1 + p2, k) with p_i = x[i,0] when every other cell is 0.
        kernel = _admit(SHIFT_BOX.format(h=1, w=1).replace(', 4)', ', 1)'))
        rounded = _admit(SHIFT_BOX.format(h=1, w=1).replace('shr(', 'shr_round(').replace(', 4)', ', 1)'))
        for total, floor, half_up in ((7, 3, 4), (-7, -4, -3), (-5, -3, -2), (5, 2, 3), (-1, -1, 0),
                                      (0, 0, 0), (4, 2, 2), (-4, -2, -2)):
            data = [total, 0, 0] + [0] * 6
            with self.subTest(total=total):
                self.assertEqual(evaluate_source(kernel.source_module, data, [-9]).output, (floor,))
                self.assertEqual(evaluate_source(rounded.source_module, data, [-9]).output, (half_up,))

    def test_requantize_reference(self):
        kernel = _admit(REQUANT.format(n=3))
        a, w = [200, 255, 17], [127, -128, 90]
        acc = sum(x * y for x, y in zip(a, w))
        expected = max(-128, min(127, ((acc * 1518500250 + 2 ** 39) >> 40) + 3))
        self.assertEqual(evaluate_source(kernel.source_module, a + w, [-9]).output, (expected,))


class ShiftProofTests(unittest.TestCase):
    def test_shifted_terms_let_a_longer_sum_fit_i32(self):
        n = 4_000_000  # 4e6 * 1023 > 2^31, but 4e6 * 255 < 2^31
        self.assertEqual(compile_scale_native(SHIFTED_SUM.format(n=n, term='x[0,k]').encode()).reason,
                         'ARITHMETIC_OVERFLOW')
        self.assertEqual(compile_scale_native(SHIFTED_SUM.format(n=n, term='shr(x[0,k], 2)').encode()).reason,
                         'VALID')
        # shr_round(1023, 2) = 256: 4e6 * 256 still fits, but 9e6 * 256 does not.
        self.assertEqual(compile_scale_native(
            SHIFTED_SUM.format(n=n, term='shr_round(x[0,k], 2)').encode()).reason, 'VALID')
        self.assertEqual(compile_scale_native(
            SHIFTED_SUM.format(n=9_000_000, term='shr_round(x[0,k], 2)').encode()).reason, 'ARITHMETIC_OVERFLOW')

    def test_operands_of_a_shift_must_still_fit(self):
        bad = SHIFTED_SUM.format(n=1, term='shr(x[0,k]*x[0,k]*x[0,k]*x[0,k], 30)')
        self.assertEqual(compile_scale_native(bad.encode()).reason, 'ARITHMETIC_OVERFLOW')

    def test_requantized_i64_producer_fits_an_i32_output(self):
        self.assertEqual(compile_scale_native(REQUANT.format(n=40000).encode()).reason, 'VALID')
        # Without the shift, the i32 output cannot hold the i64 product.
        unshifted = REQUANT.format(n=40000).replace('shr_round(', '(').replace(', 40)', ')')
        self.assertEqual(compile_scale_native(unshifted.encode()).reason, 'ARITHMETIC_OVERFLOW')

    def test_changing_the_shift_is_rejected(self):
        source = SHIFT_BOX.format(h=6, w=5).encode()
        plan = make_scale_plan(admit_source(parse_source(source)))
        self.assertTrue(check_loop_plan(source, plan).valid)
        stage = plan.stages[0]
        kind, operand, amount = stage.value
        for bad in (('shr_round', operand, amount), (kind, operand, ('const', 5)), ('max', operand, amount)):
            mutant = LoopPlan(plan.semantic_digest, plan.plan_id, (Stage(stage.loops, stage.index, bad),))
            with self.subTest(bad=bad[0]):
                self.assertEqual(check_loop_plan(source, mutant).reason, 'STRUCTURAL_MISMATCH')

    def test_plans_compute_the_reference(self):
        for text in (REQUANT.format(n=300), SHIFT_BOX.format(h=9, w=7), EDGE_I32.format(w=40),
                     EDGE_I64.format(w=40), SHIFTED_SUM.format(n=500, term='shr_round(x[0,k] * 7, 3)')):
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


class ShiftMutationTests(unittest.TestCase):
    def test_accepted_mutants_compute_the_reference(self):
        from tests.test_scale_oracle import _mutate
        rng = random.Random(2028)
        rejected = 0
        for text in (REQUANT.format(n=400), SHIFT_BOX.format(h=12, w=11), EDGE_I32.format(w=30)):
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


class ShiftNativeTests(unittest.TestCase):
    def test_native_c_matches_the_reference(self):
        assert_native_matches(self, [REQUANT.format(n=40000), REQUANT.format(n=200), SHIFT_BOX.format(h=60, w=50),
                                     SHIFT_BOX.format(h=30, w=25), EDGE_I32.format(w=5000), EDGE_I64.format(w=5000),
                                     SHIFTED_SUM.format(n=3000, term='shr_round(x[0,k] * 7, 3)')])


if __name__ == '__main__':
    unittest.main()
