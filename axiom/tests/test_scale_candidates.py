"""Untrusted candidate loop plans: decoded safely, checked, and verified when accepted."""
import dataclasses
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
        self.assertIn('2 candidates: 1 rejected', ran.stdout)
        self.assertNotIn('axiom', ran.stdout.lower())

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


if __name__ == '__main__':
    unittest.main()
