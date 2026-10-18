"""Run bounded Wasm in V8 against source and the complete finite memory state."""
import base64
from dataclasses import replace
import importlib
import importlib.util
import json
import random
import re
import shutil
import subprocess
import unittest
from hashlib import sha256
from unittest.mock import patch

from axiom.bounded_loop_codec import encode_loop_program
from axiom.bounded_loop_correspondence import expand_loop_program
from axiom.bounded_loop_model import HintError, HintLimits, IndexExpr, IndexTerm, Loop, Primitive
from axiom.bounded_loop_planner import make_loop_program
from axiom.compilation import _CompilationContext
from axiom.planner import PLAN_IDS, make_plan
from axiom.reference import evaluate_source
from axiom.frontend import parse_source
from axiom.runtime import execute_plan
from axiom.wasm import _compile_wasm_checked
from tests.helpers import stencil_source


_RUNNER = r'''
const fs = require('node:fs'), crypto = require('node:crypto');
(async () => {
 const observations = [];
 for (const c of JSON.parse(fs.readFileSync(0, 'utf8'))) {
  const bytes = Buffer.from(c.module, 'base64');
  if (!WebAssembly.validate(bytes)) throw Error('invalid module');
  const compiled = await WebAssembly.compile(bytes);
  if (WebAssembly.Module.imports(compiled).length) throw Error('imports');
  const {exports: e} = await WebAssembly.instantiate(compiled);
  if (Object.keys(e).sort().join() !== 'memory,run') throw Error('exports');
  if (e.memory.buffer.byteLength !== 65536) throw Error('memory size');
  let rejected = false;
  try { e.memory.grow(1); } catch (_) { rejected = true; }
  if (!rejected) throw Error('memory grew');
  const words = new Int32Array(e.memory.buffer);
  words.fill(0x6b6b6b6b);
  const runs = [];
  const digest = () => crypto.createHash('sha256').update(new Uint8Array(e.memory.buffer)).digest('hex');
  for (const r of c.runs) {
   words.set(r.input, 0); words.set(r.initial, c.output_offset / 4);
   const before = digest(), status = e.run(), after = digest();
   runs.push({status, output: Array.from(words.slice(c.output_offset / 4,
     c.output_offset / 4 + c.output_count)), input: Array.from(words.slice(0, c.input_count)),
     memory: after, unchanged: before === after});
  }
  observations.push(runs);
 }
 process.stdout.write(JSON.stringify(observations));
})().catch(e => { console.error(e); process.exitCode = 1; });
'''


class CompactWasmTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('axiom.bounded_loop_wasm'),
                             'compact Wasm backend is missing')
        self.backend = importlib.import_module('axiom.bounded_loop_wasm')

    def own(self, h=2, w=3, schedule='rows2-v1', program_transform=None):
        source = stencil_source(h, w, None)
        context = _CompilationContext(source)
        program = make_loop_program(context.kernel, schedule)
        plan = make_plan(context.kernel, schedule)
        if program_transform:
            program = program_transform(program)
            plan = expand_loop_program(context.kernel, program, context.limits)
        candidate = context.candidate(plan)
        owned = context.authorize(candidate, context.check(candidate))
        return owned, encode_loop_program(program)

    def case(self, artifact, runs):
        return dict(module=base64.b64encode(artifact.module_bytes).decode(),
                    output_offset=artifact.output_offset, output_count=artifact.output_count,
                    input_count=artifact.input_count, runs=runs)

    def run_modules(self, cases):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'real Node/V8 is required')
        p = subprocess.run([node, '-e', _RUNNER], input=json.dumps(cases),
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def assert_oracles(self, owned, hint, runs):
        artifact = self.backend._compile_wasm_compact(owned, hint)
        finite = _compile_wasm_checked(owned)
        compact_runs, finite_runs = self.run_modules([self.case(a, runs) for a in (artifact, finite)])
        self.assertEqual(compact_runs, finite_runs, 'all 65536 memory bytes must match finite Wasm')
        for request, result in zip(runs, compact_runs):
            source = evaluate_source(parse_source(owned.source), request['input'], request['initial'])
            self.assertEqual(source, execute_plan(owned.source, owned.plan_bytes,
                                                 request['input'], request['initial']))
            self.assertEqual(result['output'], list(source.output))
            self.assertEqual(result['input'], list(source.input_after))
            self.assertEqual(result['status'], 0 if source.first_bad_index is None else source.first_bad_index+1)
            if result['status']:
                self.assertTrue(result['unchanged'])
        return artifact, finite

    def test_all_schedules_boundary_shapes_reuse_and_full_failure_preservation(self):
        randomizer = random.Random(128395)
        for h, w in ((1,1), (2,3), (5,7), (15,15), (1,127), (127,1)):
            for schedule in PLAN_IDS:
                with self.subTest(shape=(h,w), schedule=schedule):
                    owned, hint = self.own(h,w,schedule)
                    count = (h+1)*(w+1)
                    data = [[0]*count, [1023]*count, list(range(count))]
                    data += [[randomizer.randrange(1024) for _ in range(count)] for _ in range(5)]
                    for index in (0,count//2,count-1):
                        for bad in (-2147483648,-1,1024,2147483647):
                            row = [7]*count; row[index] = bad
                            if index < count-1: row[-1] = -1
                            data.append(row)
                    data += [[9]*count]
                    runs = [dict(input=row, initial=[-100-i-j for i in range(h*w)]) for j,row in enumerate(data)]
                    compact, finite = self.assert_oracles(owned,hint,runs)
                    if (h,w) == (15,15):
                        self.assertLess(len(compact.module_bytes)*10, len(finite.module_bytes))
                        self.assertLess(compact.local_count*10, finite.local_count)

    def test_metadata_and_correspondence_are_fresh_and_exact(self):
        owned, hint = self.own()
        artifact = self.backend._compile_wasm_compact(owned,hint)
        self.assertEqual(artifact.codegen_version, 'beryl-bounded-loop-wasm-v1')
        self.assertEqual(artifact.hint_digest, sha256(hint).hexdigest())
        self.assertEqual(artifact.plan_digest, sha256(owned.plan_bytes).hexdigest())
        self.assertEqual(artifact.source_digest, sha256(owned.source).hexdigest())
        spaced = self.backend._compile_wasm_compact(owned,b' '+hint+b'\n')
        self.assertEqual(artifact.module_bytes,spaced.module_bytes)
        self.assertNotEqual(artifact.hint_digest,spaced.hint_digest)
        for bad in (replace(owned), replace(owned, plan=replace(owned.plan)), object()):
            with self.assertRaises(ValueError): self.backend._compile_wasm_compact(bad,hint)
        wrong = encode_loop_program(make_loop_program(owned.kernel,'inline-v1'))
        for bad in (wrong,b'{}',bytearray(hint),hint+b' x',b'x'*65537):
            with self.assertRaises(HintError): self.backend._compile_wasm_compact(owned,bad)
        for limits in (HintLimits(syntax_nodes=1),HintLimits(work_steps=1),HintLimits(nesting_depth=1)):
            with self.assertRaises(HintError): self.backend._compile_wasm_compact(owned,hint,hint_limits=limits)
        owned.owner.close()
        with self.assertRaises(ValueError): self.backend._compile_wasm_compact(owned,hint)

    def test_negative_parity_signed_literals_and_lexical_local_reuse(self):
        def transform(program):
            # A dead but exact checked extension forces negative parity and sibling reuse.
            extension = []
            for name in ('x','y','z'):
                extension.append(Loop(name,0,3,(
                    Primitive('const','literal',value=-2147483648),
                    Primitive('scratch_store',operands=('literal',),index=IndexExpr(0,(IndexTerm(1,name,-3,True),))),
                )))
            return replace(program,scratch_capacity_cells=max(program.scratch_capacity_cells,2),
                           body=program.body+tuple(extension)+(Loop('empty',256,256,()),))
        owned,hint = self.own(1,1,'inline-v1',transform)
        artifact,_ = self.assert_oracles(owned,hint,[dict(input=[0,1,2,3],initial=[-9]),dict(input=[9,8,7,6],initial=[-8])])
        self.assertLess(artifact.local_count,30)

    def test_maximum_nested_label_depth_preserves_parent_locals(self):
        def nest(program):
            body = program.body
            for i in range(14):
                body = (Loop('outer'+str(i),0,1,body),)
            return replace(program,body=body)
        owned,hint = self.own(2,3,'rows2-v1',nest)
        self.assert_oracles(owned,hint,[dict(input=list(range(12)),initial=[-19]*6)])

    def test_real_engine_observations_detect_mutated_branch_operand_index_and_store(self):
        owned,hint = self.own(2,3,'rows2-v1')
        runs = [dict(input=list(range(12)),initial=[-73]*6),
                dict(input=[1023-i for i in range(12)],initial=[-85]*6)]
        good = self.backend._compile_wasm_compact(owned,hint)
        loop, body, address = self.backend._loop, self.backend._body, self.backend._address
        def operand(*args):
            binary, count = body(*args)
            binary, changed = re.subn(b'\x20(.)\x20(.)\x6a',
                                      lambda m: b'\x20'+m[1]+b'\x20'+m[1]+b'\x6a', binary, count=1)
            self.assertEqual(changed,1)
            return binary,count
        mutations = (
            ('branch', '_loop', lambda *a: loop(*a).replace(b'\x0c\x00',b'\x0c\x01')),
            ('operand', '_body', operand),
            ('index', '_index', lambda *a: b'\x41\x00'),
            ('store', '_address', lambda expr,variables,base: address(
                expr,variables,base+4 if base == good.output_offset else base)),
        )
        for name,target,mutant in mutations:
            with self.subTest(mutation=name), patch.object(self.backend,target,side_effect=mutant):
                bad = self.backend._compile_wasm_compact(owned,hint)
            actual,expected = self.run_modules([self.case(a,runs) for a in (bad,good)])
            self.assertNotEqual(actual,expected,name)

    def test_fresh_correspondence_trace_and_hostile_zero_trip_expansion(self):
        from axiom.compilation_trace import CompilationTrace
        owned,hint = self.own()
        trace = CompilationTrace()
        owned.owner.trace = trace
        self.backend._compile_wasm_compact(owned,hint)
        self.backend._compile_wasm_compact(owned,hint)
        report = trace.report()
        self.assertEqual(report['phases']['loop_correspondence']['calls'],2)
        self.assertEqual(report['phases']['code_emission']['calls'],2)
        self.assertEqual(report['counts']['loop_correspondences'],2)
        program = make_loop_program(owned.kernel,'rows2-v1')
        leaf = Loop('z',0,0,())
        for name in ('c','b','a'):
            leaf = Loop(name,0,256,(leaf,))
        with self.assertRaises(HintError) as caught:
            self.backend._compile_wasm_compact(owned,encode_loop_program(replace(program,body=(leaf,))))
        self.assertEqual(caught.exception.code,'HINT_WORK_LIMIT')

    def test_hint_index_overflow_rejected_even_when_later_terms_cancel(self):
        owned,hint = self.own(1,1,'inline-v1')
        program = make_loop_program(owned.kernel,'inline-v1')
        extra = Loop('i',0,1,(Primitive('input_load','bad',index=IndexExpr(2147483647,(
            IndexTerm(1,'i',1),IndexTerm(-1,'i',1)))),))
        with self.assertRaises(HintError) as caught:
            self.backend._compile_wasm_compact(owned,encode_loop_program(replace(program,body=program.body+(extra,))))
        self.assertEqual(caught.exception.code,'HINT_INDEX_OVERFLOW')


if __name__ == '__main__':
    unittest.main()
