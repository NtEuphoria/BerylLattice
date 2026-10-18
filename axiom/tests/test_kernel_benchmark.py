"""Real native smoke tests for the independent callable-kernel measurement tool."""
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / 'tools' / 'measure-kernel.py'
CORRECT = '''#include <stdint.h>
int32_t beryl_kernel(const int32_t *a, int32_t *o) {
    for (int c=0;c<2;c++) {
        int x=a[c]+1,y=a[c+1]+1,z=a[c+3]+1,t=a[c+4]+1;
        o[c]=((x*x+y*y)+z*z)+t*t;
    }
    return 0;
}
int main(void) { return 91; }
'''


class KernelBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='beryl-kernel-test-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.baseline = self.root / 'baseline.c'
        self.candidate = self.root / 'candidate.c'
        self.output = self.root / 'result.json'
        self.baseline.write_text(CORRECT, encoding='ascii')
        self.candidate.write_text(CORRECT + '\n/* candidate identity */\n', encoding='ascii')
        self.clang = os.environ.get('AXIOM_TEST_NATIVE_CLANG') or shutil.which('clang')

    def run_tool(self, *extra):
        if not self.clang:
            self.skipTest('native Clang is required')
        return subprocess.run(
            [sys.executable, str(TOOL), '--baseline', str(self.baseline),
             '--candidate', str(self.candidate), '--clang', self.clang,
             '--height', '1', '--width', '2', '--iterations', '19',
             '--samples', '3', '--output', str(self.output), *extra],
            text=True, capture_output=True, timeout=45)

    def test_correct_real_kernels_are_audited_and_sources_identified_exactly(self):
        process = self.run_tool()
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(self.output.read_text())
        self.assertEqual(result['sample_count'], 3)
        self.assertEqual(result['iterations'], 19)
        self.assertEqual(result['sample_order'], [['baseline', 'candidate'],
                                                ['candidate', 'baseline'],
                                                ['baseline', 'candidate']])
        self.assertIn('capture', result['timed_scope'])
        self.assertIn('clang', result['toolchain']['version'].lower())
        self.assertEqual(result['flags'], ['-O3', '-std=c11', '-fno-lto'])
        for name, path in [('baseline', self.baseline), ('candidate', self.candidate)]:
            record = result['programs'][name]
            self.assertEqual(record['source_sha256'], sha256(path.read_bytes()).hexdigest())
            self.assertEqual(len(record['executable_sha256']), 64)
            self.assertGreater(record['build_seconds'], 0)
            self.assertEqual(len(record['ns_per_run']), 3)
            self.assertGreater(record['median_ns_per_run'], 0)
            self.assertGreaterEqual(record['p95_ns_per_run'], record['median_ns_per_run'])
            for sample in record['samples']:
                self.assertTrue(sample['audit_ok'])
                self.assertEqual(sample['warmup_calls'], 1)
                self.assertGreater(sample['first_call_ns'], 0)
                self.assertEqual(len(sample['final_output']), 2)
        self.assertEqual(result['programs']['baseline']['samples'],
                         [dict(item, elapsed_ns=base['elapsed_ns'],
                               ns_per_run=base['ns_per_run'], first_call_ns=base['first_call_ns'])
                          for item, base in zip(result['programs']['candidate']['samples'],
                                                result['programs']['baseline']['samples'])])
        self.assertEqual(len(result['paired_ratios']), 3)

    def test_wrong_output_is_rejected_without_publishing_results(self):
        self.candidate.write_text(CORRECT.replace('return 0;', 'o[1] += 1; return 0;'))
        process = self.run_tool()
        self.assertNotEqual(process.returncode, 0)
        self.assertIn('audit', process.stderr.lower())
        self.assertFalse(self.output.exists())

    def test_input_corruption_is_rejected(self):
        self.candidate.write_text(CORRECT.replace('return 0;',
                                  '((int32_t *)a)[0] ^= 1; return 0;'))
        process = self.run_tool()
        self.assertNotEqual(process.returncode, 0)
        self.assertIn('audit', process.stderr.lower())
        self.assertFalse(self.output.exists())

    def test_full_replay_catches_transient_unsampled_output_corruption(self):
        # Iteration zero samples o[0]. Corrupt o[1] there, overwrite it on the
        # next call, and repeat on replay: only the full replay sees the fault.
        code = CORRECT.replace('return 0;', '''
        static int calls = 0;
        if (++calls == 2 || calls == 22) o[1] += 1;
        return 0;''')
        self.candidate.write_text(code)
        process = self.run_tool()
        self.assertNotEqual(process.returncode, 0)
        self.assertIn('replay', process.stderr.lower())
        self.assertFalse(self.output.exists())

    def test_nonzero_status_is_rejected(self):
        self.candidate.write_text(CORRECT.replace('return 0;', 'return 1;'))
        process = self.run_tool()
        self.assertNotEqual(process.returncode, 0)
        self.assertIn('audit', process.stderr.lower())

    def test_existing_output_is_preserved(self):
        self.output.write_bytes(b'keep original evidence')
        process = self.run_tool()
        self.assertNotEqual(process.returncode, 0)
        self.assertIn('already exists', process.stderr)
        self.assertEqual(self.output.read_bytes(), b'keep original evidence')

    def test_invalid_arguments_are_rejected_without_results(self):
        for arguments in [('--iterations', '0'), ('--samples', '0'),
                          ('--height', '0'), ('--width', '256'),
                          ('--height', '15', '--width', '16')]:
            with self.subTest(arguments=arguments):
                process = self.run_tool(*arguments)
                self.assertNotEqual(process.returncode, 0)
                self.assertIn('must be', process.stderr)
                self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
