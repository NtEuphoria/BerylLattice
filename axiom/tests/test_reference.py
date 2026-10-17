import ast
import dataclasses
import inspect
import json
from pathlib import Path
import sys
import unittest

from axiom.frontend import parse_source
from axiom.model import DiagnosticError
from axiom.reference import ExecutionResult, evaluate_source
from tests.helpers import stencil_source


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.module = parse_source(stencil_source(1, 1))

    def test_exact_boundary_fixtures(self):
        fixtures = json.loads((Path(__file__).parent / 'fixtures/inputs/boundary_cases.json').read_text())
        for name in ('all_zero', 'all_max', 'bottom_right_one'):
            case = fixtures[name]
            with self.subTest(name=name):
                data = tuple(case['input'])
                result = evaluate_source(self.module, data, (-777,))
                self.assertEqual(result.status, 'success')
                self.assertIsNone(result.first_bad_index)
                self.assertEqual(result.output, tuple(case['output']))
                self.assertEqual(result.input_after, data)
                self.assertIsInstance(result, ExecutionResult)
                with self.assertRaises(dataclasses.FrozenInstanceError):
                    result.status = 'changed'

    def test_coordinate_sensitive_h5_w7(self):
        height, width = 5, 7
        data = tuple((row * 73 + column * 19 + row * column * 11) % 1024
                     for row in range(height + 1) for column in range(width + 1))
        expected = tuple(sum((data[(row + dr) * (width + 1) + column + dc] + 1) ** 2
                             for dr, dc in ((0, 0), (0, 1), (1, 0), (1, 1)))
                         for row in range(height) for column in range(width))
        result = evaluate_source(parse_source(stencil_source(height, width)), data, (-777,) * 35)
        self.assertEqual(result.status, 'success')
        self.assertEqual(result.output, expected)
        self.assertEqual(result.input_after, data)

    def test_alpha_renamed_original_ast(self):
        source = stencil_source(1, 1)
        import re
        names = {b'image': b'pixels', b'p': b'tmp', b'result': b'answer',
                 b'r': b'y', b'c': b'x', b'H': b'Rows', b'W': b'Cols'}
        source = re.sub(rb'\b(image|p|result|r|c|H|W)\b', lambda match: names[match[0]], source)
        result = evaluate_source(parse_source(source), (0, 0, 0, 1), (-777,))
        self.assertEqual(result.output, (7,))

    def test_preflight_first_failure_preserves_destination(self):
        data, destination = (1024, -1, 0, 0), (-777,)
        result = evaluate_source(self.module, data, destination)
        self.assertEqual(result.status, 'input_precondition_failed')
        self.assertEqual(result.first_bad_index, 0)
        self.assertEqual(result.output, destination)
        self.assertEqual(result.input_after, data)

    def test_every_preflight_position_and_full_output_preservation(self):
        module = parse_source(stencil_source(2, 3))
        destination = tuple(-777 - i for i in range(6))
        for index in range(12):
            for bad in (-1, 1024):
                data = [0] * 12
                data[index] = bad
                result = evaluate_source(module, data, list(destination))
                with self.subTest(index=index, bad=bad):
                    self.assertEqual(result.first_bad_index, index)
                    self.assertEqual(result.output, destination)
                    self.assertEqual(result.input_after, tuple(data))

    def test_no_equation_visits_until_complete_preflight(self):
        import axiom.reference as reference
        visits = []
        def record(frame, event, arg):
            if event == 'call' and frame.f_code is reference._evaluate_equation.__code__:
                visits.append(frame.f_code.co_name)
        previous = sys.getprofile()
        try:
            sys.setprofile(record)
            evaluate_source(self.module, (0, 0, 0, 1024), (-777,))
            self.assertEqual(visits, [])
            evaluate_source(self.module, (0, 0, 0, 0), (-777,))
            self.assertGreater(len(visits), 0)
        finally:
            sys.setprofile(previous)

    def diagnostic(self, data, output, code):
        with self.assertRaises(DiagnosticError) as caught:
            evaluate_source(self.module, data, output)
        self.assertEqual(caught.exception.code, code)

    def test_boundary_rejects_container_and_scalar_types(self):
        for data in (None, '0000', iter((0, 0, 0, 0))):
            self.diagnostic(data, (-777,), 'BOUNDARY_TYPE')
        for output in (None, '-777', iter((-777,))):
            self.diagnostic((0, 0, 0, 0), output, 'BOUNDARY_TYPE')
        for value in (False, True, 0.0, 1.5, '0', None):
            self.diagnostic((0, 0, 0, value), (-777,), 'BOUNDARY_TYPE')
            self.diagnostic((0, 0, 0, 0), (value,), 'BOUNDARY_TYPE')

    def test_boundary_rejects_wrong_extents(self):
        for data in ((), (0,) * 3, (0,) * 5):
            self.diagnostic(data, (-777,), 'BOUNDARY_LENGTH')
        for output in ((), (-777,) * 2):
            self.diagnostic((0,) * 4, output, 'BOUNDARY_LENGTH')

    def test_boundary_rejects_non_i32_values(self):
        for value in (-(2 ** 31) - 1, 2 ** 31):
            self.diagnostic((0, 0, 0, value), (-777,), 'BOUNDARY_I32')
            self.diagnostic((0,) * 4, (value,), 'BOUNDARY_I32')
        for value in (-(2 ** 31), 2 ** 31 - 1):
            result = evaluate_source(self.module, (0, 0, 0, value), (-777,))
            self.assertEqual(result.status, 'input_precondition_failed')

    def test_owned_lists_remain_unchanged(self):
        data, output = [0, 0, 0, 1], [-777]
        result = evaluate_source(self.module, data, output)
        self.assertEqual(result.output, (7,))
        self.assertEqual(data, [0, 0, 0, 1])
        self.assertEqual(output, [-777])

    def test_admission_precedes_runtime_boundary(self):
        unsupported = parse_source(stencil_source(1, 1).replace(b'image[r,c]+1', b'image[r,c]+2'))
        with self.assertRaises(DiagnosticError) as caught:
            evaluate_source(unsupported, (), ())
        self.assertEqual(caught.exception.code, 'UNSUPPORTED_PROFILE')

    def test_reference_has_no_plan_implementation_dependencies(self):
        import axiom.reference as reference
        module_ast = ast.parse(inspect.getsource(reference))
        forbidden = {'planner', 'checker', 'plan_format', 'selection', 'core_emit'}
        imported = []
        for node in ast.walk(module_ast):
            if isinstance(node, ast.ImportFrom):
                imported.extend((node.module or '').split('.'))
            elif isinstance(node, ast.Import):
                for name in node.names:
                    imported.extend(name.name.split('.'))
        self.assertFalse(forbidden.intersection(imported))


if __name__ == '__main__':
    unittest.main()
