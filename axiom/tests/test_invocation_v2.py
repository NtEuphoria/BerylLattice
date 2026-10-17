"""Exact source binding and reject-before-consumption tests."""
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

from axiom.artifact_chunks_v2 import BlobLimits, ChunkReference, canonical_json
from axiom.invocation_v2 import InvocationLimits, verify_invocation, write_invocation
from axiom.model import DiagnosticError
from axiom.source_profiles import SourceLimitsV2, SourceProfileV2, admit_source_v2
from tests.helpers import stencil_source
from tests.test_artifact_chunks_v2 import replace_file
from research.state_artifacts import StateMetadata


class InvocationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.limits = InvocationLimits()

    def invocation(self, source=None, target='invocation'):
        return write_invocation(source or stencil_source(1, 1), [struct.pack('<4i', 0, 1, 1024, -1)],
                                [struct.pack('<i', 29)], self.root/target, limits=self.limits)

    def test_invocation_exact_source_and_family_bindings(self):
        a = verify_invocation(self.invocation(), limits=self.limits)
        b = verify_invocation(self.invocation(b'// changed name\n'+stencil_source(1, 1), 'other'), limits=self.limits)
        self.assertEqual(a.source_sha256, hashlib.sha256(a.source_bytes).hexdigest())
        self.assertEqual(a.family_semantics_sha256, b.family_semantics_sha256)
        self.assertEqual(a.specialization_semantics_sha256, b.specialization_semantics_sha256)
        self.assertNotEqual(a.invocation_sha256, b.invocation_sha256)
        self.assertNotEqual(a.source_sha256, b.source_sha256)
        c = verify_invocation(self.invocation(target='same'), limits=self.limits)
        self.assertEqual(a.invocation_sha256, c.invocation_sha256)
        self.assertEqual((a.H, a.W), (1, 1))
        self.assertEqual(a.input.read_i32(2), 1024)  # Transport retains rejected source input.
        self.assertEqual(a.initial_output.read_i32(0), 29)
        self.assertNotEqual(a.invocation_sha256, a.state_v1_invocation_sha256())
        state = StateMetadata(a.specialization_semantics_sha256, a.H, a.W, a.input.sha256, a.initial_output.sha256)
        self.assertEqual(a.state_v1_invocation_sha256(), state.invocation_sha256)
        with self.assertRaises(FrozenInstanceError):
            a.H = 2
        for field, value in (('source_sha256', '0'*64), ('family_semantics_sha256', a.specialization_semantics_sha256),
                             ('specialization_semantics_sha256', a.family_semantics_sha256), ('H', 2),
                             ('W', True), ('buffer_contract', 'claimed-aliasing')):
            path = self.invocation(target=field)
            record = json.loads(path.read_bytes())
            record[field] = value
            replace_file(path, canonical_json(record))
            with self.assertRaises(ValueError):
                verify_invocation(path, limits=self.limits)

    def test_invocation_identity_excludes_rechunking_and_paths(self):
        source = stencil_source(1, 1)
        raw_input, raw_output = struct.pack('<4i', 0, 1, 1024, -1), struct.pack('<i', 29)
        original = verify_invocation(self.invocation(), limits=self.limits)
        tiny = InvocationLimits(blobs=BlobLimits(chunk_bytes=3))
        path = write_invocation(source, [raw_input[:1], raw_input[1:]], [raw_output],
                                self.root/'different-layout', limits=tiny)
        changed = verify_invocation(path, limits=tiny)
        self.assertNotEqual(original.input.reference.manifest_sha256, changed.input.reference.manifest_sha256)
        self.assertEqual(original.invocation_sha256, changed.invocation_sha256)
        self.assertEqual(original.state_v1_invocation_sha256(), changed.state_v1_invocation_sha256())

    def test_invocation_extent_rejected_before_iterator_read(self):
        class Untouched:
            reads = 0
            def __iter__(self):
                self.reads += 1
                raise RuntimeError('must not consume invalid extent')
        for h, w in ((8193, 1), (8192, 1023), (0, 1)):
            blocks = Untouched()
            with self.assertRaises((ValueError, DiagnosticError)):
                write_invocation(stencil_source(h, w), blocks, blocks, self.root/f'bad-{h}-{w}', limits=self.limits)
            self.assertEqual(blocks.reads, 0)
        for h, w, p, input_bytes, output_bytes in ((2049, 2047, 4198400, 16793600, 16777212),
                                                  (2048, 2048, 4198401, 16793604, 16777216)):
            admitted = admit_source_v2(stencil_source(h, w), profile=SourceProfileV2(), limits=SourceLimitsV2())
            self.assertEqual(admitted.input_cells, p)
            self.assertEqual(4*admitted.input_cells, input_bytes)
            self.assertEqual(4*admitted.output_cells, output_bytes)
        self.assertEqual(4*((2048+1)**2+2048**2), 33570820)

    def test_verified_invocation_revalidates_mutated_files(self):
        for role in ('source', 'input', 'initial_output', 'manifest'):
            path = self.invocation(target=role)
            verified = verify_invocation(path, limits=self.limits)
            if role == 'manifest':
                replace_file(path, path.read_bytes()+b' ')
            else:
                blob = verified.source if role == 'source' else getattr(verified, role)
                chunk = blob.reference.manifest_path.parent/blob.chunks[-1].path
                raw = chunk.read_bytes()
                replace_file(chunk, bytes([raw[0]^1])+raw[1:])
            with self.assertRaises(ValueError):
                verified.revalidate()

    def test_invocation_revalidation_rejects_forged_typed_records(self):
        verified = verify_invocation(self.invocation(), limits=self.limits)
        original = verified.input.chunks[0]
        chunk = object.__new__(ChunkReference)
        for field in ('offset', 'byte_length', 'path', 'sha256'):
            value = getattr(original, field)
            object.__setattr__(chunk, field, float(value) if field in ('offset', 'byte_length') else value)
        input_blob = replace(verified.input, chunks=(chunk,))
        for forged in (replace(verified, input=input_blob),
                       replace(verified, source_bytes=bytearray(verified.source_bytes))):
            with self.assertRaises(ValueError):
                forged.revalidate()
        limits = object.__new__(InvocationLimits)
        object.__setattr__(limits, 'blobs', self.limits.blobs)
        object.__setattr__(limits, 'source_profile', {})
        object.__setattr__(limits, 'source_limits', self.limits.source_limits)
        with self.assertRaises(ValueError):
            replace(verified, limits=limits).revalidate()

    def test_manifest_boundaries_and_exact_lengths(self):
        for input_raw, output_raw in ((b'\x00'*15, b'\x00'*4), (b'\x00'*16, b'\x00'*3)):
            with self.assertRaises(ValueError):
                write_invocation(stencil_source(1, 1), [input_raw], [output_raw],
                                 self.root/str(len(list(self.root.iterdir()))), limits=self.limits)
        path = self.invocation()
        record = json.loads(path.read_bytes())
        record['input']['path'] = '../escape'
        replace_file(path, canonical_json(record))
        with self.assertRaises(ValueError):
            verify_invocation(path, limits=self.limits)


if __name__ == '__main__':
    unittest.main()
