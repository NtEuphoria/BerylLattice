"""Tests for the paced Loom runner (tools/showcase.py).

    python -m unittest discover -s tools -p test_showcase.py

The native steps build in WSL (or in the local shell when already on Linux)
with gcc; when that cannot launch, the full-run test is skipped, never forced.
"""
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHOWCASE = ROOT / 'tools' / 'showcase.py'
DEMO = ROOT / 'docs' / 'pitch' / 'demo'
CC = os.environ.get('CC', 'gcc')
ANSI = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')
LEAKS = ('axiom', '.ax', 'beryllattice', 'traceback', 'codegen', 'termination_reason',
         'beryl-loop-c', 'users', 'appdata', '/mnt/', ':\\', '.local', '.py')
CODE = re.compile(r'\b[A-Z]{2,}(?:_[A-Z0-9]+)+\b')
# The checker's table as it printed on 2026-10-31, and a plain-English variant.
CHECKER_CODES = '''\
candidate                  verdict   reason                       time vs planner
changed-formula            refused   STRUCTURAL_MISMATCH             -          -
                             stored expression differs from the source template
off-by-one                 refused   COVERAGE_MISMATCH               -          -
                             loops must be (H, W) over distinct variables
planner-carry              accepted  VALID                           -          -
planner-direct             accepted  VALID                           -          -
skips-a-row                refused   COVERAGE_MISMATCH               -          -
                             loops must be (H, W) over distinct variables
wrong-program              refused   SEMANTIC_DIGEST_MISMATCH          -          -

6 candidates: 4 rejected (COVERAGE_MISMATCH 2, SEMANTIC_DIGEST_MISMATCH 1, STRUCTURAL_MISMATCH 1), \
2 accepted; fastest not timed; every accepted plan matched the reference
'''
CHECKER_PLAIN = '''\
candidate                  verdict   reason
off-by-one                 refused   COVERAGE_MISMATCH
                             reads one pixel past the edge
planner-direct             accepted  VALID
wrong-program              refused   was written for a different program

3 candidates: 2 rejected (COVERAGE_MISMATCH 1, SEMANTIC_DIGEST_MISMATCH 1), 1 accepted; \
every accepted plan matched the reference
'''
CHECKER_CAPS = '''\
plan             verdict   reason
changed-formula  REFUSED   computes a different formula
planner-carry    ACCEPTED  proved equal to the program
wrong-program    REFUSED   belongs to a different program

3 candidates: 2 REFUSED, 1 ACCEPTED; every accepted plan matched the reference
'''


def _load():
    spec = importlib.util.spec_from_file_location('showcase', SHOWCASE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _candidates():
    for folder in (DEMO / 'candidates', ROOT / '.local' / 'loom' / 'candidates'):
        if folder.is_dir() and any(folder.glob('*.json')):
            return folder
    return None


def _run(*args, timeout=600):
    ran = subprocess.run([sys.executable, str(SHOWCASE), '--no-pause', *args], cwd=str(ROOT),
                         capture_output=True, timeout=timeout)
    return ran.returncode, ran.stdout.decode('utf-8', 'replace'), ran.stderr.decode('utf-8', 'replace')


def _native_ok():
    shell = ['wsl', '-e', 'sh', '-c'] if os.name == 'nt' else ['sh', '-c']
    try:
        probe = subprocess.run([*shell, f'command -v {CC}'], capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


class LeakFree:
    def assert_clean(self, stdout, stderr):
        text = ANSI.sub('', stdout + stderr)
        for leak in LEAKS:
            self.assertNotIn(leak, text.lower(), f'leaked {leak!r}')


class KeepWarmTest(unittest.TestCase):
    """WSL idles out in under a minute; the paced run keeps it warm so no step opens blank."""

    def setUp(self):
        self.show = _load()
        self.started = []
        show = self.show

        class FakeProcess:
            def __init__(fake, argv, **kwargs):
                fake.argv, fake.stopped = argv, False
                self.started.append(fake)

            def terminate(fake):
                fake.stopped = True

        self.real_popen, show.subprocess.Popen = show.subprocess.Popen, FakeProcess
        self.real_steps, show.STEPS = show.STEPS, (lambda ctx: iter(()),) * 4

    def tearDown(self):
        self.show.subprocess.Popen, self.show.STEPS = self.real_popen, self.real_steps

    def test_a_paced_run_keeps_wsl_warm_and_stops_it(self):
        self.show.sys.stdin = open(os.devnull)  # Enter reads EOF at once
        try:
            self.show.main(['--steps', '0,1', '--color', 'never'])
        finally:
            self.show.sys.stdin.close()
            self.show.sys.stdin = sys.__stdin__
        if os.name == 'nt':
            self.assertEqual(len(self.started), 1)
            self.assertEqual(self.started[0].argv[:2], ['wsl', '-e'])
            self.assertTrue(self.started[0].stopped)
        else:
            self.assertEqual(self.started, [])

    def test_a_capture_run_starts_nothing(self):
        self.show.main(['--no-pause', '--steps', '0', '--color', 'never'])
        self.assertEqual(self.started, [])


class FormattingTest(unittest.TestCase):
    def setUp(self):
        self.show = _load()

    def test_refusal_reason_is_plain(self):
        reason = ('ARITHMETIC_OVERFLOW: the sum at byte 260 adds 3000 terms of up to 1046529 each, so it can '
                  'reach 3139587000 > 2147483647; at most 2052 terms fit in i32; declare the equation i64 '
                  '(`let t: i64[...]`) for 64-bit values')
        self.assertEqual(self.show.plain_refusal(reason),
                         'the sum can reach 3,139,587,000 > 2,147,483,647 · at most 2,052 terms fit in 32 bits'
                         ' · fix: declare t: i64')

    def test_unknown_reason_drops_codes_and_bytes(self):
        plain = self.show.plain_refusal('SOME_CODE: the read at byte 12 may reach 40000 > 32767')
        self.assertEqual(plain, 'the read may reach 40,000 > 32,767')

    def test_pair_bound_reads_the_declared_ranges(self):
        source = (DEMO / 'dense-127.ax').read_text(encoding='utf-8')
        self.assertEqual(self.show.pair_bound(source), (127, 128, 32512))
        source = (DEMO / 'dense-128.ax').read_text(encoding='utf-8')
        self.assertEqual(self.show.pair_bound(source), (128, 128, 32768))

    def test_candidate_table_hides_codes(self):
        lines = self.show.candidate_lines(self.show.Painter(False), CHECKER_CODES)
        text = '\n'.join(lines)
        self.assertIsNone(CODE.search(text), text)
        self.assertNotIn('VALID', text)
        self.assertNotIn('time', text)
        self.assertTrue(all(len(line) <= 90 for line in lines), text)
        rows = {line.split()[0]: line for line in lines if line[:1].strip()}
        self.assertIn('REFUSED', rows['wrong-program'])
        self.assertGreater(len(rows['wrong-program'].split('REFUSED', 1)[1].strip()), 10)
        self.assertIn('ACCEPTED', rows['planner-carry'])
        self.assertIn('6 plans: 4 refused, 2 accepted', text)
        self.assertIn('every accepted plan matched the reference', text)
        self.assertNotIn('fastest', text)

    def test_candidate_table_keeps_plain_reasons(self):
        lines = self.show.candidate_lines(self.show.Painter(False), CHECKER_PLAIN)
        text = '\n'.join(lines)
        self.assertIn('reads one pixel past the edge', text)
        self.assertIn('was written for a different program', text)
        self.assertIsNone(CODE.search(text), text)

    def test_candidate_table_reads_the_caps_format(self):
        lines = self.show.candidate_lines(self.show.Painter(False), CHECKER_CAPS)
        text = '\n'.join(lines)
        self.assertRegex(text, r'changed-formula\s+REFUSED\s+computes a different formula')
        self.assertRegex(text, r'planner-carry\s+ACCEPTED\s+proved equal to the program')
        self.assertIn('3 plans: 2 refused, 1 accepted', text)
        self.assertIn('every accepted plan matched the reference', text)

    def test_candidate_table_refuses_unreadable_output(self):
        with self.assertRaises(self.show.StepFailed):
            self.show.candidate_lines(self.show.Painter(False), 'nothing here\n')

    def test_colour_wraps_the_verdict(self):
        paint = self.show.Painter(True)
        self.assertEqual(paint.red('REFUSED'), '\x1b[1;31mREFUSED\x1b[0m')
        self.assertEqual(self.show.Painter(False).green('COMPILED'), 'COMPILED')


class FailureTest(unittest.TestCase, LeakFree):
    def test_missing_energy_source_prints_step_failed_only(self):
        with tempfile.TemporaryDirectory() as scratch:
            demo = Path(scratch) / 'demo'
            shutil.copytree(DEMO, demo, ignore=shutil.ignore_patterns('candidates'))
            (demo / 'energy.ax').rename(demo / 'energy-renamed.ax')
            code, out, err = _run('--demo-dir', str(demo), '--steps', '1')
        self.assertEqual(code, 1)
        self.assertIn('step failed', out)
        self.assertNotIn('REFUSED', out)
        self.assert_clean(out, err)

    def test_missing_dense_source_prints_step_failed_only(self):
        with tempfile.TemporaryDirectory() as scratch:
            demo = Path(scratch) / 'demo'
            shutil.copytree(DEMO, demo, ignore=shutil.ignore_patterns('candidates'))
            (demo / 'dense-128.ax').unlink()
            code, out, err = _run('--demo-dir', str(demo), '--steps', '3')
        self.assertEqual(code, 1)
        self.assertIn('step failed', out)
        self.assertNotIn('FAST', out)
        self.assert_clean(out, err)

    def test_missing_candidates_prints_step_failed_only(self):
        with tempfile.TemporaryDirectory() as scratch:
            code, out, err = _run('--candidates', str(Path(scratch) / 'none'), '--steps', '2')
        self.assertEqual(code, 1)
        self.assertIn('step failed', out)
        self.assert_clean(out, err)


class FullRunTest(unittest.TestCase, LeakFree):
    @classmethod
    def setUpClass(cls):
        if not _native_ok():
            raise unittest.SkipTest(f'{CC} cannot launch here (WSL or local shell)')
        folder = _candidates()
        if folder is None:
            raise unittest.SkipTest('no candidate plans found')
        cls.code, cls.out, cls.err = _run('--candidates', str(folder), '--color', 'always')
        cls.text = ANSI.sub('', cls.out)

    def test_no_leaks_and_no_failures(self):
        self.assertEqual(self.code, 0, self.text[-2000:])
        self.assertNotIn('step failed', self.text)
        self.assert_clean(self.out, self.err)

    def test_each_screen_is_cleared(self):
        self.assertEqual(self.out.count('\x1b[2J'), 4)

    def test_every_line_fits_90_columns(self):
        # The recording terminal is 90 columns wide; a wrapped line is visible on camera.
        wide = [line for line in self.text.splitlines() if len(line) > 90]
        self.assertEqual(wide, [])

    def test_step0_saturation_pair(self):
        self.assertRegex(self.text, r'right answer\s+9,715,500')
        self.assertRegex(self.text, r'fast instruction, no range check\s+5,107,068')
        self.assertRegex(self.text, r'no guard · not PyTorch\s+AMD Ryzen 3 3100 · AVX2')

    def test_step1_refusal_fix_and_worst_case(self):
        self.assertIn('\x1b[1;31mREFUSED\x1b[0m', self.out)
        self.assertIn('the sum can reach 3,139,587,000 > 2,147,483,647', self.text)
        self.assertIn('at most 2,052 terms fit in 32 bits', self.text)
        self.assertIn('\x1b[1;32mCOMPILED\x1b[0m', self.out)
        self.assertRegex(self.text, r'worst case \(3,000 readings of 1,023\)\s+->\s+3,139,587,000')

    def test_step2_candidates(self):
        self.assertIn('ACCEPTED', self.text)
        self.assertIn('REFUSED', self.text)
        self.assertIn('every accepted plan matched the reference', self.text)
        self.assertIsNone(CODE.search(self.text))

    def test_step3_pair_bound(self):
        self.assertRegex(self.text, r'2 x 127 x 128 = 32,512 <= 32,767\s+->\s+FAST')
        self.assertRegex(self.text, r'2 x 128 x 128 = 32,768 > 32,767\s+->\s+EXACT')
        # Stored, labelled as stored, never timed live: what "less than half the time" rests on.
        self.assertRegex(self.text, r'recorded 2026-10-31 · 256 x 256 x 256 layer, 1 thread:\s+full range, '
                                    r'exact path 690 µs · inputs to 127, fast pair 327 µs')


if __name__ == '__main__':
    unittest.main()
