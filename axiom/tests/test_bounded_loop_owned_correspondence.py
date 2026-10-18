"""Owned correspondence reuses finite authority but freshly validates every hint."""
from dataclasses import replace
from hashlib import sha256
import unittest
from unittest.mock import patch

from axiom import bounded_loop_correspondence as correspondence, codec
from axiom.bounded_loop_codec import encode_loop_program
from axiom.bounded_loop_model import HintError, HintLimits, Loop, Primitive
from axiom.bounded_loop_planner import make_loop_program
from axiom.compilation import _CompilationContext
from axiom.model import Limits
from axiom.planner import make_plan
from tests.helpers import stencil_source


class OwnedCorrespondenceTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(hasattr(correspondence, '_validate_owned_loop_correspondence'),
                        'owned correspondence entry has not been implemented')
        self.match = correspondence._validate_owned_loop_correspondence

    def owned(self, h=3, w=4, schedule='rows2-v1', *, source=None, plan=None, limits=Limits()):
        context = _CompilationContext(source or stencil_source(h, w, None), limits)
        candidate = context.candidate(plan or make_plan(context.kernel, schedule))
        checked = context.check(candidate)
        self.assertTrue(checked.eligible)
        owned = context.authorize(candidate, checked)
        hint = encode_loop_program(make_loop_program(context.kernel, schedule))
        self.addCleanup(context.close)
        return owned, hint

    def test_no_finite_validation_or_encoding_after_owned_check(self):
        owned, hint = self.owned()
        with patch.object(correspondence, 'validate_plan', wraps=codec.validate_plan) as validated, \
             patch.object(correspondence, 'encode_plan', wraps=codec.encode_plan) as encoded, \
             patch.object(codec, '_validate_plan', wraps=codec._validate_plan) as scans, \
             patch.object(codec, '_encode_validated_plan', wraps=codec._encode_validated_plan) as serializations, \
             patch.object(correspondence, 'decode_loop_program', wraps=correspondence.decode_loop_program) as decoded:
            result = self.match(owned, hint)
        self.assertEqual(validated.call_count, 0)
        self.assertEqual(encoded.call_count, 0)
        self.assertEqual(scans.call_count, 0)
        self.assertEqual(serializations.call_count, 0)
        self.assertEqual(decoded.call_count, 1)
        self.assertIs(result.plan, owned.plan)
        self.assertEqual(result.plan_digest, sha256(owned.plan_bytes).hexdigest())
        self.assertEqual(result.plan_digest, owned.checked.plan_digest)
        self.assertEqual(result.source_digest, sha256(owned.source).hexdigest())
        self.assertEqual(result.semantic_digest, owned.kernel.semantic_digest)
        self.assertEqual(result.hint_bytes, hint)
        self.assertEqual(result.hint_digest, sha256(hint).hexdigest())
        self.assertEqual(result.expanded_operations, len(owned.plan.operations))
        self.assertFalse(hasattr(result, 'eligible'))

    def test_both_backends_use_owned_path_without_finite_rescans(self):
        from axiom.bounded_loop_c import _emit_native_c_compact
        from axiom.bounded_loop_wasm import _compile_wasm_compact
        from axiom.compilation_trace import CompilationTrace
        owned, hint = self.owned()
        trace = CompilationTrace()
        owned.owner.trace = trace
        with patch.object(codec, '_validate_plan', wraps=codec._validate_plan) as validated, \
             patch.object(codec, '_encode_validated_plan', wraps=codec._encode_validated_plan) as encoded, \
             patch.object(correspondence, 'decode_loop_program', wraps=correspondence.decode_loop_program) as decoded:
            native = _emit_native_c_compact(owned, hint)
            wasm = _compile_wasm_compact(owned, hint)
        self.assertEqual(validated.call_count, 0)
        self.assertEqual(encoded.call_count, 0)
        self.assertEqual(decoded.call_count, 2)
        self.assertEqual(native.plan_digest, owned.checked.plan_digest)
        self.assertEqual(wasm.plan_digest, owned.checked.plan_digest)
        self.assertEqual(trace.report()['counts']['loop_correspondences'], 2)
        self.assertEqual(trace.report()['counts'].get('plan_validations', 0), 0)
        self.assertEqual(trace.report()['counts'].get('plan_encodes', 0), 0)

    def test_public_validator_and_expander_still_validate_finite_records(self):
        owned, hint = self.owned()
        with patch.object(correspondence, 'validate_plan', wraps=codec.validate_plan) as validated, \
             patch.object(correspondence, 'encode_plan', wraps=codec.encode_plan) as encoded:
            public = correspondence.validate_loop_correspondence(owned.kernel, owned.plan, hint, owned.limits)
            expanded = correspondence.expand_loop_program(owned.kernel, public.program, owned.limits)
        self.assertEqual(validated.call_count, 3)
        self.assertEqual(encoded.call_count, 1)
        self.assertEqual(expanded, public.expanded_plan)
        private = self.match(owned, hint)
        self.assertEqual(private.work_steps, public.work_steps)
        self.assertEqual(private.program, public.program)
        self.assertEqual(private.plan_digest, public.plan_digest)
        with self.assertRaises(codec.DecodeError):
            correspondence.validate_loop_correspondence(owned.kernel,
                replace(owned.plan, operations=list(owned.plan.operations)), hint, owned.limits)

    def test_forged_closed_and_cross_context_substitution_rejected_before_decode(self):
        owned, hint = self.owned()
        other, _ = self.owned(4, 3)
        for bad in (None, owned.checked, replace(owned), replace(owned, owner=other.owner),
                    replace(owned, plan=other.plan), replace(owned, kernel=other.kernel),
                    replace(owned, checked=other.checked), replace(owned, plan_bytes=other.plan_bytes)):
            with self.subTest(bad=bad), \
                 patch.object(correspondence, 'decode_loop_program', wraps=correspondence.decode_loop_program) as decoded:
                with self.assertRaises(ValueError):
                    self.match(bad, hint)
                self.assertEqual(decoded.call_count, 0)
        owned.owner.close()
        with self.assertRaises(ValueError):
            self.match(owned, hint)

    def test_same_semantics_different_raw_source_and_other_shape_reject(self):
        owned, hint = self.owned()
        whitespace, _ = self.owned(source=b' '+owned.source)
        self.assertEqual(owned.kernel.semantic_digest, whitespace.kernel.semantic_digest)
        other, _ = self.owned(4, 3)
        for changed in (whitespace, other):
            with self.assertRaises(HintError):
                self.match(changed, hint)
        spaced = b' '+hint+b'\n'
        result = self.match(owned, spaced)
        self.assertEqual(result.hint_bytes, spaced)
        self.assertNotEqual(result.hint_digest, self.match(owned, hint).hint_digest)

    def test_metadata_does_not_authorize_or_reject_matching_stream(self):
        owned, hint = self.owned()
        program = make_loop_program(owned.kernel, 'rows2-v1')
        changed = replace(program, label='unrelated label', body=(
            replace(program.body[0], origins=(17, 19)),)+program.body[1:])
        result = self.match(owned, encode_loop_program(changed))
        self.assertIs(result.plan, owned.plan)
        renamed = replace(owned.plan, plan_id='unrelated finite label')
        renamed_owned, _ = self.owned(plan=renamed)
        self.match(renamed_owned, hint)

    def test_complete_stream_count_grouping_capacity_and_specialization(self):
        owned, hint = self.owned()
        program = make_loop_program(owned.kernel, 'rows2-v1')
        body = program.body
        changes = (replace(program, scratch_capacity_cells=program.scratch_capacity_cells+1),
                   replace(program, source_digest='0'*64),
                   replace(program, semantic_digest='0'*64),
                   replace(program, body=body[:-1]),
                   replace(program, body=body+(body[-1],)),
                   replace(program, body=body+(Primitive('const', 'dead', value=0),)),
                   replace(program, body=(replace(body[0], value=2),)+body[1:]))
        for changed in changes:
            with self.subTest(changed=changed), self.assertRaises(HintError):
                self.match(owned, encode_loop_program(changed))
        # An owned, semantically valid plan with a dead suffix is not equivalent
        # as an executable stream, even though its visible result is identical.
        from axiom.plan_format import Operation
        dst = 1+max(op.dst for op in owned.plan.operations if op.dst is not None)
        plan = replace(owned.plan, operations=owned.plan.operations+(Operation('const', dst, value=0),))
        suffixed, _ = self.owned(plan=plan)
        with self.assertRaises(HintError):
            self.match(suffixed, hint)

    def test_malformed_hints_and_exact_work_budget_still_reject(self):
        owned, hint = self.owned()
        for bad in (b'{', hint+b' trailing', b'['*1000+b']'*1000, b'x'*65537):
            with self.assertRaises(HintError):
                self.match(owned, bad)
        result = self.match(owned, hint)
        self.match(owned, hint, HintLimits(work_steps=result.work_steps))
        with self.assertRaises(HintError) as caught:
            self.match(owned, hint, HintLimits(work_steps=result.work_steps-1))
        self.assertEqual(caught.exception.code, 'HINT_WORK_LIMIT')
        program = make_loop_program(owned.kernel, 'rows2-v1')
        empty = Loop('a', 0, 256, (Loop('b', 0, 256, (Loop('c', 0, 256, ()),)),))
        with self.assertRaises(HintError) as caught:
            self.match(owned, encode_loop_program(replace(program, body=(empty,))))
        self.assertEqual(caught.exception.code, 'HINT_WORK_LIMIT')


if __name__ == '__main__':
    unittest.main()
