"""Hostile bounded hint bytes, lexical records, and evaluation order."""
from dataclasses import replace
import json
import unittest

from axiom.bounded_loop_codec import decode_loop_program, encode_loop_program
from axiom.bounded_loop_correspondence import expand_loop_program, validate_loop_correspondence
from axiom.bounded_loop_model import HintError, HintLimits, IndexExpr, IndexTerm, Loop, Primitive
from axiom.bounded_loop_planner import make_loop_program
from axiom.frontend import admit_source, parse_source
from axiom.model import Limits
from axiom.planner import make_plan
from tests.helpers import stencil_source


class HostileHintTests(unittest.TestCase):
    def setUp(self):
        self.kernel = admit_source(parse_source(stencil_source(3, 4, None)))
        self.program = make_loop_program(self.kernel, 'inline-v1')

    def expand(self, body, **kw):
        return expand_loop_program(self.kernel, replace(self.program, body=body), Limits(), **kw)

    def test_index_intermediates_before_parity_and_cancellation(self):
        expressions = (IndexExpr(0,(IndexTerm(0,'r',2147483647,True),)),
                       IndexExpr(0,(IndexTerm(2147483647,'r',1),)),
                       IndexExpr(2147483647,(IndexTerm(1,'r'),IndexTerm(-1,'r'))))
        for expr in expressions:
            with self.subTest(expr=expr), self.assertRaises(HintError) as caught:
                self.expand((Loop('r',1,2,(Primitive('input_load','a',index=expr),)),))
            self.assertEqual(caught.exception.code,'HINT_INDEX_OVERFLOW')

    def test_modulo_two_is_nonnegative_even_for_negative_component(self):
        expr = IndexExpr(0, (IndexTerm(1, 'r', -2, True),))
        p = self.expand((Loop('r', 1, 2, (Primitive('input_load', 'a', index=expr),)),))
        self.assertEqual(p.operations[0].index, 1)

    def test_index_term_order_not_normalized(self):
        # Final result zero is safe only when the first intermediate is safe.
        safe = IndexExpr(2147483647,(IndexTerm(-2147483647,'r'),))
        p = self.expand((Loop('r',1,2,(Primitive('input_load','a',index=safe),)),))
        self.assertEqual(p.operations[0].index,0)

    def test_exact_work_quota_cutpoint_includes_scope_cleanup(self):
        plan = make_plan(self.kernel,'inline-v1')
        raw = encode_loop_program(self.program)
        result = validate_loop_correspondence(self.kernel,plan,raw,Limits())
        validate_loop_correspondence(self.kernel,plan,raw,Limits(),HintLimits(work_steps=result.work_steps))
        with self.assertRaises(HintError) as caught:
            validate_loop_correspondence(self.kernel,plan,raw,Limits(),HintLimits(work_steps=result.work_steps-1))
        self.assertEqual(caught.exception.code,'HINT_WORK_LIMIT')

    def test_operation_quota_and_repeated_empty_loop_work(self):
        with self.assertRaises(HintError) as caught:
            expand_loop_program(self.kernel,self.program,Limits(plan_operations=1))
        self.assertEqual(caught.exception.code,'HINT_OPERATION_LIMIT')
        leaf=Loop('c',0,256,())
        body=(Loop('a',0,256,(Loop('b',0,256,(leaf,)),)),)
        with self.assertRaises(HintError) as caught:
            self.expand(body)
        self.assertEqual(caught.exception.code,'HINT_WORK_LIMIT')

    def test_depth_and_syntax_limits_before_recursion(self):
        node=Loop('v0',0,0,())
        for i in range(1,100):
            node=Loop('v'+str(i),0,0,(node,))
        with self.assertRaises(HintError) as caught:
            self.expand((node,))
        self.assertEqual(caught.exception.code,'HINT_DEPTH_LIMIT')
        with self.assertRaises(HintError) as caught:
            self.expand((Primitive('const','a',value=1),)*4097)
        self.assertEqual(caught.exception.code,'HINT_SYNTAX_LIMIT')

    def test_bool_fields_and_oversized_terms_reject(self):
        for node in (Loop('r',False,1,()),Loop('r',0,True,()),
                     Primitive('const','a',value=True),Primitive('const','a',value=2**31),
                     Loop('r',0,1,(Primitive('input_load','a',index=IndexExpr(True)),)),
                     Loop('r',0,1,(Primitive('input_load','a',index=IndexExpr(0,(IndexTerm(True,'r'),))),)),
                     Loop('r',0,1,(Primitive('input_load','a',index=IndexExpr(0,(IndexTerm(1,'r',modulo2=1),))),))):
            with self.subTest(node=node), self.assertRaises(HintError):
                self.expand((node,))

    def test_zero_trip_body_still_has_valid_lexical_names(self):
        with self.assertRaises(HintError):
            self.expand((Loop('r',0,0,(Primitive('add','a',('absent','absent')),)),))
        with self.assertRaises(HintError):
            self.expand((Loop('r',0,0,(Primitive('input_load','a',index=IndexExpr(0,(IndexTerm(1,'outside'),))),)),))

    def test_bytes_unknown_fields_floats_duplicates_and_source_boundary(self):
        raw=encode_loop_program(self.program)
        for field,value in [('height',1.0),('height',127),('unexpected',1),('format_version',2)]:
            obj=json.loads(raw);obj[field]=value
            with self.subTest(field=field),self.assertRaises(HintError):
                decode_loop_program(json.dumps(obj).encode())
        for raw in (b'{"height":1,"height":2}', b'1e10', b'"\\ud800"', b'12345678901234567890'):
            with self.assertRaises(HintError):
                decode_loop_program(raw)

    def test_hint_limits_cannot_raise_fixed_ceiling(self):
        for field,value in [('encoded_bytes',65537),('syntax_nodes',4097),('nesting_depth',17),
                            ('work_steps',100001),('work_steps',True),('work_steps',0)]:
            with self.assertRaises(ValueError):
                HintLimits(**{field:value})

    def test_valid_origins_and_labels_are_metadata(self):
        p=make_plan(self.kernel,'inline-v1')
        changed=replace(self.program,label='changed metadata',body=(replace(self.program.body[0],origins=(123,)),)+self.program.body[1:])
        result=validate_loop_correspondence(self.kernel,p,encode_loop_program(changed),Limits())
        self.assertIs(result.plan,p)

    def test_wrong_parity_bounds_and_grouping_fail_actual_stream(self):
        program=make_loop_program(self.kernel,'rows2-v1')
        plan=make_plan(self.kernel,'rows2-v1')
        def transform(body,mode):
            result=[]
            for node in body:
                if type(node) is Loop:
                    node=replace(node,body=transform(node.body,mode))
                elif mode=='parity' and node.index:
                    node=replace(node,index=replace(node.index,terms=tuple(replace(t,modulo2=False) for t in node.index.terms)))
                elif mode=='grouping' and node.opcode=='add' and node.dst=='abd':
                    node=replace(node,operands=('ab','bvalue'))
                result.append(node)
            return tuple(result)
        variants=[replace(program,body=transform(program.body,m)) for m in ('parity','grouping')]
        variants.append(replace(program,body=(program.body[0],replace(program.body[1],stop=1))+program.body[2:]))
        # A dead primitive is still part of the correspondence obligation.
        variants.append(replace(program,body=program.body+(Primitive('const','dead',value=2),)))
        for changed in variants:
            with self.subTest(changed=changed),self.assertRaises(HintError):
                validate_loop_correspondence(self.kernel,plan,encode_loop_program(changed),Limits())


if __name__=='__main__':
    unittest.main()
