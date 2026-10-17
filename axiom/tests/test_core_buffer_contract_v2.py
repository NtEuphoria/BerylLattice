"""Executable B1 specifications; the adapter is test-only, never native evidence."""
import dataclasses
import json
from pathlib import Path
import unittest

from axiom.model import DiagnosticError
from axiom.source_profiles import SourceLimitsV2, SourceProfileV2, admit_source_v2
from tests.helpers import stencil_source

try:
    from tests.support import buffer_contract_v2 as fixture
except ImportError:
    fixture = None

FIXTURES = Path(__file__).parent / 'fixtures' / 'core_native_v2'


class BufferContractTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(fixture, 'B1 test-only checked-boundary adapter is missing')

    def source(self, h=1, w=2, cap=None):
        return stencil_source(h, w, cap)

    def invoke(self, values=None, initial=None, **kwargs):
        invocation = fixture.prepare(self.source(), ([0, 1, 2, 3, 4, 5] if values is None else values),
                                     ([-99, 77] if initial is None else initial))
        callbacks = fixture.Callbacks()
        result = fixture.checked_call(invocation, callbacks, **kwargs)
        return invocation, callbacks, result

    def test_fixed_size_arithmetic_and_profile_maxima(self):
        # Arithmetic only: none of these large states is materialized.
        cases = [(1, 1, 4, 1), (8191, 1023, 8388608, 8379393),
                 (8192, 1, 16386, 8192), (1, 8192, 16386, 8192),
                 (2049, 2047, 4198400, 4194303),
                 (2048, 2048, 4198401, 4194304)]
        for h, w, p, q in cases:
            with self.subTest(h=h, w=w):
                sizes = fixture.sizes(self.source(h, w), p)
                self.assertEqual((sizes.input_cells, sizes.output_cells), (p, q))
                self.assertEqual(sizes.state_bytes, 4*(p+q))
                self.assertEqual(sizes.scratch_bytes, 4*p)
                self.assertLess(sizes.state_bytes, 64*1024**2)
                self.assertLessEqual(sizes.scratch_bytes, 32*1024**2)
        self.assertEqual(fixture.sizes(self.source(2049, 2047), 0).input_bytes, 16793600)
        self.assertEqual(fixture.sizes(self.source(2049, 2047), 0).output_bytes, 16777212)
        self.assertEqual(fixture.sizes(self.source(2048, 2048), 0).state_bytes, 33570820)
        for h, w in [(0, 1), (1, 0), (8193, 1), (1, 8193), (8192, 1023)]:
            with self.subTest(h=h, w=w), self.assertRaises(DiagnosticError):
                fixture.sizes(self.source(h, w), 0)

    def test_reserved_capacity_not_used_cells_is_charged(self):
        self.assertEqual(fixture.sizes(self.source(), 6).scratch_bytes, 24)
        for capacity in [-1, 7, True, 1.0]:
            with self.subTest(capacity=capacity), self.assertRaises(ValueError):
                fixture.sizes(self.source(), capacity)
        with self.assertRaises(ValueError):
            fixture.sizes(self.source(cap=20), 6)
        with self.assertRaises(ValueError):
            fixture.sizes(self.source(), 6, size_max=23)
        # Unused reserved cells cannot be discounted to fit a source cap.
        self.assertEqual(fixture.sizes(self.source(cap=24), 6).scratch_bytes, 24)

    def test_valid_real_callbacks_and_timer_order(self):
        inv, cb, result = self.invoke(scratch_capacity=6)
        self.assertEqual((result.completion, result.status, result.first_bad_index),
                         ('complete', 'success', None))
        self.assertEqual(result.state, ((0, 1, 2, 3, 4, 5), (46, 74)))
        self.assertEqual(cb.events, ['timer_start', 'metadata', 'preflight',
                                   'allocate:6', 'zero:6', 'body', 'integrity',
                                   'free:6', 'timer_end', 'acquire', 'compare'])
        self.assertEqual(cb.allocations, [(6, 24)])
        self.assertEqual(cb.read_indices, list(range(6)))
        self.assertTrue(cb.scratch_was_zero)
        self.assertEqual(cb.freed, cb.allocated)
        self.assertEqual(inv.output.data, [46, 74])

    def test_invalid_input_preserves_all_state_before_scratch(self):
        for values, index in [([-1, 1, 2, 3, 4, 1024], 0),
                              ([0, 1, 2, 3, 4, 1024], 5),
                              ([0, 1024, 2, -1, 4, 5], 1)]:
            with self.subTest(index=index):
                inv, cb, result = self.invoke(values, scratch_capacity=6)
                self.assertEqual((result.completion, result.status, result.first_bad_index),
                                 ('complete', 'input_precondition_failed', index))
                self.assertEqual(result.state, (tuple(values), (-99, 77)))
                self.assertEqual(cb.events, ['timer_start', 'metadata', 'preflight',
                                           'integrity', 'timer_end', 'acquire', 'compare'])
                self.assertEqual(cb.allocations, [])
                self.assertEqual(inv.output.data, [-99, 77])
                self.assertEqual(cb.read_indices, list(range(index+1)))

    def test_inline_has_zero_allocation_and_empty_initialized_scratch(self):
        _, cb, result = self.invoke(scratch_capacity=0)
        self.assertEqual(result.state[1], (46, 74))
        self.assertEqual(cb.allocations, [])
        self.assertEqual(cb.body_scratch, (None, 0, 0))
        self.assertNotIn('free:0', cb.events)

    def test_no_caller_validation_bit_or_constructed_admission(self):
        inv = fixture.prepare(self.source(), [0]*6, [8, 9])
        with self.assertRaises(TypeError):
            fixture.checked_call(inv, fixture.Callbacks(), scratch_capacity=0, validated=True)
        kernel = admit_source_v2(self.source(), profile=SourceProfileV2(), limits=SourceLimitsV2())
        with self.assertRaises((TypeError, ValueError)):
            fixture.prepare(kernel, [0]*6, [8, 9])

    def test_boundary_metadata_rejection_precedes_core_access(self):
        mutations = [lambda inv: setattr(inv.input, 'live', False),
                     lambda inv: setattr(inv.input, 'generation', 2),
                     lambda inv: setattr(inv.input, 'generation', True),
                     lambda inv: setattr(inv.input.descriptor, 'length', 6.0),
                     lambda inv: setattr(inv.output, 'alignment', 4.0),
                     lambda inv: setattr(inv.output, 'initialized', 1),
                     lambda inv: setattr(inv.output, 'alignment', 1),
                     lambda inv: setattr(inv.output, 'identity', inv.input.identity),
                     lambda inv: setattr(inv.input.descriptor, 'length', 5),
                     lambda inv: setattr(inv.output.descriptor, 'capacity', 3),
                     lambda inv: setattr(inv, 'compiled_source_sha256', '0'*64)]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                inv = fixture.prepare(self.source(), [0]*6, [8, 9])
                mutate(inv)
                cb = fixture.Callbacks()
                result = fixture.checked_call(inv, cb, scratch_capacity=6)
                self.assertEqual(result.completion, 'boundary_error')
                self.assertIsNone(result.status)
                self.assertIsNone(result.state)
                self.assertEqual(cb.events, ['timer_start', 'metadata', 'timer_end'])
                self.assertEqual(inv.output.data, [8, 9])

    def test_preparation_rejects_bad_extents_and_non_i32_values(self):
        for values, initial in [([], [8, 9]), ([0]*6, []),
                                ([True]*6, [8, 9]), ([0]*6, [8, 2**31])]:
            with self.subTest(values=values, initial=initial), self.assertRaises(ValueError):
                fixture.prepare(self.source(), values, initial)

    def test_unsupported_tiny_scratch_is_boundary_failure_after_preflight(self):
        for capacity in [1, 7, -1, True]:
            with self.subTest(capacity=capacity):
                inv, cb, result = self.invoke(scratch_capacity=capacity)
                self.assertEqual(result.completion, 'boundary_error')
                self.assertIsNone(result.state)
                self.assertEqual(inv.output.data, [-99, 77])
                self.assertEqual(cb.events, ['timer_start', 'metadata', 'preflight', 'timer_end'])

    def test_scratch_oom_is_resource_failure_and_preserves_output(self):
        inv = fixture.prepare(self.source(), [0]*6, [8, 9])
        cb = fixture.Callbacks(fault='oom')
        result = fixture.checked_call(inv, cb, scratch_capacity=6)
        self.assertEqual(result.completion, 'resource_error')
        self.assertIsNone(result.status)
        self.assertIsNone(result.state)
        self.assertEqual(inv.output.data, [8, 9])
        self.assertEqual(cb.events, ['timer_start', 'metadata', 'preflight',
                                    'allocate:6', 'timer_end'])

    def test_failures_never_synthesize_completed_state_and_cleanup_original(self):
        for fault, completion in [('descriptor', 'integrity_error'),
                                  ('input_mutation', 'integrity_error'),
                                  ('trap', 'process_error'),
                                  ('acquire', 'acquisition_error'),
                                  ('partial_acquire', 'acquisition_error'),
                                  ('mismatch', 'comparison_error')]:
            with self.subTest(fault=fault):
                inv = fixture.prepare(self.source(), [0, 1, 2, 3, 4, 5], [-99, 77])
                cb = fixture.Callbacks(fault=fault)
                result = fixture.checked_call(inv, cb, scratch_capacity=6)
                self.assertEqual(result.completion, completion)
                self.assertIsNone(result.status)
                self.assertIsNone(result.state)
                self.assertEqual(cb.freed, cb.allocated)
                self.assertLess(cb.events.index('free:6'), cb.events.index('timer_end'))
                if fault in ('acquire', 'partial_acquire', 'mismatch', 'input_mutation'):
                    self.assertLess(cb.events.index('timer_end'), cb.events.index('acquire'))
                if fault in ('acquire', 'partial_acquire'):
                    self.assertNotIn('compare', cb.events)

    def test_preflight_protocol_contradiction_is_not_source_rejection(self):
        for value in [-2, 6, True, 0.0]:
            with self.subTest(value=value):
                inv = fixture.prepare(self.source(), [0]*6, [8, 9])
                cb = fixture.Callbacks(preflight_result=value)
                result = fixture.checked_call(inv, cb, scratch_capacity=6)
                self.assertEqual(result.completion, 'process_error')
                self.assertIsNone(result.status)
                self.assertEqual(inv.output.data, [8, 9])
                self.assertEqual(cb.allocations, [])

    def test_hand_reviewed_fixture_expected_states(self):
        cases = json.loads((FIXTURES / 'tiny-1x2-cases.json').read_text())
        for case in cases:
            with self.subTest(case=case['name']):
                _, _, result = self.invoke(case['input'], case['initial_output'], scratch_capacity=6)
                self.assertEqual(dataclasses.asdict(result), {
                    'completion': 'complete', 'status': case['status'],
                    'first_bad_index': case['first_bad_index'],
                    'state': (tuple(case['input']), tuple(case['final_output']))})
        core = (FIXTURES / 'tiny-1x2.be').read_text()
        self.assertIn('fn ax_preflight(let input: List<i32>) -> i32', core)
        self.assertIn('fn ax_body(let input: List<i32>, inout output: List<i32>,', core)
        self.assertIn('inout scratch: List<i32>)', core)

    def test_executable_bad_adapter_controls_are_detected(self):
        # These candidates really call allocation/body and mutate output; no prose scan.
        for mutation in ['scratch_before_preflight', 'caller_validation_bit', 'used_capacity']:
            with self.subTest(mutation=mutation):
                with self.assertRaises(AssertionError):
                    fixture.exercise_control(mutation)


if __name__ == '__main__':
    unittest.main()
