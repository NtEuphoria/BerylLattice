"""Research controls: passing them cannot approve the independent review gate."""
import dataclasses
import unittest

from loop_proof_feasibility import (
    Affine, Budget, Ledger, ProbeError, Rectangle, TermDAG,
    check_parity, check_prefix, check_scratch, probe_outline, run_feasibility,
)


class FeasibilityTests(unittest.TestCase):
    def test_rows2_base_step_exit(self):
        for h, w in [(1, 1), (1, 8192), (8192, 1), (32, 32)]:
            receipt = probe_outline('rows2', h, w)
            self.assertEqual(receipt.parity_cases, 2)
            self.assertIn('stage-prefix', receipt.obligations)
            self.assertIn('consumer-prefix', receipt.obligations)
            self.assertIn('outer-base-step-exit', receipt.obligations)
            self.assertTrue(receipt.complete)
        self.assertEqual(check_parity((0, 1)), ((0, 1), (1, 0)))
        for cases in [(0,), (1,), (0, 0), (0, 1, 2)]:
            with self.assertRaises(ProbeError):
                check_parity(cases)

    def test_output_conservation_cannot_forget_write(self):
        cell = Rectangle.of(0, 1, 0, 1)
        ledger = Ledger((), {})
        ledger = ledger.write(cell)
        with self.assertRaises(ProbeError):
            ledger.require_exact(())
        with self.assertRaises(ProbeError):
            ledger.write(cell)
        ledger.require_exact((cell,))

    def test_obligations_do_not_enumerate_extent(self):
        for name in ('inline', 'materialize', 'rows2'):
            runs = [probe_outline(name, n, n) for n in (32, 128, 512, 2048)]
            self.assertEqual(len({r.graph_shape for r in runs}), 1)
            self.assertEqual(len({r.primitive_events for r in runs}), 1)
            self.assertTrue(all(r.trace_bytes < 524288 for r in runs))
            self.assertTrue(all(r.total_work < 1000000 for r in runs))

    def test_prefix_gap_overlap_reset_and_empty_trip(self):
        for extent in (0, 1, 8):
            check_prefix(extent)
        for mutation in ('gap', 'overlap', 'reset', 'wrong-step', 'missing-base'):
            with self.subTest(mutation=mutation), self.assertRaises(ProbeError):
                check_prefix(8, mutation=mutation)
        with self.assertRaises(ProbeError):
            check_prefix(-1)

    def test_scratch_initialization_overwrite_frame_and_last_column(self):
        check_scratch(8)
        for mutation in ('uninitialized', 'stale', 'alias', 'short-row', 'wrong-value'):
            with self.subTest(mutation=mutation), self.assertRaises(ProbeError):
                check_scratch(8, mutation=mutation)

    def test_general_affine_endpoint_reasoning(self):
        x = Affine.var('x')
        b = Budget()
        self.assertEqual((3*x+2).bounds({'x': (0, 8191)}, b), (2, 24575))
        self.assertEqual((-2*x+1).bounds({'x': (0, 8191)}, b), (-16381, 1))
        with self.assertRaises(ProbeError):
            x.bounds({}, b)

    def test_source_term_order_sharing_and_limits(self):
        dag = TermDAG()
        a, b, c = [dag.node('input', (i, 0), ()) for i in range(3)]
        ab = dag.node('add', (), (a, b))
        left = dag.node('add', (), (ab, c))
        right = dag.node('add', (), (a, dag.node('add', (), (b, c))))
        self.assertNotEqual(left, right)
        shared = a
        for _ in range(32):
            shared = dag.node('add', (), (shared, shared), check_i32=False)
        self.assertLess(len(dag.nodes), 45)
        with self.assertRaises(ProbeError):
            TermDAG(max_nodes=1).node('input', (1, 1), (1,))
        limited = TermDAG(max_nodes=1)
        limited.node('const', (1,), ())
        with self.assertRaises(ProbeError):
            limited.node('const', (2,), ())
        self.assertEqual(len(limited.nodes), 1)
        with self.assertRaises(ProbeError):
            probe_outline('inline', 1, 1, mutation='reassociate')
        with self.assertRaises(ProbeError):
            probe_outline('inline', 1, 1, mutation='dead-overflow')

    def test_hand_authored_variants_and_unsupported_controls(self):
        for schedule in ('inline', 'materialize', 'rows2'):
            a = probe_outline(schedule, 32, 33)
            b = probe_outline(schedule, 32, 33, axis_names=('alpha', 'beta'), reverse_definitions=True)
            self.assertEqual(a.term_nodes, b.term_nodes)
        for schedule in ('inline', 'materialize'):
            self.assertTrue(probe_outline(schedule, 32, 33, column_major=True).complete)
        with self.assertRaises(ProbeError):
            probe_outline('rows2', 32, 33, column_major=True)
        with self.assertRaises(ProbeError):
            probe_outline('invented', 32, 33)

    def test_work_width_and_depth_fail_closed(self):
        with self.assertRaises(ProbeError):
            Budget(limit=1).mul(8192, 8192)
        with self.assertRaises(ProbeError):
            Budget().mul(1 << 255, 2)
        dag = TermDAG(max_depth=2)
        one = dag.node('const', (1,), ())
        two = dag.node('add', (), (one, one))
        with self.assertRaises(ProbeError):
            dag.node('add', (), (two, one))
        self.assertEqual(len(dag.nodes), 2)

    def test_candidate_encoding_arithmetic_fails_closed(self):
        from loop_proof_feasibility import hand_certificate_bounds
        bound = hand_certificate_bounds()
        self.assertEqual(bound['primitive_instances'], {'inline': 20, 'materialize': 13, 'rows2': 31})
        self.assertEqual(bound['induction_instances'], {'inline': 2, 'materialize': 4, 'rows2': 6})
        self.assertEqual(bound['proof_rows']['rows2'], 1504)
        self.assertLessEqual(bound['certificate_bytes_bound'], 524288)
        self.assertGreater(bound['total_work_bound'], 1000000)
        self.assertFalse(bound['fits_unchanged_quotas'])
        self.assertEqual(bound['peak_scratch_facts']['materialize'], 3)
        # Every specified table and every charged-work category is mandatory.
        for category in bound['table_bytes']:
            with self.subTest(table=category), self.assertRaises(ProbeError):
                hand_certificate_bounds(omit_table=category)
        for category in bound['work_categories']:
            with self.subTest(work=category), self.assertRaises(ProbeError):
                hand_certificate_bounds(omit_work=category)
        # A claimed total cannot omit proof payloads, even if still below quota.
        with self.assertRaises(ProbeError):
            hand_certificate_bounds(claimed_bytes=bound['certificate_bytes_bound']-1)
        with self.assertRaises(ProbeError):
            hand_certificate_bounds(claimed_work=bound['total_work_bound']-1)

    def test_review_is_never_self_certified(self):
        receipt = run_feasibility()
        self.assertEqual(receipt.outcome, 'blocked')
        self.assertEqual(receipt.first_unresolved, 'F1: complete hand-certificate representation and quota bound pending independent re-review')
        self.assertEqual(len(receipt.outlines), 3)
        self.assertTrue(receipt.production_gaps)
        self.assertNotIn('eligible', {f.name for f in dataclasses.fields(receipt)})
