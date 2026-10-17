"""Bounded arbitrary-byte transport boundary tests."""
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from axiom.artifact_chunks_v2 import (
    BlobLimits, BlobReference, ChunkReference, canonical_json, verify_blob, write_blob,
)


def replace_file(path, raw):
    path.unlink()
    path.write_bytes(raw)


class BlobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.limits = BlobLimits(chunk_bytes=8)

    def blob(self, raw=b'abcdefghijklmnopq'):
        return write_blob([raw[:3], raw[3:12], raw[12:]], len(raw), self.root/'blob', limits=self.limits)

    def altered(self, reference, change):
        record = json.loads(reference.manifest_path.read_bytes())
        change(record)
        raw = canonical_json(record)
        replace_file(reference.manifest_path, raw)
        return BlobReference(reference.manifest_path, hashlib.sha256(raw).hexdigest(),
                             reference.byte_length, reference.sha256)

    def test_chunk_transport_exact_coverage(self):
        reference = self.blob()
        verified = verify_blob(reference, limits=self.limits)
        self.assertEqual(b''.join(verified.iter_bytes()), b'abcdefghijklmnopq')
        self.assertEqual([c.byte_length for c in verified.chunks], [8, 8, 1])
        with self.assertRaises(FrozenInstanceError):
            reference.byte_length = 0
        empty = write_blob([], 0, self.root/'empty', limits=self.limits)
        self.assertEqual(list(verify_blob(empty, limits=self.limits).iter_bytes()), [])
        for change in (lambda d: d['chunks'].pop(),
                       lambda d: d['chunks'][1].update(offset=7),
                       lambda d: d['chunks'][0].update(offset=True),
                       lambda d: d['chunks'][0].update(offset=-1),
                       lambda d: d.update(byte_length=True),
                       lambda d: d.update(schema='other')):
            with self.subTest(change=change):
                path = self.root / str(len(list(self.root.iterdir())))
                ref = write_blob([b'a'*17], 17, path, limits=self.limits)
                with self.assertRaises(ValueError):
                    verify_blob(self.altered(ref, change), limits=self.limits)
        for blocks, length in (([b'a'], 2), ([b'abc'], 2), ([bytearray(b'a')], 1)):
            with self.assertRaises(ValueError):
                write_blob(blocks, length, self.root/str(len(list(self.root.iterdir()))), limits=self.limits)

    def test_chunk_reader_bounds_and_endianness(self):
        raw = struct.pack('<5i', -2147483648, -1, 0, 1024, 2147483647)
        reader = verify_blob(write_blob([raw], len(raw), self.root/'ints', limits=self.limits), limits=self.limits)
        self.assertEqual([reader.read_i32(i) for i in range(5)], [-2147483648, -1, 0, 1024, 2147483647])
        for index in (-1, True, 5, 2**63, 0.0):
            with self.assertRaises(ValueError):
                reader.read_i32(index)
        with self.assertRaises(ValueError):
            verify_blob(self.blob(), limits=self.limits).read_i32(0)
        odd = BlobLimits(chunk_bytes=3)
        crossing = verify_blob(write_blob([struct.pack('<2i', -1, 1024)], 8,
                                         self.root/'crossing', limits=odd), limits=odd)
        self.assertEqual([crossing.read_i32(i) for i in range(2)], [-1, 1024])

    def test_metadata_and_paths_are_strict(self):
        ref = self.blob()
        original = ref.manifest_path.read_bytes()
        for raw in (b'{"schema":"axiom-blob-v2","schema":"axiom-blob-v2"}',
                    b'['*17+b']'*17, b' '*1048577,
                    original.replace(b'"offset":0', b'"offset":9223372036854775808')):
            replace_file(ref.manifest_path, raw)
            forged = BlobReference(ref.manifest_path, hashlib.sha256(raw).hexdigest(), ref.byte_length, ref.sha256)
            with self.assertRaises(ValueError):
                verify_blob(forged, limits=self.limits)
        replace_file(ref.manifest_path, original)
        for path in ('../escape', '/absolute', 'a/../x', './x', 'a\\x'):
            altered = self.altered(ref, lambda d: d['chunks'][0].update(path=path))
            with self.assertRaises(ValueError):
                verify_blob(altered, limits=self.limits)
            replace_file(ref.manifest_path, original)
        chunk = self.root/'blob'/json.loads(original)['chunks'][0]['path']
        backup = self.root/'backup'
        chunk.rename(backup)
        chunk.symlink_to(backup)
        with self.assertRaises(ValueError):
            verify_blob(ref, limits=self.limits)
        for field, value in (('chunk_bytes', True), ('max_file_bytes', 16777217),
                             ('max_files', 16385), ('max_metadata_depth', 17)):
            with self.assertRaises(ValueError):
                BlobLimits(**{field: value})

    def test_limits_precede_decoder_and_writer_consumption(self):
        ref = self.blob()
        for raw, limits in ((b'['*17+b']'*17, self.limits),
                            (b'[0,0,0]', BlobLimits(max_metadata_items=3)),
                            (b' '*20, BlobLimits(max_metadata_bytes=10))):
            replace_file(ref.manifest_path, raw)
            changed = BlobReference(ref.manifest_path, hashlib.sha256(raw).hexdigest(), ref.byte_length, ref.sha256)
            with patch('axiom.artifact_chunks_v2.json.loads', side_effect=RuntimeError('decoder touched')):
                with self.assertRaises(ValueError):
                    verify_blob(changed, limits=limits)
        def forbidden():
            raise RuntimeError('iterator touched')
            yield b''
        for length in (-1, True, 2**63, 9):
            with self.assertRaises(ValueError):
                write_blob(forbidden(), length, self.root/'bad', limits=BlobLimits(chunk_bytes=8, max_files=2))
        target = self.root/'real'
        target.mkdir()
        link = self.root/'link'
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaises(ValueError):
            write_blob([b'a'], 1, link/'child', limits=self.limits)
        self.assertEqual(list(target.iterdir()), [])
        with self.assertRaises(ValueError):
            self.blob()  # Immutable names must never overwrite an existing blob.

    def test_missing_nonregular_and_symlink_ancestor_reject(self):
        for fault in ('missing', 'directory', 'fifo'):
            ref = write_blob([b'a'], 1, self.root/fault, limits=self.limits)
            verified = verify_blob(ref, limits=self.limits)
            chunk = ref.manifest_path.parent/verified.chunks[0].path
            chunk.unlink()
            if fault == 'directory':
                chunk.mkdir()
            elif fault == 'fifo':
                os.mkfifo(chunk)
            with self.assertRaises(ValueError):
                verified.revalidate()
        holder = self.root/'holder'
        ref = write_blob([b'a'], 1, holder/'blob', limits=self.limits)
        verified = verify_blob(ref, limits=self.limits)
        holder.rename(self.root/'real-holder')
        holder.symlink_to(self.root/'real-holder', target_is_directory=True)
        with self.assertRaises(ValueError):
            list(verified.iter_bytes())

    def test_failed_stream_retains_prefix_without_accepted_manifest(self):
        target = self.root/'incomplete'
        def broken():
            yield b'a'*8
            raise RuntimeError('acquisition failed')
        with self.assertRaisesRegex(RuntimeError, 'acquisition failed'):
            write_blob(broken(), 16, target, limits=self.limits)
        self.assertEqual((target/'chunk-00000000.bin').read_bytes(), b'a'*8)
        self.assertFalse((target/'blob.json').exists())

    def test_revalidation_rejects_forged_typed_metadata(self):
        verified = verify_blob(write_blob([b'1234'], 4, self.root/'forged', limits=self.limits), limits=self.limits)
        original = verified.chunks[0]
        for field, value in (('offset', 0.0), ('offset', False), ('byte_length', 4.0), ('byte_length', True)):
            chunk = object.__new__(ChunkReference)
            for name in ('offset', 'byte_length', 'path', 'sha256'):
                object.__setattr__(chunk, name, value if name == field else getattr(original, name))
            forged = replace(verified, chunks=(chunk,))
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                forged.revalidate()
            with self.subTest(read=field, value=value), self.assertRaises(ValueError):
                forged.read_i32(0)
        for chunks in ([original], (object(),)):
            forged = replace(verified, chunks=chunks)
            with self.assertRaises(ValueError):
                forged.revalidate()
        forged_limits = object.__new__(BlobLimits)
        for field in ('chunk_bytes', 'max_file_bytes', 'max_files', 'max_metadata_bytes',
                      'max_metadata_depth', 'max_metadata_items'):
            object.__setattr__(forged_limits, field, 8.0 if field == 'chunk_bytes' else getattr(self.limits, field))
        with self.assertRaises(ValueError):
            replace(verified, limits=forged_limits).revalidate()

    def test_actual_files_rechecked_and_cache_bounded(self):
        raw = struct.pack('<12i', *range(12))
        verified = verify_blob(write_blob([raw], len(raw), self.root/'mutate', limits=self.limits), limits=self.limits)
        for i in range(12):
            self.assertEqual(verified.read_i32(i), i)
        self.assertLessEqual(verified.cached_chunk_count, 2)
        chunk = verified.reference.manifest_path.parent/verified.chunks[-1].path
        replace_file(chunk, b'\x00'*8)
        for action in (verified.revalidate, lambda: list(verified.iter_bytes()), lambda: verified.read_i32(11)):
            with self.assertRaises(ValueError):
                action()


if __name__ == '__main__':
    unittest.main()
