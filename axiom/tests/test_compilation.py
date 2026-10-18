"""Owned compilation retains proof without admitting caller-created authority."""
from dataclasses import replace
from hashlib import sha256
import unittest
from unittest.mock import patch
from axiom import compilation, checker, codec, frontend
from axiom.model import Limits
from axiom.native_codegen import emit_native_c, _emit_native_c_checked
from axiom.wasm import compile_wasm, _compile_wasm_checked
from axiom.planner import make_plan
from axiom.selection import select_plan
from tests.helpers import stencil_source

class CompilationTests(unittest.TestCase):
    def owned(self, source=None):
        context = compilation._CompilationContext(source or stencil_source(1, 2, None), Limits())
        report, owned = compilation._select_legacy(context, 100000)
        return context, report, owned

    def test_legacy_receipts_and_bytes_are_identical(self):
        for h, w, cap in ((1, 1, 64), (5, 7, 64), (1, 7, None)):
            source = stencil_source(h, w, cap)
            context, actual, owned = self.owned(source)
            expected = select_plan(context.kernel, context.limits, 100000, context.kernel.objective)
            self.assertEqual(actual, expected)
            self.assertEqual(owned.plan_bytes, expected.selected_plan_bytes)
            self.assertEqual(_emit_native_c_checked(owned), emit_native_c(source, owned.plan_bytes))
            self.assertEqual(_compile_wasm_checked(owned), compile_wasm(source, owned.plan_bytes))

    def test_one_admission_one_validation_per_candidate_no_backend_recheck(self):
        with patch.object(compilation, 'parse_source', wraps=frontend.parse_source) as parsed, \
             patch.object(compilation, '_validate_plan', wraps=codec._validate_plan) as validated, \
             patch.object(checker, 'parse_source', side_effect=AssertionError('readmitted')), \
             patch.object(codec, 'decode_plan', side_effect=AssertionError('decoded')):
            context, report, owned = self.owned()
            _emit_native_c_checked(owned)
            _compile_wasm_checked(owned)
        self.assertEqual(parsed.call_count, 1)
        self.assertEqual(validated.call_count, 3)

    def test_cross_context_candidate_and_receipt_substitution_rejected(self):
        a, _, owned = self.owned()
        b, _, other = self.owned(stencil_source(2, 1, None))
        with self.assertRaises(ValueError):
            b.check(owned.candidate)
        with self.assertRaises(ValueError):
            a.authorize(owned.candidate, other.checked)
        with self.assertRaises(ValueError):
            a.authorize(owned.candidate, replace(owned.checked))
        with self.assertRaises(ValueError):
            _compile_wasm_checked(replace(owned, plan=other.plan))

    def test_close_invalidates_owned_artifact(self):
        context, _, owned = self.owned()
        context.close()
        with self.assertRaises(ValueError):
            _compile_wasm_checked(owned)
        with self.assertRaises(ValueError):
            context.candidate(owned.plan)

    def test_external_identity_keeps_raw_bytes(self):
        context, _, owned = self.owned()
        spaced = b' ' + owned.plan_bytes
        external = compile_wasm(context.source, spaced)
        self.assertEqual(external.module_bytes, _compile_wasm_checked(owned).module_bytes)
        self.assertEqual(external.plan_digest, sha256(spaced).hexdigest())
        self.assertNotEqual(external.plan_digest, owned.checked.plan_digest)

    def test_check_allowance_receipts_match_public_cutpoints(self):
        context = compilation._CompilationContext(stencil_source(1, 1, None), Limits())
        candidate = context.candidate(make_plan(context.kernel, 'inline-v1'))
        for allowance in (1, 10, 50, 100, 1000):
            actual = context.check(candidate, allowance)
            expected = checker.check_plan(context.kernel, candidate.plan,
                                          replace(context.limits, check_steps=allowance))
            self.assertEqual(actual, expected)

    def test_forged_limits_are_revalidated(self):
        bad = Limits()
        object.__setattr__(bad, 'expression_nodes', True)
        with self.assertRaises(ValueError):
            compilation._CompilationContext(stencil_source(1, 1, None), bad)

    def test_lazy_encoding_and_actual_metrics(self):
        context = compilation._CompilationContext(stencil_source(1, 2, None), Limits())
        plan = make_plan(context.kernel, 'rows2-v1')
        with patch.object(compilation, '_encode_validated_plan', wraps=codec._encode_validated_plan) as encoded:
            candidate = context.candidate(plan)
            self.assertEqual(encoded.call_count, 0)
            self.assertEqual(candidate.multiplication_ops, sum(op.opcode == 'mul' for op in plan.operations))
            self.assertEqual(candidate.workspace_bytes, 4 * plan.scratch_capacity_cells)
            checked = context.check(candidate)
            owned = context.authorize(candidate, checked)
            self.assertEqual(candidate.plan_bytes, owned.plan_bytes)
            self.assertEqual(encoded.call_count, 1)

    def test_limits_source_and_check_substitution_cannot_authorize(self):
        context, _, owned = self.owned()
        for changed in (replace(owned, limits=Limits(check_steps=1)),
                        replace(owned, source=stencil_source(2, 1, None)),
                        replace(owned, checked=replace(owned.checked, effective_cap=0))):
            with self.assertRaises(ValueError):
                _emit_native_c_checked(changed)
        with self.assertRaises(AttributeError):
            context.limits = Limits(check_steps=1)
        with self.assertRaises(ValueError):
            context.check(owned.candidate, context.limits.check_steps + 1)

    def test_legacy_low_budget_and_optional_receipts_unchanged(self):
        source = stencil_source(1, 2, None)
        for total, optional in ((0, None), (1, None), (200, None), (100000, 0), (100000, 1)):
            context = compilation._CompilationContext(source)
            report, owned = compilation._select_legacy(context, total, optional)
            expected = select_plan(context.kernel, context.limits, total, context.kernel.objective, optional)
            self.assertEqual(report, expected)
            self.assertEqual(owned is None, report.selected_plan is None)

    def test_public_emission_always_checks_afresh(self):
        context, _, owned = self.owned()
        with patch.object(checker, '_check_plan', wraps=checker._check_plan) as checks:
            emit_native_c(context.source, owned.plan_bytes)
            compile_wasm(context.source, owned.plan_bytes)
        self.assertEqual(checks.call_count, 2)
        self.assertTrue(all(not call.kwargs.get('_admitted') for call in checks.call_args_list))

    def test_preparation_failure_and_emission_cancellation_expire_context(self):
        from axiom import playground_service as service
        source = stencil_source(1, 1, None).decode()
        self.assertEqual(service.prepare_compiled_demo(source)['status'], 'prepared')
        previous = service._active_preparation.context
        self.assertEqual(service.prepare_compiled_demo('invalid')['status'], 'error')
        with self.assertRaises(ValueError):
            previous.candidate(make_plan(previous.kernel, 'inline-v1'))
        captured = []
        def cancel(owned):
            captured.append(owned)
            raise KeyboardInterrupt()
        with patch.object(service, '_compile_wasm_checked', side_effect=cancel), self.assertRaises(KeyboardInterrupt):
            service.prepare_compiled_demo(source)
        self.assertIsNone(service._active_preparation)
        with self.assertRaises(ValueError):
            _compile_wasm_checked(captured[0])

    def test_trace_counts_handoff_without_internal_decode(self):
        from axiom.compilation_trace import CompilationTrace
        from axiom.playground_service import prepare_compiled_demo
        trace = CompilationTrace()
        result = prepare_compiled_demo(stencil_source(1, 1, None).decode(), trace=trace)
        self.assertEqual(result['status'], 'prepared')
        report = trace.report()
        self.assertEqual(report['counts']['source_admissions'], 1)
        self.assertEqual(report['counts']['plan_validations'], 3)
        self.assertEqual(report['counts']['plan_encodes'], 3)
        self.assertEqual(report['counts']['semantic_checks'], 3)
        self.assertEqual(report['counts'].get('internal_decodes', 0), 0)
        self.assertEqual(report['phases']['code_emission']['calls'], 1)
        self.assertEqual(report['phases']['semantic_checking']['calls'], 3)
        self.assertEqual(report['phases']['total_fresh_source_preparation']['calls'], 1)

    def test_structural_failure_legacy_receipt_is_identical_without_revalidation(self):
        from axiom import selection, planner
        context = compilation._CompilationContext(stencil_source(1, 1, None))
        malformed = replace(make_plan(context.kernel, 'inline-v1'), operations=[])
        with patch.object(selection, 'make_plan', return_value=malformed):
            expected = select_plan(context.kernel, context.limits, 100000, context.kernel.objective)
        with patch.object(planner, 'make_plan', return_value=malformed), \
             patch.object(compilation, '_validate_plan', wraps=codec._validate_plan) as validation:
            actual, owned = compilation._select_legacy(context, 100000)
        self.assertEqual(actual, expected)
        self.assertIsNone(owned)
        self.assertEqual(validation.call_count, 1)

    def test_owned_runtime_preserves_full_preflight_and_initial_output(self):
        from axiom.runtime import _execute_checked, execute_plan
        context, _, owned = self.owned()
        for data in ([1, 2, 3, 4, 5, 6], [1, -1, 3, 4, 5, 1024]):
            initial = [-9, 17]
            self.assertEqual(_execute_checked(owned, data, initial),
                             execute_plan(context.source, owned.plan_bytes, data, initial))
            self.assertEqual(initial, [-9, 17])

    def test_additional_cap_keeps_exact_public_receipts(self):
        context = compilation._CompilationContext(stencil_source(1, 2, 64))
        candidate = context.candidate(make_plan(context.kernel, 'rows2-v1'))
        for cap in (None, 0, 24, 64, 100):
            self.assertEqual(context.check(candidate, additional_cap=cap),
                             checker.check_plan(context.kernel, candidate.plan, context.limits,
                                                additional_cap=cap))
        with self.assertRaises(ValueError):
            context.check(candidate, additional_cap=True)
