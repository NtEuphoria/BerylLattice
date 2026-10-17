"""Portable corpus contracts and opt-in real pinned Core correspondence."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from tests.integration.corpus import (
    LANES, PLAN_IDS, QUICK_SHAPES, Campaign, expected_observation,
    conformance_manifest, nightly_cases, quick_cases, source_for,
)
from axiom.core_observe import Observation


class CorpusTests(unittest.TestCase):
    def test_mandatory_shape_pattern_and_boundary_coverage(self):
        cases = tuple(quick_cases())
        self.assertEqual(len(cases), 108)
        self.assertEqual(len({case.case_id for case in cases}), len(cases))
        self.assertEqual({case.shape for case in cases}, set(QUICK_SHAPES))
        for shape in QUICK_SHAPES:
            group = [case for case in cases if case.shape == shape]
            self.assertEqual(len(group), 18)
            for case in group:
                n = (shape[0]+1)*(shape[1]+1)
                self.assertEqual(len(case.data), n)
                self.assertEqual(len(case.initial_output), shape[0]*shape[1])
                expected = expected_observation(case)
                self.assertEqual(expected.input, case.data)
                bad = [i for i, value in enumerate(case.data) if not 0 <= value <= 1023]
                if bad:
                    self.assertEqual(expected.status, min(bad))
                    self.assertEqual(expected.output, case.initial_output)
                else:
                    self.assertEqual(expected.status, -1)
                self.assertEqual(case.as_dict()['input'], list(case.data))
            for value in (-1, 1024):
                for index in (0, n//2, n-1):
                    self.assertTrue(any(case.data[index] == value for case in group))

    def test_nightly_is_deliberate_sampling_with_all_h5w7_impulses(self):
        cases = tuple(nightly_cases())
        impulses = [case for case in cases if case.shape == (5, 7) and case.pattern.startswith('impulse-')]
        self.assertEqual(len(impulses), 48)
        self.assertEqual({case.data.index(1023) for case in impulses}, set(range(48)))
        self.assertTrue(any(h > 5 and w > 7 for h, w in (case.shape for case in cases)))
        self.assertLess(len(cases), 1000)

    def test_independent_oracle_uses_original_source_and_all_scalars(self):
        case = next(case for case in quick_cases() if case.shape == (1, 1) and case.pattern == 'coordinate-ramp')
        self.assertIn(b'output result', source_for(case))
        expected = expected_observation(case)
        self.assertEqual(expected, Observation(-1, (0, 1, 31, 32), (2118,)))
        self.assertEqual(PLAN_IDS, ('inline-v1', 'materialize-v1', 'rows2-v1'))
        self.assertEqual(LANES, (('reference', False), ('ast', False), ('ir', False), ('ast', True), ('ir', True)))

    def test_missing_explicit_prerequisites_are_unavailable(self):
        with self.assertRaisesRegex(unittest.SkipTest, 'unavailable'):
            Campaign.from_environment({})

    def test_manifest_is_self_contained_exact_source_for_cli(self):
        from hashlib import sha256
        manifest = json.loads(json.dumps(conformance_manifest()))
        self.assertEqual(manifest['artifact_kind'], 'core_correspondence_manifest')
        self.assertEqual(manifest['plans'], list(PLAN_IDS))
        self.assertEqual(len(manifest['cases']), 108)
        for case, entry in zip(quick_cases(), manifest['cases']):
            raw = entry['source_utf8'].encode('utf-8')
            self.assertEqual(entry['source_sha256'], sha256(raw).hexdigest())
            self.assertEqual(raw, source_for(case))
            self.assertEqual(entry['input'], list(case.data))

    def test_incomplete_native_matrix_cannot_create_success_receipt(self):
        with tempfile.TemporaryDirectory() as root:
            campaign = Campaign(Path(root), None)
            with self.assertRaisesRegex(AssertionError, 'Incomplete native campaign'):
                campaign.complete('quick', 1620)
            self.assertFalse((Path(root)/'quick-complete.json').exists())

    def test_duplicate_success_rows_cannot_replace_missing_cases(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as root:
            campaign = Campaign(Path(root), SimpleNamespace(receipt_path=Path(root)/'qualification.json'))
            row = dict(case_id=next(quick_cases()).case_id, plan_id=PLAN_IDS[0],
                       lane='reference', release=False, mutation=None, classification='matched')
            campaign.records = [row]*1620
            with self.assertRaisesRegex(AssertionError, 'Incomplete native campaign'):
                campaign.complete('quick', 1620)

    def test_native_worker_limit_is_explicit_and_bounded(self):
        from tests.integration.corpus import worker_limit
        self.assertEqual(worker_limit({}), 4)
        self.assertEqual(worker_limit({'AXIOM_CORE_WORKERS': '1'}), 1)
        for value in ('0', '5', '-1', 'true', '1.5'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                worker_limit({'AXIOM_CORE_WORKERS': value})


class ActualCorrespondenceTests(unittest.TestCase):
    def test_quick_mandatory_corpus_all_plans_all_lanes_and_native_o2(self):
        campaign = Campaign.from_environment()
        for label, error in campaign.run_matrix(tuple(quick_cases())):
            with self.subTest(case=label):
                if error is not None:
                    raise error
        campaign.complete('quick', 108*3*5)

    @unittest.skipUnless(os.environ.get('AXIOM_CORE_NIGHTLY') == '1', 'nightly native sampling requires AXIOM_CORE_NIGHTLY=1')
    def test_nightly_explicit_opt_in(self):
        campaign = Campaign.from_environment()
        cases = tuple(nightly_cases())
        for label, error in campaign.run_matrix(cases):
            with self.subTest(case=label):
                if error is not None:
                    raise error
        campaign.complete('nightly', len(cases)*3*5)


if __name__ == '__main__':
    unittest.main()
