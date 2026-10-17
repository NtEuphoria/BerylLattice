"""Production bounded byte blobs. A blob carries bytes, never semantic evidence.

Readers require stable files during each traversal. Descriptor-relative NOFOLLOW
opens reject path substitution; digest checks detect replacement between uses.
This is not protection against a same-UID writer racing individual reads.
"""
from __future__ import annotations
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
from typing import Iterable, Iterator

_MAX_INTEGER = (1 << 63)-1
_SHA256 = re.compile(r'[0-9a-f]{64}\Z')


def _integer(value, name, minimum=0, maximum=_MAX_INTEGER):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{name} must be an exact integer in [{minimum}, {maximum}]')
    return value


def _identity(value, name):
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise ValueError(f'{name} must be a lowercase SHA-256 identifier')
    return value


@dataclass(frozen=True, slots=True)
class BlobLimits:
    chunk_bytes: int = 1_048_576
    max_file_bytes: int = 16_777_216
    max_files: int = 16_384
    max_metadata_bytes: int = 1_048_576
    max_metadata_depth: int = 16
    max_metadata_items: int = 65_536

    def __post_init__(self):
        for name, maximum in (('chunk_bytes', 1_048_576), ('max_file_bytes', 16_777_216),
                              ('max_files', 16_384), ('max_metadata_bytes', 1_048_576),
                              ('max_metadata_depth', 16), ('max_metadata_items', 65_536)):
            _integer(getattr(self, name), name, 1, maximum)
        if self.chunk_bytes > self.max_file_bytes:
            raise ValueError('chunk size exceeds file limit')


def _limits(limits):
    if type(limits) is not BlobLimits:
        raise ValueError('expected BlobLimits')
    limits.__post_init__()


def canonical_json(value) -> bytes:
    """Sorted ASCII JSON with exact integers, no floats or nonfinite values."""
    def check(item):
        if item is None or type(item) in (str, bool):
            return
        if type(item) is int:
            _integer(item, 'JSON integer', -_MAX_INTEGER)
        elif type(item) in (list, tuple):
            for child in item:
                check(child)
        elif type(item) is dict and all(type(key) is str for key in item):
            for child in item.values():
                check(child)
        else:
            raise ValueError('invalid canonical JSON value')
    try:
        check(value)
        return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                          allow_nan=False).encode('ascii')
    except (RecursionError, TypeError, OverflowError, UnicodeError) as exc:
        raise ValueError('invalid canonical JSON') from exc


def _decode_json(raw, limits):
    if len(raw) > limits.max_metadata_bytes:
        raise ValueError('metadata byte limit exceeded')
    # Count container and scalar token starts before json.loads allocates them.
    depth, count, quoted, escaped, primitive = 0, 0, False, False, False
    for char in raw:
        if quoted:
            if escaped:
                escaped = False
            elif char == 92:
                escaped = True
            elif char == 34:
                quoted = False
        elif char == 34:
            quoted, primitive = True, False
            count += 1
        elif char in (123, 91):
            depth += 1
            count += 1
            primitive = False
            if depth > limits.max_metadata_depth:
                raise ValueError('metadata nesting limit exceeded')
        elif char in (125, 93):
            depth -= 1
            primitive = False
        elif char in (44, 58, 32, 9, 10, 13):
            primitive = False
        elif not primitive:
            primitive = True
            count += 1
        if count > limits.max_metadata_items:
            raise ValueError('metadata item limit exceeded')

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result

    def integer(token):
        if len(token.lstrip('-')) > 19:
            raise ValueError('metadata integer limit exceeded')
        return _integer(int(token), 'JSON integer', -_MAX_INTEGER)

    def forbidden(_):
        raise ValueError('floating JSON numbers are forbidden')

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_int=integer,
                           parse_float=forbidden, parse_constant=forbidden)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('invalid JSON metadata') from exc
    if canonical_json(value) != raw:
        raise ValueError('metadata must use canonical JSON')
    return value


def _keys(value, expected, name):
    if type(value) is not dict or set(value) != set(expected):
        raise ValueError(f'{name} has missing or unknown fields')


def _relative(value):
    if (type(value) is not str or not value or '\\' in value or '\x00' in value
            or value.startswith('/') or any(p in ('', '.', '..') for p in value.split('/'))):
        raise ValueError('expected normalized relative POSIX artifact path')
    return value


def _absolute(path):
    # Do not normalize away '..' through a possibly symlinked component.
    path = Path(path)
    if '..' in path.parts:
        raise ValueError('parent path components are forbidden')
    return Path(os.path.abspath(path))


@contextmanager
def _directory(path, *, create=False):
    path = _absolute(path)
    descriptors = []
    try:
        descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(descriptor)
        for part in path.parts[1:]:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            descriptor = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            descriptors.append(descriptor)
        yield descriptor
    except OSError as exc:
        raise ValueError('cannot open safe artifact directory') from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


@contextmanager
def _file(root, relative):
    parts = _relative(relative).split('/')
    with _directory(root) as root_fd:
        descriptors = []
        try:
            descriptor = root_fd
            for part in parts[:-1]:
                descriptor = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                descriptors.append(descriptor)
            descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
            descriptors.append(descriptor)
            yield descriptor
        except OSError as exc:
            raise ValueError('cannot read safe artifact file') from exc
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read_file(root, relative, maximum):
    with _file(root, relative) as descriptor:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 <= before.st_size <= maximum:
            raise ValueError('artifact is not a bounded regular file')
        blocks, count = [], 0
        while True:
            block = os.read(descriptor, min(65_536, maximum-count+1))
            if not block:
                break
            count += len(block)
            if count > maximum:
                raise ValueError('artifact file limit exceeded')
            blocks.append(block)
        after = os.fstat(descriptor)
        if _stamp(before) != _stamp(after) or count != after.st_size:
            raise ValueError('artifact changed during read')
        return b''.join(blocks), _stamp(after)


def _write_immutable(root, name, raw):
    _relative(name)
    if '/' in name:
        raise ValueError('writer expects a direct child name')
    with _directory(root, create=True) as descriptor:
        try:
            child = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                            0o400, dir_fd=descriptor)
            with os.fdopen(child, 'wb') as stream:
                stream.write(raw)
        except OSError as exc:
            raise ValueError('cannot create immutable artifact') from exc


def read_manifest(path: Path, *, limits: BlobLimits):
    _limits(limits)
    path = _absolute(path)
    raw, _ = _read_file(path.parent, path.name, min(limits.max_metadata_bytes, limits.max_file_bytes))
    return _decode_json(raw, limits), hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class BlobReference:
    manifest_path: Path
    manifest_sha256: str
    byte_length: int
    sha256: str

    def __post_init__(self):
        object.__setattr__(self, 'manifest_path', _absolute(self.manifest_path))
        _validate_reference(self)


def _validate_reference(reference):
    if type(reference) is not BlobReference or not isinstance(reference.manifest_path, Path):
        raise ValueError('expected immutable BlobReference with a Path')
    if _absolute(reference.manifest_path) != reference.manifest_path:
        raise ValueError('blob manifest path must be absolute')
    _identity(reference.manifest_sha256, 'manifest_sha256')
    _integer(reference.byte_length, 'byte_length')
    _identity(reference.sha256, 'sha256')


@dataclass(frozen=True, slots=True)
class ChunkReference:
    offset: int
    byte_length: int
    path: str
    sha256: str


def _validate_chunk(chunk, limits):
    if type(chunk) is not ChunkReference:
        raise ValueError('expected immutable ChunkReference')
    _integer(chunk.offset, 'chunk offset')
    _integer(chunk.byte_length, 'chunk byte length', 1, min(limits.chunk_bytes, limits.max_file_bytes))
    _relative(chunk.path)
    _identity(chunk.sha256, 'chunk sha256')


def _load_blob(reference, limits):
    _limits(limits)
    _validate_reference(reference)
    record, digest = read_manifest(reference.manifest_path, limits=limits)
    if digest != reference.manifest_sha256:
        raise ValueError('blob manifest identity changed')
    _keys(record, ('schema', 'byte_length', 'sha256', 'chunks'), 'blob manifest')
    if record['schema'] != 'axiom-blob-v2':
        raise ValueError('unsupported blob schema')
    _integer(record['byte_length'], 'byte_length')
    _identity(record['sha256'], 'blob sha256')
    if (record['byte_length'], record['sha256']) != (reference.byte_length, reference.sha256):
        raise ValueError('blob identity differs from reference')
    if type(record['chunks']) is not list or len(record['chunks'])+1 > limits.max_files:
        raise ValueError('invalid chunk count')
    offset, paths, chunks = 0, set(), []
    for item in record['chunks']:
        _keys(item, ('offset', 'byte_length', 'path', 'sha256'), 'chunk')
        _integer(item['offset'], 'offset')
        _integer(item['byte_length'], 'chunk length', 1, min(limits.chunk_bytes, limits.max_file_bytes))
        _relative(item['path'])
        _identity(item['sha256'], 'chunk sha256')
        if item['offset'] != offset or item['path'] in paths or item['path'] == reference.manifest_path.name:
            raise ValueError('chunks must cover bytes once, contiguously')
        offset += item['byte_length']
        if offset > reference.byte_length:
            raise ValueError('chunk coverage exceeds blob length')
        paths.add(item['path'])
        chunks.append(ChunkReference(**item))
    if offset != reference.byte_length:
        raise ValueError('incomplete blob coverage')
    return tuple(chunks)


@dataclass(frozen=True, slots=True)
class VerifiedBlob:
    reference: BlobReference
    limits: BlobLimits
    chunks: tuple[ChunkReference, ...]
    _cache: OrderedDict = field(default_factory=OrderedDict, repr=False, compare=False)

    @property
    def byte_length(self):
        return self.reference.byte_length

    @property
    def sha256(self):
        return self.reference.sha256

    @property
    def cached_chunk_count(self):
        return len(self._cache)

    def _chunk(self, number):
        chunk = self.chunks[number]
        raw, stamp = _read_file(self.reference.manifest_path.parent, chunk.path, self.limits.chunk_bytes)
        if len(raw) != chunk.byte_length or hashlib.sha256(raw).hexdigest() != chunk.sha256:
            raise ValueError('chunk identity changed')
        return raw, stamp

    def _validate_metadata(self):
        _validate_reference(self.reference)
        _limits(self.limits)
        if type(self.chunks) is not tuple or len(self.chunks)+1 > self.limits.max_files:
            raise ValueError('expected immutable bounded chunk tuple')
        offset, paths = 0, set()
        for chunk in self.chunks:
            _validate_chunk(chunk, self.limits)
            if chunk.offset != offset or chunk.path in paths or chunk.path == self.reference.manifest_path.name:
                raise ValueError('invalid verified chunk coverage')
            offset += chunk.byte_length
            if offset > self.byte_length:
                raise ValueError('verified chunk coverage exceeds blob length')
            paths.add(chunk.path)
        if offset != self.byte_length:
            raise ValueError('incomplete verified chunk coverage')
        if type(self._cache) is not OrderedDict or len(self._cache) > 2:
            raise ValueError('invalid scalar cache')

    def revalidate(self):
        self._validate_metadata()
        fresh = verify_blob(self.reference, limits=self.limits)
        if fresh.chunks != self.chunks:
            raise ValueError('verified blob metadata changed')
        self._cache.clear()

    def iter_bytes(self) -> Iterator[bytes]:
        self.revalidate()
        digest = hashlib.sha256()
        for number in range(len(self.chunks)):
            raw, _ = self._chunk(number)
            digest.update(raw)
            yield raw
        if digest.hexdigest() != self.sha256:
            raise ValueError('blob content identity changed')

    def _cached_chunk(self, number):
        chunk = self.chunks[number]
        # Cached bytes are only reused while the safely reopened file fingerprint
        # is unchanged. Full trust-boundary traversals always hash actual bytes.
        with _file(self.reference.manifest_path.parent, chunk.path) as descriptor:
            info = os.fstat(descriptor)
            stamp = _stamp(info)
            if not stat.S_ISREG(info.st_mode) or info.st_size != chunk.byte_length:
                raise ValueError('chunk identity changed')
        cached = self._cache.get(number)
        if cached is None or cached[0] != stamp:
            raw, stamp = self._chunk(number)
            cached = (stamp, raw)
        if number not in self._cache and len(self._cache) >= 2:
            self._cache.popitem(last=False)
        self._cache[number] = cached
        self._cache.move_to_end(number)
        return cached[1]

    def read_i32(self, index: int) -> int:
        _validate_reference(self.reference)
        _limits(self.limits)
        if type(self.chunks) is not tuple or len(self.chunks)+1 > self.limits.max_files:
            raise ValueError('expected immutable bounded chunk tuple')
        _integer(index, 'i32 index', 0, _MAX_INTEGER//4)
        if self.byte_length % 4 or index >= self.byte_length//4:
            raise ValueError('i32 index outside complete scalar blob')
        offset, end, pieces = index*4, index*4+4, []
        # Binary search supports valid variable-sized generic chunk layouts.
        low, high = 0, len(self.chunks)
        while low < high:
            middle = (low+high)//2
            _validate_chunk(self.chunks[middle], self.limits)
            if self.chunks[middle].offset+self.chunks[middle].byte_length <= offset:
                low = middle+1
            else:
                high = middle
        while offset < end:
            if low >= len(self.chunks):
                raise ValueError('incomplete verified chunk coverage')
            chunk = self.chunks[low]
            _validate_chunk(chunk, self.limits)
            if not chunk.offset <= offset < chunk.offset+chunk.byte_length:
                raise ValueError('invalid verified chunk coverage')
            raw = self._cached_chunk(low)
            size = min(end-offset, chunk.offset+chunk.byte_length-offset)
            pieces.append(raw[offset-chunk.offset:offset-chunk.offset+size])
            offset += size
            low += 1
        return struct.unpack('<i', b''.join(pieces))[0]


def verify_blob(reference: BlobReference, *, limits: BlobLimits) -> VerifiedBlob:
    chunks = _load_blob(reference, limits)
    verified = VerifiedBlob(reference, limits, chunks)
    digest = hashlib.sha256()
    for number in range(len(chunks)):
        raw, _ = verified._chunk(number)
        digest.update(raw)
    if digest.hexdigest() != reference.sha256:
        raise ValueError('blob content digest mismatch')
    return verified


def write_blob(blocks: Iterable[bytes], byte_length: int, directory: Path, *, limits: BlobLimits) -> BlobReference:
    _limits(limits)
    _integer(byte_length, 'byte_length')
    count = (byte_length+limits.chunk_bytes-1)//limits.chunk_bytes
    if count+1 > limits.max_files:
        raise ValueError('blob file count limit exceeded')
    directory = _absolute(directory)
    chunks, pending, total, digest = [], bytearray(), 0, hashlib.sha256()

    def flush():
        raw = bytes(pending)
        name = f'chunk-{len(chunks):08d}.bin'
        _write_immutable(directory, name, raw)
        chunks.append(dict(offset=total-len(raw), byte_length=len(raw), path=name,
                           sha256=hashlib.sha256(raw).hexdigest()))
        pending.clear()

    for block in blocks:
        if type(block) is not bytes or len(block) > byte_length-total:
            raise ValueError('blob blocks must be exact bytes within declared length')
        view = memoryview(block)
        start = 0
        while start < len(view):
            size = min(limits.chunk_bytes-len(pending), len(view)-start)
            pending.extend(view[start:start+size])
            digest.update(view[start:start+size])
            total += size
            start += size
            if len(pending) == limits.chunk_bytes:
                flush()
    if total != byte_length:
        raise ValueError('blob stream length differs from declaration')
    if pending:
        flush()
    raw = canonical_json(dict(schema='axiom-blob-v2', byte_length=total,
                              sha256=digest.hexdigest(), chunks=chunks))
    _decode_json(raw, limits)
    if len(raw) > limits.max_file_bytes:
        raise ValueError('manifest exceeds file bound')
    _write_immutable(directory, 'blob.json', raw)
    return BlobReference(directory/'blob.json', hashlib.sha256(raw).hexdigest(), total, digest.hexdigest())
