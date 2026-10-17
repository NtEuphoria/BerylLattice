"""Source oracle versus independently interpreted, serialized physical streams."""
from itertools import product
import json
import random
import unittest

from axiom.checker import check_plan
from axiom.codec import canonical_json, decode_plan, encode_plan
from axiom.frontend import admit_source, parse_source
from axiom.model import Limits
from axiom.planner import make_plan
from axiom.reference import evaluate_source
from tests.helpers import stencil_source
from tests.plan_interpreter import interpret_plan

IDS = ('inline-v1', 'rows2-v1', 'materialize-v1')


def checked_case(h, w):
    module = parse_source(stencil_source(h, w, None))
    kernel = admit_source(module)
    plans = []
    for label in IDS:
        data = encode_plan(make_plan(kernel, label))
        plan = decode_plan(data, Limits())
        checked = check_plan(kernel, plan, Limits())
        if not checked.eligible:
            raise AssertionError(checked)
        plans.append(plan)
    return module, kernel, plans


class ConformanceTests(unittest.TestCase):
    def compare(self, module, kernel, plans, data):
        expected = evaluate_source(module, data, [-991]* (kernel.height*kernel.width))
        self.assertEqual(expected.status, 'success')
        self.assertEqual(expected.input_after, tuple(data))
        for p in plans:
            self.assertEqual(interpret_plan(p, data, kernel.height*kernel.width), expected.output,
                             (kernel.height, kernel.width, p.plan_id, data))

    def test_edge_shapes(self):
        for h, w in ((1,1),(1,7),(7,1),(2,3),(3,2),(5,7),(15,15),(1,127),(127,1)):
            module, kernel, plans = checked_case(h, w)
            size = (h+1)*(w+1)
            cases = ((0,)*size, (1023,)*size,
                     tuple((i*193+17) % 1024 for i in range(size)))
            for data in cases:
                self.compare(module, kernel, plans, data)

    def test_restricted_alphabet_exhaustion_21222_inputs(self):
        total = 0
        shape_counts = []
        for h, w in ((1,1),(1,2),(2,1),(2,2)):
            module, kernel, plans = checked_case(h, w)
            count = 0
            for data in product((0,1,1023), repeat=(h+1)*(w+1)):
                self.compare(module, kernel, plans, data)
                count += 1
            shape_counts.append(count)
            total += count
        self.assertEqual(shape_counts, [81,729,729,19683])
        self.assertEqual(total, 21222)

    def test_seeded_shapes_2048_inputs(self):
        rng = random.Random(20261015)
        count = 0
        for h in range(1,9):
            for w in range(1,9):
                module, kernel, plans = checked_case(h, w)
                for _ in range(32):
                    data = tuple(rng.randrange(1024) for _ in range((h+1)*(w+1)))
                    self.compare(module, kernel, plans, data)
                    count += 1
        self.assertEqual(count, 2048)

    def test_serialized_wrong_neighbor_alias_and_overwrite_mutants(self):
        module, k, plans = checked_case(2,3)
        data = tuple(range(12))
        expected = evaluate_source(module, data, (0,)*6).output
        mutations = []
        inline = json.loads(encode_plan(plans[0]))
        load = next(o for o in inline['operations'] if o['opcode'] == 'input_load')
        load['index'] = 1
        mutations.append(('wrong neighbor', inline))
        alias = json.loads(encode_plan(plans[1]))
        alias['scratch_capacity_cells'] = 4
        for op in alias['operations']:
            if op['opcode'] in ('scratch_load', 'scratch_store'):
                op['index'] %= 4
        mutations.append(('one row alias', alias))
        overwrite = json.loads(encode_plan(plans[1]))
        ops = overwrite['operations']
        first_output = next(i for i, op in enumerate(ops) if op['opcode'] == 'output_store')
        first_store = next(op for op in ops if op['opcode'] == 'scratch_store')
        # Overwrite slot one after the first output, before neighboring consumers.
        ops.insert(first_output+1, dict(first_store, operands=[0], index=1))
        mutations.append(('early overwrite', overwrite))
        for label, obj in mutations:
            with self.subTest(label=label):
                plan = decode_plan(canonical_json(obj), Limits())
                actual = interpret_plan(plan, data, 6)
                self.assertNotEqual(actual, expected, (label, data, expected, actual))
                checked = check_plan(k, plan, Limits())
                self.assertIn(checked.semantic_status, ('invalid', 'unknown'))
                self.assertFalse(checked.eligible)
                if checked.semantic_status == 'invalid':
                    self.assertIsNotNone(checked.witness)

    def test_equivalent_mutant_must_not_be_reported_invalid(self):
        module, k, plans = checked_case(2,3)
        obj = json.loads(encode_plan(plans[0]))
        # Commuting a sum preserves integers but changes exact expression shape.
        add = next(op for op in obj['operations'] if op['opcode'] == 'add')
        add['operands'].reverse()
        p = decode_plan(canonical_json(obj), Limits())
        checked = check_plan(k, p, Limits())
        self.assertEqual(checked.semantic_status, 'unknown')
        self.assertIsNone(checked.witness)
        for data in ((0,)*12, (1023,)*12, tuple(range(12))):
            self.compare(module, k, (p,), data)


if __name__ == '__main__':
    unittest.main()
