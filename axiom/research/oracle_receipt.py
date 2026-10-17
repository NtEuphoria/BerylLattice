"""Explicitly selected source-oracle policy and live independent-state authority.

Artifacts are claims. Only this process's issuer records grant authority, under
trusted loaded-code/OS/controller and stable-file assumptions. No child launcher
or receipt-controlled code is used. See protocol/source-oracle-v1.md.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
import hashlib
import os
from pathlib import Path
import shutil
import stat
import sys
import sysconfig
import threading
import time

from axiom import artifact_chunks_v2 as blobs
from axiom.invocation_v2 import VerifiedInvocation, verify_invocation
from axiom.source_profiles import SourceProfileV2, SourceLimitsV2, admit_source_v2
if __package__:
    from .source_oracle import OracleResult, OracleLimits, evaluate_source_state
    from .state_artifacts import ArtifactLimits, VerifiedState, verify_state, compare_state
else:
    from source_oracle import OracleResult, OracleLimits, evaluate_source_state
    from state_artifacts import ArtifactLimits, VerifiedState, verify_state, compare_state

canonical_json = blobs.canonical_json
_VERSIONS = dict(source_admission='axiom-source-v2', ast='original-source-ast-v1',
                 invocation='axiom-invocation-v2', state='axiom-state-v1', oracle='source-oracle-v1')
_IDENTITIES = ('source_sha256', 'family_semantics_sha256', 'specialization_semantics_sha256',
               'invocation_sha256', 'state_invocation_sha256')
_REPOSITORY_MODULES = ('axiom', 'axiom.model', 'axiom.frontend', 'axiom.source_profiles',
                       'axiom.invocation_v2', 'axiom.artifact_chunks_v2',
                       (__package__+'.' if __package__ else '')+'source_oracle',
                       (__package__+'.' if __package__ else '')+'state_artifacts', __name__)
_QUALIFICATIONS = {}
_ORACLES = {}
_SELECTING = False
_SELECTION_LOCK = threading.Lock()
_CLEANUP_DEBTS = {}


def _positive(value, name, maximum):
    return blobs._integer(value, name, 1, maximum)


def _text(value, name):
    if type(value) is not str or not 1 <= len(value) <= 4096 or '\x00' in value:
        raise ValueError('invalid '+name)
    return value


def _keys(value, names, name):
    blobs._keys(value, names, name)


def _digest(value):
    return blobs._identity(value, 'sha256')


def _artifact_limits(value):
    if type(value) is not ArtifactLimits:
        raise ValueError('expected exact ArtifactLimits')
    value.__post_init__()
    for name, ceiling in asdict(ArtifactLimits()).items():
        if getattr(value, name) > ceiling:
            raise ValueError('semantic ceilings may only tighten')


@dataclass(frozen=True, slots=True)
class OracleLiveRoot:
    name: str
    directory: Path

    def __post_init__(self):
        if type(self.name) is not str or self.name not in ('repository', 'python', 'system'):
            raise ValueError('unknown live-root name')
        if not isinstance(self.directory, Path) or not self.directory.is_absolute():
            raise ValueError('live root must be absolute Path')
        with blobs._directory(self.directory):
            pass


@dataclass(frozen=True, slots=True)
class OracleQualificationLimits:
    max_qualification_bytes: int = 536_870_912
    max_file_bytes: int = 16_777_216
    chunk_bytes: int = 1_048_576
    max_files: int = 16_384
    max_metadata_bytes: int = 1_048_576
    max_metadata_depth: int = 16
    max_metadata_items: int = 65_536
    semantic_limits: ArtifactLimits = field(default_factory=ArtifactLimits)
    max_operation_temporary_bytes: int = 268_435_456
    max_live_qualifications: int = 1
    max_live_oracles: int = 16

    def __post_init__(self):
        for name, maximum in (
            ('max_qualification_bytes', 536_870_912), ('max_file_bytes', 16_777_216),
            ('chunk_bytes', 1_048_576), ('max_files', 16_384),
            ('max_metadata_bytes', 1_048_576), ('max_metadata_depth', 16),
            ('max_metadata_items', 65_536), ('max_operation_temporary_bytes', 268_435_456),
            ('max_live_qualifications', 1), ('max_live_oracles', 16)):
            _positive(getattr(self, name), name, maximum)
        if self.chunk_bytes > self.max_file_bytes:
            raise ValueError('chunk exceeds file limit')
        _artifact_limits(self.semantic_limits)

    def _blob_limits(self):
        return blobs.BlobLimits(**{name: getattr(self, name) for name in
            ('chunk_bytes', 'max_file_bytes', 'max_files', 'max_metadata_bytes',
             'max_metadata_depth', 'max_metadata_items')})


class _Ledger:
    """Stat and reserve unique physical paths BEFORE reads, including metadata."""
    def __init__(self, limits, *, total=0, count=0):
        self.limits = limits
        self.maximum = getattr(limits, 'max_qualification_bytes',
                               getattr(limits, 'max_aggregate_bytes', 0))
        self.total, self.count = total, count
        self.sizes, self.pins = {}, {}

    def reserve(self, path, *, metadata=False, length=None):
        path = blobs._absolute(path)
        with blobs._file(path.parent, path.name) as fd:
            info = os.fstat(fd)
        maximum = min(self.limits.max_file_bytes, self.limits.max_metadata_bytes) if metadata else self.limits.max_file_bytes
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise ValueError('not a bounded regular closure file')
        if length is not None and info.st_size != length:
            raise ValueError('declared file length differs')
        if path in self.sizes:
            if self.sizes[path] != info.st_size:
                raise ValueError('closure file changed')
        else:
            if self.total+info.st_size > self.maximum or self.count+1 > self.limits.max_files:
                raise ValueError('aggregate closure quota exceeded before read')
            self.sizes[path] = info.st_size
            self.total += info.st_size
            self.count += 1
        return path

    def read(self, path, *, metadata=False, length=None, digest=None):
        path = self.reserve(path, metadata=metadata, length=length)
        raw, _ = blobs._read_file(path.parent, path.name, self.sizes[path])
        pin = (len(raw), hashlib.sha256(raw).hexdigest())
        if (digest is not None and pin[1] != digest) or (path in self.pins and self.pins[path] != pin):
            raise ValueError('closure identity changed')
        self.pins[path] = pin
        return blobs._decode_json(raw, self.limits) if metadata else raw

    def document(self, root, ref):
        _keys(ref, ('path', 'sha256', 'byte_length'), 'document reference')
        path = root/blobs._relative(ref['path'])
        _digest(ref['sha256'])
        blobs._integer(ref['byte_length'], 'document length')
        return self.read(path, metadata=True, length=ref['byte_length'], digest=ref['sha256'])

    def blob(self, root, ref):
        _keys(ref, ('path', 'manifest_sha256', 'sha256', 'byte_length'), 'blob reference')
        path = root/blobs._relative(ref['path'])
        reference = blobs.BlobReference(manifest_path=path, manifest_sha256=ref['manifest_sha256'], sha256=ref['sha256'], byte_length=ref['byte_length'])
        data = self.read(path, metadata=True, digest=reference.manifest_sha256)
        _keys(data, ('schema', 'sha256', 'byte_length', 'chunks'), 'blob manifest')
        blobs._integer(data['byte_length'], 'blob length')
        _digest(data['sha256'])
        if data['schema'] != 'axiom-blob-v2' or (data['sha256'], data['byte_length']) != (reference.sha256, reference.byte_length):
            raise ValueError('blob reference differs')
        if type(data['chunks']) is not list:
            raise ValueError('invalid blob chunks')
        offset, paths = 0, set()
        for item in data['chunks']:
            _keys(item, ('path', 'sha256', 'offset', 'byte_length'), 'blob chunk')
            relative = blobs._relative(item['path'])
            _digest(item['sha256'])
            blobs._integer(item['offset'], 'chunk offset')
            _positive(item['byte_length'], 'chunk length', self.limits.chunk_bytes)
            if item['offset'] != offset or relative in paths or relative == path.name:
                raise ValueError('invalid blob coverage')
            offset += item['byte_length']
            paths.add(relative)
            self.reserve(path.parent/relative, length=item['byte_length'])
        if offset != reference.byte_length:
            raise ValueError('incomplete blob')
        return reference, data['chunks']

    def verify_blob(self, reference, chunks):
        digest = hashlib.sha256()
        for item in chunks:
            digest.update(self.read(reference.manifest_path.parent/item['path'],
                length=item['byte_length'], digest=item['sha256']))
        if digest.hexdigest() != reference.sha256:
            raise ValueError('complete blob content differs')


def _logical(value, roots):
    parts = blobs._relative(value).split('/')
    if len(parts) < 2 or parts[0] not in roots:
        raise ValueError('unknown logical live root')
    return roots[parts[0]]/('/'.join(parts[1:]))


def _tree_files(directory):
    """Descriptor-relative complete regular-file traversal, excluding site trees."""
    result = set()
    def walk(fd, path):
        with os.scandir(fd) as entries:
            for entry in entries:
                if entry.name in ('site-packages', 'dist-packages'):
                    continue
                info = entry.stat(follow_symlinks=False)
                child = path/entry.name
                if stat.S_ISDIR(info.st_mode):
                    sub = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    try:
                        walk(sub, child)
                    finally:
                        os.close(sub)
                elif stat.S_ISREG(info.st_mode):
                    if len(result) >= 16_384:
                        raise ValueError('runtime inventory file ceiling exceeded')
                    result.add(child)
                else:
                    raise ValueError('unapproved nonregular standard-library entry: '+str(child))
    with blobs._directory(directory) as fd:
        walk(fd, directory)
    return result


def _mapped_libraries():
    if sys.platform != 'linux':
        raise ValueError('runtime mapping qualification requires Linux')
    result = set()
    with open('/proc/self/maps', 'r', encoding='utf-8') as stream:
        for line in stream:
            parts = line.rstrip('\n').split(None, 5)
            if len(parts) < 5:
                raise ValueError('unclassifiable Linux mapping')
            if 'x' not in parts[1]:
                continue
            if len(parts) != 6:
                raise ValueError('unclassified anonymous executable mapping')
            name = parts[5]
            if name in ('[vdso]', '[vsyscall]'):
                continue
            if not name.startswith('/') or name.endswith(' (deleted)') or '\\' in name:
                raise ValueError('unclassifiable executable-file mapping')
            path = Path(name).resolve(strict=True)
            with blobs._file(path.parent, path.name) as fd:
                info = os.fstat(fd)
            # Linux maps dev/inode bind the actual mapped file, not a new lookup.
            major, minor = (int(x, 16) for x in parts[3].split(':'))
            if (os.major(info.st_dev), os.minor(info.st_dev), info.st_ino) != (major, minor, int(parts[4])):
                raise ValueError('mapped executable-file identity differs')
            result.add(path)
    return result


def _runtime_paths():
    """Actual required paths/roles; also useful for external inventory preparation."""
    if not sys.dont_write_bytecode:
        raise ValueError('disable bytecode writes before runtime inventory')
    executable = Path(sys.executable).resolve(strict=True)
    stdlib = Path(sysconfig.get_path('stdlib')).resolve(strict=True)
    paths = {path: 'stdlib' for path in _tree_files(stdlib)}
    paths[executable] = 'python_executable'
    for path in _mapped_libraries():
        paths.setdefault(path, 'runtime_library')
    for name in _REPOSITORY_MODULES:
        module = sys.modules.get(name)
        origin = getattr(getattr(module, '__spec__', None), 'origin', None)
        if not origin or origin in ('built-in', 'frozen'):
            raise ValueError('missing implementation origin: '+name)
        path = blobs._absolute(origin)
        with blobs._file(path.parent, path.name):
            pass
        paths[path] = 'implementation'
        cached = getattr(module, '__cached__', None)
        if cached is not None and os.path.lexists(cached):
            paths[blobs._absolute(cached)] = 'implementation'
    # Loaded stdlib origins must belong to the complete selected stdlib tree;
    # unexpected site imports cannot stand in for a standard-library dependency.
    for name, module in tuple(sys.modules.items()):
        if name.split('.')[0] not in sys.stdlib_module_names:
            continue
        origin = getattr(getattr(module, '__spec__', None), 'origin', None)
        if origin in (None, 'built-in', 'frozen'):
            continue
        path = blobs._absolute(origin)
        if path not in paths:
            raise ValueError('unselected loaded standard-library origin: '+name)
        cached = getattr(module, '__cached__', None)
        if cached and os.path.lexists(cached) and blobs._absolute(cached) not in paths:
            raise ValueError('unselected loaded bytecode')
    return paths


def _hash_live(path, expected_length):
    with blobs._file(path.parent, path.name) as fd:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size != expected_length:
            raise ValueError('live inventory length differs')
        digest, size = hashlib.sha256(), 0
        while True:
            block = os.read(fd, 65_536)
            if not block:
                break
            size += len(block)
            if size > expected_length:
                raise ValueError('live file grew')
            digest.update(block)
        after = os.fstat(fd)
        if blobs._stamp(before) != blobs._stamp(after) or size != expected_length:
            raise ValueError('live file changed')
        return digest.hexdigest()


def _inventory(data, root, roots, ledger, roles):
    if type(data) is not list or not data:
        raise ValueError('inventory must be nonempty list')
    last, result, retained = '', {}, set()
    for item in data:
        _keys(item, ('role', 'logical_path', 'blob'), 'inventory entry')
        if type(item['role']) is not str or item['role'] not in roles:
            raise ValueError('unknown inventory role')
        logical = item['logical_path']
        path = _logical(logical, roots)
        _keys(item['blob'], ('path', 'manifest_sha256', 'sha256', 'byte_length'), 'inventory blob')
        if logical <= last or path in result or item['blob']['path'] in retained:
            raise ValueError('duplicate or unordered inventory')
        last = logical
        retained.add(item['blob']['path'])
        result[path] = (item['role'], *ledger.blob(root, item['blob']))
    return result


def _qualification_data(manifest, approved, roots, limits):
    ledger = _Ledger(limits)
    approval = ledger.read(manifest, metadata=True, digest=approved)
    _keys(approval, ('schema', 'qualification', 'test_evidence', 'review'), 'approval')
    if approval['schema'] != 'axiom-oracle-approval-v1':
        raise ValueError('unknown approval schema')
    root = manifest.parent
    subject = ledger.document(root, approval['qualification'])
    _keys(subject, ('schema', 'entrypoint', 'runtime_assumption', 'source_profile', 'versions',
                    'python', 'inventory', 'trusted_base'), 'qualification')
    if (subject['schema'] != 'axiom-oracle-qualification-v1' or
        subject['entrypoint'] != 'source_oracle.evaluate_source_state' or
        subject['runtime_assumption'] != 'trusted-fresh-python-in-process-v1' or
        canonical_json(subject['source_profile']) != canonical_json(asdict(SourceProfileV2())) or subject['versions'] != _VERSIONS):
        raise ValueError('unrecognized qualification policy')
    py = subject['python']
    _keys(py, ('implementation', 'version', 'executable_logical_path'), 'python runtime')
    if (py['implementation'] != 'cpython' or sys.implementation.name != 'cpython' or
        type(py['version']) is not list or any(type(n) is not int for n in py['version']) or
        py['version'] != list(sys.version_info[:3])):
        raise ValueError('Python runtime differs')
    executable = _logical(py['executable_logical_path'], roots)
    if executable != Path(sys.executable).resolve(strict=True):
        raise ValueError('actual Python executable differs')
    inventory = _inventory(subject['inventory'], root, roots, ledger,
                            ('implementation', 'python_executable', 'stdlib', 'runtime_library'))
    required = _runtime_paths()
    if {p: v[0] for p, v in inventory.items()} != required:
        raise ValueError('inventory omits or substitutes actual runtime/implementation paths')
    if sum(v[0] == 'python_executable' for v in inventory.values()) != 1 or inventory[executable][0] != 'python_executable':
        raise ValueError('require exactly one actual executable')
    trusted = ledger.document(root, subject['trusted_base'])
    _keys(trusted, ('schema', 'assumptions'), 'trusted base')
    if trusted['schema'] != 'axiom-oracle-trusted-base-v1' or type(trusted['assumptions']) is not list or not trusted['assumptions']:
        raise ValueError('invalid trusted base')
    for item in trusted['assumptions']:
        _text(item, 'assumption')
    evidence = ledger.document(root, approval['test_evidence'])
    _keys(evidence, ('schema', 'qualification_sha256', 'inputs', 'runs'), 'test evidence')
    subject_hash = approval['qualification']['sha256']
    if evidence['schema'] != 'axiom-oracle-tests-v1' or evidence['qualification_sha256'] != subject_hash:
        raise ValueError('tests do not bind qualification')
    inputs = _inventory(evidence['inputs'], root, roots, ledger,
                         ('test_source', 'test_comparator', 'fixture', 'protocol'))
    if type(evidence['runs']) is not list:
        raise ValueError('invalid test runs')
    seen, logs = set(), []
    for run in evidence['runs']:
        _keys(run, ('command_id', 'argv', 'mode', 'tests', 'passed', 'failed', 'errors', 'skipped', 'exit_code', 'log'), 'test run')
        _text(run['command_id'], 'command id')
        if run['mode'] not in ('normal', 'optimized') or (run['command_id'], run['mode']) in seen:
            raise ValueError('invalid or duplicate test mode')
        seen.add((run['command_id'], run['mode']))
        if type(run['argv']) is not list or not run['argv']:
            raise ValueError('invalid descriptive argv')
        for arg in run['argv']:
            _text(arg, 'argv item')
        for name in ('tests', 'passed', 'failed', 'errors', 'skipped', 'exit_code'):
            blobs._integer(run[name], name)
        if (run['tests'] != sum(run[k] for k in ('passed', 'failed', 'errors', 'skipped')) or
            run['passed'] == 0 or run['failed'] or run['errors'] or run['exit_code'] or
            (run['command_id'] == 'o3' and run['skipped'])):
            raise ValueError('test run not passing/executed')
        logs.append(ledger.blob(root, run['log']))
    if not {(c, m) for c in ('o3', 'source_oracle', 'synthetic_receipts') for m in ('normal', 'optimized')} <= seen:
        raise ValueError('required test runs absent')
    review = ledger.document(root, approval['review'])
    _keys(review, ('schema', 'qualification_sha256', 'test_evidence_sha256', 'reviewer',
                   'decision', 'unresolved_findings', 'record'), 'review')
    if (review['schema'] != 'axiom-oracle-review-v1' or review['qualification_sha256'] != subject_hash or
        review['test_evidence_sha256'] != approval['test_evidence']['sha256'] or
        review['decision'] != 'approved' or review['unresolved_findings'] != []):
        raise ValueError('review does not approve exact subject/evidence')
    _text(review['reviewer'], 'reviewer')
    logs.append(ledger.blob(root, review['record']))
    # All metadata/stat reservations precede ANY bulk retained payload reads.
    for _, reference, chunks in (*inventory.values(), *inputs.values()):
        ledger.verify_blob(reference, chunks)
    for reference, chunks in logs:
        ledger.verify_blob(reference, chunks)
    for path, (_, reference, _) in inventory.items():
        if _hash_live(path, reference.byte_length) != reference.sha256:
            raise ValueError('selected live bytes differ')
    return subject_hash, ledger.pins


@dataclass
class _QualificationRecord:
    handle: object
    manifest: Path
    approval: str
    qualification: str
    roots: dict
    limits: OracleQualificationLimits
    scratch: Path
    pins: dict
    active: bool = False
    lock: object = field(default_factory=threading.Lock)
    children: set = field(default_factory=set)
    leaked_bytes: int = 0
    leaked_files: int = 0
    debts: dict = field(default_factory=dict)


def _qualification(handle):
    record = _QUALIFICATIONS.get(id(handle))
    if type(handle) is not OracleQualification or record is None or record.handle is not handle:
        raise ValueError('qualification is not live issuer authority')
    return record


def _check_qualification(record):
    subject, pins = _qualification_data(record.manifest, record.approval, record.roots, record.limits)
    if subject != record.qualification or pins != record.pins:
        raise ValueError('qualification closure differs from original issuer pins')


@contextmanager
def _operation(record):
    if not record.lock.acquire(blocking=False):
        raise ValueError('qualification operation reentry forbidden')
    try:
        _qualification(record.handle)
        record.active = True
        yield
    finally:
        record.active = False
        record.lock.release()


class OracleQualification:
    __slots__ = ('_closed', '_cleanup')

    def __new__(cls):
        raise TypeError('qualifications are issued only by explicit selection')

    @property
    def qualification_sha256(self):
        return _qualification(self).qualification

    @property
    def approval_sha256(self):
        return _qualification(self).approval

    @property
    def limits(self):
        limits = _qualification(self).limits
        return replace(limits, semantic_limits=replace(limits.semantic_limits))

    def revalidate(self):
        record = _qualification(self)
        with _operation(record):
            _check_qualification(record)

    def close(self):
        if type(self) is OracleQualification and getattr(self, '_closed', False):
            _retry_cleanup(self)
            return
        record = _qualification(self)
        with _operation(record):
            retained_bytes, retained_files = _session_usage(record)
            # Block a new session even if cleanup fails after invalidation.
            _CLEANUP_DEBTS[record.scratch] = (retained_bytes, retained_files)
            del _QUALIFICATIONS[id(self)]
            self._closed = True
            self._cleanup = (record.scratch, *record.debts)
            for child in tuple(record.children):
                item = _ORACLES.pop(child)
                item.handle._closed = True
                item.handle._cleanup = ()
            record.children.clear()
            _retry_cleanup(self)

    def __enter__(self):
        self.revalidate()
        return self

    def __exit__(self, *args):
        self.close()


def _remove_owned(path):
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        if os.path.lexists(path):
            raise


def _create_directory(path):
    path = blobs._absolute(path)
    with blobs._directory(path.parent) as fd:
        os.mkdir(path.name, 0o700, dir_fd=fd)
    return path


def select_oracle_qualification(approval_manifest: Path, *, approved_root_sha256: str,
        live_roots: tuple[OracleLiveRoot, ...], scratch_directory: Path,
        limits: OracleQualificationLimits = OracleQualificationLimits()) -> OracleQualification:
    global _SELECTING
    if type(limits) is not OracleQualificationLimits:
        raise ValueError('expected qualification limits')
    limits.__post_init__()
    limits = replace(limits, semantic_limits=replace(limits.semantic_limits))
    _digest(approved_root_sha256)
    if _SELECTING or _CLEANUP_DEBTS or len(_QUALIFICATIONS) >= limits.max_live_qualifications:
        raise ValueError('live qualification capacity/reentry exceeded')
    if type(live_roots) is not tuple or not live_roots:
        raise ValueError('expected explicit live roots')
    roots = {}
    for root in live_roots:
        if type(root) is not OracleLiveRoot:
            raise ValueError('expected exact live root')
        root.__post_init__()
        if root.name in roots or root.directory in roots.values():
            raise ValueError('duplicate live root')
        roots[root.name] = root.directory
    manifest = blobs._absolute(approval_manifest)
    if not _SELECTION_LOCK.acquire(blocking=False):
        raise ValueError('qualification selection reentry forbidden')
    _SELECTING = True
    try:
        if _QUALIFICATIONS or _CLEANUP_DEBTS:
            raise ValueError('live qualification capacity/cleanup debt exceeded')
        subject, pins = _qualification_data(manifest, approved_root_sha256, roots, limits)
        scratch = _create_directory(scratch_directory)
        try:
            handle = object.__new__(OracleQualification)
            handle._closed = False
            handle._cleanup = ()
            record = _QualificationRecord(handle, manifest, approved_root_sha256, subject,
                                           roots, limits, scratch, pins)
            _QUALIFICATIONS[id(handle)] = record
            return handle
        except BaseException:
            _remove_owned(scratch)
            raise
    finally:
        _SELECTING = False
        _SELECTION_LOCK.release()


@dataclass(frozen=True, slots=True)
class OracleReceipt:
    manifest_path: Path
    manifest_sha256: str


def _shape(height, width):
    _positive(height, 'H', 8192)
    _positive(width, 'W', 8192)
    if (height+1)*(width+1) > 8_388_608:
        raise ValueError('shape exceeds source envelope')


def _state_precharge(manifest, ledger):
    """Enumerate closed state-v1 references before the existing bulk verifier."""
    manifest = blobs._absolute(manifest)
    data = ledger.read(manifest, metadata=True)
    _keys(data, ('schema', 'metadata', 'chunks'), 'state manifest')
    if data['schema'] != 'axiom-state-v1' or type(data['chunks']) is not list:
        raise ValueError('unknown state manifest')
    metadata = data['metadata']
    _keys(metadata, ('logical_semantics_sha256', 'invocation_sha256', 'shape',
                    'original_input_sha256', 'initial_output_sha256', 'status', 'first_bad_index'), 'state metadata')
    _keys(metadata['shape'], ('H', 'W'), 'shape')
    _shape(metadata['shape']['H'], metadata['shape']['W'])
    for item in data['chunks']:
        _keys(item, ('role', 'offset', 'byte_length', 'sha256', 'path'), 'state chunk')
        _positive(item['byte_length'], 'state chunk length', ledger.limits.chunk_bytes)
        _digest(item['sha256'])
        path = manifest.parent/blobs._relative(item['path'])
        if path == manifest:
            raise ValueError('state manifest cannot be its own payload')
        ledger.reserve(path, length=item['byte_length'])
    return data


def _state_checked(manifest, ledger):
    _state_precharge(manifest, ledger)
    result = verify_state(manifest, ledger.limits)
    for item in result.closure:
        if ledger.sizes.get(item.resolved_path) != item.byte_length:
            raise ValueError('state closure differs from preflight')
        pin = (item.byte_length, item.sha256)
        if item.resolved_path in ledger.pins and ledger.pins[item.resolved_path] != pin:
            raise ValueError('state changed since precharge')
        ledger.pins[item.resolved_path] = pin
    return result


def _session_usage(record):
    count, total = record.leaked_files, record.leaked_bytes
    for key in record.children:
        child = _ORACLES[key]
        count += child.anchor_files
        total += child.anchor_bytes
    return total, count


def _semantic_ledger(record):
    ledger = _Ledger(record.limits.semantic_limits, total=record.leaked_bytes, count=record.leaked_files)
    for key in record.children:
        for path, (length, _) in _ORACLES[key].anchor_pins.items():
            ledger.reserve(path, length=length)
    return ledger


def _project(ledger, byte_count, file_count):
    if ledger.total+byte_count > ledger.maximum or ledger.count+file_count > ledger.limits.max_files:
        raise ValueError('combined semantic reservation exceeds quota')


def _receipt_value(result, selected, state, state_path):
    metadata = state.metadata
    if (metadata.logical_semantics_sha256 != result.specialization_semantics_sha256 or
        metadata.invocation_sha256 != result.state_invocation_sha256 or
        metadata.status != result.status or metadata.first_bad_index != result.first_bad_index):
        raise ValueError('result claim differs from complete state metadata')
    manifest = next(c for c in state.closure if c.resolved_path == state.manifest_path)
    return dict(schema='axiom-source-oracle-receipt-v1',
        qualification_sha256=selected.qualification, approval_sha256=selected.approval,
        **{name: getattr(result, name) for name in _IDENTITIES},
        source_profile=asdict(SourceProfileV2()), H=metadata.H, W=metadata.W,
        status=metadata.status, first_bad_index=metadata.first_bad_index,
        expected_state=dict(path=state_path, sha256=manifest.sha256, byte_length=manifest.byte_length))


def _copy_file(source, destination, length):
    # Exclusive descriptor-relative writes; never hardlink mutable caller files.
    with blobs._directory(destination.parent, create=True) as parent:
        fd = os.open(destination.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=parent)
        try:
            with blobs._file(source.parent, source.name) as original:
                before = os.fstat(original)
                if not stat.S_ISREG(before.st_mode) or before.st_size != length:
                    raise ValueError('copy source changed')
                count = 0
                while block := os.read(original, 65_536):
                    count += len(block)
                    if count > length:
                        raise ValueError('copy source grew')
                    view = memoryview(block)
                    while view:
                        written = os.write(fd, view)
                        if written <= 0:
                            raise OSError('short copy write')
                        view = view[written:]
                if count != length or blobs._stamp(before) != blobs._stamp(os.fstat(original)):
                    raise ValueError('copy source changed')
        finally:
            os.close(fd)


def _cleanup_failed(record, path, reserved_bytes, reserved_files):
    try:
        _remove_owned(path)
    except BaseException:
        # Keep conservative reservation if the filesystem did not remove payload.
        if path not in record.debts:
            record.leaked_bytes += reserved_bytes
            record.leaked_files += reserved_files
            record.debts[path] = (reserved_bytes, reserved_files)
        _CLEANUP_DEBTS[path] = (reserved_bytes, reserved_files)
        raise


def produce_oracle_receipt(result: OracleResult, qualification: OracleQualification,
                           destination: Path) -> OracleReceipt:
    selected = _qualification(qualification)
    with _operation(selected):
        _check_qualification(selected)
        if type(result) is not OracleResult:
            raise ValueError('expected exact OracleResult claim')
        OracleResult.__post_init__(result)
        if result.status not in ('success', 'input_precondition_failed'):
            raise ValueError('incomplete oracle result has no expected receipt')
        ledger = _semantic_ledger(selected)
        state = _state_checked(result.state_manifest, ledger)
        value = _receipt_value(result, selected, state, 'state/'+state.manifest_path.name)
        raw = canonical_json(value)
        blobs._decode_json(raw, selected.limits.semantic_limits)
        sizes = sum(c.byte_length for c in state.closure)
        files = len(state.closure)
        # Source is a retained claim; the producer's owned copy plus receipt is
        # the new semantic closure. Precharge source itself before bulk parsing.
        existing_bytes, existing_files = _session_usage(selected)
        projected = _Ledger(selected.limits.semantic_limits, total=existing_bytes, count=existing_files)
        _project(projected, sizes+len(raw), files+1)
        if (len(raw) > selected.limits.semantic_limits.max_file_bytes or
            sizes+len(raw) > selected.limits.max_operation_temporary_bytes):
            raise ValueError('candidate copy temporary/file quota exceeded')
        destination = _create_directory(destination)
        try:
            pending = _create_directory(destination/'.pending')
            for member in state.closure:
                _copy_file(member.resolved_path, pending/'state'/member.path, member.byte_length)
            blobs._write_immutable(pending, 'receipt.json', raw)
            fresh_ledger = _Ledger(selected.limits.semantic_limits)
            copied = _state_checked(pending/'state'/state.manifest_path.name, fresh_ledger)
            if copied.manifest_sha256 != state.manifest_sha256:
                raise ValueError('copied state identity differs')
            final_ledger = _semantic_ledger(selected)
            original = _state_checked(result.state_manifest, final_ledger)
            if original.manifest_sha256 != state.manifest_sha256 or final_ledger.pins != ledger.pins:
                raise ValueError('original complete state changed')
            _check_qualification(selected)
            answer = OracleReceipt(destination/'completed/receipt.json', hashlib.sha256(raw).hexdigest())
            with blobs._directory(destination) as fd:
                os.rename('.pending', 'completed', src_dir_fd=fd, dst_dir_fd=fd)
            return answer
        except BaseException:
            _cleanup_failed(selected, destination, sizes+len(raw), files+1)
            raise


def _read_receipt(path, ledger, selected):
    data = ledger.read(path, metadata=True)
    _keys(data, ('schema', 'qualification_sha256', 'approval_sha256', *_IDENTITIES,
                'source_profile', 'H', 'W', 'status', 'first_bad_index', 'expected_state'), 'oracle receipt')
    if (data['schema'] != 'axiom-source-oracle-receipt-v1' or
        data['qualification_sha256'] != selected.qualification or data['approval_sha256'] != selected.approval or
        canonical_json(data['source_profile']) != canonical_json(asdict(SourceProfileV2()))):
        raise ValueError('receipt policy differs from explicit selection')
    for name in _IDENTITIES:
        _digest(data[name])
    _shape(data['H'], data['W'])
    if data['status'] == 'success':
        if data['first_bad_index'] is not None:
            raise ValueError('successful receipt has bad index')
    elif data['status'] == 'input_precondition_failed':
        blobs._integer(data['first_bad_index'], 'first bad index', 0, (data['H']+1)*(data['W']+1)-1)
    else:
        raise ValueError('only completed source outcomes can be verified')
    ref = data['expected_state']
    _keys(ref, ('path', 'sha256', 'byte_length'), 'expected-state reference')
    blobs._relative(ref['path'])
    _digest(ref['sha256'])
    blobs._integer(ref['byte_length'], 'expected-state length')
    return data


def _candidate(path, data, ledger):
    ref = data['expected_state']
    manifest = path.parent/ref['path']
    ledger.reserve(manifest, metadata=True, length=ref['byte_length'])
    state = _state_checked(manifest, ledger)
    meta = state.metadata
    if (state.manifest_sha256 != ref['sha256'] or
        (meta.H, meta.W, meta.logical_semantics_sha256, meta.invocation_sha256, meta.status, meta.first_bad_index) !=
        (data['H'], data['W'], data['specialization_semantics_sha256'], data['state_invocation_sha256'],
         data['status'], data['first_bad_index'])):
        raise ValueError('candidate complete state differs from receipt claim')
    return state


def _poll(limits):
    if limits.cancelled is not None:
        answer = limits.cancelled()
        if type(answer) is not bool:
            raise TypeError('cancellation callable must return exact bool')
        if answer:
            raise ValueError('oracle verification cancelled')
    if limits.deadline_monotonic_ns is not None and time.monotonic_ns() >= limits.deadline_monotonic_ns:
        raise ValueError('oracle verification timeout')


def _fresh_invocation(invocation):
    if type(invocation) is not VerifiedInvocation:
        raise ValueError('expected exact VerifiedInvocation')
    invocation.revalidate()
    # Separate authoritative pins/limits from caller-created mutable record graphs.
    limits = replace(invocation.limits, blobs=replace(invocation.limits.blobs),
        source_profile=replace(invocation.limits.source_profile), source_limits=replace(invocation.limits.source_limits))
    return verify_invocation(invocation.manifest_path, limits=limits)


def _bind_invocation(data, source_bytes, invocation, limits):
    admitted = admit_source_v2(source_bytes, profile=SourceProfileV2(),
                               limits=SourceLimitsV2(source_bytes=limits.max_source_bytes))
    expected = dict(source_sha256=admitted.source_sha256,
        family_semantics_sha256=admitted.family_semantics_sha256,
        specialization_semantics_sha256=admitted.specialization_semantics_sha256,
        invocation_sha256=invocation.invocation_sha256,
        state_invocation_sha256=invocation.state_v1_invocation_sha256())
    if (invocation.source_bytes != source_bytes or invocation.source_profile != SourceProfileV2() or
        (data['H'], data['W']) != (admitted.height, admitted.width) or
        (invocation.H, invocation.W) != (admitted.height, admitted.width) or
        any(data[name] != value for name, value in expected.items()) or
        any(getattr(invocation, name) != expected[name] for name in _IDENTITIES[:3])):
        raise ValueError('exact source/specialization/invocation binding differs')


def _preserved_input(state, invocation):
    digest, length = hashlib.sha256(), 0
    for block in state.iter_bytes('input_after'):
        digest.update(block)
        length += len(block)
    if (digest.hexdigest(), length) != (invocation.input.sha256, invocation.input.byte_length):
        raise ValueError('independent state did not preserve full invocation input')
    if (state.metadata.original_input_sha256 != invocation.input.sha256 or
        state.metadata.initial_output_sha256 != invocation.initial_output.sha256):
        raise ValueError('independent state input/output identity differs')


@dataclass
class _OracleRecord:
    handle: object
    parent: OracleQualification
    receipt_path: Path
    receipt_pins: dict
    invocation: VerifiedInvocation
    source: bytes
    identities: tuple
    anchor_path: Path
    anchor_pins: dict
    anchor_limits: ArtifactLimits
    anchor_bytes: int
    anchor_files: int
    directory: Path


def _oracle(handle):
    record = _ORACLES.get(id(handle))
    if type(handle) is not VerifiedOracle or record is None or record.handle is not handle:
        raise ValueError('oracle is not live issuer authority')
    _qualification(record.parent)
    return record


def _anchor(record):
    ledger = _Ledger(replace(record.anchor_limits))
    state = _state_checked(record.anchor_path, ledger)
    if ledger.pins != record.anchor_pins:
        raise ValueError('independent anchor changed from original issuer pins')
    return state


class VerifiedOracle:
    __slots__ = ('_closed', '_cleanup')

    def __new__(cls):
        raise TypeError('verified oracles require fresh independent execution')

    @property
    def expected_state(self):
        record = _oracle(self)
        with _operation(_qualification(record.parent)):
            return _revalidate_oracle(record)

    @property
    def source_sha256(self):
        return _oracle(self).identities[0]

    @property
    def family_semantics_sha256(self):
        return _oracle(self).identities[1]

    @property
    def specialization_semantics_sha256(self):
        return _oracle(self).identities[2]

    @property
    def invocation_sha256(self):
        return _oracle(self).identities[3]

    @property
    def state_invocation_sha256(self):
        return _oracle(self).identities[4]

    @property
    def qualification_sha256(self):
        return _qualification(_oracle(self).parent).qualification

    @property
    def approval_sha256(self):
        return _qualification(_oracle(self).parent).approval

    def revalidate(self):
        record = _oracle(self)
        with _operation(_qualification(record.parent)):
            _revalidate_oracle(record)

    def close(self):
        if type(self) is VerifiedOracle and getattr(self, '_closed', False):
            _retry_cleanup(self)
            return
        record = _oracle(self)
        selected = _qualification(record.parent)
        with _operation(selected):
            del _ORACLES[id(self)]
            selected.children.remove(id(self))
            self._closed = True
            self._cleanup = (record.directory,)
            _cleanup_failed(selected, record.directory, record.anchor_bytes, record.anchor_files)
            self._cleanup = ()

    def __enter__(self):
        self.revalidate()
        return self

    def __exit__(self, *args):
        self.close()


def verify_oracle_receipt(receipt: Path, source_bytes: bytes, invocation: VerifiedInvocation,
        qualification: OracleQualification, *, limits: OracleLimits) -> VerifiedOracle:
    selected = _qualification(qualification)
    if type(limits) is not OracleLimits or type(source_bytes) is not bytes:
        raise ValueError('expected exact OracleLimits/source bytes')
    OracleLimits.__post_init__(limits)
    limits = replace(limits, state_limits=replace(limits.state_limits))
    with _operation(selected):
        _check_qualification(selected)
        if len(selected.children) >= selected.limits.max_live_oracles:
            raise ValueError('live oracle capacity exhausted')
        _poll(limits)
        path = blobs._absolute(receipt)
        ledger = _semantic_ledger(selected)
        data = _read_receipt(path, ledger, selected)
        fresh_invocation = _fresh_invocation(invocation)
        _bind_invocation(data, source_bytes, fresh_invocation, limits)
        state_limits = ArtifactLimits(**{name: min(getattr(limits.state_limits, name), value)
            for name, value in asdict(selected.limits.semantic_limits).items()})
        cells = (data['H']+1)*(data['W']+1)
        output_cells = data['H']*data['W']
        state_bytes = 4*(cells+output_cells)
        manifest_bytes = min(state_limits.max_metadata_bytes, state_limits.max_file_bytes)
        anchor_bytes = state_bytes+manifest_bytes
        anchor_files = 1+sum((4*n+state_limits.chunk_bytes-1)//state_limits.chunk_bytes for n in (cells, output_cells))
        _project(ledger, anchor_bytes, anchor_files)
        ledger.total += anchor_bytes
        ledger.count += anchor_files
        # Private receipt metadata is retained input; reserve its bounded raw
        # envelope as operation overhead in addition to O2 snapshot/state/manifest.
        private_bytes = ledger.sizes[path]
        temporary = min(limits.max_temporary_bytes, selected.limits.max_operation_temporary_bytes)
        if 4*cells+anchor_bytes+private_bytes > temporary:
            raise ValueError('combined operation temporary quota exceeded')
        candidate = _candidate(path, data, ledger)
        candidate_pins = dict(ledger.pins)
        # O2 keeps its exact pre-write metadata projection; O3 only reserves the
        # selected maximum manifest and never calls a private O2 helper.
        run_limits = replace(limits, state_limits=state_limits, max_temporary_bytes=temporary-private_bytes)
        directory = selected.scratch/('anchor-'+str(time.monotonic_ns()))
        if os.path.lexists(directory):
            raise ValueError('anchor destination already exists')
        try:
            result = evaluate_source_state(source_bytes, fresh_invocation, directory,
                profile=SourceProfileV2(), limits=run_limits)
            if type(result) is not OracleResult:
                raise ValueError('independent evaluator returned wrong result type')
            OracleResult.__post_init__(result)
            if result.status not in ('success', 'input_precondition_failed'):
                raise ValueError('independent execution incomplete: '+result.status)
            anchor_ledger = _Ledger(state_limits)
            anchor = _state_checked(result.state_manifest, anchor_ledger)
            if not anchor.manifest_path.is_relative_to(directory):
                raise ValueError('independent evaluator escaped owned destination')
            if anchor_ledger.total > anchor_bytes or anchor_ledger.count > anchor_files:
                raise ValueError('independent anchor exceeded reservation')
            if any(getattr(result, name) != data[name] for name in _IDENTITIES):
                raise ValueError('independent result identities differ')
            _preserved_input(anchor, fresh_invocation)
            if not compare_state(candidate, anchor).equal:
                raise ValueError('complete candidate state differs from independent source state')
            # Poll trusted controls BEFORE final rehashes: a callback may alter
            # artifacts, but cannot run again after those final checks.
            _poll(limits)
            # Fresh final parsing, not a caller-supplied VerifiedState closure.
            final_ledger = _semantic_ledger(selected)
            final_data = _read_receipt(path, final_ledger, selected)
            _candidate(path, final_data, final_ledger)
            if final_ledger.pins != candidate_pins:
                raise ValueError('candidate changed at final boundary')
            fresh_invocation.revalidate()
            check_anchor = _Ledger(state_limits)
            _state_checked(anchor.manifest_path, check_anchor)
            if check_anchor.pins != anchor_ledger.pins:
                raise ValueError('anchor changed at final boundary')
            _check_qualification(selected)
            handle = object.__new__(VerifiedOracle)
            handle._closed = False
            handle._cleanup = ()
            record = _OracleRecord(handle, qualification, path, candidate_pins, fresh_invocation,
                source_bytes, tuple(data[name] for name in _IDENTITIES), anchor.manifest_path,
                dict(anchor_ledger.pins), state_limits, anchor_ledger.total, anchor_ledger.count, directory)
            if limits.deadline_monotonic_ns is not None and time.monotonic_ns() >= limits.deadline_monotonic_ns:
                raise ValueError('oracle verification timeout')
            # Commit only after every fallible validation. Roll back partial table
            # insertion if allocation fails; no subsequent validation can fail.
            try:
                selected.children.add(id(handle))
                _ORACLES[id(handle)] = record
            except BaseException:
                selected.children.discard(id(handle))
                _ORACLES.pop(id(handle), None)
                raise
            return handle
        except BaseException:
            _cleanup_failed(selected, directory, anchor_bytes, anchor_files)
            raise


def _revalidate_oracle(record):
    selected = _qualification(record.parent)
    _check_qualification(selected)
    record.invocation.revalidate()
    if record.invocation.source_bytes != record.source:
        raise ValueError('original invocation source changed')
    ledger = _semantic_ledger(selected)
    data = _read_receipt(record.receipt_path, ledger, selected)
    _candidate(record.receipt_path, data, ledger)
    if ledger.pins != record.receipt_pins or tuple(data[n] for n in _IDENTITIES) != record.identities:
        raise ValueError('receipt differs from original issuer pins')
    return _anchor(record)


def _retry_cleanup(handle):
    while handle._cleanup:
        path = handle._cleanup[0]
        _remove_owned(path)
        # Successful removal ends ownership of this pathname. A later close
        # must not delete a new caller-created directory at the same name.
        handle._cleanup = handle._cleanup[1:]
        _CLEANUP_DEBTS.pop(path, None)
        for record in _QUALIFICATIONS.values():
            debt = record.debts.pop(path, None)
            if debt is not None:
                record.leaked_bytes -= debt[0]
                record.leaked_files -= debt[1]
