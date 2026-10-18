"""Exact structural diagnostics against the immutable pre-optimization codec."""
import cProfile
import dis
from dataclasses import replace
import hashlib
from pathlib import Path
import sys
import types
import unittest

from axiom import codec, planner
from axiom.frontend import admit_source, parse_source
from axiom.model import Limits
from axiom.plan_format import Operation, Plan
from tests.helpers import stencil_source


BASELINE = '21f36d4e977ff950276fbfff6198d8640bb24029'
BASELINE_SHA256 = '5c8c67adb70760ffe7b4907701e8655a4af7b21d17cec26c5aba4247c46ebf49'


def all_shapes():
    return Plan(1, 'a' * 64, 'label " \\ \n 🧮', 12, (
        Operation('const', dst=0, value=-2147483648, origins=(0, 10, 9999999999)),
        Operation('input_load', dst=1, index=9999999999),
        Operation('add', dst=2, operands=(0, 1)),
        Operation('mul', dst=3, operands=(1, 2), origins=(99,)),
        Operation('scratch_store', operands=(3,), index=11),
        Operation('scratch_load', dst=4, index=11),
        Operation('output_store', operands=(4,), index=9999999999),
    ))


class ValidationHotpathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The baseline is executed only by tests, in a separate module. It does
        # not share validator helpers with the implementation under comparison.
        # Frozen verbatim with git show <BASELINE>:axiom/src/axiom/codec.py.
        # Runtime tests need neither Git nor the historical commit object.
        source = (Path(__file__).parent / 'fixtures' / 'codec-21f36d4.py.txt').read_bytes()
        if hashlib.sha256(source).hexdigest() != BASELINE_SHA256:
            raise AssertionError('immutable prior codec fixture changed')
        cls.prior = types.ModuleType('axiom._prior_codec_validation_hotpath')
        cls.prior.__package__ = 'axiom'
        exec(compile(source, '<codec at ' + BASELINE + '>', 'exec'), cls.prior.__dict__)

    def outcome(self, module, plan, limits, method='_validate_plan'):
        try:
            result = getattr(module, method)(plan, limits) if method != 'encode_plan' else (
                module.encode_plan(plan, limits=limits))
            return ('ok', result)
        except module.DecodeError as error:
            return (error.code, error.field_path, str(error))

    def assert_same(self, plan, limits=Limits(), method='_validate_plan'):
        self.assertEqual(self.outcome(codec, plan, limits, method),
                         self.outcome(self.prior, plan, limits, method))

    def test_success_formats_no_diagnostic_field_paths(self):
        # Count executed lines containing formatting opcodes, independent of
        # machine speed. Successful scans must not format error paths. Line
        # tracing also works in runtimes that disable opcode tracing.
        code = codec._validate_plan.__code__
        formatting = {instruction.positions.lineno for instruction in dis.get_instructions(code)
                      if instruction.opname in ('FORMAT_VALUE', 'FORMAT_SIMPLE',
                                                'FORMAT_WITH_SPEC')}
        seen = []

        def trace(frame, event, arg):
            if frame.f_code is code:
                if event == 'line' and frame.f_lineno in formatting:
                    seen.append(frame.f_lineno)
                return trace

        previous = sys.gettrace()
        try:
            sys.settrace(trace)
            metrics = codec._validate_plan(all_shapes(), Limits())
        finally:
            sys.settrace(previous)
        self.assertEqual(metrics, (1, 48))
        self.assertEqual(seen, [], 'valid records eagerly format diagnostic field paths')

    def test_success_avoids_generic_integer_helper_for_operands_and_origins(self):
        with cProfile.Profile() as profile:
            codec.validate_plan(all_shapes(), Limits())
        calls = sum(entry.callcount for entry in profile.getstats()
                    if entry.code is codec._integer.__code__)
        self.assertLessEqual(calls, 2, 'only the two fixed header fields need generic checks')

    def test_all_shapes_and_generated_candidates_preserve_metrics_and_bytes(self):
        kernel = admit_source(parse_source(stencil_source(2, 3, None)))
        plans = [all_shapes(), replace(all_shapes(), operations=())]
        plans.extend(planner.make_plan(kernel, label) for label in planner.PLAN_IDS)
        for plan in plans:
            with self.subTest(label=plan.plan_id):
                self.assert_same(plan)
                self.assert_same(plan, method='encode_plan')
                self.assertEqual(codec._validate_plan(plan, Limits()), (
                    sum(op.opcode == 'mul' for op in plan.operations),
                    4 * plan.scratch_capacity_cells))
                encoded = codec.encode_plan(plan)
                self.assertEqual(codec.decode_plan(encoded, Limits()), plan)
                self.assertIsNone(codec.validate_plan(plan, Limits()))

    def test_malformed_records_preserve_exact_first_error(self):
        base = all_shapes()
        bad_scalars = (True, False, None, -1, 10000000000, '0', 1.0)
        mutations = [None, {}, replace(base, operations=list(base.operations)),
                     replace(base, operations=(None,)), replace(base, plan_id='\ud800'),
                     replace(base, plan_id=''), replace(base, plan_id='é' * 129),
                     replace(base, semantic_digest='A' * 64)]
        for field in ('format_version', 'scratch_capacity_cells'):
            mutations.extend(replace(base, **{field: value}) for value in bad_scalars)
        mutations.append(replace(base, format_version=2))
        mutations.append(replace(base, scratch_capacity_cells=2147483648))
        for i, op in enumerate(base.operations):
            changes = [('opcode', value) for value in (True, None, 'unknown')]
            changes += [(field, value) for field in ('dst', 'index', 'value')
                        for value in bad_scalars]
            changes += [('operands', value) for value in (None, [], (), (0, 1, 2))]
            changes += [('origins', value) for value in (None, [], (True,), (-1,),
                                                        (None,), (10000000000,))]
            changes += [('dst', 999), ('index', 12), ('value', -2147483649),
                        ('value', 2147483648)]
            if op.operands:
                changes += [('operands', (value,) + op.operands[1:])
                            for value in (*bad_scalars, 9999999999)]
            for field, value in changes:
                altered = replace(op, **{field: value})
                mutations.append(replace(base, operations=(
                    base.operations[:i] + (altered,) + base.operations[i + 1:])))
        for i, plan in enumerate(mutations):
            with self.subTest(mutation=i):
                self.assert_same(plan)
                self.assert_same(plan, replace(Limits(), plan_bytes=220))
        for field in ('plan_bytes', 'plan_operations'):
            for value in (True, False, 0, -1, None, 1.0):
                with self.subTest(limit=field, value=value):
                    limits = types.SimpleNamespace(plan_bytes=Limits().plan_bytes,
                                                   plan_operations=Limits().plan_operations)
                    setattr(limits, field, value)
                    self.assert_same(base, limits)
        self.assert_same(base, replace(Limits(), plan_operations=1))

    def test_every_small_plan_byte_boundary_preserves_quota_path_and_precedence(self):
        base = all_shapes()
        small = replace(base, operations=base.operations[:1])
        two_operations = replace(base, operations=base.operations[:2])
        invalid_origin = replace(small, operations=(replace(small.operations[0],
                                                          origins=(0, 10, True)),))
        for plan in (replace(small, operations=()), small, two_operations, invalid_origin):
            for budget in range(1, len(self.prior.encode_plan(two_operations)) + 2):
                with self.subTest(operations=len(plan.operations), budget=budget,
                                  invalid_origin=plan is invalid_origin):
                    limits = replace(Limits(), plan_bytes=budget)
                    self.assert_same(plan, limits)
                    self.assert_same(plan, limits, method='encode_plan')


if __name__ == '__main__':
    unittest.main()
