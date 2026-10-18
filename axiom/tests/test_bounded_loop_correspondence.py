"""Bounded hints have independent, frozen finite-stream correspondence."""
from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

from axiom.frontend import admit_source, parse_source
from axiom.model import Limits
from axiom.planner import make_plan, PLAN_IDS
from tests.helpers import stencil_source


def kernel(h=3, w=4):
    return admit_source(parse_source(stencil_source(h, w, None)))


def stream_hash(plan):
    data = [plan.scratch_capacity_cells, [[o.opcode, o.dst, list(o.operands),
                                         o.index, o.value] for o in plan.operations]]
    return hashlib.sha256(json.dumps(data, separators=(',', ':')).encode()).hexdigest()


class BoundedLoopTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('axiom.bounded_loop_correspondence'),
                             'independent bounded correspondence is not implemented')
        from axiom.bounded_loop_codec import encode_loop_program, decode_loop_program
        from axiom.bounded_loop_correspondence import validate_loop_correspondence, expand_loop_program
        from axiom.bounded_loop_planner import make_loop_program
        self.encode, self.decode = encode_loop_program, decode_loop_program
        self.match, self.expand, self.generate = validate_loop_correspondence, expand_loop_program, make_loop_program

    def test_all_955_shapes_three_schedules_match_frozen_baseline(self):
        frozen = json.loads((Path(__file__).parent/'fixtures/bounded_loop_v1_stream_hashes.json').read_text())['streams']
        self.assertEqual(len(frozen), 955*3)
        maximum_work = 0
        for key, digest in frozen.items():
            h, w, schedule = key.split(',')
            k = kernel(int(h), int(w))
            p = make_plan(k, schedule)
            hint = self.encode(self.generate(k, schedule))
            result = self.match(k, p, hint, Limits())
            self.assertEqual(stream_hash(result.expanded_plan), digest, key)
            self.assertIs(result.plan, p)
            self.assertEqual(result.expanded_operations, len(p.operations))
            maximum_work = max(maximum_work, result.work_steps)
        self.assertLessEqual(maximum_work, 100000)

    def test_raw_identity_and_metadata_do_not_grant_authority(self):
        k = kernel()
        p = replace(make_plan(k, 'rows2-v1'), plan_id='renamed finite plan')
        program = replace(self.generate(k, 'rows2-v1'), label='unrelated label')
        hint = self.encode(program)
        a = self.match(k, p, hint, Limits())
        b = self.match(k, p, b' '+hint+b'\n', Limits())
        self.assertNotEqual(a.hint_digest, b.hint_digest)
        self.assertEqual(a.plan_digest, b.plan_digest)
        self.assertEqual(a.source_digest, k.source_digest)
        self.assertFalse(hasattr(a, 'eligible'))
        self.assertEqual(a.hint_bytes, hint)

    def test_mutated_executable_stream_and_specialization_reject(self):
        from axiom.bounded_loop_model import HintError
        k = kernel()
        p = make_plan(k, 'rows2-v1')
        program = self.generate(k, 'rows2-v1')
        variants = [replace(program, scratch_capacity_cells=program.scratch_capacity_cells+1),
                    replace(program, width=program.width+1),
                    replace(program, source_digest='0'*64),
                    replace(program, semantic_digest='0'*64),
                    replace(program, body=program.body[:-1]),
                    replace(program, body=program.body+(program.body[-1],))]
        for changed in variants:
            with self.subTest(changed=changed), self.assertRaises(HintError):
                self.match(k, p, self.encode(changed), Limits())
        ops = p.operations
        changed = replace(p, operations=ops+(replace(ops[-1], index=0),))
        with self.assertRaises(HintError):
            self.match(k, changed, self.encode(program), Limits())

    def test_empty_nested_traversal_exhausts_before_expanding(self):
        from axiom.bounded_loop_model import Loop, HintError, HintLimits
        k = kernel()
        program = self.generate(k, 'inline-v1')
        leaf = Loop('z', 0, 0, ())
        for name in ('c', 'b', 'a'):
            leaf = Loop(name, 0, 256, (leaf,))
        program = replace(program, body=(leaf,))
        with self.assertRaises(HintError) as caught:
            self.expand(k, program, Limits(), HintLimits())
        self.assertEqual(caught.exception.code, 'HINT_WORK_LIMIT')

    def test_hostile_decoder_bounds_and_exact_types(self):
        from axiom.bounded_loop_model import HintError, HintLimits
        raw = self.encode(self.generate(kernel(), 'inline-v1'))
        obj = json.loads(raw)
        for field, value in [('height', True), ('width', -1), ('scratch_capacity_cells', 2**40)]:
            bad = dict(obj, **{field: value})
            with self.subTest(field=field), self.assertRaises(HintError):
                self.decode(json.dumps(bad).encode())
        for bad in (b'{"a":1,"a":2}', b'['*1000+b']'*1000, raw+b' x', b'\xff', b'0'*70000):
            with self.assertRaises(HintError):
                self.decode(bad)
        with self.assertRaises(HintError):
            self.decode(raw, HintLimits(encoded_bytes=32))

    def test_scope_index_and_bound_mutations(self):
        from axiom.bounded_loop_model import Loop, Primitive, IndexExpr, IndexTerm, HintError
        k = kernel()
        program = self.generate(k, 'inline-v1')
        for body in ((Primitive('add','bad',('missing','missing')),),
                     (Loop('r',0,1,(Primitive('const','x',value=1),)), Primitive('add','y',('x','x'))),
                     (Primitive('const','x',value=1), Primitive('const','x',value=2)),
                     (Loop('r',0,1,(Loop('r',0,1,()),)),),
                     (Loop('r',0,1,(Primitive('input_load','x',index=IndexExpr(-1)),)),),
                     (Loop('r',0,1,(Primitive('input_load','x',index=IndexExpr(2147483647,(IndexTerm(1,'r',1),IndexTerm(-1,'r',1)))),)),)):
            with self.subTest(body=body), self.assertRaises(HintError):
                self.expand(k, replace(program, body=body), Limits())


if __name__ == '__main__':
    unittest.main()
