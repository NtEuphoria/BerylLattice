"""Strict bounded JSON and versioned physical-plan serialization.

Only JSON primitives cross this boundary. The small parser enforces quotas
before integer conversion and container insertion, including the operation
array quota before parsing an excess operation. Decoding does not run a plan.
"""
import hashlib
import json
import re
from json.decoder import scanstring

from .model import Limits
from .plan_format import Operation, Plan


class DecodeError(ValueError):
    """Artifact rejection with a stable category and JSON-style field path."""

    def __init__(self, code: str, field_path: str, message: str):
        self.code = code
        self.field_path = field_path
        self.path = field_path
        super().__init__(f'{code} at {field_path}: {message}')


def _fail(code, path, message):
    raise DecodeError(code, path, message)


def _positive_limit(value, name):
    if type(value) is not int or value <= 0:
        _fail('INVALID_LIMIT', '$.' + name, 'limit must be a positive exact integer')


class _JSONParser:
    def __init__(self, text, max_items, max_depth, max_integer_digits, operation_limit):
        self.text = text
        self.pos = 0
        self.items = 0
        self.max_items = max_items
        self.max_depth = max_depth
        self.max_integer_digits = max_integer_digits
        self.operation_limit = operation_limit

    def whitespace(self):
        while self.pos < len(self.text) and self.text[self.pos] in ' \t\r\n':
            self.pos += 1

    def item(self, path):
        if self.items >= self.max_items:
            _fail('CONTAINER_LIMIT', path, 'JSON container item quota exceeded')
        self.items += 1

    def string(self, path):
        try:
            value, self.pos = scanstring(self.text, self.pos + 1, True)
            value.encode('utf-8')
        except (ValueError, UnicodeError) as error:
            _fail('INVALID_JSON', path, f'invalid JSON string: {error}')
        return value

    def value(self, path='$', depth=0):
        self.whitespace()
        if depth > self.max_depth:
            _fail('DEPTH_LIMIT', path, 'JSON nesting quota exceeded')
        if self.pos >= len(self.text):
            _fail('INVALID_JSON', path, 'expected a JSON value')
        ch = self.text[self.pos]
        if ch == '"':
            return self.string(path)
        if ch in '[{':
            self.pos += 1
            self.whitespace()
            is_object = ch == '{'
            close = '}' if is_object else ']'
            result = {} if is_object else []
            if self.pos < len(self.text) and self.text[self.pos] == close:
                self.pos += 1
                return result
            while True:
                self.whitespace()
                if not is_object and path == '$.operations' and self.operation_limit is not None:
                    if len(result) >= self.operation_limit:
                        _fail('OPERATION_LIMIT', path, 'physical operation quota exceeded')
                self.item(path)
                if is_object:
                    if self.pos >= len(self.text) or self.text[self.pos] != '"':
                        _fail('INVALID_JSON', path, 'expected an object key')
                    key = self.string(path)
                    child_path = path + '.' + key
                    if key in result:
                        _fail('DUPLICATE_KEY', child_path, 'duplicate object key')
                    self.whitespace()
                    if self.pos >= len(self.text) or self.text[self.pos] != ':':
                        _fail('INVALID_JSON', child_path, 'expected colon after key')
                    self.pos += 1
                    result[key] = self.value(child_path, depth + 1)
                else:
                    result.append(self.value(f'{path}[{len(result)}]', depth + 1))
                self.whitespace()
                if self.pos >= len(self.text):
                    _fail('INVALID_JSON', path, 'unterminated container')
                delimiter = self.text[self.pos]
                self.pos += 1
                if delimiter == close:
                    return result
                if delimiter != ',':
                    _fail('INVALID_JSON', path, 'expected comma or closing delimiter')
        for spelling, value in (('true', True), ('false', False), ('null', None)):
            if self.text.startswith(spelling, self.pos):
                self.pos += len(spelling)
                return value
        if ch == '-' or '0' <= ch <= '9':
            start = self.pos
            if ch == '-':
                self.pos += 1
            digit_start = self.pos
            while self.pos < len(self.text) and '0' <= self.text[self.pos] <= '9':
                self.pos += 1
                if self.pos - digit_start > self.max_integer_digits:
                    _fail('INTEGER_TOKEN_LIMIT', path, 'integer token too long')
            if self.pos == digit_start:
                _fail('INVALID_JSON', path, 'expected decimal integer')
            if self.pos - digit_start > 1 and self.text[digit_start] == '0':
                _fail('INVALID_JSON', path, 'leading zero in integer')
            if self.pos < len(self.text) and self.text[self.pos] in '.eE':
                _fail('NON_INTEGER_NUMBER', path, 'floating point JSON numbers are forbidden')
            return int(self.text[start:self.pos])
        _fail('INVALID_JSON', path, 'unsupported or invalid JSON value')


def strict_json_loads(data: bytes, *, max_bytes=2097152, max_items=300000,
                      max_depth=64, max_integer_digits=10, _operation_limit=None):
    """Decode bounded UTF-8 JSON, rejecting duplicates, floats and surrogates.

    ``max_items`` counts object members and array elements across the document.
    Limits apply before accumulating the next member, element or integer.
    """
    for name, value in (('max_bytes', max_bytes), ('max_items', max_items),
                        ('max_depth', max_depth), ('max_integer_digits', max_integer_digits)):
        _positive_limit(value, name)
    if type(data) is not bytes:
        _fail('INVALID_JSON', '$', 'expected bytes')
    if len(data) > max_bytes:
        _fail('BYTE_LIMIT', '$', 'artifact byte quota exceeded')
    try:
        text = data.decode('utf-8')
    except UnicodeError:
        _fail('INVALID_JSON', '$', 'artifact must be valid UTF-8')
    accepted = _fast_loads(text, max_items, max_depth, max_integer_digits, _operation_limit)
    if accepted is not _REJECTED:
        return accepted
    return _strict_parse(text, max_items, max_depth, max_integer_digits, _operation_limit)


class _Fallback(Exception):
    pass


_REJECTED = object()


def _fast_loads(text, max_items, max_depth, max_integer_digits, operation_limit):
    """C-decoder fast path accepting only what _strict_parse accepts. Hooks refuse
    floats, NaN, long integers and duplicate keys; a post-pass applies depth, item,
    operation and Unicode rules. Otherwise _REJECTED: the strict parser re-reads
    the text, so every rejection keeps its exact code and path."""
    def parse_int(token):
        if len(token) - (token[0] == '-') > max_integer_digits:
            raise _Fallback
        return int(token)

    def refuse(_token):
        raise _Fallback

    def pairs(items):
        result = dict(items)
        if len(result) != len(items):
            raise _Fallback
        return result

    try:
        value = json.loads(text, parse_int=parse_int, parse_float=refuse,
                           parse_constant=refuse, object_pairs_hook=pairs)
    except (ValueError, RecursionError, _Fallback):
        return _REJECTED
    if operation_limit is not None and type(value) is dict:
        operations = value.get('operations')
        if type(operations) is list and len(operations) > operation_limit:
            return _REJECTED
    items = 0
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > max_depth:
            return _REJECTED
        kind = type(item)
        if kind is str:
            try:
                item.encode('utf-8')
            except UnicodeError:
                return _REJECTED
        elif kind is list:
            items += len(item)
            pending.extend((child, depth + 1) for child in item)
        elif kind is dict:
            items += len(item)
            for key, child in item.items():
                try:
                    key.encode('utf-8')
                except UnicodeError:
                    return _REJECTED
                pending.append((child, depth + 1))
        if items > max_items:
            return _REJECTED
    return value


def _strict_parse(text, max_items, max_depth, max_integer_digits, operation_limit):
    parser = _JSONParser(text, max_items, max_depth, max_integer_digits, operation_limit)
    value = parser.value()
    parser.whitespace()
    if parser.pos != len(text):
        _fail('INVALID_JSON', '$', 'trailing data')
    return value


def canonical_json(value) -> bytes:
    """Encode JSON primitives as sorted-key, compact UTF-8 without floats."""
    def visit(item, path, depth):
        if depth > 64:
            _fail('DEPTH_LIMIT', path, 'JSON nesting quota exceeded')
        if item is None or type(item) is bool:
            return
        if type(item) is int:
            if not -9999999999 <= item <= 9999999999:
                _fail('INTEGER_TOKEN_LIMIT', path, 'integer token too long')
            return
        if type(item) is str:
            try:
                item.encode('utf-8')
            except UnicodeError:
                _fail('INVALID_JSON', path, 'strings must contain Unicode scalar values')
            return
        if type(item) is list:
            for i, child in enumerate(item):
                visit(child, f'{path}[{i}]', depth + 1)
            return
        if type(item) is dict:
            for key, child in item.items():
                if type(key) is not str:
                    _fail('INVALID_JSON', path, 'object keys must be strings')
                visit(key, path, depth + 1)
                visit(child, path + '.' + key, depth + 1)
            return
        _fail('INVALID_JSON', path, 'expected JSON primitive, array or object')
    visit(value, '$', 0)
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


_PLAN_FIELDS = {'format_version', 'semantic_digest', 'plan_id',
                'scratch_capacity_cells', 'operations'}
_OPERATION_FIELDS = {'opcode', 'dst', 'operands', 'index', 'value', 'origins'}
# Fixed keys and punctuation; scalar values, opcode text and list contents
# are charged separately after their types and bounds have been validated.
_OPERATION_SHELL_BYTES = len(
    b'{"dst":,"index":,"opcode":"","operands":[],"origins":[],"value":}')
# opcode -> (produces SSA result, operand count, has index, has literal)
_SHAPES = {'const': (True, 0, False, True),
           'input_load': (True, 0, True, False),
           'add': (True, 2, False, False),
           'mul': (True, 2, False, False),
           'scratch_store': (False, 1, True, False),
           'scratch_load': (True, 0, True, False),
           'output_store': (False, 1, True, False)}


def _integer(value, path, minimum=0, maximum=9999999999):
    if type(value) is not int or not minimum <= value <= maximum:
        _fail('INVALID_PLAN', path, f'expected exact integer in [{minimum},{maximum}]')


def _fields(value, fields, path):
    if type(value) is not dict or set(value) != fields:
        _fail('INVALID_PLAN', path, 'missing or unknown fields')


def validate_plan(plan: Plan, limits: Limits) -> None:
    """Validate untrusted in-memory records without allocating scratch storage.

    Dense SSA and prior-use ordering are structural; shape-dependent input and
    output bounds, scratch initialization and output coverage belong to checking.
    """
    _validate_plan(plan, limits)


def _validate_plan(plan, limits):
    """Validate once and return actual metrics for private compilation ranking."""
    for name in ('plan_bytes', 'plan_operations'):
        _positive_limit(getattr(limits, name, None), name)
    if type(plan) is not Plan:
        _fail('INVALID_PLAN', '$', 'expected a Plan record')
    _integer(plan.format_version, '$.format_version')
    if plan.format_version != 1:
        _fail('UNSUPPORTED_PLAN_VERSION', '$.format_version', 'only plan format 1 is supported')
    if type(plan.semantic_digest) is not str or re.fullmatch('[0-9a-f]{64}', plan.semantic_digest) is None:
        _fail('INVALID_PLAN', '$.semantic_digest', 'expected lowercase SHA-256 digest')
    if type(plan.plan_id) is not str or len(plan.plan_id) > 256:
        _fail('INVALID_PLAN', '$.plan_id', 'expected bounded plan label')
    try:
        label_length = len(plan.plan_id.encode('utf-8'))
    except UnicodeError:
        _fail('INVALID_PLAN', '$.plan_id', 'invalid Unicode label')
    if not 1 <= label_length <= 256:
        _fail('INVALID_PLAN', '$.plan_id', 'plan label must contain 1 to 256 UTF-8 bytes')
    _integer(plan.scratch_capacity_cells, '$.scratch_capacity_cells', maximum=2147483647)
    if type(plan.operations) is not tuple:
        _fail('INVALID_PLAN', '$.operations', 'operations must be an immutable tuple')
    if len(plan.operations) > limits.plan_operations:
        _fail('OPERATION_LIMIT', '$.operations', 'physical operation quota exceeded')
    # A direct record has no original bytes: apply the effective quota to its
    # exact canonical size. Header and per-operation shells have bounded size;
    # origins are charged from tuple length before inspecting any elements.
    used_bytes = len(canonical_json(_plan_header_object(plan)))
    if used_bytes > limits.plan_bytes:
        _fail('BYTE_LIMIT', '$', 'canonical plan byte quota exceeded')
    next_dst = 0
    multiplication_ops = 0
    for i, op in enumerate(plan.operations):
        # Valid records need no diagnostic strings or generic integer calls.
        # Keep checks and quota checkpoints in their public first-error order.
        if type(op) is not Operation:
            _fail('INVALID_PLAN', f'$.operations[{i}]', 'expected Operation record')
        if type(op.opcode) is not str or op.opcode not in _SHAPES:
            _fail('UNKNOWN_OPCODE', f'$.operations[{i}].opcode', 'unknown physical opcode')
        result, arity, indexed, literal = _SHAPES[op.opcode]
        if op.opcode == 'mul':
            multiplication_ops += 1
        if result:
            if type(op.dst) is not int or not 0 <= op.dst <= 9999999999:
                _fail('INVALID_PLAN', f'$.operations[{i}].dst',
                      'expected exact integer in [0,9999999999]')
            if op.dst != next_dst:
                _fail('INVALID_PLAN', f'$.operations[{i}].dst', 'SSA definitions must be dense and ordered')
        elif op.dst is not None:
            _fail('INVALID_PLAN', f'$.operations[{i}].dst', 'opcode has no SSA result')
        if type(op.operands) is not tuple or len(op.operands) != arity:
            _fail('INVALID_PLAN', f'$.operations[{i}].operands', 'wrong operand tuple arity')
        for j, operand in enumerate(op.operands):
            if type(operand) is not int or not 0 <= operand <= 9999999999:
                _fail('INVALID_PLAN', f'$.operations[{i}].operands[{j}]',
                      'expected exact integer in [0,9999999999]')
            if operand >= next_dst:
                _fail('INVALID_PLAN', f'$.operations[{i}].operands[{j}]',
                      'SSA operand must refer to an earlier definition')
        if indexed:
            if type(op.index) is not int or not 0 <= op.index <= 9999999999:
                _fail('INVALID_PLAN', f'$.operations[{i}].index',
                      'expected exact integer in [0,9999999999]')
            if op.opcode.startswith('scratch_') and op.index >= plan.scratch_capacity_cells:
                _fail('INVALID_PLAN', f'$.operations[{i}].index', 'scratch index outside reserved arena')
        elif op.index is not None:
            _fail('INVALID_PLAN', f'$.operations[{i}].index', 'opcode has no index')
        if literal:
            if type(op.value) is not int or not -2147483648 <= op.value <= 2147483647:
                _fail('INVALID_PLAN', f'$.operations[{i}].value',
                      'expected exact integer in [-2147483648,2147483647]')
        elif op.value is not None:
            _fail('INVALID_PLAN', f'$.operations[{i}].value', 'opcode has no literal')
        if type(op.origins) is not tuple:
            _fail('INVALID_PLAN', f'$.operations[{i}].origins', 'origins must be an immutable tuple')
        # Opcodes are fixed ASCII names, nullable fields are exact bounded
        # integers or null, and operands contain at most two integers. Account
        # for their exact encoding without constructing JSON for each operation.
        shell_bytes = (_OPERATION_SHELL_BYTES + len(op.opcode)
                       + (len(str(op.dst)) if result else 4)
                       + (len(str(op.index)) if indexed else 4)
                       + (len(str(op.value)) if literal else 4)
                       + sum(len(str(operand)) for operand in op.operands)
                       + max(0, arity - 1))
        used_bytes += shell_bytes + (1 if i else 0)
        if used_bytes > limits.plan_bytes:
            _fail('BYTE_LIMIT', f'$.operations[{i}]', 'canonical plan byte quota exceeded')
        # Every nonnegative origin needs at least one digit and a separator
        # except the first. The shell above already includes the brackets.
        used_bytes += max(0, 2 * len(op.origins) - 1)
        if used_bytes > limits.plan_bytes:
            _fail('BYTE_LIMIT', f'$.operations[{i}].origins', 'canonical plan byte quota exceeded')
        for j, origin in enumerate(op.origins):
            if type(origin) is not int or not 0 <= origin <= 9999999999:
                _fail('INVALID_PLAN', f'$.operations[{i}].origins[{j}]',
                      'expected exact integer in [0,9999999999]')
            used_bytes += len(str(origin)) - 1
            if used_bytes > limits.plan_bytes:
                _fail('BYTE_LIMIT', f'$.operations[{i}].origins[{j}]',
                      'canonical plan byte quota exceeded')
        if result:
            next_dst += 1

    return multiplication_ops, 4 * plan.scratch_capacity_cells


def _plan_header_object(plan):
    return {'format_version': plan.format_version, 'semantic_digest': plan.semantic_digest,
            'plan_id': plan.plan_id, 'scratch_capacity_cells': plan.scratch_capacity_cells,
            'operations': []}


def _operation_object(op, origins):
    return {'opcode': op.opcode, 'dst': op.dst, 'operands': list(op.operands),
            'index': op.index, 'value': op.value, 'origins': origins}


def _plan_object(plan):
    obj = _plan_header_object(plan)
    obj['operations'] = [_operation_object(op, list(op.origins)) for op in plan.operations]
    return obj


def encode_plan(plan: Plan, *, limits: Limits = Limits()) -> bytes:
    validate_plan(plan, limits)
    return _encode_validated_plan(plan, limits)


def _encode_validated_plan(plan, limits):
    """Serialize records already validated by their private compilation owner."""
    # Structural validation above already checks every primitive and the exact
    # byte quota before allocating the complete JSON tree and encoded artifact.
    data = json.dumps(_plan_object(plan), sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')
    if len(data) > limits.plan_bytes:
        _fail('BYTE_LIMIT', '$', 'canonical plan byte quota exceeded')
    return data


def decode_plan(data: bytes, limits: Limits) -> Plan:
    for name in ('plan_bytes', 'plan_operations'):
        _positive_limit(getattr(limits, name, None), name)
    obj = strict_json_loads(data, max_bytes=limits.plan_bytes,
                            max_items=limits.plan_bytes,
                            _operation_limit=limits.plan_operations)
    _fields(obj, _PLAN_FIELDS, '$')
    if type(obj['operations']) is not list:
        _fail('INVALID_PLAN', '$.operations', 'expected operation array')
    ops = []
    for i, item in enumerate(obj['operations']):
        path = f'$.operations[{i}]'
        _fields(item, _OPERATION_FIELDS, path)
        for field in ('operands', 'origins'):
            if type(item[field]) is not list:
                _fail('INVALID_PLAN', path + '.' + field, 'expected array')
        ops.append(Operation(item['opcode'], item['dst'], tuple(item['operands']),
                             item['index'], item['value'], tuple(item['origins'])))
    plan = Plan(obj['format_version'], obj['semantic_digest'], obj['plan_id'],
                obj['scratch_capacity_cells'], tuple(ops))
    validate_plan(plan, limits)
    return plan


def plan_digest(plan: Plan, *, limits: Limits = Limits()) -> str:
    return hashlib.sha256(encode_plan(plan, limits=limits)).hexdigest()
