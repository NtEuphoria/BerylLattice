"""Lossless complete-state artifacts; declarations do not prove native acquisition."""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
from typing import Iterable, Iterator

_ROLES = ('input_after', 'output')
_SHA256 = re.compile(r'[0-9a-f]{64}\Z')
_MAX_INTEGER = (1 << 63)-1


def _integer(value, name, minimum=0, maximum=_MAX_INTEGER):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{name} must be an integer in [{minimum}, {maximum}]')
    return value


def _identity(value, name):
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f'{name} must be a lowercase SHA-256 identifier')
    return value


@dataclass(frozen=True)
class ArtifactLimits:
    chunk_bytes: int = 1_048_576
    max_file_bytes: int = 16_777_216
    max_aggregate_bytes: int = 268_435_456
    max_files: int = 16_384
    max_logical_bytes: int = 268_435_456
    max_metadata_bytes: int = 1_048_576
    max_metadata_depth: int = 16
    max_metadata_items: int = 65_536

    def __post_init__(self):
        for name, value in asdict(self).items():
            _integer(value, name, 1)
        if self.chunk_bytes % 4 or self.chunk_bytes > self.max_file_bytes:
            raise ValueError('chunk_bytes must be i32 aligned and fit max_file_bytes')


def canonical_json(value) -> bytes:
    """V1 JSON: ASCII, sorted keys, no whitespace, floating numbers or NaN."""
    def check(item):
        if item is None or type(item) in (str, int, bool):
            return
        if type(item) in (list, tuple):
            for child in item:
                check(child)
        elif type(item) is dict and all(type(key) is str for key in item):
            for child in item.values():
                check(child)
        else:
            raise ValueError('canonical JSON requires integer JSON values')
    try:
        check(value)
        return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')
    except (RecursionError, TypeError, OverflowError) as exc:
        raise ValueError('invalid canonical JSON') from exc


def _decode_json(raw, limits):
    if len(raw) > limits.max_metadata_bytes:
        raise ValueError('metadata byte limit exceeded')
    # Bound depth and token growth before the JSON decoder allocates containers.
    depth, punctuation, quoted, escaped = 0, 0, False, False
    for char in raw:
        if quoted:
            if escaped:
                escaped = False
            elif char == 92:
                escaped = True
            elif char == 34:
                quoted = False
        elif char == 34:
            quoted = True
        elif char in (123, 91):
            depth += 1
            punctuation += 1
            if depth > limits.max_metadata_depth:
                raise ValueError('metadata nesting limit exceeded')
        elif char in (125, 93):
            depth -= 1
        elif char in (44, 58):
            punctuation += 1
        if punctuation > 2*limits.max_metadata_items:
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
        value = int(token)
        if abs(value) > _MAX_INTEGER:
            raise ValueError('metadata integer limit exceeded')
        return value

    def forbidden(_):
        raise ValueError('floating and nonfinite JSON numbers are forbidden')

    try:
        decoded = json.loads(raw, object_pairs_hook=pairs, parse_int=integer, parse_float=forbidden, parse_constant=forbidden)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('invalid JSON metadata') from exc
    pending, count = [decoded], 0
    while pending:
        item = pending.pop()
        count += 1
        if count > limits.max_metadata_items:
            raise ValueError('metadata item limit exceeded')
        if type(item) is dict:
            pending.extend(item.keys())
            pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)
    if canonical_json(decoded) != raw:
        raise ValueError('metadata must use canonical JSON')
    return decoded


def _keys(value, expected, name):
    if type(value) is not dict or set(value) != set(expected):
        raise ValueError(f'{name} has missing or unknown fields')


def _relative(value):
    if not isinstance(value, str) or not value or '\\' in value:
        raise ValueError('artifact path must be a relative POSIX path')
    if PurePosixPath(value).is_absolute() or any(p in ('', '.', '..') for p in value.split('/')):
        raise ValueError('artifact path escapes or is not normalized')
    return value


def _root(path):
    absolute = Path(os.path.abspath(path))
    for component in (absolute, *absolute.parents):
        if component.is_symlink():
            raise ValueError('symlink paths are forbidden')
    return absolute


@dataclass(frozen=True)
class ClosureFile:
    path: str
    resolved_path: Path
    sha256: str
    byte_length: int


def _read_file(root, relative, maximum, retain=False):
    """Open all path components with NOFOLLOW and hash every actual byte."""
    relative = _relative(relative)
    descriptors = []
    try:
        descriptor = os.open(root.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(descriptor)
        for component in root.parts[1:]:
            descriptor = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            descriptors.append(descriptor)
        parts = relative.split('/')
        for part in parts[:-1]:
            descriptor = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            descriptors.append(descriptor)
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        descriptors.append(descriptor)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
            raise ValueError('artifact is not a regular bounded file')
        digest, size, pieces = hashlib.sha256(), 0, []
        while True:
            block = os.read(descriptor, min(65_536, maximum-size+1))
            if not block:
                break
            size += len(block)
            if size > maximum:
                raise ValueError('artifact file byte limit exceeded')
            digest.update(block)
            if retain:
                pieces.append(block)
        after = os.fstat(descriptor)
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns) or size != after.st_size:
            raise ValueError('artifact changed while reading')
        return ClosureFile(relative, root/relative, digest.hexdigest(), size), b''.join(pieces) if retain else None
    except OSError as exc:
        raise ValueError(f'cannot read safe artifact path: {relative}') from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


class _Budget:
    def __init__(self, root, limits):
        self.root, self.limits, self.records, self.total = root, limits, {}, 0

    def add(self, relative, *, metadata=False):
        relative = _relative(relative)
        maximum = min(self.limits.max_file_bytes, self.limits.max_metadata_bytes) if metadata else self.limits.max_file_bytes
        record, raw = _read_file(self.root, relative, maximum, metadata)
        previous = self.records.get(relative)
        if previous is not None:
            if previous != record:
                raise ValueError('artifact changed within verification')
        else:
            if len(self.records) >= self.limits.max_files or self.total+record.byte_length > self.limits.max_aggregate_bytes:
                raise ValueError('aggregate artifact closure limit exceeded')
            self.records[relative] = record
            self.total += record.byte_length
        return record, raw


def read_manifest(path: Path, limits: ArtifactLimits = ArtifactLimits()):
    """Read bounded strict canonical JSON; caller traverses its indirect closure."""
    path = _root(Path(path))
    _, raw = _read_file(path.parent, path.name, min(limits.max_file_bytes, limits.max_metadata_bytes), True)
    return _decode_json(raw, limits)


@dataclass(frozen=True)
class StateMetadata:
    logical_semantics_sha256: str
    H: int
    W: int
    original_input_sha256: str
    initial_output_sha256: str
    status: str = 'success'
    first_bad_index: int | None = None

    def __post_init__(self):
        for name in ('logical_semantics_sha256', 'original_input_sha256', 'initial_output_sha256'):
            _identity(getattr(self, name), name)
        _integer(self.H, 'H', 1)
        _integer(self.W, 'W', 1)
        if self.status not in ('success', 'input_precondition_failed'):
            raise ValueError('invalid status')
        if self.status == 'success':
            if self.first_bad_index is not None:
                raise ValueError('successful status requires null first_bad_index')
        else:
            _integer(self.first_bad_index, 'first_bad_index', maximum=(self.H+1)*(self.W+1)-1)

    @property
    def invocation_sha256(self):
        return hashlib.sha256(canonical_json(dict(logical_semantics_sha256=self.logical_semantics_sha256,
            shape={'H': self.H, 'W': self.W}, original_input_sha256=self.original_input_sha256,
            initial_output_sha256=self.initial_output_sha256))).hexdigest()

    def to_record(self):
        return dict(logical_semantics_sha256=self.logical_semantics_sha256,
            invocation_sha256=self.invocation_sha256, shape={'H': self.H, 'W': self.W},
            original_input_sha256=self.original_input_sha256, initial_output_sha256=self.initial_output_sha256,
            status=self.status, first_bad_index=self.first_bad_index)


def _metadata(record):
    _keys(record, ('logical_semantics_sha256', 'invocation_sha256', 'shape', 'original_input_sha256',
                   'initial_output_sha256', 'status', 'first_bad_index'), 'state metadata')
    _keys(record['shape'], ('H', 'W'), 'shape')
    result = StateMetadata(logical_semantics_sha256=record['logical_semantics_sha256'],
        H=record['shape']['H'], W=record['shape']['W'], original_input_sha256=record['original_input_sha256'],
        initial_output_sha256=record['initial_output_sha256'], status=record['status'], first_bad_index=record['first_bad_index'])
    if record['invocation_sha256'] != result.invocation_sha256:
        raise ValueError('semantic invocation identity mismatch')
    return result


def _counts(metadata, limits):
    counts = ((metadata.H+1)*(metadata.W+1), metadata.H*metadata.W)
    if 4*sum(counts) > limits.max_logical_bytes:
        raise ValueError('expanded logical state byte limit exceeded')
    return dict(zip(_ROLES, counts))


@dataclass(frozen=True)
class StateChunk:
    role: str
    offset: int
    byte_length: int
    sha256: str
    path: str


@dataclass(frozen=True)
class VerifiedState:
    root: Path
    manifest_path: Path
    manifest_sha256: str
    metadata: StateMetadata
    chunks: tuple[StateChunk, ...]
    closure: tuple[ClosureFile, ...]
    logical_bytes: int
    limits: ArtifactLimits

    def revalidate(self):
        for previous in self.closure:
            record, _ = _read_file(self.root, previous.path, self.limits.max_file_bytes)
            if record != previous:
                raise ValueError('previously verified artifact changed')

    def iter_bytes(self, role: str) -> Iterator[bytes]:
        """Traverse all logical bytes, rechecking mutable paths on every traversal."""
        if role not in _ROLES:
            raise ValueError('unknown state role')
        self.revalidate()
        for chunk in self.chunks:
            if chunk.role == role:
                record, raw = _read_file(self.root, chunk.path, self.limits.chunk_bytes, True)
                if (record.sha256, record.byte_length) != (chunk.sha256, chunk.byte_length):
                    raise ValueError('state chunk changed since verification')
                yield raw

    def iter_scalars(self, role: str) -> Iterator[int]:
        for raw in self.iter_bytes(role):
            for (value,) in struct.iter_unpack('<i', raw):
                yield value


ValidatedState = VerifiedState


def verify_state(manifest: Path, limits: ArtifactLimits = ArtifactLimits(), *,
                 sidecars: Iterable[str] = (), closure_paths: Iterable[str] = ()) -> VerifiedState:
    manifest = _root(Path(manifest))
    budget = _Budget(manifest.parent, limits)
    manifest_record, raw = budget.add(manifest.name, metadata=True)
    data = _decode_json(raw, limits)
    _keys(data, ('schema', 'metadata', 'chunks'), 'state manifest')
    if data['schema'] != 'axiom-state-v1':
        raise ValueError('unknown state schema')
    metadata = _metadata(data['metadata'])
    counts = _counts(metadata, limits)
    if type(data['chunks']) is not list:
        raise ValueError('chunks must be a list')
    offsets, role_number, chunks = dict.fromkeys(_ROLES, 0), 0, []
    for item in data['chunks']:
        _keys(item, ('role', 'offset', 'byte_length', 'sha256', 'path'), 'chunk')
        role = item['role']
        if not isinstance(role, str) or role not in _ROLES:
            raise ValueError('unknown chunk role')
        next_role = _ROLES.index(role)
        if next_role < role_number or (next_role > role_number and offsets[_ROLES[role_number]] != 4*counts[_ROLES[role_number]]):
            raise ValueError('reordered or incomplete role coverage')
        role_number = next_role
        offset = _integer(item['offset'], 'offset')
        length = _integer(item['byte_length'], 'byte_length', 1, limits.chunk_bytes)
        if offset != offsets[role] or length % 4 or offset+length > counts[role]*4:
            raise ValueError('noncontiguous, overlapping or excessive chunk coverage')
        _identity(item['sha256'], 'chunk sha256')
        record, _ = budget.add(item['path'])
        if (record.sha256, record.byte_length) != (item['sha256'], length):
            raise ValueError('actual state bytes differ from chunk identity')
        offsets[role] += length
        chunks.append(StateChunk(**item))
    if any(offsets[role] != 4*counts[role] for role in _ROLES):
        raise ValueError('incomplete state role coverage')
    for relative in closure_paths:
        budget.add(relative)
    for relative in sidecars:
        _, acquisition_raw = budget.add(relative, metadata=True)
        _acquisition_record(_decode_json(acquisition_raw, limits), manifest_record.sha256, metadata.invocation_sha256, manifest.name)
    return VerifiedState(manifest.parent, manifest, manifest_record.sha256, metadata,
        tuple(chunks), tuple(budget.records.values()), 4*sum(counts.values()), limits)


@contextmanager
def _write_directory(path, *, create=False):
    """Pin each directory without following symlinks, including during mkdir."""
    descriptor = None
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptor = os.open(path.anchor, flags)
        for component in path.parts[1:]:
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(component, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    except OSError as exc:
        raise ValueError(f'cannot open safe artifact write directory: {path}') from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _write_immutable(root, relative, raw):
    relative = _relative(relative)
    target = root/relative
    with _write_directory(target.parent) as parent_descriptor:
        try:
            descriptor = os.open(target.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=parent_descriptor)
        except FileExistsError:
            _, existing = _read_file(root, relative, len(raw), True)
            if existing != raw:
                raise ValueError('immutable artifact path already has different bytes')
        else:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(raw)


def write_state(input_after: Iterable[int], output: Iterable[int], metadata: StateMetadata,
                directory: Path, *, limits: ArtifactLimits = ArtifactLimits()) -> Path:
    if not isinstance(metadata, StateMetadata):
        raise ValueError('metadata must be StateMetadata')
    counts = _counts(metadata, limits)
    # Reject impossible metadata envelopes before consuming potentially huge iterables.
    _decode_json(canonical_json(dict(schema='axiom-state-v1', metadata=metadata.to_record(), chunks=[])), limits)
    projected_chunks = sum((4*n+limits.chunk_bytes-1)//limits.chunk_bytes for n in counts.values())
    if projected_chunks > limits.max_metadata_items//11:
        raise ValueError('projected state metadata item limit exceeded')
    root = _root(Path(directory))
    with _write_directory(root/'chunks', create=True):
        pass
    chunks = []
    for role, values in zip(_ROLES, (input_after, output)):
        iterator, offset = iter(values), 0
        while offset < counts[role]*4:
            raw = bytearray()
            for _ in range(min(limits.chunk_bytes//4, counts[role]-offset//4)):
                try:
                    value = next(iterator)
                except StopIteration as exc:
                    raise ValueError(f'too few {role} scalars') from exc
                _integer(value, role+' i32', -(1 << 31), (1 << 31)-1)
                raw.extend(struct.pack('<i', value))
            digest = hashlib.sha256(raw).hexdigest()
            relative = f'chunks/{digest}.i32'
            _write_immutable(root, relative, raw)
            chunks.append(dict(role=role, offset=offset, byte_length=len(raw), sha256=digest, path=relative))
            offset += len(raw)
        sentinel = object()
        if next(iterator, sentinel) is not sentinel:
            raise ValueError(f'too many {role} scalars')
    raw = canonical_json(dict(schema='axiom-state-v1', metadata=metadata.to_record(), chunks=chunks))
    _decode_json(raw, limits)
    _write_immutable(root, 'state.json', raw)
    result = root/'state.json'
    verify_state(result, limits)
    return result


@dataclass(frozen=True)
class AcquisitionMetadata:
    run_sha256: str
    collector_sha256: str
    plan_sha256: str
    emitted_kernel_sha256: str
    binary_sha256: str
    mode: str
    started_utc: str
    completed_utc: str

    def __post_init__(self):
        for name in ('run_sha256', 'collector_sha256', 'plan_sha256', 'emitted_kernel_sha256', 'binary_sha256'):
            _identity(getattr(self, name), name)
        if self.mode not in ('synthetic', 'native_observed'):
            raise ValueError('invalid acquisition mode')
        times = []
        for name in ('started_utc', 'completed_utc'):
            value = getattr(self, name)
            try:
                if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z', value):
                    raise ValueError('timestamp must be UTC with Z suffix')
                times.append(datetime.fromisoformat(value[:-1]+'+00:00'))
            except (ValueError, TypeError) as exc:
                raise ValueError('invalid acquisition timestamp') from exc
        if times[1] < times[0]:
            raise ValueError('acquisition timestamps are reversed')


def _acquisition_record(record, manifest_sha256, invocation_sha256, manifest_name):
    _keys(record, ('schema', 'state_manifest', 'state_manifest_sha256', 'invocation_sha256', 'acquisition'), 'acquisition sidecar')
    if record['schema'] != 'axiom-acquisition-v1' or record['state_manifest'] != manifest_name or record['state_manifest_sha256'] != manifest_sha256 or record['invocation_sha256'] != invocation_sha256:
        raise ValueError('acquisition does not bind this complete state and invocation')
    _keys(record['acquisition'], AcquisitionMetadata.__dataclass_fields__, 'acquisition metadata')
    return AcquisitionMetadata(**record['acquisition'])


def write_acquisition(manifest: Path, acquisition: AcquisitionMetadata, *, name='acquisition.json',
                      limits: ArtifactLimits = ArtifactLimits()) -> Path:
    verified = verify_state(manifest, limits)
    raw = canonical_json(dict(schema='axiom-acquisition-v1', state_manifest=verified.manifest_path.name,
        state_manifest_sha256=verified.manifest_sha256, invocation_sha256=verified.metadata.invocation_sha256,
        acquisition=asdict(acquisition)))
    _decode_json(raw, limits)
    _write_immutable(verified.root, name, raw)
    verify_state(manifest, limits, sidecars=[name])
    return verified.root/name


def verify_acquisition(path: Path, state: VerifiedState) -> AcquisitionMetadata:
    state.revalidate()
    path = _root(Path(path))
    try:
        relative = path.relative_to(state.root).as_posix()
    except ValueError as exc:
        raise ValueError('acquisition path escapes state root') from exc
    verified = verify_state(state.manifest_path, state.limits, sidecars=[relative], closure_paths=[c.path for c in state.closure])
    if verified.manifest_sha256 != state.manifest_sha256:
        raise ValueError('state changed since verification')
    return _acquisition_record(read_manifest(path, state.limits), state.manifest_sha256,
        state.metadata.invocation_sha256, state.manifest_path.name)


@dataclass(frozen=True)
class StateComparison:
    equal: bool
    reason: str | None = None
    role: str | None = None
    index: int | None = None
    coordinate: tuple[int, int] | None = None
    left: int | None = None
    right: int | None = None


def compare_state(a: VerifiedState, b: VerifiedState) -> StateComparison:
    """Compare actual complete scalar bytes, rather than digest equality."""
    a.revalidate()
    b.revalidate()
    if a.metadata != b.metadata:
        return StateComparison(False, 'semantic metadata differs')
    for role in _ROLES:
        width = a.metadata.W + (role == 'input_after')
        for index, (left, right) in enumerate(zip(a.iter_scalars(role), b.iter_scalars(role), strict=True)):
            if left != right:
                return StateComparison(False, 'state bytes differ', role, index, divmod(index, width), left, right)
    return StateComparison(True)
