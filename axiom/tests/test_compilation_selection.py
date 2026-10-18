"""Ranked proof policy: actual streams, terminal states and conserved work."""
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
import unittest
from unittest.mock import patch
from axiom import checker, codec, compilation, compilation_selection as ranked, selection
from axiom.model import ConstraintStatus, DiagnosticError, Limits, Objective, SemanticStatus
from axiom.planner import PLAN_IDS, make_plan
from tests.helpers import stencil_source


class RankedSelectionTests(unittest.TestCase):
    def context(self, h=5, w=7, cap=64, objective='multiplication_ops', limits=Limits()):
        return compilation._CompilationContext(stencil_source(h, w, cap, objective), limits)

    def select(self, context=None, total=100000):
        return ranked._select_ranked(context or self.context(), total)

    def assert_no_artifact(self, result, owned):
        self.assertIsNone(owned)
        self.assertEqual((result.selected_plan, result.selected_plan_bytes, result.selected_check), (None, None, None))
        self.assertFalse(result.portfolio_optimal)
        self.assertEqual(result.artifact_state, 'none')
        self.assertEqual(result.total_work_used, sum(a.work_used for a in result.attempts))
        self.assertLessEqual(result.total_work_used, result.total_check_steps)

    def test_one_real_proof_three_validations_one_encoding_no_decode(self):
        with patch.object(compilation, '_check_admitted_plan', wraps=checker._check_admitted_plan) as checked, \
             patch.object(compilation, '_validate_plan', wraps=codec._validate_plan) as validated, \
             patch.object(compilation, '_encode_validated_plan', wraps=codec._encode_validated_plan) as encoded, \
             patch.object(codec, 'decode_plan', side_effect=AssertionError('internal decode')):
            context = self.context()
            result, owned = self.select(context)
        self.assertEqual((checked.call_count, validated.call_count, encoded.call_count), (1, 3, 1))
        self.assertEqual(result.selected_plan.plan_id, 'rows2-v1')
        self.assertEqual(result.termination_reason, 'completed')
        self.assertTrue(result.portfolio_optimal)
        self.assertIs(owned.checked, result.selected_check)
        self.assertEqual(owned.plan_bytes, result.selected_plan_bytes)
        self.assertEqual(result.selected_plan_bytes, codec.encode_plan(result.selected_plan))
        self.assertEqual([a.state for a in result.attempts], ['not_checked_worse_rank', 'proved_eligible', 'constraint_rejected'])
        self.assertEqual([a.check is not None for a in result.attempts], [False, True, False])
        self.assertEqual(result.total_work_used, result.selected_check.work_used)
        for attempt in result.attempts:
            plan = make_plan(context.kernel, attempt.candidate_id)
            self.assertEqual(attempt.multiplication_ops, sum(op.opcode == 'mul' for op in plan.operations))
            self.assertEqual(attempt.operation_count, len(plan.operations))
            self.assertEqual(attempt.workspace_bytes, 4 * plan.scratch_capacity_cells)
        self.assertIsNone(result.attempts[0].plan_digest)
        self.assertIsNone(result.attempts[2].plan_digest)

    def test_policy_and_frozen_versioned_reports(self):
        result, _ = self.select()
        self.assertEqual(result.policy_id, 'ranked-proof-v1')
        self.assertEqual(result.report_version, 2)
        self.assertEqual(result.policy_digest, '45bbc9ceff403c30f4d1b4fb50e9fd326bed1c1b5cc1cac4f1ca8aae57b94f64')
        self.assertEqual(ranked.ranked_policy_digest(Objective.PLAN_WORKSPACE_BYTES),
                         'f2de163e2f82b4c54d22186fc90d104f3c570ccc52e7977a5062f844644504f7')
        self.assertEqual(result.policy_digest, ranked.ranked_policy_digest(result.objective))
        self.assertNotEqual(result.policy_digest, selection.ranking_digest(result.objective))
        self.assertNotEqual(result.policy_digest, ranked.ranked_policy_digest(Objective.PLAN_WORKSPACE_BYTES))
        self.assertEqual(result.budget_accounting_version, selection.BUDGET_ACCOUNTING_VERSION)
        for record, field in ((result, 'portfolio_optimal'), (result.attempts[0], 'state')):
            with self.assertRaises(FrozenInstanceError):
                setattr(record, field, None)

    def test_named_winners_and_zero_cap_filter(self):
        for h, w, cap, objective, label in ((5,7,0,'multiplication_ops','inline-v1'),
                (5,7,None,'multiplication_ops','rows2-v1'), (5,7,None,'plan_workspace_bytes','inline-v1'),
                (1,1,None,'multiplication_ops','inline-v1'), (1,7,None,'multiplication_ops','materialize-v1')):
            with self.subTest(shape=(h,w), cap=cap, objective=objective):
                result, owned = self.select(self.context(h,w,cap,objective))
                self.assertEqual(result.selected_plan.plan_id, label)
                self.assertIsNotNone(owned)
                self.assertTrue(result.portfolio_optimal)
                self.assertEqual(sum(a.check is not None for a in result.attempts), 1)

    def test_renamed_labels_and_identical_full_key_keep_portfolio_order(self):
        context = self.context(1,7,None)
        labels = {'inline-v1':'zzz', 'rows2-v1':'aaa', 'materialize-v1':'bbb'}
        with patch.object(ranked, 'make_plan', side_effect=lambda k,l: replace(make_plan(k,l), plan_id=labels[l])):
            result, _ = self.select(context)
        self.assertEqual(result.selected_plan.plan_id, 'aaa')
        with patch.object(ranked, 'make_plan', side_effect=lambda k,l: replace(make_plan(k,l), plan_id='equal')):
            result, _ = self.select(context)
        self.assertEqual([a.candidate_id for a in result.attempts if a.state == 'proved_eligible'], ['rows2-v1'])

    def test_labels_never_supply_costs_and_declared_scratch_is_exact(self):
        def misleading(kernel, label):
            plan = make_plan(kernel, 'inline-v1' if label == 'rows2-v1' else 'rows2-v1')
            return replace(plan, plan_id=label, scratch_capacity_cells=plan.scratch_capacity_cells+1)
        with patch.object(ranked, 'make_plan', side_effect=misleading):
            result, _ = self.select(self.context(cap=None))
        self.assertEqual(result.selected_plan.plan_id, 'inline-v1')
        self.assertEqual(result.attempts[0].multiplication_ops, 48)
        self.assertEqual(result.attempts[0].workspace_bytes, 68)
        self.assertEqual(result.attempts[1].workspace_bytes, 4)

    def test_structural_rejection_has_no_receipt_and_proceeds(self):
        def malformed(kernel, label):
            p = make_plan(kernel, label)
            return replace(p, operations=(replace(p.operations[0], dst=True),)+p.operations[1:]) if label == 'rows2-v1' else p
        with patch.object(ranked, 'make_plan', side_effect=malformed):
            result, _ = self.select()
        self.assertEqual(result.selected_plan.plan_id, 'inline-v1')
        self.assertEqual(result.attempts[1].state, 'structurally_rejected')
        self.assertIsNone(result.attempts[1].check)
        self.assertIsNone(result.attempts[1].multiplication_ops)
        self.assertEqual(result.attempts[1].work_used, 0)

    def test_wrong_arithmetic_is_proved_invalid_then_next_is_checked(self):
        def wrong(kernel, label):
            p = make_plan(kernel, label)
            return replace(p, operations=(replace(p.operations[0], value=3),)+p.operations[1:]) if label == 'rows2-v1' else p
        with patch.object(ranked, 'make_plan', side_effect=wrong):
            result, _ = self.select()
        self.assertEqual(result.selected_plan.plan_id, 'inline-v1')
        self.assertEqual(result.attempts[1].state, 'proved_invalid')
        self.assertEqual(result.attempts[1].check.semantic_status, SemanticStatus.INVALID)
        self.assertEqual(result.attempts[0].allowance, 100000-result.attempts[1].work_used)
        self.assertEqual(result.total_work_used, sum(a.work_used for a in result.attempts))

    def test_zero_one_and_exact_success_budget_prefixes(self):
        full, _ = self.select()
        work = full.total_work_used
        for total in (0,1,work-1,work,work+1):
            with self.subTest(total=total):
                result, owned = self.select(total=total)
                self.assertEqual(len(result.attempts), 3)
                if total >= work:
                    self.assertIsNotNone(owned)
                    self.assertTrue(result.portfolio_optimal)
                    self.assertEqual(result.total_work_used, work)
                else:
                    self.assert_no_artifact(result, owned)
                    self.assertEqual(result.termination_reason, 'total_budget_exhausted')
                    self.assertEqual(result.total_work_used, total)
                    self.assertNotIn('not_checked_worse_rank', [a.state for a in result.attempts])
                if total == 0:
                    self.assertTrue(all(a.check is None for a in result.attempts))

    def test_all_resource_unknowns_stop_without_proof_fallback(self):
        cases = ((replace(Limits(),plan_bytes=1),'BYTE_LIMIT'), (replace(Limits(),plan_operations=1),'OPERATION_LIMIT'),
                 (replace(Limits(),expression_nodes=100),'EXPRESSION_NODES_EXHAUSTED'),
                 (replace(Limits(),check_steps=1),'CHECK_STEPS_EXHAUSTED'))
        for limits, reason in cases:
            with self.subTest(reason=reason):
                result, owned = self.select(self.context(limits=limits))
                self.assert_no_artifact(result, owned)
                self.assertEqual(result.reason, reason)
                self.assertEqual(sum(a.check is not None for a in result.attempts), int(reason in ('CHECK_STEPS_EXHAUSTED','EXPRESSION_NODES_EXHAUSTED')))
                self.assertIn('unknown', [a.state for a in result.attempts])
        mutations = (lambda p: replace(p,format_version=2),
                     lambda p: replace(p,operations=(replace(p.operations[0],opcode='future'),)+p.operations[1:]))
        for mutation in mutations:
            with patch.object(ranked,'make_plan',side_effect=lambda k,l: mutation(make_plan(k,l))):
                result, owned = self.select()
            self.assert_no_artifact(result, owned)
            self.assertEqual(result.termination_reason,'unknown')
            self.assertEqual(result.total_work_used,0)

    def test_checker_unknown_even_if_complete_never_gets_bypassed(self):
        original = checker._check_admitted_plan
        for reason in ('INCONCLUSIVE_INTERVAL','STRUCTURAL_MISMATCH','UNSUPPORTED_SOURCE_EXPRESSION'):
            def inconclusive(*args, **kwargs):
                return replace(original(*args,**kwargs),semantic_status=SemanticStatus.UNKNOWN,reason=reason)
            with self.subTest(reason=reason), patch.object(compilation,'_check_admitted_plan',side_effect=inconclusive) as checked:
                result, owned = self.select()
                self.assert_no_artifact(result,owned)
                self.assertEqual(result.termination_reason,'unknown')
                self.assertEqual(checked.call_count,1)

    def test_exception_without_receipt_consumes_call_allowance(self):
        for failure, stop in ((RuntimeError('failed'),'checker_error'),(KeyboardInterrupt(),'cancelled')):
            with self.subTest(failure=type(failure).__name__), patch.object(compilation,'_check_admitted_plan',side_effect=failure):
                result, owned = self.select(total=71)
                self.assert_no_artifact(result,owned)
                self.assertEqual(result.termination_reason,stop)
                self.assertEqual(result.total_work_used,71)
                self.assertEqual(result.attempts[1].allowance,71)
                self.assertIsNone(result.attempts[1].check)

    def test_generation_errors_prevent_any_proof_even_for_worse_candidate(self):
        for fail_at in PLAN_IDS:
            for failure, stop in ((RuntimeError('generation'),'candidate_error'),(KeyboardInterrupt(),'cancelled')):
                def fail(kernel,label):
                    if label == fail_at:
                        raise failure
                    return make_plan(kernel,label)
                with self.subTest(fail_at=fail_at,stop=stop), patch.object(ranked,'make_plan',side_effect=fail), \
                     patch.object(compilation,'_check_admitted_plan',side_effect=AssertionError('must not check')):
                    result, owned = self.select()
                self.assert_no_artifact(result,owned)
                self.assertEqual(result.termination_reason,stop)
                self.assertEqual(result.total_work_used,0)

    def test_cancellation_at_validation_encoding_and_authorization(self):
        for method, expected_work in (('candidate',0),('_encoding',0),('authorize',None)):
            with self.subTest(method=method), patch.object(compilation._CompilationContext,method,side_effect=KeyboardInterrupt()):
                result, owned = self.select()
            self.assert_no_artifact(result,owned)
            self.assertEqual(result.termination_reason,'cancelled')
            if expected_work is not None:
                self.assertEqual(result.total_work_used,expected_work)
            else:
                self.assertGreater(result.total_work_used,0)

    def test_malformed_receipts_and_corrupt_complete_metrics_fail_closed(self):
        original = checker._check_admitted_plan
        mutations = (lambda r: None, lambda r: True,
            lambda r: replace(r,work_used=True),lambda r: replace(r,work_used=100001),
            lambda r: replace(r,source_digest='0'*64),lambda r: replace(r,plan_digest='0'*64),
            lambda r: replace(r,constraint_digest='0'*64),lambda r: replace(r,effective_cap=None),
            lambda r: replace(r,multiplication_ops=r.multiplication_ops+1),lambda r: replace(r,multiplication_ops=True),
            lambda r: replace(r,workspace_bytes=r.workspace_bytes+4),lambda r: replace(r,opcode_counts=(('mul',r.multiplication_ops),)))
        for mutation in mutations:
            with self.subTest(mutation=mutation), patch.object(compilation,'_check_admitted_plan',side_effect=lambda *a,**kw: mutation(original(*a,**kw))):
                result, owned = self.select()
            self.assert_no_artifact(result,owned)
            self.assertEqual(result.termination_reason,'checker_error')

    def test_all_invalid_candidates_are_conclusively_ineligible(self):
        with patch.object(ranked,'make_plan',side_effect=lambda k,l: replace(make_plan(k,l),semantic_digest='0'*64)):
            result, owned = self.select(self.context(cap=None))
        self.assert_no_artifact(result,owned)
        self.assertEqual(result.termination_reason,'no_eligible_candidate')
        self.assertTrue(all(a.state == 'proved_invalid' for a in result.attempts))

    def test_request_validation_and_closed_context(self):
        for total in (-1,True,False,1.0,None,'1'):
            with self.subTest(total=total), self.assertRaises(ValueError):
                self.select(total=total)
        context = self.context()
        context.close()
        with self.assertRaises(ValueError):
            self.select(context)

    def test_invalid_then_exception_charges_only_remaining_shared_allowance(self):
        original = checker._check_admitted_plan
        calls = []
        def fail_second(*args, **kwargs):
            calls.append(args[2].check_steps)
            if len(calls) == 2:
                raise RuntimeError('second proof')
            return original(*args, **kwargs)
        def invalid_best(k, label):
            plan = make_plan(k, label)
            return replace(plan, semantic_digest='0'*64) if label == 'rows2-v1' else plan
        # An identity-invalid first candidate has a real zero-work receipt; a
        # wrong-arithmetic candidate below spends nonzero source/stream work.
        def arithmetic_invalid(k, label):
            plan = invalid_best(k, label)
            if label == 'rows2-v1':
                plan = replace(plan, semantic_digest=k.semantic_digest,
                    operations=(replace(plan.operations[0], value=3),)+plan.operations[1:])
            return plan
        with patch.object(ranked, 'make_plan', side_effect=arithmetic_invalid), \
             patch.object(compilation, '_check_admitted_plan', side_effect=fail_second):
            result, owned = self.select(total=10000)
        self.assert_no_artifact(result, owned)
        self.assertEqual(result.termination_reason, 'checker_error')
        self.assertEqual(result.total_work_used, 10000)
        self.assertEqual(calls, [10000, 10000-result.attempts[1].work_used])
        self.assertGreater(result.attempts[1].work_used, 0)
        self.assertEqual(result.attempts[0].work_used, result.attempts[0].allowance)

    def test_source_expression_quota_exact_boundary(self):
        allocations = 0
        original = checker._Expressions.allocate
        def count(arena, node):
            nonlocal allocations
            allocations += 1
            return original(arena, node)
        with patch.object(checker._Expressions, 'allocate', count):
            result, owned = self.select(self.context(2, 2, None))
        self.assertIsNotNone(owned)
        self.assertGreater(allocations, 100)
        with self.assertRaises(DiagnosticError):
            self.context(2, 2, None, limits=replace(Limits(), expression_nodes=1))
        for quota in (allocations-1, allocations, allocations+1):
            with self.subTest(quota=quota):
                result, owned = self.select(self.context(2, 2, None,
                    limits=replace(Limits(), expression_nodes=quota)))
                if quota < allocations:
                    self.assert_no_artifact(result, owned)
                    self.assertEqual(result.reason, 'EXPRESSION_NODES_EXHAUSTED')
                else:
                    self.assertIsNotNone(owned)
                    self.assertTrue(result.portfolio_optimal)

    def test_dead_multiplications_are_counted_and_proved(self):
        def with_dead_mul(k, label):
            plan = make_plan(k, label)
            if label == 'rows2-v1':
                dst = sum(op.dst is not None for op in plan.operations)
                from axiom.plan_format import Operation
                plan = replace(plan, operations=plan.operations+(Operation('mul', dst, (0, 0)),))
            return plan
        with patch.object(ranked, 'make_plan', side_effect=with_dead_mul):
            result, owned = self.select(self.context(cap=None))
        self.assertIsNotNone(owned)
        self.assertEqual(result.selected_plan.plan_id, 'materialize-v1')
        self.assertEqual(result.attempts[1].multiplication_ops, 49)
        self.assertEqual(result.attempts[2].multiplication_ops, 48)

    def test_real_structural_mismatch_is_unknown_even_with_complete_metrics(self):
        def reordered(k, label):
            plan = make_plan(k, label)
            if label == 'rows2-v1':
                operations = list(plan.operations)
                index = next(i for i, op in enumerate(operations) if op.opcode == 'add')
                operations[index] = replace(operations[index],
                    operands=tuple(reversed(operations[index].operands)))
                plan = replace(plan, operations=tuple(operations))
            return plan
        with patch.object(ranked, 'make_plan', side_effect=reordered):
            result, owned = self.select()
        self.assert_no_artifact(result, owned)
        self.assertEqual(result.reason, 'STRUCTURAL_MISMATCH')
        self.assertEqual(result.termination_reason, 'unknown')
        self.assertTrue(result.attempts[1].check.check_complete)
        self.assertEqual(result.attempts[1].state, 'unknown')
        self.assertEqual(result.attempts[0].state, 'not_checked')
        self.assertIsNone(result.attempts[0].check)

    def test_budget_prefixes_after_real_invalid_candidate_do_not_restart_work(self):
        def wrong(k, label):
            plan = make_plan(k, label)
            if label == 'rows2-v1':
                plan = replace(plan, operations=(replace(plan.operations[0], value=3),)+plan.operations[1:])
            return plan
        with patch.object(ranked, 'make_plan', side_effect=wrong):
            complete, _ = self.select()
            invalid_work = complete.attempts[1].work_used
            for budget in (invalid_work, invalid_work+1, complete.total_work_used-1, complete.total_work_used):
                with self.subTest(budget=budget):
                    result, owned = self.select(total=budget)
                    if budget == complete.total_work_used:
                        self.assertTrue(result.portfolio_optimal)
                        self.assertIsNotNone(owned)
                    else:
                        self.assert_no_artifact(result, owned)
                        self.assertEqual(result.termination_reason, 'total_budget_exhausted')
                    self.assertEqual(result.total_work_used, budget)
                    self.assertEqual(result.attempts[1].work_used, invalid_work)
                    if budget > invalid_work:
                        self.assertEqual(result.attempts[0].allowance, budget-invalid_work)

    def test_later_cap_infeasible_candidate_resource_failure_still_stops(self):
        # Inline is valid within this quota and cap; the next stream exceeds the
        # operation quota even though its reservation also exceeds the cap.
        context = self.context(1, 1, 0, limits=replace(Limits(), plan_operations=17))
        with patch.object(compilation, '_check_admitted_plan', side_effect=AssertionError('must not prove')):
            result, owned = self.select(context)
        self.assert_no_artifact(result, owned)
        self.assertEqual(result.reason, 'OPERATION_LIMIT')
        self.assertEqual(result.attempts[0].state, 'not_checked')
        self.assertEqual(result.attempts[1].state, 'unknown')
        self.assertEqual(result.total_work_used, 0)

    def test_all_structural_rejections_need_no_semantic_allowance(self):
        with patch.object(ranked, 'make_plan', return_value=None):
            result, owned = self.select(total=0)
        self.assert_no_artifact(result, owned)
        self.assertEqual(result.termination_reason, 'no_eligible_candidate')
        self.assertEqual([a.state for a in result.attempts], ['structurally_rejected']*3)
        self.assertTrue(all(a.check is None and a.allowance == 0 for a in result.attempts))


class ExhaustiveRankedSelectionTests(unittest.TestCase):
    def test_all_955_shapes_and_14518_contexts_equal_legacy_bytes(self):
        # Real independent semantic checks for all three streams of each shape.
        # Across cap/objective contexts only, reuse those receipts after exact
        # immutable stream equality and rebuild the complete context binding.
        # This adapter is exclusively test infrastructure, never a proof cache.
        shapes = contexts = 0
        for h in range(1, 128):
            for w in range(1, 128):
                if (h+1)*(w+1) > 256:
                    continue
                shapes += 1
                base_context = compilation._CompilationContext(stencil_source(h, w, None))
                kernel = base_context.kernel
                encoded = {}
                def capture(plan, *, limits):
                    data = codec.encode_plan(plan, limits=limits)
                    encoded[plan.plan_id] = data
                    return data
                with patch.object(selection, 'encode_plan', side_effect=capture):
                    base = selection.select_plan(kernel, Limits(), 100000, kernel.objective)
                self.assertEqual(len(base.attempts), 3, (h, w, base.reason))
                records = {a.candidate_id: a.check for a in base.attempts}
                streams = {label: make_plan(kernel, label) for label in records}
                self.assertTrue(all(record.eligible for record in records.values()))

                def context_check(k, plan, limits):
                    self.assertEqual(plan, streams[plan.plan_id])
                    receipt = records[plan.plan_id]
                    self.assertGreaterEqual(limits.check_steps, receipt.work_used)
                    satisfied = k.cap is None or receipt.workspace_bytes <= k.cap
                    digest = sha256(codec.canonical_json({'version':1,
                        'property':'plan_workspace_bytes', 'source_cap':k.cap,
                        'additional_cap':None, 'effective_cap':k.cap})).hexdigest()
                    return replace(receipt, source_digest=k.source_digest, effective_cap=k.cap,
                        constraint_digest=digest,
                        constraint_status=ConstraintStatus.SATISFIED if satisfied else ConstraintStatus.VIOLATED)

                def owned_context_check(k, plan, limits, identity, *, additional_cap=None):
                    self.assertIsNone(additional_cap)
                    self.assertEqual(identity, records[plan.plan_id].plan_digest)
                    return context_check(k, plan, limits)

                def context_encoding(plan, limits):
                    self.assertEqual(plan, streams[plan.plan_id])
                    self.assertLessEqual(len(encoded[plan.plan_id]), limits.plan_bytes)
                    return encoded[plan.plan_id]

                row_bytes, material_bytes = 8*(w+1), 4*(h+1)*(w+1)
                caps = sorted({0,row_bytes-1,row_bytes,row_bytes+1,
                               material_bytes-1,material_bytes,material_bytes+1})+[None]
                with patch.object(selection, 'check_plan', side_effect=context_check), \
                     patch.object(selection, 'encode_plan', side_effect=context_encoding), \
                     patch.object(compilation, '_check_admitted_plan', side_effect=owned_context_check), \
                     patch.object(compilation, '_encode_validated_plan', side_effect=context_encoding):
                    for objective in Objective:
                        for cap in caps:
                            contexts += 1
                            context = compilation._CompilationContext(stencil_source(h,w,cap,objective.value))
                            expected = selection.select_plan(context.kernel, context.limits, 100000, objective)
                            actual, owned = ranked._select_ranked(context, 100000)
                            self.assertIsNotNone(owned, (h,w,cap,objective,actual.reason))
                            self.assertTrue(actual.portfolio_optimal)
                            self.assertEqual(actual.selected_plan, expected.selected_plan)
                            self.assertEqual(actual.selected_plan_bytes, expected.selected_plan_bytes)
                            self.assertEqual(actual.selected_check, expected.selected_check)
                            self.assertEqual(actual.selected_key, expected.selected_key)
                            self.assertEqual(sum(a.check is not None for a in actual.attempts), 1)
                            context.close()
                base_context.close()
        self.assertEqual(shapes, 955)
        self.assertEqual(contexts, 14518)


if __name__ == '__main__':
    unittest.main()
