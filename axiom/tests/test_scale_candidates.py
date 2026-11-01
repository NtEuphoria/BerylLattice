"""Untrusted candidate loop plans: decoded safely, checked, and verified when accepted."""
import contextlib
import dataclasses
import io
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from axiom.frontend import admit_source, parse_source
from axiom.scale_candidates import SoundnessAlarm, load_plan, review_candidates
from axiom.scale_checker import check_loop_plan
from axiom.scale_plan import LoopPlan, Stage, make_scale_plan, plan_json
from tests.test_scale_family import BOX, SUM
from tests.test_scale_oracle import _mutate

REASONS = {'VALID', 'STRUCTURAL_MISMATCH', 'COVERAGE_MISMATCH', 'ARITHMETIC_OVERFLOW',
           'LOAD_OUT_OF_BOUNDS', 'INVALID_PLAN'}


class CandidateTests(unittest.TestCase):
    def test_round_trip(self):
        source = BOX.format(h=30, w=25).encode()
        kernel = admit_source(parse_source(source))
        for plan_id in ('direct-v1', 'carry-v1'):
            plan = make_scale_plan(kernel, plan_id)
            with self.subTest(plan=plan_id):
                self.assertEqual(load_plan(plan_json(plan)), plan)

    def test_hostile_candidates_are_rejected_not_raised(self):
        source = SUM.format(n=2000).encode()
        digest = admit_source(parse_source(source)).semantic_digest
        floats = json.dumps({'format': 'beryl-loop-plan-v1', 'semantic_digest': digest,
                             'plan_id': 'direct-v1',
                             'stages': [{'loops': [['r', 1.5], ['c', 1]], 'index': [0, [['c', 1]]],
                                         'value': ['const', 0]}]}).encode()
        hostile = {'huge': b'x' * (2 << 20), 'deep': b'[' * 10000, 'wrong shape': b'{"stages": 5}',
                   'nan': b'NaN', 'floats': floats}
        results = review_candidates(source, list(hostile.items()))
        for result in results:
            with self.subTest(candidate=result.name):
                self.assertFalse(result.accepted)
                self.assertEqual(result.reason, 'INVALID_PLAN')
                self.assertIsNone(result.plan)

    def test_mutants_are_reported_with_reasons(self):
        source = SUM.format(n=2000).encode()
        plan = make_scale_plan(admit_source(parse_source(source)))
        stage = plan.stages[0]
        rng = random.Random(20261029)
        candidates = []
        for number in range(50):
            mutant = LoopPlan(plan.semantic_digest, plan.plan_id,
                              (Stage(stage.loops, stage.index, _mutate(stage.value, rng)),))
            candidates.append((f'mutant-{number}', plan_json(mutant)))
        results = review_candidates(source, candidates)
        self.assertEqual(len(results), 50)
        self.assertLessEqual({r.reason for r in results}, REASONS)
        self.assertGreaterEqual(sum(not r.accepted for r in results), 30)

    def test_samples_lie_inside_each_declared_range(self):
        # Samples outside a range would make both sides fail the same check and "match" vacuously.
        from tests.test_scale_ranges import INT8_DOT
        source = INT8_DOT.format(n=500).encode()
        plan = make_scale_plan(admit_source(parse_source(source)))
        (result,) = review_candidates(source, [('planner', plan_json(plan))])
        self.assertTrue(result.accepted)
        self.assertEqual(result.samples_run, 3)

    def test_accepted_mismatch_raises_alarm(self):
        source = SUM.format(n=2000).encode()
        plan = make_scale_plan(admit_source(parse_source(source)))
        stage = plan.stages[0]
        _, var, lo, hi, body = stage.value
        forged = dataclasses.replace(plan, stages=(dataclasses.replace(
            stage, value=('sum', var, lo, hi, ('mul', body, ('const', 2)))),))
        self.assertFalse(check_loop_plan(source, forged).valid)
        lenient = dataclasses.replace(check_loop_plan(source, plan), reason='VALID')

        def accept(*args, **kwargs):
            return lenient
        with mock.patch('axiom.scale_candidates.check_loop_plan', accept), \
                mock.patch('axiom.scale_runtime.check_loop_plan', accept):
            with self.assertRaises(SoundnessAlarm):
                review_candidates(source, [('forged', plan_json(forged))])


ROOT = Path(__file__).resolve().parents[2]


class PublicOutputTests(unittest.TestCase):
    """What the demo video shows must say beryl, never the internal codename."""

    def test_demo_output_has_no_codename(self):
        source = SUM.format(n=2000).encode()
        plan = make_scale_plan(admit_source(parse_source(source)))
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'candidates'
            folder.mkdir()
            (Path(tmp) / 'program.ax').write_bytes(source)
            (folder / 'direct.json').write_bytes(plan_json(plan))
            (folder / 'broken.json').write_bytes(b'{"stages": 5}')
            ran = subprocess.run([sys.executable, str(ROOT / 'tools' / 'demo-checked-candidates.py'),
                                  '--source', str(Path(tmp) / 'program.ax'), '--candidates', str(folder),
                                  '--no-time'], capture_output=True, text=True, timeout=600)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertIn('2 candidates: 1 REFUSED, 1 ACCEPTED', ran.stdout)
        self.assertNotIn('axiom', ran.stdout.lower())
        self.assertNotIn(tmp, ran.stdout)

    def test_demo_refusal_has_no_codename(self):
        # A source beryl refuses, or a missing one, ends with a beryl message, not a traceback.
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / 'bad.ax'
            bad.write_text('module m;\nshape H = 1;\n', encoding='utf-8')
            for source in (bad, Path(tmp) / 'missing.ax'):
                ran = subprocess.run([sys.executable, str(ROOT / 'tools' / 'demo-checked-candidates.py'),
                                      '--source', str(source), '--candidates', tmp, '--no-time'],
                                     capture_output=True, text=True, timeout=600)
                text = (ran.stdout + ran.stderr).lower()
                with self.subTest(source=source.name):
                    self.assertEqual(ran.returncode, 1)
                    self.assertIn('beryl', text)
                    self.assertNotIn('axiom', text)
                    self.assertNotIn('traceback', text)
                    self.assertNotIn(tmp.lower(), text)  # no file paths on screen
                    self.assertNotIn('.ax', text)

    def test_wrapper_output_has_no_codename(self):
        with tempfile.TemporaryDirectory() as tmp:
            program = Path(tmp) / 'program.ax'
            program.write_bytes(SUM.format(n=2000).encode())
            for argv, branded in ((['--help'], True), (['check', '--help'], True), (['check', str(program)], False)):
                ran = subprocess.run([sys.executable, str(ROOT / 'tools' / 'beryl.py'), *argv],
                                     capture_output=True, text=True, timeout=600)
                text = (ran.stdout + ran.stderr).lower()
                with self.subTest(argv=argv[0] if branded else 'check program'):
                    self.assertEqual(ran.returncode, 0, ran.stderr)
                    self.assertNotIn('axiom', text)
                    if branded:
                        self.assertIn('usage: beryl', text)


DEMO = ROOT / 'tools' / 'demo-checked-candidates.py'
PROGRAM = ROOT / 'bench' / 'demo_b' / 'program.ax'
CURATED = ROOT / 'docs' / 'pitch' / 'demo' / 'candidates'
# The label spoken in the video, and the words its plain-English refusal must use.
SPOKEN = {'off-by-one': 'past the edge', 'skips-a-row': 'last row',
          'changed-formula': 'different formula', 'wrong-program': 'different program'}


def _demo_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location('beryl_demo', DEMO)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rows(stdout):
    """{candidate name: its table row} for every row of the demo's table."""
    return {line.split()[0]: line for line in stdout.splitlines()
            if line.split() and line.split()[0] in {f.stem for f in CURATED.glob('*.json')}}


class CuratedCandidateTests(unittest.TestCase):
    """The six plans the video shows: each broken one has exactly the defect its label names."""

    @classmethod
    def setUpClass(cls):
        cls.kernel = admit_source(parse_source(PROGRAM.read_bytes()))
        cls.direct = make_scale_plan(cls.kernel, 'direct-v1')
        cls.plans = {f.stem: load_plan(f.read_bytes()) for f in CURATED.glob('*.json')}

    def test_the_six_plans(self):
        self.assertEqual(set(self.plans), {'planner-direct', 'planner-carry', *SPOKEN})
        self.assertEqual(self.plans['planner-direct'], self.direct)
        self.assertEqual(self.plans['planner-carry'], make_scale_plan(self.kernel, 'carry-v1'))

    def test_each_label_names_the_real_defect(self):
        stage = self.direct.stages[0]
        (rv, rows), (cv, cols) = stage.loops

        def only(**change):
            return dataclasses.replace(self.direct, stages=(dataclasses.replace(stage, **change),))
        # One column too many in every row: the loop runs to 255 where the image has 254.
        self.assertEqual(self.plans['off-by-one'], only(loops=((rv, rows), (cv, cols + 1))))
        # The row loop stops one short: the last output row is never written.
        self.assertEqual(self.plans['skips-a-row'], only(loops=((rv, rows - 1), (cv, cols))))
        # x[r+2,c] is added twice and x[r+2,c+1] never: a different formula, same loops and bounds.
        changed = self.plans['changed-formula']
        self.assertEqual((changed.semantic_digest, changed.stages[0].loops, changed.stages[0].index),
                         (self.direct.semantic_digest, stage.loops, stage.index))
        loads = [n[1][0] for n in _walk(changed.stages[0].value) if n[0] == 'load']
        self.assertEqual(sorted(loads), [0, 1, 2, 256, 257, 258, 512, 512, 514])
        # A real plan from beryl's planner, for the sensor-energy program.
        other = admit_source(parse_source((ROOT / 'docs' / 'pitch' / 'demo' / 'energy-i64.ax').read_bytes()))
        self.assertEqual(self.plans['wrong-program'], make_scale_plan(other))
        self.assertNotEqual(other.semantic_digest, self.kernel.semantic_digest)

    def test_a_missing_candidates_folder_is_an_error(self):
        # A mistyped path must not read like a real "0 candidates" result.
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / 'no-such-folder'
            ran = subprocess.run([sys.executable, str(DEMO), '--source', str(PROGRAM),
                                  '--candidates', str(missing), '--no-time'],
                                 capture_output=True, text=True, timeout=600)
        self.assertEqual(ran.returncode, 1, ran.stdout)
        self.assertIn('beryl could not find the candidate plans', ran.stdout)
        self.assertNotIn(tmp, ran.stdout)
        self.assertNotIn('0 candidates', ran.stdout)

    def test_demo_table_reads_plainly(self):
        ran = subprocess.run([sys.executable, str(DEMO), '--source', str(PROGRAM),
                              '--candidates', str(CURATED), '--no-time'],
                             capture_output=True, text=True, timeout=600)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        lines = ran.stdout.rstrip().splitlines()
        rows = _rows(ran.stdout)
        self.assertEqual(len(rows), 6)
        for name in ('planner-direct', 'planner-carry'):
            self.assertIn('ACCEPTED', rows[name].split())
        reasons = []
        for name, words in SPOKEN.items():
            with self.subTest(candidate=name):
                self.assertIn('REFUSED', rows[name].split())
                self.assertIn(words, rows[name])
                reasons.append(rows[name].split('REFUSED', 1)[1].strip())
        self.assertEqual(len(set(reasons)), 4, reasons)
        text = ran.stdout.lower()
        for hidden in ('mismatch', 'axiom', '.ax', '.json', 'beryllattice', 'traceback', ' ns', ' us', 'time'):
            self.assertNotIn(hidden, text)
        self.assertNotIn('\\', ran.stdout)
        self.assertLessEqual(max(map(len, lines)), 90, ran.stdout)
        self.assertIn('6 candidates: 4 REFUSED, 2 ACCEPTED', ran.stdout)
        self.assertIn('every accepted plan matched the reference', lines[-1])

    def test_checker_codes_stay_available(self):
        demo = _demo_module()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = demo.main(['--source', str(PROGRAM), '--candidates', str(CURATED), '--no-time', '--codes'])
        self.assertEqual(code, 0)
        for reason in ('COVERAGE_MISMATCH', 'STRUCTURAL_MISMATCH', 'SEMANTIC_DIGEST_MISMATCH'):
            self.assertIn(reason, out.getvalue())
        self.assertLessEqual(max(map(len, out.getvalue().splitlines())), 90, out.getvalue())

    def test_timed_table_fits_90_columns(self):
        demo = _demo_module()
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(out), \
                mock.patch.object(demo, 'time_plan', lambda *a: 1_234_567 if a[3] != 'baseline' else 2_469_134):
            code = demo.main(['--source', str(PROGRAM), '--candidates', str(CURATED), '--out', tmp])
        self.assertEqual(code, 0)
        self.assertLessEqual(max(map(len, out.getvalue().splitlines())), 90, out.getvalue())
        self.assertIn('2.00x', out.getvalue())
        self.assertIn('every accepted plan matched the reference', out.getvalue().rstrip().splitlines()[-1])

    def test_unexpected_failure_is_one_line(self):
        demo = _demo_module()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out), \
                mock.patch.object(demo, 'review_candidates', side_effect=RuntimeError(str(PROGRAM))):
            code = demo.main(['--source', str(PROGRAM), '--candidates', str(CURATED), '--no-time'])
        self.assertEqual(code, 1)
        self.assertIn('beryl', out.getvalue())
        self.assertNotIn(str(ROOT), out.getvalue())
        self.assertNotIn('traceback', out.getvalue().lower())


def _walk(node):
    if isinstance(node, tuple) and node and isinstance(node[0], str):
        yield node
        for child in node[1:]:
            yield from _walk(child)


if __name__ == '__main__':
    unittest.main()
