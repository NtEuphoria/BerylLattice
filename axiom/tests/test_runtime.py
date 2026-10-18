"""Behavioral tests for fresh checked finite-plan execution."""
from dataclasses import FrozenInstanceError, replace
import importlib
import importlib.util
import unittest
from unittest.mock import patch

from axiom.codec import DecodeError, encode_plan
from axiom.frontend import admit_source, parse_source
from axiom.model import DiagnosticError, Limits
from axiom.planner import PLAN_IDS, make_plan
from axiom.reference import ExecutionResult, evaluate_source
from tests.helpers import stencil_source


class RuntimeTests(unittest.TestCase):
    def runtime(self):
        self.assertIsNotNone(importlib.util.find_spec('axiom.runtime'),
                             'checked production runtime is missing')
        return importlib.import_module('axiom.runtime')

    def plan(self, source, name='inline-v1'):
        return make_plan(admit_source(parse_source(source)), name)

    def execute(self, source, data, initial, name='inline-v1', **kwargs):
        return self.runtime().execute_plan(source, encode_plan(self.plan(source, name)),
                                           data, initial, **kwargs)

    def test_all_schedules_execute_coordinate_sensitive_original_source(self):
        source = stencil_source(5, 7, cap=None)
        data = [(r * 73 + c * 19 + r * c * 11) % 1024
                for r in range(6) for c in range(8)]
        initial = [-777 - i for i in range(35)]
        expected = evaluate_source(parse_source(source), data, initial)
        for name in PLAN_IDS:
            with self.subTest(name=name):
                result = self.execute(source, data, initial, name)
                self.assertEqual(result, expected)
                self.assertIsInstance(result, ExecutionResult)
                with self.assertRaises(FrozenInstanceError):
                    result.output = ()
        self.assertEqual(initial, [-777 - i for i in range(35)])
        self.assertEqual(data, list(expected.input_after))

    def test_maximum_balanced_shape_matches_for_every_schedule(self):
        source = stencil_source(15, 15, cap=None)
        data = [(i * 47 + i // 16) % 1024 for i in range(256)]
        expected = evaluate_source(parse_source(source), data, [-9] * 225)
        for name in PLAN_IDS:
            with self.subTest(name=name):
                self.assertEqual(self.execute(source, data, [-9] * 225, name), expected)

    def test_runtime_does_not_call_source_evaluator(self):
        source = stencil_source(1, 1, cap=None)
        with patch('axiom.reference.evaluate_source', side_effect=AssertionError('not independent')):
            for name in PLAN_IDS:
                with self.subTest(name=name):
                    self.assertEqual(self.execute(source, [0, 1, 2, 3], [-9], name).output, (30,))

    def test_ineligible_plan_never_executes_under_tighter_source_cap(self):
        source = stencil_source(5, 7, cap=0)
        plan_bytes = encode_plan(self.plan(source, 'rows2-v1'))
        with self.assertRaises(DiagnosticError) as caught:
            self.runtime().execute_plan(source, plan_bytes, [0] * 48, [-9] * 35)
        self.assertEqual(caught.exception.code, 'CONSTRAINT_VIOLATED')

    def test_unknown_check_result_never_executes(self):
        source = stencil_source(1, 1)
        with self.assertRaises(DiagnosticError) as caught:
            self.execute(source, [0] * 4, [-9], limits=Limits(check_steps=1))
        self.assertEqual(caught.exception.code, 'CHECK_STEPS_EXHAUSTED')

    def test_altered_semantics_are_rejected_despite_unchanged_plan_label(self):
        source = stencil_source(1, 1)
        plan = self.plan(source)
        changed = replace(plan, operations=(replace(plan.operations[0], value=2),) + plan.operations[1:])
        with self.assertRaises(DiagnosticError):
            self.runtime().execute_plan(source, encode_plan(changed), [0] * 4, [-9])

    def test_wrong_source_and_malformed_plan_bytes_are_rejected(self):
        source = stencil_source(1, 1)
        plan_bytes = encode_plan(self.plan(source))
        with self.assertRaises(DiagnosticError) as caught:
            self.runtime().execute_plan(stencil_source(2, 1), plan_bytes, [0] * 6, [-9] * 2)
        self.assertEqual(caught.exception.code, 'SEMANTIC_DIGEST_MISMATCH')
        for raw in (b'{}', b'not json', plan_bytes + b' trailing', bytearray(plan_bytes)):
            with self.subTest(raw=type(raw).__name__), self.assertRaises((DiagnosticError, DecodeError)):
                self.runtime().execute_plan(source, raw, [0] * 4, [-9])

    def test_all_input_preflight_positions_preserve_entire_destination(self):
        source = stencil_source(2, 3, cap=None)
        for name in PLAN_IDS:
            for index in range(12):
                data = [0] * 12
                data[index] = 1024 if index % 2 else -1
                initial = [-123 - i for i in range(6)]
                with self.subTest(name=name, index=index):
                    result = self.execute(source, data, initial, name)
                    self.assertEqual(result.status, 'input_precondition_failed')
                    self.assertEqual(result.first_bad_index, index)
                    self.assertEqual(result.output, tuple(initial))
                    self.assertEqual(result.input_after, tuple(data))
                    self.assertEqual(initial, [-123 - i for i in range(6)])

    def test_first_bad_input_and_boundary_preflight_before_arithmetic(self):
        result = self.execute(stencil_source(1, 1), [2**31 - 1, -1, 0, 0], [-9])
        self.assertEqual(result.first_bad_index, 0)
        self.assertEqual(result.output, (-9,))
        # A later non-i32 is a malformed boundary even if an earlier i32 fails
        # the source precondition: the complete boundary must be validated first.
        with self.assertRaises(DiagnosticError) as caught:
            self.execute(stencil_source(1, 1), [1024, 0, 0, 2**31], [-9])
        self.assertEqual(caught.exception.code, 'BOUNDARY_I32')

    def test_boundary_rejects_types_lengths_alias_and_non_i32(self):
        self.runtime()
        source = stencil_source(1, 1)
        cases = ((None, [-9], 'BOUNDARY_TYPE'),
                 ([0] * 3, [-9], 'BOUNDARY_LENGTH'),
                 ([0] * 4, [], 'BOUNDARY_LENGTH'),
                 ([False, 0, 0, 0], [-9], 'BOUNDARY_TYPE'),
                 ([0] * 4, [0.0], 'BOUNDARY_TYPE'),
                 ([0] * 4, [2**31], 'BOUNDARY_I32'))
        for data, initial, code in cases:
            with self.subTest(code=code), self.assertRaises(DiagnosticError) as caught:
                self.execute(source, data, initial)
            self.assertEqual(caught.exception.code, code)
        shared = [0] * 4
        with self.assertRaises(DiagnosticError) as caught:
            self.execute(source, shared, shared)
        self.assertEqual(caught.exception.code, 'BOUNDARY_ALIAS')

    def test_huge_unused_declared_arena_does_not_require_huge_allocation(self):
        source = stencil_source(1, 1, cap=None)
        plan = replace(self.plan(source), scratch_capacity_cells=2147483647)
        result = self.runtime().execute_plan(source, encode_plan(plan), [0, 1, 2, 3], [-9])
        self.assertEqual(result.output, (30,))

    def test_source_admission_and_exact_argument_types_precede_execution(self):
        source = stencil_source(1, 1)
        plan_bytes = encode_plan(self.plan(source))
        for malformed in (b'not axiom', source.replace(b'+1)', b'+2)'), stencil_source(32, 32)):
            with self.subTest(source=malformed[:20]), self.assertRaises(DiagnosticError):
                self.runtime().execute_plan(malformed, plan_bytes, [], [])
        with self.assertRaises(DiagnosticError):
            self.runtime().execute_plan(bytearray(source), plan_bytes, [0] * 4, [-9])
        with self.assertRaises(DiagnosticError):
            self.runtime().execute_plan(source, plan_bytes, [0] * 4, [-9], limits=None)


if __name__ == '__main__':
    unittest.main()
