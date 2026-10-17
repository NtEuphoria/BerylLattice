"""Physical generators have no privileged status at the checker boundary."""
import ast
from collections import Counter
from dataclasses import fields, is_dataclass
from pathlib import Path
import unittest

from axiom.checker import check_plan
from axiom.codec import decode_plan, encode_plan
from axiom.frontend import admit_source, parse_source
from axiom.model import Limits
from axiom import planner
from tests.helpers import stencil_source

IDS = ('inline-v1', 'rows2-v1', 'materialize-v1')


def admitted(h=5, w=7):
    return admit_source(parse_source(stencil_source(h, w, None)))


class PlannerTests(unittest.TestCase):
    def test_exact_three_ids_and_reject_other_labels(self):
        self.assertEqual(planner.PLAN_IDS, IDS)
        for label in ('SSA-staged', 'rows1-v1', '', None, True):
            with self.subTest(label=label), self.assertRaises((TypeError, ValueError)):
                planner.make_plan(admitted(), label)

    def test_h5w7_checked_costs_and_canonical_bytes(self):
        k = admitted()
        expected = {'inline-v1': (0, 140), 'rows2-v1': (64, 48),
                    'materialize-v1': (192, 48)}
        for label, costs in expected.items():
            with self.subTest(label=label):
                plan = planner.make_plan(k, label)
                encoded = encode_plan(plan)
                restored = decode_plan(encoded, Limits())
                self.assertEqual(encode_plan(restored), encoded)
                self.assertEqual(restored, plan)
                self.assertEqual(plan, planner.make_plan(k, label))
                result = check_plan(k, restored, Limits())
                self.assertTrue(result.eligible, result)
                self.assertEqual((result.workspace_bytes, result.multiplication_ops), costs)
                self.assertEqual(dict(result.opcode_counts), dict(Counter(o.opcode for o in plan.operations)))
                self.assertEqual(sum(o.opcode == 'mul' for o in plan.operations), costs[1])

    def test_every_admitted_shape_has_bounded_dense_unrolled_stream(self):
        shapes = 0
        largest = dict.fromkeys(IDS, 0)
        for h in range(1, 128):
            for w in range(1, 128):
                if (h+1)*(w+1) > 256:
                    continue
                shapes += 1
                k = admitted(h, w)
                n, out = (h+1)*(w+1), h*w
                for label in IDS:
                    with self.subTest(h=h, w=w, label=label):
                        p = planner.make_plan(k, label)
                        counts = Counter(o.opcode for o in p.operations)
                        expected_ops = 1+16*out if label == 'inline-v1' else 1+4*n+8*out
                        self.assertEqual(len(p.operations), expected_ops)
                        self.assertEqual(counts['mul'], 4*out if label == 'inline-v1' else n)
                        self.assertEqual(counts['const'], 1)
                        self.assertEqual(counts['output_store'], out)
                        self.assertEqual(p.scratch_capacity_cells,
                                         {'inline-v1': 0, 'rows2-v1': 2*(w+1), 'materialize-v1': n}[label])
                        self.assertEqual([o.dst for o in p.operations if o.dst is not None],
                                         list(range(sum(o.dst is not None for o in p.operations))))
                        for op in p.operations:
                            if op.dst is not None:
                                self.assertTrue(all(v < op.dst for v in op.operands))
                        self.assertLess(len(p.operations), Limits().plan_operations)
                        largest[label] = max(largest[label], len(p.operations))
        self.assertEqual(shapes, 955)
        self.assertEqual(largest, {'inline-v1': 3601, 'rows2-v1': 2825, 'materialize-v1': 2825})

    def test_origins_refer_to_retained_source_and_no_snippets_execute(self):
        source = stencil_source(2, 3, None).replace(b'module demo;', b'module demo; // __import__("os").system("false")')
        k = admit_source(parse_source(source))
        offsets = set()
        def visit(value):
            if is_dataclass(value):
                if hasattr(value, 'span'):
                    offsets.add(value.span.offset)
                for field in fields(value):
                    visit(getattr(value, field.name))
            elif isinstance(value, tuple):
                for item in value:
                    visit(item)
        visit(k.source_expressions)
        for label in IDS:
            for op in planner.make_plan(k, label).operations:
                self.assertTrue(op.origins)
                self.assertTrue(set(op.origins) <= offsets)
        tree = ast.parse(Path(planner.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn('checker', node.module or '')
                self.assertNotIn('reference', node.module or '')
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, ('eval', 'exec', 'compile', '__import__'))


if __name__ == '__main__':
    unittest.main()
