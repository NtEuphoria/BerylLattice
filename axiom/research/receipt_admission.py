"""Fail-closed measurement consistency checks; no native collector is approved.

SyntheticFixtureOracle is a caller-selected literal test oracle. It must be
selected independently of a measurement, never derived from that receipt's
self-claimed expected digest. It is not a scalable Axiom oracle or physics proof.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re

from experiment_manifest import FrozenManifest
from state_artifacts import (ArtifactLimits, ClosureFile, canonical_json, compare_state,
    read_manifest, verify_acquisition, verify_state, _read_file, _root, _write_immutable)

COSTS = ('setup','capture','compute','maintenance','invalidation','conversion','cleanup','cold_refresh')
RESOURCES = ('peak_bytes','retained_bytes','allocations','text_bytes','build_ns','edit_check_ns')
PHASES = ('preflight','dispatch','scratch_setup','initialization','copies','kernel','scratch_cleanup')
NATIVE_UNAVAILABLE = (
    'native unavailable: reviewed collector definitions and physical instrumentation validation are deferred',
    'native unavailable: independently reviewed scalable Axiom oracle is deferred',
    'native unavailable: separately reviewed larger-buffer lowering gate is deferred',
)
ASSUMPTIONS = (
    'Receipt consistency and retained bytes do not establish execution of the collector or physical timer/resource correctness.',
    'Collector completeness, hardware/OS controls, absence of unreported accesses and the stated sampling/reset independence remain external assumptions.',
    'Synthetic expected values and provenance are supplied independently by the fixture author; this is not a reviewed scalable Axiom oracle.',
)
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_TOKEN = re.compile(r'[A-Za-z0-9_.:-]{1,128}\Z')


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _keys(value, names, label):
    _require(type(value) is dict and set(value)==set(names),label+': missing or unknown fields')


def _same_json(left,right):
    return canonical_json(left)==canonical_json(right)


def _integer(value, label, minimum=0):
    _require(type(value) is int and minimum<=value<=(1<<63)-1,label+': invalid integer')
    return value


def _sha(value, label):
    _require(type(value) is str and _SHA.fullmatch(value),label+': invalid SHA-256')


def _time(value):
    _require(type(value) is str and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z',value),'chronology: invalid UTC timestamp')
    return datetime.fromisoformat(value[:-1]+'+00:00')


def _tuple(value, cls, label):
    _require(type(value) is tuple and all(type(item) is cls for item in value),label+' requires an immutable typed tuple')


def _record(cls,record):
    _keys(record,(f.name for f in fields(cls)),cls.__name__)
    return cls(**record)


@dataclass(frozen=True)
class FileEvidence:
    path: Path
    sha256: str

    def __post_init__(self):
        _require(type(self.path) is Path or isinstance(self.path,Path),'file path must be Path')
        _sha(self.sha256,'file evidence')


@dataclass(frozen=True)
class Observation:
    key: str
    value: int | None
    unit: str
    scope: str
    status: str
    raw_key: str
    reason: str = ''

    def __post_init__(self):
        _require(type(self.reason) is str,'observation reason must be a string')


@dataclass(frozen=True)
class IdentityEvidence:
    measurement_id: str
    unit_id: str
    session_id: str
    run_sha256: str
    artifact_role: str
    toolchain_sha256: str
    environment_sha256: str
    compiler_argv: tuple[str,...]
    files: tuple[tuple[str,FileEvidence],...]

    def __post_init__(self):
        _tuple(self.compiler_argv,str,'compiler argv')
        _require(type(self.files) is tuple and all(type(p) is tuple and len(p)==2 and type(p[0]) is str and type(p[1]) is FileEvidence for p in self.files),'identity files require immutable pairs')


@dataclass(frozen=True)
class StateEvidence:
    observed_manifest: Path
    acquisition: Path
    expected_manifest: Path
    oracle: Path
    events: FileEvidence
    stdout: FileEvidence
    diagnostics: FileEvidence


@dataclass(frozen=True)
class Instrumentation:
    collector_version: str
    collector_sha256: str
    raw: FileEvidence
    timer_scope: str
    start_ns: int
    end_ns: int
    included_phases: tuple[str,...]
    paid: tuple[Observation,...]
    total_paid_ns: int
    resources: tuple[Observation,...]
    diagnostics: tuple[Observation,...]

    def __post_init__(self):
        _tuple(self.included_phases,str,'phases')
        for key in ('paid','resources','diagnostics'):
            _tuple(getattr(self,key),Observation,key)


@dataclass(frozen=True)
class SamplingEvidence:
    sample_index: int
    pair_order: str
    position: str
    session_mode: str
    reset_evidence: FileEvidence | None
    schedule_sha256: str
    reset_protocol: str
    warmup: str
    input_touch: str
    output_initialization: str


@dataclass(frozen=True)
class MeasurementReceipt:
    schema_version: int
    provenance: str
    experiment_sha256: str
    stratum_sha256: str
    role: str
    started_utc: str
    completed_utc: str
    objective_sha256: str
    selector_sha256: str
    identity: IdentityEvidence
    state: StateEvidence
    instrumentation: Instrumentation
    sampling: SamplingEvidence

    def __post_init__(self):
        for key,cls in (('identity',IdentityEvidence),('state',StateEvidence),('instrumentation',Instrumentation),('sampling',SamplingEvidence)):
            _require(type(getattr(self,key)) is cls,key+' must be a typed immutable record')
        for key in ('observed_manifest','acquisition','expected_manifest','oracle'):
            _require(isinstance(getattr(self.state,key),Path),'state paths must be Path')
        for key in ('events','stdout','diagnostics'):
            _require(type(getattr(self.state,key)) is FileEvidence,'semantic files must be typed')
        _require(type(self.instrumentation.raw) is FileEvidence,'raw observations require file evidence')
        _require(self.sampling.reset_evidence is None or type(self.sampling.reset_evidence) is FileEvidence,'reset evidence requires a file')

    def to_record(self):
        def encode(value):
            if isinstance(value,Path): return str(value)
            if type(value) is dict: return {key:encode(v) for key,v in value.items()}
            if type(value) in (tuple,list): return [encode(v) for v in value]
            return value
        return encode(asdict(self))

    @classmethod
    def from_record(cls,record):
        _keys(record,(f.name for f in fields(cls)),'measurement receipt')
        values=dict(record)
        for key,record_cls in (('identity',IdentityEvidence),('state',StateEvidence),('instrumentation',Instrumentation),('sampling',SamplingEvidence)):
            _keys(values[key],(f.name for f in fields(record_cls)),key)
        def file(value):
            _keys(value,('path','sha256'),'file evidence')
            _require(type(value['path']) is str,'path must be text')
            return FileEvidence(Path(value['path']),value['sha256'])
        identity=dict(values['identity'])
        _require(type(identity.get('files')) is list and type(identity.get('compiler_argv')) is list,'identity arrays required')
        _require(all(type(pair) is list and len(pair)==2 for pair in identity['files']),'identity files require pairs')
        identity['files']=tuple((key,file(ref)) for key,ref in identity['files'])
        identity['compiler_argv']=tuple(identity['compiler_argv'])
        values['identity']=_record(IdentityEvidence,identity)
        state=dict(values['state'])
        for key in ('observed_manifest','acquisition','expected_manifest','oracle'):
            _require(type(state.get(key)) is str,'state path must be text')
            state[key]=Path(state[key])
        for key in ('events','stdout','diagnostics'): state[key]=file(state[key])
        values['state']=_record(StateEvidence,state)
        instrument=dict(values['instrumentation'])
        instrument['raw']=file(instrument['raw'])
        for key in ('paid','resources','diagnostics'):
            _require(type(instrument.get(key)) is list,key+' must be an array')
            instrument[key]=tuple(_record(Observation,item) for item in instrument[key])
        _require(type(instrument.get('included_phases')) is list,'phases must be array')
        instrument['included_phases']=tuple(instrument['included_phases'])
        values['instrumentation']=_record(Instrumentation,instrument)
        sampling=dict(values['sampling'])
        if sampling.get('reset_evidence') is not None: sampling['reset_evidence']=file(sampling['reset_evidence'])
        values['sampling']=_record(SamplingEvidence,sampling)
        return cls(**values)


@dataclass(frozen=True)
class SyntheticFixtureOracle:
    expected_manifest: Path
    sidecar: Path
    version: str
    expected_manifest_sha256: str
    sidecar_sha256: str

    def __post_init__(self):
        _require(isinstance(self.expected_manifest,Path) and isinstance(self.sidecar,Path),'oracle paths must be Path')
        _require(type(self.version) is str and _TOKEN.fullmatch(self.version),'oracle version invalid')
        _sha(self.expected_manifest_sha256,'oracle expected manifest')
        _sha(self.sidecar_sha256,'oracle sidecar')


@dataclass(frozen=True)
class MeasurementAdmission:
    eligible: bool
    synthetic_eligible: bool
    provenance: str
    state_verified: bool
    reasons: tuple[str,...]
    native_reasons: tuple[str,...]
    assumptions: tuple[str,...]
    closure: tuple[ClosureFile,...]
    instrumentation_validated: bool = False


class _Closure:
    def __init__(self,limits):
        self.limits=limits
        self.files={}

    def add(self,record):
        prior=self.files.get(record.resolved_path)
        _require(prior is None or prior.sha256==record.sha256,'evidence changed within admission')
        if prior is None:
            _require(len(self.files)<self.limits.max_files and sum(r.byte_length for r in self.files.values())+record.byte_length<=self.limits.max_aggregate_bytes,'aggregate closure budget exceeded')
            self.files[record.resolved_path]=record

    def read(self,reference,label,retain=False):
        _require(type(reference) is FileEvidence,label+': file evidence required')
        path=_root(reference.path)
        record,raw=_read_file(path.parent,path.name,self.limits.max_file_bytes,retain)
        _require(record.sha256==reference.sha256,label+': stale identity')
        self.add(record)
        return raw

    def state(self,verified):
        for record in verified.closure: self.add(record)

    def finish(self):
        for record in self.files.values():
            current,_=_read_file(record.resolved_path.parent,record.resolved_path.name,self.limits.max_file_bytes)
            _require(current.sha256==record.sha256 and current.byte_length==record.byte_length,'evidence changed during admission')
        return tuple(self.files.values())


def write_fixture_oracle(expected_manifest: Path, *, version: str, events: FileEvidence,
                         stdout: FileEvidence, name='fixture-oracle.json') -> Path:
    """Bind independently authored literal expected state; never produce an oracle."""
    expected=verify_state(expected_manifest)
    _require(type(version) is str and _TOKEN.fullmatch(version),'oracle version invalid')
    refs={}
    for key,ref in (('events',events),('stdout',stdout)):
        relative=_root(ref.path).relative_to(expected.root).as_posix()
        record,_=_read_file(expected.root,relative,expected.limits.max_file_bytes)
        _require(record.sha256==ref.sha256,'oracle semantic identity differs')
        refs[key]=dict(path=relative,sha256=ref.sha256)
    record=dict(schema='axiom-synthetic-fixture-oracle-v1',provenance='synthetic',oracle_version=version,
        expected_manifest=expected.manifest_path.name,expected_manifest_sha256=expected.manifest_sha256,
        invocation_sha256=expected.metadata.invocation_sha256,status=expected.metadata.status,
        first_bad_index=expected.metadata.first_bad_index,events=refs['events'],stdout=refs['stdout'])
    _write_immutable(expected.root,name,canonical_json(record))
    return expected.root/name


def _observations(items,names,label,raw):
    _require(len(items)==len(names) and {o.key for o in items}==set(names),label+': missing or duplicate metrics')
    result={}
    for observation in items:
        key=observation.key
        _require(observation.status in ('measured','inapplicable','unavailable'),label+': invalid observation status')
        if observation.status=='unavailable':
            _require(observation.value is None,label+': unavailable numeric values must be null')
            raise ValueError(label+': unavailable observation '+key)
        _integer(observation.value,label+' '+key)
        if observation.status=='inapplicable':
            _require(label=='paid' and observation.value==0 and type(observation.reason) is str and bool(observation.reason.strip()),label+': zero inapplicability requires a reason')
        else:
            _require(observation.status=='measured',label+': required observation is unmeasured')
        expected=dict(value=observation.value,unit=observation.unit,scope=observation.scope,status=observation.status)
        _require(type(observation.raw_key) is str and observation.raw_key in raw and _same_json(raw[observation.raw_key],expected),label+': missing or inconsistent raw observation '+key)
        unit='ns' if label=='paid' or key.endswith('_ns') else 'count' if key=='allocations' else 'bytes'
        scope='checked_call' if label=='paid' else 'build' if key=='build_ns' else 'edit_check' if key=='edit_check_ns' else 'artifact_text_section' if key=='text_bytes' else 'operation'
        _require(observation.unit==unit and observation.scope==scope,label+': wrong units or scope '+key)
        result[key]=observation.value
    return result


def _validate(receipt,experiment,fixture_oracle,limits):
    _require(type(receipt) is MeasurementReceipt,'receipt must be MeasurementReceipt')
    _require(type(experiment) is FrozenManifest,'experiment must be FrozenManifest')
    experiment.revalidate()
    _require(type(receipt.schema_version) is int and receipt.schema_version==1,'unsupported measurement schema')
    _require(receipt.provenance in ('synthetic','native_observed'),'unknown measurement provenance')
    _require(receipt.experiment_sha256==experiment.sha256,'frozen experiment identity differs')
    spec=experiment.spec
    for key in ('objective_sha256','selector_sha256'):
        _require(getattr(receipt,key)==getattr(spec,key),'changed frozen '+key)
    matching=[w for w in spec.workloads if w.stratum_sha256==receipt.stratum_sha256 and w.role==receipt.role]
    _require(len(matching)==1,'unknown single frozen workload/role stratum')
    workload=matching[0]
    start,end=_time(receipt.started_utc),_time(receipt.completed_utc)
    _require(start<end<=datetime.now(timezone.utc),'chronology: empty, reversed or future receipt interval')
    if receipt.role=='pilot':
        _require(_time(spec.baseline_selected_utc)<=start<end<_time(spec.policy_frozen_utc),'chronology: pilot outside baseline/policy freeze')
        _require(receipt.identity.artifact_role=='baseline','chronology: A/A pilot requires baseline')
    elif receipt.role=='training':
        _require(_time(spec.preregistered_utc)<=start<end<=_time(spec.baseline_selected_utc),'chronology: training outside frozen window')
    else:
        _require(start>max(_time(spec.candidate_frozen_utc),_time(spec.policy_frozen_utc)),'chronology: measurement precedes candidate/policy freeze')
    closure=_Closure(limits)
    record,_=_read_file(experiment.path.parent,experiment.path.name,limits.max_file_bytes)
    closure.add(record)
    identity=receipt.identity
    for key in ('measurement_id','unit_id','session_id'):
        value=getattr(identity,key)
        _require(type(value) is str and _TOKEN.fullmatch(value),'invalid run '+key)
    _sha(identity.run_sha256,'run')
    _require(identity.artifact_role in ('baseline','candidate'),'unknown artifact role')
    _require(identity.compiler_argv and all(arg and len(arg)<=4096 for arg in identity.compiler_argv),'missing full compiler argv')
    _require(len(identity.files)==6 and {key for key,_ in identity.files}=={'executable','compiler','toolchain','environment','plan','emitted_kernel'},'identity files incomplete or duplicate')
    artifacts=dict(identity.files)
    for key,reference in identity.files: closure.read(reference,'identity '+key)
    _require(artifacts['compiler'].sha256==spec.compiler_sha256,'compiler identity differs from frozen compiler')
    _require(artifacts['executable'].sha256==getattr(spec,identity.artifact_role+'_sha256'),'executable identity differs from frozen artifact')
    _require(artifacts['toolchain'].sha256==identity.toolchain_sha256 and artifacts['environment'].sha256==identity.environment_sha256,'actual toolchain/environment identity differs')
    sampling=receipt.sampling
    _integer(sampling.sample_index,'sampling index')
    plan=spec.sampling
    _require(sampling.sample_index<plan.sample_count and sampling.pair_order==plan.orders[sampling.sample_index] and sampling.position in ('A','B'),'sampling: order/index mismatch')
    expected_role='baseline' if sampling.position=='A' or receipt.role=='pilot' else 'candidate'
    _require(identity.artifact_role==expected_role,'sampling: pair position differs from artifact role')
    _require(sampling.schedule_sha256==plan.sha256,'sampling: changed frozen schedule')
    for key in ('session_mode','reset_protocol','warmup','input_touch','output_initialization'):
        _require(getattr(sampling,key)==getattr(plan,key),'sampling: changed frozen '+key)
    if plan.session_mode=='reset_contract':
        _require(sampling.reset_evidence is not None and sampling.reset_evidence.sha256==plan.reset_evidence_sha256,'sampling: reset evidence mismatch')
        _require(closure.read(sampling.reset_evidence,'sampling reset',True),'sampling: empty reset evidence')
    else:
        _require(sampling.reset_evidence is None,'sampling: unexpected reset evidence')
    instrument=receipt.instrumentation
    _require(type(instrument.collector_version) is str and _TOKEN.fullmatch(instrument.collector_version),'collector version missing')
    _sha(instrument.collector_sha256,'collector')
    _require(instrument.timer_scope=='checked_call','timer scope must be checked_call')
    _integer(instrument.start_ns,'call timer start')
    _integer(instrument.end_ns,'call timer end',1)
    _require(instrument.start_ns<instrument.end_ns,'invalid call timer interval')
    span=instrument.end_ns-instrument.start_ns
    elapsed=end-start
    elapsed_ns=(elapsed.days*86400+elapsed.seconds)*1_000_000_000+elapsed.microseconds*1000
    _require(span<=elapsed_ns,'timer interval exceeds acquisition chronology')
    _require(instrument.included_phases==PHASES,'checked-call phase coverage incomplete or reordered')
    closure.read(instrument.raw,'raw observations')
    raw=read_manifest(instrument.raw.path,limits)
    _keys(raw,('schema','measurement_id','run_sha256','collector','identity','observations','timer','phases'),'raw observations')
    _require(raw['schema']=='synthetic-instrument-observations-v1' if receipt.provenance=='synthetic' else raw['schema']=='unreviewed-native-instrument-observations-v1','raw observation schema/provenance mismatch')
    _require(raw['measurement_id']==identity.measurement_id and raw['run_sha256']==identity.run_sha256,'raw observations identify another run')
    _require(_same_json(raw['collector'],dict(version=instrument.collector_version,sha256=instrument.collector_sha256)),'raw collector identity mismatch')
    _require(_same_json(raw['identity'],dict(files={key:ref.sha256 for key,ref in identity.files},compiler_argv=list(identity.compiler_argv),unit_id=identity.unit_id,session_id=identity.session_id,artifact_role=identity.artifact_role)),'raw compiler/artifact identity mismatch')
    _require(_same_json(raw['timer'],dict(scope=instrument.timer_scope,start_ns=instrument.start_ns,end_ns=instrument.end_ns)) and raw['phases']==list(instrument.included_phases),'raw timer/phase evidence mismatch')
    _require(type(raw['observations']) is dict,'raw observations must be records')
    paid=_observations(instrument.paid,COSTS,'paid',raw['observations'])
    total=_integer(instrument.total_paid_ns,'total paid',1)
    _require(sum(paid.values())==total<=span,'total paid must equal disjoint components within call interval')
    resources=_observations(instrument.resources,RESOURCES,'resources',raw['observations'])
    _require(resources['retained_bytes']<=resources['peak_bytes'],'resource retained exceeds peak')
    diagnostics=('process_rss_peak_bytes','arena_capacity_bytes','allocator_peak_bytes')
    _require(len(instrument.diagnostics)==3 and {o.key for o in instrument.diagnostics}==set(diagnostics),'resource diagnostic quantities must be explicit and distinct')
    all_observations=instrument.paid+instrument.resources+instrument.diagnostics
    raw_keys=[o.raw_key for o in all_observations]
    _require(len(raw_keys)==len(set(raw_keys)) and set(raw_keys)==set(raw['observations']),'raw observations must map one-to-one to paid/resources/diagnostics')
    seen=set()
    for observation in instrument.diagnostics:
        _require(observation.key in ('process_rss_peak_bytes','arena_capacity_bytes','allocator_peak_bytes') and observation.key not in seen,'invalid or conflated resource diagnostic')
        seen.add(observation.key)
        _require(observation.unit=='bytes' and observation.scope==dict(process_rss_peak_bytes='process',arena_capacity_bytes='plan_arena',allocator_peak_bytes='allocator')[observation.key],'resource diagnostic units/scope invalid')
        if observation.status=='unavailable':
            _require(observation.value is None,'unknown diagnostic numeric must be null')
        else:
            _integer(observation.value,'resource diagnostic')
            _require(observation.status=='measured','diagnostic status invalid')
        _require(_same_json(raw['observations'].get(observation.raw_key),dict(value=observation.value,unit=observation.unit,scope=observation.scope,status=observation.status)),'raw diagnostic mismatch')
    state=receipt.state
    try:
        observed=verify_state(state.observed_manifest,limits,sidecars=[state.acquisition.relative_to(state.observed_manifest.parent).as_posix()])
        acquisition=verify_acquisition(state.acquisition,observed)
    except (ValueError,OSError) as exc:
        raise ValueError('state/acquisition: '+str(exc)) from exc
    closure.state(observed)
    _require(acquisition.run_sha256==identity.run_sha256,'acquisition run identity mismatch')
    _require(acquisition.collector_sha256==instrument.collector_sha256,'acquisition collector identity mismatch')
    _require((acquisition.plan_sha256,acquisition.emitted_kernel_sha256,acquisition.binary_sha256)==tuple(artifacts[k].sha256 for k in ('plan','emitted_kernel','executable')),'acquisition artifact identity mismatch')
    _require(acquisition.mode==receipt.provenance,'acquisition provenance mismatch')
    _require((acquisition.started_utc,acquisition.completed_utc)==(receipt.started_utc,receipt.completed_utc),'acquisition chronology mismatch')
    meta=observed.metadata
    _require((meta.logical_semantics_sha256,meta.W,meta.H,meta.original_input_sha256,meta.initial_output_sha256)==(workload.logical_semantics_sha256,workload.W,workload.H,workload.input_sha256,workload.initial_output_sha256),'semantic invocation boundary differs from frozen workload')
    _require(fixture_oracle is not None,'independent oracle unavailable: explicit caller-selected synthetic fixture oracle required')
    _require(type(fixture_oracle) is SyntheticFixtureOracle,'oracle must be explicit SyntheticFixtureOracle')
    _require(receipt.provenance=='synthetic','synthetic oracle cannot admit native provenance')
    _require(_root(state.expected_manifest)==_root(fixture_oracle.expected_manifest) and _root(state.oracle)==_root(fixture_oracle.sidecar),'oracle: receipt differs from independently selected fixture')
    try:
        closure.read(FileEvidence(state.oracle,fixture_oracle.sidecar_sha256),'oracle pinned sidecar')
        closure.read(FileEvidence(state.expected_manifest,fixture_oracle.expected_manifest_sha256),'oracle pinned expected manifest')
        oracle=read_manifest(state.oracle,limits)
        _keys(oracle,('schema','provenance','oracle_version','expected_manifest','expected_manifest_sha256','invocation_sha256','status','first_bad_index','events','stdout'),'oracle sidecar')
        _require(oracle['schema']=='axiom-synthetic-fixture-oracle-v1' and oracle['provenance']=='synthetic' and oracle['oracle_version']==fixture_oracle.version,'oracle provenance/version mismatch')
        extras=[state.oracle.relative_to(state.expected_manifest.parent).as_posix()]
        for key in ('events','stdout'):
            _keys(oracle[key],('path','sha256'),'oracle '+key)
            extras.append(oracle[key]['path'])
        expected=verify_state(state.expected_manifest,limits,closure_paths=extras)
        closure.state(expected)
        _require(oracle['expected_manifest']==expected.manifest_path.name and oracle['expected_manifest_sha256']==expected.manifest_sha256,'oracle expected state identity mismatch')
        _require(oracle['invocation_sha256']==expected.metadata.invocation_sha256==meta.invocation_sha256 and oracle['status']==expected.metadata.status and _same_json(oracle['first_bad_index'],expected.metadata.first_bad_index),'oracle semantic invocation/status mismatch')
    except (ValueError,OSError,KeyError,TypeError) as exc:
        raise ValueError('oracle: '+str(exc)) from exc
    _require(observed.logical_bytes+expected.logical_bytes<=limits.max_logical_bytes,'expanded logical comparison byte budget exceeded')
    comparison=compare_state(observed,expected)
    _require(comparison.equal,'semantic '+str(comparison.reason)+' '+str(comparison.role)+' '+str(comparison.coordinate))
    # Immutable-input preservation is known independently of fixture output values.
    # This supplements (and never replaces) the complete scalar comparison above.
    input_digest=hashlib.sha256()
    for block in observed.iter_bytes('input_after'):
        input_digest.update(block)
    _require(input_digest.hexdigest()==meta.original_input_sha256,'semantic input preservation differs from frozen original input')
    for key in ('events','stdout'):
        actual=closure.read(getattr(state,key),'semantic '+key,True)
        expected_ref=FileEvidence(expected.root/oracle[key]['path'],oracle[key]['sha256'])
        expected_raw=closure.read(expected_ref,'oracle semantic '+key,True)
        _require(actual==expected_raw,'semantic '+key+' differs from independent fixture')
    closure.read(state.diagnostics,'instrumentation diagnostics')
    return closure.finish()


def _admit(receipt,experiment,fixture_oracle,limits):
    provenance=receipt.provenance if type(receipt) is MeasurementReceipt else 'unavailable'
    try:
        closure=_validate(receipt,experiment,fixture_oracle,limits)
    except (ValueError,OSError,TypeError,KeyError,AttributeError,OverflowError) as exc:
        return MeasurementAdmission(False,False,provenance,False,(str(exc),),NATIVE_UNAVAILABLE,ASSUMPTIONS,())
    return MeasurementAdmission(False,True,'synthetic',True,(),NATIVE_UNAVAILABLE,ASSUMPTIONS,closure)


def admit_measurement(receipt: MeasurementReceipt, experiment: FrozenManifest, *,
                      limits: ArtifactLimits=ArtifactLimits()) -> MeasurementAdmission:
    """Native admission is unavailable; no receipt field/version can enable it."""
    return _admit(receipt,experiment,None,limits)


def admit_synthetic_fixture(receipt: MeasurementReceipt, experiment: FrozenManifest, *,
                            fixture_oracle: SyntheticFixtureOracle,
                            limits: ArtifactLimits=ArtifactLimits()) -> MeasurementAdmission:
    """Validate a synthetic fixture against an independently selected test oracle.

    Caller must select expected values independently of the receipt. The result
    always has eligible=False; synthetic_eligible is solely an infrastructure test.
    """
    return _admit(receipt,experiment,fixture_oracle,limits)
