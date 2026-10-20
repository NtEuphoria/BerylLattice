"""Execute emitted finite-plan C, independently checking complete states."""
import ctypes
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from axiom.codec import encode_plan
from axiom.frontend import admit_source, parse_source
from axiom.model import DiagnosticError, Limits
from axiom.plan_format import Operation
from axiom.planner import PLAN_IDS, make_plan
from axiom.reference import evaluate_source
from tests.helpers import stencil_source

try:
    native_codegen = importlib.import_module('axiom.native_codegen')
except ModuleNotFoundError as error:
    if error.name != 'axiom.native_codegen':
        raise
    native_codegen = None


def proposal(height=1, width=2, plan_id='inline-v1', cap=None):
    source = stencil_source(height, width, cap)
    return source, make_plan(admit_source(parse_source(source)), plan_id)


class NativeEmissionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(native_codegen, 'missing checked native finite-plan emitter')

    def test_immutable_deterministic_artifact_binds_exact_source_and_plan(self):
        source, plan = proposal()
        encoded = encode_plan(plan)
        artifact = native_codegen.emit_native_c(source, encoded)
        self.assertEqual(artifact, native_codegen.emit_native_c(source, encoded))
        self.assertEqual((artifact.height, artifact.width, artifact.input_count,
                          artifact.output_count), (1, 2, 6, 2))
        self.assertIs(type(artifact.c_source), bytes)
        self.assertEqual(artifact.source_digest, sha256(source).hexdigest())
        spaced = native_codegen.emit_native_c(source, b' ' + encoded)
        self.assertEqual(artifact.plan_digest, sha256(encoded).hexdigest())
        self.assertEqual(spaced.plan_digest, sha256(b' ' + encoded).hexdigest())
        self.assertNotEqual(artifact.plan_digest, spaced.plan_digest)
        self.assertEqual(artifact.c_source, spaced.c_source)
        self.assertEqual(artifact.c_digest, sha256(artifact.c_source).hexdigest())
        with self.assertRaises(FrozenInstanceError):
            artifact.height = 2

    def test_every_emission_freshly_rejects_invalid_source_plan_constraints_and_budget(self):
        source, plan = proposal()
        bad_plans = [replace(plan, semantic_digest='0' * 64)]
        operations = list(plan.operations)
        operations[0] = replace(operations[0], value=2)
        bad_plans.append(replace(plan, operations=tuple(operations)))
        for bad in bad_plans:
            with self.subTest(plan=bad), self.assertRaises(DiagnosticError):
                native_codegen.emit_native_c(source, encode_plan(bad))
        constrained, materialized = proposal(plan_id='materialize-v1', cap=0)
        with self.assertRaisesRegex(DiagnosticError, 'CONSTRAINT'):
            native_codegen.emit_native_c(constrained, encode_plan(materialized))
        with self.assertRaisesRegex(DiagnosticError, 'CHECK_STEPS_EXHAUSTED'):
            native_codegen.emit_native_c(source, encode_plan(plan), Limits(check_steps=1))
        with self.assertRaisesRegex(DiagnosticError, 'INVALID_EXECUTION_ARGUMENT'):
            native_codegen.emit_native_c(bytearray(source), encode_plan(plan))
        # Above 256 cells the source is scale-v1, which has loop plans only: the
        # finite checker refuses its semantics version.
        with self.assertRaisesRegex(DiagnosticError, 'UNSUPPORTED_SEMANTICS_VERSION'):
            larger, larger_plan = proposal(1, 127)
            native_codegen.emit_native_c(larger.replace(b'W = 127', b'W = 128'),
                                         encode_plan(larger_plan))

    def test_unused_reserved_scratch_is_bounded_before_native_storage_emission(self):
        source, plan = proposal()
        for capacity in (257, 2147483647):
            with self.subTest(capacity=capacity), self.assertRaisesRegex(
                    DiagnosticError, 'BACKEND_STORAGE_LIMIT'):
                native_codegen.emit_native_c(source, encode_plan(
                    replace(plan, scratch_capacity_cells=capacity)))

    def test_dead_signed_i32_overflow_cannot_be_compiled(self):
        source, plan = proposal()
        next_dst = max(op.dst for op in plan.operations if op.dst is not None) + 1
        origin = plan.operations[0].origins
        operations = plan.operations + (
            Operation('const', next_dst, (), None, 2147483647, origin),
            Operation('add', next_dst + 1, (next_dst, 0), None, None, origin))
        with self.assertRaisesRegex(DiagnosticError, 'OVERFLOW'):
            native_codegen.emit_native_c(source, encode_plan(replace(
                plan, plan_id='safe-output-with-unsafe-dead-operation', operations=operations)))


class NativeExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = os.environ.get('AXIOM_TEST_NATIVE_CLANG') or shutil.which('clang')
        if not cls.compiler:
            raise unittest.SkipTest('native C tests need Clang or AXIOM_TEST_NATIVE_CLANG')

    def setUp(self):
        self.assertIsNotNone(native_codegen, 'missing checked native finite-plan emitter')
        self.temporary = tempfile.TemporaryDirectory(prefix='axiom-native-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.serial = 0

    def build(self, source, plan, *, shared=False):
        artifact = native_codegen.emit_native_c(source, encode_plan(plan))
        self.serial += 1
        path = self.root / ('kernel' + str(self.serial) + '.c')
        path.write_bytes(artifact.c_source)
        binary = path.with_suffix('.so' if shared else '.exe')
        flags = ['-shared', '-fPIC'] if shared else []
        result = subprocess.run([self.compiler, '-std=c11', '-O2', '-Wall', '-Wextra',
                                 '-Werror', *flags, str(path), '-o', str(binary)],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        return artifact, binary

    def library(self, binary):
        library = ctypes.CDLL(str(binary))
        library.beryl_kernel.argtypes = [ctypes.POINTER(ctypes.c_int32)] * 2
        library.beryl_kernel.restype = ctypes.c_int32
        return library

    def invoke(self, library, data, initial):
        inputs = (ctypes.c_int32 * len(data))(*data)
        output = (ctypes.c_int32 * len(initial))(*initial)
        status = library.beryl_kernel(inputs, output)
        return status, tuple(inputs), tuple(output)

    def test_same_compiled_artifact_reuses_varying_inputs_for_all_plans_and_shapes(self):
        for height, width in ((1, 1), (5, 7), (15, 15)):
            for plan_id in PLAN_IDS:
                with self.subTest(shape=(height, width), plan=plan_id):
                    source, plan = proposal(height, width, plan_id)
                    artifact, binary = self.build(source, plan, shared=True)
                    library = self.library(binary)
                    initial = tuple(-2147483648 if i % 2 else 2147483647
                                    for i in range(artifact.output_count))
                    patterns = [tuple([0] * artifact.input_count),
                                tuple([1023] * artifact.input_count),
                                tuple(range(artifact.input_count)),
                                tuple(1023 * (i % 2) for i in range(artifact.input_count))]
                    for data in patterns:
                        expected = evaluate_source(parse_source(source), data, initial)
                        status, final_input, output = self.invoke(library, data, initial)
                        self.assertEqual(status, 0)
                        self.assertEqual((final_input, output), (expected.input_after, expected.output))

    def test_first_invalid_input_preserves_every_initial_output_and_all_inputs(self):
        for plan_id in PLAN_IDS:
            source, plan = proposal(2, 3, plan_id)
            artifact, binary = self.build(source, plan, shared=True)
            library = self.library(binary)
            initial = (-2147483648, 2147483647, -99, 77, 0, -1)
            for first in (0, artifact.input_count // 2, artifact.input_count - 1):
                for invalid in (-2147483648, -1, 1024, 2147483647):
                    with self.subTest(plan=plan_id, first=first, invalid=invalid):
                        data = [0] * artifact.input_count
                        data[first] = invalid
                        data[-1] = invalid
                        status, final_input, output = self.invoke(library, data, initial)
                        self.assertEqual(status, first + 1)
                        self.assertEqual(final_input, tuple(data))
                        self.assertEqual(output, initial)

    def test_arbitrary_checked_plan_accepts_dead_signed_i32_endpoint_arithmetic(self):
        source, plan = proposal()
        next_dst = max(op.dst for op in plan.operations if op.dst is not None) + 1
        origin = plan.operations[0].origins
        operations = plan.operations + (
            Operation('const', next_dst, (), None, 2147483647, origin),
            Operation('const', next_dst + 1, (), None, -2147483648, origin),
            Operation('add', next_dst + 2, (next_dst, next_dst + 1), None, None, origin),
            Operation('mul', next_dst + 3, (next_dst + 2, next_dst), None, None, origin))
        artifact, binary = self.build(source, replace(plan, plan_id='hand-extended',
                                                      operations=operations), shared=True)
        self.assertIn(b'2147483647LL', artifact.c_source)
        self.assertIn(b'-2147483648LL', artifact.c_source)
        data, initial = (0, 1, 2, 3, 4, 5), (-2147483648, 2147483647)
        expected = evaluate_source(parse_source(source), data, initial)
        self.assertEqual(self.invoke(self.library(binary), data, initial),
                         (0, expected.input_after, expected.output))

    def test_standalone_driver_uses_runtime_values_and_outputs_only_json(self):
        for plan_id in PLAN_IDS:
            source, plan = proposal(plan_id=plan_id)
            artifact, binary = self.build(source, plan)
            for values in ((0, 1, 2, 3, 4, 5), (1023,) * 6, (0,) * 6):
                payload = ' '.join(map(str, (1, 2) + values))
                result = subprocess.run([binary], input=payload, capture_output=True,
                                        text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                expected = evaluate_source(parse_source(source), values, (-9, -9))
                self.assertEqual(json.loads(result.stdout), list(expected.output))
                self.assertEqual(result.stderr, '')
            self.assertEqual(artifact.input_count, 6)

    def test_driver_rejects_malformed_missing_extra_and_out_of_range_tokens(self):
        source, plan = proposal()
        _, binary = self.build(source, plan)
        for payload in ('', '1', '2 1 0 1 2 3 4 5', '1 2 0 1 2 3 4',
                        '1 2 0 1 2 3 4 5 6', '1 2 0 1 2 3 4 1024',
                        '1 2 0 1 2 3 4 -2147483648',
                        '1 2 0 1 2 3 4 2147483648',
                        '1 2 0 1 2 3 4 -2147483649',
                        '1 2 0 1 2 3 4 9223372036854775808',
                        '1 2 0 1 2 3 4 1.0', '1 2 0 1 2 3 4 0x1',
                        '1 2 0 1 2 3 4 +', '1 2 0 1 2 3 4 true',
                        '1 2 0 1 2 3 4 0\x00hidden',
                        '1 2 ' + '0' * 70 + ' 0 0 0 0',
                        '2147483648 2 0 1 2 3 4 5'):
            with self.subTest(payload=payload):
                result = subprocess.run([binary], input=payload, capture_output=True,
                                        text=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()
