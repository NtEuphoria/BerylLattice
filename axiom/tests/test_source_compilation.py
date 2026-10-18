"""Fresh source transactions and narrowly typed compact-lowering fallback."""
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
import importlib
import importlib.util
import unittest
from unittest.mock import patch
from axiom.bounded_loop_model import HintError
from axiom.compilation import _CompilationContext
from axiom.model import Limits
from tests.helpers import stencil_source

class SourceCompilationTests(unittest.TestCase):
    def compiler(self):
        self.assertIsNotNone(importlib.util.find_spec('axiom.source_compilation'),
                             'fresh source compilation coordinator is missing')
        return importlib.import_module('axiom.source_compilation')

    def test_fresh_source_compiles_both_backends_with_ranked_identity(self):
        compiler = self.compiler()
        source = stencil_source(5, 7, 64)
        for name in ('compile_native_source', 'compile_wasm_source'):
            with self.subTest(backend=name):
                result = getattr(compiler, name)(source)
                self.assertEqual(result.kernel.source_digest, sha256(source).hexdigest())
                self.assertEqual(result.search.policy_id, 'ranked-proof-v1')
                self.assertTrue(result.search.portfolio_optimal)
                self.assertEqual(result.artifact.plan_digest, result.search.selected_check.plan_digest)
                self.assertIsNotNone(result.artifact.hint_digest)
                self.assertIsNone(result.hint_failure)
                with self.assertRaises(FrozenInstanceError):
                    result.kernel = None

    def test_every_call_admits_fresh_and_closes_its_context(self):
        compiler = self.compiler()
        contexts = []
        def context(*args, **kwargs):
            result = _CompilationContext(*args, **kwargs)
            contexts.append(result)
            return result
        with patch.object(compiler, '_CompilationContext', side_effect=context):
            for _ in range(2):
                compiler.compile_wasm_source(stencil_source(1, 1, 0))
        self.assertEqual(len(contexts), 2)
        self.assertIsNot(contexts[0], contexts[1])
        for context in contexts:
            with self.assertRaises(ValueError):
                context._live()

    def test_typed_hint_failure_uses_finite_fallback_but_fault_propagates(self):
        compiler = self.compiler()
        for compact, name in (('_compile_wasm_compact', 'compile_wasm_source'),
                              ('_emit_native_c_compact', 'compile_native_source')):
            with self.subTest(backend=name):
                with patch.object(compiler, compact, side_effect=HintError('INVALID_HINT', 'bad hint')):
                    result = getattr(compiler, name)(stencil_source(1, 1, 0))
                self.assertEqual(result.hint_failure, 'INVALID_HINT')
                self.assertIsNone(result.artifact.hint_digest)
                with patch.object(compiler, compact, side_effect=RuntimeError('emitter fault')):
                    with self.assertRaisesRegex(RuntimeError, 'emitter fault'):
                        getattr(compiler, name)(stencil_source(1, 1, 0))

    def test_unknown_search_emits_no_artifact(self):
        result = self.compiler().compile_wasm_source(stencil_source(1, 1, 0), Limits(check_steps=1))
        self.assertIsNone(result.artifact)
        self.assertFalse(result.search.portfolio_optimal)
        self.assertIsNone(result.hint_failure)

    def test_relabelled_valid_finite_plan_keeps_schedule_intent_untrusted(self):
        compiler = self.compiler()
        from axiom import compilation_selection
        from axiom.planner import make_plan
        def relabel(kernel, candidate_id):
            return replace(make_plan(kernel, candidate_id), plan_id='renamed-' + candidate_id)
        with patch.object(compilation_selection, 'make_plan', side_effect=relabel):
            result = compiler.compile_wasm_source(stencil_source(5, 7, 64))
        self.assertEqual(result.search.selected_plan.plan_id, 'renamed-rows2-v1')
        self.assertIsNotNone(result.artifact.hint_digest)
        self.assertIsNone(result.hint_failure)

    def test_unmatched_valid_finite_stream_falls_back_without_discarding_dead_operations(self):
        compiler = self.compiler()
        from axiom import compilation_selection
        from axiom.planner import make_plan
        from axiom.plan_format import Operation
        def with_dead_operation(kernel, candidate_id):
            plan = make_plan(kernel, candidate_id)
            register = max(op.dst for op in plan.operations if op.dst is not None) + 1
            return replace(plan, operations=plan.operations + (Operation('const', register, value=7),))
        with patch.object(compilation_selection, 'make_plan', side_effect=with_dead_operation):
            result = compiler.compile_wasm_source(stencil_source(1, 1, 0))
        self.assertTrue(result.search.selected_check.eligible)
        self.assertEqual(result.search.selected_plan.operations[-1].value, 7)
        self.assertIsNotNone(result.hint_failure)
        self.assertIsNone(result.artifact.hint_digest)
