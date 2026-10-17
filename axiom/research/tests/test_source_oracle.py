"""Independent original-source oracle controls; no native qualification."""
from dataclasses import replace
from pathlib import Path
import ast
import errno
import hashlib
import inspect
import json
import os
import re
import subprocess
import sys
import time
import struct
import tempfile
import unittest
from unittest.mock import patch

from axiom.frontend import parse_source
from axiom.reference import evaluate_source as reference

from axiom.artifact_chunks_v2 import BlobLimits
from axiom.invocation_v2 import InvocationLimits, verify_invocation, write_invocation
from axiom.source_profiles import SourceProfileV2
try:
    from research import source_oracle as oracle
    from research import state_artifacts as state
except ModuleNotFoundError:
    import source_oracle as oracle
    import state_artifacts as state


def stencil_source(h, w):
    """Literal disclosed fixture; independent of either test-package namespace."""
    return f"""module demo;
shape H = {h};
shape W = {w};
input image: i32[H+1,W+1] in 0..=1023;
let p[r in 0..H+1,c in 0..W+1] =
  (image[r,c]+1)*(image[r,c]+1);
output result[r in 0..H,c in 0..W] =
  ((p[r,c]+p[r,c+1])+p[r+1,c])+p[r+1,c+1];
require plan_workspace_bytes <= 64;
prefer multiplication_ops;
""".encode('utf-8')


class SourceOracleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.serial = 0

    def invocation(self, source, values, output, *, chunk_bytes=1_048_576):
        self.serial += 1
        limits = InvocationLimits(blobs=BlobLimits(chunk_bytes=chunk_bytes))
        manifest = write_invocation(source, [struct.pack('<%di' % len(values), *values)],
            [struct.pack('<%di' % len(output), *output)], self.root/f'inv-{self.serial}', limits=limits)
        return verify_invocation(manifest, limits=limits)

    def evaluate(self, source, values, output, **kwargs):
        invocation = self.invocation(source, values, output)
        result = oracle.evaluate_source_state(source, invocation, self.root/f'result-{self.serial}',
            profile=SourceProfileV2(), limits=kwargs.get('limits', oracle.OracleLimits()))
        return result

    def checked(self, result):
        self.assertIn(result.status, ('success', 'input_precondition_failed'), result)
        return state.verify_state(result.state_manifest)

    def assert_incomplete(self, result, destination, status):
        self.assertEqual(result.status, status, result)
        self.assertIsNone(result.state_manifest)
        self.assertIsNone(result.first_bad_index)
        self.assertIsNotNone(result.failure_detail)
        self.assertLessEqual(len(result.failure_detail), 128)
        self.assertFalse(destination.exists(), list(destination.rglob('*')) if destination.exists() else '')

    def run_invocation(self, source, invocation, limits=None, destination=None):
        destination = destination or self.root/f'result-{self.serial}'
        return oracle.evaluate_source_state(source, invocation, destination, profile=SourceProfileV2(),
            limits=limits or oracle.OracleLimits())

    def test_independent_one_cell(self):
        result = self.evaluate(stencil_source(1, 1), [0, 1, 2, 3], [123])
        self.assertEqual(result.status, 'success')
        checked = state.verify_state(result.state_manifest)
        self.assertEqual(list(checked.iter_scalars('input_after')), [0, 1, 2, 3])
        self.assertEqual(list(checked.iter_scalars('output')), [30])

    def test_invalid_preserves_every_canary_and_input(self):
        values = [0, -1, 2, 3, 1024, 5, 6, 7, 8, 9, 10, 11]
        canaries = [91, -92, 93, -94, 95, -96]
        result = self.evaluate(stencil_source(2, 3), values, canaries)
        self.assertEqual((result.status, result.first_bad_index), ('input_precondition_failed', 1))
        checked = state.verify_state(result.state_manifest)
        self.assertEqual(list(checked.iter_scalars('input_after')), values)
        self.assertEqual(list(checked.iter_scalars('output')), canaries)
        self.assertEqual(result.input_preflight_scalars, len(values))
        self.assertEqual(result.scalar_evaluations, 0)

    def test_small_boundary_corpus_and_coordinate_case(self):
        fixtures = json.loads((Path(__file__).resolve().parents[2]/'tests/fixtures/inputs/boundary_cases.json').read_text())
        for name in ('all_zero', 'all_max', 'bottom_right_one'):
            case = fixtures[name]
            result = self.evaluate(stencil_source(1, 1), case['input'], [-777])
            self.assertEqual(list(self.checked(result).iter_scalars('output')), case['output'])
        h, w = 5, 7
        values = [(r*73+c*19+r*c*11) % 1024 for r in range(h+1) for c in range(w+1)]
        self.compare_reference(stencil_source(h, w), values, [-777-i for i in range(h*w)])

    def compare_reference(self, source, values, output):
        expected = reference(parse_source(source), values, output)
        result = self.evaluate(source, values, output)
        checked = self.checked(result)
        self.assertEqual((result.status, result.first_bad_index), (expected.status, expected.first_bad_index))
        self.assertEqual(tuple(checked.iter_scalars('input_after')), expected.input_after)
        self.assertEqual(tuple(checked.iter_scalars('output')), expected.output)
        return result

    def test_every_invalid_position_and_i32_extrema(self):
        for index in range(12):
            for bad in (-1, 1024, -(1 << 31), (1 << 31)-1):
                with self.subTest(index=index, bad=bad):
                    values = list(range(12))
                    values[index] = bad
                    result = self.compare_reference(stencil_source(2, 3), values, [-777-i for i in range(6)])
                    self.assertEqual(result.input_preflight_scalars, 12)
                    self.assertEqual(result.scalar_evaluations, 0)

    def test_rejected_input_never_visits_any_expression(self):
        with patch.object(oracle, '_evaluate_expression', side_effect=AssertionError('must not visit')) as visitor:
            result = self.evaluate(stencil_source(2, 3), [-1]+[0]*10+[1024], [7, 8, -9, 10, 11, -12])
        self.assertEqual(result.input_preflight_scalars, 12)
        self.assertEqual(result.first_bad_index, 0)
        visitor.assert_not_called()

    def test_preflight_finishes_before_first_expression(self):
        original = oracle._evaluate_expression
        visits = []
        def expression(node, scalars, tensors, work):
            self.assertEqual(work.input_preflight_scalars, 12)
            visits.append(type(node).__name__)
            return original(node, scalars, tensors, work)
        with patch.object(oracle, '_evaluate_expression', expression):
            self.compare_reference(stencil_source(2, 3), list(range(12)), [9]*6)
        self.assertTrue(visits)

    def test_renaming_groups_work_and_exact_budget(self):
        source = stencil_source(2, 3)
        values, canaries = list(range(12)), [-1]*6
        original = self.compare_reference(source, values, canaries)
        renamed = re.sub(rb'\b(demo|H|W|image|p|result|r|c)\b', lambda m: {
            b'demo': b'alt', b'H': b'Rows', b'W': b'Cols', b'image': b'pixels', b'p': b'producer',
            b'result': b'answer', b'r': b'y', b'c': b'x'}[m[0]], source)
        renamed_result = self.compare_reference(renamed, values, canaries)
        # Axis scalar names can also equal tensor names: separate namespaces.
        self.compare_reference(re.sub(rb'\br\b', b'image', source), values, canaries)
        grouped = source.replace(b'(image[r,c]+1)', b'(((image[r,c]+1)))')
        grouped_result = self.compare_reference(grouped, values, canaries)
        self.assertGreater(grouped_result.scalar_evaluations, original.scalar_evaluations)
        self.assertEqual(renamed_result.scalar_evaluations, original.scalar_evaluations)
        self.assertEqual(renamed_result.state_invocation_sha256, original.state_invocation_sha256)
        self.assertNotEqual(renamed_result.invocation_sha256, original.invocation_sha256)
        exact = oracle.OracleLimits(max_scalar_evaluations=grouped_result.scalar_evaluations)
        succeeded = self.evaluate(grouped, values, canaries, limits=exact)
        self.assertEqual(succeeded.status, 'success')
        failed = self.evaluate(grouped, values, canaries,
            limits=replace(exact, max_scalar_evaluations=exact.max_scalar_evaluations-1))
        self.assert_incomplete(failed, self.root/f'result-{self.serial}', 'work_limit')
        self.assertEqual(failed.scalar_evaluations, exact.max_scalar_evaluations-1)

    def test_unsupported_equation_and_mismatched_source_do_not_acquire(self):
        source = stencil_source(1, 1)
        invocation = self.invocation(source, [0, 1, 2, 3], [9])
        with patch.object(oracle, '_copy_input', side_effect=AssertionError('must not acquire')):
            result = self.run_invocation(source.replace(b'image[r,c]+1', b'image[r,c]+2'), invocation)
        self.assert_incomplete(result, self.root/f'result-{self.serial}', 'unsupported_source')
        with patch.object(oracle, '_copy_input', side_effect=AssertionError('must not acquire')):
            result = self.run_invocation(b'// changed exact bytes\n'+source, invocation)
        self.assert_incomplete(result, self.root/f'result-{self.serial}', 'invalid_invocation')

    def test_generic_seven_byte_blob_and_sixteen_byte_state_chunks(self):
        source, values, output = stencil_source(2, 3), list(range(12)), [50+i for i in range(6)]
        invocation = self.invocation(source, values, output, chunk_bytes=7)
        limits = oracle.OracleLimits(max_cached_input_bytes=8, state_limits=state.ArtifactLimits(chunk_bytes=16))
        result = self.run_invocation(source, invocation, limits)
        checked = state.verify_state(result.state_manifest, limits=limits.state_limits)
        self.assertEqual(list(checked.iter_scalars('input_after')), values)
        self.assertEqual(tuple(checked.iter_scalars('output')), reference(parse_source(source), values, output).output)
        self.assertEqual(result.input_snapshot_bytes, 48)
        self.assertEqual(result.acquired_input_bytes, 48)
        self.assertEqual(result.emitted_state_scalars, 18)
        self.assertEqual(result.input_read_scalars, 48)
        self.assertLessEqual(result.peak_cached_input_bytes, 8)
        self.assertGreater(result.cache_misses, 2)
        invalid = self.invocation(source, [-1]+values[1:-1]+[1024], output, chunk_bytes=7)
        result = self.run_invocation(source, invalid, limits)
        checked = state.verify_state(result.state_manifest, limits=limits.state_limits)
        self.assertEqual(list(checked.iter_scalars('output')), output)
        self.assertEqual(result.input_preflight_scalars, 12)

    def test_snapshot_cache_first_last_eviction_and_minimum(self):
        with tempfile.TemporaryFile() as stream:
            values = [-2147483648, -1, 0, 2147483647]
            stream.write(struct.pack('<4i', *values))
            stream.flush()
            for budget in (4, 5, 8, 12, 16, 24):
                work = oracle._Work(oracle.OracleLimits(max_cached_input_bytes=budget))
                reader = oracle._SnapshotI32Reader(stream, 4, work)
                for index in (0, 3, 1, 2, 0, 3):
                    self.assertEqual(reader.read(index), values[index])
                    self.assertLessEqual(len(reader.cache), 2)
                    self.assertLessEqual(sum(map(len, reader.cache.values())), budget)
                self.assertLessEqual(work.peak_cached_input_bytes, budget)
                self.assertEqual(work.input_read_scalars, 6)

    def test_complete_identities_and_original_files_preserved(self):
        source = stencil_source(2, 3)
        invocation = self.invocation(source, list(range(12)), [-777]*6)
        before = {path: path.read_bytes() for path in invocation.manifest_path.parent.rglob('*') if path.is_file()}
        result = self.run_invocation(source, invocation)
        checked = self.checked(result)
        self.assertEqual(result.source_sha256, hashlib.sha256(source).hexdigest())
        self.assertEqual(result.family_semantics_sha256, invocation.family_semantics_sha256)
        self.assertEqual(result.specialization_semantics_sha256, invocation.specialization_semantics_sha256)
        self.assertEqual(result.invocation_sha256, invocation.invocation_sha256)
        self.assertEqual(result.state_invocation_sha256, invocation.state_v1_invocation_sha256())
        self.assertEqual(checked.metadata.invocation_sha256, result.state_invocation_sha256)
        self.assertEqual(checked.metadata.logical_semantics_sha256, result.specialization_semantics_sha256)
        self.assertNotEqual(result.invocation_sha256, result.state_invocation_sha256)
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_all_zero_and_all_max_disclosed_32_controls(self):
        for value, expected in ((0, 4), (1023, 4194304)):
            with self.subTest(value=value):
                source = stencil_source(32, 32)
                values, output = [value]*1089, [-991]*1024
                invocation = self.invocation(source, values, output)
                start = time.monotonic()
                result = self.run_invocation(source, invocation)
                duration = time.monotonic()-start
                checked = self.checked(result)
                self.assertEqual(list(checked.iter_scalars('input_after')), values)
                self.assertEqual(list(checked.iter_scalars('output')), [expected]*1024)
                self.assertEqual(result.input_preflight_scalars, 1089)
                self.assertEqual(result.emitted_state_scalars, 2113)
                self.assertEqual(result.input_read_scalars, 8192)
                self.assertEqual(result.invocation_sha256, invocation.invocation_sha256)
                print('O2 disclosed 32 control', value, 'seconds', round(duration, 6),
                    'AST', result.scalar_evaluations, 'cache_misses', result.cache_misses,
                    'peak_cache', result.peak_cached_input_bytes, 'acquired', result.acquired_input_bytes,
                    'snapshot_written', result.input_snapshot_bytes, 'snapshot_read', result.snapshot_read_bytes)

    def test_limit_records_revalidate_exact_types_and_nested_ceilings(self):
        for field, bad_values in {
            'max_source_bytes': (True, 0, 65537),
            'max_cached_input_bytes': (True, 3, 2097153),
            'max_scalar_evaluations': (False, 0, 1000000001),
            'max_temporary_bytes': (1.5, 0, 268435457),
            'max_input_snapshot_bytes': (False, -1, 33554433),
            'deadline_monotonic_ns': (True, -1, float('nan'), 1 << 64),
            'cancelled': (True, 'yes'), 'state_limits': (None,),
        }.items():
            for bad in bad_values:
                with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
                    oracle.OracleLimits(**{field: bad})
        for name in state.ArtifactLimits.__dataclass_fields__:
            maximum = getattr(state.ArtifactLimits(), name)
            with self.subTest(name=name), self.assertRaises(ValueError):
                oracle.OracleLimits(state_limits=replace(state.ArtifactLimits(), **{name: maximum*2}))
        forged = oracle.OracleLimits()
        object.__setattr__(forged, 'max_source_bytes', True)
        with self.assertRaises(ValueError):
            oracle.evaluate_source_state(b'', None, self.root/'bad', profile=SourceProfileV2(), limits=forged)
        nested = state.ArtifactLimits()
        object.__setattr__(nested, 'max_files', True)
        with self.assertRaises(ValueError):
            oracle.OracleLimits(state_limits=nested)

    def test_quota_preflight_before_acquisition_or_payload_creation(self):
        source = stencil_source(2, 3)
        invocation = self.invocation(source, [0]*12, [0]*6)
        states = [
            state.ArtifactLimits(chunk_bytes=16, max_files=5), # needs 3+2 chunks plus manifest even with dedup
            state.ArtifactLimits(max_aggregate_bytes=72),
            state.ArtifactLimits(max_logical_bytes=71),
            state.ArtifactLimits(max_metadata_bytes=100),
            state.ArtifactLimits(max_metadata_items=30),
            state.ArtifactLimits(max_metadata_depth=2),
            state.ArtifactLimits(chunk_bytes=16, max_file_bytes=16), # manifest cannot fit
        ]
        configurations = [oracle.OracleLimits(state_limits=item) for item in states]
        configurations += [oracle.OracleLimits(max_temporary_bytes=1), oracle.OracleLimits(max_input_snapshot_bytes=47)]
        for index, limits in enumerate(configurations):
            destination = self.root/f'quota-{index}'
            with self.subTest(index=index), patch.object(oracle, '_copy_input') as copy, \
                    patch.object(oracle.tempfile, 'TemporaryFile') as temporary, patch.object(oracle, 'write_state') as writer:
                result = self.run_invocation(source, invocation, limits, destination)
                self.assert_incomplete(result, destination, 'resource_limit')
                copy.assert_not_called()
                temporary.assert_not_called()
                writer.assert_not_called()
                self.assertEqual(result.acquired_input_bytes, 0)
                self.assertEqual(result.emitted_state_scalars, 0)

    def test_existing_destination_and_symlink_ancestor_preserved(self):
        source = stencil_source(1, 1)
        invocation = self.invocation(source, [0]*4, [9])
        destination = self.root/'existing'
        destination.mkdir()
        (destination/'canary').write_bytes(b'keep')
        result = self.run_invocation(source, invocation, destination=destination)
        self.assertEqual(result.status, 'io_failure')
        self.assertEqual((destination/'canary').read_bytes(), b'keep')
        self.assertEqual(list(destination.iterdir()), [destination/'canary'])
        alias = self.root/'alias'
        alias.symlink_to(destination, target_is_directory=True)
        result = self.run_invocation(source, invocation, destination=alias/'new')
        self.assertEqual(result.status, 'io_failure')
        self.assertFalse((destination/'new').exists())

    def test_failed_ancestor_opens_do_not_leak_descriptors(self):
        source = stencil_source(1, 1)
        invocation = self.invocation(source, [0]*4, [9])
        before = set(os.listdir('/proc/self/fd'))
        for _ in range(20):
            result = self.run_invocation(source, invocation, destination=self.root/'missing'/'child'/'state')
            self.assertEqual(result.status, 'io_failure')
        self.assertEqual(set(os.listdir('/proc/self/fd')), before)

    def test_forged_typed_invocations_reject_before_equations(self):
        source = stencil_source(1, 1)
        for field, change in (
            ('source_bytes', b'other'), ('manifest_sha256', '0'*64), ('manifest', None),
            ('limits', None), ('input', None), ('manifest_path', self.root/'missing.json'),
        ):
            invocation = self.invocation(source, [0]*4, [9])
            object.__setattr__(invocation, field, change)
            with self.subTest(field=field), patch.object(oracle, '_evaluate_expression', side_effect=AssertionError('equation')):
                result = self.run_invocation(source, invocation)
            self.assert_incomplete(result, self.root/f'result-{self.serial}', 'invalid_invocation')
        invocation = self.invocation(source, [0]*4, [9])
        object.__setattr__(invocation.manifest, 'H', True)
        result = self.run_invocation(source, invocation)
        self.assert_incomplete(result, self.root/f'result-{self.serial}', 'invalid_invocation')

    def mutate_input(self, invocation):
        chunk = invocation.input.chunks[0]
        path = invocation.input.reference.manifest_path.parent/chunk.path
        raw = bytearray(path.read_bytes())
        raw[0] ^= 1
        path.chmod(0o600)
        path.write_bytes(raw)

    def test_mutation_before_entry_before_acquisition_and_prepublication(self):
        source = stencil_source(1, 1)
        invocation = self.invocation(source, [0]*4, [9])
        self.mutate_input(invocation)
        result = self.run_invocation(source, invocation)
        self.assert_incomplete(result, self.root/f'result-{self.serial}', 'invalid_invocation')
        invocation = self.invocation(source, [0]*4, [9])
        original = oracle._copy_input
        def mutate_then_copy(*args):
            self.mutate_input(invocation)
            return original(*args)
        with patch.object(oracle, '_copy_input', mutate_then_copy):
            result = self.run_invocation(source, invocation)
        self.assert_incomplete(result, self.root/f'result-{self.serial}', 'io_failure')
        invocation = self.invocation(source, [0]*4, [9])
        original_verify = oracle.verify_state
        def mutate_after_verification(*args, **kwargs):
            checked = original_verify(*args, **kwargs)
            self.mutate_input(invocation)
            return checked
        with patch.object(oracle, 'verify_state', mutate_after_verification):
            result = self.run_invocation(source, invocation)
        self.assert_incomplete(result, self.root/f'result-{self.serial}', 'invalid_invocation')
        self.assertEqual(result.emitted_state_scalars, 5)

    def test_early_cancel_and_expired_deadline(self):
        source = stencil_source(1, 1)
        invocation = self.invocation(source, [0]*4, [9])
        for limits, status in ((oracle.OracleLimits(cancelled=lambda: True), 'cancelled'),
                               (oracle.OracleLimits(deadline_monotonic_ns=0), 'timeout')):
            with patch.object(oracle, '_copy_input') as copy:
                result = self.run_invocation(source, invocation, limits)
            self.assert_incomplete(result, self.root/f'result-{self.serial}', status)
            copy.assert_not_called()

    def test_cooperative_mid_preflight_mid_output_and_prepublish_cancel(self):
        source = stencil_source(2, 3)
        for phase in ('preflight', 'output', 'prepublish'):
            invocation = self.invocation(source, [0]*12, [9]*6)
            seen = {'work': None, 'complete_result_allocated': False}
            original_poll, original_result = oracle._Work.poll, oracle._Work.result
            def poll(work):
                seen['work'] = work
                return original_poll(work)
            def result(work, *args, **kwargs):
                value = original_result(work, *args, **kwargs)
                if value.state_manifest is not None:
                    seen['complete_result_allocated'] = True
                return value
            def cancelled():
                work = seen['work']
                return bool(work and ((phase == 'preflight' and work.input_preflight_scalars >= 6) or
                    (phase == 'output' and work.emitted_state_scalars >= 14) or
                    (phase == 'prepublish' and seen['complete_result_allocated'])))
            with self.subTest(phase=phase), patch.object(oracle._Work, 'poll', poll), patch.object(oracle._Work, 'result', result):
                value = self.run_invocation(source, invocation, oracle.OracleLimits(cancelled=cancelled))
            self.assert_incomplete(value, self.root/f'result-{self.serial}', 'cancelled')
            if phase == 'preflight':
                self.assertEqual(value.scalar_evaluations, 0)
                self.assertEqual(value.input_preflight_scalars, 6)
            if phase == 'prepublish':
                self.assertEqual(value.emitted_state_scalars, 18)

    def test_snapshot_short_read_allocation_and_write_failures(self):
        source = stencil_source(1, 1)
        for label, target, side_effect, status in (
            ('short', 'pread', lambda *args: b'', 'io_failure'),
            ('memory', 'pread', MemoryError(), 'allocation_failure'),
        ):
            invocation = self.invocation(source, [0]*4, [9])
            with self.subTest(label=label), patch.object(oracle.os, target, side_effect=side_effect):
                result = self.run_invocation(source, invocation)
            self.assert_incomplete(result, self.root/f'result-{self.serial}', status)
        original = oracle.tempfile.TemporaryFile
        for fault, status in ((OSError(errno.EIO, 'write'), 'io_failure'),
                              (OSError(errno.ENOSPC, 'full'), 'resource_limit'),
                              (MemoryError(), 'allocation_failure'), (0, 'io_failure'), (3, 'io_failure')):
            invocation = self.invocation(source, [0]*4, [9])
            streams = []
            class BrokenSnapshot:
                def __enter__(self):
                    self.stream = original()
                    streams.append(self.stream)
                    return self
                def __exit__(self, *args):
                    self.stream.close()
                def write(self, raw):
                    if isinstance(fault, Exception):
                        raise fault
                    return fault
            with self.subTest(fault=repr(fault)), patch.object(oracle.tempfile, 'TemporaryFile', return_value=BrokenSnapshot()):
                result = self.run_invocation(source, invocation)
            self.assert_incomplete(result, self.root/f'result-{self.serial}', status)
            self.assertTrue(all(stream.closed for stream in streams))
            if fault == 3:
                self.assertEqual(result.input_snapshot_bytes, 3)
        with tempfile.TemporaryFile() as stream:
            stream.write(struct.pack('<4i', 0, 1, 2, 3))
            stream.flush()
            work = oracle._Work(oracle.OracleLimits())
            reader = oracle._SnapshotI32Reader(stream, 4, work)
            with patch.object(oracle.os, 'pread', return_value=b'\x00'), self.assertRaises(oracle._Stop) as caught:
                reader.read(0)
            self.assertEqual(caught.exception.status, 'io_failure')
            self.assertEqual(work.snapshot_read_bytes, 1)
            self.assertEqual(work.cache_misses, 0)
            self.assertEqual(len(reader.cache), 0)

    def test_ast_allocation_and_recursion_failures_are_incomplete(self):
        source = stencil_source(1, 1)
        for fault, status in ((MemoryError(), 'allocation_failure'), (RecursionError(), 'resource_limit')):
            invocation = self.invocation(source, [0]*4, [9])
            with patch.object(oracle, '_evaluate_expression', side_effect=fault):
                result = self.run_invocation(source, invocation)
            self.assert_incomplete(result, self.root/f'result-{self.serial}', status)
            self.assertEqual(result.input_preflight_scalars, 4)

    def test_nested_forged_blob_fields_reject_before_acquisition(self):
        source = stencil_source(1, 1)
        for change in ('chunk_offset', 'cache', 'reference_length'):
            invocation = self.invocation(source, [0]*4, [9])
            if change == 'chunk_offset':
                object.__setattr__(invocation.input.chunks[0], 'offset', False)
            elif change == 'cache':
                object.__setattr__(invocation.input, '_cache', {})
            else:
                object.__setattr__(invocation.input.reference, 'byte_length', 16.0)
            with patch.object(oracle, '_copy_input', side_effect=AssertionError('must not acquire')):
                result = self.run_invocation(source, invocation)
            self.assert_incomplete(result, self.root/f'result-{self.serial}', 'invalid_invocation')

    def test_acquisition_rechecks_full_length_and_hash_before_equations(self):
        source = stencil_source(1, 1)
        for raw in (struct.pack('<4i', 1, 0, 0, 0), b'\x00'*12, b'\x00'*20):
            invocation = self.invocation(source, [0]*4, [9])
            original = type(invocation.input).iter_bytes
            def changed(blob):
                if blob is invocation.input:
                    yield raw
                else:
                    yield from original(blob)
            with patch.object(type(invocation.input), 'iter_bytes', changed), \
                    patch.object(oracle, '_evaluate_expression', side_effect=AssertionError('must not evaluate')):
                result = self.run_invocation(source, invocation)
            self.assert_incomplete(result, self.root/f'result-{self.serial}', 'invalid_invocation')

    def test_public_result_has_strict_complete_incomplete_contract(self):
        result = self.evaluate(stencil_source(1, 1), [0]*4, [9])
        for changes in ({'scalar_evaluations': True}, {'first_bad_index': 0}, {'source_sha256': None},
                        {'state_manifest': None}, {'failure_detail': 'unexpected'}, {'status': 'bogus'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(result, **changes)
        # A well-typed fabricated record still carries no qualification authority.
        self.assertEqual(replace(result).status, 'success')

    def test_state_chunk_failure_and_late_verification_cleanup(self):
        source = stencil_source(2, 3)
        original_write = state._write_immutable
        def write_late(root, relative, raw):
            if relative.startswith('chunks/') and len(raw) == 8:
                raise OSError(errno.EIO, 'late output chunk')
            return original_write(root, relative, raw)
        invocation = self.invocation(source, list(range(12)), [9]*6)
        with patch.object(state, '_write_immutable', write_late):
            result = self.run_invocation(source, invocation,
                oracle.OracleLimits(state_limits=state.ArtifactLimits(chunk_bytes=16)))
        self.assert_incomplete(result, self.root/f'result-{self.serial}', 'io_failure')
        self.assertEqual(result.emitted_state_scalars, 18)
        for target in (state, oracle):
            invocation = self.invocation(source, [0]*12, [9]*6)
            with patch.object(target, 'verify_state', side_effect=ValueError('broken final verification')):
                result = self.run_invocation(source, invocation)
            self.assert_incomplete(result, self.root/f'result-{self.serial}', 'io_failure')
            self.assertEqual(result.emitted_state_scalars, 18)

    def test_storage_error_wrapped_by_safe_helper_is_resource_failure(self):
        source = stencil_source(1, 1)
        invocation = self.invocation(source, [0]*4, [9])
        def failed(*args, **kwargs):
            try:
                raise OSError(errno.ENOSPC, 'full')
            except OSError as cause:
                raise ValueError('safe writer') from cause
        with patch.object(oracle, 'write_state', failed):
            result = self.run_invocation(source, invocation)
        self.assert_incomplete(result, self.root/f'result-{self.serial}', 'resource_limit')

    def test_programmer_exceptions_are_not_semantic_rejections(self):
        source = stencil_source(1, 1)
        for error in (RuntimeError('bug'), ValueError('bug'), KeyError('bug')):
            invocation = self.invocation(source, [0]*4, [9])
            with self.subTest(error=error), patch.object(oracle, '_evaluate_expression', side_effect=error):
                with self.assertRaises(type(error)):
                    self.run_invocation(source, invocation)
            self.assertFalse((self.root/f'result-{self.serial}').exists())
        invocation = self.invocation(source, [0]*4, [9])
        with self.assertRaises(TypeError):
            self.run_invocation(source, invocation, oracle.OracleLimits(cancelled=lambda: 1))

    def test_no_forbidden_computational_dependencies_and_clean_import(self):
        source_text = inspect.getsource(oracle)
        tree = ast.parse(source_text)
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(item.name for item in node.names)
            if isinstance(node, ast.ImportFrom):
                imported.append(node.module or '')
        allowed_axiom = {'axiom.invocation_v2', 'axiom.model', 'axiom.source_profiles', 'axiom.artifact_chunks_v2'}
        self.assertTrue(all(name in allowed_axiom for name in imported if name.startswith('axiom.')), imported)
        code = """
import importlib.abc, sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        forbidden = ('reference', 'plan', 'check', 'select', 'emit', 'native', 'schedule')
        if fullname.startswith('axiom.') and any(word in fullname for word in forbidden):
            raise RuntimeError('forbidden computational dependency: '+fullname)
sys.meta_path.insert(0, Guard())
import source_oracle
from axiom.source_profiles import SourceProfileV2
assert source_oracle.OracleLimits().max_scalar_evaluations == 1000000000
"""
        process = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[2],
            env={**os.environ, 'PYTHONPATH': 'src:research'}, capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        # Only rank-sized collections may live in the interpreter. The output
        # iterator and producer reader contain no comprehension/materialization.
        producer_ast = ast.parse(inspect.getsource(oracle._iter_output))
        self.assertFalse(any(isinstance(node, (ast.ListComp, ast.DictComp, ast.SetComp)) for node in ast.walk(producer_ast)))


if __name__ == '__main__':
    unittest.main()
