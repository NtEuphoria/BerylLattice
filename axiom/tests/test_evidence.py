"""Exact replay and untrusted public receipts."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from axiom import evidence
from axiom.checker import check_plan
from axiom.codec import canonical_json, decode_plan
from axiom.frontend import admit_source, parse_source
from axiom.model import Limits
from axiom.selection import select_plan
from tests.helpers import stencil_source

class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.source=stencil_source(5,7)
        self.module=parse_source(self.source); self.kernel=admit_source(self.module)
        self.result=select_plan(self.kernel,Limits(),100000,self.kernel.objective)
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)
    def published(self):
        path=evidence.write_attempt(self.directory,self.module,self.result)
        return path,path.read_bytes(),self.result.selected_plan_bytes
    def test_replay_additional_cap_never_weakens_source(self):
        _,manifest,plan=self.published()
        for cap in (None,192,64):
            checked=evidence.replay(self.source,plan,manifest,Limits(),cap)
            self.assertTrue(checked.eligible); self.assertEqual(checked.effective_cap,64)
            self.assertEqual(checked.plan_digest,sha256(plan).hexdigest())
        tight=evidence.replay(self.source,plan,manifest,Limits(),0)
        self.assertEqual(tight.constraint_status,'violated'); self.assertEqual(tight.effective_cap,0)
        self.assertEqual(tight.plan_digest,sha256(plan).hexdigest())
        self.assertNotEqual(tight.constraint_digest,self.result.selected_check.constraint_digest)
    def test_snapshot_and_plan_tampering_but_fresh_check_accepts_whitespace(self):
        _,manifest,plan=self.published()
        for source,data in ((self.source+b'\n',plan),(self.source.replace(b'demo',b'edit'),plan),(self.source,plan+b' ')):
            with self.assertRaises(evidence.ReplayError): evidence.replay(source,data,manifest,Limits(),None)
        self.assertTrue(check_plan(admit_source(parse_source(self.source+b'\n')),self.result.selected_plan,Limits()).eligible)
    def test_versions_identities_and_strict_manifest(self):
        _,manifest,plan=self.published(); obj=json.loads(manifest)
        changes={'checker_version':'other','accounting_version':2,'semantics_version':'other','plan_version':2,
                 'ranking_digest':'0'*64,'constraint_digest':'0'*64,'semantic_digest':'0'*64,
                 'schema_version':True,'original_effective_cap':False,'source_file':'../escape','unexpected':1}
        for key,value in changes.items():
            with self.subTest(key=key),self.assertRaises(evidence.ReplayError):
                evidence.replay(self.source,plan,canonical_json(dict(obj,**{key:value})),Limits(),None)
        for data in (manifest[:-3],b'{"schema_version":1,"schema_version":1}',b'{}',b'{"schema_version":'+b'1'*100+b'}'):
            with self.assertRaises(evidence.ReplayError): evidence.replay(self.source,plan,data,Limits(),None)
    def test_saved_unknown_is_history_and_budget_rechecked(self):
        _,manifest,plan=self.published(); obj=json.loads(manifest)
        obj['saved_check'].update(semantic_status='unknown',check_complete=False,reason='CHECK_STEPS_EXHAUSTED',multiplication_ops=None,opcode_counts=None)
        self.assertTrue(evidence.replay(self.source,plan,canonical_json(obj),Limits(),None).eligible)
        checked=evidence.replay(self.source,plan,manifest,Limits(check_steps=1),None)
        self.assertEqual(checked.semantic_status,'unknown'); self.assertFalse(checked.check_complete)
    def test_noeligible_manifest_has_all_null_selection(self):
        result=select_plan(self.kernel,Limits(),0,self.kernel.objective)
        path=evidence.write_attempt(self.directory,self.module,result); obj=json.loads(path.read_bytes())
        for key in ('plan_digest','plan_file','saved_check','selected_key'): self.assertIsNone(obj[key])
        with self.assertRaises(evidence.ReplayError): evidence.replay(self.source,b'',path.read_bytes(),Limits(),None)
    def test_forged_public_records_are_not_proof(self):
        for result in (replace(self.result,selected_plan=replace(self.result.selected_plan,scratch_capacity_cells=0)),
                       replace(self.result,selected_plan_bytes=b'{}'),
                       replace(self.result,selected_check=replace(self.result.selected_check,multiplication_ops=0)),
                       replace(self.result,objective='multiplication_ops'),replace(self.result,total_work_used=True)):
            with self.assertRaises(ValueError): evidence.write_attempt(self.directory,self.module,result)
        with self.assertRaises(ValueError): evidence.write_attempt(self.directory,replace(self.module,cap=None),self.result)
    def test_interrupted_publication_preserves_old_manifest(self):
        path,manifest,_=self.published(); other=parse_source(self.source+b'\n'); kernel=admit_source(other)
        result=select_plan(kernel,Limits(),100000,kernel.objective)
        with patch.object(evidence.os,'replace',side_effect=OSError('interrupted')):
            with self.assertRaises(OSError): evidence.write_attempt(self.directory,other,result)
        self.assertEqual(path.read_bytes(),manifest); obj=json.loads(manifest)
        for kind in ('source','plan'):
            self.assertEqual(sha256((self.directory/obj[kind+'_file']).read_bytes()).hexdigest(),obj[kind+'_digest'])
    def test_replaced_referenced_file_is_rejected(self):
        path,manifest,_=self.published(); obj=json.loads(manifest); planpath=self.directory/obj['plan_file']
        planpath.write_bytes(b'{}')
        with self.assertRaises(OSError): evidence.write_attempt(self.directory,self.module,self.result)
        self.assertEqual(path.read_bytes(),manifest)
        with self.assertRaises(evidence.ReplayError): evidence.replay(self.source,planpath.read_bytes(),manifest,Limits(),None)

    def test_ranking_key_tamper_rejected_by_fresh_metrics(self):
        _,manifest,plan=self.published(); obj=json.loads(manifest)
        obj['selected_key'][0]=0
        with self.assertRaises(evidence.ReplayError):
            evidence.replay(self.source,plan,canonical_json(obj),Limits(),None)

    def test_exception_attempt_retains_constraint_identity_and_bounded_history(self):
        from axiom import selection
        with patch.object(selection,'check_plan',side_effect=RuntimeError('boom')):
            result=select_plan(self.kernel,Limits(),100,self.kernel.objective)
        path=evidence.write_attempt(self.directory,self.module,result)
        obj=json.loads(path.read_bytes())
        self.assertEqual(obj['attempts'][0]['constraint_digest'],obj['constraint_digest'])
        obj['attempts'][0]['constraint_digest']=None
        with self.assertRaises(evidence.ReplayError): evidence.decode_manifest(canonical_json(obj))

    def test_incoherent_optional_accounting_rejected(self):
        with self.assertRaises(ValueError):
            evidence.write_attempt(self.directory,self.module,replace(self.result,optional_work_used=0))

    def test_public_history_is_validated_before_serialization(self):
        attempt=self.result.attempts[0]
        forged_check=replace(attempt.check,witness=(("detail",object()),))
        forged=replace(self.result,attempts=(replace(attempt,check=forged_check),)+self.result.attempts[1:])
        with self.assertRaises(ValueError): evidence.write_attempt(self.directory,self.module,forged)
        oversized=replace(self.result,attempts=(attempt,)*100)
        with self.assertRaises(ValueError): evidence.write_attempt(self.directory,self.module,oversized)

    def test_swapped_ancestor_during_content_publication_cannot_create_outside(self):
        parent=self.directory/'parent'; directory=parent/'attempt'
        outside=self.directory/'outside'; (outside/'attempt').mkdir(parents=True)
        parent.mkdir(); directory.mkdir()
        real_link=evidence.os.link; swapped=False
        def swap_then_link(*args,**kwargs):
            nonlocal swapped
            if not swapped:
                swapped=True
                descriptor=evidence.os.open(args[0],evidence.os.O_RDONLY,dir_fd=kwargs.get('src_dir_fd'))
                with evidence.os.fdopen(descriptor,'rb') as stream: retained=stream.read()
                parent.rename(self.directory/'moved')
                parent.symlink_to(outside,target_is_directory=True)
                injected=outside/'attempt'/Path(args[0]).name
                injected.write_bytes(retained)
                try: return real_link(*args,**kwargs)
                finally: injected.unlink(missing_ok=True)
            return real_link(*args,**kwargs)
        with patch.object(evidence.os,'link',side_effect=swap_then_link):
            with self.assertRaises(OSError): evidence.write_attempt(directory,self.module,self.result)
        self.assertEqual(list((outside/'attempt').iterdir()),[])

    def test_swapped_ancestor_at_manifest_replace_cannot_overwrite_outside(self):
        parent=self.directory/'parent'; directory=parent/'attempt'
        outside=self.directory/'outside'; (outside/'attempt').mkdir(parents=True)
        parent.mkdir(); directory.mkdir()
        sentinel=outside/'attempt'/'manifest.json'; sentinel.write_bytes(b'outside sentinel')
        real_replace=evidence.os.replace
        def swap_then_replace(*args,**kwargs):
            descriptor=evidence.os.open(args[0],evidence.os.O_RDONLY,dir_fd=kwargs.get('src_dir_fd'))
            with evidence.os.fdopen(descriptor,'rb') as stream: retained=stream.read()
            parent.rename(self.directory/'moved')
            parent.symlink_to(outside,target_is_directory=True)
            injected=outside/'attempt'/Path(args[0]).name
            injected.write_bytes(retained)
            try: return real_replace(*args,**kwargs)
            finally: injected.unlink(missing_ok=True)
        with patch.object(evidence.os,'replace',side_effect=swap_then_replace):
            with self.assertRaises(OSError): evidence.write_attempt(directory,self.module,self.result)
        self.assertEqual(sentinel.read_bytes(),b'outside sentinel')
        self.assertEqual(sorted(p.name for p in (outside/'attempt').iterdir()),['manifest.json'])


    def test_coherently_rewritten_manifest_cannot_replay_noncanonical_plan_bytes(self):
        _,manifest,plan=self.published()
        variants=(b' '+plan+b'\n',json.dumps(json.loads(plan),indent=2).encode('utf-8'),
                  json.dumps(dict(reversed(list(json.loads(plan).items()))),separators=(',',':')).encode('utf-8'))
        for raw in variants:
            with self.subTest(prefix=raw[:32]):
                # General decoding remains permissive; exact replay has a stricter
                # artifact contract so its receipt identifies the supplied bytes.
                self.assertEqual(decode_plan(raw,Limits()),self.result.selected_plan)
                obj=json.loads(manifest); original=obj['plan_digest']; exact=sha256(raw).hexdigest()
                obj['plan_digest']=exact; obj['plan_file']='plan-'+exact+'.json'
                obj['saved_check']['plan_digest']=exact
                for attempt in obj['attempts']:
                    if attempt['plan_digest']==original:
                        attempt['plan_digest']=exact
                        if attempt['check'] is not None: attempt['check']['plan_digest']=exact
                coherent=canonical_json(obj)
                self.assertEqual(evidence.decode_manifest(coherent).plan_digest,exact)
                with self.assertRaises(evidence.ReplayError) as caught:
                    evidence.replay(self.source,raw,coherent,Limits(),None)
                self.assertEqual(caught.exception.code,'REPLAY_IDENTITY_MISMATCH')
                self.assertEqual(caught.exception.field_path,'$.plan')
