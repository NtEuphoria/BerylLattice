"""Faulty-emitter controls rehash artifacts, then face an independent oracle."""
from dataclasses import replace
from hashlib import sha256
import re
import unittest

from axiom.codec import canonical_json
from axiom.core_runner import _validate_bundle
from tests.integration.corpus import Campaign, CorpusMismatch, LANES, PLAN_IDS, quick_cases


def mutate_bundle(bundle, mutation):
    kernel = bundle.kernel_source_bytes
    if mutation == 'wrong-neighbor':
        kernel, count = re.subn(rb'(let ax_v[0-9]+: i32 = input\[)0(\])', rb'\g<1>1\2', kernel, count=1)
        if count != 1:
            raise AssertionError('Mutation did not change an input read')
    elif mutation == 'drop-final-store':
        stores = tuple(re.finditer(rb'    output\[[0-9]+\] = ax_v[0-9]+\n', kernel))
        if not stores:
            raise AssertionError('Mutation found no output stores')
        store = stores[-1]
        kernel = kernel[:store.start()] + b' '*(len(store[0])-1)+b'\n'+kernel[store.end():]
    elif mutation == 'shift-failure-index':
        if kernel.count(b'{ return 47 }') != 1:
            raise AssertionError('Failure-index control requires H5/W7 last input')
        kernel = kernel.replace(b'{ return 47 }', b'{ return 46 }', 1)
    else:
        raise ValueError('Unknown mutation')
    # Preserve mapping extents while rebinding every source identity, as a
    # consistently faulty source emitter would do. Identity alone must pass.
    if len(kernel) != len(bundle.kernel_source_bytes) or kernel == bundle.kernel_source_bytes:
        raise AssertionError('Mutation must alter exact bytes without shifting mappings')
    source = kernel+bundle.source_bytes[len(bundle.kernel_source_bytes):]
    digest = sha256(source).hexdigest()
    changed = replace(bundle, source_bytes=source, source_sha256=digest,
                      kernel_source_bytes=kernel, kernel_source_sha256=sha256(kernel).hexdigest(),
                      mappings=tuple(replace(mapping, generated_source_sha256=digest) for mapping in bundle.mappings))
    identity = canonical_json(dict(version=1, artifact_kind='core_witness_source',
        source_digest=changed.source_digest, plan_digest=changed.plan_digest,
        plan_bytes_sha256=changed.plan_bytes_sha256, emitter_digest=changed.emitter_digest,
        generated_source_sha256=changed.generated_source_sha256,
        data=list(changed.data), initial_output=list(changed.initial_output)))
    return replace(changed, case_digest=sha256(identity).hexdigest())


class MutationControls(unittest.TestCase):
    def test_rehashed_faults_preserve_validated_bundle_identity(self):
        from axiom.codec import encode_plan
        from axiom.core_emit import emit_core
        from axiom.frontend import admit_source, parse_source
        from axiom.model import Limits
        from axiom.planner import make_plan
        from tests.integration.corpus import source_for
        for mutation in ('wrong-neighbor', 'drop-final-store', 'shift-failure-index'):
            case = next(case for case in quick_cases() if case.shape == (5, 7) and case.pattern ==
                        ('invalid-1024-last' if mutation == 'shift-failure-index' else 'coordinate-ramp'))
            source = source_for(case)
            for plan_id in PLAN_IDS:
                with self.subTest(mutation=mutation, plan=plan_id):
                    bundle = emit_core(source, encode_plan(make_plan(admit_source(parse_source(source)), plan_id)),
                                       Limits(), case.data, case.initial_output)
                    faulty = mutate_bundle(bundle, mutation)
                    self.assertNotEqual(faulty.source_bytes, bundle.source_bytes)
                    self.assertNotEqual(faulty.case_digest, bundle.case_digest)
                    self.assertEqual(faulty.generated_source_sha256, sha256(faulty.source_bytes).hexdigest())
                    _validate_bundle(faulty)

    def test_independent_oracle_rejects_all_rehashed_faults_when_core_lanes_agree(self):
        campaign = Campaign.from_environment()
        count = 0
        for mutation in ('wrong-neighbor', 'drop-final-store', 'shift-failure-index'):
            case = next(case for case in quick_cases() if case.shape == (5, 7) and case.pattern ==
                        ('invalid-1024-last' if mutation == 'shift-failure-index' else 'coordinate-ramp'))
            for plan_id in PLAN_IDS:
                faulty = mutate_bundle(campaign.bundle(case, plan_id), mutation)
                for lane, release in LANES:
                    with self.subTest(mutation=mutation, plan=plan_id, lane=lane, release=release):
                        with self.assertRaisesRegex(CorpusMismatch, 'independent source oracle'):
                            campaign.check(case, plan_id, faulty, lane, release, mutation=mutation)
                        row = campaign.records[-1]
                        self.assertEqual(row['classification'], 'semantic_mismatch')
                        self.assertEqual(row['run']['classification'], 'success')
                        if lane != 'reference':
                            self.assertEqual(row['observations']['reference'], row['observations']['native'])
                        count += 1
        self.assertEqual(count, 45)


if __name__ == '__main__':
    unittest.main()
