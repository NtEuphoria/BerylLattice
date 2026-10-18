"""Behavioral checks for the developer benchmark, not speed thresholds."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[2] / 'tools' / 'benchmark-playground.py'
        spec = importlib.util.spec_from_file_location('benchmark', path)
        self.bench = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.bench)

    def test_workload_checks_actual_output(self):
        result = self.bench.measure_case(1, 1, 'ramp', 0, 1)
        self.assertEqual(result['output_cells'], 1)
        self.assertEqual(result['output_sum'], 30)
        self.assertEqual(result['plan'], 'inline-v1')
        self.assertEqual(len(result['seconds']), 1)

    def test_output_audit_rejects_wrong_values(self):
        with self.assertRaises(ValueError):
            self.bench.audit_output([31], [0, 1, 2, 3], 1, 1)

    def test_number_stream_includes_every_value_across_chunk_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'numbers.txt'
            self.bench.write_numbers(path, 10003)
            values = path.read_text(encoding='ascii').splitlines()
            self.assertEqual(values, [str(i) for i in range(10003)])


class NativeComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[2] / 'tools' / 'compare-playground.py'
        spec = importlib.util.spec_from_file_location('native_comparison', path)
        cls.compare = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.compare)

    def test_same_changing_inputs_are_used_and_audits_are_outside_samples(self):
        clock = [0.0]
        calls = []
        audit = self.compare.audit_output

        def run(command, *, input, **kwargs):
            values = list(map(int, input.split()))
            self.assertEqual(values[:2], [1, 1])
            calls.append((command[0], input))
            clock[0] += 0.25
            return SimpleNamespace(stdout=json.dumps([sum((value + 1) ** 2 for value in values[2:])]))

        def slow_audit(*args):
            clock[0] += 10
            audit(*args)

        with patch.object(self.compare.subprocess, 'run', side_effect=run), \
                patch.object(self.compare, 'perf_counter', side_effect=lambda: clock[0]), \
                patch.object(self.compare, 'audit_output', side_effect=slow_audit):
            result = self.compare.measure_case(
                {'beryl': ['beryl'], 'C': ['C'], 'Rust': ['Rust']}, 'source', 1, 1, 'ramp', 2, {})
        self.assertEqual([name for name, _ in calls],
                         ['beryl', 'C', 'Rust', 'C', 'Rust', 'beryl', 'Rust', 'beryl', 'C'])
        for offset in (0, 3, 6):
            self.assertEqual(len({payload for _, payload in calls[offset:offset + 3]}), 1)
        self.assertEqual(len({payload for _, payload in calls}), 3)
        self.assertTrue(all(item['seconds'] == [0.25, 0.25]
                            for item in result['measurements'].values()))
        self.assertEqual([item['measured'] for item in result['requests']], [False, True, True])

    def test_a_wrong_native_output_stops_the_audit(self):
        with patch.object(self.compare.subprocess, 'run', return_value=SimpleNamespace(stdout='[31]')):
            with self.assertRaises(ValueError):
                self.compare.measure_case({'beryl': ['beryl']}, 'source', 1, 1, 'ramp', 1, {})

    def test_python_request_cost_has_a_separate_result_scope(self):
        def run(command, *, input, **kwargs):
            if command == ['python-service']:
                data = json.loads(input)['inputs']
                result = dict(status='success', input=data,
                              output=[sum((value + 1) ** 2 for value in data)],
                              comparison=dict(matches=True))
            else:
                data = list(map(int, input.split()))[2:]
                result = [sum((value + 1) ** 2 for value in data)]
            return SimpleNamespace(stdout=json.dumps(result))

        with patch.object(self.compare.subprocess, 'run', side_effect=run):
            result = self.compare.measure_case(
                {'beryl': ['beryl'], 'C': ['C'], 'Rust': ['Rust']}, 'source', 1, 1,
                'checkerboard', 1, {}, ['python-service'])
        self.assertEqual(set(result['measurements']), {'beryl', 'C', 'Rust'})
        self.assertEqual(len(result['python_full_request']['seconds']), 1)
        self.assertTrue(all('python_request_sha256' in item for item in result['requests']))

    def test_every_executable_is_prepared_before_any_case_runs(self):
        events = []

        def compile_program(command, binary):
            events.append(('compile', binary.name))
            return {}

        def prepare(height, width, directory, cc):
            events.append(('prepare', height, width))
            return dict(binary=directory / f'beryl-{height}x{width}', source='source', record={})

        def measure(*args):
            self.assertEqual([event[0] for event in events[:5]],
                             ['compile', 'compile', 'prepare', 'prepare', 'prepare'])
            events.append(('measure',))
            return {}

        with patch.object(self.compare, 'compile_program', side_effect=compile_program), \
                patch.object(self.compare, 'prepare_beryl', side_effect=prepare), \
                patch.object(self.compare, 'measure_case', side_effect=measure), \
                patch('builtins.print'):
            compilation, cases = self.compare.run_cases(Path('/unused'), 'clang', 'rustc', ['-O'], 1)
        self.assertEqual(len(cases), 6)
        self.assertEqual(set(compilation['beryl']), {'1x1', '5x7', '15x15'})
        self.assertEqual([event[0] for event in events[5:]], ['measure'] * 6)

    def test_all_runtime_input_patterns_stay_bounded_and_change(self):
        for height, width in self.compare.SHAPES:
            for mode in self.compare.MODES:
                previous = None
                for iteration in range(31):
                    data = self.compare.case_inputs(height, width, mode, iteration)
                    self.assertEqual(len(data), (height + 1) * (width + 1))
                    self.assertTrue(all(type(value) is int and 0 <= value <= 1023 for value in data))
                    self.assertNotEqual(data, previous)
                    previous = data

    def test_optional_python_command_survives_native_compilation_setup(self):
        for archive in (None, Path('/reviewed/public-compiler.zip')):
            with self.subTest(archive=archive):
                prepared = dict(binary=Path('/unused/beryl'), source='source', record={})
                with patch.object(self.compare, 'compile_program', return_value={}) as compile_program, \
                        patch.object(self.compare, 'prepare_beryl', return_value=prepared), \
                        patch.object(self.compare, 'compiler', return_value=SimpleNamespace(archive=archive)), \
                        patch.object(self.compare, 'measure_case', return_value={}) as measure, \
                        patch('builtins.print'):
                    self.compare.run_cases(Path('/unused'), 'clang', 'rustc', ['-O'], 1,
                                           include_python=True)
                self.assertEqual(compile_program.call_count, 2)
                self.assertEqual(measure.call_count, 6)
                for call in measure.call_args_list:
                    command = call.args[-1]
                    if archive is None:
                        self.assertEqual(command, [self.compare.sys.executable, '-m',
                                                   'axiom.playground_service'])
                    else:
                        self.assertEqual(command[:3], [self.compare.sys.executable, '-I', '-c'])
                        self.assertIn('sys.path.insert(0, sys.argv[1])', command[3])
                        self.assertIn('from beryl.playground_service import main', command[3])
                        self.assertEqual(command[4], str(archive))

    @unittest.skipIf(os.name == 'nt', 'temporary POSIX multicall compiler driver')
    def test_compiler_symlink_keeps_its_invoked_name(self):
        with tempfile.TemporaryDirectory(prefix='beryl-compiler-alias-test-') as directory:
            driver = Path(directory) / 'multicall'
            driver.write_text('#!/bin/sh\nprintf "%s\\n" "$0"\n', encoding='ascii')
            driver.chmod(0o700)
            rustc = Path(directory) / 'rustc'
            rustc.symlink_to(driver)
            info = self.compare.tool_info(str(rustc))
            self.assertEqual(info['version'], str(rustc))
            self.assertEqual(info['path'], str(rustc.absolute()))
            self.assertEqual(info['resolved_path'], str(driver.resolve()))
            self.assertEqual(info['binary_sha256'], self.compare.file_digest(driver))

    def test_compiled_selected_artifact_accepts_different_runtime_inputs(self):
        clang = os.environ.get('AXIOM_TEST_NATIVE_CLANG') or shutil.which('clang')
        if not clang:
            self.skipTest('Clang is required to exercise the emitted executable')
        with tempfile.TemporaryDirectory(prefix='beryl-comparison-test-') as directory:
            with patch.object(self.compare, 'case_inputs', side_effect=AssertionError('compilation read runtime input')), \
                    patch.object(self.compare, 'compile_program', wraps=self.compare.compile_program) as compile_program:
                prepared = self.compare.prepare_beryl(1, 1, Path(directory), clang)
            self.assertEqual(compile_program.call_count, 1)
            self.assertEqual(prepared['record']['plan_id'], 'inline-v1')
            self.assertEqual(prepared['record']['scratch_cap'], 0)
            self.assertEqual(prepared['record']['source_sha256'], self.compare.digest(prepared['source'].encode()))
            self.assertEqual(prepared['record']['generated_c_sha256'],
                             self.compare.file_digest(Path(directory) / 'beryl-1x1.c'))
            for data in ([0, 1, 2, 3], [1023, 0, 17, 29]):
                process = subprocess.run([str(prepared['binary'])],
                                         input=' '.join(map(str, [1, 1, *data])), text=True,
                                         capture_output=True, check=True, timeout=30)
                self.compare.audit_output(json.loads(process.stdout), data, 1, 1)


if __name__ == '__main__':
    unittest.main()
