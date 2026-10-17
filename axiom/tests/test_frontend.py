import dataclasses
from pathlib import Path
import unittest

from axiom.frontend import admit_source, parse_source
from axiom.model import DiagnosticError, Limits, Objective, GroupExpression
from tests.helpers import stencil_source


class FrontendTests(unittest.TestCase):
    def diagnostic(self, source, code):
        with self.assertRaises(DiagnosticError) as caught:
            admit_source(parse_source(source))
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_canonical_and_alpha_renamed_stencil(self):
        source = stencil_source(5, 7, 64)
        kernel = admit_source(parse_source(source))
        renamed = source
        for old, new in [(b'demo', b'other'), (b'image', b'pixels'),
                         (b'result', b'answer'), (b' p[', b' stage['),
                         (b'(p[', b'(stage['), (b'+p[', b'+stage[')]:
            renamed = renamed.replace(old, new)
        # Token-aware renaming of axes and shape constants.
        import re
        renamed = re.sub(rb'\b(H|W|r|c)\b', lambda m: {
            b'H': b'Rows', b'W': b'Cols', b'r': b'y', b'c': b'x'}[m[0]], renamed)
        other = admit_source(parse_source(renamed))
        self.assertEqual((kernel.height, kernel.width, kernel.cap), (5, 7, 64))
        self.assertEqual(kernel.input_interval, (0, 1023))
        self.assertEqual(kernel.objective, 'multiplication_ops')
        self.assertEqual(kernel.semantic_digest, other.semantic_digest)
        self.assertNotEqual(kernel.source_digest, other.source_digest)
        self.assertEqual(kernel.source_module.source_bytes, source)
        self.assertIsInstance(kernel.source_expressions[1], type(kernel.source_module.outputs[0].expression))
        self.assertIsInstance(kernel.source_expressions[0].left, GroupExpression)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            kernel.height = 1

    def test_axis_alpha_renaming_can_shadow_tensor_names(self):
        import re
        source = stencil_source(5, 7)
        original = admit_source(parse_source(source))
        for axis, tensor_name in [(b'r', b'image'), (b'r', b'p'),
                                  (b'c', b'image'), (b'c', b'p')]:
            with self.subTest(axis=axis, tensor_name=tensor_name):
                renamed = re.sub(rb'\b' + axis + rb'\b', tensor_name, source)
                kernel = admit_source(parse_source(renamed))
                self.assertEqual(kernel.semantic_digest, original.semantic_digest)
                self.assertNotEqual(kernel.source_digest, original.source_digest)
                self.assertEqual(kernel.source_module.source_bytes, renamed)

    def test_format_and_policy_excluded_from_semantic_identity(self):
        a = admit_source(parse_source(stencil_source(5, 7)))
        b = admit_source(parse_source(b'// caf\xc3\xa9\n' + stencil_source(5, 7, None, 'plan_workspace_bytes')))
        self.assertEqual(a.semantic_digest, b.semantic_digest)
        self.assertNotEqual(a.source_digest, b.source_digest)
        self.assertIsNone(b.cap)
        self.assertEqual(b.objective, Objective.PLAN_WORKSPACE_BYTES)
        default = stencil_source(5, 7).replace(b'prefer multiplication_ops;\n', b'')
        self.assertEqual(admit_source(parse_source(default)).objective, Objective.MULTIPLICATION_OPS)

    def test_byte_spans_after_utf8_comment(self):
        source = b'// caf\xc3\xa9 \xf0\x9f\x8c\xb2\n' + stencil_source(5, 7).replace(b'image[r,c]', b'missing[r,c]', 1)
        error = self.diagnostic(source, 'UNDEFINED_NAME')
        self.assertEqual(error.span.offset, source.index(b'missing'))
        self.assertEqual(error.span.length, len(b'missing'))

    def test_duplicate_and_undefined_names(self):
        source = stencil_source(5, 7)
        self.diagnostic(source.replace(b'shape W', b'shape H'), 'DUPLICATE_NAME')
        self.diagnostic(source.replace(b'p[r,c]', b'nope[r,c]', 1), 'UNDEFINED_NAME')
        self.diagnostic(source.replace(b'image[r,c]', b'image[r,z]', 1), 'UNDEFINED_NAME')
        self.diagnostic(source.replace(b'c in 0..W+1', b'r in 0..W+1'), 'DUPLICATE_NAME')

    def test_invalid_shapes_and_range_bounds(self):
        for h, w in [(0, 7), (5, 0), (-1, 7), (5, -1)]:
            self.diagnostic(stencil_source(h, w), 'INVALID_SHAPE')
        self.diagnostic(stencil_source(16, 16), 'UNSUPPORTED_PROFILE')
        self.diagnostic(stencil_source(5, 7).replace(b'0..=1023', b'1023..=0'), 'INVALID_RANGE')
        self.diagnostic(stencil_source(5, 7).replace(b'r in 0..H+1', b'r in 7..H+1'), 'INVALID_RANGE')
        self.diagnostic(stencil_source(5, 7).replace(b'result[r in 0..H,', b'result[r in 1..H,'), 'UNSUPPORTED_PROFILE')
        self.diagnostic(stencil_source(5, 7).replace(b'image[r,c]+1', b'image[r+1,c]+1'), 'INVALID_INDEX')

    def test_expression_depth_and_huge_tokens(self):
        source = stencil_source(5, 7)
        self.diagnostic(source.replace(b'image[r,c]+1', b'('*33 + b'image[r,c]+1' + b')'*33), 'EXPRESSION_DEPTH_LIMIT')
        self.diagnostic(source.replace(b'= 5;', b'= 12345678901;'), 'INTEGER_TOKEN_LIMIT')
        self.diagnostic(source.replace(b'+1)', b'+2147483648)', 1), 'INVALID_INTEGER')

    def test_invalid_utf8_and_nul(self):
        self.diagnostic((Path(__file__).parent / 'fixtures/source/invalid_utf8.ax').read_bytes(), 'INVALID_UTF8')
        self.diagnostic(b'// comment\x00\n' + stencil_source(5, 7), 'NUL_BYTE')

    def test_structural_profile_rejections(self):
        source = stencil_source(5, 7)
        extra = (Path(__file__).parent / 'fixtures/source/extra_producer.ax').read_bytes()
        self.diagnostic(extra, 'UNSUPPORTED_PROFILE')
        self.diagnostic(source.replace(b'image[r,c]+1', b'image[r,c]+2'), 'UNSUPPORTED_PROFILE')
        self.diagnostic(source.replace(b'((p[r,c]+p[r,c+1])+p[r+1,c])', b'(p[r,c]+(p[r,c+1]+p[r+1,c]))'), 'UNSUPPORTED_PROFILE')
        self.diagnostic(source.replace(b'i32[H+1,W+1]', b'i32[6,8]'), 'UNSUPPORTED_PROFILE')

    def test_constraints_and_objectives(self):
        self.diagnostic(stencil_source(5, 7, -1), 'INVALID_CONSTRAINT')
        self.diagnostic(stencil_source(5, 7, 2147483648), 'INVALID_CONSTRAINT')
        self.diagnostic(stencil_source(5, 7).replace(b'require plan_workspace_bytes', b'require latency'), 'UNSUPPORTED_CONSTRAINT')
        self.diagnostic(stencil_source(5, 7, objective='latency'), 'UNSUPPORTED_OBJECTIVE')

    def test_quotas_and_exact_limit_types(self):
        with self.assertRaises(DiagnosticError) as caught:
            parse_source(b' '*65537)
        self.assertEqual(caught.exception.code, 'SOURCE_BYTES_LIMIT')
        with self.assertRaises(DiagnosticError) as caught:
            parse_source(stencil_source(5, 7), Limits(expression_nodes=5))
        self.assertEqual(caught.exception.code, 'EXPRESSION_NODES_LIMIT')
        for value in [True, 0, -1, 2.0]:
            with self.assertRaises(ValueError):
                Limits(check_steps=value)

    def test_syntax_rejects_subtraction_and_invalid_tokens(self):
        source = stencil_source(5, 7)
        self.diagnostic(source.replace(b'image[r,c]+1', b'image[r,c]-1'), 'SYNTAX_ERROR')
        self.diagnostic(source + b'@', 'INVALID_TOKEN')
        self.diagnostic(source.replace(b'module demo;', b'module demo'), 'SYNTAX_ERROR')


if __name__ == '__main__':
    unittest.main()
