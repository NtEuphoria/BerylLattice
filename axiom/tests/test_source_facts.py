"""Source sharing must preserve the immutable accounting-v1 checker result.

The fixture is byte-for-byte checker.py from 39dc2f6df136c643cfd030ce4470503e807750fe.
It imports the same codec/frontend records so this differential isolates checking.
"""
import cProfile
from dataclasses import asdict, replace
from hashlib import sha256
import importlib.util
from pathlib import Path
import sys
import unittest

from axiom import checker
from axiom.codec import plan_digest
from axiom.frontend import admit_source, parse_source
from axiom.model import (BinaryExpression, GroupExpression, IntegerLiteral, Limits,
                         NameReference, ReadExpression, Span)
from axiom.plan_format import Operation
from axiom.planner import PLAN_IDS, make_plan
from tests.helpers import stencil_source
from tests.test_checker import kernel, staged


SNAPSHOT = Path(__file__).parent / 'fixtures' / 'checker_39dc2f6.py'
SPEC = importlib.util.spec_from_file_location('axiom._checker_39dc2f6', SNAPSHOT)
BASELINE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASELINE
SPEC.loader.exec_module(BASELINE)


def call_count(profile, function):
    return sum(entry.callcount for entry in profile.getstats()
               if entry.code is function.__code__)


def source_run(implementation, k, environments, *, steps=100000, nodes=100000):
    """Observe interpreter semantics/accounting, ignoring physical node indices."""
    dag = implementation._Expressions(nodes, k.input_interval)
    work = implementation._Work(steps)
    results = []
    reason, witness = 'VALID', None

    def tree(index):
        node = dag.nodes[index]
        return (node.kind, node.atom, node.lower, node.upper, node.samples,
                None if node.left is None else tree(node.left),
                None if node.right is None else tree(node.right))

    try:
        for environment in environments:
            result = implementation._source_expression(
                k.source_module.outputs[0].expression, environment, k, dag, work)
            results.append(tree(result))
    except implementation._Stop as stop:
        reason, witness = stop.reason, stop.witness
    allocated = getattr(dag, 'allocations', len(dag.nodes))
    return (reason, witness, work.used, allocated, dag.inconclusive, results)


class SourceFactTests(unittest.TestCase):
    def assert_result_equal(self, k, plan, limits=Limits(), **context):
        expected = BASELINE.check_plan(k, plan, limits, **context)
        actual = checker.check_plan(k, plan, limits, **context)
        self.assertEqual(asdict(actual), asdict(expected), (limits, context))
        return actual

    def test_baseline_is_the_immutable_original_checker(self):
        self.assertEqual(sha256(SNAPSHOT.read_bytes()).hexdigest(),
                         'bfe22abb6142f63e4d868570916ea7ad64e13b5011fd54cfafeea618ec73aaa5')
        self.assertEqual(checker.CHECKER_VERSION, BASELINE.CHECKER_VERSION)
        self.assertEqual(checker.CHECK_ACCOUNTING_VERSION, 1)

    def test_each_concrete_source_producer_is_evaluated_once_per_proof(self):
        k = kernel(2, 2)
        plan = staged(k)
        profile = cProfile.Profile()
        result = profile.runcall(checker.check_plan, k, plan, Limits())
        self.assertTrue(result.eligible, result)
        self.assertEqual(result.work_used, 476)
        # Two original input AST reads per unique producer plus nine plan loads.
        self.assertEqual(call_count(profile, checker._Expressions.input), 2*9+9)
        # 75 source DAG nodes plus 40 plan nodes; quota remains 164 allocations.
        self.assertEqual(call_count(profile, checker._Expressions.allocate), 115)
        self.assert_result_equal(k, plan, Limits(expression_nodes=163))
        self.assertTrue(self.assert_result_equal(k, plan, Limits(expression_nodes=164)).eligible)

    def test_renamed_output_axes_do_not_prevent_reuse_or_cross_invocations(self):
        source = stencil_source(2, 2).replace(
            b'output result[r in 0..H,c in 0..W] =\n  ((p[r,c]+p[r,c+1])+p[r+1,c])+p[r+1,c+1];',
            b'output result[y in 0..H,x in 0..W] =\n  ((p[y,x]+p[y,x+1])+p[y+1,x])+p[y+1,x+1];')
        k = admit_source(parse_source(source))
        plan = staged(k)
        for _ in range(2):
            profile = cProfile.Profile()
            result = profile.runcall(checker.check_plan, k, plan, Limits())
            self.assertTrue(result.eligible, result)
            self.assertEqual(call_count(profile, checker._Expressions.input), 27)
            self.assertEqual(result.work_used, 476)

    def test_all_admitted_shapes_and_schedules_match_original_results(self):
        shapes = 0
        for height in range(1, 128):
            for width in range(1, 128):
                if (height+1)*(width+1) > 256:
                    continue
                shapes += 1
                k = admit_source(parse_source(stencil_source(height, width)))
                for schedule in PLAN_IDS:
                    with self.subTest(height=height, width=width, schedule=schedule):
                        self.assert_result_equal(k, make_plan(k, schedule))
        self.assertEqual(shapes, 955)

    def test_every_small_work_and_allocation_prefix_matches(self):
        for height, width in ((1, 2), (2, 1), (2, 2)):
            k = kernel(height, width)
            for schedule in PLAN_IDS:
                plan = make_plan(k, schedule)
                full = BASELINE.check_plan(k, plan, Limits())
                for steps in range(1, full.work_used+2):
                    self.assert_result_equal(k, plan, Limits(check_steps=steps))
                # Scalar source allocation is 31 per output, plus each physical
                # const/load/add/mul. Scratch loads alias existing nodes.
                total = 31*height*width + sum(op.opcode in ('const', 'input_load', 'add', 'mul')
                                            for op in plan.operations)
                for nodes in range(1, total+2):
                    self.assert_result_equal(k, plan, Limits(expression_nodes=nodes))

    def test_joint_prefixes_include_cache_hit_and_source_plan_boundary(self):
        k = kernel(1, 2)
        plan = staged(k)
        for steps in (*range(70, 111), *range(150, 160), 243, 244):
            for nodes in (*range(25, 51), *range(60, 66), 86, 87):
                self.assert_result_equal(k, plan, Limits(check_steps=steps, expression_nodes=nodes))

    def test_owned_checks_keep_exact_boundary_and_start_a_fresh_arena(self):
        k = kernel(2, 2, None)
        plan = make_plan(k, 'materialize-v1')
        identity = plan_digest(plan)
        for _ in range(2):
            profile = cProfile.Profile()
            result = profile.runcall(checker._check_admitted_plan, k, plan, Limits(), identity)
            self.assertEqual(asdict(result), asdict(BASELINE.check_plan(k, plan, Limits())))
            self.assertEqual(call_count(profile, checker._Expressions.input), 27)
        for nodes in (163, 164, 165):
            for steps in (82, 83, 84, 307, 308, 309, 487, 488, 489):
                limits = Limits(check_steps=steps, expression_nodes=nodes)
                actual = checker._check_admitted_plan(k, plan, limits, identity)
                expected = BASELINE.check_plan(k, plan, limits)
                self.assertEqual(asdict(actual), asdict(expected), limits)

    def test_grouping_names_and_declaration_order_preserve_full_results(self):
        original = stencil_source(2, 3)
        grouped = original.replace(b'(image[r,c]+1)*(image[r,c]+1)',
                                   b'(((image[(r),(c)]+(1)))*((image[(r),(c)]+(1))))')
        renamed = grouped.replace(b'image', b'pixels').replace(b'p[', b'producer[')
        reordered = renamed.replace(b'require plan_workspace_bytes <= 64;\n', b'').replace(
            b'input pixels:', b'require plan_workspace_bytes <= 64;\ninput pixels:')
        for source in (original, grouped, renamed, reordered):
            k = admit_source(parse_source(source))
            for schedule in PLAN_IDS:
                plan = make_plan(k, schedule)
                self.assertTrue(self.assert_result_equal(k, plan).eligible)
                for steps, nodes in ((140, 1000), (10000, 72), (149, 72)):
                    self.assert_result_equal(k, plan, Limits(check_steps=steps, expression_nodes=nodes))

    def test_forged_records_invalid_plans_and_semantic_unknowns_match(self):
        k = kernel(2, 2)
        plan = staged(k)
        next_register = 40
        # staged uses 40 dense destinations; include dead overflow and lost
        # correlation without replacing any visible output.
        overflow = (Operation('const', dst=next_register, value=2147483647),
                    Operation('add', dst=next_register+1, operands=(next_register, 0)))
        unknown = (Operation('const', dst=40, value=-1),
                   Operation('mul', dst=41, operands=(1, 40)),
                   Operation('add', dst=42, operands=(1, 41)),
                   Operation('const', dst=43, value=2147483647),
                   Operation('mul', dst=44, operands=(42, 43)))
        variants = [replace(plan, operations=plan.operations+overflow),
                    replace(plan, operations=plan.operations+unknown),
                    replace(plan, operations=plan.operations[:-1]),
                    replace(plan, operations=plan.operations+(plan.operations[-1],)),
                    replace(plan, operations=(Operation('scratch_load', dst=0, index=0),),
                            scratch_capacity_cells=1)]
        changed = list(plan.operations)
        changed[1] = replace(changed[1], index=1)
        variants.append(replace(plan, operations=tuple(changed)))
        for variant in variants:
            full = self.assert_result_equal(k, variant)
            self.assertFalse(full.eligible)
            for steps in (1, 83, 307, 308, full.work_used, full.work_used+1):
                self.assert_result_equal(k, variant, Limits(check_steps=steps))
            for nodes in (31, 35, 123, 124, 163, 164, 168):
                self.assert_result_equal(k, variant, Limits(expression_nodes=nodes))
        scalar = IntegerLiteral(1, Span(0, 1))
        forged_module = replace(k.source_module, producers=(
            replace(k.source_module.producers[0], expression=scalar),))
        for forged in (replace(k, cap=None), replace(k, input_interval=(0, 1)),
                       replace(k, source_module=forged_module),
                       replace(k, source_digest='f'*64)):
            self.assert_result_equal(forged, plan)
        for limits in (Limits(source_bytes=1), Limits(plan_bytes=1), Limits(plan_operations=1)):
            self.assert_result_equal(k, plan, limits)
        self.assert_result_equal(k, plan, additional_cap=0)

    def test_actual_free_bindings_and_retained_ast_supply_interpreter_facts(self):
        # Synthetic private-interpreter case exercises assumptions beyond the
        # admitted profile without granting caller-created public records trust.
        k = kernel(1, 1)
        span = Span(0, 1)
        ref = lambda name: NameReference(name, span)
        expression = BinaryExpression('+', ReadExpression('image', (ref('r'), ref('c')), span, span),
                                      ref('offset'), span)
        producer = replace(k.source_module.producers[0], expression=expression)
        read = ReadExpression('p', (IntegerLiteral(0, span), IntegerLiteral(0, span)), span, span)
        output = replace(k.source_module.outputs[0], expression=read)
        k = replace(k, source_module=replace(k.source_module, producers=(producer,), outputs=(output,)))
        environments = [{'offset': value, 'irrelevant': index} for index, value in enumerate((1, 1, 2, 1))]
        expected = source_run(BASELINE, k, environments)
        self.assertEqual(source_run(checker, k, environments), expected)
        self.assertNotEqual(expected[-1][0], expected[-1][2])
        for steps in range(1, expected[2]+2):
            for nodes in range(1, expected[3]+2):
                self.assertEqual(source_run(checker, k, environments, steps=steps, nodes=nodes),
                                 source_run(BASELINE, k, environments, steps=steps, nodes=nodes))

    def test_source_overflow_and_inconclusive_effects_keep_precedence(self):
        k = kernel(1, 1)
        span = Span(0, 1)
        literal = lambda value: IntegerLiteral(value, span)
        ref = lambda name: NameReference(name, span)
        read = ReadExpression('image', (ref('r'), ref('c')), span, span)
        negated = BinaryExpression('*', read, literal(-1), span)
        cancellation = BinaryExpression('+', read, negated, span)
        inconclusive = BinaryExpression('*', cancellation, literal(2147483647), span)
        overflow = BinaryExpression('+', literal(2147483647), ref('offset'), span)
        for expression in (inconclusive, overflow, BinaryExpression('-', read, literal(1), span)):
            producer = replace(k.source_module.producers[0], expression=expression)
            output_read = ReadExpression('p', (literal(0), literal(0)), span, span)
            output = replace(k.source_module.outputs[0], expression=GroupExpression(output_read, span))
            custom = replace(k, source_module=replace(k.source_module, producers=(producer,), outputs=(output,)))
            environments = [{'offset': 0}, {'offset': 0}, {'offset': 1}]
            expected = source_run(BASELINE, custom, environments)
            self.assertEqual(source_run(checker, custom, environments), expected)
            for steps in range(1, expected[2]+2):
                for nodes in range(1, expected[3]+2):
                    self.assertEqual(source_run(checker, custom, environments, steps=steps, nodes=nodes),
                                     source_run(BASELINE, custom, environments, steps=steps, nodes=nodes))


if __name__ == '__main__':
    unittest.main()
