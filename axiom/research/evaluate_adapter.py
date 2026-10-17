"""External, fail-closed binding to the pinned Beryl evaluator.

Only literal synthetic fixtures are supported. Retained read-only copies plus
full pre/post verification defend reproducibility, not a hostile same-UID writer.
No native collector or scalable semantic oracle is approved by this module.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import types
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from experiment_manifest import FrozenManifest, Receipt, Workload, load_manifest, validate_chronology
from receipt_admission import (MeasurementReceipt, SyntheticFixtureOracle,
    admit_synthetic_fixture, NATIVE_UNAVAILABLE, ASSUMPTIONS)
from state_artifacts import (ArtifactLimits, ClosureFile, canonical_json, read_manifest,
    verify_state, _read_file, _root, _relative)

VERIFIER_VERSION='axiom-export-v1.0'
EVALUATOR_SHA256='b368462fc46c3173650c8654765e283fc84fd1e86c7c6c11154d809367956593'
EVALUATOR_GIT_BLOB='2549df76055546a3b89d91cbc99599d2d131b96f'
PROFILES=('synthetic_correctness_fixture','synthetic_descriptive_held_out_fixture')


def require(condition,message):
    if not condition: raise ValueError(message)


def keys(record,names,label):
    require(type(record) is dict and set(record)==set(names),label+': missing or unknown fields')


def equal(a,b):
    return canonical_json(a)==canonical_json(b)


def utc_ns(value):
    dt=datetime.fromisoformat(value.replace('Z','+00:00'))-datetime(1970,1,1,tzinfo=timezone.utc)
    return (dt.days*86400+dt.seconds)*10**9+dt.microseconds*1000


def environment():
    # Never inherit Python startup/module injection configuration.
    return {'PATH':os.defpath,'LANG':'C.UTF-8','PYTHONNOUSERSITE':'1','PYTHONSAFEPATH':'1','PYTHONDONTWRITEBYTECODE':'1'}


@dataclass(frozen=True)
class ExportAdmission:
    request: Path
    experiment: FrozenManifest
    python: Path
    evaluator: Path
    limits: ArtifactLimits
    closure: tuple[ClosureFile,...]
    snapshot_root: Path
    python_version: str
    profile: str
    verifier_version: str = VERIFIER_VERSION

    @property
    def native_eligible(self): return False

    @property
    def native_reasons(self): return NATIVE_UNAVAILABLE


@dataclass(frozen=True)
class EvaluationRun:
    exit_status: int
    result: dict
    output: Path
    receipt_path: Path
    snapshot_root: Path
    python_version: str
    python_sha256: str
    evaluator_sha256: str
    native_eligible: bool = False


class Closure:
    def __init__(self,root,limits):
        self.root=root; self.limits=limits; self.files={}

    def add(self,record):
        prior=self.files.get(record.resolved_path)
        require(prior is None or (prior.sha256,prior.byte_length)==(record.sha256,record.byte_length),'closure identity changed')
        if prior is None:
            require(len(self.files)<self.limits.max_files,'closure file count budget exceeded')
            require(sum(f.byte_length for f in self.files.values())+record.byte_length<=self.limits.max_aggregate_bytes,'closure aggregate budget exceeded')
            self.files[record.resolved_path]=record

    def read(self,path,expected=None):
        path=_root(path)
        record,raw=_read_file(path.parent,path.name,self.limits.max_file_bytes,True)
        require(expected is None or record.sha256==expected,'stale closure identity: '+str(path))
        self.add(record)
        return raw

    def path(self,name):
        _relative(name)
        require(name.split('/')[0]!='.tools','reserved tool storage path')
        return _root(self.root/name)

    def ref(self,reference):
        keys(reference,('path','sha256'),'file reference')
        path=self.path(reference['path']); self.read(path,reference['sha256'])
        return path

    def json(self,reference):
        return read_manifest(self.ref(reference),self.limits)

    def finish(self):
        for record in tuple(self.files.values()): self.read(record.resolved_path,record.sha256)
        return tuple(sorted(self.files.values(),key=lambda r:str(r.resolved_path)))


def _receipt_paths(record,closure):
    """Resolve ONLY schema-defined paths; argv is data, never executed."""
    import copy
    record=copy.deepcopy(record)
    for _,ref in record['identity']['files']: ref['path']=str(closure.path(ref['path']))
    for key in ('observed_manifest','acquisition','expected_manifest','oracle'):
        record['state'][key]=str(closure.path(record['state'][key]))
    for key in ('events','stdout','diagnostics'):
        ref=record['state'][key]; ref['path']=str(closure.path(ref['path']))
    ref=record['instrumentation']['raw']; ref['path']=str(closure.path(ref['path']))
    if record['sampling']['reset_evidence'] is not None:
        ref=record['sampling']['reset_evidence']; ref['path']=str(closure.path(ref['path']))
    return MeasurementReceipt.from_record(record)


def _inspect(request,experiment,python,evaluator,limits):
    require(type(experiment) is FrozenManifest,'frozen experiment required')
    require(type(limits) is ArtifactLimits,'typed artifact limits required')
    defaults=ArtifactLimits()
    for name in ('max_file_bytes','max_aggregate_bytes','max_files','max_logical_bytes'):
        require(getattr(limits,name)<=getattr(defaults,name),'cannot widen evaluator closure limits')
    request=_root(request); python=Path(python).resolve(strict=True); evaluator=_root(evaluator)
    c=Closure(request.parent,limits)
    evaluator_bytes=c.read(evaluator,EVALUATOR_SHA256)
    require(hashlib.sha1(b'blob '+str(len(evaluator_bytes)).encode()+b'\0'+evaluator_bytes).hexdigest()==EVALUATOR_GIT_BLOB,'evaluator Git blob pin differs')
    python_bytes=c.read(python)
    envelope_path=Path(str(request)+'.axiom-export.json'); c.read(envelope_path)
    envelope=read_manifest(envelope_path,limits)
    keys(envelope,('schema','profile','verifier_version','request','experiment','semantic_contract','oracle','python_sha256','evaluator_sha256','measurements'),'export envelope')
    require(envelope['schema']=='axiom-export-v1' and envelope['verifier_version']==VERIFIER_VERSION,'unsupported export/verifier version')
    profile=envelope['profile']; require(profile in PROFILES,'native export unavailable; unknown synthetic profile')
    require(envelope['python_sha256']==hashlib.sha256(python_bytes).hexdigest() and envelope['evaluator_sha256']==EVALUATOR_SHA256,'tool identity differs')
    require(c.ref(envelope['request'])==request,'request binding differs')
    require(c.ref(envelope['experiment'])==_root(experiment.path),'experiment binding differs')
    experiment.revalidate()
    contract=c.ref(envelope['semantic_contract'])
    require(contract.stat().st_size>0,'empty semantic contract')
    oracle=envelope['oracle']; keys(oracle,('expected_manifest','sidecar','version'),'independently selected oracle')
    selected_oracle=SyntheticFixtureOracle(c.ref(oracle['expected_manifest']),c.ref(oracle['sidecar']),oracle['version'],
        oracle['expected_manifest']['sha256'],oracle['sidecar']['sha256'])
    request_record=c.json(envelope['request'])
    sealed=c.json(request_record['freeze']); pilot=c.json(sealed['pilot']); selection=c.json(request_record['selection'])
    require(pilot['evidence_kind']=='synthetic_validation','synthetic evidence cannot claim collector measurements')
    require(pilot['fingerprints']['semantic_contract']==envelope['semantic_contract'],'semantic contract binding differs')
    require(request_record['role']==('selection' if profile==PROFILES[0] else 'held_out'),'correctness/descriptive dataset role mismatch')
    workload_record=c.json(pilot['fingerprints']['workload']); workload=Workload.from_record(workload_record)
    require(workload in experiment.spec.workloads,'workload not frozen')
    require(workload.role==('correctness' if profile==PROFILES[0] else 'held_out'),'correctness cannot be relabeled held-out')
    require(workload.stratum_sha256!=experiment.primary_workload.stratum_sha256,'primary native endpoint unavailable; fixtures are descriptive only')
    if profile==PROFILES[0]:
        # A correctness label must not disguise an approved held-out input or shape.
        for held in experiment.spec.workloads:
            if held.role=='held_out':
                require(workload.content_sha256!=held.content_sha256 and (experiment.spec.holdout_rule!='shape' or (workload.W,workload.H)!=(held.W,held.H)),'correctness fixture violates held-out policy')
    fingerprints=pilot['fingerprints']
    for key,expected in (('baseline',experiment.spec.baseline_sha256),('compiler',experiment.spec.compiler_sha256)):
        require(fingerprints[key]['sha256']==expected,'frozen artifact identity mapping differs')
    require(request_record['candidate']['sha256']==experiment.spec.candidate_sha256,'candidate identity mapping differs')
    if profile==PROFILES[1]:
        require(sealed['frozen_utc_ns']==utc_ns(experiment.spec.policy_frozen_utc),'policy freeze chronology differs')
    else:
        require(sealed['frozen_utc_ns']>utc_ns(experiment.spec.policy_frozen_utc),'synthetic machinery freeze chronology differs')
    require(type(envelope['measurements']) is list,'measurement mappings must be array')
    bindings={}
    for binding in envelope['measurements']:
        keys(binding,('measurement','receipt'),'measurement mapping')
        key=str(c.ref(binding['measurement']))
        require(key not in bindings,'duplicate measurement mapping')
        bindings[key]=binding
    used=set(); logical_states={}; chronological=[]; fresh_sessions=set()
    sampling=experiment.spec.sampling
    independence_method={'fresh_owned_process':'separate_owned_sessions',
                         'reset_contract':'verified_reset_equivalence'}[sampling.session_mode]
    for stage,blocks in (('pilot',pilot['blocks']),('evaluation',request_record['blocks'])):
        require(type(blocks) is list and len(blocks)==experiment.spec.sampling.sample_count,'frozen sample count mapping differs')
        for index,block in enumerate(blocks):
            require(block['first']==experiment.spec.sampling.orders[index][0].lower(),'frozen schedule mapping differs')
            independence=c.json(block['independence'])
            require(independence['method']==independence_method,'independence method differs from frozen session mode')
            reset_path=c.ref(independence['evidence']) if sampling.session_mode=='reset_contract' else None
            for side in ('a','b'):
                path=str(c.ref(block[side])); require(path in bindings and path not in used,'missing or reused measurement mapping'); used.add(path)
                binding=bindings[path]; require(binding['measurement']==block[side],'measurement identity mapping differs')
                external=c.json(block[side]); receipt=_receipt_paths(c.json(binding['receipt']),c)
                require(receipt.stratum_sha256==workload.stratum_sha256,'workload stratum mapping differs')
                role='correctness' if profile==PROFILES[0] else 'pilot' if stage=='pilot' else 'held_out'
                require(receipt.role==role,'research role mapping differs')
                admission=admit_synthetic_fixture(receipt,experiment,fixture_oracle=selected_oracle,limits=limits)
                require(admission.synthetic_eligible,'measurement admission: '+'; '.join(admission.reasons))
                for record in admission.closure:
                    require(record.resolved_path.is_relative_to(c.root),'measurement closure escapes self-contained root')
                    c.add(record)
                for state in (receipt.state.observed_manifest,receipt.state.expected_manifest):
                    if state not in logical_states: logical_states[state]=verify_state(state,limits).logical_bytes
                require(sum(logical_states.values())<=limits.max_logical_bytes,'expanded logical closure budget exceeded')
                expected_base=stage=='pilot' or side=='a'
                require(receipt.identity.artifact_role==('baseline' if expected_base else 'candidate'),'artifact role mapping differs')
                expected_position='A' if profile==PROFILES[0] and stage=='pilot' else side.upper()
                require(receipt.sampling.position==expected_position and receipt.sampling.sample_index==index,'sample position mapping differs')
                for key in ('measurement_id','unit_id','session_id'):
                    require(external[key]==getattr(receipt.identity,key),'identity mapping differs: '+key)
                require(external['unit_id']==block['unit_id'],'unit mapping differs')
                if sampling.session_mode=='fresh_owned_process':
                    require(receipt.identity.session_id not in fresh_sessions,'fresh owned session reused across pilot/evaluation')
                    fresh_sessions.add(receipt.identity.session_id)
                else:
                    reset=receipt.sampling.reset_evidence
                    require(reset is not None and reset.path==reset_path and
                        reset.sha256==independence['evidence']['sha256']==sampling.reset_evidence_sha256,
                        'reset evidence mapping differs from frozen research evidence')
                require(external['started_utc_ns']==utc_ns(receipt.started_utc) and external['ended_utc_ns']==utc_ns(receipt.completed_utc),'chronology mapping differs')
                require(equal(external['paid_ns'],{o.key:o.value for o in receipt.instrumentation.paid}) and
                    type(external['total_paid_ns']) is int and external['total_paid_ns']==receipt.instrumentation.total_paid_ns,'paid metric mapping differs')
                require(equal(external['resources'],{o.key:o.value for o in receipt.instrumentation.resources}),'resource metric mapping differs')
                identities=dict(receipt.identity.files)
                for key in ('compiler','toolchain','environment'):
                    require(external['fingerprints'][key]==identities[key].sha256,'toolchain identity mapping differs')
                require(external['fingerprints']['artifact']==identities['executable'].sha256,'executable identity mapping differs')
                semantic=external['semantic']
                require(semantic['status']=='complete' and type(semantic['expected_cases']) is int and semantic['expected_cases']==1 and type(semantic['completed_cases']) is int and semantic['completed_cases']==1,'semantic case mapping differs')
                for key,expected_path in (('state',receipt.state.observed_manifest),('events',receipt.state.events.path),('stdout',receipt.state.stdout.path)):
                    require(c.ref(semantic[key])==expected_path,'semantic '+key+' mapping differs')
                state=verify_state(receipt.state.observed_manifest,limits)
                require(state.metadata.status=='success','incomplete invocation cannot map to successful evaluator case')
                chronology_ids={key:getattr(experiment.spec,key) for key in ('objective_sha256','selector_sha256','compiler_sha256','baseline_sha256','candidate_sha256')}
                chronological.append(Receipt(role,receipt.stratum_sha256,receipt.started_utc,receipt.completed_utc,**chronology_ids,baseline_aa=role=='pilot'))
    require(used==set(bindings),'unmapped measurement sidecar')
    if profile==PROFILES[1]:
        selected_ns=selection['selected_utc_ns']
        selected=datetime.fromtimestamp(selected_ns//10**9,timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        require(selected_ns%10**9==0,'selection chronology requires whole-second timestamp')
        chronological.append(Receipt('selection',workload.stratum_sha256,selected,selected,**chronology_ids))
        chronology=validate_chronology(experiment,tuple(chronological))
        require(chronology.eligible,'experiment chronology: '+'; '.join(chronology.reasons))
    # Run pinned pure analytical validation with our stricter closure reader.
    module=types.ModuleType('_axiom_pinned_evaluator')
    module.__file__=str(evaluator)
    # Execute exactly the bytes whose pins were checked, without reopening code.
    exec(compile(evaluator_bytes,str(evaluator),'exec'),module.__dict__)
    class Reader:
        def bytes(self,reference): return c.read(c.ref(reference),reference['sha256'])
        def json(self,reference): return c.json(reference)
    result=module.evaluate(Reader(),envelope['request'],time.time_ns())
    require(result['evidence_kind']=='synthetic_validation' and not result['automatic_adoption'],'unexpected evaluator provenance')
    version=subprocess.run([str(python),'--version'],capture_output=True,text=True,check=True,env=environment(),cwd='/').stdout.strip()
    require(version.startswith('Python '),'Python version unavailable')
    return c.finish(),version,profile


def _normalized(closure,root,python,evaluator):
    result=[]
    for record in closure:
        path=record.resolved_path
        name='.tools/python' if path==python else '.tools/evaluate.py' if path==evaluator else path.relative_to(root).as_posix()
        result.append((name,record.sha256,record.byte_length))
    return tuple(sorted(result))


def admit_export(request:Path,experiment:FrozenManifest,python:Path,evaluator:Path,
                 limits:ArtifactLimits=ArtifactLimits()) -> ExportAdmission:
    request=_root(request); python=Path(python).resolve(strict=True); evaluator=_root(evaluator)
    closure,version,profile=_inspect(request,experiment,python,evaluator,limits)
    snapshot=Path(tempfile.mkdtemp(prefix='axiom-export-retained-'))
    try:
        for record in closure:
            name='.tools/python' if record.resolved_path==python else '.tools/evaluate.py' if record.resolved_path==evaluator else record.resolved_path.relative_to(request.parent).as_posix()
            destination=snapshot/name; destination.parent.mkdir(parents=True,exist_ok=True)
            current,raw=_read_file(record.resolved_path.parent,record.resolved_path.name,limits.max_file_bytes,True)
            require((current.sha256,current.byte_length)==(record.sha256,record.byte_length),'evidence changed during snapshot')
            with destination.open('xb') as stream: stream.write(raw)
            destination.chmod(0o555 if name=='.tools/python' else 0o444)
        snapshot_experiment=load_manifest(snapshot/experiment.path.relative_to(request.parent))
        retained,retained_version,retained_profile=_inspect(snapshot/request.name,snapshot_experiment,snapshot/'.tools/python',snapshot/'.tools/evaluate.py',limits)
        require(_normalized(closure,request.parent,python,evaluator)==_normalized(retained,snapshot,snapshot/'.tools/python',snapshot/'.tools/evaluate.py'),'snapshot closure mismatch')
        require(version==retained_version and profile==retained_profile,'snapshot tools/profile mismatch')
        # Read-only storage is a reproducibility convention, not a same-UID sandbox.
        for directory,_,_ in os.walk(snapshot,topdown=False): Path(directory).chmod(0o555)
        return ExportAdmission(request,experiment,python,evaluator,limits,closure,snapshot,version,profile)
    except BaseException:
        shutil.rmtree(snapshot,ignore_errors=True)
        raise


def _revalidate(admission,request,python,evaluator):
    require(type(admission) is ExportAdmission,'ExportAdmission required; local success results are insufficient')
    require(_root(request)==admission.request and Path(python).resolve(strict=True)==admission.python and _root(evaluator)==admission.evaluator,'substituted request/tool admission')
    require(admission.verifier_version==VERIFIER_VERSION,'verifier changed')
    source,version,profile=_inspect(request,admission.experiment,python,evaluator,admission.limits)
    require(source==admission.closure and version==admission.python_version and profile==admission.profile,'fabricated or changed export admission')
    snapshot=_root(admission.snapshot_root)
    require(snapshot!=admission.request.parent,'retained snapshot must be independent')
    retained_experiment=load_manifest(snapshot/admission.experiment.path.relative_to(admission.request.parent))
    retained,rv,rp=_inspect(snapshot/admission.request.name,retained_experiment,snapshot/'.tools/python',snapshot/'.tools/evaluate.py',admission.limits)
    require(_normalized(source,admission.request.parent,admission.python,admission.evaluator)==_normalized(retained,snapshot,snapshot/'.tools/python',snapshot/'.tools/evaluate.py') and rv==version and rp==profile,'retained snapshot changed')


def evaluate(admission:ExportAdmission,request:Path,python:Path,evaluator:Path,output:Path) -> EvaluationRun:
    _revalidate(admission,request,python,evaluator)
    output=_root(output); receipt_path=Path(str(output)+'.axiom-run.json')
    require(not output.exists() and not receipt_path.exists(),'output and run receipt must be new files')
    require(not output.is_relative_to(admission.snapshot_root),'output cannot modify retained evidence')
    argv=[str(admission.snapshot_root/'.tools/python'),str(admission.snapshot_root/'.tools/evaluate.py'),
        'evaluate','--input',str(admission.snapshot_root/request.name),'--output',str(output)]
    process=subprocess.run(argv,capture_output=True,env=environment(),cwd='/',check=False)
    _revalidate(admission,request,python,evaluator)
    from state_artifacts import _decode_json
    result=_decode_json(process.stdout.strip(),admission.limits)
    if process.returncode==0:
        require(output.is_file() and output.read_bytes()==process.stdout,'output differs from evaluator stdout')
        require(result['evidence_kind']=='synthetic_validation' and result['decision']!='eligible_held_out' and result['automatic_adoption'] is False,'native result forbidden')
    python_hash=next(c.sha256 for c in admission.closure if c.resolved_path==admission.python)
    receipt=dict(schema='axiom-evaluation-run-v1',profile=admission.profile,scope='synthetic descriptive infrastructure fixture; no primary endpoint or native claim',
        argv=argv,exit_status=process.returncode,result=result,python_version=admission.python_version,python_sha256=python_hash,
        evaluator_sha256=EVALUATOR_SHA256,evaluator_git_blob=EVALUATOR_GIT_BLOB,verifier_version=VERIFIER_VERSION,
        native_eligible=False,native_reasons=list(NATIVE_UNAVAILABLE),assumptions=list(ASSUMPTIONS),
        closure=[dict(path=p,sha256=s,byte_length=n) for p,s,n in _normalized(admission.closure,admission.request.parent,admission.python,admission.evaluator)],
        stderr=process.stderr.decode('utf-8',errors='replace'))
    with receipt_path.open('xb') as stream: stream.write(canonical_json(receipt))
    return EvaluationRun(process.returncode,result,output,receipt_path,admission.snapshot_root,admission.python_version,python_hash,EVALUATOR_SHA256)
