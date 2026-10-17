"""Frozen v1 experiment declarations, not proof of undisclosed access or native execution."""
from __future__ import annotations

from array import array
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from functools import lru_cache
import hashlib
import os
from pathlib import Path
import re
import sys

from state_artifacts import canonical_json, read_manifest, _write_directory, _write_immutable

TRAINING_SHAPES = ((32,32),(128,128),(512,512),(2048,2048),(4096,64),(64,4096))
HELD_OUT_SHAPES = ((31,33),(127,129),(511,513),(2047,2049),(4093,67),(67,4093),(8191,1),(1,8191))
TRAINING_SEEDS = (1,2,3,4)
HELD_OUT_SEEDS = (65537,65538,65539,65540)
THRESHOLD_POLICY = 'max(5%,pilot_p95_absolute_paired_variation)'
SCHEMA = 'axiom-experiment-v1'
SCHEDULE_VERSION = 'sha256-sort-balanced-abba-v1'
_ROLES = ('correctness','training','pilot','selection','held_out')
_IDENTITIES = ('objective_sha256','selector_sha256','compiler_sha256','baseline_sha256','candidate_sha256')
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_UTC = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z\Z')


def _integer(value, name, minimum=0, maximum=(1<<63)-1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{name} must be an integer in [{minimum}, {maximum}]')


def _sha(value, name):
    if type(value) is not str or not _SHA.fullmatch(value):
        raise ValueError(f'{name} must be a lowercase SHA-256 identifier')


def _text(value, name):
    if type(value) is not str or not value.strip() or len(value)>4096:
        raise ValueError(f'{name} must be nonempty bounded text')


def _time(value):
    if type(value) is not str or not _UTC.fullmatch(value):
        raise ValueError('timestamp must use UTC with Z suffix')
    try:
        return datetime.fromisoformat(value[:-1]+'+00:00')
    except ValueError as exc:
        raise ValueError('invalid UTC timestamp') from exc


def _hash(value):
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _keys(record, expected, name):
    if type(record) is not dict or set(record)!=set(expected):
        raise ValueError(f'{name} has missing or unknown fields')


def _record(cls, record):
    _keys(record, (f.name for f in fields(cls)), cls.__name__)
    return cls(**record)


@lru_cache(maxsize=128,typed=True)
def approved_input_sha256(W: int, H: int, seed: int) -> str:
    """Hash actual approved LCG64 input as row-major little-endian i32 bytes.

    This synthesizes the declared input, never an observed post-call state. Bounds
    keep a malformed declaration from requesting an unbounded generator workload.
    """
    _integer(W,'W',1,8191)
    _integer(H,'H',1,8191)
    _integer(seed,'seed',0,(1<<64)-1)
    if (W+1)*(H+1)>4_198_401:
        raise ValueError('input exceeds the frozen v1 shape envelope')
    remaining, state, digest = (W+1)*(H+1), seed, hashlib.sha256()
    while remaining:
        count=min(remaining,16384)
        block=array('i')
        for _ in range(count):
            state=(state*6364136223846793005+1442695040888963407)&((1<<64)-1)
            block.append((state>>32)&1023)
        if block.itemsize!=4:
            raise ValueError('platform does not provide 32-bit array integers')
        if sys.byteorder!='little':
            block.byteswap()
        digest.update(block.tobytes())
        remaining-=count
    return digest.hexdigest()


@dataclass(frozen=True)
class Workload:
    role: str
    W: int
    H: int
    seed: int
    logical_semantics_sha256: str
    input_sha256: str
    initial_output_sha256: str
    generator: str = 'lcg64'
    generator_version: str = 'v1'
    cap_bytes: int | None = None
    entry_contract: str = 'ordinary_checked_call'
    cache_regime: str = 'validation_warmed'

    def __post_init__(self):
        if self.role not in _ROLES:
            raise ValueError('invalid dataset role')
        _integer(self.W,'W',1,8191)
        _integer(self.H,'H',1,8191)
        _integer(self.seed,'seed',0,(1<<64)-1)
        for name in ('logical_semantics_sha256','input_sha256','initial_output_sha256'):
            _sha(getattr(self,name),name)
        for name in ('generator','generator_version','entry_contract','cache_regime'):
            _text(getattr(self,name),name)
        if self.cap_bytes is not None:
            _integer(self.cap_bytes,'cap_bytes')

    @property
    def content_sha256(self):
        # Filenames, role, seed/generator labels and cache cannot hide identical data.
        return _hash(dict(logical_semantics_sha256=self.logical_semantics_sha256,
                          shape={'W':self.W,'H':self.H},input_sha256=self.input_sha256))

    @property
    def stratum_sha256(self):
        return _hash(dict(content_sha256=self.content_sha256, generator=self.generator,
            generator_version=self.generator_version, seed=self.seed, cap_bytes=self.cap_bytes,
            entry_contract=self.entry_contract, initial_output_sha256=self.initial_output_sha256,
            cache_regime=self.cache_regime))

    def to_record(self):
        return asdict(self)

    @classmethod
    def from_record(cls, record):
        return _record(cls,record)


@dataclass(frozen=True)
class AccessRecord:
    workload: Workload
    purpose: str
    accessed_utc: str
    baseline_aa: bool = False

    def __post_init__(self):
        if not isinstance(self.workload,Workload):
            raise ValueError('access requires a typed workload')
        if self.purpose not in ('training','selection','tuning','correctness','pilot'):
            raise ValueError('unknown access purpose')
        _time(self.accessed_utc)
        if type(self.baseline_aa) is not bool or (self.baseline_aa and self.purpose!='pilot'):
            raise ValueError('only a baseline A/A pilot may declare baseline_aa')


@dataclass(frozen=True)
class SamplingPlan:
    sample_count: int
    randomization_seed: int
    session_mode: str
    independence_assumption: str
    reset_protocol: str
    warmup: str
    input_touch: str
    output_initialization: str
    reset_evidence_sha256: str | None = None
    version: str = SCHEDULE_VERSION

    def __post_init__(self):
        _integer(self.sample_count,'sample_count',30,1024)
        if self.sample_count%2:
            raise ValueError('sample_count must be even')
        _integer(self.randomization_seed,'randomization_seed',0,(1<<63)-1)
        if self.version!=SCHEDULE_VERSION:
            raise ValueError('unsupported sampling schedule version')
        if self.session_mode not in ('fresh_owned_process','reset_contract'):
            raise ValueError('session_mode requires owned sessions or an external reset contract')
        for name in ('independence_assumption','reset_protocol','warmup','input_touch','output_initialization'):
            _text(getattr(self,name),name)
        if self.reset_evidence_sha256 is not None:
            _sha(self.reset_evidence_sha256,'reset_evidence_sha256')
        if self.session_mode=='reset_contract' and self.reset_evidence_sha256 is None:
            raise ValueError('reused sessions require externally established reset evidence')

    @property
    def orders(self) -> tuple[str,...]:
        # Hash-sort is explicitly versioned, independent of random.shuffle versions.
        indices=sorted(range(self.sample_count),key=lambda i: hashlib.sha256(
            f'{self.version}:{self.randomization_seed}:{i}'.encode('ascii')).digest())
        return tuple('AB' if i<self.sample_count//2 else 'BA' for i in indices)

    @property
    def sha256(self):
        return _hash(dict(plan=asdict(self),orders=self.orders))


@dataclass(frozen=True)
class ExperimentSpec:
    workloads: tuple[Workload,...]
    known_accesses: tuple[AccessRecord,...]
    training_history_complete: bool
    holdout_rule: str
    preregistered_utc: str
    selector_design_frozen_utc: str
    baseline_selected_utc: str
    candidate_frozen_utc: str
    policy_frozen_utc: str
    objective_sha256: str
    selector_sha256: str
    compiler_sha256: str
    baseline_sha256: str
    candidate_sha256: str
    sampling: SamplingPlan
    primary_stratum_sha256: str | None = None

    def __post_init__(self):
        for name,cls in (('workloads',Workload),('known_accesses',AccessRecord)):
            value=getattr(self,name)
            if type(value) is not tuple or any(not isinstance(item,cls) for item in value):
                raise ValueError(f'{name} must be an immutable tuple of {cls.__name__}')
        if type(self.training_history_complete) is not bool:
            raise ValueError('training_history_complete must be boolean')
        if self.holdout_rule not in ('input','shape'):
            raise ValueError('holdout_rule must explicitly be input or shape')
        for name in _IDENTITIES:
            _sha(getattr(self,name),name)
        for name in ('preregistered_utc','selector_design_frozen_utc','baseline_selected_utc','candidate_frozen_utc','policy_frozen_utc'):
            _time(getattr(self,name))
        if not isinstance(self.sampling,SamplingPlan):
            raise ValueError('sampling must be SamplingPlan')
        if self.primary_stratum_sha256 is not None:
            _sha(self.primary_stratum_sha256,'primary_stratum_sha256')

    def to_record(self):
        record=asdict(self)
        record['workloads']=[w.to_record() for w in self.workloads]
        record['known_accesses']=[asdict(a) for a in self.known_accesses]
        return record

    @classmethod
    def from_record(cls,record):
        _keys(record,(f.name for f in fields(cls)),'ExperimentSpec')
        values=dict(record)
        if type(values['workloads']) is not list or type(values['known_accesses']) is not list:
            raise ValueError('workloads and known_accesses must be JSON arrays')
        values['workloads']=tuple(Workload.from_record(w) for w in values['workloads'])
        accesses=[]
        for access in values['known_accesses']:
            _keys(access,(f.name for f in fields(AccessRecord)),'AccessRecord')
            access=dict(access)
            access['workload']=Workload.from_record(access['workload'])
            accesses.append(AccessRecord(**access))
        values['known_accesses']=tuple(accesses)
        values['sampling']=_record(SamplingPlan,values['sampling'])
        return cls(**values)


def _primary(spec):
    candidates=[w for w in spec.workloads if w.role=='held_out' and (w.W,w.H,w.seed)==(2047,2049,65537)
                and w.cap_bytes is None and w.entry_contract=='ordinary_checked_call']
    if spec.primary_stratum_sha256 is not None:
        candidates=[w for w in candidates if w.stratum_sha256==spec.primary_stratum_sha256]
    if len(candidates)!=1:
        raise ValueError('exactly one primary checked-call unconstrained stratum must be frozen')
    return candidates[0]


def _held_out_access(workload, held_content, held_shapes, holdout_rule):
    return (workload.content_sha256 in held_content or
            (holdout_rule=='shape' and (workload.W,workload.H) in held_shapes))


def _validate_spec(spec):
    if not isinstance(spec,ExperimentSpec):
        raise ValueError('spec must be ExperimentSpec')
    if not spec.training_history_complete:
        raise ValueError('complete known training history must be declared; unreported access cannot be discovered')
    if len(spec.workloads)>1024 or len(spec.known_accesses)>4096:
        raise ValueError('experiment record count limit exceeded')
    pre,design,baseline,candidate,policy=(_time(getattr(spec,n)) for n in
        ('preregistered_utc','selector_design_frozen_utc','baseline_selected_utc','candidate_frozen_utc','policy_frozen_utc'))
    if not pre<=design<=baseline<=candidate<policy:
        raise ValueError('dataset/design/baseline/candidate/policy freeze chronology is reversed')
    seen=set()
    timing_cells={(W,H,seed) for W,H in TRAINING_SHAPES for seed in TRAINING_SEEDS}
    timing_cells.update((W,H,seed) for W,H in HELD_OUT_SHAPES for seed in HELD_OUT_SEEDS)
    for workload in spec.workloads:
        key=(workload.role,workload.stratum_sha256)
        if key in seen:
            raise ValueError('duplicate dataset stratum')
        seen.add(key)
        if workload.role in ('training','held_out','pilot','selection'):
            if (workload.W,workload.H,workload.seed) not in timing_cells:
                raise ValueError('timing shape/seed cell is outside the approved v1 matrix')
            if workload.input_sha256!=approved_input_sha256(workload.W,workload.H,workload.seed):
                raise ValueError('declared input hash differs from actual approved generator input bytes')
    for role,shapes,seeds in (('training',TRAINING_SHAPES,TRAINING_SEEDS),('held_out',HELD_OUT_SHAPES,HELD_OUT_SEEDS)):
        expected={(W,H,seed) for W,H in shapes for seed in seeds}
        actual={(w.W,w.H,w.seed) for w in spec.workloads if w.role==role}
        if actual!=expected:
            raise ValueError(f'{role} shape/seed matrix differs from approved v1 matrix')
    primary=_primary(spec)
    if any(w.logical_semantics_sha256!=primary.logical_semantics_sha256 for w in spec.workloads):
        raise ValueError('all frozen workloads must share the declared logical semantics')
    held=[w for w in spec.workloads if w.role=='held_out']
    held_content={w.content_sha256 for w in held}
    held_shapes={(w.W,w.H) for w in held}
    trained=set()
    for access in spec.known_accesses:
        if access.purpose!='correctness' and access.workload.input_sha256!=approved_input_sha256(access.workload.W,access.workload.H,access.workload.seed):
            raise ValueError('known access input hash differs from actual approved generator input bytes')
        at=_time(access.accessed_utc)
        if access.purpose=='pilot':
            if not access.baseline_aa:
                raise ValueError('pilot access must be baseline A/A, never candidate feedback')
            if at<design:
                raise ValueError('selector design must freeze before baseline pilot exposure')
            if not baseline<=at<policy:
                raise ValueError('baseline A/A pilot must follow baseline selection and precede policy freeze')
            continue
        if access.baseline_aa:
            raise ValueError('invalid A/A access role')
        if not pre<=at<=candidate:
            raise ValueError('known tuning access must follow preregistration and precede candidate freeze')
        if access.purpose=='training':
            if at>baseline:
                raise ValueError('training history must precede fixed baseline selection')
            trained.add(access.workload.content_sha256)
        contamination=_held_out_access(access.workload,held_content,held_shapes,spec.holdout_rule)
        if contamination:
            raise ValueError('held-out content/shape appears in known tuning access history')
    required={w.content_sha256 for w in spec.workloads if w.role=='training'}
    if not required<=trained:
        raise ValueError('missing declared training history for frozen training content')
    return primary


def _payload(spec):
    primary=_validate_spec(spec)
    return dict(schema=SCHEMA,spec=spec.to_record(),primary_stratum_sha256=primary.stratum_sha256,
                threshold_policy=THRESHOLD_POLICY,sampling_orders=list(spec.sampling.orders))


@dataclass(frozen=True)
class FrozenManifest:
    path: Path
    sha256: str
    spec: ExperimentSpec

    @property
    def primary_workload(self):
        return _primary(self.spec)

    @property
    def threshold_policy(self):
        return THRESHOLD_POLICY

    def to_record(self):
        return _payload(self.spec)

    def revalidate(self):
        if load_manifest(self.path)!=self:
            raise ValueError('frozen manifest changed or does not match its typed declaration')


def load_manifest(path: Path) -> FrozenManifest:
    path=Path(os.path.abspath(path))
    record=read_manifest(path)
    _keys(record,('schema','spec','primary_stratum_sha256','threshold_policy','sampling_orders'),'experiment manifest')
    if record['schema']!=SCHEMA:
        raise ValueError('unsupported experiment schema')
    spec=ExperimentSpec.from_record(record['spec'])
    expected=_payload(spec)
    if canonical_json(record)!=canonical_json(expected):
        raise ValueError('frozen primary, threshold or sampling schedule was modified')
    return FrozenManifest(path,_hash(record),spec)


def freeze_manifest(spec: ExperimentSpec, directory: Path) -> FrozenManifest:
    raw=canonical_json(_payload(spec))
    # The loader's strict envelope applies before publication as well.
    if len(raw)>1_048_576:
        raise ValueError('experiment manifest exceeds metadata envelope')
    directory=Path(os.path.abspath(directory))
    # Share the state writer's descriptor-pinned directory traversal. NOFOLLOW on
    # only the final filename would still allow a raced ancestor symlink write.
    with _write_directory(directory,create=True):
        pass
    name=f'experiment-{hashlib.sha256(raw).hexdigest()}.json'
    path=directory/name
    _write_immutable(directory,name,raw)
    result=load_manifest(path)
    if result.sha256!=hashlib.sha256(raw).hexdigest() or result.spec!=spec:
        raise ValueError('immutable experiment changed before freeze completed')
    return result


@dataclass(frozen=True)
class Receipt:
    role: str
    stratum_sha256: str
    started_utc: str
    completed_utc: str
    objective_sha256: str
    selector_sha256: str
    compiler_sha256: str
    baseline_sha256: str
    candidate_sha256: str
    baseline_aa: bool = False

    def __post_init__(self):
        if self.role not in _ROLES:
            raise ValueError('unknown chronology receipt role')
        _sha(self.stratum_sha256,'stratum_sha256')
        for name in _IDENTITIES:
            _sha(getattr(self,name),name)
        if _time(self.completed_utc)<_time(self.started_utc):
            raise ValueError('receipt UTC window is reversed')
        if type(self.baseline_aa) is not bool or (self.baseline_aa and self.role!='pilot'):
            raise ValueError('only pilot receipts may declare baseline A/A')

    def to_record(self):
        return asdict(self)

    @classmethod
    def from_record(cls,record):
        return _record(cls,record)


ChronologyReceipt = Receipt


@dataclass(frozen=True)
class ChronologyResult:
    eligible: bool
    reasons: tuple[str,...]


def validate_chronology(manifest: FrozenManifest, receipts: tuple[Receipt,...]) -> ChronologyResult:
    """Check reported chronology per stratum; cannot infer undisclosed accesses."""
    reasons=[]
    try:
        manifest.revalidate()
    except (ValueError,OSError,TypeError) as exc:
        return ChronologyResult(False,(f'invalid frozen manifest: {exc}',))
    if type(receipts) is not tuple or any(not isinstance(r,Receipt) for r in receipts):
        return ChronologyResult(False,('receipts must be an immutable tuple of Receipt',))
    s=manifest.spec
    known={w.stratum_sha256:w for w in s.workloads}
    held_content={w.content_sha256 for w in s.workloads if w.role=='held_out'}
    held_shapes={(w.W,w.H) for w in s.workloads if w.role=='held_out'}
    preregistered=_time(s.preregistered_utc)
    training_strata={w.stratum_sha256 for w in s.workloads if w.role=='training'}
    held_strata={w.stratum_sha256 for w in s.workloads if w.role=='held_out'}
    design,baseline,candidate,policy=(_time(getattr(s,n)) for n in
        ('selector_design_frozen_utc','baseline_selected_utc','candidate_frozen_utc','policy_frozen_utc'))
    for index,r in enumerate(receipts):
        if r.stratum_sha256 not in known:
            reasons.append(f'receipt {index}: unknown single measurement stratum')
        for name in _IDENTITIES:
            if getattr(r,name)!=getattr(s,name):
                reasons.append(f'receipt {index}: changed {name} after freeze')
        start,end=_time(r.started_utc),_time(r.completed_utc)
        workload=known.get(r.stratum_sha256)
        contamination=(workload is not None and
                       _held_out_access(workload,held_content,held_shapes,s.holdout_rule))
        # Disclosed accesses obey the same holdout and preregistration rules as
        # AccessRecord. Final artifact selection/measurement has stricter windows
        # below; baseline A/A pilot exposure keeps its explicit exception.
        if start<preregistered:
            reasons.append(f'receipt {index}: disclosed access precedes dataset preregistration')
        if r.role!='pilot' and start<=candidate and contamination:
            reasons.append(f'receipt {index}: held-out content/shape appears in disclosed pre-freeze access')
        if r.role=='correctness':
            if start<=candidate:
                if end>candidate:
                    reasons.append(f'receipt {index}: correctness tuning access extends past candidate freeze')
            elif contamination:
                selections=[selected for selected in receipts if selected.role=='selection'
                            and selected.stratum_sha256==r.stratum_sha256]
                if (start<=policy or len(selections)!=1 or
                    _time(selections[0].completed_utc)>=start):
                    reasons.append(f'receipt {index}: held-out correctness acquisition must follow completed frozen selection')
        if r.role=='pilot' and (not r.baseline_aa or start<design or start<baseline or end>=policy):
            reasons.append(f'receipt {index}: baseline A/A pilot must follow design/baseline freeze and finish before policy freeze')
        if r.role=='training':
            if start<preregistered or end>baseline:
                reasons.append(f'receipt {index}: training outside preregistration/baseline window')
            if r.stratum_sha256 not in training_strata:
                reasons.append(f'receipt {index}: training receipt relabels nontraining/held-out data')
        if r.role=='selection' and start<=max(policy,candidate):
            reasons.append(f'receipt {index}: selection must follow candidate and pilot policy freeze')
        if r.role=='held_out':
            if r.stratum_sha256 not in held_strata:
                reasons.append(f'receipt {index}: final measurement is not a frozen held-out stratum')
            if start<=max(policy,candidate):
                reasons.append(f'receipt {index}: candidate measurement precedes candidate/policy freeze')
    measured=[r for r in receipts if r.role=='held_out']
    if not measured:
        reasons.append('no final held-out measurement receipt')
    for measurement in measured:
        strata=measurement.stratum_sha256
        pilots=[r for r in receipts if r.role=='pilot' and r.stratum_sha256==strata and r.baseline_aa]
        selections=[r for r in receipts if r.role=='selection' and r.stratum_sha256==strata]
        if not pilots:
            reasons.append(f'{strata}: missing separate baseline A/A pilot')
        if len(selections)!=1:
            reasons.append(f'{strata}: exactly one frozen selection receipt required')
        elif _time(selections[0].completed_utc)>=_time(measurement.started_utc):
            reasons.append(f'{strata}: candidate measurement precedes completed selection')
    return ChronologyResult(not reasons,tuple(dict.fromkeys(reasons)))
