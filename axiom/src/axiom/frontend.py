"""Bounded parsing and structural admission of the single Axiom stencil.

Normalization changes declaration and bound-axis identities only. Parenthesis
nodes remain in the retained AST; comparison ignores those wrappers but keeps
the exact binary tree. No algebraic identities or constant folding are used
when recognizing the supported profile.
"""
from dataclasses import dataclass
import hashlib
import json

from .model import (
    AdmittedKernel, AxisBinding, BinaryExpression, ConstraintDeclaration,
    DiagnosticError, EquationDeclaration, Expression, GroupExpression,
    InputDeclaration, IntegerLiteral, Limits, NameReference, Objective,
    ReadExpression, SEMANTICS_VERSION, ShapeDeclaration, SourceModule, Span,
)


def _fail(code: str, span: Span, message: str):
    raise DiagnosticError(code, span, message)


@dataclass(frozen=True, slots=True)
class _Token:
    text: str
    span: Span


def _lex(data: bytes, limits: Limits) -> tuple[_Token, ...]:
    if type(data) is not bytes:
        _fail('INVALID_SOURCE', Span(0, 0), 'source must be immutable bytes')
    if len(data) > limits.source_bytes:
        _fail('SOURCE_BYTES_LIMIT', Span(0, len(data)), 'source byte quota exceeded')
    try:
        data.decode('utf-8', errors='strict')
    except UnicodeDecodeError as exc:
        _fail('INVALID_UTF8', Span(exc.start, exc.end-exc.start), 'invalid UTF-8')
    nul = data.find(b'\0')
    if nul >= 0:
        _fail('NUL_BYTE', Span(nul, 1), 'NUL is forbidden even in comments')
    tokens = []
    pos = 0
    while pos < len(data):
        byte = data[pos]
        if byte in b' \t\r\n\v\f':
            pos += 1
            continue
        if data[pos:pos+2] == b'//':
            end = data.find(b'\n', pos)
            pos = len(data) if end < 0 else end+1
            continue
        start = pos
        if 65 <= byte <= 90 or 97 <= byte <= 122 or byte == 95:
            pos += 1
            while pos < len(data) and (65 <= data[pos] <= 90 or
                    97 <= data[pos] <= 122 or 48 <= data[pos] <= 57 or data[pos] == 95):
                pos += 1
        elif 48 <= byte <= 57:
            pos += 1
            while pos < len(data) and 48 <= data[pos] <= 57:
                pos += 1
            if pos-start > 10:
                _fail('INTEGER_TOKEN_LIMIT', Span(start, pos-start), 'integer tokens have at most ten digits')
        else:
            matched = next((x for x in (b'..=', b'..', b'<=') if data.startswith(x, pos)), None)
            if matched is not None:
                pos += len(matched)
            elif byte in b';=:[],()+*-':
                pos += 1
            else:
                # Byte offsets do not depend on Python's Unicode character indices.
                size = len(data[pos:].decode('utf-8')[0].encode('utf-8'))
                _fail('INVALID_TOKEN', Span(pos, size), 'unexpected source character')
        tokens.append(_Token(data[start:pos].decode('ascii'), Span(start, pos-start)))
    tokens.append(_Token('', Span(len(data), 0)))
    return tuple(tokens)


class _Parser:
    def __init__(self, data: bytes, limits: Limits):
        self.data = data
        self.limits = limits
        self.tokens = _lex(data, limits)
        self.pos = 0
        self.nodes = 0
        self.depths = {}

    @property
    def token(self):
        return self.tokens[self.pos]

    def take(self, text: str | None = None):
        token = self.token
        if text is not None and token.text != text:
            _fail('SYNTAX_ERROR', token.span, f'expected {text!r}')
        if not token.text:
            _fail('SYNTAX_ERROR', token.span, 'unexpected end of source')
        self.pos += 1
        return token

    def identifier(self):
        token = self.token
        if not token.text or not (token.text[0].isascii() and
                (token.text[0].isalpha() or token.text[0] == '_')):
            _fail('SYNTAX_ERROR', token.span, 'expected an ASCII identifier')
        return self.take()

    def span_from(self, start):
        end = self.tokens[self.pos-1].span
        return Span(start.offset, end.offset+end.length-start.offset)

    def node(self, value, children=()):
        self.nodes += 1
        if self.nodes > self.limits.expression_nodes:
            _fail('EXPRESSION_NODES_LIMIT', value.span, 'expression node quota exceeded')
        depth = 1 + max((self.depths[id(child)] for child in children), default=0)
        if depth > 32:
            _fail('EXPRESSION_DEPTH_LIMIT', value.span, 'expression nesting exceeds 32')
        self.depths[id(value)] = depth
        return value

    def integer(self):
        start = self.token.span
        sign = -1 if self.token.text == '-' else 1
        if sign == -1:
            self.take('-')
        token = self.take()
        if not token.text.isdecimal():
            _fail('SYNTAX_ERROR', token.span, 'unary minus is allowed only on a decimal literal')
        return self.node(IntegerLiteral(sign*int(token.text), self.span_from(start)))

    def expression(self, scalar=False, nesting=0):
        if nesting > 32:
            _fail('EXPRESSION_DEPTH_LIMIT', self.token.span, 'expression nesting exceeds 32')
        left = self.product(scalar, nesting)
        while self.token.text == '+':
            self.take('+')
            right = self.product(scalar, nesting)
            left = self.node(BinaryExpression('+', left, right,
                Span(left.span.offset, right.span.offset+right.span.length-left.span.offset)), (left, right))
        return left

    def product(self, scalar, nesting):
        left = self.atom(scalar, nesting)
        while scalar and self.token.text == '*':
            self.take('*')
            right = self.atom(scalar, nesting)
            left = self.node(BinaryExpression('*', left, right,
                Span(left.span.offset, right.span.offset+right.span.length-left.span.offset)), (left, right))
        return left

    def atom(self, scalar, nesting):
        token = self.token
        if token.text == '-' or token.text.isdecimal():
            return self.integer()
        if token.text == '(':
            if nesting >= 32:
                _fail('EXPRESSION_DEPTH_LIMIT', token.span, 'expression nesting exceeds 32')
            self.take('(')
            child = self.expression(scalar, nesting+1)
            self.take(')')
            return self.node(GroupExpression(child, self.span_from(token.span)), (child,))
        name = self.identifier()
        if scalar and self.token.text == '[':
            self.take('[')
            indices = [self.expression(False, nesting+1)]
            while self.token.text == ',':
                self.take(',')
                indices.append(self.expression(False, nesting+1))
            self.take(']')
            return self.node(ReadExpression(name.text, tuple(indices), self.span_from(name.span), name.span), indices)
        return self.node(NameReference(name.text, name.span))

    def parse(self):
        self.take('module')
        module_name = self.identifier().text
        self.take(';')
        declarations, shapes, inputs, producers, outputs, constraints = [], [], [], [], [], []
        cap = None
        objective = Objective.MULTIPLICATION_OPS
        prefer_seen = False
        while self.token.text:
            start = self.take()
            if start.text == 'shape':
                name = self.identifier()
                self.take('=')
                value = self.expression()
                self.take(';')
                decl = ShapeDeclaration(name.text, value, self.span_from(start.span), name.span)
                shapes.append(decl)
            elif start.text == 'input':
                name = self.identifier()
                self.take(':')
                element_type = self.identifier().text
                self.take('[')
                dimensions = [self.expression()]
                while self.token.text == ',':
                    self.take(',')
                    dimensions.append(self.expression())
                self.take(']')
                self.take('in')
                lower = self.integer().value
                self.take('..=')
                upper = self.integer().value
                self.take(';')
                decl = InputDeclaration(name.text, element_type, tuple(dimensions), (lower, upper), self.span_from(start.span), name.span)
                inputs.append(decl)
            elif start.text in ('let', 'output'):
                name = self.identifier()
                self.take('[')
                axes = []
                while True:
                    axis_name = self.identifier()
                    self.take('in')
                    lower = self.expression()
                    self.take('..')
                    upper = self.expression()
                    axes.append(AxisBinding(axis_name.text, lower, upper, self.span_from(axis_name.span), axis_name.span))
                    if self.token.text != ',':
                        break
                    self.take(',')
                self.take(']')
                self.take('=')
                expression = self.expression(True)
                self.take(';')
                decl = EquationDeclaration(name.text, tuple(axes), expression, self.span_from(start.span), name.span,
                                           'producer' if start.text == 'let' else 'output')
                (producers if start.text == 'let' else outputs).append(decl)
            elif start.text == 'require':
                name = self.identifier()
                self.take('<=')
                value = self.integer().value
                self.take(';')
                decl = ConstraintDeclaration(name.text, value, self.span_from(start.span))
                constraints.append(decl)
                if name.text == 'plan_workspace_bytes':
                    cap = value if cap is None else min(cap, value)
            elif start.text == 'prefer':
                if prefer_seen:
                    _fail('DUPLICATE_OBJECTIVE', start.span, 'only one objective is allowed')
                prefer_seen = True
                value = self.identifier()
                self.take(';')
                try:
                    objective = Objective(value.text)
                except ValueError:
                    objective = value.text
                continue
            else:
                _fail('SYNTAX_ERROR', start.span, 'expected a declaration')
            declarations.append(decl)
        return SourceModule(self.data, hashlib.sha256(self.data).hexdigest(), module_name,
                            tuple(shapes), tuple(inputs), tuple(producers), tuple(outputs),
                            cap, objective, Span(0, len(self.data)), tuple(declarations), tuple(constraints))


def parse_source(data: bytes, limits: Limits = Limits()) -> SourceModule:
    """Parse a bounded immutable source snapshot without executing any source."""
    return _Parser(data, limits).parse()


def _ungroup(expression):
    while isinstance(expression, GroupExpression):
        expression = expression.expression
    return expression


def _constant(expression, values):
    expression = _ungroup(expression)
    if isinstance(expression, IntegerLiteral):
        return expression.value
    if isinstance(expression, NameReference):
        if expression.name not in values:
            _fail('UNDEFINED_NAME', expression.span, f'undefined shape {expression.name!r}')
        return values[expression.name]
    if isinstance(expression, BinaryExpression) and expression.operator == '+':
        return _constant(expression.left, values)+_constant(expression.right, values)
    _fail('INVALID_EXPRESSION', expression.span, 'expected a constant shape expression')


def _interval(expression, shapes, axes):
    expression = _ungroup(expression)
    if isinstance(expression, IntegerLiteral):
        return expression.value, expression.value
    if isinstance(expression, NameReference):
        if expression.name in axes:
            return axes[expression.name]
        if expression.name in shapes:
            value = shapes[expression.name]
            return value, value
        _fail('UNDEFINED_NAME', expression.span, f'undefined index {expression.name!r}')
    if isinstance(expression, BinaryExpression) and expression.operator == '+':
        a, b = _interval(expression.left, shapes, axes)
        c, d = _interval(expression.right, shapes, axes)
        return a+c, b+d
    _fail('INVALID_EXPRESSION', expression.span, 'invalid index expression')


def _validate_scalar(expression, shapes, axes, tensors):
    pending = [expression]
    while pending:
        node = _ungroup(pending.pop())
        if isinstance(node, IntegerLiteral):
            if not -2147483648 <= node.value <= 2147483647:
                _fail('INVALID_INTEGER', node.span, 'scalar literal does not fit i32')
        elif isinstance(node, BinaryExpression):
            pending.extend((node.right, node.left))
        elif isinstance(node, ReadExpression):
            if node.name not in tensors:
                _fail('UNDEFINED_NAME', node.name_span, f'undefined tensor {node.name!r}')
            dimensions = tensors[node.name]
            if len(node.indices) != len(dimensions):
                _fail('INVALID_INDEX', node.span, 'tensor rank does not match read')
            for index, (lower, upper) in zip(node.indices, dimensions):
                lo, hi = _interval(index, shapes, axes)
                if lo < lower or hi >= upper:
                    _fail('INVALID_INDEX', index.span, 'read may exceed the declared tensor bounds')
        elif isinstance(node, NameReference):
            _fail('UNDEFINED_NAME', node.span, 'scalar values must be tensor reads or integer literals')
        else:
            _fail('INVALID_EXPRESSION', node.span, 'unknown scalar expression')


def _validate(module):
    names, shapes, tensors = set(), {}, {}
    for decl in module.declarations:
        if isinstance(decl, ConstraintDeclaration):
            continue
        if decl.name in names:
            _fail('DUPLICATE_NAME', decl.name_span, f'duplicate declaration {decl.name!r}')
        names.add(decl.name)
        if isinstance(decl, ShapeDeclaration):
            value = _constant(decl.value, shapes)
            if value <= 0:
                _fail('INVALID_SHAPE', decl.value.span, 'shape dimensions must be positive')
            shapes[decl.name] = value
        elif isinstance(decl, InputDeclaration):
            dimensions = tuple((0, _constant(value, shapes)) for value in decl.dimensions)
            if any(upper <= 0 for _, upper in dimensions):
                _fail('INVALID_SHAPE', decl.span, 'input dimensions must be positive')
            if decl.input_interval[0] > decl.input_interval[1]:
                _fail('INVALID_RANGE', decl.span, 'input interval is inverted')
            tensors[decl.name] = dimensions
        else:
            axes = {}
            for axis in decl.axes:
                if axis.name in axes:
                    _fail('DUPLICATE_NAME', axis.name_span, 'duplicate bound axis')
                lower = _constant(axis.lower, shapes)
                upper = _constant(axis.upper, shapes)
                if lower >= upper:
                    _fail('INVALID_RANGE', axis.span, 'axis range must be nonempty')
                axes[axis.name] = lower, upper-1
            _validate_scalar(decl.expression, shapes, axes, tensors)
            tensors[decl.name] = tuple((axes[axis.name][0], axes[axis.name][1]+1) for axis in decl.axes)
    return shapes


def _normalized(expression: Expression, index_names: dict[str, str],
                tensor_names: dict[str, str]):
    node = _ungroup(expression)
    if isinstance(node, IntegerLiteral):
        return ['integer', node.value]
    if isinstance(node, NameReference):
        return ['name', index_names.get(node.name, node.name)]
    if isinstance(node, BinaryExpression):
        return [node.operator, _normalized(node.left, index_names, tensor_names),
                _normalized(node.right, index_names, tensor_names)]
    if isinstance(node, ReadExpression):
        return ['read', tensor_names.get(node.name, node.name),
                [_normalized(i, index_names, tensor_names) for i in node.indices]]
    _fail('INVALID_EXPRESSION', node.span, 'unknown expression record')


def _profile(module):
    """Normalize tensor bases independently from locally scoped axis names."""
    shapes = {decl.name: f'shape{index}' for index, decl in enumerate(module.shapes)}
    tensors = {decl.name: f'input{index}' for index, decl in enumerate(module.inputs)}
    tensors.update({decl.name: f'producer{index}' for index, decl in enumerate(module.producers)})
    tensors.update({decl.name: f'output{index}' for index, decl in enumerate(module.outputs)})
    equations = []
    for decl in (*module.producers, *module.outputs):
        local = dict(shapes)
        local.update({axis.name: f'axis{index}' for index, axis in enumerate(decl.axes)})
        equations.append([
            [[_normalized(axis.lower, shapes, tensors), _normalized(axis.upper, shapes, tensors)]
             for axis in decl.axes],
            _normalized(decl.expression, local, tensors),
        ])
    return {
        'inputs': [[decl.element_type, [_normalized(d, shapes, tensors) for d in decl.dimensions],
                    list(decl.input_interval)] for decl in module.inputs],
        'equations': equations,
    }


def _canonical_profile():
    integer = lambda value: ['integer', value]
    name = lambda value: ['name', value]
    add = lambda a, b: ['+', a, b]
    row, col = name('axis0'), name('axis1')
    height, width = name('shape0'), name('shape1')
    read = lambda tensor, r, c: ['read', tensor, [r, c]]
    increment = add(read('input0', row, col), integer(1))
    consumer = add(add(add(read('producer0', row, col),
                           read('producer0', row, add(col, integer(1)))),
                       read('producer0', add(row, integer(1)), col)),
                   read('producer0', add(row, integer(1)), add(col, integer(1))))
    return {'inputs': [['i32', [add(height, integer(1)), add(width, integer(1))], [0, 1023]]],
            'equations': [
                [[[integer(0), add(height, integer(1))], [integer(0), add(width, integer(1))]], ['*', increment, increment]],
                [[[integer(0), height], [integer(0), width]], consumer],
            ]}


def admit_source(module: SourceModule) -> AdmittedKernel:
    """Validate all source structure before recognizing the exact stencil profile."""
    if not isinstance(module, SourceModule):
        _fail('INVALID_SOURCE', Span(0, 0), 'expected a SourceModule')
    shapes = _validate(module)
    for constraint in module.constraints:
        if constraint.property_name != 'plan_workspace_bytes':
            _fail('UNSUPPORTED_CONSTRAINT', constraint.span, 'unknown hard property')
        if type(constraint.value) is not int or not 0 <= constraint.value <= 2147483647:
            _fail('INVALID_CONSTRAINT', constraint.span, 'workspace cap must be a nonnegative i32 integer')
    try:
        objective = Objective(module.objective)
    except ValueError:
        _fail('UNSUPPORTED_OBJECTIVE', module.span, 'unknown objective')
    if (len(module.shapes), len(module.inputs), len(module.producers), len(module.outputs)) != (2, 1, 1, 1):
        _fail('UNSUPPORTED_PROFILE', module.span, 'requires exactly two shapes, one input, one producer and one output')
    # Shape declarations must be literal parameters, rather than arbitrary constant propagation.
    if any(not isinstance(_ungroup(decl.value), IntegerLiteral) for decl in module.shapes):
        _fail('UNSUPPORTED_PROFILE', module.span, 'shape parameters must be literal declarations')
    height, width = (shapes[decl.name] for decl in module.shapes)
    if (height+1)*(width+1) > 256:
        _fail('UNSUPPORTED_PROFILE', module.span, 'input exceeds 256 cells')
    profile = _profile(module)
    if profile != _canonical_profile():
        _fail('UNSUPPORTED_PROFILE', module.span, 'source is outside the exact canonical stencil profile')
    semantics = {
        'semantics_version': SEMANTICS_VERSION,
        'height': height, 'width': width, 'profile': profile,
        'arithmetic': 'exact-i32-per-scalar-node',
        'boundary': 'row-major-preflight-preserve-output-first-invalid',
    }
    canonical = json.dumps(semantics, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
    return AdmittedKernel(height, width, module.cap, module.inputs[0].input_interval,
                          objective, module.source_digest, hashlib.sha256(canonical).hexdigest(),
                          (module.producers[0].expression, module.outputs[0].expression),
                          SEMANTICS_VERSION, module)
