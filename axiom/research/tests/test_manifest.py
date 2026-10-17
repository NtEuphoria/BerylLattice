"""Frozen experiment declarations; synthetic hashes are never native observations."""
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from experiment_manifest import (AccessRecord, ChronologyResult, ExperimentSpec,
    Receipt, SamplingPlan, Workload, TRAINING_SHAPES, HELD_OUT_SHAPES,
    approved_input_sha256, freeze_manifest, load_manifest, validate_chronology)


def digest(label):
    return hashlib.sha256(label.encode()).hexdigest()


def workload(role, W, H, seed, **kw):
    values = dict(role=role, W=W, H=H, seed=seed,
        logical_semantics_sha256=digest('semantics'), input_sha256=approved_input_sha256(W,H,seed),
        initial_output_sha256=digest(f'zeros:{W}:{H}'), generator='lcg64', generator_version='v1',
        cap_bytes=None, entry_contract='ordinary_checked_call', cache_regime='validation_warmed')
    values.update(kw)
    return Workload(**values)


def spec():
    rows = tuple(workload('training',W,H,seed) for W,H in TRAINING_SHAPES for seed in range(1,5))
    rows += tuple(workload('held_out',W,H,seed) for W,H in HELD_OUT_SHAPES for seed in range(65537,65541))
    accesses = tuple(AccessRecord(w,'training','2026-10-01T02:00:00Z') for w in rows if w.role=='training')
    return ExperimentSpec(workloads=rows, known_accesses=accesses, training_history_complete=True, holdout_rule='shape',
        preregistered_utc='2026-10-01T00:00:00Z', selector_design_frozen_utc='2026-10-01T01:00:00Z',
        baseline_selected_utc='2026-10-01T03:00:00Z', candidate_frozen_utc='2026-10-01T04:00:00Z',
        policy_frozen_utc='2026-10-01T06:00:00Z', objective_sha256=digest('objective'),
        selector_sha256=digest('selector'), compiler_sha256=digest('compiler'),
        baseline_sha256=digest('baseline'), candidate_sha256=digest('candidate'),
        sampling=SamplingPlan(32,71,'fresh_owned_process',
            'Independent owned sessions; inspect drift and no shared execution state.',
            'Release owned sessions; restore declared input/output and warmup before every sample.',
            'one untimed checked call','read all input','zero before timing'))


def receipts(s):
    primary=next(w for w in s.workloads if (w.W,w.H,w.seed,w.role)==(2047,2049,65537,'held_out'))
    ids={key:getattr(s,key) for key in ('objective_sha256','selector_sha256','compiler_sha256','baseline_sha256','candidate_sha256')}
    return (Receipt('pilot',primary.stratum_sha256,'2026-10-01T05:00:00Z','2026-10-01T05:30:00Z',**ids,baseline_aa=True),
            Receipt('selection',primary.stratum_sha256,'2026-10-01T07:00:00Z','2026-10-01T07:01:00Z',**ids),
            Receipt('held_out',primary.stratum_sha256,'2026-10-01T08:00:00Z','2026-10-01T08:30:00Z',**ids))


class ManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base=spec()

    def freeze(self,s=None):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return freeze_manifest(s or self.base,Path(tmp.name))

    def test_lcg64_stream_is_little_endian_i32_and_not_a_label_hash(self):
        import struct
        state,values=1,[]
        for _ in range(6):
            state=(state*6364136223846793005+1442695040888963407)&((1<<64)-1)
            values.append((state>>32)&1023)
        self.assertEqual(approved_input_sha256(1,2,1),hashlib.sha256(struct.pack('<6i',*values)).hexdigest())
        with self.assertRaises(ValueError):
            self.freeze(replace(self.base,workloads=(replace(self.base.workloads[0],input_sha256=digest('fake')),)+self.base.workloads[1:]))

    def test_content_identity_survives_renamed_generator_and_cache_labels(self):
        held=self.base.workloads[-1]
        renamed=replace(held,role='selection',generator='renamed-file',generator_version='other',cache_regime='cold')
        self.assertEqual(held.content_sha256,renamed.content_sha256)
        self.assertNotEqual(held.stratum_sha256,renamed.stratum_sha256)
        access=AccessRecord(renamed,'selection','2026-10-01T02:00:00Z')
        with self.assertRaisesRegex(ValueError,'held.out'):
            self.freeze(replace(self.base,known_accesses=self.base.known_accesses+(access,)))

    def test_shape_holdout_cannot_be_evaded_with_different_input_seed(self):
        held=self.base.workloads[-1]
        other=workload('training',held.W,held.H,2,cache_regime='other')
        access=AccessRecord(other,'training','2026-10-01T02:00:00Z')
        with self.assertRaisesRegex(ValueError,'held.out'):
            self.freeze(replace(self.base,known_accesses=self.base.known_accesses+(access,)))
        self.freeze(replace(self.base,holdout_rule='input',known_accesses=self.base.known_accesses+(access,)))

    def test_missing_or_incomplete_training_history_rejected(self):
        for update in (dict(training_history_complete=False),dict(known_accesses=self.base.known_accesses[1:])):
            with self.subTest(update=next(iter(update))):
                with self.assertRaisesRegex(ValueError,'training history'):
                    self.freeze(replace(self.base,**update))

    def test_exact_approved_shapes_and_seeds_required(self):
        variants=(self.base.workloads[:-1],self.base.workloads+(self.base.workloads[0],),
                  (replace(self.base.workloads[0],seed=9,input_sha256=approved_input_sha256(32,32,9)),)+self.base.workloads[1:])
        for rows in variants:
            with self.subTest(size=len(rows)):
                with self.assertRaises(ValueError):
                    self.freeze(replace(self.base,workloads=rows))

    def test_freeze_roundtrip_is_immutable_and_revalidates_disk(self):
        frozen=self.freeze()
        self.assertEqual(frozen,load_manifest(frozen.path))
        self.assertEqual((frozen.primary_workload.W,frozen.primary_workload.H,frozen.primary_workload.seed),(2047,2049,65537))
        self.assertEqual(frozen.threshold_policy,'max(5%,pilot_p95_absolute_paired_variation)')
        with self.assertRaises(FrozenInstanceError):
            frozen.spec.objective_sha256=digest('retuned')
        raw=json.loads(frozen.path.read_text())
        raw['spec']['compiler_sha256']=digest('changed')
        frozen.path.write_text(json.dumps(raw))
        with self.assertRaises(ValueError):
            frozen.revalidate()

    def test_selector_design_must_freeze_before_any_baseline_pilot_exposure(self):
        primary=next(w for w in self.base.workloads if w.role=='held_out')
        pilot=AccessRecord(primary,'pilot','2026-10-01T00:30:00Z',baseline_aa=True)
        with self.assertRaisesRegex(ValueError,'selector design'):
            self.freeze(replace(self.base,known_accesses=self.base.known_accesses+(pilot,)))
        allowed=replace(pilot,accessed_utc='2026-10-01T05:00:00Z')
        self.freeze(replace(self.base,known_accesses=self.base.known_accesses+(allowed,)))
        with self.assertRaises(ValueError):
            self.freeze(replace(self.base,known_accesses=self.base.known_accesses+(replace(allowed,baseline_aa=False),)))

    def test_tuning_and_dataset_ordering_cannot_be_backdated(self):
        for update in (dict(preregistered_utc='2026-10-01T03:00:00Z'),dict(candidate_frozen_utc='2026-10-01T01:30:00Z'),dict(policy_frozen_utc='2026-10-01T03:30:00Z')):
            with self.subTest(update=next(iter(update))):
                with self.assertRaises(ValueError):
                    self.freeze(replace(self.base,**update))

    def test_valid_chronology_and_pinned_objective_selector_compiler(self):
        frozen=self.freeze(); rows=receipts(self.base)
        self.assertEqual(validate_chronology(frozen,rows),ChronologyResult(True,()))
        for field in ('objective_sha256','selector_sha256','compiler_sha256','baseline_sha256','candidate_sha256'):
            with self.subTest(field=field):
                result=validate_chronology(frozen,rows[:-1]+(replace(rows[-1],**{field:digest('retuned')}),))
                self.assertFalse(result.eligible)
                self.assertTrue(any(field in r for r in result.reasons))

    def test_candidate_before_freeze_selection_or_pilot_policy_fails(self):
        frozen=self.freeze(); rows=receipts(self.base)
        variants=(rows[:-1]+(replace(rows[-1],started_utc='2026-10-01T03:30:00Z'),),
                  rows[:-1]+(replace(rows[-1],started_utc='2026-10-01T06:30:00Z'),),
                  (replace(rows[0],started_utc='2026-10-01T00:30:00Z'),)+rows[1:],
                  (replace(rows[0],completed_utc='2026-10-01T06:30:00Z'),)+rows[1:],
                  rows[1:],rows[:1]+rows[2:],(replace(rows[0],baseline_aa=False),)+rows[1:])
        for index,variant in enumerate(variants):
            with self.subTest(variant=index):
                self.assertFalse(validate_chronology(frozen,variant).eligible)

    def test_strata_must_have_separate_pilot_selection_and_receipts(self):
        frozen=self.freeze(); rows=receipts(self.base)
        different=self.base.workloads[-1]
        self.assertFalse(validate_chronology(frozen,rows[:-1]+(replace(rows[-1],stratum_sha256=different.stratum_sha256),)).eligible)
        with self.assertRaises(ValueError):
            replace(rows[-1],stratum_sha256=(rows[-1].stratum_sha256,different.stratum_sha256))

    def test_balanced_reproducible_fixed_sample_schedule_and_session_assumptions(self):
        s=self.base.sampling
        self.assertEqual(s.orders.count('AB'),16); self.assertEqual(s.orders.count('BA'),16)
        self.assertEqual(s.orders,replace(s).orders)
        self.assertNotEqual(s.orders,replace(s,randomization_seed=72).orders)
        for n in (0,29,31,1025,True):
            with self.subTest(n=n):
                with self.assertRaises(ValueError):
                    replace(s,sample_count=n)
        self.assertEqual(len(replace(s,sample_count=30).orders),30)
        self.assertEqual(len(replace(s,sample_count=1024).orders),1024)
        for update in (dict(independence_assumption=''),dict(reset_protocol=''),dict(session_mode='new_pid'),dict(session_mode='reset_contract')):
            with self.subTest(update=update):
                with self.assertRaises(ValueError):
                    replace(s,**update)
        self.assertEqual(replace(s,session_mode='reset_contract',reset_evidence_sha256=digest('reset')).session_mode,'reset_contract')

    def test_strict_loader_rejects_unknown_fields(self):
        frozen=self.freeze(); raw=json.loads(frozen.path.read_text()); raw['surprise']='no'
        from state_artifacts import canonical_json
        frozen.path.write_bytes(canonical_json(raw))
        with self.assertRaises(ValueError):
            load_manifest(frozen.path)

    def test_experiment_record_roundtrip_and_sampling_threshold_tampering(self):
        self.assertEqual(self.base,ExperimentSpec.from_record(self.base.to_record()))
        from state_artifacts import canonical_json
        for field,value in (('threshold_policy','max(1%,pilot_noise)'),('sampling_orders',['AB']*32)):
            with self.subTest(field=field):
                frozen=self.freeze(); record=frozen.to_record(); record[field]=value
                frozen.path.write_bytes(canonical_json(record))
                with self.assertRaises(ValueError):
                    load_manifest(frozen.path)

    def test_auxiliary_timing_roles_do_not_add_unapproved_shape_seed_cells(self):
        extra=workload('pilot',2,2,10)
        with self.assertRaises(ValueError):
            self.freeze(replace(self.base,workloads=self.base.workloads+(extra,)))

    def test_freeze_directory_swap_never_writes_outside_owned_root(self):
        import os
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as base:
            parent=Path(base); root=parent/'manifest'; root.mkdir()
            outside=parent/'outside'; outside.mkdir()
            moved=parent/'moved'; real_open=os.open; swapped=False
            def racing_open(path,flags,*args,**kwargs):
                nonlocal swapped
                if not swapped and flags & os.O_CREAT and Path(path).name.startswith('experiment-'):
                    root.rename(moved); root.symlink_to(outside,target_is_directory=True); swapped=True
                return real_open(path,flags,*args,**kwargs)
            with patch('experiment_manifest.os.open',side_effect=racing_open):
                with self.assertRaises(ValueError):
                    freeze_manifest(self.base,root)
            self.assertTrue(swapped)
            self.assertEqual(list(outside.iterdir()),[])

    def test_freeze_rejects_valid_but_replaced_declaration(self):
        from unittest.mock import patch
        import experiment_manifest as module
        other=self.freeze(replace(self.base,objective_sha256=digest('other valid declaration')))
        replacement=other.path.read_bytes(); real_write=module._write_immutable
        def replaced_write(root,name,raw):
            real_write(root,name,raw)
            (root/name).write_bytes(replacement)
        with tempfile.TemporaryDirectory() as directory:
            with patch('experiment_manifest._write_immutable',side_effect=replaced_write):
                with self.assertRaises(ValueError):
                    freeze_manifest(self.base,Path(directory))

    def test_generator_cache_never_bypasses_integer_validation(self):
        approved_input_sha256(1,2,1)
        with self.assertRaises(ValueError):
            approved_input_sha256(True,2,1)

    def test_known_access_input_hash_is_checked_before_input_level_holdout(self):
        held=self.base.workloads[-1]
        disguised=replace(held,role='selection',input_sha256=digest('false input identity'))
        access=AccessRecord(disguised,'selection','2026-10-01T02:00:00Z')
        with self.assertRaises(ValueError):
            self.freeze(replace(self.base,holdout_rule='input',known_accesses=self.base.known_accesses+(access,)))

    def test_receipt_training_role_cannot_relabel_known_held_out_data(self):
        frozen=self.freeze(); rows=receipts(self.base)
        extra=replace(rows[-1],role='training',started_utc='2026-10-01T02:00:00Z',completed_utc='2026-10-01T02:30:00Z')
        self.assertFalse(validate_chronology(frozen,(extra,)+rows).eligible)

    def test_disclosed_correctness_receipts_obey_holdout_and_preregistration(self):
        frozen=self.freeze(); rows=receipts(self.base)
        for start,end in (('2026-10-01T02:00:00Z','2026-10-01T02:30:00Z'),
                          ('2026-09-01T02:00:00Z','2026-09-01T02:30:00Z')):
            with self.subTest(start=start):
                access=replace(rows[-1],role='correctness',started_utc=start,completed_utc=end)
                self.assertFalse(validate_chronology(frozen,(access,)+rows).eligible)
        training=replace(rows[-1],role='correctness',stratum_sha256=self.base.workloads[0].stratum_sha256,
                         started_utc='2026-09-01T02:00:00Z',completed_utc='2026-09-01T02:30:00Z')
        self.assertFalse(validate_chronology(frozen,(training,)+rows).eligible)
        inside=replace(training,started_utc='2026-10-01T02:00:00Z',completed_utc='2026-10-01T02:30:00Z')
        self.assertTrue(validate_chronology(frozen,(inside,)+rows).eligible)

    def test_correctness_receipt_labels_cannot_hide_content_or_shape_access(self):
        primary=next(w for w in self.base.workloads if (w.W,w.H,w.seed,w.role)==(2047,2049,65537,'held_out'))
        disguised=replace(primary,role='correctness',generator='renamed',cache_regime='other')
        other_input=workload('correctness',primary.W,primary.H,2)
        for additional in (disguised,other_input):
            s=replace(self.base,workloads=self.base.workloads+(additional,))
            frozen=self.freeze(s); rows=receipts(s)
            access=replace(rows[-1],role='correctness',stratum_sha256=additional.stratum_sha256,
                           started_utc='2026-10-01T02:00:00Z',completed_utc='2026-10-01T02:30:00Z')
            self.assertFalse(validate_chronology(frozen,(access,)+rows).eligible)
            if additional==other_input:
                narrower=self.freeze(replace(s,holdout_rule='input'))
                self.assertTrue(validate_chronology(narrower,(access,)+rows).eligible)

    def test_postfreeze_held_out_correctness_needs_completed_selection(self):
        frozen=self.freeze(); rows=receipts(self.base)
        verified=replace(rows[-1],role='correctness',started_utc='2026-10-01T08:30:00Z',completed_utc='2026-10-01T08:31:00Z')
        self.assertTrue(validate_chronology(frozen,rows+(verified,)).eligible)
        for start,end in (('2026-10-01T06:30:00Z','2026-10-01T06:31:00Z'),
                          ('2026-10-01T03:59:00Z','2026-10-01T07:02:00Z')):
            with self.subTest(start=start):
                early=replace(verified,started_utc=start,completed_utc=end)
                self.assertFalse(validate_chronology(frozen,(early,)+rows).eligible)

    def test_records_reject_mutable_collections_booleans_and_noncanonical_timestamps(self):
        for update in (dict(workloads=list(self.base.workloads)),dict(training_history_complete=1),dict(preregistered_utc='2026-10-01T00:00:00+00:00')):
            with self.subTest(update=next(iter(update))):
                with self.assertRaises(ValueError):
                    self.freeze(replace(self.base,**update))


if __name__=='__main__':
    unittest.main()
