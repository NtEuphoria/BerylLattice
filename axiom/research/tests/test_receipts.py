"""Synthetic receipt controls never establish native measurement validity."""
from dataclasses import FrozenInstanceError, replace
import hashlib
from pathlib import Path
import struct
import tempfile
import unittest

from experiment_manifest import Workload, freeze_manifest
from state_artifacts import (AcquisitionMetadata, StateMetadata, canonical_json,
    compare_state, verify_state, write_acquisition, write_state)
from tests.test_manifest import digest, spec
from receipt_admission import (COSTS, RESOURCES, FileEvidence, IdentityEvidence,
    Instrumentation, MeasurementReceipt, Observation, SamplingEvidence,
    StateEvidence, SyntheticFixtureOracle, admit_measurement,
    admit_synthetic_fixture, write_fixture_oracle)


class ReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = spec()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.input = (0,1,2,3)
        self.output = (30,)
        self.meta = StateMetadata(digest('semantics'),1,1,
            hashlib.sha256(struct.pack('<4i',*self.input)).hexdigest(),
            hashlib.sha256(struct.pack('<i',0)).hexdigest())
        self.workload = Workload('correctness',1,1,0,self.meta.logical_semantics_sha256,
            self.meta.original_input_sha256,self.meta.initial_output_sha256,
            generator='fixture',generator_version='synthetic-v1')
        self.experiment = freeze_manifest(replace(self.base,
            workloads=self.base.workloads+(self.workload,)),self.root/'experiment')
        observed = write_state(self.input,self.output,self.meta,self.root/'observed')
        expected = write_state(self.input,self.output,self.meta,self.root/'expected')
        self.files = {}
        for key in ('executable','compiler','toolchain','environment','plan','emitted_kernel','events','stdout','diagnostics'):
            self.files[key] = self.file(self.root/'observed'/key,b'' if key in ('events','stdout') else key.encode())
        self.acquire = AcquisitionMetadata(digest('run'),digest('collector'),
            self.files['plan'].sha256,self.files['emitted_kernel'].sha256,self.files['executable'].sha256,
            'synthetic','2026-10-01T08:00:00Z','2026-10-01T08:00:01Z')
        acquisition = write_acquisition(observed,self.acquire)
        expected_events = self.file(self.root/'expected'/'events',b'')
        expected_stdout = self.file(self.root/'expected'/'stdout',b'')
        oracle = write_fixture_oracle(expected,version='independent-literal-fixture-v1',
            events=expected_events,stdout=expected_stdout)
        self.oracle = SyntheticFixtureOracle(expected,oracle,'independent-literal-fixture-v1',
            hashlib.sha256(expected.read_bytes()).hexdigest(),hashlib.sha256(oracle.read_bytes()).hexdigest())
        identities = tuple((key,self.files[key]) for key in ('executable','compiler','toolchain','environment','plan','emitted_kernel'))
        # Match the frozen compiler and candidate identities to retained actual files.
        self.experiment = freeze_manifest(replace(self.experiment.spec,
            compiler_sha256=self.files['compiler'].sha256,candidate_sha256=self.files['executable'].sha256),self.root/'bound-experiment')
        identity = IdentityEvidence('measurement-1','unit-1','session-1',digest('run'),
            'candidate',self.files['toolchain'].sha256,self.files['environment'].sha256,
            ('clang','-O2','kernel.c','-o','kernel'),identities)
        paid = tuple(Observation(k,10,'ns','checked_call','measured',k) for k in COSTS)
        resources = tuple(Observation(k,10,'count' if k=='allocations' else 'ns' if k.endswith('_ns') else 'bytes',
            'build' if k=='build_ns' else 'edit_check' if k=='edit_check_ns' else 'artifact_text_section' if k=='text_bytes' else 'operation',
            'measured',k) for k in RESOURCES)
        diagnostics=tuple(Observation(k,None,'bytes',scope,'unavailable',k) for k,scope in (
            ('process_rss_peak_bytes','process'),('arena_capacity_bytes','plan_arena'),('allocator_peak_bytes','allocator')))
        raw = dict(schema='synthetic-instrument-observations-v1',measurement_id='measurement-1',run_sha256=digest('run'),
            observations={o.raw_key:dict(value=o.value,unit=o.unit,scope=o.scope,status=o.status) for o in paid+resources+diagnostics},
            collector=dict(version='synthetic-collector-v1',sha256=digest('collector')),
            identity=dict(files={key:ref.sha256 for key,ref in identities},compiler_argv=list(identity.compiler_argv),
                unit_id=identity.unit_id,session_id=identity.session_id,artifact_role=identity.artifact_role),
            timer=dict(scope='checked_call',start_ns=100,end_ns=1000),
            phases=['preflight','dispatch','scratch_setup','initialization','copies','kernel','scratch_cleanup'])
        self.raw = raw
        rawfile = self.file(self.root/'observed'/'raw.json',canonical_json(raw))
        instrumentation = Instrumentation('synthetic-collector-v1',digest('collector'),rawfile,
            'checked_call',100,1000,tuple(raw['phases']),paid,80,resources,diagnostics)
        sampling = SamplingEvidence(0,'AB','B','fresh_owned_process',None,
            self.experiment.spec.sampling.sha256,self.experiment.spec.sampling.reset_protocol,
            self.experiment.spec.sampling.warmup,self.experiment.spec.sampling.input_touch,
            self.experiment.spec.sampling.output_initialization)
        sampling = replace(sampling,pair_order=self.experiment.spec.sampling.orders[0])
        self.receipt = MeasurementReceipt(1,'synthetic',self.experiment.sha256,
            self.workload.stratum_sha256,'correctness','2026-10-01T08:00:00Z','2026-10-01T08:00:01Z',
            self.experiment.spec.objective_sha256,self.experiment.spec.selector_sha256,
            identity,StateEvidence(observed,acquisition,expected,oracle,self.files['events'],self.files['stdout'],self.files['diagnostics']),
            instrumentation,sampling)

    def file(self,path,data):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(data)
        return FileEvidence(path,hashlib.sha256(data).hexdigest())

    def admit(self,receipt=None,oracle=None):
        return admit_synthetic_fixture(receipt or self.receipt,self.experiment,fixture_oracle=oracle or self.oracle)

    def rejected(self,receipt,contains):
        result=self.admit(receipt)
        self.assertFalse(result.synthetic_eligible,result)
        self.assertIn(contains,' '.join(result.reasons))

    def test_synthetic_fixture_full_state_pass_is_never_native(self):
        result=self.admit()
        self.assertTrue(result.synthetic_eligible,result.reasons)
        self.assertFalse(result.eligible)
        self.assertEqual(result.provenance,'synthetic')
        self.assertTrue(result.state_verified)
        self.assertFalse(result.instrumentation_validated)
        self.assertIn('collector',' '.join(result.assumptions))
        self.assertTrue(result.native_reasons)
        ordinary=admit_measurement(self.receipt,self.experiment)
        self.assertFalse(ordinary.eligible)
        self.assertFalse(ordinary.synthetic_eligible)

    def test_no_native_field_or_claimed_collector_version_opens_gate(self):
        receipt=replace(self.receipt,provenance='native_observed',instrumentation=replace(
            self.receipt.instrumentation,collector_version='approved-native-v999'))
        result=admit_measurement(receipt,self.experiment)
        self.assertFalse(result.eligible)
        self.assertIn('collector',' '.join(result.native_reasons))
        self.assertIn('oracle',' '.join(result.native_reasons))
        self.assertIn('buffer',' '.join(result.native_reasons))
        record=self.receipt.to_record(); record['native_enabled']=True
        with self.assertRaises(ValueError): MeasurementReceipt.from_record(record)

    def test_missing_and_unavailable_resources_and_fake_zero_rejected(self):
        instrument=self.receipt.instrumentation
        self.rejected(replace(self.receipt,instrumentation=replace(instrument,resources=instrument.resources[:-1])),'resources')
        for item in (replace(instrument.resources[0],value=None,status='unavailable'),
                     replace(instrument.resources[0],value=0,status='unavailable'),
                     replace(instrument.resources[0],value=0,status='measured')):
            resources=(item,)+instrument.resources[1:]
            self.rejected(replace(self.receipt,instrumentation=replace(instrument,resources=resources)),'resource')

    def test_whole_process_timer_and_missing_operation_costs_rejected(self):
        instrument=self.receipt.instrumentation
        self.rejected(replace(self.receipt,instrumentation=replace(instrument,timer_scope='process')),'checked_call')
        for phase in ('preflight','initialization','copies','scratch_cleanup'):
            self.rejected(replace(self.receipt,instrumentation=replace(instrument,
                included_phases=tuple(p for p in instrument.included_phases if p!=phase))),'phase')
        self.rejected(replace(self.receipt,instrumentation=replace(instrument,paid=instrument.paid[1:])),'paid')
        self.rejected(replace(self.receipt,instrumentation=replace(instrument,total_paid_ns=79)),'total')

    def test_stale_executable_and_compiler_and_frozen_identity_rejected(self):
        self.files['executable'].path.write_bytes(b'changed executable')
        self.rejected(self.receipt,'identity')
        self.files['executable'].path.write_bytes(b'executable')
        self.rejected(replace(self.receipt,objective_sha256=digest('other')),'objective')
        refs=tuple((k,replace(v,sha256=digest('other')) if k=='compiler' else v) for k,v in self.receipt.identity.files)
        self.rejected(replace(self.receipt,identity=replace(self.receipt.identity,files=refs)),'identity')

    def test_same_wrong_complete_output_is_rejected_by_independent_oracle(self):
        wrong=write_state(self.input,(99,),self.meta,self.root/'wrong')
        wrong_pair=write_state(self.input,(99,),self.meta,self.root/'wrong-pair')
        self.assertTrue(compare_state(verify_state(wrong),verify_state(wrong_pair)).equal)
        acquisition=write_acquisition(wrong,self.acquire)
        states=replace(self.receipt.state,observed_manifest=wrong,acquisition=acquisition)
        self.rejected(replace(self.receipt,state=states),'state bytes differ')

    def test_post_call_input_must_be_observed_and_match_independent_expected(self):
        changed=write_state((9,1,2,3),self.output,self.meta,self.root/'changed-input')
        acquisition=write_acquisition(changed,self.acquire)
        self.rejected(replace(self.receipt,state=replace(self.receipt.state,
            observed_manifest=changed,acquisition=acquisition)),'input_after')
        self.rejected(replace(self.receipt,state=replace(self.receipt.state,
            observed_manifest=self.receipt.state.expected_manifest)),'acquisition')

    def test_independent_fixture_cannot_redefine_input_preservation(self):
        actual=write_state((9,1,2,3),self.output,self.meta,self.root/'same-wrong-input-actual')
        expected=write_state((9,1,2,3),self.output,self.meta,self.root/'same-wrong-input-expected')
        acquisition=write_acquisition(actual,self.acquire)
        events=self.file(expected.parent/'events',b'')
        stdout=self.file(expected.parent/'stdout',b'')
        sidecar=write_fixture_oracle(expected,version='literal-v1',events=events,stdout=stdout)
        oracle=SyntheticFixtureOracle(expected,sidecar,'literal-v1',
            hashlib.sha256(expected.read_bytes()).hexdigest(),hashlib.sha256(sidecar.read_bytes()).hexdigest())
        receipt=replace(self.receipt,state=replace(self.receipt.state,observed_manifest=actual,
            acquisition=acquisition,expected_manifest=expected,oracle=sidecar))
        result=self.admit(receipt,oracle)
        self.assertFalse(result.synthetic_eligible)
        self.assertIn('input preservation',' '.join(result.reasons))

    def test_incomplete_output_and_input_coverage_rejected(self):
        path=self.receipt.state.observed_manifest
        import json
        original=path.read_bytes()
        for role in ('input_after','output'):
            record=json.loads(original)
            record['chunks']=[chunk for chunk in record['chunks'] if chunk['role']!=role]
            path.write_bytes(canonical_json(record))
            self.rejected(self.receipt,'state')
        path.write_bytes(original)

    def test_wrong_semantics_status_and_first_failure_rejected(self):
        for metadata in (replace(self.meta,logical_semantics_sha256=digest('other')),
                         replace(self.meta,status='input_precondition_failed',first_bad_index=0)):
            path=write_state(self.input,self.output,metadata,self.root/digest(str(metadata)))
            acquisition=write_acquisition(path,self.acquire)
            self.rejected(replace(self.receipt,state=replace(self.receipt.state,
                observed_manifest=path,acquisition=acquisition)),'semantic')

    def test_oracle_receipt_cannot_replace_trusted_fixture_expected(self):
        wrong=write_state(self.input,(99,),self.meta,self.root/'wrong-oracle')
        self.rejected(replace(self.receipt,state=replace(self.receipt.state,expected_manifest=wrong)),'oracle')
        self.receipt.state.oracle.write_bytes(b'{}')
        self.rejected(self.receipt,'oracle')

    def test_run_and_acquisition_and_sampling_binding_rejected(self):
        self.rejected(replace(self.receipt,identity=replace(self.receipt.identity,run_sha256=digest('other'))),'run')
        self.rejected(replace(self.receipt,sampling=replace(self.receipt.sampling,schedule_sha256=digest('other'))),'sampling')
        self.rejected(replace(self.receipt,sampling=replace(self.receipt.sampling,pair_order='BA' if self.receipt.sampling.pair_order=='AB' else 'AB')),'sampling')
        self.rejected(replace(self.receipt,started_utc='2026-10-01T03:00:00Z'),'chronology')

    def test_semantic_stdout_events_and_instrumentation_diagnostics_are_separate(self):
        self.assertTrue(self.admit().synthetic_eligible)
        self.files['events'].path.write_bytes(b'Core internal trace offsets')
        self.rejected(self.receipt,'semantic')

    def test_raw_retained_observations_required_and_cannot_be_scalar_claims(self):
        self.receipt.instrumentation.raw.path.write_bytes(b'{}')
        self.rejected(self.receipt,'raw')

    def test_consistently_replaced_expected_and_sidecar_cannot_change_trusted_oracle(self):
        import json
        path=self.receipt.state.expected_manifest
        original=json.loads(path.read_bytes())
        # Rewrite the retained expected scalar and both manifest/chunk identities.
        chunk=next(c for c in original['chunks'] if c['role']=='output')
        raw=struct.pack('<i',99)
        (path.parent/chunk['path']).write_bytes(raw)
        chunk['sha256']=hashlib.sha256(raw).hexdigest()
        path.write_bytes(canonical_json(original))
        oracle=json.loads(self.receipt.state.oracle.read_bytes())
        oracle['expected_manifest_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        self.receipt.state.oracle.write_bytes(canonical_json(oracle))
        wrong=write_state(self.input,(99,),self.meta,self.root/'all-wrong')
        acquisition=write_acquisition(wrong,self.acquire)
        self.rejected(replace(self.receipt,state=replace(self.receipt.state,
            observed_manifest=wrong,acquisition=acquisition)),'oracle')

    def test_diagnostic_quantities_are_explicit_distinct_and_nullable(self):
        required=('process_rss_peak_bytes','arena_capacity_bytes','allocator_peak_bytes')
        result=self.admit()
        self.assertTrue(result.synthetic_eligible,result.reasons)
        diagnostics=self.receipt.instrumentation.diagnostics
        self.assertEqual(tuple(o.key for o in diagnostics),required)
        self.assertTrue(all(o.value is None and o.status=='unavailable' for o in diagnostics))
        instrument=replace(self.receipt.instrumentation,diagnostics=())
        self.rejected(replace(self.receipt,instrumentation=instrument),'diagnostic')

    def test_scalar_and_raw_claims_are_bound_to_collector_and_artifact_run(self):
        instrument=replace(self.receipt.instrumentation,collector_sha256=digest('other'))
        self.rejected(replace(self.receipt,instrumentation=instrument),'collector')
        identity=replace(self.receipt.identity,compiler_argv=('other-compiler','-O0'))
        self.rejected(replace(self.receipt,identity=identity),'raw')

    def test_future_acquisition_is_not_a_completed_measurement(self):
        started='2099-10-01T08:00:00Z'
        completed='2099-10-01T08:00:01Z'
        acquisition=write_acquisition(self.receipt.state.observed_manifest,
            replace(self.acquire,started_utc=started,completed_utc=completed),name='future-acquisition.json')
        self.rejected(replace(self.receipt,started_utc=started,completed_utc=completed,
            state=replace(self.receipt.state,acquisition=acquisition)),'chronology')

    def test_pair_position_and_session_are_bound_to_artifact_and_raw_run(self):
        self.rejected(replace(self.receipt,sampling=replace(self.receipt.sampling,position='A')),'sampling')
        self.rejected(replace(self.receipt,identity=replace(self.receipt.identity,session_id='another-session')),'raw')

    def test_raw_boolean_cannot_equal_measured_integer(self):
        instrument=self.receipt.instrumentation
        target=instrument.resources[-1]
        changed=replace(target,value=1)
        raw=dict(self.raw)
        raw['observations']=dict(raw['observations'])
        raw['observations'][target.raw_key]=dict(value=True,unit=target.unit,scope=target.scope,status='measured')
        reference=self.file(self.root/'observed'/'boolean-raw.json',canonical_json(raw))
        receipt=replace(self.receipt,instrumentation=replace(instrument,raw=reference,
            resources=instrument.resources[:-1]+(changed,)))
        self.rejected(receipt,'raw')

    def test_reusing_one_raw_observation_cannot_double_count_paid_costs(self):
        instrument=self.receipt.instrumentation
        paid=(instrument.paid[0],replace(instrument.paid[1],raw_key=instrument.paid[0].raw_key))+instrument.paid[2:]
        self.rejected(replace(self.receipt,instrumentation=replace(instrument,paid=paid)),'raw')

    def test_verified_measured_zero_is_distinct_from_unavailable(self):
        instrument=self.receipt.instrumentation
        target=instrument.resources[-1]
        changed=replace(target,value=0)
        raw=dict(self.raw)
        raw['observations']=dict(raw['observations'])
        raw['observations'][target.raw_key]=dict(value=0,unit=target.unit,scope=target.scope,status='measured')
        reference=self.file(self.root/'observed'/'zero-raw.json',canonical_json(raw))
        receipt=replace(self.receipt,instrumentation=replace(instrument,raw=reference,
            resources=instrument.resources[:-1]+(changed,)))
        self.assertTrue(self.admit(receipt).synthetic_eligible)

    def test_combined_closure_and_expanded_state_limits_include_both_sides(self):
        from state_artifacts import ArtifactLimits
        admission=self.admit()
        self.assertTrue(admission.synthetic_eligible)
        byte_count=sum(record.byte_length for record in admission.closure)
        for limits in (ArtifactLimits(max_aggregate_bytes=byte_count-1),
                       ArtifactLimits(max_logical_bytes=39),
                       ArtifactLimits(max_files=len(admission.closure)-1)):
            result=admit_synthetic_fixture(self.receipt,self.experiment,
                fixture_oracle=self.oracle,limits=limits)
            self.assertFalse(result.synthetic_eligible)

    def test_observation_reasons_reject_mutable_and_nonstring_values_for_all_variants(self):
        variants=(('paid',0,'measured'),('paid',0,'inapplicable'),
                  ('resources',0,'measured'),('diagnostics',0,'unavailable'),
                  ('diagnostics',0,'measured'))
        for group,index,status in variants:
            for reason in (['mutable'],True,{'mutable':'reason'}):
                with self.subTest(group=group,status=status,reason=reason):
                    record=self.receipt.to_record()
                    item=record['instrumentation'][group][index]
                    item['status']=status
                    item['reason']=reason
                    if status=='inapplicable': item['value']=0
                    if status=='measured' and item['value'] is None: item['value']=0
                    with self.assertRaisesRegex(ValueError,'reason'):
                        MeasurementReceipt.from_record(record)
                    original=getattr(self.receipt.instrumentation,group)[index]
                    with self.assertRaisesRegex(ValueError,'reason'):
                        replace(original,status=status,reason=reason)

    def test_string_observation_reasons_roundtrip_and_preserve_synthetic_admission(self):
        record=self.receipt.to_record()
        for group in ('paid','resources','diagnostics'):
            for observation in record['instrumentation'][group]:
                observation['reason']='explicit string explanation'
        parsed=MeasurementReceipt.from_record(record)
        self.assertEqual(parsed.to_record(),record)
        self.assertTrue(self.admit(parsed).synthetic_eligible)
        # Inapplicable cost reasons and measured diagnostic reasons also stay strings.
        cost=replace(parsed.instrumentation.paid[0],status='inapplicable',value=0,
            reason='this declared operation does not pay this component')
        diagnostic=replace(parsed.instrumentation.diagnostics[0],status='measured',value=0,
            reason='retained measured zero')
        variants=replace(parsed,instrumentation=replace(parsed.instrumentation,
            paid=(cost,)+parsed.instrumentation.paid[1:],
            diagnostics=(diagnostic,)+parsed.instrumentation.diagnostics[1:]))
        self.assertEqual(MeasurementReceipt.from_record(variants.to_record()),variants)

    def test_receipt_and_admission_are_immutable_and_roundtrip_strictly(self):
        self.assertEqual(MeasurementReceipt.from_record(self.receipt.to_record()),self.receipt)
        with self.assertRaises(FrozenInstanceError): self.receipt.provenance='native_observed'
        result=self.admit()
        with self.assertRaises(FrozenInstanceError): result.eligible=True
        with self.assertRaises(ValueError): replace(self.receipt.identity,files=list(self.receipt.identity.files))


if __name__=='__main__': unittest.main()
