"""Golden control for checker performance work: every CheckResult field, exactly.

The fixture was recorded from the checker before any speed change. Any
optimization must reproduce status, reason, witness, metrics and the exact
work counter for every case, including broken plans and tight quotas.
Regenerate only for an intended semantic change:
    PYTHONPATH=src py -3 tests/test_checker_golden.py --write
"""
from dataclasses import fields, replace
import json
from pathlib import Path
import sys
import unittest

from axiom.checker import check_plan
from axiom.frontend import admit_source, parse_source
from axiom.model import Limits
from axiom.plan_format import Operation
from axiom.planner import PLAN_IDS, make_plan

FIXTURE = Path(__file__).parent / 'fixtures' / 'checker_golden.json'
SOURCE = '''module golden;
shape H = {h};
shape W = {w};
input image: i32[H+1,W+1] in 0..=1023;
let p[r in 0..H+1,c in 0..W+1] =
  (image[r,c]+1)*(image[r,c]+1);
output result[r in 0..H,c in 0..W] =
  ((p[r,c]+p[r,c+1])+p[r+1,c])+p[r+1,c+1];
require plan_workspace_bytes <= {cap};
prefer multiplication_ops;
'''


def kernel(h, w, cap):
    return admit_source(parse_source(SOURCE.format(h=h, w=w, cap=cap).encode()))


def mutate(plan, kind):
    ops = list(plan.operations)
    first = lambda opcode: next(i for i, op in enumerate(ops) if op.opcode == opcode)
    if kind == 'const':
        i = first('const')
        ops[i] = replace(ops[i], value=ops[i].value + 1)
    elif kind == 'const_max':  # reaches the arithmetic-overflow witness path
        i = first('const')
        ops[i] = replace(ops[i], value=2147483647)
    elif kind == 'swap':
        i = first('add')
        ops[i] = replace(ops[i], operands=tuple(reversed(ops[i].operands)))
    elif kind == 'mul_to_add':
        i = first('mul')
        ops[i] = replace(ops[i], opcode='add')
    elif kind == 'drop_output':
        del ops[max(i for i, op in enumerate(ops) if op.opcode == 'output_store')]
    elif kind == 'duplicate_output':
        i = first('output_store')
        ops.insert(i + 1, ops[i])
    elif kind == 'input_oob':
        i = first('input_load')
        ops[i] = replace(ops[i], index=10 ** 6)
    elif kind == 'wrong_input':
        i = first('input_load')
        ops[i] = replace(ops[i], index=ops[i].index + 1)
    elif kind == 'scratch_uninit':
        if not any(op.opcode == 'scratch_load' for op in ops):
            return None
        i = first('scratch_store')
        del ops[i]
    elif kind == 'label':
        return replace(plan, plan_id='renamed')
    elif kind == 'bad_digest':
        return replace(plan, semantic_digest='0' * 64)
    return replace(plan, operations=tuple(ops))


def cases():
    for h, w in ((1, 1), (2, 3), (5, 7), (1, 15), (15, 1), (15, 15)):
        for cap in (0, 64, 128, 1024):
            k = kernel(h, w, cap)
            for plan_id in PLAN_IDS:
                yield f'{h}x{w} cap={cap} {plan_id}', k, make_plan(k, plan_id), Limits(), None
    k = kernel(5, 7, 1024)
    for plan_id in PLAN_IDS:
        plan = make_plan(k, plan_id)
        for kind in ('const', 'const_max', 'swap', 'mul_to_add', 'drop_output', 'duplicate_output', 'input_oob',
                     'wrong_input', 'scratch_uninit', 'label', 'bad_digest'):
            broken = mutate(plan, kind)
            if broken is not None:
                yield f'5x7 {plan_id} {kind}', k, broken, Limits(), None
        for steps in (1, 50, 1000, 5000):
            yield f'5x7 {plan_id} steps={steps}', k, plan, replace(Limits(), check_steps=steps), None
        for nodes in (1, 100, 1000):
            yield f'5x7 {plan_id} nodes={nodes}', k, plan, replace(Limits(), expression_nodes=nodes), None
        yield f'5x7 {plan_id} extra_cap=0', k, plan, Limits(), 0


def snapshot(k, plan, limits, extra):
    result = check_plan(k, plan, limits, additional_cap=extra)
    return json.loads(json.dumps({f.name: getattr(result, f.name) for f in fields(result)}))


class CheckerGolden(unittest.TestCase):
    def test_every_field_matches_recorded_checker(self):
        golden = json.loads(FIXTURE.read_text(encoding='utf-8'))
        seen = set()
        for name, k, plan, limits, extra in cases():
            seen.add(name)
            self.assertIn(name, golden)
            self.assertEqual(snapshot(k, plan, limits, extra), golden[name], name)
        self.assertEqual(seen, set(golden))


if __name__ == '__main__':
    if '--write' in sys.argv:
        data = {name: snapshot(k, p, l, e) for name, k, p, l, e in cases()}
        FIXTURE.write_text(json.dumps(data, indent=1, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
        print(f'wrote {len(data)} cases')
    else:
        unittest.main()
