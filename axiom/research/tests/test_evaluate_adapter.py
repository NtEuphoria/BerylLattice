"""Synthetic adapter machinery; these are not primary-workload measurements."""
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import types
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

from state_artifacts import ArtifactLimits, StateMetadata, canonical_json, write_acquisition, write_state
from experiment_manifest import freeze_manifest
from receipt_admission import FileEvidence, SyntheticFixtureOracle, write_fixture_oracle
from tests import test_receipts as receipt_tests
import evaluate_adapter as adapter

EVALUATOR = Path('/workspace/beryl/tools/beryl-experiments/evaluate.py')
PYTHON = Path('/usr/bin/python3').resolve()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ns(value):
    d = datetime.fromisoformat(value.replace('Z','+00:00'))
    delta = d - datetime(1970,1,1,tzinfo=timezone.utc)
    return (delta.days*86400+delta.seconds)*10**9+delta.microseconds*1000


class Fixture:
    def __init__(self, case, held_out=False, wrong_output=False):
        # Existing literal fixture author independently selects expected state.
        source=receipt_tests.ReceiptTests(); source.setUpClass(); source.setUp()
        case.addCleanup(source.doCleanups)
        self.root=source.root
        self.source=source
        self.held_out=held_out
        self.wrong_output=wrong_output
        if held_out: self.held_fixture()
        baseline=source.file(self.root/'baseline',b'baseline')
        self.experiment=freeze_manifest(replace(source.experiment.spec,
            baseline_sha256=baseline.sha256),self.root/'export-experiment')
        self.bindings=[]
        self.semantic=self.ref('semantic-contract',b'axiom-export-v1: literal synthetic correctness only')
        workload=self.ref('workload.json',source.workload.to_record())
        identity=dict(source.receipt.identity.files)
        self.fingerprints={key:self.refpath(ref.path) for key,ref in (
            ('baseline',baseline),('compiler',identity['compiler']),('toolchain',identity['toolchain']),
            ('environment',identity['environment']))}
        self.fingerprints.update(workload=workload,semantic_contract=self.semantic)
        self.proof=self.ref('independence.txt',b'Synthetic fixture author assertions only; no collector execution.')
        self.pilot={'schema_version':1,'kind':'beryl.performance.pilot','experiment_id':'synthetic-correctness',
            'evidence_kind':'synthetic_validation','resource_policy':'resource_adequate_exact',
            'metric':'median_paired_total_paid_ns','population':{'sampling':'independent_identically_distributed',
            'description':'Synthetic adapter machinery; no population sampled.'},'fingerprints':self.fingerprints,
            'budgets':dict(peak_bytes=100,retained_bytes=100,allocations=100,text_growth_ppm=200000,build_ratio_ppm=2000000,edit_check_growth_ppm=100000),
            'blocks':self.blocks('pilot',5 if held_out else 8,baseline)}
        self.pilot_ref=self.ref('pilot.json',self.pilot)
        # Historical analytical freeze is synthetic input, not a backdated CLI run.
        ev=types.ModuleType('pinned_fixture_evaluator'); ev.__file__=str(EVALUATOR)
        exec(compile(EVALUATOR.read_bytes(),str(EVALUATOR),'exec'),ev.__dict__)
        self.ev=ev
        seal=ev.freeze(ev.Reader(self.root),self.pilot_ref,ns('2026-10-01T06:00:00Z' if held_out else '2026-10-01T09:00:00Z'))
        freeze=self.ref('freeze.json',seal)
        candidate=self.refpath(identity['executable'].path)
        selection=self.ref('selection.json',dict(schema_version=1,kind='beryl.performance.selection',status='frozen',
            candidate_sha256=candidate['sha256'],selected_utc_ns=ns('2026-10-01T07:00:00Z' if held_out else '2026-10-01T09:01:00Z'),prior_workload_sha256=[],evidence=self.proof))
        self.request=self.root/'request.json'
        self.request_record=dict(schema_version=1,kind='beryl.performance.evaluation',freeze=freeze,
            candidate=candidate,selection=selection,role='held_out' if held_out else 'selection',blocks=self.blocks('evaluation',10,baseline))
        self.ref('request.json',self.request_record)
        oracle=source.oracle
        self.envelope=dict(schema='axiom-export-v1',profile='synthetic_descriptive_held_out_fixture' if held_out else 'synthetic_correctness_fixture',verifier_version=adapter.VERIFIER_VERSION,
            request=self.refpath(self.request),experiment=self.refpath(self.experiment.path),semantic_contract=self.semantic,
            oracle=dict(expected_manifest=self.refpath(oracle.expected_manifest),sidecar=self.refpath(oracle.sidecar),version=oracle.version),
            python_sha256=sha(PYTHON),evaluator_sha256=adapter.EVALUATOR_SHA256,
            measurements=self.bindings)
        self.envelope_path=Path(str(self.request)+'.axiom-export.json')
        self.save_envelope()

    def held_fixture(self):
        """Independently authored test-only expected values, not a source oracle API."""
        s=self.source
        workload=next(w for w in s.experiment.spec.workloads if (w.W,w.H,w.seed,w.role)==(8191,1,65537,'held_out'))
        value=workload.seed; inputs=[]
        for _ in range((workload.H+1)*(workload.W+1)):
            value=(value*6364136223846793005+1442695040888963407)&((1<<64)-1)
            inputs.append((value>>32)&1023)
        # Explicit four-neighbor arithmetic over the literal fixture's two rows.
        expected=[sum((inputs[j]+1)**2 for j in (c,c+1,8192+c,8193+c)) for c in range(8191)]
        initial=hashlib.sha256(bytes(4*8191)).hexdigest()
        workload=replace(workload,initial_output_sha256=initial)
        s.workload=workload
        s.meta=StateMetadata(workload.logical_semantics_sha256,1,8191,workload.input_sha256,initial)
        observed=write_state(inputs,[0]*8191 if self.wrong_output else expected,s.meta,self.root/'held-observed')
        expected_manifest=write_state(inputs,expected,s.meta,self.root/'held-expected')
        events=s.file(expected_manifest.parent/'events',b''); stdout=s.file(expected_manifest.parent/'stdout',b'')
        sidecar=write_fixture_oracle(expected_manifest,version='independent-literal-fixture-v1',events=events,stdout=stdout)
        s.oracle=SyntheticFixtureOracle(expected_manifest,sidecar,'independent-literal-fixture-v1',sha(expected_manifest),sha(sidecar))
        rows=tuple(workload if (w.W,w.H,w.seed,w.role)==(8191,1,65537,'held_out') else w for w in s.experiment.spec.workloads)
        s.experiment=freeze_manifest(replace(s.experiment.spec,workloads=rows+(replace(workload,role='pilot'),)),self.root/'held-experiment')
        s.receipt=replace(s.receipt,stratum_sha256=workload.stratum_sha256,
            state=replace(s.receipt.state,observed_manifest=observed,expected_manifest=expected_manifest,oracle=sidecar))

    def ref(self,name,value):
        path=self.root/name; path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(value if isinstance(value,bytes) else canonical_json(value))
        return self.refpath(path)

    def refpath(self,path):
        return dict(path=path.relative_to(self.root).as_posix(),sha256=sha(path))

    def save_envelope(self):
        self.envelope_path.write_bytes(canonical_json(self.envelope))

    def remap_sampling(self, mode, method, *, reuse=False, cross_stage_reuse=False, evidence_override=None):
        """Rewrite every affected identity/hash, preserving a valid evaluator freeze."""
        sampling=self.experiment.spec.sampling
        reset=self.ref('approved-reset.txt',b'Synthetic fixture reset contract; authors assert restored owned input/output and independent sampling.') if mode=='reset_contract' else None
        if reset is not None:
            sampling=replace(sampling,session_mode=mode,reset_evidence_sha256=reset['sha256'],
                reset_protocol='Fixture reset restores input/output and independence before each sample.')
        self.experiment=freeze_manifest(replace(self.experiment.spec,sampling=sampling),self.root/'remapped-experiment')
        self.envelope['experiment']=self.refpath(self.experiment.path)
        first_session=None
        for binding in self.bindings:
            record=json.loads((self.root/binding['receipt']['path']).read_bytes())
            identity=record['identity']
            if first_session is None: first_session=identity['session_id']
            if reuse or (cross_stage_reuse and identity['measurement_id']=='evaluation-0-a'):
                identity['session_id']='reused-session' if reuse else first_session
                raw_path=record['instrumentation']['raw']['path']
                raw=json.loads((self.root/raw_path).read_bytes()); raw['identity']['session_id']=identity['session_id']
                record['instrumentation']['raw']=self.ref(raw_path,raw)
            record['experiment_sha256']=self.experiment.sha256
            record['sampling'].update(session_mode=mode,reset_evidence=reset,schedule_sha256=sampling.sha256,
                reset_protocol=sampling.reset_protocol)
            binding['receipt'].update(self.ref(binding['receipt']['path'],record))
            measured=json.loads((self.root/binding['measurement']['path']).read_bytes())
            measured['session_id']=identity['session_id']
            binding['measurement'].update(self.ref(binding['measurement']['path'],measured))
        for blocks in (self.pilot['blocks'],self.request_record['blocks']):
            for block in blocks:
                record=json.loads((self.root/block['independence']['path']).read_bytes())
                record['method']=method
                record['evidence']=evidence_override or reset or self.proof
                block['independence'].update(self.ref(block['independence']['path'],record))
        self.pilot_ref.update(self.ref('pilot.json',self.pilot))
        seal=self.ev.freeze(self.ev.Reader(self.root),self.pilot_ref,ns('2026-10-01T06:00:00Z' if self.held_out else '2026-10-01T09:00:00Z'))
        self.request_record['freeze']=self.ref('freeze.json',seal)
        self.envelope['request']=self.ref('request.json',self.request_record)
        self.save_envelope()

    def blocks(self,stage,hour,baseline):
        blocks=[]; s=self.source; original=s.receipt
        for index,order in enumerate(self.experiment.spec.sampling.orders):
            unit=f'{stage}-{index}'; block=dict(unit_id=unit,first=order[0].lower())
            for side in ('a','b'):
                mid=unit+'-'+side
                start=f'2026-10-01T{hour:02}:{index:02}:{0 if side==order[0].lower() else 2:02}Z'
                end=f'2026-10-01T{hour:02}:{index:02}:{1 if side==order[0].lower() else 3:02}Z'
                base=stage=='pilot' or side=='a'
                files=tuple((k,baseline if k=='executable' and base else v) for k,v in original.identity.files)
                identity=replace(original.identity,measurement_id=mid,unit_id=unit,session_id=mid+'-session',
                    run_sha256=hashlib.sha256(mid.encode()).hexdigest(),artifact_role='baseline' if base else 'candidate',files=files)
                acquire=replace(s.acquire,run_sha256=identity.run_sha256,binary_sha256=dict(files)['executable'].sha256,
                    started_utc=start,completed_utc=end)
                acquisition=write_acquisition(original.state.observed_manifest,acquire,name=mid+'-acquisition.json')
                paid=tuple(replace(o,value=10 if base else 8) for o in original.instrumentation.paid)
                raw=dict(s.raw,measurement_id=mid,run_sha256=identity.run_sha256,
                    identity=dict(files={k:v.sha256 for k,v in files},compiler_argv=list(identity.compiler_argv),unit_id=unit,
                        session_id=identity.session_id,artifact_role=identity.artifact_role))
                raw['observations']=dict(raw['observations'])
                for o in paid: raw['observations'][o.raw_key]=dict(value=o.value,unit=o.unit,scope=o.scope,status=o.status)
                rawref=self.ref('raw/'+mid+'.json',raw)
                instrument=replace(original.instrumentation,paid=paid,total_paid_ns=sum(o.value for o in paid),
                    raw=FileEvidence(self.root/rawref['path'],rawref['sha256']))
                receipt=replace(original,experiment_sha256=self.experiment.sha256,identity=identity,instrumentation=instrument,
                    started_utc=start,completed_utc=end,role=('pilot' if stage=='pilot' else 'held_out') if self.held_out else 'correctness',
                    state=replace(original.state,acquisition=acquisition),
                    sampling=replace(original.sampling,sample_index=index,pair_order=order,position=side.upper() if self.held_out else 'A' if base else 'B'))
                record=receipt.to_record()
                def relative(obj):
                    if isinstance(obj,dict): return {k:relative(v) for k,v in obj.items()}
                    if isinstance(obj,list): return [relative(v) for v in obj]
                    if isinstance(obj,str) and obj.startswith(str(self.root)+'/'): return Path(obj).relative_to(self.root).as_posix()
                    return obj
                receipt_ref=self.ref('receipts/'+mid+'.json',relative(record))
                external=dict(schema_version=1,kind='beryl.performance.measurement',measurement_id=mid,unit_id=unit,
                    session_id=identity.session_id,status='complete',started_utc_ns=ns(start),ended_utc_ns=ns(end),
                    fingerprints={**{k:v['sha256'] for k,v in self.fingerprints.items() if k!='baseline'},'artifact':dict(files)['executable'].sha256},
                    paid_ns={o.key:o.value for o in paid},total_paid_ns=instrument.total_paid_ns,
                    resources={o.key:o.value for o in instrument.resources},semantic=dict(status='complete',expected_cases=1,completed_cases=1,
                        state=self.refpath(receipt.state.observed_manifest),events=self.refpath(receipt.state.events.path),stdout=self.refpath(receipt.state.stdout.path)))
                block[side]=self.ref('measurements/'+mid+'.json',external)
                self.bindings.append(dict(measurement=block[side],receipt=receipt_ref))
            block['independence']=self.ref('independence/'+unit+'.json',dict(schema_version=1,kind='beryl.performance.independence',
                status='verified',unit_id=unit,method='separate_owned_sessions',measurement_ids=[unit+'-a',unit+'-b'],evidence=self.proof))
            blocks.append(block)
        return blocks


class AdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Cache the expensive approved LCG workload hashes once.
        receipt_tests.ReceiptTests.setUpClass()

    def setUp(self):
        self.f=Fixture(self)

    def admit(self,limits=ArtifactLimits()):
        result=adapter.admit_export(self.f.request,self.f.experiment,PYTHON,EVALUATOR,limits)
        self.addCleanup(shutil.rmtree,result.snapshot_root,True)
        return result

    def test_frozen_fresh_sessions_cannot_claim_reset_equivalence(self):
        self.f=Fixture(self,held_out=True)
        self.f.remap_sampling('fresh_owned_process','verified_reset_equivalence',reuse=True)
        external=self.f.ev.evaluate(self.f.ev.Reader(self.f.root),self.f.refpath(self.f.request),ns('2026-10-02T00:00:00Z'))
        self.assertEqual(external['decision'],'synthetic_gate_pass')
        with self.assertRaisesRegex(ValueError,'independence method.*frozen'):
            self.admit()

    def test_fresh_session_uniqueness_spans_pilot_and_evaluation(self):
        self.f.remap_sampling('fresh_owned_process','separate_owned_sessions',cross_stage_reuse=True)
        with self.assertRaisesRegex(ValueError,'fresh owned session reused'):
            self.admit()

    def test_reset_contract_requires_exact_frozen_research_evidence(self):
        self.f=Fixture(self,held_out=True)
        substitute=self.f.ref('unapproved-reset.txt',b'An unrelated synthetic reset assertion.')
        self.f.remap_sampling('reset_contract','verified_reset_equivalence',reuse=True,evidence_override=substitute)
        external=self.f.ev.evaluate(self.f.ev.Reader(self.f.root),self.f.refpath(self.f.request),ns('2026-10-02T00:00:00Z'))
        self.assertEqual(external['decision'],'synthetic_gate_pass')
        with self.assertRaisesRegex(ValueError,'reset evidence mapping'):
            self.admit()

    def test_approved_reset_contract_maps_and_preserves_synthetic_gate(self):
        self.f=Fixture(self,held_out=True)
        self.f.remap_sampling('reset_contract','verified_reset_equivalence',reuse=True)
        admission=self.admit()
        run=adapter.evaluate(admission,self.f.request,PYTHON,EVALUATOR,self.f.root/'reset-result.json')
        self.assertEqual(run.result['decision'],'synthetic_gate_pass')
        self.assertFalse(run.native_eligible)
        reset=next(c for c in admission.closure if c.resolved_path==self.f.root/'approved-reset.txt')
        self.assertEqual(reset.sha256,self.f.experiment.spec.sampling.reset_evidence_sha256)

    def test_synthetic_correctness_roundtrip_retains_external_selection_only(self):
        admission=self.admit()
        output=self.f.root/'result.json'
        run=adapter.evaluate(admission,self.f.request,PYTHON,EVALUATOR,output)
        self.assertEqual(run.exit_status,0)
        self.assertEqual(run.result['decision'],'selection_only')
        self.assertEqual(run.result['evidence_kind'],'synthetic_validation')
        self.assertFalse(run.native_eligible)
        self.assertFalse(run.result['automatic_adoption'])
        self.assertEqual(run.python_sha256,sha(PYTHON))
        self.assertTrue(run.python_version.startswith('Python '))
        self.assertEqual(run.evaluator_sha256,adapter.EVALUATOR_SHA256)
        self.assertTrue(run.receipt_path.is_file())
        self.assertTrue((admission.snapshot_root/'request.json').is_file())
        self.assertEqual(json.loads(output.read_bytes()),run.result)

    def test_approved_small_held_out_fixture_is_descriptive_synthetic_gate_pass(self):
        self.f=Fixture(self,held_out=True)
        admission=self.admit()
        run=adapter.evaluate(admission,self.f.request,PYTHON,EVALUATOR,self.f.root/'held-result.json')
        self.assertEqual(run.result['decision'],'synthetic_gate_pass')
        self.assertFalse(run.native_eligible)
        self.assertEqual((self.f.experiment.primary_workload.W,self.f.experiment.primary_workload.H),(2047,2049))
        receipt=json.loads(run.receipt_path.read_bytes())
        self.assertIn('descriptive',receipt['scope'])

    def test_same_wrong_output_cannot_replace_independent_held_out_oracle(self):
        self.f=Fixture(self,held_out=True,wrong_output=True)
        # The unchanged external evaluator alone accepts the same wrong pair.
        external=self.f.ev.evaluate(self.f.ev.Reader(self.f.root),self.f.refpath(self.f.request),ns('2026-10-02T00:00:00Z'))
        self.assertEqual(external['decision'],'synthetic_gate_pass')
        with self.assertRaisesRegex(ValueError,'state bytes differ'): self.admit()

    def test_actual_freeze_cli_uses_current_clock_and_new_output(self):
        a=self.admit(); output=self.f.root/'current-freeze.json'
        before=__import__('time').time_ns()
        result=subprocess.run([str(PYTHON),str(EVALUATOR),'freeze','--input',str(self.f.root/'pilot.json'),
            '--output',str(output)],capture_output=True,check=False)
        self.assertEqual(result.returncode,0,result.stdout)
        freeze=json.loads(output.read_bytes())
        self.assertGreaterEqual(freeze['frozen_utc_ns'],before)
        self.assertLessEqual(freeze['frozen_utc_ns'],__import__('time').time_ns())
        self.assertEqual(freeze['threshold'],{'numerator':1,'denominator':20})

    def test_json_cannot_open_native_profile_or_replace_oracle_pin(self):
        self.f.envelope['profile']='native_observed'; self.f.save_envelope()
        with self.assertRaisesRegex(ValueError,'native'): self.admit()
        self.f.envelope['profile']='synthetic_correctness_fixture'
        self.f.envelope['oracle']['expected_manifest']['sha256']='0'*64; self.f.save_envelope()
        with self.assertRaisesRegex(ValueError,'identity'): self.admit()

    def test_held_out_relabel_is_rejected(self):
        self.f.request_record['role']='held_out'
        self.f.ref('request.json',self.f.request_record)
        self.f.envelope['request']=self.f.refpath(self.f.request); self.f.save_envelope()
        with self.assertRaisesRegex(ValueError,'correctness|role'): self.admit()

    def test_request_and_evaluator_mutation_rejected(self):
        a=self.admit(); self.f.request.write_bytes(b'{}')
        with self.assertRaises(ValueError): adapter.evaluate(a,self.f.request,PYTHON,EVALUATOR,self.f.root/'out')
        bad=self.f.root/'bad-evaluator.py'; bad.write_bytes(EVALUATOR.read_bytes()+b'\n')
        with self.assertRaises(ValueError): adapter.admit_export(self.f.request,self.f.experiment,PYTHON,bad,ArtifactLimits())

    def test_indirect_chunk_mutation_is_not_hidden_by_manifest_identity(self):
        a=self.admit(); manifest=self.f.source.receipt.state.observed_manifest
        record=json.loads(manifest.read_bytes()); chunk=manifest.parent/record['chunks'][-1]['path']
        chunk.write_bytes(b'\x00'*chunk.stat().st_size)
        with self.assertRaises(ValueError): adapter.evaluate(a,self.f.request,PYTHON,EVALUATOR,self.f.root/'out')

    def test_fabricated_admission_is_freshly_revalidated(self):
        a=self.admit()
        bad=replace(a,closure=(),python_version='fabricated')
        with self.assertRaises(ValueError): adapter.evaluate(bad,self.f.request,PYTHON,EVALUATOR,self.f.root/'out')
        with self.assertRaises(ValueError): adapter.evaluate(object(),self.f.request,PYTHON,EVALUATOR,self.f.root/'out')

    def test_snapshot_mutation_rejected(self):
        a=self.admit(); path=a.snapshot_root/'request.json'; path.chmod(0o600); path.write_bytes(b'{}')
        with self.assertRaises(ValueError): adapter.evaluate(a,self.f.request,PYTHON,EVALUATOR,self.f.root/'out')

    def test_full_closure_quota_counts_equal_bytes_at_distinct_paths(self):
        a=self.admit()
        total=sum(c.byte_length for c in a.closure)
        for limits in (replace(ArtifactLimits(),max_aggregate_bytes=total-1),
                       replace(ArtifactLimits(),max_files=len(a.closure)-1),
                       replace(ArtifactLimits(),max_logical_bytes=39)):
            with self.subTest(limits=limits):
                with self.assertRaises(ValueError): self.admit(limits)
        same=[c for c in a.closure if c.byte_length>0 and sum(other.sha256==c.sha256 for other in a.closure)>1]
        self.assertGreaterEqual(len(same),2)

    def test_hidden_oversized_indirect_evidence_rejected(self):
        p=self.f.source.receipt.state.diagnostics.path
        p.write_bytes(b'x'*7000001)
        with self.assertRaisesRegex(ValueError,'bounded|limit'): self.admit(replace(ArtifactLimits(),max_file_bytes=7000000))

    def test_threshold_policy_change_rejected(self):
        freeze=self.f.root/'freeze.json'; record=json.loads(freeze.read_bytes()); record['threshold']={'numerator':1,'denominator':100}
        self.f.ref('freeze.json',record); self.f.request_record['freeze']=self.f.refpath(freeze)
        self.f.ref('request.json',self.f.request_record); self.f.envelope['request']=self.f.refpath(self.f.request); self.f.save_envelope()
        with self.assertRaisesRegex(ValueError,'freeze|threshold'): self.admit()

    def test_external_metric_mapping_cannot_diverge_from_raw_receipt(self):
        binding=self.f.bindings[-1]; path=self.f.root/binding['measurement']['path']; record=json.loads(path.read_bytes())
        record['paid_ns']['compute']+=1; record['total_paid_ns']+=1
        self.f.ref(binding['measurement']['path'],record)
        # Even after the author consistently updates all direct references.
        binding['measurement'].update(self.f.refpath(path)); self.f.ref('request.json',self.f.request_record)
        self.f.envelope['request']=self.f.refpath(self.f.request); self.f.save_envelope()
        with self.assertRaisesRegex(ValueError,'mapping'): self.admit()

    def test_exclusive_output_preserves_existing_file(self):
        a=self.admit(); output=self.f.root/'exists'; output.write_bytes(b'keep')
        with self.assertRaises((ValueError,FileExistsError)): adapter.evaluate(a,self.f.request,PYTHON,EVALUATOR,output)
        self.assertEqual(output.read_bytes(),b'keep')

    def test_post_execution_mutation_is_detected(self):
        a=self.admit(); real=subprocess.run
        def mutate(*args,**kwargs):
            result=real(*args,**kwargs)
            if 'evaluate' in args[0]:
                path=a.snapshot_root/'request.json'; path.chmod(0o600); path.write_bytes(b'{}')
            return result
        with patch('evaluate_adapter.subprocess.run',side_effect=mutate):
            with self.assertRaises(ValueError): adapter.evaluate(a,self.f.request,PYTHON,EVALUATOR,self.f.root/'out')


if __name__=='__main__': unittest.main()
