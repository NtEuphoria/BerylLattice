"""Execute emitted modules in a real Wasm engine and compare independent observations."""
import base64
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
import importlib
import importlib.util
import json
import random
import shutil
import subprocess
import unittest

from axiom.codec import DecodeError, encode_plan
from axiom.frontend import admit_source, parse_source
from axiom.model import DiagnosticError, Limits
from axiom.plan_format import Operation
from axiom.planner import PLAN_IDS, make_plan
from axiom.reference import evaluate_source
from axiom.runtime import execute_plan
from tests.helpers import stencil_source


_NODE_RUNNER = r'''
const fs = require('node:fs');
async function main() {
  const cases = JSON.parse(fs.readFileSync(0, 'utf8'));
  const observed = [];
  for (const item of cases) {
    const bytes = Buffer.from(item.module, 'base64');
    if (!WebAssembly.validate(bytes)) throw new Error('Emitted module is invalid');
    const module = await WebAssembly.compile(bytes);
    if (WebAssembly.Module.imports(module).length) throw new Error('Unexpected import');
    const instance = await WebAssembly.instantiate(module);
    const {memory, run} = instance.exports;
    if (memory.buffer.byteLength !== 65536) throw new Error('Memory must be one page');
    let growthRejected = false;
    try { memory.grow(1); } catch (_) { growthRejected = true; }
    if (!growthRejected) throw new Error('Memory maximum must be one page');
    const i32 = new Int32Array(memory.buffer);
    const runs = [];
    for (const request of item.runs) {
      i32.fill(0x6b6b6b6b);
      i32.set(request.input, item.input_offset / 4);
      i32.set(request.initial, item.output_offset / 4);
      const before = new Uint8Array(memory.buffer).slice();
      const status = run();
      runs.push({status,
        input: Array.from(i32.slice(item.input_offset / 4,
                                   item.input_offset / 4 + item.input_count)),
        output: Array.from(i32.slice(item.output_offset / 4,
                                    item.output_offset / 4 + item.output_count)),
        scratch: Array.from(i32.slice(item.output_offset / 4 + item.output_count,
                                     item.output_offset / 4 + item.output_count + (item.scratch_count || 0))),
        unchanged: before.every((value, index) => value === new Uint8Array(memory.buffer)[index])});
    }
    observed.push({exports: Object.keys(instance.exports).sort(), runs});
  }
  process.stdout.write(JSON.stringify(observed));
}
main().catch(error => { console.error(error); process.exitCode = 1; });
'''


class WasmTests(unittest.TestCase):
    def backend(self):
        self.assertIsNotNone(importlib.util.find_spec('axiom.wasm'),
                             'bounded Wasm backend is missing')
        return importlib.import_module('axiom.wasm')

    def plan(self, source, name='inline-v1'):
        return make_plan(admit_source(parse_source(source)), name)

    def compile(self, source, name='inline-v1', **kwargs):
        return self.backend().compile_wasm(source, encode_plan(self.plan(source, name)), **kwargs)

    def case(self, artifact, runs, scratch_count=0):
        return dict(module=base64.b64encode(artifact.module_bytes).decode('ascii'),
                    input_offset=artifact.input_offset, output_offset=artifact.output_offset,
                    input_count=artifact.input_count, output_count=artifact.output_count,
                    runs=runs, scratch_count=scratch_count)

    def execute_modules(self, cases):
        node = shutil.which('node')
        if node is None:
            self.skipTest('Node is required to execute actual Wasm modules')
        completed = subprocess.run([node, '-e', _NODE_RUNNER],
                                   input=json.dumps(cases), capture_output=True,
                                   text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, '')
        return json.loads(completed.stdout)

    def test_artifact_is_immutable_deterministic_and_binds_exact_bytes(self):
        source = stencil_source(5, 7, cap=None)
        plan_bytes = encode_plan(self.plan(source, 'rows2-v1'))
        artifact = self.backend().compile_wasm(source, plan_bytes)
        self.assertEqual(artifact, self.backend().compile_wasm(source, plan_bytes))
        self.assertIsInstance(artifact.module_bytes, bytes)
        self.assertTrue(artifact.module_bytes.startswith(b'\x00asm\x01\x00\x00\x00'))
        self.assertEqual((artifact.height, artifact.width), (5, 7))
        self.assertEqual((artifact.input_count, artifact.output_count), (48, 35))
        self.assertEqual((artifact.input_offset, artifact.output_offset), (0, 48 * 4))
        self.assertEqual(artifact.memory_bytes, 65536)
        self.assertEqual(artifact.input_interval, (0, 1023))
        self.assertEqual(artifact.source_digest, sha256(source).hexdigest())
        self.assertEqual(artifact.plan_digest, sha256(plan_bytes).hexdigest())
        self.assertEqual(artifact.module_digest, sha256(artifact.module_bytes).hexdigest())
        with self.assertRaises(FrozenInstanceError):
            artifact.output_offset = 0

    def test_all_schedules_and_bounded_shapes_match_both_oracles_on_repeated_inputs(self):
        generator = random.Random(91823)
        cases = []
        expected = []
        for height, width in ((1, 1), (2, 3), (5, 7), (15, 15), (1, 127), (127, 1)):
            source = stencil_source(height, width, cap=None)
            count = (height + 1) * (width + 1)
            inputs = [[0] * count, list(range(count)),
                      [1023 * ((r + c) % 2) for r in range(height + 1)
                       for c in range(width + 1)],
                      [generator.randrange(1024) for _ in range(count)],
                      [generator.randrange(1024) for _ in range(count)]]
            for name in PLAN_IDS:
                with self.subTest(height=height, width=width, name=name):
                    artifact = self.compile(source, name)
                    runs = []
                    results = []
                    for iteration, data in enumerate(inputs):
                        initial = [-777 - i - iteration for i in range(height * width)]
                        reference = evaluate_source(parse_source(source), data, initial)
                        self.assertEqual(execute_plan(source, encode_plan(self.plan(source, name)),
                                                      data, initial), reference)
                        runs.append(dict(input=data, initial=initial))
                        results.append(reference)
                    cases.append(self.case(artifact, runs))
                    expected.append(results)
        observed = self.execute_modules(cases)
        self.assertEqual(len(observed), len(expected))
        for compiled, reference_runs in zip(observed, expected):
            self.assertEqual(compiled['exports'], ['memory', 'run'])
            for actual, reference in zip(compiled['runs'], reference_runs):
                self.assertEqual(actual['status'], 0)
                self.assertEqual(actual['output'], list(reference.output))
                self.assertEqual(actual['input'], list(reference.input_after))

    def test_failed_preflight_preserves_every_memory_byte_and_returns_first_bad_index(self):
        source = stencil_source(2, 3, cap=None)
        cases = []
        expected = []
        for name in PLAN_IDS:
            artifact = self.compile(source, name)
            runs = []
            results = []
            for index in (0, 6, 11):
                for bad in (-2147483648, -1, 1024, 2147483647):
                    data = [7] * 12
                    data[index] = bad
                    initial = [-2147483648, 2147483647, -79, 128, 0, -1]
                    results.append(evaluate_source(parse_source(source), data, initial))
                    runs.append(dict(input=data, initial=initial))
            data = [1024, -1] + [7] * 10
            runs.append(dict(input=data, initial=[-11] * 6))
            results.append(evaluate_source(parse_source(source), data, [-11] * 6))
            # Reuse the same instance successfully after its rejected calls.
            runs.append(dict(input=[3] * 12, initial=[-12] * 6))
            results.append(evaluate_source(parse_source(source), [3] * 12, [-12] * 6))
            cases.append(self.case(artifact, runs))
            expected.append(results)
        for actual_case, references in zip(self.execute_modules(cases), expected):
            for actual, reference in zip(actual_case['runs'], references):
                status = reference.first_bad_index + 1 if reference.first_bad_index is not None else 0
                self.assertEqual(actual['status'], status)
                self.assertEqual(actual['input'], list(reference.input_after))
                self.assertEqual(actual['output'], list(reference.output))
                if status:
                    self.assertTrue(actual['unchanged'], 'preflight must precede all memory stores')

    def test_signed_literals_reach_scratch_without_changing_source_output(self):
        source = stencil_source(1, 1, cap=None)
        plan = self.plan(source)
        next_dst = sum(op.dst is not None for op in plan.operations)
        literals = [-2147483648, -8193, -8192, -65, -64, -1,
                    0, 63, 64, 127, 128, 8192, 2147483647]
        operations = list(plan.operations)
        for index, value in enumerate(literals):
            operations.extend((Operation('const', dst=next_dst + index, value=value),
                               Operation('scratch_store', index=index,
                                         operands=(next_dst + index,))))
        plan = replace(plan, scratch_capacity_cells=len(literals), operations=tuple(operations))
        artifact = self.backend().compile_wasm(source, encode_plan(plan))
        result = self.execute_modules([self.case(artifact, [dict(input=[0, 1, 2, 3], initial=[-9])],
                                                scratch_count=len(literals))])[0]['runs'][0]
        self.assertEqual(result['status'], 0)
        self.assertEqual(result['output'], [30])
        self.assertEqual(result['scratch'], literals)

    def test_plan_labels_and_debug_origins_do_not_change_generated_instructions(self):
        source = stencil_source(1, 1, cap=None)
        plan = self.plan(source)
        debug_changed = replace(plan, plan_id='untrusted label',
                                operations=tuple(replace(op, origins=(0, 7)) for op in plan.operations))
        original = self.backend().compile_wasm(source, encode_plan(plan))
        changed = self.backend().compile_wasm(source, encode_plan(debug_changed))
        self.assertEqual(original.module_bytes, changed.module_bytes)
        self.assertNotEqual(original.plan_digest, changed.plan_digest)

    def test_fresh_check_rejects_changed_semantics_overflow_caps_and_check_exhaustion(self):
        source = stencil_source(1, 1, cap=None)
        plan = self.plan(source)
        changed = replace(plan, operations=(replace(plan.operations[0], value=2),) + plan.operations[1:])
        with self.assertRaises(DiagnosticError):
            self.backend().compile_wasm(source, encode_plan(changed))
        next_dst = sum(op.dst is not None for op in plan.operations)
        overflow = replace(plan, operations=plan.operations + (
            Operation('const', dst=next_dst, value=2147483647),
            Operation('add', dst=next_dst + 1, operands=(next_dst, 0))))
        with self.assertRaises(DiagnosticError) as caught:
            self.backend().compile_wasm(source, encode_plan(overflow))
        self.assertEqual(caught.exception.code, 'ARITHMETIC_OVERFLOW')
        with self.assertRaises(DiagnosticError) as caught:
            self.compile(stencil_source(1, 1, cap=0), 'rows2-v1')
        self.assertEqual(caught.exception.code, 'CONSTRAINT_VIOLATED')
        with self.assertRaises(DiagnosticError) as caught:
            self.compile(source, limits=Limits(check_steps=1))
        self.assertEqual(caught.exception.code, 'CHECK_STEPS_EXHAUSTED')
        with self.assertRaises(DiagnosticError) as caught:
            self.backend().compile_wasm(stencil_source(2, 1), encode_plan(plan))
        self.assertEqual(caught.exception.code, 'SEMANTIC_DIGEST_MISMATCH')

    def test_huge_unused_scratch_is_rejected_without_allocation_or_metric_changes(self):
        source = stencil_source(1, 1, cap=None)
        for capacity in (257, 2147483647):
            plan = replace(self.plan(source), scratch_capacity_cells=capacity)
            with self.subTest(capacity=capacity), self.assertRaises(DiagnosticError) as caught:
                self.backend().compile_wasm(source, encode_plan(plan))
            self.assertEqual(caught.exception.code, 'BACKEND_STORAGE_LIMIT')
        # The upper supported reservation remains the plan's own reservation.
        plan = replace(self.plan(source), scratch_capacity_cells=256)
        artifact = self.backend().compile_wasm(source, encode_plan(plan))
        result = self.execute_modules([self.case(artifact, [dict(input=[0, 1, 2, 3], initial=[-9])])])
        self.assertEqual(result[0]['runs'][0]['output'], [30])

    def test_malformed_bytes_and_nonexact_arguments_never_emit_modules(self):
        source = stencil_source(1, 1)
        plan_bytes = encode_plan(self.plan(source))
        for malformed in (b'{}', b'not json', plan_bytes + b' trailing', bytearray(plan_bytes)):
            with self.subTest(plan_type=type(malformed).__name__), \
                    self.assertRaises((DiagnosticError, DecodeError)):
                self.backend().compile_wasm(source, malformed)
        for malformed in (b'not a module', source.replace(b'+1)', b'+2)'), stencil_source(32, 32)):
            with self.subTest(source=malformed[:20]), self.assertRaises(DiagnosticError):
                self.backend().compile_wasm(malformed, plan_bytes)
        with self.assertRaises(DiagnosticError):
            self.backend().compile_wasm(bytearray(source), plan_bytes)
        with self.assertRaises(DiagnosticError):
            self.backend().compile_wasm(source, plan_bytes, limits=None)


if __name__ == '__main__':
    unittest.main()
