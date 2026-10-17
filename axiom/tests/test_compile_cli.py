"""Capsule boundaries, fixed-plan failures and independent observations."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from axiom.__main__ import main
from axiom.codec import encode_plan
from axiom.frontend import admit_source, parse_source
from axiom.planner import make_plan
from tests.helpers import stencil_source


class CompileCLITests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root/'source.ax'
        self.source.write_bytes(stencil_source(1, 1, cap=None))
        self.plan = self.root/'plan.json'
        self.plan.write_bytes(encode_plan(make_plan(admit_source(parse_source(self.source.read_bytes())), 'inline-v1')))
        self.case = self.root/'case.json'
        self.case.write_text(json.dumps(dict(schema_version=1, input=[0]*4, initial_output=[-9])))

    def cli(self, *args):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = main(list(map(str, args)))
        return code, json.loads(stdout.getvalue())

    def witness(self):
        return self.cli('witness', self.source, '--plan', self.plan, '--case', self.case,
                        '--clang', self.root/'missing clang', '--core', self.root/'missing core', '--out', self.root/'out')

    def test_conformance_rejects_worker_count_outside_fixed_bound(self):
        code, result = self.cli('conformance', '--manifest', 'unused', '--toolchain', 'unused', '--out', self.root/'out', '--workers', '5')
        self.assertEqual(code, 2)
        self.assertIn('invalid choice', result['diagnostic']['message'])

    def test_missing_case_is_usage_error(self):
        code, result = self.cli('witness', self.source, '--plan', self.plan, '--clang', 'clang', '--core', 'core', '--out', self.root/'out')
        self.assertEqual(code, 2)
        self.assertIn('--case', result['diagnostic']['message'])

    def test_case_exact_shape_and_fields_checked_before_toolchain(self):
        for case in (dict(schema_version=1, input=[0], initial_output=[-9]),
                     dict(schema_version=1, input=[0]*4, initial_output=[-9], saved_success=True),
                     dict(schema_version=True, input=[0]*4, initial_output=[-9]),
                     dict(schema_version=1, input=[False]*4, initial_output=[-9])):
            with self.subTest(case=case):
                self.case.write_text(json.dumps(case))
                code, result = self.witness()
                self.assertEqual(code, 2)
                self.assertIn('case', result['diagnostic']['message'].lower())
                self.assertFalse((self.root/'out').exists())

    def test_valid_plan_missing_compiler_is_infrastructure_failure(self):
        code, result = self.witness()
        self.assertEqual(code, 5)
        self.assertEqual(result['status'], 'unavailable')
        self.assertFalse((self.root/'out'/'manifest.json').exists())

    def test_build_failure_after_valid_fixed_plan_retains_source_and_diagnostics(self):
        from types import SimpleNamespace
        from axiom.core_toolchain import CommandReceipt, ToolchainError
        from axiom import core_capsule
        private = self.root/'private-working-capsule'
        def allocate(*args, **kwargs):
            private.mkdir()
            return str(private)
        failure = CommandReceipt(('clang with spaces', '-std=c11'), private, 1, 'retained output', 'compile failed')
        with patch.object(core_capsule, 'inspect_toolchain', return_value=SimpleNamespace(available=True)), \
             patch.object(core_capsule.tempfile, 'mkdtemp', side_effect=allocate), \
             patch.object(core_capsule, 'prepare_snapshot', return_value=private/'snapshot'), \
             patch.object(core_capsule, 'build_core', side_effect=ToolchainError('build failed', (failure,))):
            code, result = self.witness()
        self.assertEqual(code, 5)
        self.assertEqual(result['source_emission'], 'success')
        self.assertEqual(result['build_status'], 'failed')
        self.assertEqual(result['conformance_status'], 'not_observed')
        output = Path(result['manifest']).parent
        self.assertEqual((output/'fixed'/'plan.json').read_bytes(), self.plan.read_bytes())
        diagnostics = json.loads((output/'toolchain-failure.json').read_bytes())
        self.assertEqual(diagnostics['receipts'][0]['argv'], list(failure.argv))
        self.assertEqual(diagnostics['receipts'][0]['stderr'], 'compile failed')

    def test_stale_source_origins_rejected_before_toolchain(self):
        self.source.write_bytes(b'\n'+self.source.read_bytes())
        code, result = self.witness()
        self.assertEqual(code, 2)
        self.assertIn('ORIGIN', result['diagnostic']['message'])

    def test_missing_toolchain_receipt_not_replayed_as_commands(self):
        manifest = self.root/'manifest.json'
        manifest.write_text('{}')
        code, result = self.cli('conformance', '--manifest', manifest, '--toolchain', self.root/'receipt', '--out', self.root/'out')
        self.assertEqual(code, 2)
        self.assertFalse((self.root/'out').exists())

    def test_conformance_validates_exact_embedded_source(self):
        source = self.source.read_bytes()
        manifest = dict(schema_version=1, artifact_kind='core_correspondence_manifest', plans=['inline-v1'],
                        lanes=[dict(lane='reference', release=False)], cases=[dict(case_id='a', shape=[1,1], pattern='zero',
                        source_utf8=source.decode(), source_sha256='0'*64, input=[0]*4, initial_output=[-9])])
        path = self.root/'manifest.json'
        path.write_text(json.dumps(manifest))
        code, result = self.cli('conformance', '--manifest', path, '--toolchain', self.root/'receipt', '--out', self.root/'out')
        self.assertEqual(code, 2)
        self.assertIn('source', result['diagnostic']['message'])


if __name__ == '__main__':
    unittest.main()

class CapsulePublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.work = self.root/'work'
        self.work.mkdir()
        (self.work/'one.txt').write_bytes(b'one')

    def test_manifest_last_on_interruption(self):
        from axiom import core_capsule
        original = core_capsule._export_file
        def interrupt(descriptor, name, raw):
            original(descriptor, name, raw)
            raise KeyboardInterrupt
        with patch.object(core_capsule, '_export_file', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                core_capsule._publish(self.work, self.root/'out', {'status':'matched'})
        self.assertFalse((self.root/'out'/'manifest.json').exists())

    def test_export_manifest_binds_every_file_and_original_mapping(self):
        from hashlib import sha256
        from axiom.core_capsule import _publish
        path = _publish(self.work, self.root/'out', {'status':'matched'})
        manifest = json.loads(path.read_bytes())
        self.assertEqual(len(manifest['files']), 1)
        item = manifest['files'][0]
        self.assertEqual(item['original_path'], str(self.work/'one.txt'))
        self.assertEqual(sha256((path.parent/item['path']).read_bytes()).hexdigest(), item['sha256'])
        with self.assertRaises(FileExistsError):
            _publish(self.work, self.root/'out', {'status':'matched'})

    def test_symlinked_output_ancestor_never_receives_files(self):
        from axiom.core_capsule import _publish
        elsewhere = self.root/'elsewhere'
        elsewhere.mkdir()
        (self.root/'link').symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaises(OSError):
            _publish(self.work, self.root/'link'/'out', {'status':'matched'})
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_changed_ancestor_after_first_export_never_receives_files(self):
        from axiom import core_capsule
        (self.work/'two.txt').write_bytes(b'two')
        parent = self.root/'parent'
        parent.mkdir()
        outside = self.root/'outside'
        outside.mkdir()
        original = core_capsule._export_file
        count = 0
        def swap(descriptor, name, raw):
            nonlocal count
            original(descriptor, name, raw)
            count += 1
            if count == 1:
                parent.rename(self.root/'retired')
                parent.symlink_to(outside, target_is_directory=True)
        with patch.object(core_capsule, '_export_file', side_effect=swap):
            with self.assertRaises(OSError):
                core_capsule._publish(self.work, parent/'out', {'status':'matched'})
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse((self.root/'retired'/'out'/'manifest.json').exists())


class CapsuleOracleTests(unittest.TestCase):
    def test_shared_core_output_error_is_independent_mismatch(self):
        from axiom.core_capsule import _compare, _expected
        from axiom.core_emit import emit_core
        from axiom.model import Limits
        from tests.test_core_runner import RunnerTests
        fixture = RunnerTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        source = stencil_source(1,1)
        module = parse_source(source)
        kernel = admit_source(module)
        bundle = emit_core(source, encode_plan(make_plan(kernel,'inline-v1')), Limits(), (0,1,2,3), (-99,))
        # Both Core lanes agree on 31. The independent source oracle computes 30.
        toolchain = fixture.protocol(payload=b'-1\n0\n1\n2\n3\n31\nok  1 test, 0 assertions\n')
        row = _compare(bundle, kernel, _expected(module,bundle.data,bundle.initial_output), toolchain, 'ast', False, fixture.root)
        self.assertEqual(row['classification'], 'semantic_mismatch')
        self.assertEqual(row['build_status'], 'success')
        for comparison in row['comparisons'].values():
            self.assertTrue(comparison['status'])
            self.assertTrue(comparison['input'])
            self.assertFalse(comparison['output'])

    def test_fixed_plan_lowering_failure_retained_without_fallback(self):
        from axiom.core_capsule import _compare, _expected
        from axiom.core_emit import emit_core
        from axiom.model import Limits
        from tests.test_core_runner import RunnerTests
        fixture = RunnerTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        source = stencil_source(1,1)
        module = parse_source(source)
        kernel = admit_source(module)
        bundle = emit_core(source, encode_plan(make_plan(kernel,'rows2-v1')), Limits(), (0,1,2,3), (-99,))
        toolchain = fixture.protocol("report['status']='unavailable'")
        row = _compare(bundle,kernel,_expected(module,bundle.data,bundle.initial_output),toolchain,'ir',False,fixture.root)
        self.assertEqual(row['classification'],'unavailable')
        runs = list((fixture.root/'runs').iterdir())
        self.assertEqual(len(runs),1)
        self.assertEqual((runs[0]/'witness.be').read_bytes(),bundle.source_bytes)
        self.assertEqual(row['conformance_status'],'not_observed')

class CapsuleWorkerTests(unittest.TestCase):
    def test_interruption_cancels_queued_cells_and_joins_active_workers(self):
        import threading
        from axiom import core_capsule
        started = []
        finished = []
        release = threading.Event()
        timer = threading.Timer(0.1, release.set)
        timer.start()
        self.addCleanup(timer.join)
        def execute(number):
            started.append(number)
            if number == 0:
                raise KeyboardInterrupt
            release.wait(2)
            finished.append(number)
        with self.assertRaises(KeyboardInterrupt):
            core_capsule._run_tasks(list(range(100)), execute)
        self.assertLess(len(started), 100)
        self.assertEqual(set(finished), set(started)-{0})

class CapsuleReviewRegressionTests(unittest.TestCase):
    def test_later_failure_cancels_queue_while_earlier_cell_is_blocked(self):
        import threading
        from axiom.core_capsule import _run_tasks
        release = threading.Event()
        started = []
        def execute(number):
            started.append(number)
            if number == 0:
                release.wait(1)
            elif number == 1:
                raise RuntimeError('later cell failed')
            else:
                release.wait(1)
        timer = threading.Timer(0.15, release.set)
        timer.start()
        try:
            with self.assertRaisesRegex(RuntimeError, 'later cell failed'):
                _run_tasks(list(range(100)), execute)
        finally:
            release.set()
            timer.join()
        self.assertLessEqual(len(started), 5)

    def test_all_retained_qualification_files_bound_and_change_blocks_publication(self):
        from types import SimpleNamespace
        from axiom.core_capsule import _external_references, _publish
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            retained = root/'retained'
            retained.mkdir()
            for name in ('toolchain.json', 'build.json', 'unit.json', 'native.json', 'compiler', 'clang', 'snapshot/.axiom-source.json'):
                path = retained/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'identity')
            qualification = retained/'native-probe'
            qualification.mkdir()
            expected = []
            for name in ('witness.be', '.beryl-cache/job-native/result.json',
                         '.beryl-cache/job-native/version.stdout.log', '.beryl-cache/job-native/version.stderr.log',
                         '.beryl-cache/job-native/llvm-ir.stdout.log', '.beryl-cache/job-native/llvm-ir.stderr.log',
                         '.beryl-cache/job-native/assembly.stdout.log', '.beryl-cache/job-native/assembly.stderr.log',
                         '.beryl-cache/job-native/driver-jobs.stdout.log', '.beryl-cache/job-native/driver-jobs.stderr.log',
                         '.beryl-cache/job-native/compile.stdout.log', '.beryl-cache/job-native/compile.stderr.log',
                         '.beryl-cache/job-native/run.stdout.log', '.beryl-cache/job-native/run.stderr.log'):
                path = qualification/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'qualified')
                expected.append(path)
            toolchain = SimpleNamespace(compiler=retained/'compiler', clang=retained/'clang',
                receipt_path=retained/'toolchain.json', snapshot=retained/'snapshot',
                clang_config=(), clang_components=(), native_artifacts=(), source_inventory=(),
                source_repository=retained/'source', snapshot_inventory=())
            work = root/'work'
            work.mkdir()
            (work/'request.json').write_bytes(b'{}')
            references = _external_references(toolchain, work)
            by_path = {item['path']: item for item in references}
            self.assertTrue({str(path) for path in expected}.issubset(by_path))
            expected[-1].write_bytes(b'changed')
            with self.assertRaisesRegex(OSError, 'reference changed'):
                _publish(work, root/'changed-out', {'status':'matched'}, references)
            self.assertFalse((root/'changed-out'/'manifest.json').exists())
            expected[-1].unlink()
            with self.assertRaises(OSError):
                _publish(work, root/'missing-out', {'status':'matched'}, references)
            self.assertFalse((root/'missing-out'/'manifest.json').exists())
