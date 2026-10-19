"""Compact loop hints for window-stencil kernels: exact correspondence or fallback.

A hint is untrusted. These controls require every family hint to expand to the
exact checked plan, tampered hints to be refused, compact Wasm to leave all
64 KiB of memory identical to finite Wasm, and both to equal the reference.
"""
from dataclasses import replace
import unittest

from axiom.bounded_loop_codec import encode_loop_program
from axiom.bounded_loop_correspondence import validate_loop_correspondence
from axiom.bounded_loop_model import HintError
from axiom.compilation import _CompilationContext
from axiom.frontend import admit_source, parse_source
from axiom.model import Limits
from axiom.native_codegen import emit_native_c
from axiom.planner import make_plan, plan_ids
from axiom.reference import evaluate_source
from axiom.source_compilation import compile_native_source, compile_wasm_source
from axiom.wasm import _compile_wasm_checked
from axiom.window_loop_planner import make_window_loop_program
from tests.helpers import stencil_source
from tests import test_bounded_loop_wasm as wasm_tests
from tests.test_window_family import SHAPES, source


def owned(src, schedule):
    context = _CompilationContext(src)
    candidate = context.candidate(make_plan(context.kernel, schedule))
    return context.authorize(candidate, context.check(candidate))


class WindowCompactTests(unittest.TestCase):
    def test_every_hint_expands_to_the_exact_checked_plan(self):
        for name, shapes in SHAPES.items():
            for h, w in shapes:
                kernel = admit_source(parse_source(source(name, h, w)))
                for plan_id in plan_ids(kernel):
                    with self.subTest(program=name, shape=(h, w), plan=plan_id):
                        hint = encode_loop_program(make_window_loop_program(kernel, plan_id))
                        validate_loop_correspondence(kernel, make_plan(kernel, plan_id), hint, Limits())

    def test_tampered_hints_are_refused(self):
        kernel = admit_source(parse_source(source('conv3x3', 3, 5)))
        plan = make_plan(kernel, 'rows-v1')
        program = make_window_loop_program(kernel, 'rows-v1')
        body = list(program.body)
        body[0] = replace(body[0], value=body[0].value + 1)  # first prologue constant
        for label, tampered in (('constant', replace(program, body=tuple(body))),
                                ('reservation', replace(program, scratch_capacity_cells=program.scratch_capacity_cells + 1)),
                                ('truncated', replace(program, body=program.body[:-1]))):
            with self.subTest(change=label), self.assertRaises(HintError):
                validate_loop_correspondence(kernel, plan, encode_loop_program(tampered), Limits())
        other = admit_source(parse_source(source('box3x3', 3, 5)))
        with self.assertRaises(HintError):  # a hint is bound to its own kernel
            validate_loop_correspondence(other, make_plan(other, 'rows-v1'),
                                         encode_loop_program(program), Limits())

    def test_family_compilation_uses_compact_loops(self):
        for name in SHAPES:
            h, w = SHAPES[name][-1]
            for compile_source in (compile_native_source, compile_wasm_source):
                with self.subTest(program=name, backend=compile_source.__name__):
                    compiled = compile_source(source(name, h, w, 1024))
                    self.assertIsNone(compiled.hint_failure)
                    self.assertIn('bounded-loop', compiled.artifact.codegen_version)

    def test_compact_wasm_equals_finite_wasm_and_reference(self):
        runner = wasm_tests.CompactWasmTests('run_modules')  # reuse its Node runner only
        from axiom.bounded_loop_wasm import _compile_wasm_compact
        for name in SHAPES:
            h, w = SHAPES[name][0] if name == 'stencil1d3' else (3, 5) if name != 'polymap' else (4, 4)
            src = source(name, h, w)
            kernel = admit_source(parse_source(src))
            for plan_id in plan_ids(kernel):
                with self.subTest(program=name, plan=plan_id):
                    own = owned(src, plan_id)
                    hint = encode_loop_program(make_window_loop_program(kernel, plan_id))
                    runs = []
                    for pattern in (0, 1023, 'hash', 'bad'):
                        data = ([(i * 2654435761 & 0xFFFFFFFF) >> 22 for i in range(kernel.input_count)]
                                if pattern in ('hash', 'bad') else [pattern] * kernel.input_count)
                        if pattern == 'bad':
                            data[kernel.input_count // 2] = 1024
                        runs.append(dict(input=data, initial=[-7] * kernel.output_count))
                    compact, finite = (_compile_wasm_compact(own, hint), _compile_wasm_checked(own))
                    compact_runs, finite_runs = runner.run_modules([runner.case(a, runs) for a in (compact, finite)])
                    self.assertEqual(compact_runs, finite_runs)
                    for request, result in zip(runs, compact_runs):
                        expected = evaluate_source(kernel.source_module, request['input'], request['initial'])
                        self.assertEqual(result['output'], list(expected.output))
                        self.assertEqual(result['status'], 0 if expected.first_bad_index is None else expected.first_bad_index + 1)

    def test_finite_c_fast_preflight_only_for_family_kernels(self):
        canonical = stencil_source(5, 7, None)
        k = admit_source(parse_source(canonical))
        legacy = emit_native_c(canonical, _plan_bytes(k, 'inline-v1')).c_source
        self.assertNotIn(b'ax_invalid', legacy)  # published canonical bytes keep the legacy preflight
        src = source('conv3x3', 3, 5)
        kernel = admit_source(parse_source(src))
        family = emit_native_c(src, _plan_bytes(kernel, 'rows-v1')).c_source
        self.assertIn(b'ax_invalid', family)
        self.assertIn(b'restrict', family)


def _plan_bytes(kernel, plan_id):
    from axiom.codec import encode_plan
    return encode_plan(make_plan(kernel, plan_id))


if __name__ == '__main__':
    unittest.main()
