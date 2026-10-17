"""Complete-state format checks; synthetic data are never native evidence."""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from dataclasses import replace
try:
    from research import state_artifacts as s
except ModuleNotFoundError:
    import state_artifacts as s
ID = hashlib.sha256(b'test semantic identity').hexdigest()

class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
    def meta(self, **changes):
        values = dict(logical_semantics_sha256=ID, H=1, W=1,
                      original_input_sha256=ID, initial_output_sha256=ID)
        values.update(changes)
        return s.StateMetadata(**values)
    def write(self, **changes):
        return s.write_state([0, 1, 2, 3], [9], self.meta(**changes), self.root)
    def alter(self, manifest, change):
        data = json.loads(manifest.read_text())
        change(data)
        manifest.write_bytes(s.canonical_json(data))
    def test_little_endian_full_i32_capacity_and_streaming(self):
        values = [-2147483648, -1, 0, 2147483647]
        p = s.write_state(iter(values), iter([9]), self.meta(), self.root)
        v = s.verify_state(p)
        self.assertEqual(b''.join(v.iter_bytes('input_after')), struct.pack('<4i', *values))
        self.assertEqual(list(v.iter_scalars('input_after')), values)
        self.assertEqual(v.logical_bytes, 20)
        self.assertEqual(v.metadata.invocation_sha256, self.meta().invocation_sha256)
        self.assertGreaterEqual(len(v.closure), 3)
        self.assertTrue(all(c.sha256 == hashlib.sha256(c.resolved_path.read_bytes()).hexdigest() for c in v.closure))
    def test_shape_lengths_and_integer_bounds_are_checked(self):
        for values in ([], [1] * 3, [1] * 5, [1, 2, 3, True], [1, 2, 3, 2147483648]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                s.write_state(values, [0], self.meta(), self.root)
        for changes in ({'H': 0}, {'W': True}, {'H': 2**80}, {'logical_semantics_sha256': 'abc'},
                        {'status': 'failed'}, {'first_bad_index': 0}, {'status': 'input_precondition_failed'},
                        {'status': 'input_precondition_failed', 'first_bad_index': 4}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                s.write_state([0] * 4, [0], self.meta(**changes), self.root)
        v = s.verify_state(self.write(status='input_precondition_failed', first_bad_index=3))
        self.assertEqual(v.metadata.first_bad_index, 3)
    def test_exact_coverage_rejects_missing_extra_reordered_and_overlap(self):
        limits = s.ArtifactLimits(chunk_bytes=8)
        p = s.write_state([0, 1, 2, 3], [9], self.meta(), self.root, limits=limits)
        original = p.read_bytes()
        changes = [lambda d: d.update(chunks=[]), lambda d: d['chunks'].pop(),
                   lambda d: d['chunks'].append(d['chunks'][0]), lambda d: d['chunks'].reverse(),
                   lambda d: d['chunks'][1].update(offset=0), lambda d: d['chunks'][0].update(byte_length=0),
                   lambda d: d['chunks'][0].update(role='unknown')]
        for change in changes:
            p.write_bytes(original)
            self.alter(p, change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                s.verify_state(p, limits)
    def test_corruption_and_post_verification_mutation_fail(self):
        p = self.write()
        v = s.verify_state(p)
        chunk = next(c for c in v.closure if c.path.endswith('.i32'))
        chunk.resolved_path.write_bytes(b'X' * chunk.byte_length)
        with self.assertRaises(ValueError): s.verify_state(p)
        with self.assertRaises(ValueError): list(v.iter_scalars('input_after'))
    def test_duplicate_keys_noncanonical_and_metadata_bounds_fail(self):
        p = self.write()
        original = p.read_bytes()
        for data in (b'{"version":1,"version":1}', original+b' ',
                     b'{"x":'+b'['*30+b'0'+b']'*30+b'}', b'{"x":'+b'9'*10000+b'}'):
            p.write_bytes(data)
            with self.assertRaises(ValueError): s.verify_state(p)
        p.write_bytes(original)
        for limits in (s.ArtifactLimits(max_metadata_bytes=10), s.ArtifactLimits(max_metadata_items=2),
                       s.ArtifactLimits(max_metadata_depth=1)):
            with self.subTest(limits=limits), self.assertRaises(ValueError): s.verify_state(p, limits)
    def test_same_hash_and_path_at_distinct_offsets_is_valid(self):
        limits = s.ArtifactLimits(chunk_bytes=8)
        p = s.write_state([0]*4, [0], self.meta(), self.root, limits=limits)
        data = json.loads(p.read_text())
        self.assertEqual(data['chunks'][0]['path'], data['chunks'][1]['path'])
        v = s.verify_state(p, limits)
        self.assertEqual(list(v.iter_scalars('input_after')), [0]*4)
        self.assertEqual(v.logical_bytes, 20)
        with self.assertRaises(ValueError): s.verify_state(p, replace(limits, max_logical_bytes=19))
    def test_paths_symlinks_and_complete_closure_limits(self):
        p = self.write()
        original = p.read_bytes()
        for path in ('../escape.i32', '/tmp/escape.i32', 'chunks/../escape.i32'):
            self.alter(p, lambda d: d['chunks'][0].update(path=path))
            with self.assertRaises(ValueError): s.verify_state(p)
            p.write_bytes(original)
        link = self.root/'link'
        link.symlink_to(self.root/json.loads(p.read_text())['chunks'][0]['path'])
        self.alter(p, lambda d: d['chunks'][0].update(path='link'))
        with self.assertRaises(ValueError): s.verify_state(p)
        p.write_bytes(original)
        extra = self.root/'pilot.json'
        extra.write_bytes(b'x'*100)
        v = s.verify_state(p, closure_paths=['pilot.json'])
        self.assertIn('pilot.json', [c.path for c in v.closure])
        actual = sum(c.byte_length for c in v.closure)
        for limits in (replace(s.ArtifactLimits(), max_aggregate_bytes=actual-1),
                       replace(s.ArtifactLimits(), max_files=len(v.closure)-1),
                       replace(s.ArtifactLimits(), chunk_bytes=8, max_file_bytes=10)):
            with self.assertRaises(ValueError): s.verify_state(p, limits, closure_paths=['pilot.json'])
        copy = self.root/'pilot-copy.json'
        copy.write_bytes(extra.read_bytes())
        v2 = s.verify_state(p, closure_paths=['pilot.json', 'pilot-copy.json', 'pilot.json'])
        self.assertEqual(sum(c.byte_length for c in v2.closure), actual+100)
    def test_bytewise_comparison_reports_role_coordinate_and_metadata(self):
        a = s.verify_state(self.write())
        b = s.verify_state(s.write_state([0, 1, 8, 3], [9], self.meta(), self.root/'other'))
        c = s.compare_state(a, b)
        self.assertFalse(c.equal)
        self.assertEqual((c.role, c.index, c.coordinate), ('input_after', 2, (1, 0)))
        self.assertEqual((c.left, c.right), (2, 8))
        v = s.verify_state(s.write_state([0, 1, 2, 3], [9], self.meta(), self.root/'third'))
        self.assertTrue(s.compare_state(a, v).equal)
        v = s.verify_state(s.write_state([0, 1, 2, 3], [9], self.meta(original_input_sha256='f'*64), self.root/'fourth'))
        self.assertFalse(s.compare_state(a, v).equal)
    def test_acquisition_separate_from_canonical_semantic_state(self):
        a = self.write()
        b = s.write_state([0, 1, 2, 3], [9], self.meta(), self.root/'second')
        self.assertEqual(a.read_bytes(), b.read_bytes())
        common = dict(run_sha256=ID, collector_sha256=ID, plan_sha256=ID,
                      emitted_kernel_sha256=ID, binary_sha256=ID, mode='synthetic',
                      started_utc='2026-10-15T00:00:00Z', completed_utc='2026-10-15T00:00:01Z')
        x = s.write_acquisition(a, s.AcquisitionMetadata(**common), name='acq-a.json')
        common.update(run_sha256='d'*64, plan_sha256='f'*64, emitted_kernel_sha256='e'*64)
        y = s.write_acquisition(a, s.AcquisitionMetadata(**common), name='acq-b.json')
        self.assertNotEqual(x.read_bytes(), y.read_bytes())
        v = s.verify_state(a, sidecars=[x.name, y.name])
        self.assertIn(x.name, [c.path for c in v.closure])
        self.assertEqual(s.verify_acquisition(x, v).mode, 'synthetic')
        self.alter(x, lambda d: d.update(state_manifest_sha256='a'*64))
        with self.assertRaises(ValueError): s.verify_state(a, sidecars=[x.name])
    def test_limits_preflight_before_consuming_or_allocating_state(self):
        def forbidden():
            raise AssertionError('state consumed before declared bounds were checked')
            yield 0
        for limits in (s.ArtifactLimits(max_logical_bytes=19),
                       s.ArtifactLimits(max_metadata_items=2)):
            with self.subTest(limits=limits), self.assertRaises(ValueError):
                s.write_state(forbidden(), forbidden(), self.meta(), self.root, limits=limits)
    def test_semantic_identity_and_shape_tampering_fail(self):
        p = self.write()
        original = p.read_bytes()
        for change in (lambda d: d['metadata'].update(invocation_sha256='f'*64),
                       lambda d: d['metadata']['shape'].update(H=True),
                       lambda d: d['metadata'].update(extra='unexpected'),
                       lambda d: d['chunks'][0].update(offset=True)):
            p.write_bytes(original)
            self.alter(p, change)
            with self.assertRaises(ValueError): s.verify_state(p)
    def test_acquisition_rejects_malformed_utc_and_mutated_closure(self):
        common = dict(run_sha256=ID, collector_sha256=ID, plan_sha256=ID,
                      emitted_kernel_sha256=ID, binary_sha256=ID, mode='synthetic',
                      started_utc='2026-10-15T00:00:00Z', completed_utc='2026-10-15T00:00:01Z')
        for value in ('2026-10-15Z', '2026-10-15T00:00:00', '2026-10-14T00:00:00Z'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                s.AcquisitionMetadata(**dict(common, completed_utc=value))
        p = self.write()
        x = s.write_acquisition(p, s.AcquisitionMetadata(**common))
        pilot = self.root/'pilot'
        pilot.write_bytes(b'original pilot')
        state = s.verify_state(p, sidecars=[x.name], closure_paths=['pilot'])
        pilot.write_bytes(b'mutated pilot')
        with self.assertRaises(ValueError): s.verify_acquisition(x, state)
    def test_revalidation_rejects_swapped_symlink_ancestor(self):
        holder = self.root/'holder'
        p = s.write_state([0, 1, 2, 3], [9], self.meta(), holder/'bundle')
        verified = s.verify_state(p)
        holder.rename(self.root/'real-holder')
        holder.symlink_to(self.root/'real-holder', target_is_directory=True)
        with self.assertRaises(ValueError): list(verified.iter_bytes('input_after'))
    def test_write_rejects_swapped_directory_without_outside_file(self):
        bundle = self.root/'bundle'
        outside = self.root/'outside'
        outside.mkdir()
        original_open = s.os.open
        swapped = False
        def swapping_open(path, flags, *args, **kwargs):
            nonlocal swapped
            if flags & s.os.O_CREAT and not swapped:
                swapped = True
                (bundle/'chunks').rename(bundle/'original-chunks')
                (bundle/'chunks').symlink_to(outside, target_is_directory=True)
            return original_open(path, flags, *args, **kwargs)
        with patch.object(s.os, 'open', side_effect=swapping_open):
            with self.assertRaises(ValueError):
                s.write_state([1, 2, 3, 4], [5], self.meta(), bundle)
        self.assertTrue(swapped)
        self.assertEqual(list(outside.iterdir()), [])
    def test_directory_creation_does_not_follow_swapped_ancestor(self):
        holder = self.root/'holder'
        holder.mkdir()
        outside = self.root/'outside'
        outside.mkdir()
        original_mkdir = s.os.mkdir
        swapped = False
        def swapping_mkdir(path, *args, **kwargs):
            nonlocal swapped
            if Path(path).name == 'bundle' and not swapped:
                swapped = True
                holder.rename(self.root/'original-holder')
                holder.symlink_to(outside, target_is_directory=True)
            return original_mkdir(path, *args, **kwargs)
        with patch.object(s.os, 'mkdir', side_effect=swapping_mkdir):
            with self.assertRaises(ValueError):
                s.write_state([1, 2, 3, 4], [5], self.meta(), holder/'bundle')
        self.assertTrue(swapped)
        self.assertEqual(list(outside.iterdir()), [])
    def test_primary_size_synthetic_streaming_roundtrip_format_only(self):
        H, W = 2049, 2047
        p = s.write_state(iter(range((H+1)*(W+1))), (-n-1 for n in range(H*W)),
                          self.meta(H=H, W=W), self.root)
        v = s.verify_state(p)
        self.assertEqual(v.logical_bytes, 33570812)
        self.assertEqual(sum(map(len, v.iter_bytes('input_after'))), 16793600)
        self.assertEqual(sum(map(len, v.iter_bytes('output'))), 16777212)
        self.assertTrue(all(n == i for i, n in enumerate(v.iter_scalars('input_after'))))
        self.assertTrue(all(n == -i-1 for i, n in enumerate(v.iter_scalars('output'))))
        self.assertEqual(sum(c.byte_length for c in v.closure if c.path.endswith('.i32')), 33570812)
        self.assertTrue(all(c.byte_length <= 16777216 for c in v.closure))
if __name__ == '__main__': unittest.main()
