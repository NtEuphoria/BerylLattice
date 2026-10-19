"""Equivalence controls for the strict-JSON fast decoder and plan byte quotas.

Planner output is used only as a realistic corpus; the expected outcome of
every decode always comes from the original strict parser.
"""
from dataclasses import replace
import unittest

from axiom.codec import (_REJECTED, DecodeError, _fast_loads, _operation_object, _strict_parse,
                         canonical_json, decode_plan, encode_plan, strict_json_loads, validate_plan)
from axiom.frontend import admit_source, parse_source
from axiom.model import Limits
from axiom.plan_format import Operation
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


class PlanByteQuota(unittest.TestCase):
    def test_byte_quota_boundary_is_unchanged(self):
        plan = next(corpus())
        exact = len(encode_plan(plan))
        validate_plan(plan, replace(Limits(), plan_bytes=exact))
        with self.assertRaises(DecodeError) as raised:
            validate_plan(plan, replace(Limits(), plan_bytes=exact - 1))
        self.assertEqual(raised.exception.code, 'BYTE_LIMIT')


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


if __name__ == '__main__':
    unittest.main()
