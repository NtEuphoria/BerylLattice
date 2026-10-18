"""The v2 name boundary preserves original source and bounds semantic lookup."""
import dataclasses
import importlib.util
import re
import unittest
from unittest.mock import patch

from axiom import source_profiles
from axiom.frontend import parse_source
from axiom.model import DiagnosticError, Span
from axiom.source_profiles import SourceLimitsV2, SourceProfileV2, admit_source_v2
from tests.helpers import stencil_source


def renamed_source():
    names = (b'H', b'W', b'image', b'p', b'result', b'r', b'c')
    spellings = [b'long_common_prefix_' + b'z' * 128 + bytes([65 + i])
                 for i in range(len(names))]
    mapping = dict(zip(names, spellings))
    return re.sub(rb'\b(H|W|image|p|result|r|c)\b',
                  lambda match: mapping[match[0]], stencil_source(5, 7))


def rename(source, mapping):
    return re.sub(rb'\b[A-Za-z_][A-Za-z_0-9]*\b',
                  lambda match: mapping.get(match[0], match[0]), source)


def accepted_cases():
    """Also exported to the isolated baseline differential evidence runner."""
    for h, w in ((1, 1), (5, 7), (32, 32), (2048, 2048),
                 (8191, 1023), (1023, 8191), (8192, 1022), (1022, 8192),
                 (1, 8192), (8192, 1)):
        yield f'dimensions_{h}_{w}', stencil_source(h, w)
    source = stencil_source(5, 7)
    yield 'long_equal_prefixes', renamed_source()
    yield 'alias_spellings', rename(source, dict(zip(
        (b'H', b'W', b'image', b'p', b'result', b'r', b'c'),
        (b'b', b'a', b'c', b'd', b'e', b'f', b'g'))))
    yield 'unequal_lengths', rename(source, dict(zip(
        (b'H', b'W', b'image', b'p', b'result', b'r', b'c'),
        (b'z', b'zz', b'zzz', b'zzzz', b'zzzzz', b'zzzzzz', b'zzzzzzz'))))
    for axis_name in (b'H', b'W', b'image', b'p', b'result'):
        yield 'axis_shadow_' + axis_name.decode(), rename(source, {b'r': axis_name})
    producer, consumer = source.split(b'output ', 1)
    yield 'nine_names', producer + b'output ' + rename(consumer, {b'r': b'u', b'c': b'v'})
    yield 'distinct_reversed_axes', producer + b'output ' + rename(consumer, {b'r': b'c', b'c': b'r'})
    yield 'shape_groups', source.replace(b'= 5;', b'= (((5)));').replace(b'= 7;', b'= ((7));')
    yield 'index_groups', source.replace(b'[r,c]', b'[(r),((c))]')
    yield 'deep_groups', source.replace(b'= 5;', b'= ' + b'(' * 31 + b'5' + b')' * 31 + b';')
    yield 'padded_literals', source.replace(b'= 5;', b'= 0000000005;').replace(b'+1', b'+0000000001')
    line = b'require plan_workspace_bytes <= 0;\n'
    yield 'interspersed_constraints', source.replace(b'shape ', line + b'shape ') + line
    yield 'repeated_constraints_max_bytes', (source + line * ((65536-len(source)) // len(line))).ljust(65536, b' ')
    yield 'no_constraint', stencil_source(5, 7, None)
    yield 'workspace_objective', stencil_source(5, 7, 0, 'plan_workspace_bytes')
    yield 'comments_and_space', b'// original spans\n' + source.replace(b' = ', b'  =   ')
    yield 'max_padding', source + b'//' + b' ' * (65536-len(source)-2)
    yield 'max_output_name', source.replace(b'result', b'q' * (65536-len(source)+len(b'result')))
    yield 'long_module_name', source.replace(b'demo', b'm' * 2048)


def rejected_cases():
    source = stencil_source(5, 7)
    for name, before, after in (
        ('duplicate_global', b'shape W', b'shape H'),
        ('duplicate_axis', b'c in 0..W+1', b'r in 0..W+1'),
        ('undefined_shape', b'i32[H+1', b'i32[missing_shape+1'),
        ('undefined_index', b'image[r,c]', b'image[missing_index,c]'),
        ('undefined_tensor', b'image[r,c]', b'missing_tensor[r,c]'),
        ('producer_self_read', b'image[r,c]', b'p[r,c]'),
        ('producer_forward_read', b'image[r,c]', b'result[r,c]'),
        ('shape_nonliteral', b'shape W = 7', b'shape W = H+2'),
        ('shape_chain', b'shape W = 7', b'shape W = H+H+H'),
        ('shape_extra', b'shape W = 7;', b'shape W = 7; shape extra = W+W;'),
        ('shape_missing', b'shape W = 7;\n', b''),
        ('input_rank', b'i32[H+1,W+1]', b'i32[H+1]'),
        ('producer_rank', b'r in 0..H+1,c in 0..W+1', b'r in 0..H+1'),
        ('output_rank', b'r in 0..H,c in 0..W', b'r in 0..H'),
        ('changed_association', b'((p[r,c]+p[r,c+1])+p[r+1,c])', b'(p[r,c]+(p[r,c+1]+p[r+1,c]))'),
        ('changed_literal', b'image[r,c]+1', b'image[r,c]+2'),
        ('changed_operator', b')*(image', b')+(image'),
        ('changed_read', b'image[r,c]+1', b'image[r+1,c]+1'),
        ('changed_shadowing', b'p[r,c]+p[r,c+1]', b'p[H,c]+p[r,c+1]'),
        ('wrong_type', b'i32[', b'i64['),
        ('negative_cap', b'<= 64', b'<= -1'),
        ('oversize_cap', b'<= 64', b'<= 2147483648'),
        ('bad_property', b'require plan_workspace_bytes', b'require other'),
        ('bad_objective', b'prefer multiplication_ops', b'prefer other'),
    ):
        yield name, source.replace(before, after)
    producer, consumer = source.split(b'output ', 1)
    nine = producer + b'output ' + rename(consumer, {b'r': b'u', b'c': b'v'})
    yield 'tenth_name', nine.replace(b'p[u,v]', b'p[unknown,v]', 1)
    yield 'undefined_before_extra_shape', source.replace(b'i32[H+1', b'i32[missing+1') + b'shape extra = 1;'
    yield 'negative_before_nonliteral', source.replace(b'= 5;', b'= -1;').replace(b'= 7;', b'= H+1;')


class SourceNameBoundaryTests(unittest.TestCase):
    def admit(self, source):
        return admit_source_v2(source, profile=SourceProfileV2(), limits=SourceLimitsV2())

    def test_private_view_exists_and_retains_original_ast_and_identities(self):
        self.assertIsNotNone(importlib.util.find_spec('axiom.source_names_v2'),
                             'v2 requires a bounded name adapter')
        from axiom.source_names_v2 import _build_name_view
        source = renamed_source()
        original = parse_source(source)
        view = _build_name_view(original)
        admitted = self.admit(source)
        self.assertEqual(admitted.source_module, original)
        self.assertIs(view.module.source_bytes, original.source_bytes)
        self.assertEqual(view.module.source_digest, original.source_digest)
        self.assertNotEqual(view.module.shapes[0].name, original.shapes[0].name)
        canonical = self.admit(stencil_source(5, 7))
        for field in ('family_digest', 'specialization_digest',
                      'constraint_digest', 'objective_digest'):
            self.assertEqual(getattr(admitted, field), getattr(canonical, field))

    def test_shared_validator_and_profile_receive_only_fixed_aliases(self):
        seen = []
        validate, profile = source_profiles._validate, source_profiles._profile

        def inspect_validate(module):
            seen.append(module)
            return validate(module)

        def inspect_profile(module):
            seen.append(module)
            return profile(module)

        with patch.object(source_profiles, '_validate', inspect_validate), \
                patch.object(source_profiles, '_profile', inspect_profile):
            admitted = self.admit(renamed_source())
        self.assertEqual(len(seen), 2)

        def inspect_names(value):
            if dataclasses.is_dataclass(value):
                for field in dataclasses.fields(value):
                    child = getattr(value, field.name)
                    if field.name == 'name':
                        self.assertIn(child, tuple('abcdefghi'))
                    else:
                        inspect_names(child)
            elif isinstance(value, tuple):
                for child in value:
                    inspect_names(child)

        for module in seen:
            inspect_names(module)
            self.assertIsNot(module, admitted.source_module)

    def test_necessary_guards_run_before_general_validation(self):
        source = stencil_source(5, 7)
        rejected = [
            source.replace(b'shape W = 7;', b'shape W = 7; shape extra = H+W;'),
            source.replace(b'shape H = 5;', b'shape H = 2+3;'),
            source.replace(b'i32[H+1,W+1]', b'i32[H+1]'),
            source.replace(b'r in 0..H+1,c in 0..W+1', b'r in 0..H+1'),
            source.replace(b'r in 0..H,c in 0..W', b'r in 0..H'),
        ]
        validate = source_profiles._validate
        for changed in rejected:
            with self.subTest(source=changed):
                calls = []

                def inspect(module):
                    calls.append(module)
                    return validate(module)

                with patch.object(source_profiles, '_validate', inspect):
                    with self.assertRaises(DiagnosticError) as caught:
                        self.admit(changed)
                self.assertEqual(caught.exception.code, 'UNSUPPORTED_PROFILE')
                self.assertEqual(calls, [])

    def test_all_accepted_variants_retain_exact_original_ast(self):
        for name, source in accepted_cases():
            with self.subTest(case=name):
                admitted = self.admit(source)
                self.assertEqual(admitted.source_module, parse_source(source))
                self.assertEqual(admitted.source_bytes, source)

    def test_all_rejected_variants_still_reject(self):
        for name, source in rejected_cases():
            with self.subTest(case=name), self.assertRaises(DiagnosticError):
                self.admit(source)

    def test_private_view_preserves_every_non_name_field_and_shared_declaration(self):
        from axiom.source_names_v2 import _build_name_view

        def check(original, renamed):
            self.assertIs(type(original), type(renamed))
            if dataclasses.is_dataclass(original):
                for field in dataclasses.fields(original):
                    before, after = getattr(original, field.name), getattr(renamed, field.name)
                    if field.name == 'name':
                        self.assertIn(after, tuple('abcdefghi'))
                        self.assertEqual(originals[ord(after)-ord('a')], before)
                    else:
                        check(before, after)
            elif isinstance(original, tuple):
                self.assertEqual(len(original), len(renamed))
                for before, after in zip(original, renamed):
                    check(before, after)
            else:
                self.assertEqual(original, renamed)

        for name, source in accepted_cases():
            with self.subTest(case=name):
                original = parse_source(source)
                result = _build_name_view(original)
                originals = result.original_names
                check(original, result.module)
                for decl in (*result.module.shapes, *result.module.inputs,
                             *result.module.producers, *result.module.outputs,
                             *result.module.constraints):
                    self.assertEqual(sum(candidate is decl for candidate in result.module.declarations), 1)

    def test_registry_scans_each_resident_once_without_hash_or_whole_name_equality(self):
        from axiom.source_names_v2 import _BoundedNames, _NameWork

        class Name(str):
            def __hash__(self):
                raise AssertionError('original spelling was hashed')

            def __eq__(self, other):
                raise AssertionError('original spelling used whole-string equality')

            def __ne__(self, other):
                raise AssertionError('original spelling used whole-string inequality')

        work = _NameWork()
        registry = _BoundedNames(work)
        names = [Name('common_prefix_' + str(index)) for index in range(9)]
        for index, name in enumerate(names):
            before = work.candidate_comparisons
            self.assertEqual(registry.lookup(name, Span(index, len(name))), 'abcdefghi'[index])
            self.assertEqual(work.candidate_comparisons-before, index)
        seen = []
        matches = _BoundedNames._matches

        def inspect(instance, name, resident):
            seen.append(id(resident))
            return matches(instance, name, resident)

        with patch.object(_BoundedNames, '_matches', inspect):
            self.assertEqual(registry.lookup(Name('common_prefix_8'), Span(99, 15)), 'i')
        self.assertEqual(seen, [id(name) for name in names])
        self.assertEqual(len(registry.originals), 9)
        before_candidates, before_chars = work.candidate_comparisons, work.character_comparisons
        span = Span(201, 200)
        with self.assertRaises(DiagnosticError) as caught:
            registry.lookup(Name('x' * 200), span)
        self.assertEqual(caught.exception.code, 'UNSUPPORTED_PROFILE')
        self.assertEqual(caught.exception.span, span)
        self.assertEqual(work.candidate_comparisons-before_candidates, 9)
        self.assertEqual(work.character_comparisons, before_chars)
        self.assertEqual(len(registry.originals), 9)

    def test_actual_registry_counts_and_view_visits_match_independent_walk(self):
        from axiom.source_names_v2 import _build_name_view
        from axiom.model import (AxisBinding, BinaryExpression, ConstraintDeclaration,
                                 GroupExpression, IntegerLiteral, NameReference, ReadExpression)

        expression_types = (IntegerLiteral, NameReference, BinaryExpression, ReadExpression, GroupExpression)

        def walk(value):
            yield value
            if dataclasses.is_dataclass(value):
                for field in dataclasses.fields(value):
                    yield from walk(getattr(value, field.name))
            elif isinstance(value, tuple):
                for item in value:
                    yield from walk(item)

        for name, source in accepted_cases():
            with self.subTest(case=name):
                original = parse_source(source)
                result = _build_name_view(original)
                nodes = tuple(walk(original.declarations))
                occurrences = tuple(node.name for node in nodes if hasattr(node, 'name'))
                residents, candidates, characters = [], 0, 0
                for spelling in occurrences:
                    for resident in residents:
                        candidates += 1
                        if len(spelling) != len(resident):
                            continue
                        for left, right in zip(spelling, resident):
                            characters += 1
                            if left != right:
                                break
                        else:
                            break
                    else:
                        residents.append(spelling)
                self.assertEqual(result.work.name_occurrences, len(occurrences))
                self.assertEqual(result.work.identifier_bytes, sum(map(len, occurrences)))
                self.assertEqual(result.work.candidate_comparisons, candidates)
                self.assertEqual(result.work.character_comparisons, characters)
                self.assertEqual(result.work.expression_visits,
                                 sum(isinstance(node, expression_types) for node in nodes))
                self.assertEqual(result.work.axis_visits, sum(isinstance(node, AxisBinding) for node in nodes))
                self.assertEqual(result.work.declaration_visits, len(original.declarations))
                self.assertLessEqual(candidates, 9 * len(occurrences))
                self.assertLessEqual(characters, 9 * sum(map(len, occurrences)))
                expected_copies = 1 + sum(isinstance(node, expression_types + (AxisBinding,))
                                          and not isinstance(node, IntegerLiteral) for node in nodes)
                expected_copies += sum(not isinstance(decl, ConstraintDeclaration) for decl in original.declarations)
                self.assertEqual(result.work.rebuilt_records, expected_copies)

    def test_original_name_diagnostics_do_not_cascade_or_expose_alias_traceback(self):
        from axiom.source_names_v2 import _original_name_diagnostic
        span = Span(19, 30)
        for prefix in ('undefined shape', 'undefined index', 'undefined tensor', 'duplicate declaration'):
            code = 'DUPLICATE_NAME' if prefix.startswith('duplicate') else 'UNDEFINED_NAME'
            for original in ('b', 'a_b_c', 'a' * 512):
                error = DiagnosticError(code, span, f"{prefix} 'a'")
                translated = _original_name_diagnostic(error, (original, 'c'))
                self.assertEqual(translated.message, f'{prefix} {original!r}')
                self.assertEqual((translated.code, translated.span), (code, span))
        unchanged = DiagnosticError('UNDEFINED_NAME', span, "scalar values must be tensor reads or integer literals")
        self.assertIs(_original_name_diagnostic(unchanged, ('b', 'a')), unchanged)
        source = rename(stencil_source(5, 7), {b'H': b'b', b'W': b'a'})
        for changed, message, token in (
            (source.replace(b'shape a', b'shape b'), "duplicate declaration 'b'", b'shape b = 7'),
            (source.replace(b'image[r,c]', b'a_b_c[r,c]'), "undefined tensor 'a_b_c'", b'a_b_c['),
            (source.replace(b'i32[b+1', b'i32[missing_shape+1'), "undefined shape 'missing_shape'", b'missing_shape'),
            (source.replace(b'image[r,c]', b'image[missing_index,c]'), "undefined index 'missing_index'", b'missing_index'),
        ):
            with self.subTest(message=message), self.assertRaises(DiagnosticError) as caught:
                self.admit(changed)
            self.assertEqual(caught.exception.message, message)
            offset = changed.index(token) + (6 if token.startswith(b'shape ') else 0)
            self.assertEqual(caught.exception.span.offset, offset)
            self.assertTrue(caught.exception.__suppress_context__)

    def test_tenth_spelling_rejects_at_original_occurrence(self):
        source = next(source for name, source in rejected_cases() if name == 'tenth_name')
        with self.assertRaises(DiagnosticError) as caught:
            self.admit(source)
        self.assertEqual(caught.exception.code, 'UNSUPPORTED_PROFILE')
        self.assertEqual(caught.exception.span, Span(source.index(b'unknown'), len(b'unknown')))


if __name__ == '__main__':
    unittest.main()
