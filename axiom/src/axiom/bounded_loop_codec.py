"""Strict bounded byte and record validation for optional compact hints."""
from dataclasses import asdict
import json
import re

from .codec import DecodeError, strict_json_loads
from .bounded_loop_model import (FORMAT_VERSION, I32_MIN, I32_MAX, HintError,
                                 HintLimits, IndexExpr, IndexTerm, Loop,
                                 LoopProgram, Primitive)

# Deliberately independent from planner and finite-plan opcode tables.
SHAPES = {'const': (True, 0, False, True), 'input_load': (True, 0, True, False),
          'add': (True, 2, False, False), 'mul': (True, 2, False, False),
          'scratch_load': (True, 0, True, False),
          'scratch_store': (False, 1, True, False),
          'output_store': (False, 1, True, False)}


def _fail(message, code='INVALID_HINT'):
    raise HintError(code, message)


def _integer(value, low=I32_MIN, high=I32_MAX):
    if type(value) is not int or not low <= value <= high:
        _fail('expected bounded exact integer')


def _name(value):
    if type(value) is not str or re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,31}', value) is None:
        _fail('invalid lexical name')


def validate_loop_program(program, hint_limits=HintLimits()):
    if type(hint_limits) is not HintLimits:
        _fail('expected HintLimits')
    if type(program) is not LoopProgram or program.format_version != FORMAT_VERSION:
        _fail('unsupported bounded hint format')
    for digest in (program.source_digest, program.semantic_digest):
        if type(digest) is not str or re.fullmatch('[0-9a-f]{64}', digest) is None:
            _fail('invalid source digest')
    # Bound the output grid; each kernel's own input/scratch arenas are enforced
    # per index during expansion, and specialization binds the exact kernel
    # shape. Every admitted kernel (canonical or window) has at most 256 inputs.
    _integer(program.height, 1, 256)
    _integer(program.width, 1, 256)
    if program.height*program.width > 256:
        _fail('bounded hints retain the 256-cell boundary')
    _integer(program.scratch_capacity_cells, 0, I32_MAX)
    if type(program.label) is not str or len(program.label) > 256:
        _fail('invalid label')
    try:
        if not 1 <= len(program.label.encode('utf-8')) <= 256:
            _fail('invalid label')
    except UnicodeError:
        _fail('invalid label')
    count = 0

    def charge(amount=1):
        nonlocal count
        count += amount
        if count > hint_limits.syntax_nodes:
            _fail('syntax node quota exceeded', 'HINT_SYNTAX_LIMIT')

    def block(body, depth, scalars, indices):
        if depth > hint_limits.nesting_depth:
            _fail('loop nesting quota exceeded', 'HINT_DEPTH_LIMIT')
        if type(body) is not tuple:
            _fail('body must be immutable tuple')
        # Reject long containers before inspecting children or allocating scopes.
        if len(body) > hint_limits.syntax_nodes-count:
            _fail('syntax node quota exceeded', 'HINT_SYNTAX_LIMIT')
        local = set(scalars)
        for node in body:
            charge()
            if type(node) is Loop:
                _name(node.variable)
                if node.variable in local or node.variable in indices:
                    _fail('loop name shadows active binding')
                _integer(node.start, 0, 256)
                _integer(node.stop, 0, 256)
                if node.stop < node.start:
                    _fail('reversed loop bounds')
                block(node.body, depth+1, local, indices | {node.variable})
                continue
            if type(node) is not Primitive or type(node.opcode) is not str or node.opcode not in SHAPES:
                _fail('unknown primitive')
            result, arity, indexed, literal = SHAPES[node.opcode]
            if type(node.operands) is not tuple or len(node.operands) != arity:
                _fail('wrong operand arity')
            for operand in node.operands:
                _name(operand)
                if operand not in local:
                    _fail('operand escapes lexical scope or precedes definition')
            if result:
                _name(node.dst)
                if node.dst in local or node.dst in indices:
                    _fail('scalar name shadows active binding')
                local.add(node.dst)
            elif node.dst is not None:
                _fail('store has no scalar result')
            if indexed:
                expr = node.index
                if type(expr) is not IndexExpr or type(expr.terms) is not tuple:
                    _fail('expected immutable index expression')
                charge(1+len(expr.terms))
                _integer(expr.constant)
                for term in expr.terms:
                    if type(term) is not IndexTerm:
                        _fail('invalid index term')
                    _integer(term.coefficient)
                    _integer(term.offset)
                    _name(term.variable)
                    if term.variable not in indices or type(term.modulo2) is not bool:
                        _fail('invalid index variable or modulo flag')
            elif node.index is not None:
                _fail('primitive has no index')
            if literal:
                _integer(node.value)
            elif node.value is not None:
                _fail('primitive has no literal')
            if type(node.origins) is not tuple or len(node.origins) > 32:
                _fail('invalid bounded origins')
            charge(len(node.origins))
            for origin in node.origins:
                _integer(origin, 0, I32_MAX)
    block(program.body, 0, set(), set())


def encode_loop_program(program, hint_limits=HintLimits()):
    validate_loop_program(program, hint_limits)
    data = json.dumps(asdict(program), sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')
    if len(data) > hint_limits.encoded_bytes:
        _fail('encoded hint quota exceeded', 'HINT_BYTE_LIMIT')
    return data


def decode_loop_program(data, hint_limits=HintLimits()):
    if type(hint_limits) is not HintLimits:
        _fail('expected HintLimits')
    try:
        obj = strict_json_loads(data, max_bytes=hint_limits.encoded_bytes,
                               max_items=hint_limits.syntax_nodes*16,
                               max_depth=2*hint_limits.nesting_depth+8,
                               max_integer_digits=10)
    except DecodeError as error:
        raise HintError('HINT_DECODE_'+error.code, str(error)) from error

    def fields(value, cls):
        if type(value) is not dict or set(value) != set(cls.__slots__):
            _fail('missing or unknown fields')

    count = 0
    def block(items, depth=0):
        nonlocal count
        if depth > hint_limits.nesting_depth:
            _fail('loop nesting quota exceeded', 'HINT_DEPTH_LIMIT')
        if type(items) is not list:
            _fail('expected body array')
        if len(items)+count > hint_limits.syntax_nodes:
            _fail('syntax node quota exceeded', 'HINT_SYNTAX_LIMIT')
        result = []
        for item in items:
            count += 1
            if type(item) is dict and 'body' in item:
                fields(item, Loop)
                result.append(Loop(item['variable'], item['start'], item['stop'],
                                   block(item['body'], depth+1)))
            else:
                fields(item, Primitive)
                if type(item['operands']) is not list or type(item['origins']) is not list:
                    _fail('expected operand and origin arrays')
                index = item['index']
                if index is not None:
                    fields(index, IndexExpr)
                    if type(index['terms']) is not list:
                        _fail('expected index terms array')
                    count += 1+len(index['terms'])
                    if count > hint_limits.syntax_nodes:
                        _fail('syntax node quota exceeded', 'HINT_SYNTAX_LIMIT')
                    terms = []
                    for term in index['terms']:
                        fields(term, IndexTerm)
                        terms.append(IndexTerm(**term))
                    index = IndexExpr(index['constant'], tuple(terms))
                result.append(Primitive(item['opcode'], item['dst'], tuple(item['operands']),
                                        index, item['value'], tuple(item['origins'])))
        return tuple(result)
    fields(obj, LoopProgram)
    program = LoopProgram(obj['format_version'], obj['source_digest'], obj['semantic_digest'],
                          obj['height'], obj['width'], obj['scratch_capacity_cells'],
                          block(obj['body']), obj['label'])
    validate_loop_program(program, hint_limits)
    return program
