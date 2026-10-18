"""Strict artifact boundary tests: no plan generator is used as an oracle."""
import cProfile
import hashlib
import json
from dataclasses import replace
from pathlib import Path
import unittest

from axiom.codec import (DecodeError, canonical_json, decode_plan, encode_plan,
                         plan_digest, strict_json_loads, validate_plan)
from axiom.model import Limits
from axiom.plan_format import Operation, Plan

FIXTURES = Path(__file__).parent / 'fixtures' / 'plans'


def inline_plan():
    ops = [Operation('const', dst=0, value=1, origins=(0,))]
    producers = []
    for index in range(4):
        dst = 1 + index * 3
        ops.extend((Operation('input_load', dst=dst, index=index),
                    Operation('add', dst=dst + 1, operands=(dst, 0)),
                    Operation('mul', dst=dst + 2, operands=(dst + 1, dst + 1))))
        producers.append(dst + 2)
    ops.extend((Operation('add', dst=13, operands=tuple(producers[:2])),
                Operation('add', dst=14, operands=(13, producers[2])),
                Operation('add', dst=15, operands=(14, producers[3])),
                Operation('output_store', operands=(15,), index=0)))
    return Plan(1, 'a' * 64, 'manual inline 1x1', 0, tuple(ops))


class CodecTests(unittest.TestCase):
    def setUp(self):
        self.plan = inline_plan()
        self.limits = Limits()

    def reject(self, data, code=None, limits=None):
        with self.assertRaises(DecodeError) as raised:
            decode_plan(data, limits or self.limits)
        self.assertTrue(raised.exception.field_path)
        if code:
            self.assertEqual(raised.exception.code, code)
        return raised.exception

    def mutate(self, **fields):
        obj = json.loads(encode_plan(self.plan))
        obj.update(fields)
        return json.dumps(obj).encode()

    def test_round_trip_and_exact_canonical_fixture(self):
        encoded = encode_plan(self.plan)
        self.assertEqual(encoded, (FIXTURES / 'inline-1x1.json').read_bytes())
        self.assertEqual(decode_plan(encoded, self.limits), self.plan)
        self.assertEqual(plan_digest(self.plan), hashlib.sha256(encoded).hexdigest())
        self.assertNotIn(b' ', encoded.replace(b'manual inline 1x1', b''))

    def test_reordered_keys_canonicalize_and_operations_remain_ordered(self):
        obj = json.loads(encode_plan(self.plan))
        reordered = dict(reversed(list(obj.items())))
        self.assertEqual(encode_plan(decode_plan(json.dumps(reordered).encode(), self.limits)),
                         encode_plan(self.plan))
        reordered['operations'][1], reordered['operations'][2] = (
            reordered['operations'][2], reordered['operations'][1])
        self.reject(json.dumps(reordered).encode())
        a = replace(self.plan, operations=self.plan.operations + (
            Operation('output_store', operands=(14,), index=1),))
        b = replace(a, operations=a.operations[:-2] + (a.operations[-1], a.operations[-2]))
        self.assertNotEqual(plan_digest(a), plan_digest(b))

    def test_duplicate_keys_and_bool_indices_rejected(self):
        self.reject((FIXTURES / 'duplicate-key.json').read_bytes(), 'DUPLICATE_KEY')
        self.reject(encode_plan(self.plan).replace(b'"index":0', b'"index":true', 1))
        self.reject(self.mutate(scratch_capacity_cells=True))
        self.reject(self.mutate(format_version=True))
        data = encode_plan(self.plan).replace(b'"operands":[1,0]', b'"operands":[true,0]', 1)
        self.reject(data)

    def test_unknown_fields_operations_and_version(self):
        self.reject(self.mutate(extra=1))
        self.reject(encode_plan(self.plan).replace(b'"opcode":"const"', b'"opcode":"call"', 1),
                    'UNKNOWN_OPCODE')
        self.reject(self.mutate(format_version=2), 'UNSUPPORTED_PLAN_VERSION')
        self.reject(encode_plan(self.plan).replace(b'"dst":0', b'"extra":0,"dst":0', 1))

    def test_floats_nan_and_large_integer_tokens(self):
        for token in (b'1.0', b'1e0', b'NaN', b'Infinity', b'-Infinity', b'12345678901', b'-12345678901'):
            with self.subTest(token=token):
                self.reject(encode_plan(self.plan).replace(b'"scratch_capacity_cells":0',
                            b'"scratch_capacity_cells":' + token))
        self.reject((FIXTURES / 'overlong-integer.json').read_bytes(), 'INTEGER_TOKEN_LIMIT')

    def test_negative_indices_capacity_and_i32_constants(self):
        for fields in ({'scratch_capacity_cells': -1}, {'scratch_capacity_cells': 2147483648}):
            self.reject(self.mutate(**fields))
        for before, after in ((b'"index":0', b'"index":-1'),
                              (b'"value":1', b'"value":2147483648'),
                              (b'"value":1', b'"value":-2147483649'),
                              (b'"origins":[0]', b'"origins":[-1]')):
            self.reject(encode_plan(self.plan).replace(before, after, 1))
        for value in (-2147483648, 2147483647):
            p = replace(self.plan, operations=(Operation('const', dst=0, value=value),))
            self.assertEqual(decode_plan(encode_plan(p), self.limits), p)

    def test_byte_and_operation_quotas(self):
        self.reject(encode_plan(self.plan), 'BYTE_LIMIT', replace(self.limits, plan_bytes=8))
        self.reject(encode_plan(self.plan), 'OPERATION_LIMIT',
                    replace(self.limits, plan_operations=1))
        many = b'{"operations":[' + b'{},' * 1000 + b'{}]}'
        error = self.reject(many, 'OPERATION_LIMIT', replace(self.limits, plan_operations=1))
        self.assertEqual(error.field_path, '$.operations')

    def test_fixed_fields_and_opcode_shapes(self):
        obj = json.loads(encode_plan(self.plan))
        for key in ('opcode', 'dst', 'operands', 'index', 'value', 'origins'):
            changed = json.loads(json.dumps(obj))
            del changed['operations'][0][key]
            self.reject(json.dumps(changed).encode())
        for op in (Operation('const', dst=0, value=1, index=0),
                   Operation('input_load', dst=0), Operation('add', dst=0, operands=(0,)),
                   Operation('output_store', dst=0, operands=(0,), index=0),
                   Operation('const', dst=None, value=1)):
            with self.subTest(op=op), self.assertRaises(DecodeError):
                validate_plan(replace(self.plan, operations=(op,)), self.limits)

    def test_dense_ssa_prior_references_and_scratch_bounds(self):
        for ops, capacity in (((Operation('const', dst=1, value=1),), 0),
                              ((Operation('add', dst=0, operands=(0, 0)),), 0),
                              ((Operation('scratch_load', dst=0, index=0),), 0),
                              ((Operation('const', dst=0, value=1),
                                Operation('scratch_store', operands=(0,), index=1)), 1)):
            with self.subTest(ops=ops), self.assertRaises(DecodeError):
                validate_plan(replace(self.plan, operations=ops, scratch_capacity_cells=capacity), self.limits)
        scratch = replace(self.plan, scratch_capacity_cells=2147483647,
                          operations=(Operation('scratch_load', dst=0, index=2147483646),))
        self.assertEqual(decode_plan(encode_plan(scratch), self.limits), scratch)

    def test_memory_records_are_not_privileged(self):
        for p in (replace(self.plan, operations=list(self.plan.operations)),
                  replace(self.plan, operations=(Operation('const', dst=True, value=1),)),
                  replace(self.plan, operations=(Operation('const', dst=0, value=True),)),
                  replace(self.plan, operations=(Operation('const', dst=0, value=1, origins=[0]),)),
                  replace(self.plan, semantic_digest='not sha256'),
                  replace(self.plan, plan_id='x' * 257)):
            with self.subTest(p=p), self.assertRaises(DecodeError):
                validate_plan(p, self.limits)
        labeled = replace(self.plan, plan_id='arbitrary 🧮 label')
        self.assertEqual(decode_plan(encode_plan(labeled), self.limits), labeled)

    def test_direct_records_respect_effective_canonical_byte_limit(self):
        escaped = replace(self.plan, plan_id='label \"\n 🧮', operations=(
            Operation('const', dst=0, value=-2147483648, origins=(0, 10, 9999999999)),))
        for plan in (self.plan, escaped):
            encoded = encode_plan(plan)
            validate_plan(plan, replace(self.limits, plan_bytes=len(encoded)))
            for budget in (1, len(encoded) - 1):
                with self.subTest(plan_id=plan.plan_id, budget=budget):
                    with self.assertRaises(DecodeError) as raised:
                        validate_plan(plan, replace(self.limits, plan_bytes=budget))
                    self.assertEqual(raised.exception.code, 'BYTE_LIMIT')

    def test_validation_does_not_serialize_each_operation(self):
        plan = replace(self.plan, operations=tuple(
            Operation('const', dst=i, value=i) for i in range(256)))
        with cProfile.Profile() as profile:
            validate_plan(plan, self.limits)
        dumps_calls = sum(entry.callcount for entry in profile.getstats()
                          if entry.code is json.dumps.__code__)
        # The bounded header may be serialized once; operations need only
        # structural validation and size accounting, with no temporary JSON.
        self.assertLessEqual(dumps_calls, 1)

    def test_encoding_does_not_repeat_generic_json_tree_validation(self):
        with cProfile.Profile() as profile:
            encoded = encode_plan(self.plan)
        self.assertEqual(encoded, (FIXTURES / 'inline-1x1.json').read_bytes())
        generic_calls = sum(entry.callcount for entry in profile.getstats()
                            if entry.code is canonical_json.__code__)
        # Structural plan validation already checks every primitive. Only the
        # fixed-size header may use the generic primitive validator again.
        self.assertLessEqual(generic_calls, 1)

    def test_canonical_size_matches_independent_json_oracle_at_every_prefix(self):
        origin_lists = ([], [0], [0, 9, 10, 99, 100, 9999999999])
        rows = [('const', i, [], None, value) for i, value in enumerate((
            -2147483648, -1000000000, -100, -10, -1, 0, 1, 9, 10, 99, 100,
            2147483647))]
        rows.extend((('input_load', 12, [], 9999999999, None),
                     ('add', 13, [9, 10], None, None),
                     ('mul', 14, [11, 12], None, None),
                     ('scratch_store', None, [13], 2147483646, None),
                     ('scratch_load', 15, [], 2147483646, None),
                     ('output_store', None, [15], 9999999999, None)))
        raw_operations = [
            {'opcode': opcode, 'dst': dst, 'operands': operands, 'index': index,
             'value': value, 'origins': origin_lists[i % len(origin_lists)]}
            for i, (opcode, dst, operands, index, value) in enumerate(rows)]
        operations = tuple(Operation(op['opcode'], op['dst'], tuple(op['operands']),
                                     op['index'], op['value'], tuple(op['origins']))
                           for op in raw_operations)
        for label in ('plain', 'quote " slash \\ /', '\0\b\f\n\r\t\x1f',
                      'café 🧮', 'é' * 128):
            for count in range(len(operations) + 1):
                with self.subTest(label=label, operation_count=count):
                    raw = {'format_version': 1, 'semantic_digest': 'b' * 64,
                           'plan_id': label, 'scratch_capacity_cells': 2147483647,
                           'operations': raw_operations[:count]}
                    expected = json.dumps(raw, sort_keys=True, separators=(',', ':'),
                                          ensure_ascii=False, allow_nan=False).encode('utf-8')
                    plan = Plan(1, 'b' * 64, label, 2147483647, operations[:count])
                    exact = replace(self.limits, plan_bytes=len(expected))
                    validate_plan(plan, exact)
                    self.assertEqual(encode_plan(plan, limits=exact), expected)
                    self.assertEqual(plan_digest(plan, limits=exact),
                                     hashlib.sha256(expected).hexdigest())
                    self.assertEqual(decode_plan(expected, exact), plan)
                    short = replace(exact, plan_bytes=len(expected) - 1)
                    with self.assertRaises(DecodeError) as raised:
                        validate_plan(plan, short)
                    self.assertEqual(raised.exception.code, 'BYTE_LIMIT')
                    with self.assertRaises(DecodeError) as raised:
                        encode_plan(plan, limits=short)
                    self.assertEqual(raised.exception.code, 'BYTE_LIMIT')

    def test_oversized_direct_origins_tuple_respects_default_byte_limit(self):
        oversized = replace(self.plan, operations=(
            Operation('const', dst=0, value=1, origins=(0,) * 1048576),))
        with self.assertRaises(DecodeError) as raised:
            validate_plan(oversized, self.limits)
        self.assertEqual(raised.exception.code, 'BYTE_LIMIT')
        with self.assertRaises(DecodeError) as encoded:
            encode_plan(oversized)
        self.assertEqual(encoded.exception.code, 'BYTE_LIMIT')

    def test_encoding_and_digest_use_explicit_limits(self):
        oversized = replace(self.plan, operations=(
            Operation('const', dst=0, value=1, origins=(0,) * 1048576),))
        larger = replace(self.limits, plan_bytes=3 * 1024 * 1024)
        encoded = encode_plan(oversized, limits=larger)
        self.assertGreater(len(encoded), self.limits.plan_bytes)
        self.assertEqual(plan_digest(oversized, limits=larger),
                         hashlib.sha256(encoded).hexdigest())
        self.assertEqual(decode_plan(encoded, larger), oversized)
        for encode in (encode_plan, plan_digest):
            with self.subTest(encode=encode.__name__), self.assertRaises(DecodeError) as raised:
                encode(self.plan, limits=replace(self.limits, plan_bytes=1))
            self.assertEqual(raised.exception.code, 'BYTE_LIMIT')

    def test_json_primitive_policy(self):
        self.assertEqual(canonical_json({'z': None, 'á': [True, False, -1]}),
                         '{"z":null,"á":[true,false,-1]}'.encode())
        for value in (1.0, float('nan'), {1: 'key'}, ('not', 'JSON'), '\ud800'):
            with self.subTest(value=value), self.assertRaises(DecodeError):
                canonical_json(value)
        self.assertEqual(strict_json_loads(b'{"a":[true,null,-1]}'), {'a': [True, None, -1]})

    def test_json_invalid_encoding_syntax_and_depth(self):
        for data in (b'\xff', b'{}{}', b'{"x":01}', b'{"x":+1}', b'{"x":1,}',
                     b'{"x":"\\ud800"}', b'[', b'\xef\xbb\xbf{}', b'{"x":null}\x00'):
            with self.subTest(data=data), self.assertRaises(DecodeError):
                strict_json_loads(data)
        with self.assertRaises(DecodeError):
            strict_json_loads(b'[' * 1000 + b']' * 1000)
        with self.assertRaises(DecodeError):
            strict_json_loads(b'[0,1,2]', max_items=2)
        with self.assertRaises(DecodeError):
            strict_json_loads(b'{"a":0,"b":1,"c":2}', max_items=2)
        with self.assertRaises(DecodeError):
            strict_json_loads(b'{}', max_bytes=1)


if __name__ == '__main__':
    unittest.main()
