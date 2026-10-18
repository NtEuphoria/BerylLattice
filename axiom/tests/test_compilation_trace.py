"""Measurement contracts: exact identities/counts, never latency thresholds."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


def load_profiler():
    spec = importlib.util.spec_from_file_location('compilation_profiler', ROOT / 'tools/profile-compilation.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CompilationTraceTests(unittest.TestCase):
    def test_nested_phases_are_inclusive_and_counts_are_separate(self):
        from axiom.compilation_trace import CompilationTrace
        ticks = iter((0, 10, 30, 60, 70, 100))
        trace = CompilationTrace(clock=lambda: next(ticks))
        with trace.phase('total_fresh_source_preparation'):
            with trace.phase('semantic_checking'):
                trace.count('semantic_proofs')
        with trace.phase('semantic_checking'):
            trace.count('semantic_proofs', 2)
        report = trace.report()
        self.assertEqual(report['schema_version'], 1)
        self.assertEqual(report['timing_unit'], 'ns')
        self.assertEqual(report['timing_semantics'], 'inclusive')
        self.assertEqual(report['phases'], {
            'total_fresh_source_preparation': {'elapsed_ns': 60, 'calls': 1},
            'semantic_checking': {'elapsed_ns': 50, 'calls': 2}})
        self.assertEqual(report['counts'], {'semantic_proofs': 3})
        json.dumps(report, allow_nan=False)

    def test_exceptions_are_recorded_and_report_snapshots_are_detached(self):
        from axiom.compilation_trace import CompilationTrace
        ticks = iter((100, 125))
        trace = CompilationTrace(clock=lambda: next(ticks))
        with self.assertRaisesRegex(ValueError, 'fixture'):
            with trace.phase('code_emission'):
                raise ValueError('fixture')
        report = trace.report()
        report['phases']['code_emission']['elapsed_ns'] = -1
        report['counts']['forged'] = 1
        self.assertEqual(trace.report()['phases']['code_emission'], {'elapsed_ns': 25, 'calls': 1})
        self.assertEqual(trace.report()['counts'], {})

    def test_trace_rejects_non_integer_counter_amounts(self):
        from axiom.compilation_trace import CompilationTrace
        trace = CompilationTrace()
        for amount in (True, 0.5, '1', -1):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                trace.count('proofs', amount)
        self.assertEqual(trace.report()['counts'], {})


class CompilationProfilerTests(unittest.TestCase):
    def test_boundary_fixtures_cover_reservations_objectives_and_edits(self):
        profiler = load_profiler()
        fixtures = profiler.build_fixtures('boundary')
        for height, width in ((1, 1), (5, 7), (15, 15), (1, 127), (127, 1), (2, 4), (3, 2)):
            cases = [case for case in fixtures if (case['height'], case['width']) == (height, width)]
            reservations = (0, 8 * (width + 1), 4 * (height + 1) * (width + 1))
            expected_caps = {max(0, value + delta) for value in reservations for delta in (-1, 0, 1)}
            self.assertEqual({case['cap'] for case in cases}, expected_caps)
            self.assertEqual({case['objective'] for case in cases}, {'multiplication_ops', 'plan_workspace_bytes'})
        self.assertEqual({case['edit'] for case in fixtures}, {'base', 'comment', 'rename', 'cap', 'objective', 'input_only'})
        self.assertTrue(all((case['height'] + 1) * (case['width'] + 1) <= 256 for case in fixtures))
        ids = [case['id'] for case in fixtures]
        self.assertEqual(len(ids), len(set(ids)))

    def test_fixture_source_and_external_audit_agree(self):
        profiler = load_profiler()
        from axiom.frontend import admit_source, parse_source
        from axiom.model import Limits
        self.assertEqual(profiler.reference_output([0, 1, 2, 3], 1, 1), [30])
        for case in profiler.build_fixtures('boundary'):
            source = profiler.fixture_source(case)
            kernel = admit_source(parse_source(source.encode(), Limits()))
            self.assertEqual((kernel.height, kernel.width), (case['height'], case['width']))
            data = list(range((case['height'] + 1) * (case['width'] + 1)))
            expected = profiler.reference_output(data, case['height'], case['width'])
            profiler.audit_output(expected, data, case['height'], case['width'])
            with self.assertRaises(ValueError):
                profiler.audit_output(expected + [0], data, case['height'], case['width'])

    def test_wasm_local_count_reads_code_declarations(self):
        profiler = load_profiler()
        module = b'\x00asm\x01\x00\x00\x00' + bytes((10, 9, 1, 7, 2, 3, 0x7f, 2, 0x7e, 0, 11))
        self.assertEqual(profiler.wasm_local_count(module), 5)
        with self.assertRaises(ValueError):
            profiler.wasm_local_count(module[:-1])


class NativeCompilationFieldTests(unittest.TestCase):
    def test_external_compilation_retains_size_and_wall_phase(self):
        import sys
        import tempfile
        spec = importlib.util.spec_from_file_location('trace_native_comparison', ROOT / 'tools/compare-playground.py')
        compare = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(compare)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'artifact'
            command = [sys.executable, '-c', 'from pathlib import Path; import sys; Path(sys.argv[1]).write_bytes(b"fixture")', str(output)]
            result = compare.compile_program(command, output)
            self.assertEqual(result['binary_bytes'], 7)
            self.assertEqual(result['binary_sha256'], compare.digest(b'fixture'))
            self.assertEqual(result['phase'], 'native_compiler_link')
            self.assertEqual(result['command'], command)
            self.assertIn('seconds', result)


class NativeSourceProfilerTests(unittest.TestCase):
    def test_native_pipeline_emits_actual_compact_15x15_source(self):
        profiler = load_profiler()
        case = next(case for case in profiler.build_fixtures() if (case['height'], case['cap']) == (15, 128))
        source = profiler.fixture_source(case).encode()
        pipeline, prepare = profiler.native_pipeline()
        from axiom import native_codegen
        with patch.object(native_codegen, 'emit_native_c', side_effect=AssertionError('legacy byte emitter used')):
            result = prepare(source)
        self.assertEqual(pipeline, 'source-coordinator')
        self.assertEqual(result.artifact.codegen_version, 'beryl-bounded-loop-c-v1')
        self.assertEqual(result.search.policy_id, 'ranked-proof-v1')
        self.assertEqual(result.artifact.source_digest, profiler.sha256(source))
        self.assertEqual(result.artifact.plan_digest, profiler.sha256(result.search.selected_plan_bytes))
        self.assertEqual(result.artifact.c_digest, profiler.sha256(result.artifact.c_source))
        self.assertIsNotNone(result.artifact.hint_digest)
        finite = native_codegen.emit_native_c(source, result.search.selected_plan_bytes)
        self.assertLess(len(result.artifact.c_source) * 10, len(finite.c_source))

    def test_old_checkout_detection_uses_real_legacy_public_pipeline(self):
        profiler = load_profiler()
        original_import = profiler.importlib.import_module
        def old_import(name):
            if name == 'axiom.source_compilation':
                raise ModuleNotFoundError(name, name=name)
            return original_import(name)
        with patch.object(profiler.importlib, 'import_module', side_effect=old_import):
            pipeline, prepare = profiler.native_pipeline()
        case = profiler.build_fixtures('smoke')[0]
        result = prepare(profiler.fixture_source(case).encode())
        self.assertEqual(pipeline, 'legacy-public-bytes')
        self.assertEqual(result.artifact.codegen_version, 'beryl-finite-c-v1')
        self.assertEqual(result.artifact.plan_digest, profiler.sha256(result.search.selected_plan_bytes))
        self.assertIsNone(result.hint_failure)
        with patch.object(profiler.importlib, 'import_module', side_effect=ModuleNotFoundError('dependency', name='axiom.broken_dependency')):
            with self.assertRaises(ModuleNotFoundError):
                profiler.native_pipeline()

    def test_native_wall_fields_cover_frontend_file_write_and_real_compiler(self):
        profiler = load_profiler()
        cc = os.environ.get('AXIOM_TEST_NATIVE_CLANG') or shutil.which('clang')
        if cc is None:
            self.skipTest('Clang required for real native profiler audit')
        case = profiler.build_fixtures('smoke')[0]
        source = profiler.fixture_source(case)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(profiler, 'perf_counter_ns', side_effect=(100, 120, 130, 160)):
                result = profiler.native_sample(source, case, cc, Path(directory), ['-O3', '-std=c11'])
            generated = (Path(directory) / 'sample.c').read_bytes()
        self.assertEqual(result['pipeline'], 'source-coordinator')
        self.assertEqual(result['source_compilation_ns'], 20)
        self.assertEqual(result['source_compilation_seconds'], 20 / 1e9)
        self.assertEqual(result['native_compiler_link_ns'], 30)
        self.assertEqual(result['total_fresh_native_preparation_ns'], 60)
        self.assertEqual(result['generated_c_sha256'], profiler.sha256(generated))
        self.assertEqual(result['generated_c_bytes'], len(generated))
        self.assertEqual(result['source_sha256'], profiler.sha256(source.encode()))
        self.assertEqual(result['codegen_version'], 'beryl-bounded-loop-c-v1')
        self.assertEqual(result['independent_audit'], 'passed')
        self.assertNotIn('selection_and_check_ns', result)
        self.assertNotIn('fresh_check_and_emit_ns', result)

    def test_native_trace_diagnostics_are_separate_and_preserve_c_identity(self):
        profiler = load_profiler()
        _, prepare = profiler.native_pipeline()
        source = profiler.fixture_source(profiler.build_fixtures('smoke')[0]).encode()
        compiled = prepare(source)
        report = profiler.native_diagnostic(prepare, source, compiled.artifact.c_digest)
        self.assertIn('separate native diagnostic', report['scope'])
        self.assertEqual(report['trace']['counts']['source_admissions'], 1)
        self.assertEqual(report['trace']['counts']['semantic_checks'], 1)
        self.assertTrue(report['call_counts'])

    def test_archive_provenance_keeps_declared_revision_distinct_from_git_identity(self):
        profiler = load_profiler()
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            modules = repo / 'axiom/src/axiom'
            modules.mkdir(parents=True)
            (modules / 'example.py').write_bytes(b'# snapshot')
            identity = profiler.git_identity(repo, declared_revision='39dc2f6')
        self.assertEqual(identity['kind'], 'source-snapshot')
        self.assertIsNone(identity['revision'])
        self.assertIsNone(identity['working_tree_dirty'])
        self.assertEqual(identity['declared_revision'], '39dc2f6')
        self.assertEqual(identity['modules'], {'axiom/src/axiom/example.py': profiler.sha256(b'# snapshot')})

    def test_cli_refuses_existing_output_and_lists_unchanged_fixtures(self):
        command = [sys.executable, str(ROOT / 'tools/profile-compilation.py')]
        listed = subprocess.run(command + ['--list-fixtures', '--fixture-set', 'smoke'],
                                check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(listed.stdout)[0]['id'], '1x1-cap64-multiplication_ops')
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'existing.json'
            output.write_text('preserve me')
            attempted = subprocess.run(command + ['--fixture-set', 'smoke', '--samples', '1', '--output', str(output)],
                                       capture_output=True, text=True)
            self.assertNotEqual(attempted.returncode, 0)
            self.assertIn('new --output', attempted.stderr)
            self.assertEqual(output.read_text(), 'preserve me')


if __name__ == '__main__':
    unittest.main()
