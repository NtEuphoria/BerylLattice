"""Exact, bounded replay receipts and manifest-last artifact publication.

Saved checks and attempt records are history. Only a fresh checker invocation
establishes eligibility. SHA-256 binds bytes; it is not a semantic proof.
"""
from contextlib import contextmanager
from dataclasses import dataclass, fields, is_dataclass
from enum import StrEnum
from hashlib import sha256
import os
from pathlib import Path
import re
import secrets
import stat

from .checker import CHECKER_VERSION, CHECK_ACCOUNTING_VERSION, CheckResult, check_plan
from .codec import DecodeError, canonical_json, decode_plan, encode_plan, strict_json_loads
from .frontend import admit_source, parse_source
from .model import ConstraintStatus, Limits, Objective, SemanticStatus, SourceModule, SEMANTICS_VERSION
from .selection import (ArtifactState, AttemptRecord, BUDGET_ACCOUNTING_VERSION,
                        SearchResult, SearchStop, ranking_digest)

MANIFEST_VERSION = 1
MANIFEST_BYTES = 262144
MAX_ATTEMPTS = 3
_MAX_INTEGER = 9999999999
_OPCODES = {'const', 'input_load', 'add', 'mul', 'scratch_store', 'scratch_load', 'output_store'}


class ReplayError(DecodeError):
    """Typed invalid/unsupported replay identity or manifest diagnostic."""


@dataclass(frozen=True, slots=True)
class ReplayManifest:
    schema_version: int
    source_digest: str
    source_file: str
    plan_digest: str | None
    plan_file: str | None
    semantic_digest: str
    constraint_digest: str
    ranking_digest: str
    semantics_version: str
    plan_version: int
    checker_version: str
    accounting_version: int
    budget_accounting_version: int
    original_effective_cap: int | None
    objective: Objective
    saved_check: CheckResult | None
    attempts: tuple[AttemptRecord, ...]
    termination_reason: SearchStop
    reason: str
    selected_key: tuple[int, int, str] | None
    total_check_steps: int
    total_work_used: int
    optional_check_steps: int | None
    optional_work_used: int
    artifact_state: ArtifactState
    limits: Limits


def json_record(value):
    """Convert immutable public records to JSON primitives without executing text."""
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value):
        return {f.name: json_record(getattr(value, f.name)) for f in fields(value)}
    if type(value) in (list, tuple):
        return [json_record(x) for x in value]
    if type(value) is dict:
        return {key: json_record(item) for key, item in value.items()}
    return value


def _fail(path, message, code='INVALID_MANIFEST'):
    raise ReplayError(code, path, message)


def _object(value, names, path):
    if type(value) is not dict or set(value) != set(names):
        _fail(path, 'missing or unknown fields')


def _integer(value, path, maximum=_MAX_INTEGER, nullable=False, minimum=0):
    if nullable and value is None:
        return
    if type(value) is not int or not minimum <= value <= maximum:
        _fail(path, f'expected exact integer in [{minimum},{maximum}]')


def _text(value, path, maximum=2048, minimum=1):
    if type(value) is not str:
        _fail(path, 'expected string')
    if len(value)>maximum:
        _fail(path, 'string size exceeds field quota')
    try:
        size = len(value.encode('utf-8'))
    except UnicodeError:
        _fail(path, 'expected Unicode scalar values')
    if not minimum <= size <= maximum:
        _fail(path, 'string size exceeds field quota')


def _digest(value, path, nullable=False):
    if nullable and value is None:
        return
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        _fail(path, 'expected lowercase SHA-256')


def _enum(kind, value, path):
    if type(value) is not str:
        _fail(path, 'expected enum string')
    try:
        return kind(value)
    except ValueError:
        _fail(path, 'unknown enum value')


def _cap_digest(cap):
    # Selection never has an additional cap. Replay computes its new context in
    # check_plan, retaining this original identity solely as historical context.
    return sha256(canonical_json({'version': 1, 'property': 'plan_workspace_bytes',
                                 'source_cap': cap, 'additional_cap': None,
                                 'effective_cap': cap})).hexdigest()


def _check(value, path):
    _object(value, (f.name for f in fields(CheckResult)), path)
    semantic = _enum(SemanticStatus, value['semantic_status'], path+'.semantic_status')
    constraint = _enum(ConstraintStatus, value['constraint_status'], path+'.constraint_status')
    if type(value['check_complete']) is not bool:
        _fail(path+'.check_complete', 'expected boolean')
    _text(value['reason'], path+'.reason')
    for name in ('workspace_bytes','multiplication_ops'):
        _integer(value[name], path+'.'+name, nullable=True)
    _integer(value['work_used'], path+'.work_used')
    _integer(value['effective_cap'], path+'.effective_cap', 2147483647, nullable=True)
    _digest(value['source_digest'], path+'.source_digest')
    _digest(value['plan_digest'], path+'.plan_digest', nullable=True)
    _digest(value['constraint_digest'], path+'.constraint_digest')
    _text(value['checker_version'], path+'.checker_version',256)
    witness = value['witness']
    if witness is not None:
        if type(witness) is not list or len(witness)>32:
            _fail(path+'.witness', 'expected up to 32 witness pairs')
        for pair in witness:
            if type(pair) is not list or len(pair)!=2:
                _fail(path+'.witness','expected key/value pair')
            _text(pair[0],path+'.witness.key',256)
            if type(pair[1]) is str:
                _text(pair[1],path+'.witness.value',2048,minimum=0)
            else:
                _integer(pair[1],path+'.witness.value',minimum=-_MAX_INTEGER)
        witness = tuple(tuple(pair) for pair in witness)
    counts = value['opcode_counts']
    if counts is not None:
        if type(counts) is not list or len(counts)>len(_OPCODES):
            _fail(path+'.opcode_counts','invalid opcode counts')
        seen=set()
        for pair in counts:
            if type(pair) is not list or len(pair)!=2 or type(pair[0]) is not str or pair[0] not in _OPCODES or pair[0] in seen:
                _fail(path+'.opcode_counts','invalid or duplicate opcode')
            seen.add(pair[0]); _integer(pair[1],path+'.opcode_counts.value')
        counts=tuple(tuple(pair) for pair in counts)
    return CheckResult(semantic,constraint,value['check_complete'],value['reason'],witness,
                       value['workspace_bytes'],value['multiplication_ops'],counts,value['work_used'],
                       value['source_digest'],value['plan_digest'],value['checker_version'],
                       value['effective_cap'],value['constraint_digest'])


def _attempt(value, path):
    _object(value,(f.name for f in fields(AttemptRecord)),path)
    _text(value['candidate_id'],path+'.candidate_id',256)
    _digest(value['plan_digest'],path+'.plan_digest',nullable=True)
    _digest(value['constraint_digest'],path+'.constraint_digest')
    for name in ('source_digest','semantic_digest','ranking_digest'):
        _digest(value[name],path+'.'+name)
    for name in ('allowance','work_used'):
        _integer(value[name],path+'.'+name)
    if value['work_used']>value['allowance']:
        _fail(path,'work exceeds allowance')
    _text(value['reason'],path+'.reason')
    check=None if value['check'] is None else _check(value['check'],path+'.check')
    return AttemptRecord(**dict(value,check=check))


def decode_manifest(data: bytes) -> ReplayManifest:
    """Decode a canonical, bounded v1 manifest; do not reuse its saved result."""
    try:
        obj=strict_json_loads(data,max_bytes=MANIFEST_BYTES,max_items=4096,max_depth=12)
    except DecodeError as error:
        raise ReplayError(error.code,error.field_path,str(error)) from error
    _object(obj,(f.name for f in fields(ReplayManifest)),'$')
    for name in ('schema_version','plan_version','accounting_version','budget_accounting_version'):
        _integer(obj[name],'$.'+name)
    for name,expected in (('schema_version',MANIFEST_VERSION),('plan_version',1),
                          ('accounting_version',CHECK_ACCOUNTING_VERSION),
                          ('budget_accounting_version',BUDGET_ACCOUNTING_VERSION)):
        if obj[name]!=expected:
            _fail('$.'+name,'unsupported version','UNSUPPORTED_REPLAY_VERSION')
    for name,expected in (('semantics_version',SEMANTICS_VERSION),('checker_version',CHECKER_VERSION)):
        _text(obj[name],'$.'+name,256)
        if obj[name]!=expected:
            _fail('$.'+name,'unsupported identity','UNSUPPORTED_REPLAY_VERSION')
    for name in ('source_digest','semantic_digest','constraint_digest','ranking_digest'):
        _digest(obj[name],'$.'+name)
    _digest(obj['plan_digest'],'$.plan_digest',nullable=True)
    for name in ('total_check_steps','total_work_used','optional_work_used'):
        _integer(obj[name],'$.'+name)
    _integer(obj['optional_check_steps'],'$.optional_check_steps',nullable=True)
    _integer(obj['original_effective_cap'],'$.original_effective_cap',2147483647,nullable=True)
    _text(obj['reason'],'$.reason')
    objective=_enum(Objective,obj['objective'],'$.objective')
    stop=_enum(SearchStop,obj['termination_reason'],'$.termination_reason')
    state=_enum(ArtifactState,obj['artifact_state'],'$.artifact_state')
    _object(obj['limits'],(f.name for f in fields(Limits)),'$.limits')
    for name,value in obj['limits'].items():
        _integer(value,'$.limits.'+name,minimum=1)
    limits=Limits(**obj['limits'])
    if type(obj['attempts']) is not list or len(obj['attempts'])>MAX_ATTEMPTS:
        _fail('$.attempts','expected up to three attempt records')
    attempts=tuple(_attempt(x,f'$.attempts[{i}]') for i,x in enumerate(obj['attempts']))
    saved=None if obj['saved_check'] is None else _check(obj['saved_check'],'$.saved_check')
    key=obj['selected_key']
    if key is not None:
        if type(key) is not list or len(key)!=3:
            _fail('$.selected_key','expected [primary, secondary, plan_id]')
        _integer(key[0],'$.selected_key[0]'); _integer(key[1],'$.selected_key[1]')
        _text(key[2],'$.selected_key[2]',256)
        key=tuple(key)
    expected_source='source-'+obj['source_digest']+'.ax'
    if obj['source_file']!=expected_source or type(obj['source_file']) is not str:
        _fail('$.source_file','source filename must match exact digest')
    expected_plan=None if obj['plan_digest'] is None else 'plan-'+obj['plan_digest']+'.json'
    if obj['plan_file']!=expected_plan:
        _fail('$.plan_file','plan filename must match exact digest')
    selected=(obj['plan_digest'],obj['plan_file'],saved,key)
    if state==ArtifactState.NONE:
        if any(x is not None for x in selected): _fail('$','no artifact requires null selection')
    elif any(x is None for x in selected):
        _fail('$','available artifact requires complete selection')
    if obj['constraint_digest']!=_cap_digest(obj['original_effective_cap']):
        _fail('$.constraint_digest','original constraint identity mismatch')
    if obj['ranking_digest']!=ranking_digest(objective):
        _fail('$.ranking_digest','ranking policy mismatch','UNSUPPORTED_RANKING_POLICY')
    if obj['total_work_used']!=sum(a.work_used for a in attempts) or obj['total_work_used']>obj['total_check_steps']:
        _fail('$.total_work_used','inconsistent total budget accounting')
    expected_optional=sum(a.work_used for a in attempts[1:])
    if obj['optional_work_used']!=expected_optional:
        _fail('$.optional_work_used','optional work must account for every attempt after the initial candidate')
    if obj['optional_work_used']>obj['total_work_used'] or (obj['optional_check_steps'] is not None and obj['optional_work_used']>obj['optional_check_steps']):
        _fail('$.optional_work_used','inconsistent optional budget accounting')
    for i,a in enumerate(attempts):
        if (a.source_digest!=obj['source_digest'] or a.semantic_digest!=obj['semantic_digest']
                or a.ranking_digest!=obj['ranking_digest']):
            _fail(f'$.attempts[{i}]','attempt identity mismatch')
        if a.constraint_digest!=obj['constraint_digest']:
            _fail(f'$.attempts[{i}].constraint_digest','constraint identity mismatch')
        if a.check is not None:
            _check_identity(a.check,obj,a.plan_digest,f'$.attempts[{i}].check')
            if a.work_used!=a.check.work_used or a.constraint_digest!=a.check.constraint_digest:
                _fail(f'$.attempts[{i}]','check accounting/constraint mismatch')
    if saved is not None:
        _check_identity(saved,obj,obj['plan_digest'],'$.saved_check')
    manifest=ReplayManifest(**dict(obj,objective=objective,termination_reason=stop,artifact_state=state,
                                  limits=limits,attempts=attempts,saved_check=saved,selected_key=key))
    if canonical_json(json_record(manifest))!=data:
        _fail('$','manifest must use canonical JSON encoding')
    return manifest


def _check_identity(check, obj, plan_digest, path):
    if (check.source_digest!=obj['source_digest'] or check.plan_digest!=plan_digest
            or check.constraint_digest!=obj['constraint_digest']
            or check.effective_cap!=obj['original_effective_cap']
            or check.checker_version!=obj['checker_version']):
        _fail(path,'saved check identity mismatch')


def encode_manifest(manifest: ReplayManifest) -> bytes:
    if type(manifest) is not ReplayManifest:
        raise ValueError('expected ReplayManifest')
    data=canonical_json(json_record(manifest))
    decode_manifest(data)
    return data


def replay(source: bytes, plan_bytes: bytes, manifest_bytes: bytes,
           limits: Limits, cap: int | None = None) -> CheckResult:
    """Re-admit exact bytes and freshly check one plan under an additional cap."""
    if type(limits) is not Limits:
        raise ValueError('expected Limits')
    _integer(cap,'$.cap',2147483647,nullable=True)
    manifest=decode_manifest(manifest_bytes)
    if type(source) is not bytes or len(source)>limits.source_bytes:
        _fail('$.source','source bytes exceed quota','SOURCE_LIMIT')
    if type(plan_bytes) is not bytes or len(plan_bytes)>limits.plan_bytes:
        _fail('$.plan','plan bytes exceed quota','BYTE_LIMIT')
    if sha256(source).hexdigest()!=manifest.source_digest:
        _fail('$.source_digest','exact source snapshot mismatch','REPLAY_IDENTITY_MISMATCH')
    if manifest.plan_digest is None:
        _fail('$.plan_digest','manifest has no eligible artifact','NO_REPLAY_ARTIFACT')
    if sha256(plan_bytes).hexdigest()!=manifest.plan_digest:
        _fail('$.plan_digest','exact plan bytes mismatch','REPLAY_IDENTITY_MISMATCH')
    kernel=admit_source(parse_source(source,limits))
    if (kernel.semantic_digest!=manifest.semantic_digest or kernel.cap!=manifest.original_effective_cap
            or kernel.objective!=manifest.objective):
        _fail('$','source admission does not match manifest','REPLAY_IDENTITY_MISMATCH')
    plan=decode_plan(plan_bytes,limits)
    # The checker identifies canonical physical-plan bytes. Exact replay must
    # retain that same representation so its fresh receipt binds the supplied
    # snapshot rather than a different canonicalization of it. General decoding
    # remains permissive outside this stricter replay boundary.
    if encode_plan(plan,limits=limits)!=plan_bytes:
        _fail('$.plan','exact replay requires canonical plan bytes','REPLAY_IDENTITY_MISMATCH')
    if plan.semantic_digest!=manifest.semantic_digest or plan.plan_id!=manifest.selected_key[2]:
        _fail('$.plan','plan identity mismatch','REPLAY_IDENTITY_MISMATCH')
    checked=check_plan(kernel,plan,limits,additional_cap=cap)
    if checked.multiplication_ops is not None and checked.workspace_bytes is not None:
        metrics=(checked.multiplication_ops,checked.workspace_bytes)
        if kernel.objective==Objective.PLAN_WORKSPACE_BYTES:
            metrics=metrics[::-1]
        if (*metrics,plan.plan_id)!=manifest.selected_key:
            _fail('$.selected_key','ranking key differs from fresh complete metrics','REPLAY_IDENTITY_MISMATCH')
    return checked


def _same_typed(a,b):
    if type(a) is not type(b): return False
    if is_dataclass(a): return all(_same_typed(getattr(a,f.name),getattr(b,f.name)) for f in fields(a))
    if type(a) is tuple: return len(a)==len(b) and all(_same_typed(x,y) for x,y in zip(a,b))
    return a==b



def _validate_public_check(check, path):
    """Bound nested direct-record containers before JSON serialization."""
    if (type(check) is not CheckResult or type(check.semantic_status) is not SemanticStatus
            or type(check.constraint_status) is not ConstraintStatus):
        _fail(path,'expected typed CheckResult')
    _text(check.reason,path+'.reason')
    _text(check.checker_version,path+'.checker_version',256)
    for name,maximum in (('witness',32),('opcode_counts',len(_OPCODES))):
        pairs=getattr(check,name)
        if pairs is None:
            continue
        if type(pairs) is not tuple or len(pairs)>maximum:
            _fail(path+'.'+name,'expected bounded immutable pairs')
        for pair in pairs:
            if type(pair) is not tuple or len(pair)!=2:
                _fail(path+'.'+name,'expected immutable key/value pair')
            _text(pair[0],path+'.'+name+'.key',256)
            if type(pair[1]) is str and name=='witness':
                _text(pair[1],path+'.witness.value',2048,minimum=0)
            else:
                _integer(pair[1],path+'.'+name+'.value',minimum=-_MAX_INTEGER if name=='witness' else 0)
    _check(json_record(check),path)


def _manifest(module, result):
    if type(module) is not SourceModule or type(result) is not SearchResult or type(result.limits) is not Limits:
        raise ValueError('expected SourceModule, SearchResult and Limits records')
    fresh_module=parse_source(module.source_bytes,result.limits)
    if not _same_typed(module,fresh_module):
        raise ValueError('module does not match its immutable source snapshot')
    kernel=admit_source(fresh_module)
    if type(result.objective) is not Objective or result.objective!=kernel.objective:
        raise ValueError('objective must match source')
    if (type(result.attempts) is not tuple or len(result.attempts)>MAX_ATTEMPTS
            or any(type(a) is not AttemptRecord for a in result.attempts)):
        raise ValueError('expected immutable attempt records')
    if type(result.termination_reason) is not SearchStop or type(result.artifact_state) is not ArtifactState:
        raise ValueError('expected typed search state')
    _text(result.reason,'$.reason')
    for name in ('total_check_steps','total_work_used','optional_work_used'):
        _integer(getattr(result,name),'$.'+name)
    _integer(result.optional_check_steps,'$.optional_check_steps',nullable=True)
    for name in ('source_bytes','plan_bytes','plan_operations','expression_nodes','check_steps'):
        _integer(getattr(result.limits,name),'$.limits.'+name,minimum=1)
    for i,attempt in enumerate(result.attempts):
        path=f'$.attempts[{i}]'
        _text(attempt.candidate_id,path+'.candidate_id',256)
        _text(attempt.reason,path+'.reason')
        if attempt.check is not None:
            _validate_public_check(attempt.check,path+'.check')
        _attempt(json_record(attempt),path)
    # JSON schema validation below rejects bool integers and oversized retained
    # history before anything is published. The typed comparison rejects mutable
    # replacements in nested frozen public records as well.
    digest=None
    if result.selected_plan is not None:
        if type(result.selected_plan_bytes) is not bytes or type(result.selected_check) is not CheckResult:
            raise ValueError('selected bytes and check must accompany the plan')
        encoded=encode_plan(result.selected_plan,limits=result.limits)
        if encoded!=result.selected_plan_bytes:
            raise ValueError('selected plan differs from retained exact bytes')
        checked=check_plan(kernel,result.selected_plan,result.limits)
        if not checked.eligible or not _same_typed(checked,result.selected_check):
            raise ValueError('selected receipt does not match fresh eligible check')
        digest=sha256(encoded).hexdigest()
        metrics=(checked.multiplication_ops,checked.workspace_bytes)
        if kernel.objective==Objective.PLAN_WORKSPACE_BYTES: metrics=metrics[::-1]
        if not _same_typed(result.selected_key,(*metrics,result.selected_plan.plan_id)):
            raise ValueError('selected ranking key mismatch')
        if not any(a.candidate_id==result.selected_plan.plan_id and _same_typed(a.check,checked)
                   and a.plan_digest==digest for a in result.attempts):
            raise ValueError('selected artifact has no matching checked attempt')
    elif any(x is not None for x in (result.selected_plan_bytes,result.selected_check,result.selected_key)):
        raise ValueError('no plan requires null selected fields')
    manifest=ReplayManifest(MANIFEST_VERSION,kernel.source_digest,'source-'+kernel.source_digest+'.ax',
                            digest,None if digest is None else 'plan-'+digest+'.json',
                            kernel.semantic_digest,_cap_digest(kernel.cap),ranking_digest(kernel.objective),
                            SEMANTICS_VERSION,1,CHECKER_VERSION,CHECK_ACCOUNTING_VERSION,
                            result.budget_accounting_version,kernel.cap,kernel.objective,result.selected_check,
                            result.attempts,result.termination_reason,result.reason,result.selected_key,
                            result.total_check_steps,result.total_work_used,result.optional_check_steps,
                            result.optional_work_used,result.artifact_state,result.limits)
    validated=decode_manifest(canonical_json(json_record(manifest)))
    if not _same_typed(manifest,validated):
        raise ValueError('search history contains incorrectly typed records')
    return manifest



@contextmanager
def _directory(directory, *, create=False):
    """Pin each real directory component without following a swapped symlink."""
    path=Path(os.path.abspath(directory))
    flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
    descriptor=os.open(path.anchor,flags)
    try:
        for component in path.parts[1:]:
            if create:
                try:
                    os.mkdir(component,mode=0o755,dir_fd=descriptor)
                except FileExistsError:
                    pass
            child=os.open(component,flags,dir_fd=descriptor)
            os.close(descriptor)
            descriptor=child
        yield descriptor
    finally:
        os.close(descriptor)


def _directory_unchanged(directory, descriptor):
    with _directory(directory) as named:
        expected,actual=os.fstat(descriptor),os.fstat(named)
        if (expected.st_dev,expected.st_ino)!=(actual.st_dev,actual.st_ino):
            raise OSError('publication directory was replaced')


def _read_exact_at(directory_fd, name, data):
    # O_NONBLOCK prevents a replaced FIFO from hanging before fstat rejects it.
    descriptor=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory_fd)
    with os.fdopen(descriptor,'rb') as stream:
        metadata=os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size!=len(data):
            raise OSError('referenced artifact is not a matching regular file: '+name)
        if stream.read(len(data)+1)!=data:
            raise OSError('referenced artifact bytes changed: '+name)


def _temporary(directory_fd, prefix):
    for _ in range(32):
        name=prefix+secrets.token_hex(16)
        try:
            descriptor=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,
                               0o600,dir_fd=directory_fd)
            return descriptor,name
        except FileExistsError:
            continue
    raise OSError('cannot allocate a unique artifact temporary')


def _unlink_at(directory_fd, name):
    try:
        os.unlink(name,dir_fd=directory_fd)
    except FileNotFoundError:
        pass


def _publish_content(directory_fd, name, data):
    try:
        _read_exact_at(directory_fd,name,data)
        return
    except FileNotFoundError:
        pass
    descriptor,temporary=_temporary(directory_fd,'.axiom-')
    try:
        with os.fdopen(descriptor,'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # Hard-link is an atomic no-replace publication of a complete file.
        try:
            os.link(temporary,name,src_dir_fd=directory_fd,dst_dir_fd=directory_fd,
                    follow_symlinks=False)
        except FileExistsError:
            _read_exact_at(directory_fd,name,data)
    finally:
        _unlink_at(directory_fd,temporary)


def write_attempt(directory: Path, module: SourceModule, result: SearchResult) -> Path:
    """Publish immutable snapshots and atomically replace manifest last.

    Every filesystem mutation is relative to a pinned directory descriptor.
    Ancestor replacement cannot redirect content creation, cleanup or manifest
    replacement into another directory. Renaming the original directory is
    detected before returning a published path. Arbitrary later content changes
    remain detectable by exact replay rather than prevented by this protocol.
    """
    manifest=_manifest(module,result)
    data=encode_manifest(manifest)
    directory=Path(directory)
    references=[(manifest.source_file,module.source_bytes)]
    if manifest.plan_file is not None:
        references.append((manifest.plan_file,result.selected_plan_bytes))
    with _directory(directory,create=True) as directory_fd:
        for name,content in references:
            _publish_content(directory_fd,name,content)
        descriptor,temporary=_temporary(directory_fd,'.manifest-')
        try:
            with os.fdopen(descriptor,'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            for name,content in references:
                _read_exact_at(directory_fd,name,content)
            _directory_unchanged(directory,directory_fd)
            os.fsync(directory_fd)
            os.replace(temporary,'manifest.json',src_dir_fd=directory_fd,dst_dir_fd=directory_fd)
            os.fsync(directory_fd)
            _directory_unchanged(directory,directory_fd)
        finally:
            _unlink_at(directory_fd,temporary)
    return directory/'manifest.json'


def verify_references(directory: Path, source: bytes, plan_bytes: bytes,
                      manifest_bytes: bytes) -> None:
    """Verify published snapshots using pinned, non-symlink directory reads.

    The bytes-only replay API has no filesystem context. The CLI calls this
    before returning success so missing/replaced files cannot be accepted by
    supplying separate copies of their former bytes.
    """
    manifest=decode_manifest(manifest_bytes)
    with _directory(directory) as directory_fd:
        _read_exact_at(directory_fd,manifest.source_file,source)
        if manifest.plan_file is not None:
            _read_exact_at(directory_fd,manifest.plan_file,plan_bytes)
        _directory_unchanged(directory,directory_fd)
