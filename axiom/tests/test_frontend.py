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
        # Above 256 cells the stencil is scale-v1; above 2^31 - 1 it is refused.
        self.assertEqual(admit_source(parse_source(stencil_source(16, 16))).profile, 'scale-v1')
        self.diagnostic(stencil_source(46341, 46341), 'UNSUPPORTED_PROFILE')
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
        # Literal input dimensions are reduce-v1 (no longer a rejection); the
        # identity differs from the canonical spelling.
        literal = admit_source(parse_source(source.replace(b'i32[H+1,W+1]', b'i32[6,8]')))
        self.assertEqual((literal.profile, literal.input_shapes), ('reduce-v1', ((6, 8),)))
        self.diagnostic(source.replace(b'i32[H+1,W+1]', b'i32[H+9,W+1]'), 'UNSUPPORTED_PROFILE')
        # Outside the two-stage window family as well as the canonical profile:
        # the output reads the input directly, a transposed read and a
        # shape-offset read.
        self.diagnostic(source.replace(b'+p[r+1,c+1]', b'+image[r,c]'), 'UNSUPPORTED_PROFILE')
        # Square, so the transposed read stays in bounds and reaches recognition.
        self.diagnostic(stencil_source(5, 5).replace(b'p[r,c+1]', b'p[c,r]'), 'UNSUPPORTED_PROFILE')
        self.diagnostic(source.replace(b'(image[r,c]+1)*(image[r,c]+1)', b'image[r,c]*image[H,c]'), 'UNSUPPORTED_PROFILE')
        # Another input range is no longer refused: the program is scale-v1,
        # whose checker bounds reads by each input's declared range.
        self.assertEqual(admit_source(parse_source(source.replace(b'in 0..=1023', b'in 0..=1022'))).profile,
                         'scale-v1')

    def test_window_family_variants_have_distinct_identities(self):
        from axiom.model import CANONICAL_PROFILE, WINDOW_PROFILE, WINDOW_SEMANTICS_VERSION
        source = stencil_source(5, 7)
        canonical = admit_source(parse_source(source))
        self.assertEqual(canonical.profile, CANONICAL_PROFILE)
        variants = [source.replace(b'image[r,c]+1', b'image[r,c]+2'),
                    source.replace(b'((p[r,c]+p[r,c+1])+p[r+1,c])', b'(p[r,c]+(p[r,c+1]+p[r+1,c]))')]
        digests = {canonical.semantic_digest}
        for variant in variants:
            kernel = admit_source(parse_source(variant))
            self.assertEqual((kernel.profile, kernel.semantics_version), (WINDOW_PROFILE, WINDOW_SEMANTICS_VERSION))
            self.assertEqual((kernel.input_shape, kernel.producer_shape), ((6, 8), (6, 8)))
            digests.add(kernel.semantic_digest)
        self.assertEqual(len(digests), 3)  # association is retained, never normalized away

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

    def test_subtraction_scope_and_invalid_tokens(self):
        source = stencil_source(5, 7)
        # Scalar subtraction is defined as exactly a + (-1)*b ...
        minus = admit_source(parse_source(source.replace(b'image[r,c]+1', b'image[r,c]-1')))
        spelled = admit_source(parse_source(source.replace(b'image[r,c]+1', b'image[r,c]+-1*1')))
        self.assertEqual(minus.semantic_digest, spelled.semantic_digest)
        self.assertNotEqual(minus.semantic_digest, admit_source(parse_source(source)).semantic_digest)
        # ... while indices and shapes still reject it, at the operator.
        caught = self.diagnostic(source.replace(b'p[r+1,c+1]', b'p[r+1,c-1]'), 'SYNTAX_ERROR')
        self.assertEqual(source.replace(b'p[r+1,c+1]', b'p[r+1,c-1]')[caught.span.offset:caught.span.offset + 1], b'-')
        self.diagnostic(source.replace(b'shape W = 7;', b'shape W = 8 - 1;'), 'SYNTAX_ERROR')
        self.diagnostic(source + b'@', 'INVALID_TOKEN')
        self.diagnostic(source.replace(b'module demo;', b'module demo'), 'SYNTAX_ERROR')

    def test_rejections_name_the_rule_and_location(self):
        source = stencil_source(5, 7)
        cases = [
            (source.replace(b'+p[r+1,c+1]', b'+image[r,c]'), b'image', 'may only read `p`'),
            (stencil_source(5, 5).replace(b'p[r,c+1]', b'p[c,r]'), b'c', 'first index must be `r`'),
            (source.replace(b'i32[H+1,W+1]', b'i32[H+9,W+1]'), b'H+9', 'input dimensions must be a literal'),
            (source.replace(b'(image[r,c]+1)*(image[r,c]+1)', b'image[r,c]*image[H,c]'), b'H',
             'producer indices must be an axis'),
            (source.replace(b'result[r in 0..H,', b'result[r in 1..H,'), b'r in 1..H', 'output axes must be exactly'),
        ]
        for bad, at, message in cases:
            with self.subTest(message=message):
                error = self.diagnostic(bad, 'UNSUPPORTED_PROFILE')
                self.assertIn(message, error.message)
                self.assertEqual(bad[error.span.offset:error.span.offset + len(at)], at)
        counts = self.diagnostic(source.replace(b'let p[r in 0..H+1,c in 0..W+1] =\n  (image[r,c]+1)*(image[r,c]+1);\n', b'')
                                 .replace(b'p[', b'image['), 'UNSUPPORTED_PROFILE')
        self.assertIn('found 2 shape(s), 1 input(s), 0 producer(s)', counts.message)


if __name__ == '__main__':
    unittest.main()
