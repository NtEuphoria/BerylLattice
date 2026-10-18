"""Behavioral checks for the developer benchmark, not speed thresholds."""
import importlib.util
from pathlib import Path
import tempfile
import unittest


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


if __name__ == '__main__':
    unittest.main()
