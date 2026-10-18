"""Equivalence controls for codec fast paths: same bytes, quotas and errors.

Planner output is used only as a realistic corpus of operations; the
expected values always come from the original canonical encoder.
"""
from dataclasses import replace
import hashlib
import json
import unittest

from axiom.codec import (_REJECTED, DecodeError, _canonical_ok, _fast_loads, _operation_object,
                         _operation_shell_length, _strict_parse, canonical_json, decode_plan,
                         encode_plan, plan_digest, strict_json_loads, validate_plan,
                         validated_plan_digest)
from axiom.frontend import admit_source, parse_source
from axiom.model import Limits
from axiom.plan_format import Operation, Plan
from axiom.planner import PLAN_IDS, make_plan

SOURCE = '''module demo;
shape H = {h};
shape W = {w};
input image: i32[H+1,W+1] in 0..=1023;
let p[r in 0..H+1,c in 0..W+1] =
  (image[r,c]+1)*(image[r,c]+1);
output result[r in 0..H,c in 0..W] =
  ((p[r,c]+p[r,c+1])+p[r+1,c])+p[r+1,c+1];
require plan_workspace_bytes <= 1024;
prefer multiplication_ops;
'''


def corpus():
    for h, w in ((1, 1), (1, 15), (5, 7), (15, 15)):
        kernel = admit_source(parse_source(SOURCE.format(h=h, w=w).encode()))
        for plan_id in PLAN_IDS:
            yield make_plan(kernel, plan_id)


class OperationShellLength(unittest.TestCase):
    def test_matches_canonical_encoding_for_generated_plans(self):
        checked = 0
        for plan in corpus():
            for op in plan.operations:
                self.assertEqual(_operation_shell_length(op),
                                 len(canonical_json(_operation_object(op, []))), op)
                checked += 1
        self.assertGreater(checked, 1000)

    def test_matches_canonical_encoding_at_field_extremes(self):
        for op in (Operation('const', dst=0, value=-2147483648),
                   Operation('const', dst=9999999999, value=2147483647),
                   Operation('const', dst=0, value=0),
                   Operation('input_load', dst=7, index=9999999999),
                   Operation('add', dst=12, operands=(0, 9999999999)),
                   Operation('scratch_store', operands=(3,), index=0),
                   Operation('output_store', operands=(10,), index=255, origins=(1, 2, 3))):
            self.assertEqual(_operation_shell_length(op),
                             len(canonical_json(_operation_object(op, []))), op)

    def test_byte_quota_boundary_is_unchanged(self):
        plan = next(corpus())
        exact = len(encode_plan(plan))
        validate_plan(plan, replace(Limits(), plan_bytes=exact))
        with self.assertRaises(DecodeError) as raised:
            validate_plan(plan, replace(Limits(), plan_bytes=exact - 1))
        self.assertEqual(raised.exception.code, 'BYTE_LIMIT')


class CanonicalJsonFastPath(unittest.TestCase):
    def test_valid_values_encode_identically(self):
        for value in (None, True, 0, -9999999999, 'é☃', [], {}, [[1, 2], {'b': 1, 'a': [None]}],
                      {'deep': [[[[[[[[1]]]]]]]]}):
            self.assertTrue(_canonical_ok(value))
            self.assertEqual(canonical_json(value), json.dumps(
                value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode())

    def test_invalid_values_keep_first_error_code_and_path(self):
        nested = 0
        for _ in range(66):
            nested = [nested]
        cases = (
            ([1, 10000000000], 'INTEGER_TOKEN_LIMIT', '$[1]'),
            ({'a': [0, 1.5]}, 'INVALID_JSON', '$.a[1]'),
            ({'a': 1, 2: 3}, 'INVALID_JSON', '$'),
            (['ok', '\ud800'], 'INVALID_JSON', '$[1]'),
            ([1.0, 10000000000], 'INVALID_JSON', '$[0]'),
            (nested, 'DEPTH_LIMIT', '$' + '[0]' * 65),
            ((1, 2), 'INVALID_JSON', '$'),
        )
        for value, code, path in cases:
            self.assertFalse(_canonical_ok(value))
            with self.assertRaises(DecodeError) as raised:
                canonical_json(value)
            self.assertEqual((raised.exception.code, raised.exception.field_path), (code, path), value)


class StrictLoadsFastPath(unittest.TestCase):
    """The fast decoder must agree with _strict_parse on every input."""

    TEXTS = [
        '0', '-0', '7', '-2147483648', '9999999999', '-9999999999', '10000000000', '01', '-', '1.0',
        '1e5', '1E5', 'NaN', 'Infinity', '-Infinity', 'true', 'false', 'null', 'tru', 'nulll',
        '""', '"a\\u0041"', '"\\ud800"', '"\\ud83d\\ude00"', '"tab\there"', '"\\x"', '"é☃"',
        '[]', '{}', '[1,2,3]', '[1,]', '[,1]', '{"a":1,"a":2}', '{"a":1,"b":{"a":2}}', '{"a" : 1 }',
        ' \t\r\n[ 1 , 2 ]\n', '[1] x', '[1]]', '{"a":1,}', '{1:2}', '{"a" 1}', '[[[[]]]]', '﻿[]',
        '{"operations":[1,2,3]}', '{"operations":[1,2,3,4]}', '{"x":{"operations":[1,2,3,4]}}',
        '{"\\ud800":1}', '[1.5]', '[-]', '[00]', '[0,[1,[2,[3]]]]', '', '   ',
        '{"format_version":1,"operations":[{"dst":0,"opcode":"const","value":-1}]}',
    ]
    LIMITS = [dict(max_items=300000, max_depth=64, max_integer_digits=10, _operation_limit=None),
              dict(max_items=3, max_depth=2, max_integer_digits=2, _operation_limit=3),
              dict(max_items=1, max_depth=1, max_integer_digits=1, _operation_limit=1)]

    def outcome(self, fn):
        try:
            return 'ok', fn()
        except DecodeError as error:
            return 'error', error.code, error.field_path

    def test_fast_path_agrees_with_strict_parser(self):
        texts = self.TEXTS + ['[' * 70 + ']' * 70, '[' * 3000 + ']' * 3000, '[' + '1,' * 40 + '1]',
                              canonical_json(_operation_object(Operation('add', dst=3, operands=(1, 2)), [9])).decode()]
        for limits in self.LIMITS:
            for text in texts:
                strict = self.outcome(lambda: _strict_parse(text, limits['max_items'], limits['max_depth'],
                                                            limits['max_integer_digits'], limits['_operation_limit']))
                public = self.outcome(lambda: strict_json_loads(text.encode('utf-8', 'surrogatepass'), **limits))
                self.assertEqual(public, strict, (text[:40], limits))

    def test_generated_plans_take_the_fast_path(self):
        limits = Limits()
        for plan in corpus():
            data = encode_plan(plan, limits=limits)
            self.assertIsNot(_fast_loads(data.decode(), limits.plan_bytes, 64, 10, limits.plan_operations),
                             _REJECTED)
            self.assertEqual(decode_plan(data, limits), plan)


class ValidatedDigest(unittest.TestCase):
    def test_equals_plan_digest(self):
        limits = Limits()
        for plan in corpus():
            validate_plan(plan, limits)
            self.assertEqual(validated_plan_digest(plan, limits), plan_digest(plan, limits=limits))
            self.assertEqual(validated_plan_digest(plan, limits),
                             hashlib.sha256(encode_plan(plan, limits=limits)).hexdigest())


if __name__ == '__main__':
    unittest.main()
