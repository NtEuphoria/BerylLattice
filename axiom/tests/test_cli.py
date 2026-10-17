"""Public JSON interface and explicit exit classes."""
from hashlib import sha256
import json
from axiom.codec import canonical_json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from tests.helpers import stencil_source

class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name); self.source=self.directory/'source.ax'
        self.source.write_bytes(stencil_source(5,7))
    def cli(self,*args):
        p=subprocess.run([sys.executable,'-m','axiom',*map(str,args)],capture_output=True,text=True)
        self.assertTrue(p.stdout,p.stderr)
        return p.returncode,json.loads(p.stdout)
    def test_check_plan_replay(self):
        code,obj=self.cli('check',self.source); self.assertEqual(code,0); self.assertEqual(obj['status'],'admitted')
        out=self.directory/'attempt'
        code,obj=self.cli('plan',self.source,'--out',out,'--check-steps',100000)
        self.assertEqual(code,0); self.assertEqual(obj['selected_plan_id'],'rows2-v1')
        manifest=out/'manifest.json'; saved=json.loads(manifest.read_bytes())
        args=('replay',self.source,out/saved['plan_file'],'--manifest',manifest)
        code,obj=self.cli(*args); self.assertEqual(code,0); self.assertEqual(obj['check']['semantic_status'],'valid')
        code,obj=self.cli(*args,'--cap',0); self.assertEqual(code,4); self.assertEqual(obj['check']['constraint_status'],'violated')
    def test_zero_budget_and_optional_zero(self):
        out=self.directory/'attempt'
        code,obj=self.cli('plan',self.source,'--out',out,'--check-steps',0)
        self.assertEqual(code,4); self.assertEqual(obj['artifact_state'],'none'); self.assertTrue((out/'manifest.json').exists())
        code,obj=self.cli('plan',self.source,'--out',out,'--check-steps',100000,'--optional-check-steps',0)
        self.assertEqual(code,0); self.assertEqual(obj['selected_plan_id'],'inline-v1')
    def test_exit_classes(self):
        self.source.write_bytes(b'module ?;'); self.assertEqual(self.cli('check',self.source)[0],2)
        self.source.write_bytes(stencil_source(5,7).replace(b'0..=1023',b'0..=1022'))
        self.assertEqual(self.cli('check',self.source)[0],3)
        self.assertEqual(self.cli('check',self.directory/'missing')[0],5)
        self.assertEqual(self.cli('plan',self.source,'--out',self.directory,'--check-steps',-1)[0],2)
        self.assertEqual(self.cli('nonesuch')[0],2)
    def test_eval_boundary(self):
        inp,out=self.directory/'input.json',self.directory/'output.json'; data=[0]*48; original=[-9]*35
        inp.write_text(json.dumps(data)); out.write_text(json.dumps(original))
        args=('eval',self.source,'--input',inp,'--output-initial',out)
        code,obj=self.cli(*args); self.assertEqual(code,0); self.assertEqual(obj['execution']['output'],[4]*35)
        data[10]=1024; data[20]=-1; inp.write_text(json.dumps(data))
        code,obj=self.cli(*args); self.assertEqual(code,6); self.assertEqual(obj['execution']['first_bad_index'],10)
        self.assertEqual(obj['execution']['output'],original)
        inp.write_text('[true]'); self.assertEqual(self.cli(*args)[0],2)

    def test_replay_requires_all_published_references(self):
        out=self.directory/'attempt'
        code,_=self.cli('plan',self.source,'--out',out,'--check-steps',100000)
        self.assertEqual(code,0)
        manifest=out/'manifest.json'; obj=json.loads(manifest.read_bytes())
        (out/obj['source_file']).unlink()
        code,result=self.cli('replay',self.source,out/obj['plan_file'],'--manifest',manifest)
        self.assertEqual(code,5)
        self.assertEqual(result['status'],'infrastructure_failure')

    def test_edited_source_replay_is_invalid_snapshot(self):
        out=self.directory/'attempt'
        self.cli('plan',self.source,'--out',out)
        manifest=out/'manifest.json'; obj=json.loads(manifest.read_bytes())
        self.source.write_bytes(self.source.read_bytes()+b"\n")
        code,result=self.cli('replay',self.source,out/obj['plan_file'],'--manifest',manifest)
        self.assertEqual(code,2)
        self.assertEqual(result['diagnostic']['code'],'REPLAY_IDENTITY_MISMATCH')


    def test_coherent_noncanonical_published_plan_is_invalid_replay(self):
        out=self.directory/'attempt'
        self.cli('plan',self.source,'--out',out)
        manifest=out/'manifest.json'; obj=json.loads(manifest.read_bytes())
        original=obj['plan_digest']; raw=b' '+(out/obj['plan_file']).read_bytes()+b'\n'
        exact=sha256(raw).hexdigest()
        obj['plan_digest']=exact; obj['plan_file']='plan-'+exact+'.json'
        obj['saved_check']['plan_digest']=exact
        for attempt in obj['attempts']:
            if attempt['plan_digest']==original:
                attempt['plan_digest']=exact
                if attempt['check'] is not None: attempt['check']['plan_digest']=exact
        (out/obj['plan_file']).write_bytes(raw)
        manifest.write_bytes(canonical_json(obj))
        code,result=self.cli('replay',self.source,out/obj['plan_file'],'--manifest',manifest)
        self.assertEqual(code,2)
        self.assertEqual(result['diagnostic']['code'],'REPLAY_IDENTITY_MISMATCH')
        self.assertEqual(result['diagnostic']['field_path'],'$.plan')
