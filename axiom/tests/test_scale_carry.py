"""carry-v1: a producer stage computed once, read through ('prod', i, j)."""
import dataclasses
import random
import unittest

from axiom.frontend import admit_source, parse_source
from axiom.reference import evaluate_source
from axiom.scale_c import compile_scale_native
from axiom.scale_carry import plan_costs, window_rows
from axiom.scale_checker import check_loop_plan
from axiom.scale_plan import LoopPlan, Stage, make_scale_plan
from axiom.scale_runtime import execute_loop_plan
from tests.helpers import stencil_source
from tests.test_scale_family import BOX
from tests.test_scale_oracle import _mutate


def data_for(n, seed=0):
    rng = random.Random(seed)
    return [rng.randrange(1024) for _ in range(n)]


class CarryTests(unittest.TestCase):
    def test_ranking_follows_objective_and_cap(self):
        free = stencil_source(60, 50, None)
        self.assertEqual(compile_scale_native(free).plan.plan_id, 'carry-v1')
        # A declared workspace cap below the ring keeps direct-v1 (0 bytes).
        self.assertEqual(compile_scale_native(stencil_source(60, 50, 64)).plan.plan_id, 'direct-v1')
        workspace = free.replace(b'prefer multiplication_ops', b'prefer plan_workspace_bytes')
        self.assertEqual(compile_scale_native(workspace).plan.plan_id, 'direct-v1')
        kernel = admit_source(parse_source(free))
        direct, carry = (make_scale_plan(kernel, p) for p in ('direct-v1', 'carry-v1'))
        self.assertEqual(plan_costs(direct, kernel)[0], 4)          # (x+1)^2 four times
        self.assertLess(plan_costs(carry, kernel)[0], 1.05)         # once per producer cell
        self.assertEqual((window_rows(carry.stages[-1].value), plan_costs(carry, kernel)[2]), (2, 2 * 51 * 4))

    def test_carry_plans_match_the_reference(self):
        for source in (stencil_source(37, 41, None), BOX.format(h=33, w=29).encode()):
            kernel = admit_source(parse_source(source))
            plan = make_scale_plan(kernel, 'carry-v1')
            self.assertTrue(check_loop_plan(source, plan).valid)
            for bad in (None, 0, kernel.input_count - 1):
                data = data_for(kernel.input_count)
                if bad is not None:
                    data[bad] = 1024
                initial = [-9] * kernel.output_count
                with self.subTest(module=source[:12], bad=bad):
                    self.assertEqual(execute_loop_plan(source, plan, data, initial),
                                     evaluate_source(kernel.source_module, data, initial))

    def test_forged_carry_plans_are_rejected(self):
        source = BOX.format(h=33, w=29).encode()
        kernel = admit_source(parse_source(source))
        plan = make_scale_plan(kernel, 'carry-v1')
        produce, stage = plan.stages

        def with_output(value):
            return dataclasses.replace(plan, stages=(produce, dataclasses.replace(stage, value=value)))

        def shift(expr, di, dj):
            if expr[0] == 'prod':
                return ('prod', expr[1] + di, expr[2] + dj)
            if expr[0] in ('add', 'mul'):
                return (expr[0], shift(expr[1], di, dj), expr[2])
            return expr
        forged = {
            'row offset shifted': with_output(shift(stage.value, 1, 0)),
            'column offset shifted': with_output(shift(stage.value, 0, 1)),
            'producer stage changed': dataclasses.replace(
                plan, stages=(dataclasses.replace(produce, value=('add', produce.value, ('const', 0))), stage)),
            'producer loops short': dataclasses.replace(
                plan, stages=(dataclasses.replace(produce, loops=((produce.loops[0][0], produce.loops[0][1] - 1),
                                                                 produce.loops[1])), stage)),
            'producer index wrong': dataclasses.replace(
                plan, stages=(dataclasses.replace(produce, index=(1, produce.index[1])), stage)),
            'prod in a one-stage plan': LoopPlan(plan.semantic_digest, plan.plan_id, (stage,)),
            'loop variable reused': dataclasses.replace(
                plan, stages=(dataclasses.replace(produce, loops=((stage.loops[0][0], produce.loops[0][1]),
                                                                 produce.loops[1]),
                                                  index=(0, tuple(sorted(((stage.loops[0][0], produce.loops[1][1]),
                                                                          (produce.loops[1][0], 1)))))), stage)),
            'stages swapped': dataclasses.replace(plan, stages=(stage, produce)),
        }
        self.assertTrue(check_loop_plan(source, plan).valid)
        for label, bad in forged.items():
            with self.subTest(forgery=label):
                self.assertFalse(check_loop_plan(source, bad).valid)

    def test_window_beyond_the_producer_is_refused(self):
        source = stencil_source(20, 20, None)
        kernel = admit_source(parse_source(source))
        plan = make_scale_plan(kernel, 'carry-v1')
        produce, stage = plan.stages
        # Producer rows are H + 1, so a read at row offset 2 would run past the last row.
        far = ('add', stage.value, ('prod', 2, 0))
        self.assertFalse(check_loop_plan(source, dataclasses.replace(
            plan, stages=(produce, dataclasses.replace(stage, value=far)))).valid)

    def test_accepted_carry_mutants_compute_the_reference(self):
        rng = random.Random(7)
        source = BOX.format(h=17, w=19).encode()
        kernel = admit_source(parse_source(source))
        plan = make_scale_plan(kernel, 'carry-v1')
        produce, stage = plan.stages
        rejected = 0
        for _ in range(200):
            if rng.random() < 0.5:
                mutant = dataclasses.replace(plan, stages=(dataclasses.replace(produce, value=_mutate(produce.value, rng)), stage))
            else:
                mutant = dataclasses.replace(plan, stages=(produce, dataclasses.replace(stage, value=_mutate(stage.value, rng))))
            if not check_loop_plan(source, mutant).valid:
                rejected += 1
                continue
            data = data_for(kernel.input_count, 3)
            initial = [-9] * kernel.output_count
            self.assertEqual(execute_loop_plan(source, mutant, data, initial),
                             evaluate_source(kernel.source_module, data, initial))
        self.assertGreater(rejected, 150)


if __name__ == '__main__':
    unittest.main()
