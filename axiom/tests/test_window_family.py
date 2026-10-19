"""Two-stage window stencils: admission, plans, proof, execution and boundaries.

The planner is exercised as a candidate source only. Correctness always comes
from the unchanged independent checker and the original-source reference.
"""
from dataclasses import replace
import unittest

from axiom.checker import check_plan
from axiom.codec import encode_plan
from axiom.frontend import admit_source, parse_source
from axiom.model import DiagnosticError, Limits, Objective, WINDOW_PROFILE
from axiom.planner import make_plan, plan_ids
from axiom.reference import evaluate_source
from axiom.runtime import execute_plan
from axiom.selection import select_plan

PROGRAMS = {
    'conv3x3': ('i32[H+2,W+2]', 'H+2', 'W', '(g[r,c]+2*g[r,c+1])+g[r,c+2]', '(t[r,c]+2*t[r+1,c])+t[r+2,c]'),
    'box3x3': ('i32[H+2,W+2]', 'H+2', 'W', '(g[r,c]+g[r,c+1])+g[r,c+2]', '(t[r,c]+t[r+1,c])+t[r+2,c]'),
    'laplace5': ('i32[H+2,W+2]', 'H+2', 'W+2', 'g[r,c]',
                 '4*t[r+1,c+1] + -1*t[r,c+1] + -1*t[r+2,c+1] + -1*t[r+1,c] + -1*t[r+1,c+2]'),
    'sq2x2-plus2': ('i32[H+1,W+1]', 'H+1', 'W+1', '(g[r,c]+2)*(g[r,c]+2)',
                    '((t[r,c]+t[r,c+1])+t[r+1,c])+t[r+1,c+1]'),
    'stencil1d3': ('i32[H,W+2]', 'H', 'W', '(g[r,c]+2*g[r,c+1])+g[r,c+2]', 't[r,c]'),
    'polymap': ('i32[H,W]', 'H', 'W', 'g[r,c]*g[r,c]*g[r,c] + 3*g[r,c] + 7', 't[r,c]'),
}
SHAPES = {'conv3x3': ((1, 1), (3, 5), (14, 14)), 'box3x3': ((1, 1), (14, 14)),
          'laplace5': ((1, 1), (14, 14)), 'sq2x2-plus2': ((1, 1), (15, 15)),
          'stencil1d3': ((1, 1), (1, 254)), 'polymap': ((1, 1), (16, 16))}


def source(name, h, w, cap=None, objective='multiplication_ops'):
    dims, prow, pcol, producer, output = PROGRAMS[name]
    requirement = '' if cap is None else f'require plan_workspace_bytes <= {cap};\n'
    return (f'module family;\nshape H = {h};\nshape W = {w};\n'
            f'input g: {dims} in 0..=1023;\n'
            f'let t[r in 0..{prow},c in 0..{pcol}] = {producer};\n'
            f'output o[r in 0..H,c in 0..W] = {output};\n'
            f'{requirement}prefer {objective};\n').encode()


def patterns(count):
    yield [0] * count
    yield [1023] * count
    yield [(i * 2654435761 & 0xFFFFFFFF) >> 22 for i in range(count)]


class WindowFamilyTests(unittest.TestCase):
    def test_every_plan_is_proved_and_matches_the_reference(self):
        limits = Limits()
        for name, shapes in SHAPES.items():
            for h, w in shapes:
                src = source(name, h, w)
                kernel = admit_source(parse_source(src))
                self.assertEqual(kernel.profile, WINDOW_PROFILE)
                self.assertLessEqual(kernel.input_count, 256)
                for plan_id in plan_ids(kernel):
                    with self.subTest(program=name, shape=(h, w), plan=plan_id):
                        plan = make_plan(kernel, plan_id)
                        checked = check_plan(kernel, plan, limits)
                        self.assertEqual((checked.semantic_status.value, checked.reason), ('valid', 'VALID'))
                        data = encode_plan(plan, limits=limits)
                        for inputs in patterns(kernel.input_count):
                            initial = [-9] * kernel.output_count
                            observed = execute_plan(src, data, inputs, initial, limits)
                            self.assertEqual(observed, evaluate_source(kernel.source_module, inputs, initial))
                            self.assertEqual(observed.status.value, 'success')

    def test_selection_trades_storage_for_multiplications_at_exact_caps(self):
        h, w = 14, 14
        rows_bytes, material_bytes = 3 * w * 4, (h + 2) * w * 4  # 3 rolling rows vs whole producer
        for cap, expected in ((0, 'inline-v1'), (rows_bytes - 1, 'inline-v1'), (rows_bytes, 'rows-v1'),
                              (material_bytes, 'rows-v1'), (None, 'rows-v1')):
            with self.subTest(cap=cap):
                kernel = admit_source(parse_source(source('conv3x3', h, w, cap)))
                result = select_plan(kernel, Limits(), 10 ** 7, Objective.MULTIPLICATION_OPS)
                self.assertEqual(result.selected_plan.plan_id, expected)
                if cap is not None:
                    self.assertLessEqual(result.selected_check.workspace_bytes, cap)
        kernel = admit_source(parse_source(source('conv3x3', h, w, None, 'plan_workspace_bytes')))
        result = select_plan(kernel, Limits(), 10 ** 7, Objective.PLAN_WORKSPACE_BYTES)
        self.assertEqual(result.selected_plan.plan_id, 'inline-v1')
        checks = {a.candidate_id: a.check for a in result.attempts}
        self.assertEqual(checks['rows-v1'].workspace_bytes, rows_bytes)
        self.assertEqual(checks['materialize-v1'].workspace_bytes, material_bytes)
        self.assertLess(checks['rows-v1'].multiplication_ops, checks['inline-v1'].multiplication_ops)

    def test_broken_plans_are_never_eligible(self):
        kernel = admit_source(parse_source(source('conv3x3', 3, 5)))
        for plan_id in plan_ids(kernel):
            plan = make_plan(kernel, plan_id)
            ops = list(plan.operations)
            first = lambda opcode: next(i for i, op in enumerate(ops) if op.opcode == opcode)
            mutations = {}
            i = first('const')
            mutations['const'] = replace(plan, operations=tuple(ops[:i] + [replace(ops[i], value=ops[i].value + 1)] + ops[i+1:]))
            i = first('input_load')
            mutations['input_index'] = replace(plan, operations=tuple(ops[:i] + [replace(ops[i], index=ops[i].index + 1)] + ops[i+1:]))
            i = first('add')
            mutations['swapped'] = replace(plan, operations=tuple(ops[:i] + [replace(ops[i], operands=ops[i].operands[::-1])] + ops[i+1:]))
            last_store = max(j for j, op in enumerate(ops) if op.opcode == 'output_store')
            mutations['missing_output'] = replace(plan, operations=tuple(ops[:last_store] + ops[last_store+1:]))
            if any(op.opcode == 'scratch_store' for op in ops):
                j = first('scratch_store')
                mutations['uninitialized_scratch'] = replace(plan, operations=tuple(ops[:j] + ops[j+1:]))
            mutations['wrong_semantics'] = replace(plan, semantic_digest='0' * 64)
            for label, broken in mutations.items():
                with self.subTest(plan=plan_id, mutation=label):
                    self.assertFalse(check_plan(kernel, broken, Limits()).eligible)

    def test_overflow_is_detected_not_executed(self):
        src = source('conv3x3', 2, 2).replace(b'2*g[r,c+1]', b'2147483647*g[r,c+1]')
        kernel = admit_source(parse_source(src))
        checked = check_plan(kernel, make_plan(kernel, 'inline-v1'), Limits())
        self.assertEqual((checked.semantic_status.value, checked.reason), ('invalid', 'ARITHMETIC_OVERFLOW'))
        result = select_plan(kernel, Limits(), 10 ** 7, Objective.MULTIPLICATION_OPS)
        self.assertIsNone(result.selected_plan)

    def test_input_precondition_preserves_everything(self):
        src = source('conv3x3', 3, 5)
        kernel = admit_source(parse_source(src))
        data = encode_plan(make_plan(kernel, 'rows-v1'))
        inputs = [0] * kernel.input_count
        inputs[17] = 1024
        initial = [-5] * kernel.output_count
        observed = execute_plan(src, data, inputs, initial, Limits())
        self.assertEqual((observed.status.value, observed.first_bad_index), ('input_precondition_failed', 17))
        self.assertEqual(observed, evaluate_source(kernel.source_module, inputs, initial))

    def test_canonical_only_paths_refuse_family_kernels(self):
        from axiom.core_emit import emit_core_kernel
        from axiom.source_compilation import compile_native_source, compile_wasm_source
        src = source('conv3x3', 3, 5, 1024)
        kernel = admit_source(parse_source(src))
        plan_bytes = encode_plan(make_plan(kernel, 'inline-v1'))
        with self.assertRaises(DiagnosticError) as caught:
            emit_core_kernel(src, plan_bytes, Limits())
        self.assertEqual(caught.exception.code, 'UNSUPPORTED_PROFILE')
        for compile_source in (compile_native_source, compile_wasm_source):
            # Compilation itself is not canonical-only: family kernels get compact
            # loop hints that must match the checked plan exactly (see test_window_compact).
            compiled = compile_source(src)
            self.assertIsNone(compiled.hint_failure)
            self.assertIn('bounded-loop', compiled.artifact.codegen_version)
            self.assertEqual(compiled.artifact.input_count, kernel.input_count)

    def test_service_reports_family_shapes_and_prescans(self):
        from axiom.playground_service import run_demo
        src = source('conv3x3', 3, 5, 1024).decode()
        result = run_demo(dict(source=src, input_mode='ramp'))
        self.assertEqual(result['status'], 'success')
        self.assertEqual((result['shape']['input_height'], result['shape']['input_width']), (5, 7))
        self.assertEqual(result['selected']['plan_id'], 'rows-v1')
        bad = [0] * 35
        bad[4] = 2000
        refused = run_demo(dict(source=src, input_mode='custom', inputs=bad))
        self.assertEqual((refused['status'], refused['first_bad_index'], refused['attempts']),
                         ('input_precondition_failed', 4, []))


if __name__ == '__main__':
    unittest.main()
