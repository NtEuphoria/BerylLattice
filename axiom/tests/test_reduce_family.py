"""reduce-v1: sum syntax, a second input, gathers, and their proofs."""
import dataclasses
import unittest

from axiom.checker import check_plan
from axiom.frontend import admit_source, parse_source
from axiom.model import DiagnosticError, Limits, REDUCE_PROFILE
from axiom.plan_format import Plan
from axiom.reference import evaluate_source
from axiom.runtime import execute_plan
from axiom.selection import select_plan

DOT = b'''module dot;
shape H = 1;
shape W = 1;
input x: i32[1,128] in 0..=1023;
input y: i32[1,128] in 0..=1023;
let t[r in 0..H,c in 0..W] = sum(k in 0..128: x[0,k]*y[0,k]);
output d[r in 0..H,c in 0..W] = t[r,c];
'''
MATMUL = b'''module matmul;
shape H = 8;
shape W = 8;
input a: i32[H,8] in 0..=1023;
input b: i32[8,W] in 0..=1023;
let t[r in 0..H,c in 0..W] = sum(k in 0..8: a[r,k]*b[k,c]);
output m[r in 0..H,c in 0..W] = t[r,c];
'''
SUM = b'''module total;
shape H = 1;
shape W = 1;
input x: i32[1,256] in 0..=1023;
let t[r in 0..H,c in 0..W] = sum(k in 0..256: x[0,k]);
output s[r in 0..H,c in 0..W] = t[r,c];
'''
TRANSPOSE = b'''module transpose;
shape H = 4;
shape W = 6;
input x: i32[W,H] in 0..=1023;
let t[r in 0..H,c in 0..W] = x[c,r];
output y[r in 0..H,c in 0..W] = t[r,c];
'''


def small(source, expression):
    return (b'module m;\nshape H = 1;\nshape W = 1;\ninput x: i32[1,8] in 0..=1023;\n'
            b'let t[r in 0..H,c in 0..W] = ' + expression + b';\n'
            b'output o[r in 0..H,c in 0..W] = t[r,c];\n') if source is None else source


def data_for(kernel):
    return [(i * 2654435761 & 0xFFFFFFFF) >> 22 for i in range(kernel.input_count)]


class ReduceFamilyTests(unittest.TestCase):
    def run_source(self, source, data=None):
        kernel = admit_source(parse_source(source))
        search = select_plan(kernel, Limits(), 10 ** 7, kernel.objective)
        self.assertIsNotNone(search.selected_plan)
        data = data_for(kernel) if data is None else data
        initial = [-9] * kernel.output_count
        observed = execute_plan(source, search.selected_plan_bytes, data, initial, Limits())
        self.assertEqual(observed, evaluate_source(kernel.source_module, data, initial))
        return kernel, search, observed, data

    def digest(self, expression):
        return admit_source(parse_source(small(None, expression))).semantic_digest

    def test_sum_is_exactly_a_balanced_tree(self):
        # mid = (lo + hi) // 2: three terms are t0 + (t1 + t2).
        self.assertEqual(self.digest(b'sum(k in 0..3: x[0,k])'), self.digest(b'x[0,0]+(x[0,1]+x[0,2])'))
        self.assertNotEqual(self.digest(b'sum(k in 0..3: x[0,k])'), self.digest(b'(x[0,0]+x[0,1])+x[0,2]'))
        self.assertEqual(self.digest(b'sum(k in 2..3: 5*x[0,k])'), self.digest(b'5*x[0,2]'))
        # The variable is a literal in scalar positions too, and sums nest.
        self.assertEqual(self.digest(b'sum(k in 0..2: k*x[0,k])'), self.digest(b'0*x[0,0]+1*x[0,1]'))
        nested = b'sum(i in 0..2: sum(j in 0..2: x[0,i+j]))'
        self.assertEqual(self.digest(nested), self.digest(b'(x[0,0+0]+x[0,0+1])+(x[0,1+0]+x[0,1+1])'))

    def test_kernels_match_the_reference_and_direct_formulas(self):
        _, _, observed, x = self.run_source(DOT)
        self.assertEqual(observed.output, (sum(x[i] * x[128 + i] for i in range(128)),))
        _, _, observed, x = self.run_source(MATMUL)
        a, b = x[:64], x[64:]
        self.assertEqual(observed.output, tuple(sum(a[i * 8 + k] * b[k * 8 + j] for k in range(8))
                                                for i in range(8) for j in range(8)))
        _, _, observed, x = self.run_source(SUM)
        self.assertEqual(observed.output, (sum(x),))
        kernel, _, observed, x = self.run_source(TRANSPOSE)
        self.assertEqual(observed.output, tuple(x[c * 4 + r] for r in range(4) for c in range(6)))
        self.assertEqual((kernel.profile, kernel.input_shapes, kernel.input_count), (REDUCE_PROFILE, ((6, 4),), 24))

    def test_second_input_layout_and_first_bad_index(self):
        kernel = admit_source(parse_source(DOT))
        self.assertEqual((kernel.input_shapes, kernel.input_count), (((1, 128), (1, 128)), 256))
        data = data_for(kernel)
        data[130] = 1024  # y[0,2]: an offset in the concatenated buffer
        search = select_plan(kernel, Limits(), 10 ** 7, kernel.objective)
        observed = execute_plan(DOT, search.selected_plan_bytes, data, [-9], Limits())
        self.assertEqual((observed.status.value, observed.first_bad_index, observed.output),
                         ('input_precondition_failed', 130, (-9,)))
        self.assertEqual(observed, evaluate_source(kernel.source_module, data, [-9]))

    def test_checker_rejects_a_plan_reading_the_wrong_input(self):
        kernel = admit_source(parse_source(DOT))
        plan = select_plan(kernel, Limits(), 10 ** 7, kernel.objective).selected_plan
        self.assertTrue(check_plan(kernel, plan, Limits(check_steps=10 ** 7)).eligible)
        position, load = next((i, op) for i, op in enumerate(plan.operations)
                              if op.opcode == 'input_load' and op.index >= 128)
        forged = list(plan.operations)
        forged[position] = dataclasses.replace(load, index=load.index - 128)  # x instead of y
        result = check_plan(kernel, Plan(plan.format_version, plan.semantic_digest, plan.plan_id,
                                         plan.scratch_capacity_cells, tuple(forged)),
                            Limits(check_steps=10 ** 7))
        self.assertFalse(result.eligible)

    def test_names_ranges_and_size(self):
        cases = [(b'sum(H in 0..2: x[0,H])', 'DUPLICATE_NAME'), (b'sum(r in 0..2: x[0,r])', 'DUPLICATE_NAME'),
                 (b'sum(k in 0..2: sum(k in 0..2: x[0,k]))', 'DUPLICATE_NAME'),
                 (b'sum(k in 2..2: x[0,k])', 'INVALID_RANGE'), (b'sum(k in 0..20000000: x[0,0])', 'INVALID_RANGE'),
                 (b'sum(k in 0..9: x[0,k])', 'INVALID_INDEX'), (b'x[0,sum(k in 0..2: k)]', 'SYNTAX_ERROR')]
        for expression, code in cases:
            with self.subTest(expression=expression):
                with self.assertRaises(DiagnosticError) as caught:
                    admit_source(parse_source(small(None, expression)))
                self.assertEqual(caught.exception.code, code)
        # One cell over 256 leaves reduce-v1 for scale-v1 (template-proved loop plans).
        big = DOT.replace(b'x: i32[1,128]', b'x: i32[1,129]')
        self.assertEqual(admit_source(parse_source(big)).profile, 'scale-v1')

    def test_oversized_plans_stop_at_the_operation_limit(self):
        # Review finding: inline-v1 of a 9x9 box over a 100-term producer has
        # over a million operations; generation must stop at the quota instead.
        import time
        from axiom.codec import DecodeError
        from axiom.planner import make_plan
        source = (b'module big;\nshape H = 8;\nshape W = 8;\ninput x: i32[H+8,W+8] in 0..=1023;\n'
                  b'let p[r in 0..H+8,c in 0..W+8] = sum(k in 0..100: k*x[r,c]);\n'
                  b'output o[r in 0..H,c in 0..W] = sum(i in 0..9: sum(j in 0..9: p[r+i,c+j]));\n')
        kernel = admit_source(parse_source(source))
        start = time.perf_counter()
        with self.assertRaises(DecodeError) as caught:
            make_plan(kernel, 'inline-v1', max_operations=Limits().plan_operations)
        self.assertEqual(caught.exception.code, 'OPERATION_LIMIT')
        search = select_plan(kernel, Limits(), 10 ** 7, kernel.objective)
        self.assertIsNone(search.selected_plan)
        self.assertLess(time.perf_counter() - start, 5)

    def test_window_and_canonical_programs_keep_their_family(self):
        from tests.helpers import stencil_source
        self.assertEqual(admit_source(parse_source(stencil_source(5, 7))).profile, 'canonical-stencil-v1')
        window = stencil_source(5, 7).replace(b'image[r,c]+1', b'image[r,c]+2')
        self.assertEqual(admit_source(parse_source(window)).profile, 'window-stencil-v1')


if __name__ == '__main__':
    unittest.main()
