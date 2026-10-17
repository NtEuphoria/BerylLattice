"""Portfolio ranking, fresh eligibility, deterministic work and interruptions."""
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
import unittest
from unittest.mock import patch
from axiom import selection
from axiom.checker import check_plan
from axiom.codec import canonical_json, encode_plan
from axiom.frontend import admit_source, parse_source
from axiom.model import ConstraintStatus, Limits, Objective, SemanticStatus
from axiom.planner import make_plan
from tests.helpers import stencil_source


def admitted(h=5, w=7, cap=64, objective='multiplication_ops'):
    return admit_source(parse_source(stencil_source(h, w, cap, objective)))


def analytic(h, w, cap, objective):
    costs = [(4*h*w, 0, 'inline-v1'), ((h+1)*(w+1), 8*(w+1), 'rows2-v1'),
             ((h+1)*(w+1), 4*(h+1)*(w+1), 'materialize-v1')]
    feasible = [item for item in costs if cap is None or item[1] <= cap]
    if objective == Objective.PLAN_WORKSPACE_BYTES:
        return min((arena, muls, label) for muls, arena, label in feasible)[2]
    return min(feasible)[2]


class SelectionTests(unittest.TestCase):
    def select(self, k=None, total=100000, optional=None, limits=Limits()):
        k = admitted() if k is None else k
        return selection.select_plan(k, limits, total, k.objective, optional)

    def assert_coherent(self, result, kernel):
        self.assertIsNotNone(result.selected_plan)
        self.assertTrue(result.selected_check.eligible)
        self.assertEqual(result.selected_plan_bytes, encode_plan(result.selected_plan))
        self.assertEqual(sha256(result.selected_plan_bytes).hexdigest(), result.selected_check.plan_digest)
        self.assertEqual(result.selected_check.source_digest, kernel.source_digest)
        self.assertEqual(result.artifact_state, 'available')
        self.assertEqual(sum(a.work_used for a in result.attempts), result.total_work_used)
        self.assertLessEqual(result.total_work_used, result.total_check_steps)

    def test_named_rankings_and_materialize_cap_violation(self):
        for h, w, cap, objective, label in [
            (5, 7, 0, 'multiplication_ops', 'inline-v1'),
            (5, 7, 64, 'multiplication_ops', 'rows2-v1'),
            (5, 7, None, 'multiplication_ops', 'rows2-v1'),
            (5, 7, None, 'plan_workspace_bytes', 'inline-v1'),
            (1, 1, None, 'multiplication_ops', 'inline-v1'),
            (1, 7, None, 'multiplication_ops', 'materialize-v1')]:
            with self.subTest(h=h, w=w, cap=cap, objective=objective):
                k = admitted(h, w, cap, objective)
                result = self.select(k)
                self.assert_coherent(result, k)
                self.assertEqual(result.selected_plan.plan_id, label)
                self.assertEqual(result.termination_reason, 'completed')
                if (h, w, cap) == (5, 7, 64):
                    self.assertEqual(result.attempts[2].check.constraint_status, ConstraintStatus.VIOLATED)
                    self.assertEqual(result.attempts[2].check.workspace_bytes, 192)

    def test_zero_total_never_calls_checker_and_has_no_artifact(self):
        with patch.object(selection, 'check_plan', side_effect=AssertionError('must not check')):
            result = self.select(total=0)
        self.assertEqual(result.termination_reason, 'total_budget_exhausted')
        self.assertEqual(result.attempts, ())
        self.assertEqual(result.total_work_used, 0)
        self.assertEqual((result.selected_plan, result.selected_plan_bytes, result.selected_check), (None, None, None))
        self.assertEqual(result.artifact_state, 'none')

    def test_exact_inline_budget_and_optional_zero_do_not_waive_admission(self):
        k = admitted()
        work = check_plan(k, make_plan(k, 'inline-v1'), Limits()).work_used
        exact = self.select(k, total=work)
        self.assert_coherent(exact, k)
        self.assertEqual(exact.selected_plan.plan_id, 'inline-v1')
        self.assertEqual(exact.termination_reason, 'total_budget_exhausted')
        self.assertEqual(len(exact.attempts), 1)
        self.assertEqual(exact.total_work_used, work)
        zero = self.select(k, optional=0)
        self.assert_coherent(zero, k)
        self.assertEqual(zero.termination_reason, 'optional_budget_exhausted')
        self.assertEqual(zero.optional_work_used, 0)
        insufficient = self.select(k, total=work-1, optional=0)
        self.assertIsNone(insufficient.selected_plan)
        self.assertEqual(insufficient.attempts[0].check.reason, 'CHECK_STEPS_EXHAUSTED')
        self.assertFalse(insufficient.attempts[0].check.check_complete)
        self.assertEqual(insufficient.total_work_used, work-1)
        self.assertNotIn('infeasible', insufficient.reason.lower())

    def test_exact_optional_budget_commits_improved_incumbent(self):
        k = admitted()
        row_work = check_plan(k, make_plan(k, 'rows2-v1'), Limits()).work_used
        result = self.select(k, optional=row_work)
        self.assert_coherent(result, k)
        self.assertEqual(result.selected_plan.plan_id, 'rows2-v1')
        self.assertEqual(result.optional_work_used, row_work)
        self.assertEqual(result.termination_reason, 'optional_budget_exhausted')
        self.assertEqual(len(result.attempts), 2)

    def test_initial_constraint_failure_stops_before_optional_candidates(self):
        k = admitted(cap=0)
        def extra_scratch(kernel, label):
            self.assertEqual(label, 'inline-v1')
            return replace(make_plan(kernel, label), scratch_capacity_cells=1)
        with patch.object(selection, 'make_plan', side_effect=extra_scratch):
            result = self.select(k)
        self.assertEqual(result.termination_reason, 'initial_ineligible')
        self.assertEqual(result.reason, 'CONSTRAINT_VIOLATED')
        self.assertEqual(len(result.attempts), 1)
        self.assertTrue(result.attempts[0].check.check_complete)
        self.assertEqual(result.attempts[0].check.semantic_status, SemanticStatus.VALID)
        self.assertEqual(result.attempts[0].check.constraint_status, ConstraintStatus.VIOLATED)
        self.assertIsNone(result.selected_plan)

    def test_positive_per_call_limit_and_remaining_optional_are_both_enforced(self):
        k = admitted()
        work = check_plan(k, make_plan(k, 'inline-v1'), Limits()).work_used
        with patch.object(selection, 'check_plan', wraps=check_plan) as checker:
            result = self.select(k, optional=3, total=work+2)
        self.assert_coherent(result, k)
        self.assertEqual([call.args[2].check_steps for call in checker.call_args_list], [work+2, 2])
        self.assertEqual(result.optional_work_used, 2)
        self.assertEqual(result.total_work_used, work+2)
        result = self.select(k, limits=replace(Limits(), check_steps=work-1))
        self.assertIsNone(result.selected_plan)
        self.assertEqual(result.attempts[0].allowance, work-1)
        self.assertEqual(result.total_work_used, work-1)

    def test_later_invalid_or_unknown_candidate_cannot_replace_incumbent(self):
        k = admitted()
        def wrong(kernel, label):
            p = make_plan(kernel, label)
            if label == 'rows2-v1':
                return replace(p, semantic_digest='0'*64)
            if label == 'materialize-v1':
                return replace(p, operations=p.operations + (p.operations[-1],)*20000)
            return p
        with patch.object(selection, 'make_plan', side_effect=wrong):
            result = self.select(k)
        self.assert_coherent(result, k)
        self.assertEqual(result.selected_plan.plan_id, 'inline-v1')
        self.assertEqual(result.attempts[1].check.semantic_status, SemanticStatus.INVALID)
        self.assertEqual(result.attempts[2].check.semantic_status, SemanticStatus.UNKNOWN)
        self.assertNotIn('infeasible', result.reason.lower())

    def test_checker_exception_and_cancellation_keep_only_committed_incumbent(self):
        for failure, stop in [(RuntimeError('checker failed'), 'checker_error'),
                              (KeyboardInterrupt(), 'cancelled')]:
            for fail_at in (0, 1, 2):
                with self.subTest(failure=type(failure).__name__, fail_at=fail_at):
                    calls = 0
                    def interrupted(kernel, plan, limits):
                        nonlocal calls
                        calls += 1
                        if calls == fail_at+1:
                            raise failure
                        return check_plan(kernel, plan, limits)
                    k = admitted()
                    with patch.object(selection, 'check_plan', side_effect=interrupted):
                        result = self.select(k)
                    self.assertEqual(result.termination_reason, stop)
                    self.assertLessEqual(result.total_work_used, 100000)
                    self.assertEqual(result.attempts[-1].work_used, result.attempts[-1].allowance)
                    if fail_at:
                        self.assert_coherent(result, k)
                        self.assertEqual(result.selected_plan.plan_id, 'inline-v1' if fail_at == 1 else 'rows2-v1')
                    else:
                        self.assertIsNone(result.selected_plan)

    def test_cancel_during_generation_keeps_incumbent_without_spending_check_work(self):
        def interrupted(k, label):
            if label == 'rows2-v1':
                raise KeyboardInterrupt()
            return make_plan(k, label)
        with patch.object(selection, 'make_plan', side_effect=interrupted):
            result = self.select()
        self.assert_coherent(result, admitted())
        self.assertEqual(result.termination_reason, 'cancelled')
        self.assertEqual(result.attempts[-1].work_used, 0)

    def test_labels_do_not_change_legality_but_break_equal_metric_ties(self):
        k = admitted(1, 7, None)
        names = {'inline-v1': 'zzz', 'rows2-v1': 'aaa', 'materialize-v1': 'bbb'}
        def renamed(kernel, label):
            return replace(make_plan(kernel, label), plan_id=names[label])
        with patch.object(selection, 'make_plan', side_effect=renamed):
            result = self.select(k)
        self.assert_coherent(result, k)
        self.assertTrue(all(a.check.eligible for a in result.attempts))
        self.assertEqual(result.selected_plan.plan_id, 'aaa')
        self.assertEqual(tuple(a.candidate_id for a in result.attempts), ('inline-v1', 'rows2-v1', 'materialize-v1'))

    def test_request_validation_and_frozen_receipts(self):
        k = admitted()
        for bad in (-1, True, False, 1.0, '1', None):
            with self.subTest(total=bad), self.assertRaises(ValueError):
                self.select(k, total=bad)
        for bad in (-1, True, False, 1.0, '1'):
            with self.subTest(optional=bad), self.assertRaises(ValueError):
                self.select(k, optional=bad)
        for bad in (Objective.PLAN_WORKSPACE_BYTES, 'multiplication_ops', True):
            with self.subTest(objective=bad), self.assertRaises(ValueError):
                selection.select_plan(k, Limits(), 100000, bad)
        self.assertEqual(k.objective, Objective.MULTIPLICATION_OPS)
        for field, value in [('height', 10**100), ('cap', None), ('source_digest', '0'*64)]:
            with self.subTest(field=field), self.assertRaises(ValueError), patch.object(selection, 'make_plan', side_effect=AssertionError('untrusted generation')):
                self.select(replace(k, **{field: value}))
        result = self.select(k, optional=0)
        self.assertEqual(result.limits, Limits())
        for value, field, replacement in [(result, 'reason', 'changed'), (result.attempts[0], 'work_used', 0)]:
            with self.assertRaises(FrozenInstanceError):
                setattr(value, field, replacement)

    def test_source_and_plan_quotas_remain_independent_of_check_budget(self):
        k = admitted()
        for limits, reason in [(replace(Limits(), plan_bytes=1), 'BYTE_LIMIT'),
                               (replace(Limits(), plan_operations=1), 'OPERATION_LIMIT'),
                               (replace(Limits(), expression_nodes=100), 'EXPRESSION_NODES_EXHAUSTED')]:
            with self.subTest(reason=reason):
                result = self.select(k, limits=limits)
                self.assertIsNone(result.selected_plan)
                self.assertEqual(len(result.attempts), 1)
                self.assertEqual(result.reason, reason)
                self.assertEqual(result.attempts[0].check.semantic_status, SemanticStatus.UNKNOWN)
        with self.assertRaises(ValueError):
            self.select(k, limits=replace(Limits(), source_bytes=1))

    def test_exception_attempt_still_identifies_requested_constraints(self):
        k = admitted()
        expected = check_plan(k, make_plan(k, 'inline-v1'), Limits()).constraint_digest
        with patch.object(selection, 'check_plan', side_effect=RuntimeError('no receipt')):
            result = self.select(k)
        self.assertEqual(result.attempts[0].constraint_digest, expected)

    def test_mismatched_constraint_receipt_cannot_become_an_artifact(self):
        k = admitted()
        checked = check_plan(k, make_plan(k, 'inline-v1'), Limits())
        with patch.object(selection, 'check_plan', return_value=replace(checked, constraint_digest='0'*64)):
            result = self.select(k)
        self.assertIsNone(result.selected_plan)
        self.assertEqual(result.attempts[0].constraint_digest, checked.constraint_digest)

    def test_malformed_checker_receipt_stops_with_no_artifact(self):
        for malformed in (True, object(), None):
            with self.subTest(receipt=malformed), patch.object(selection, 'check_plan', return_value=malformed):
                result = self.select()
                self.assertEqual(result.termination_reason, 'checker_error')
                self.assertIsNone(result.selected_plan)
                self.assertEqual(result.total_work_used, 100000)
                self.assertIsNone(result.attempts[0].check)

    def test_every_admitted_shape_and_cap_boundary_against_analytic_portfolio(self):
        # Each specialization receives three real independent semantic checks.
        # The adapter below avoids repeating the identical semantic scan for
        # cap/ranking changes; it checks that each generated stream is identical
        # and rebuilds only the context-dependent parts of its real receipt.
        # This adapter is test infrastructure, never a production proof cache.
        shapes = contexts = 0
        for h in range(1, 128):
            for w in range(1, 128):
                if (h+1)*(w+1) > 256:
                    continue
                shapes += 1
                base_kernel = admitted(h, w, None)
                encoded_streams = {}
                def capture_encoding(plan, *, limits):
                    data = encode_plan(plan, limits=limits)
                    encoded_streams[plan.plan_id] = data
                    return data
                with patch.object(selection, 'encode_plan', side_effect=capture_encoding):
                    base = self.select(base_kernel)
                self.assertEqual(base.selected_plan.plan_id, analytic(h, w, None, base_kernel.objective))
                self.assertEqual(len(base.attempts), 3, (h, w, base.termination_reason, base.reason))
                records = {a.candidate_id: a.check for a in base.attempts}
                streams = {label: make_plan(base_kernel, label) for label in records}
                self.assertTrue(all(check.eligible for check in records.values()))
                def context_check(k, plan, limits):
                    self.assertEqual(plan, streams[plan.plan_id])
                    real = records[plan.plan_id]
                    self.assertGreaterEqual(limits.check_steps, real.work_used)
                    constraint = ConstraintStatus.SATISFIED if k.cap is None or real.workspace_bytes <= k.cap else ConstraintStatus.VIOLATED
                    digest = sha256(canonical_json({'version': 1, 'property': 'plan_workspace_bytes',
                        'source_cap': k.cap, 'additional_cap': None, 'effective_cap': k.cap})).hexdigest()
                    return replace(real, source_digest=k.source_digest, effective_cap=k.cap,
                                   constraint_status=constraint, constraint_digest=digest)
                row_bytes, material_bytes = 8*(w+1), 4*(h+1)*(w+1)
                caps = sorted({0, row_bytes-1, row_bytes, row_bytes+1,
                               material_bytes-1, material_bytes, material_bytes+1}) + [None]
                # Canonical bytes are also identical once the generated stream
                # has passed context_check's exact comparison. Reuse only the
                # encoder outputs captured from the real uncapped selection.
                def context_encoding(plan, *, limits):
                    self.assertLessEqual(len(encoded_streams[plan.plan_id]), limits.plan_bytes)
                    return encoded_streams[plan.plan_id]
                with patch.object(selection, 'check_plan', side_effect=context_check), patch.object(selection, 'encode_plan', side_effect=context_encoding):
                    for objective in Objective:
                        for cap in caps:
                            contexts += 1
                            k = admitted(h, w, cap, objective.value)
                            result = self.select(k)
                            self.assertEqual(result.selected_plan.plan_id, analytic(h, w, cap, objective),
                                             (h, w, cap, objective))
                            self.assertTrue(result.selected_check.eligible)
                            self.assertEqual(result.selected_check.effective_cap, cap)
                            self.assertEqual(result.selected_check.plan_digest, sha256(result.selected_plan_bytes).hexdigest())
                            self.assertEqual(len(result.attempts), 3, (h, w, cap, objective, result.termination_reason, result.reason))
        self.assertEqual(shapes, 955)
        self.assertEqual(contexts, 14518)

    def test_repeated_fresh_checks_have_identical_work_and_identities(self):
        k = admitted()
        with patch.object(selection, 'check_plan', wraps=check_plan) as checker:
            first = self.select(k)
            second = self.select(k)
        self.assertEqual(first, second)
        self.assertEqual(checker.call_count, 6)
        self.assertTrue(all(a.source_digest == k.source_digest and a.semantic_digest == k.semantic_digest and
                            a.constraint_digest == a.check.constraint_digest and
                            a.ranking_digest == selection.ranking_digest(k.objective) for a in first.attempts))


if __name__ == '__main__':
    unittest.main()
