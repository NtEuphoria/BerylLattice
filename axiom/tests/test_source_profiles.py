"""Explicit v2 admission boundaries; v1 fixtures remain literal golden values."""
import dataclasses
import hashlib
import re
import unittest

from axiom.frontend import admit_source, parse_source
from axiom.model import DiagnosticError, Objective, SourceModule
from axiom.source_profiles import (
    AdmittedLoopKernel, SourceLimitsV2, SourceProfileV2, admit_source_v2,
)
from tests.helpers import stencil_source


class SourceProfileTests(unittest.TestCase):
    def admit(self, source):
        return admit_source_v2(source, profile=SourceProfileV2(), limits=SourceLimitsV2())

    def test_v1_admits_large_shape_only_as_scale_v1(self):
        # Large shapes are scale-v1 (template-proved loop plans), never finite plans.
        from axiom.planner import plan_ids
        kernel = admit_source(parse_source(stencil_source(32, 32)))
        self.assertEqual((kernel.profile, plan_ids(kernel)), ('scale-v1', ()))

    def test_explicit_v2_accepts_training_shape(self):
        source = stencil_source(32, 32)
        kernel = self.admit(source)
        self.assertIsInstance(kernel, AdmittedLoopKernel)
        self.assertEqual((kernel.height, kernel.width, kernel.input_cells), (32, 32, 1089))
        self.assertEqual(kernel.output_cells, 1024)
        self.assertEqual(kernel.source_bytes, source)
        self.assertIsInstance(kernel.source_module, SourceModule)
        self.assertEqual(kernel.source_module.source_bytes, source)
        self.assertEqual(kernel.source_digest, hashlib.sha256(source).hexdigest())
        self.assertEqual(kernel.input_interval, (0, 1023))
        self.assertEqual(kernel.objective, Objective.MULTIPLICATION_OPS)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            kernel.height = 1

    def test_dimension_and_cell_envelope(self):
        for height, width in [(8191, 1023), (8192, 1022), (1, 8192), (8192, 1)]:
            with self.subTest(height=height, width=width):
                kernel = self.admit(stencil_source(height, width))
                self.assertEqual(kernel.input_cells, (height+1)*(width+1))
        self.assertEqual(self.admit(stencil_source(8191, 1023)).input_cells, 2**23)
        for height, width in [(8193, 1), (1, 8193), (8192, 1023),
                              (0, 1), (1, 0), (-1, 1), (1, -1), (True, 1), (1, False)]:
            with self.subTest(height=height, width=width), self.assertRaises(DiagnosticError):
                self.admit(stencil_source(height, width))

    def test_family_and_specialization_identities(self):
        source = stencil_source(32, 32)
        original = self.admit(source)
        renamed = re.sub(rb'\b(demo|H|W|image|p|result|r|c)\b', lambda m: {
            b'demo': b'other', b'H': b'Rows', b'W': b'Cols', b'image': b'pixels',
            b'p': b'stage', b'result': b'answer', b'r': b'y', b'c': b'x'}[m[0]], source)
        for changed in [renamed, b'// comment\n'+source, source.replace(b' = ', b'  =  ')]:
            kernel = self.admit(changed)
            self.assertEqual(kernel.family_digest, original.family_digest)
            self.assertEqual(kernel.specialization_digest, original.specialization_digest)
            self.assertNotEqual(kernel.source_digest, original.source_digest)
        changed_shape = self.admit(stencil_source(33, 32))
        self.assertEqual(changed_shape.family_digest, original.family_digest)
        self.assertNotEqual(changed_shape.specialization_digest, original.specialization_digest)
        self.assertNotEqual(original.family_digest, original.specialization_digest)
        for changed in [source.replace(b'((p[r,c]+p[r,c+1])+p[r+1,c])',
                                        b'(p[r,c]+(p[r,c+1]+p[r+1,c]))'),
                        source.replace(b'0..=1023', b'0..=1022'),
                        source.replace(b'image[r,c]+1', b'image[r,c]+2')]:
            with self.subTest(changed=changed), self.assertRaises(DiagnosticError):
                self.admit(changed)
        with self.assertRaises(ValueError):
            SourceProfileV2(profile_id='axiom-stencil-fixed-buffer-v2')
        self.assertEqual(original.source_sha256, original.source_digest)
        self.assertEqual(original.family_semantics_sha256, original.family_digest)
        self.assertEqual(original.specialization_semantics_sha256, original.specialization_digest)

    def test_caps_derived_from_actual_source(self):
        a, b = self.admit(stencil_source(32, 32, 64)), self.admit(stencil_source(32, 32, 0))
        self.assertEqual((a.cap, b.cap), (64, 0))
        self.assertEqual(a.family_digest, b.family_digest)
        self.assertEqual(a.specialization_digest, b.specialization_digest)
        self.assertNotEqual(a.source_digest, b.source_digest)
        self.assertNotEqual(a.constraint_digest, b.constraint_digest)
        for caps in [(64, 0, 32), (32, 64, 0)]:
            source = stencil_source(32, 32, None) + b''.join(
                f'require plan_workspace_bytes <= {cap};\n'.encode() for cap in caps)
            kernel = self.admit(source)
            self.assertEqual(kernel.cap, 0)
            self.assertEqual(tuple(c.value for c in kernel.source_constraints), caps)
            self.assertEqual(kernel.constraint_digest, b.constraint_digest)
        other_objective = self.admit(stencil_source(32, 32, 64, 'plan_workspace_bytes'))
        self.assertEqual(other_objective.family_digest, a.family_digest)
        self.assertEqual(other_objective.specialization_digest, a.specialization_digest)
        self.assertNotEqual(other_objective.objective_digest, a.objective_digest)
        self.assertIsNone(self.admit(stencil_source(32, 32, None)).cap)

    def test_declaration_order_and_separate_axis_namespace(self):
        source = stencil_source(32, 33)
        original = self.admit(source)
        renamed = re.sub(rb'\br\b', b'image', source)
        self.assertEqual(self.admit(renamed).family_digest, original.family_digest)
        swapped = source.replace(b'shape H = 32;\nshape W = 33;',
                                 b'shape W = 33;\nshape H = 32;')
        with self.assertRaises(DiagnosticError):
            self.admit(swapped)

    def test_public_validators_and_bounded_parser(self):
        for field in ('max_height', 'max_width', 'max_input_cells'):
            for value in (True, 0, -1, 2.0, []):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    SourceProfileV2(**{field: value})
        for field in ('source_bytes', 'expression_nodes'):
            for value in (True, 0, -1, 2.0, [], 100001 if field == 'expression_nodes' else 65537):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    SourceLimitsV2(**{field: value})
        for record in (SourceProfileV2, SourceLimitsV2):
            for version in (1, True, '2', []):
                with self.subTest(record=record, version=version), self.assertRaises(ValueError):
                    record(version=version)
        with self.assertRaises(ValueError):
            SourceProfileV2(index_semantics='unchecked')
        for value in (bytearray(stencil_source(32, 32)), parse_source(stencil_source(5, 7))):
            with self.subTest(value=type(value)), self.assertRaises(DiagnosticError):
                self.admit(value)
        with self.assertRaises(ValueError):
            admit_source_v2(stencil_source(32, 32), profile={}, limits=SourceLimitsV2())
        with self.assertRaises(ValueError):
            admit_source_v2(stencil_source(32, 32), profile=SourceProfileV2(), limits={})
        for source, code, limits in [
                (b' '*65537, 'SOURCE_BYTES_LIMIT', SourceLimitsV2()),
                (stencil_source(32, 32), 'EXPRESSION_NODES_LIMIT', SourceLimitsV2(expression_nodes=5)),
                (b'\xff', 'INVALID_UTF8', SourceLimitsV2()),
                (b'//\x00', 'NUL_BYTE', SourceLimitsV2())]:
            with self.subTest(code=code), self.assertRaises(DiagnosticError) as caught:
                admit_source_v2(source, profile=SourceProfileV2(), limits=limits)
            self.assertEqual(caught.exception.code, code)

    def test_source_constraints_and_scalar_profile_rejections(self):
        source = stencil_source(32, 32)
        for changed, code in [
                (stencil_source(32, 32, -1), 'INVALID_CONSTRAINT'),
                (stencil_source(32, 32, 2**31), 'INVALID_CONSTRAINT'),
                (source.replace(b'require plan_workspace_bytes', b'require latency'), 'UNSUPPORTED_CONSTRAINT'),
                (stencil_source(32, 32, objective='latency'), 'UNSUPPORTED_OBJECTIVE'),
                (source.replace(b'image[r,c]+1', b'image[r+1,c]+1'), 'INVALID_INDEX'),
                (source.replace(b'shape W', b'shape H'), 'DUPLICATE_NAME')]:
            with self.subTest(code=code), self.assertRaises(DiagnosticError) as caught:
                self.admit(changed)
            self.assertEqual(caught.exception.code, code)

    def test_v1_golden_identities_unchanged(self):
        for h, w, cap, source_digest, semantic_digest in [
            (5, 7, 64, 'd524b924fe7488d1664ea0f63c1938ab15357faa0681604b66a690389958336d',
             '17692e7e1022cc35edf4d6f0e4f0a42fdd8252f836e5b01f933854236198ac26'),
            (5, 7, 0, 'ecfbdd30faa0845dc6597661fb65214105256dc62eb8e8756f79a0275727941b',
             '17692e7e1022cc35edf4d6f0e4f0a42fdd8252f836e5b01f933854236198ac26'),
            (1, 1, 64, '98d097a3644021097002258f23085c8b731cb000616f768d6cd09be369e37427',
             '5d05369787514882a59044e660bc18116da9b576ed65e6db3d11f05feeb1a4fa')]:
            source = stencil_source(h, w, cap)
            old = admit_source(parse_source(source))
            self.assertEqual((old.source_digest, old.semantic_digest), (source_digest, semantic_digest))
            new = self.admit(source)
            self.assertNotEqual(new.family_digest, semantic_digest)
            self.assertNotEqual(new.specialization_digest, semantic_digest)


if __name__ == '__main__':
    unittest.main()
