"""Executable protocol controls; fake Core actually creates jobs and nested processes."""
from dataclasses import dataclass, replace
import hashlib
import json
import os
import signal
import time
from pathlib import Path
import sys
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

from axiom.core_runner import run_core
from axiom.core_emit import emit_core
from axiom.codec import encode_plan
from axiom.frontend import parse_source, admit_source
from axiom.planner import make_plan
from axiom.model import Limits
from tests.helpers import stencil_source


@dataclass(frozen=True)
class FakeToolchain:
    compiler: Path
    clang: Path
    compiler_sha256: str
    clang_sha256: str

    def revalidate_identity(self):
        if hashlib.sha256(self.compiler.read_bytes()).hexdigest() != self.compiler_sha256:
            raise ValueError('compiler identity changed')


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='axiom runner spaces ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = stencil_source(1, 1)
        self.bundle = emit_core(source, encode_plan(make_plan(admit_source(parse_source(source)), 'inline-v1')),
                                Limits(), (0, 1, 2, 3), (-99,))

    def compiler(self, body):
        compiler = self.root / 'compiler with spaces'
        compiler.write_text('#!' + sys.executable + '\n' + body)
        compiler.chmod(0o700)
        return FakeToolchain(compiler, Path(sys.executable).resolve(),
                             hashlib.sha256(compiler.read_bytes()).hexdigest(), 'unused')

    def protocol(self, change='', payload=None):
        payload = payload if payload is not None else b'-1\n0\n1\n2\n3\n30\nok  1 test, 0 assertions\n'
        return self.compiler('''import hashlib,json,sys
from pathlib import Path
Path('received.json').write_text(json.dumps(sys.argv))
lane = sys.argv[sys.argv.index('--lowering')+1]
backend = sys.argv[sys.argv.index('--backend')+1]
job=Path('.beryl-cache/job-fresh');job.mkdir(parents=True)
native=job/'job-native';native.mkdir()
stdout=''' + repr(payload) + '''
(job/'reference.stdout.log').write_bytes(stdout)
(job/'reference.events.jsonl').write_bytes(b'{"event":"test_begin"}\\n')
(native/'differential.stdout.log').write_bytes(stdout)
report={'schema_version':1,'operation':'test','backend':backend,'status':'success',
'requested_lowering':lane,'selected_lowering':lane,'reference_attempted':True,
'reference_status':'success','tests':1,'failed_tests':0,'assertions':0,
'compared':backend=='differential','native_status':'exited' if backend=='differential' else None,
'native_exit_code':0 if backend=='differential' else None,
'native_job':str(native) if backend=='differential' else None,
'reference_output_sha256':hashlib.sha256(stdout).hexdigest(),
'reference_events_sha256':hashlib.sha256((job/'reference.events.jsonl').read_bytes()).hexdigest(),
'compiler_fingerprint':hashlib.sha256(Path(sys.argv[0]).read_bytes()).hexdigest(),
'sources':[{'path':sys.argv[-1],'sha256':hashlib.sha256(Path(sys.argv[-1]).read_bytes()).hexdigest()}],
'budgets':{'timeout_ms':120000},
'ir_test_profile':{'schema_version':5,'admitted':True} if lane=='ir' else None}
report['source_fingerprint']=hashlib.sha256(json.dumps(report['sources'],separators=(',',':')).encode()).hexdigest()
''' + change + '''
(job/'result.json').write_text(json.dumps(report))
print('outer diagnostics are not the observation')
''')

    def test_lanes_argv_spaces_and_fresh_private_jobs(self):
        for lane in ('reference', 'ast', 'ir'):
            with self.subTest(lane=lane):
                toolchain = self.protocol()
                run = run_core(self.bundle, toolchain, lane, self.root / 'runs', release=lane=='ast')
                self.assertEqual(run.classification, 'success', run.reason)
                self.assertTrue(run.cleanup_verified)
                self.assertEqual(run.argv[0], str(toolchain.compiler))
                self.assertEqual(json.loads((run.cwd/'received.json').read_text()), list(run.argv))
                self.assertEqual(run.stage_timeout_ms, 120000)
                self.assertEqual(run.pipeline_timeout_ms, 1200000)
                self.assertEqual('--release' in run.argv, lane=='ast')
                self.assertNotEqual(run.cwd, self.root/'runs')
                self.assertTrue(all(run.cwd in path.parents for path in run.job_paths))
                self.assertIsInstance(run.report_bytes, bytes)
                self.assertIsNone(run.native_signal)

    def test_rejects_failed_or_inconsistent_reports(self):
        changes = ["report['status']='failure'", "report['compared']=False",
                   "report['tests']=2", "report['tests']=True", "report['assertions']=1",
                   "report['reference_attempted']=False", "report['reference_status']='trap'",
                   "report['native_status']='start_failed'", "report['native_exit_code']=139",
                   "report['selected_lowering']='ast'", "report['ir_test_profile']['schema_version']=4",
                   "report['ir_test_profile']['admitted']=False",
                   "report['reference_output_sha256']='0'*64", "report['native_job']='/tmp'",
                   "(native/'differential.stdout.log').unlink()", "(native/'differential.stdout.log').write_bytes(b'partial')"]
        for change in changes:
            with self.subTest(change=change):
                run = run_core(self.bundle, self.protocol(change), 'ir', self.root/'runs')
                self.assertEqual(run.classification, 'error')
                self.assertIsNone(run.native_signal)

    def test_rejects_partial_observation_even_with_successful_report(self):
        run = run_core(self.bundle, self.protocol(payload=b'-1\n'), 'ast', self.root/'runs')
        self.assertEqual(run.classification, 'error')

    def test_rejects_forged_bundle_metadata_and_plan_before_execution(self):
        for fields in ({'source_digest':'0'*64}, {'semantic_digest':'0'*64},
                       {'plan_digest':'0'*64}, {'plan_bytes_sha256':'0'*64},
                       {'case_digest':'0'*64}, {'plan_bytes':b'{}'},
                       {'kernel_source_sha256':'0'*64}, {'data':(0,1,2,True)},
                       {'mappings':(replace(self.bundle.mappings[0], generated_offset=999999),)}):
            with self.subTest(fields=fields):
                run = run_core(replace(self.bundle, **fields), self.protocol(), 'reference', self.root/'runs')
                self.assertEqual(run.classification, 'infrastructure_error')
                self.assertFalse((run.cwd/'received.json').exists())

    def test_source_receipt_must_bind_exact_witness(self):
        for change in ("report['sources'][0]['sha256']='0'*64", "report['sources'][0]['path']='/tmp/other.be'",
                       "report['source_fingerprint']='0'*64"):
            with self.subTest(change=change):
                run = run_core(self.bundle, self.protocol(change), 'reference', self.root/'runs')
                self.assertEqual(run.classification, 'error')

    def test_unavailable_and_stage_timeout_remain_distinct(self):
        for status in ('unavailable', 'timeout'):
            run = run_core(self.bundle, self.protocol("report['status']="+repr(status)), 'ir', self.root/'runs')
            self.assertEqual(run.classification, status)
            self.assertEqual(run.stage_timed_out, status=='timeout')
            self.assertFalse(run.pipeline_timed_out)

    def test_missing_report_and_identity_changes_fail_closed(self):
        toolchain = self.compiler('print("no report")\n')
        run = run_core(self.bundle, toolchain, 'reference', self.root/'runs')
        self.assertEqual(run.classification, 'error')
        toolchain.compiler.write_text('changed')
        run = run_core(self.bundle, toolchain, 'reference', self.root/'runs')
        self.assertEqual(run.classification, 'infrastructure_error')

    @unittest.skipUnless(sys.platform=='linux' and hasattr(os, 'pidfd_open'), 'Linux pidfd supervision required')
    def test_timeout_cleans_distinct_group_and_reparented_grandchild(self):
        child_code = "import os,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); open('grandchild.pid','w').write(str(os.getpid())); time.sleep(60)"
        middle_code = "import subprocess,sys; subprocess.Popen([sys.executable,'-c'," + repr(child_code) + "],start_new_session=True)"
        toolchain = self.compiler('import os,signal,subprocess,sys,time\n'
                                  'signal.signal(signal.SIGTERM,signal.SIG_IGN)\n'
                                  'subprocess.Popen([sys.executable,"-c",'+repr(middle_code)+'],start_new_session=True)\n'
                                  'time.sleep(60)\n')
        run = run_core(self.bundle, toolchain, 'reference', self.root/'runs', pipeline_timeout_ms=300)
        self.assertEqual(run.classification, 'timeout', run.reason)
        self.assertTrue(run.pipeline_timed_out)
        self.assertTrue(run.cleanup_verified, run.reason)
        pid = int((run.cwd/'grandchild.pid').read_text())
        self.assertFalse(Path('/proc', str(pid)).exists(), f'owned grandchild {pid} survived')

    def test_cleanup_never_signals_an_unrelated_process(self):
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        try:
            toolchain = self.compiler('import time\ntime.sleep(60)\n')
            run = run_core(self.bundle, toolchain, 'reference', self.root/'runs', pipeline_timeout_ms=100)
            self.assertEqual(run.classification, 'timeout')
            self.assertTrue(run.cleanup_verified)
            self.assertIsNone(unrelated.poll())
        finally:
            unrelated.terminate()
            unrelated.wait(timeout=2)

    def test_malformed_report_cannot_put_mutable_values_in_frozen_run(self):
        run = run_core(self.bundle, self.protocol("report['native_status']={};report['native_exit_code']=[];report['reference_status']={}"),
                       'ast', self.root/'runs')
        self.assertEqual(run.classification, 'error')
        self.assertIsNone(run.native_status)
        self.assertIsNone(run.native_exit_code)
        self.assertIsNone(run.reference_status)

    def test_core_folded_signal_code_is_retained_without_invented_signal(self):
        run = run_core(self.bundle, self.protocol("report['status']='failure';report['native_exit_code']=139"),
                       'ast', self.root/'runs')
        self.assertEqual(run.classification, 'error')
        self.assertEqual(run.native_exit_code, 139)
        self.assertIsNone(run.native_signal)

    def test_preexisting_shared_cache_cannot_supply_a_missing_new_report(self):
        stale = self.root/'runs'/'.beryl-cache'/'job-stale'
        stale.mkdir(parents=True)
        (stale/'result.json').write_text('{"status":"success"}')
        run = run_core(self.bundle, self.compiler('pass\n'), 'reference', self.root/'runs')
        self.assertEqual(run.classification, 'error')
        self.assertEqual(run.job_paths, ())
        self.assertIsNone(run.result_path)

    @unittest.skipUnless(sys.platform == 'linux' and hasattr(os, 'pidfd_open'), 'Linux ownership mechanism required')
    def test_caller_and_group_sigint_reap_nested_children_before_propagation(self):
        child_code = ("import os,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                      "open('nested.pid','w').write(str(os.getpid())); time.sleep(60)")
        toolchain = self.compiler('import os,signal,subprocess,sys,time\n'
                                  'signal.signal(signal.SIGTERM,signal.SIG_IGN)\n'
                                  "open('core.pid','w').write(str(os.getpid()))\n"
                                  'subprocess.Popen([sys.executable,"-c",'+repr(child_code)+'],start_new_session=True)\n'
                                  'time.sleep(60)\n')
        # This disposable caller is also a *test-only* fallback subreaper: the RED
        # regression must record leaked children before safely cleaning them itself.
        script = r'''import ctypes,json,os,signal,sys,time
from pathlib import Path
from axiom.core_runner import run_core
from axiom._core_supervisor import descendants,send_owned,reap
from axiom.core_emit import emit_core
from axiom.codec import encode_plan
from axiom.frontend import parse_source,admit_source
from axiom.planner import make_plan
from axiom.model import Limits
from tests.helpers import stencil_source
from tests.test_core_runner import FakeToolchain
import hashlib
ctypes.CDLL(None).prctl(36,1,0,0,0)
root=Path(sys.argv[1]);compiler=Path(sys.argv[2])
source=stencil_source(1,1)
bundle=emit_core(source,encode_plan(make_plan(admit_source(parse_source(source)),'inline-v1')),Limits(),(0,1,2,3),(-99,))
chain=FakeToolchain(compiler,Path(sys.executable).resolve(),hashlib.sha256(compiler.read_bytes()).hexdigest(),'unused')
original_mask=signal.pthread_sigmask(signal.SIG_BLOCK, [])
result={}
try:
    run=run_core(bundle,chain,'reference',root/'runs',pipeline_timeout_ms=20000)
    result['returned']=run.classification
except KeyboardInterrupt:
    result['interrupted']=True
finally:
    signal.signal(signal.SIGINT,signal.SIG_IGN)
    jobs=list((root/'runs').glob('core-*'))
    cwd=jobs[0] if jobs else None
    receipt=cwd/'supervisor-result.json' if cwd else None
    result['receipt']=json.loads(receipt.read_text()) if receipt and receipt.exists() else None
    result['surviving_owned']=sorted(descendants(os.getpid()))
    result['mask_restored']=signal.pthread_sigmask(signal.SIG_BLOCK, []) == original_mask
    (root/'result.json').write_text(json.dumps(result))
    until=time.monotonic()+3
    while time.monotonic()<until:
        send_owned(os.getpid(),signal.SIGKILL)
        if reap():break
        time.sleep(.01)
'''
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)'])
        try:
            for group in (False, True):
                for repeats in (1, 4):
                    with self.subTest(group=group, repeats=repeats):
                        root = self.root / f'cancel-{group}-{repeats}'
                        root.mkdir()
                        with (root/'caller.log').open('wb') as log:
                            caller = subprocess.Popen([sys.executable, '-c', script, str(root), str(toolchain.compiler)],
                                                      start_new_session=True, stdout=log, stderr=log)
                            try:
                                until = time.monotonic()+5
                                nested=[]
                                while time.monotonic()<until:
                                    nested=list((root/'runs').glob('core-*/nested.pid'))
                                    if nested and nested[0].read_text():break
                                    if caller.poll() is not None:break
                                    time.sleep(.01)
                                self.assertTrue(nested, (root/'caller.log').read_text())
                                cwd=nested[0].parent
                                pids=[int((cwd/name).read_text()) for name in ('core.pid','nested.pid')]
                                self.assertNotEqual(os.getpgid(pids[0]), os.getpgid(pids[1]))
                                for _ in range(repeats):
                                    if group:os.killpg(caller.pid,signal.SIGINT)
                                    else:os.kill(caller.pid,signal.SIGINT)
                                    time.sleep(.04)
                                caller.wait(timeout=8)
                                result=json.loads((root/'result.json').read_text())
                                self.assertTrue(result.get('interrupted'), result)
                                self.assertIsNotNone(result['receipt'], result)
                                self.assertTrue(result['receipt']['cleanup_verified'], result)
                                self.assertFalse(result['receipt']['timed_out'], result)
                                self.assertEqual(result['surviving_owned'], [], result)
                                self.assertTrue(result['mask_restored'], result)
                                self.assertTrue(all(not Path('/proc',str(pid)).exists() for pid in pids))
                                self.assertIsNone(unrelated.poll())
                            finally:
                                if caller.poll() is None:
                                    os.kill(caller.pid,signal.SIGINT)
                                    caller.wait(timeout=8)
        finally:
            unrelated.terminate()
            unrelated.wait(timeout=2)

    def test_successful_outer_exit_does_not_leave_background_children(self):
        toolchain = self.compiler('import subprocess,sys\nsubprocess.Popen([sys.executable,"-c",'
                                  + repr('import time;time.sleep(60)') + '],start_new_session=True)\n')
        run = run_core(self.bundle, toolchain, 'reference', self.root/'runs')
        self.assertTrue(run.cleanup_verified)
        self.assertNotEqual(run.classification, 'success')
