"""scale-v1 against an independent oracle, and the template checker under mutation.

bench/oracle.py defines every benchmark kernel directly in plain Python and
imports nothing from axiom; a static check below keeps it that way.
"""
import ast
import random
import sys
import unittest
from pathlib import Path

from axiom.frontend import admit_source, parse_source
from axiom.reference import evaluate_source
from axiom.scale_checker import check_loop_plan
from axiom.scale_plan import LoopPlan, Stage, make_scale_plan
from axiom.scale_runtime import execute_loop_plan

BENCH = Path(__file__).resolve().parents[2] / 'bench'


def _bench():
    if str(BENCH) not in sys.path:
        sys.path.insert(0, str(BENCH))
    import axiom_adapter
    import oracle
    return axiom_adapter, oracle


# Shapes above 256 input cells (so scale-v1), small enough for Python.
CASES = [('sq2x2', 40, 30), ('stencil1d3', 3000, 0), ('box3x3', 40, 37), ('laplace5', 33, 41),
         ('conv3x3', 37, 29), ('polymap', 5000, 0), ('transpose', 40, 40), ('sum', 3000, 0),
         ('matmul', 20, 0), ('dot', 300, 0)]


class ScaleOracleTests(unittest.TestCase):
    def test_oracle_imports_nothing_from_axiom(self):
        for name in ('oracle.py', 'catalog.py'):
            tree = ast.parse((BENCH / name).read_text(encoding='utf-8'))
            modules = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
            modules += [node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            with self.subTest(file=name):
                self.assertFalse([m for m in modules if m.split('.')[0] == 'axiom'], modules)

    def test_scale_programs_match_the_independent_oracle(self):
        adapter, oracle = _bench()
        for kernel, a, b in CASES:
            for pattern in ('hash', 'max', 'alt'):
                with self.subTest(kernel=kernel, pattern=pattern):
                    source, data, n_out, _ = adapter.request(kernel, pattern, a, b, None, None)
                    admitted = admit_source(parse_source(source))
                    self.assertEqual(admitted.profile, 'scale-v1')
                    plan = make_scale_plan(admitted)
                    observed = execute_loop_plan(source, plan, data, [-9] * n_out)
                    self.assertEqual(observed.status.value, 'success')
                    self.assertEqual(list(observed.output), oracle.expected(kernel, a, b, data))


def _mutate(expr, rng):
    """One random local change somewhere in an expression tree."""
    kind = expr[0]
    choice = rng.random()
    if kind == 'const':
        return ('const', expr[1] + rng.choice((-1, 1, 7)))
    if kind == 'prod':
        if choice < 0.5:
            return ('prod', expr[1] + rng.choice((-1, 1)), expr[2])
        return ('prod', expr[1], expr[2] + rng.choice((-1, 1)))
    if kind == 'load':
        constant, terms = expr[1]
        if terms and choice < 0.5:
            var, k = rng.choice(terms)
            terms = tuple(sorted((v, c + (1 if v == var else 0)) for v, c in terms))
            return ('load', (constant, terms))
        return ('load', (constant + rng.choice((-1, 1)), terms))
    if kind in ('add', 'mul', 'min', 'max'):
        if choice < 0.2:
            return ({'add': 'mul', 'mul': 'add', 'min': 'max', 'max': 'min'}[kind], expr[1], expr[2])
        if choice < 0.3:
            return (kind, expr[2], expr[1])
        if choice < 0.65:
            return (kind, _mutate(expr[1], rng), expr[2])
        return (kind, expr[1], _mutate(expr[2], rng))
    _, var, lo, hi, body = expr
    if choice < 0.25:
        return ('sum', var, lo, hi + rng.choice((-1, 1)), body)
    if choice < 0.35:
        return ('sum', var, lo + 1, hi, body)
    return ('sum', var, lo, hi, _mutate(body, rng))


class TemplateCheckerMutationTests(unittest.TestCase):
    def test_accepted_mutants_compute_the_reference(self):
        """Soundness by fuzzing: any accepted plan must equal the source everywhere tested."""
        adapter, _ = _bench()
        rng = random.Random(20261024)
        accepted = rejected = 0
        for kernel, a, b in (('box3x3', 20, 19), ('matmul', 18, 0), ('sum', 2000, 0), ('transpose', 20, 20)):
            source, _, n_out, _ = adapter.request(kernel, 'hash', a, b, None, None)
            admitted = admit_source(parse_source(source))
            plan = make_scale_plan(admitted)
            stage = plan.stages[0]
            for _ in range(100):
                value = _mutate(stage.value, rng)
                if rng.random() < 0.1:
                    loops = tuple((v, n + rng.choice((-1, 1))) if i == rng.randrange(2) else (v, n)
                                  for i, (v, n) in enumerate(stage.loops))
                    mutant = LoopPlan(plan.semantic_digest, plan.plan_id, (Stage(loops, stage.index, value),))
                else:
                    mutant = LoopPlan(plan.semantic_digest, plan.plan_id, (Stage(stage.loops, stage.index, value),))
                if not check_loop_plan(source, mutant).valid:
                    rejected += 1
                    continue
                accepted += 1
                for seed in range(3):
                    data = [random.Random(seed).randrange(1024) for _ in range(admitted.input_count)]
                    initial = [-9] * n_out
                    self.assertEqual(execute_loop_plan(source, mutant, data, initial),
                                     evaluate_source(admitted.source_module, data, initial))
        self.assertGreater(rejected, 300)  # the fuzzer really produces wrong plans
        self.assertLessEqual(accepted, 100)  # only no-op mutations may survive


if __name__ == '__main__':
    unittest.main()
