"""The per-selection source-derivation cache must be unobservable.

Every CheckResult and SearchResult produced with the cache must equal the one
produced by direct derivation, for every step/node budget, including budgets
that exhaust inside the source derivation, on the probe itself, or exactly at
its boundary, and in any order of reuse.
"""
from contextvars import ContextVar
from dataclasses import replace
import unittest
from unittest.mock import patch

from axiom import selection
from axiom.checker import _SourceCache, check_plan
from axiom.frontend import admit_source, parse_source
from axiom.model import Limits, Objective
from axiom.planner import PLAN_IDS, make_plan
from axiom.selection import select_plan
from tests.helpers import stencil_source


def kernel(h, w, cap=1024, objective='multiplication_ops'):
    return admit_source(parse_source(stencil_source(h, w, cap, objective)))


def direct_select(*args, **kwargs):
    """select_plan whose scope sets an unrelated variable: checks derive directly."""
    with patch.object(selection, '_ACTIVE_SOURCE_CACHE', ContextVar('unused', default=None)):
        return select_plan(*args, **kwargs)


class SourceCacheEquivalence(unittest.TestCase):
    def source_charges(self, k):
        cache = _SourceCache(10 ** 9)
        check_plan(k, make_plan(k, 'inline-v1'), Limits(), _source_cache=cache)
        (derivation,) = cache.entries.values()
        return derivation.charges

    def test_check_results_match_direct_derivation_for_every_budget(self):
        k = kernel(2, 3)
        charges = self.source_charges(k)
        steps = sorted({1, 2, charges - 1, charges, charges + 1, charges + 2,
                        2 * charges, Limits().check_steps})
        for cap in (charges - 1, charges, charges + 1, Limits().check_steps):
            for order in (steps, list(reversed(steps))):
                cache = _SourceCache(cap)  # reused across every call below
                for limit in order:
                    for plan_id in PLAN_IDS:
                        for nodes in (1, 10, Limits().expression_nodes):
                            limits = replace(Limits(), check_steps=limit, expression_nodes=nodes)
                            plan = make_plan(k, plan_id)
                            with self.subTest(cap=cap, limit=limit, plan=plan_id, nodes=nodes):
                                self.assertEqual(check_plan(k, plan, limits, _source_cache=cache),
                                                 check_plan(k, plan, limits))

    def test_broken_plans_match_direct_derivation(self):
        k = kernel(5, 7)
        cache = _SourceCache(Limits().check_steps)
        for plan_id in PLAN_IDS:
            plan = make_plan(k, plan_id)
            ops = list(plan.operations)
            first_const = next(i for i, op in enumerate(ops) if op.opcode == 'const')
            ops[first_const] = replace(ops[first_const], value=2147483647)
            for candidate in (plan, replace(plan, operations=tuple(ops)),
                              replace(plan, operations=plan.operations[:-1]),
                              replace(plan, semantic_digest='0' * 64)):
                self.assertEqual(check_plan(k, candidate, Limits(), _source_cache=cache),
                                 check_plan(k, candidate, Limits()))

    def test_search_results_match_direct_derivation(self):
        for h, w in ((1, 1), (2, 3), (5, 7)):
            for cap in (0, 64, 128, 1024):
                for objective in ('multiplication_ops', 'plan_workspace_bytes'):
                    k = kernel(h, w, cap, objective)
                    charges = self.source_charges(k)
                    for total in sorted({0, 1, charges, charges + 1, 3 * charges, 100000}):
                        for optional in (None, 0, charges, 100000):
                            for step_limit in (charges, Limits().check_steps):
                                limits = replace(Limits(), check_steps=step_limit)
                                args = (k, limits, total, Objective(objective), optional)
                                with self.subTest(h=h, w=w, cap=cap, objective=objective,
                                                  total=total, optional=optional, steps=step_limit):
                                    self.assertEqual(select_plan(*args), direct_select(*args))

    def test_selection_really_uses_one_derivation_and_resets_scope(self):
        from axiom import checker
        k = kernel(5, 7)
        with patch.object(checker, '_derive_source', wraps=checker._derive_source) as derive:
            select_plan(k, Limits(), 100000, Objective.MULTIPLICATION_OPS)
        self.assertEqual(derive.call_count, 1)
        self.assertIsNone(checker._ACTIVE_SOURCE_CACHE.get())
        with patch.object(checker, '_derive_source', wraps=checker._derive_source) as derive:
            direct_select(k, Limits(), 100000, Objective.MULTIPLICATION_OPS)
        self.assertEqual(derive.call_count, 3)

    def test_largest_shape_search_matches(self):
        k = kernel(15, 15, 128)
        for total in (100000, 10 ** 7):
            args = (k, Limits(), total, Objective.MULTIPLICATION_OPS)
            self.assertEqual(select_plan(*args), direct_select(*args))


if __name__ == '__main__':
    unittest.main()
