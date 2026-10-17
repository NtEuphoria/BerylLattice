"""Direct lowering, pinned witness, and byte provenance contracts."""
from dataclasses import fields, is_dataclass, replace
from hashlib import sha256
import json
from pathlib import Path
import unittest
from axiom.codec import decode_plan, encode_plan, plan_digest
from axiom.core_emit import CoreEmissionError, emit_core, emit_core_kernel, EMITTER_VERSION
from axiom.frontend import admit_source, parse_source
from axiom.model import Limits, Span
from axiom.planner import make_plan
from tests.helpers import stencil_source
FIXTURES = Path(__file__).parent / 'fixtures' / 'core_emit'

class CoreEmitTests(unittest.TestCase):
    def setUp(self):
        self.source = (FIXTURES / 'minimal.ax').read_bytes()
        self.limits = Limits()
        self.kernel = admit_source(parse_source(self.source, self.limits))
        self.plan = make_plan(self.kernel, 'inline-v1')
        self.plan_bytes = encode_plan(self.plan)

    def emit(self, **kwargs):
        args = dict(source=self.source, plan_bytes=self.plan_bytes, limits=self.limits,
                    data=(0,1,2,3), initial_output=(-99,))
        args.update(kwargs)
        return emit_core(**args)

    def test_minimal_hand_reviewed_complete_witness(self):
        bundle = self.emit()
        self.assertEqual(bundle.source_bytes, (FIXTURES/'minimal.be').read_bytes())
        self.assertEqual((FIXTURES/'minimal.stdout').read_bytes(), b'-1\n0\n1\n2\n3\n30\nok  1 test, 0 assertions\n')
        self.assertEqual(bundle.artifact_kind, 'core_witness_source')
        self.assertEqual(bundle.data, (0,1,2,3))
        self.assertEqual(bundle.initial_output, (-99,))
        layout = bundle.observation_layout
        self.assertEqual((layout.status_index,layout.input_start,layout.input_count,
                          layout.output_start,layout.output_count,layout.scalar_count), (0,1,4,5,1,6))

    def test_h5_w7_preflight_initialization_and_complete_scalar_order(self):
        source = stencil_source(5,7)
        kernel = admit_source(parse_source(source,self.limits))
        code = self.emit(source=source,plan_bytes=encode_plan(make_plan(kernel,'rows2-v1')),
                         data=(0,)*47+(1024,),initial_output=(-77,)*35).source_bytes
        self.assertIn(b'fn ax_kernel(input: [i32; 48], inout output: [i32; 35]) -> i32',code)
        start = code.index(b'    let ax_v0:')
        for i in range(48):
            check = f'    if input[{i}] < 0 || input[{i}] > 1023 {{ return {i} }}'.encode()
            self.assertLess(code.index(check),start)
        init = b'    var scratch: [i32; 16] = ['+b', '.join([b'0']*16)+b']'
        self.assertIn(init,code)
        self.assertLess(code.index(init),code.index(b'    scratch[0] ='))
        self.assertGreater(code.index(init),code.index(b'{ return 47 }'))
        self.assertIn(b'    return -1\n}',code)
        self.assertNotIn(b'unsafe',code)
        self.assertNotIn(b'wrapping',code)
        self.assertIn(b'ax_v1 + ax_v0',code)
        self.assertIn(b'ax_v2 * ax_v2',code)
        prints = [b'    println(status)']
        prints += [f'    println(input[{i}])'.encode() for i in range(48)]
        prints += [f'    println(output[{i}])'.encode() for i in range(35)]
        self.assertEqual([line for line in code.splitlines() if b'println(' in line],prints)
        self.assertEqual(code.count(b'ax_kernel(input, inout output)'),1)

    def test_stable_byte_case_and_logical_identities(self):
        bundle = self.emit()
        self.assertEqual(bundle,self.emit())
        self.assertEqual(bundle.source_sha256,sha256(bundle.source_bytes).hexdigest())
        self.assertEqual(bundle.generated_source_sha256,bundle.source_sha256)
        self.assertEqual(bundle.axiom_source_bytes,self.source)
        self.assertEqual(bundle.source_digest,sha256(self.source).hexdigest())
        self.assertEqual(bundle.plan_bytes_sha256,sha256(self.plan_bytes).hexdigest())
        self.assertEqual(bundle.plan_digest,plan_digest(self.plan))
        self.assertEqual(bundle.semantic_digest,self.kernel.semantic_digest)
        self.assertEqual(bundle.emitter_version,EMITTER_VERSION)
        self.assertEqual(len(bundle.emitter_digest),64)
        changed = self.emit(data=(1,1,2,3))
        self.assertNotEqual(bundle.case_digest,changed.case_digest)
        self.assertNotEqual(bundle.source_sha256,changed.source_sha256)
        self.assertEqual(bundle.kernel_source_sha256,changed.kernel_source_sha256)

    def test_plan_names_are_labels_and_exact_serialized_bytes_bound(self):
        original = self.emit()
        changed = encode_plan(replace(self.plan,plan_id='manually-reviewed-name'))
        renamed = self.emit(plan_bytes=changed)
        self.assertEqual(original.source_bytes,renamed.source_bytes)
        self.assertEqual(original.semantic_digest,renamed.semantic_digest)
        self.assertNotEqual(original.plan_digest,renamed.plan_digest)
        self.assertEqual(renamed.plan_digest,plan_digest(decode_plan(changed,self.limits)))
        spaced = self.emit(plan_bytes=b' '+self.plan_bytes)
        self.assertEqual(original.plan_digest,spaced.plan_digest)
        self.assertNotEqual(original.plan_bytes_sha256,spaced.plan_bytes_sha256)
        self.assertNotEqual(original.case_digest,spaced.case_digest)
        source_space = self.emit(source=self.source+b'\n')
        self.assertEqual(original.semantic_digest,source_space.semantic_digest)
        self.assertNotEqual(original.source_digest,source_space.source_digest)
        self.assertNotEqual(original.case_digest,source_space.case_digest)

    def test_kernel_artifact_distinct_and_no_witness_entry(self):
        kernel = emit_core_kernel(self.source,self.plan_bytes,self.limits)
        bundle = self.emit()
        self.assertEqual(kernel.artifact_kind,'core_kernel_source')
        self.assertNotIn(b'test "',kernel.source_bytes)
        self.assertNotIn(b'println',kernel.source_bytes)
        self.assertEqual(kernel.source_bytes,bundle.kernel_source_bytes)
        self.assertEqual(kernel.source_sha256,bundle.kernel_source_sha256)
        self.assertFalse(hasattr(kernel,'data'))

    def test_mapping_complete_generated_ranges_and_exact_ast_origins(self):
        bundle = self.emit()
        valid_spans = set()
        stack = [self.kernel.source_module]
        while stack:
            item = stack.pop()
            if isinstance(item,Span): valid_spans.add(item)
            elif is_dataclass(item): stack.extend(getattr(item,f.name) for f in fields(item))
            elif isinstance(item,tuple): stack.extend(item)
        cursor,repeated = 0,[]
        for entry in bundle.mappings:
            self.assertEqual(entry.generated_offset,cursor)
            self.assertGreater(entry.generated_length,0)
            cursor += entry.generated_length
            self.assertLessEqual(cursor,len(bundle.source_bytes))
            self.assertEqual(entry.generated_source_sha256,bundle.source_sha256)
            self.assertEqual(entry.generated_file_key,'witness.be')
            self.assertTrue(entry.origins)
            for origin in entry.origins:
                self.assertIn(origin,valid_spans)
                self.assertGreater(origin.length,0)
                self.assertLessEqual(origin.offset+origin.length,len(self.source))
            if entry.operation_index is not None:
                self.assertEqual(entry.role,'user_equation')
                self.assertFalse(entry.synthetic)
                repeated.extend(entry.origins)
            else: self.assertTrue(entry.synthetic)
        self.assertEqual(cursor,len(bundle.source_bytes))
        self.assertLess(len(set(repeated)),len(repeated))
        self.assertEqual(sum(m.operation_index is not None for m in bundle.mappings),len(self.plan.operations))

    def test_multiple_contributing_origins(self):
        origins=(self.plan.operations[0].origins[0],self.plan.operations[1].origins[0])
        ops=(replace(self.plan.operations[0],origins=origins),)+self.plan.operations[1:]
        bundle=self.emit(plan_bytes=encode_plan(replace(self.plan,operations=ops)))
        entry=next(m for m in bundle.mappings if m.operation_index==0)
        self.assertEqual(tuple(span.offset for span in entry.origins),origins)

    def test_non_ast_or_out_of_bounds_origins_fail_closed(self):
        for origins in ((len(self.source),),(len(self.source)+1,),
                        (self.source.index(b'image:')+2,),()):
            with self.subTest(origins=origins),self.assertRaisesRegex(CoreEmissionError,'ORIGIN'):
                ops=(replace(self.plan.operations[0],origins=origins),)+self.plan.operations[1:]
                self.emit(plan_bytes=encode_plan(replace(self.plan,operations=ops)))

    def test_tampered_or_stale_plan_fails_fresh_check(self):
        with self.assertRaisesRegex(CoreEmissionError,'SEMANTIC_DIGEST_MISMATCH'):
            self.emit(plan_bytes=encode_plan(replace(self.plan,semantic_digest='0'*64)))
        ops=(replace(self.plan.operations[0],value=2),)+self.plan.operations[1:]
        with self.assertRaises(CoreEmissionError):
            self.emit(plan_bytes=encode_plan(replace(self.plan,operations=ops)))
        with self.assertRaises(CoreEmissionError):
            self.emit(source=self.source.replace(b'H = 1',b'H = 2'))

    def test_unknown_opcode_cannot_fall_through(self):
        obj=json.loads(self.plan_bytes)
        obj['operations'][0]['opcode']='foreign_call'
        with self.assertRaises(ValueError): self.emit(plan_bytes=json.dumps(obj).encode())

    def test_checker_budget_and_cap_cannot_be_bypassed(self):
        with self.assertRaisesRegex(CoreEmissionError,'CHECK_STEPS_EXHAUSTED'):
            self.emit(limits=Limits(check_steps=1))
        source=stencil_source(1,1,cap=0)
        kernel=admit_source(parse_source(source,self.limits))
        with self.assertRaisesRegex(CoreEmissionError,'CONSTRAINT'):
            self.emit(source=source,plan_bytes=encode_plan(make_plan(kernel,'materialize-v1')))

    def test_exact_i32_tuple_boundary(self):
        for data in ((1,2),[0,1,2,3],(True,1,2,3),(2**31,1,2,3)):
            with self.subTest(data=data),self.assertRaises(CoreEmissionError): self.emit(data=data)
        for output in ((),[0],(True,),(-2**31-1,)):
            with self.subTest(output=output),self.assertRaises(CoreEmissionError): self.emit(initial_output=output)
        self.assertIn(b'[-2147483648]',self.emit(initial_output=(-2**31,)).source_bytes)

    def test_huge_scratch_rejected_before_allocation(self):
        with self.assertRaisesRegex(CoreEmissionError,'CORE_AGGREGATE_LIMIT'):
            self.emit(plan_bytes=encode_plan(replace(self.plan,scratch_capacity_cells=2147483647)))

if __name__=='__main__': unittest.main()
