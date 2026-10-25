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
    CANONICAL_PROFILE, AdmittedKernel, AxisBinding, BinaryExpression, ConstraintDeclaration,
    DiagnosticError, EquationDeclaration, Expression, GroupExpression,
    InputDeclaration, IntegerLiteral, Limits, NameReference, Objective,
    ReadExpression, SEMANTICS_VERSION, ShapeDeclaration, SourceModule, Span, SumExpression,
    VALUE_BOUNDS,
)
from .canonical_profile import _canonical_profile, _normalized, _profile
from .reduce_family import MAX_TERMS, admit_reduce, expand_small_sums, parse_sum, reduce_shape
from .scale_family import admit_scale, scale_shape
from .window_explain import explain, explain_counts
from .window_family import admit_window, window_shape


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
        self.reserved = set()  # shapes, plus the axes of the equation being parsed
        self.sum_names = []

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
        while self.token.text in ('+', '-'):
            operator = self.take()
            if operator.text == '-' and not scalar:
                _fail('SYNTAX_ERROR', operator.span,
                      'subtraction is only allowed in scalar expressions; write indices as r + k with k >= 0')
            right = self.product(scalar, nesting)
            if operator.text == '-':
                # `a - b` is defined as exactly `a + (-1)*b`: every node stays an
                # i32-checked + or *, so checking and every backend are unchanged.
                minus_one = self.node(IntegerLiteral(-1, operator.span))
                right = self.node(BinaryExpression('*', minus_one, right,
                    Span(operator.span.offset, right.span.offset+right.span.length-operator.span.offset)),
                    (minus_one, right))
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
        if scalar and name.text == 'sum' and self.token.text == '(':
            return parse_sum(self, name, nesting)
        if scalar and name.text in ('min', 'max', 'clamp', 'shr', 'shr_round') and self.token.text == '(':
            return self.call(name, nesting)
        if scalar and self.token.text == '[':
            self.take('[')
            indices = [self.expression(False, nesting+1)]
            while self.token.text == ',':
                self.take(',')
                indices.append(self.expression(False, nesting+1))
            self.take(']')
            return self.node(ReadExpression(name.text, tuple(indices), self.span_from(name.span), name.span), indices)
        return self.node(NameReference(name.text, name.span))

    def call(self, name, nesting):
        """`min(a, b)` and `max(a, b)` are binary nodes with operator 'min' or 'max'.

        `clamp(x, lo, hi)` is defined as exactly `min(max(x, lo), hi)`, like
        subtraction: checking and every backend see only min and max.

        `shr(x, k)` is floor(x / 2^k) and `shr_round(x, k)` is floor(x / 2^k + 1/2),
        rounding halves up; k is an integer literal, 0..63 for shr and 1..63 for
        shr_round. Neither can overflow.
        """
        if nesting >= 32:
            _fail('EXPRESSION_DEPTH_LIMIT', name.span, 'expression nesting exceeds 32')
        self.take('(')
        arguments = [self.expression(True, nesting+1)]
        while self.token.text == ',':
            self.take(',')
            arguments.append(self.expression(True, nesting+1))
        self.take(')')
        span = self.span_from(name.span)
        if len(arguments) != (3 if name.text == 'clamp' else 2):
            _fail('SYNTAX_ERROR', span, f'{name.text} takes {3 if name.text == "clamp" else 2} arguments')
        if name.text in ('shr', 'shr_round'):
            amount = _ungroup(arguments[1])
            if not isinstance(amount, IntegerLiteral):
                _fail('SYNTAX_ERROR', arguments[1].span, f'the shift amount of {name.text} must be an integer literal')
            lowest = 1 if name.text == 'shr_round' else 0
            if not lowest <= amount.value <= 63:
                _fail('INVALID_EXPRESSION', arguments[1].span, f'{name.text} shifts by {lowest} to 63 bits')
        if name.text != 'clamp':
            return self.node(BinaryExpression(name.text, *arguments, span), arguments)
        value, lower, upper = arguments
        low, high = _ungroup(lower), _ungroup(upper)
        if isinstance(low, IntegerLiteral) and isinstance(high, IntegerLiteral) and low.value > high.value:
            _fail('INVALID_EXPRESSION', span, 'clamp needs its lower bound <= its upper bound')
        inner = self.node(BinaryExpression('max', value, lower, span), (value, lower))
        return self.node(BinaryExpression('min', inner, upper, span), (inner, upper))

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
                self.reserved.add(name.text)
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
                element_type = 'i32'
                if self.token.text == ':':
                    self.take(':')
                    element_type = self.identifier().text
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
                axis_names = {axis.name for axis in axes} - self.reserved
                self.reserved |= axis_names
                expression = self.expression(True)
                self.reserved -= axis_names
                self.take(';')
                decl = EquationDeclaration(name.text, tuple(axes), expression, self.span_from(start.span), name.span,
                                           'producer' if start.text == 'let' else 'output', element_type)
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


def require_canonical(kernel: AdmittedKernel, consumer: str) -> AdmittedKernel:
    """Refuse non-canonical kernels in paths built only for the canonical stencil."""
    if kernel.profile != CANONICAL_PROFILE:
        _fail('UNSUPPORTED_PROFILE', kernel.source_module.span,
              f'{consumer} supports only the canonical stencil')
    return kernel


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
    # literal: variables of sums small enough to expand; each becomes an
    # integer literal in every term, so it may also be used as a scalar.
    pending = [(expression, axes, frozenset())]
    while pending:
        node, axes, literal = pending.pop()
        node = _ungroup(node)
        if isinstance(node, IntegerLiteral):
            if not -2147483648 <= node.value <= 2147483647:
                _fail('INVALID_INTEGER', node.span, 'scalar literal does not fit i32')
        elif isinstance(node, BinaryExpression):
            pending.extend(((node.right, axes, literal), (node.left, axes, literal)))
        elif isinstance(node, SumExpression):
            # A symbolic sum variable ranges over lower..upper-1 in its body's indices.
            small = node.upper - node.lower <= MAX_TERMS
            pending.append((node.body, {**axes, node.variable: (node.lower, node.upper - 1)},
                            literal | {node.variable} if small else literal))
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
            if node.name not in literal:
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
            if not VALUE_BOUNDS['i32'][0] <= decl.input_interval[0] <= decl.input_interval[1] <= VALUE_BOUNDS['i32'][1]:
                _fail('INVALID_RANGE', decl.span, 'an i32 input range must lie within -2147483648..=2147483647')
            tensors[decl.name] = dimensions
        else:
            if decl.element_type not in VALUE_BOUNDS:
                _fail('UNSUPPORTED_TYPE', decl.name_span, 'equations are i32 or i64')
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
    counts = (len(module.shapes), len(module.inputs), len(module.producers), len(module.outputs))
    if counts not in ((2, 1, 1, 1), (2, 2, 1, 1)):
        span, message = explain_counts(module)
        _fail('UNSUPPORTED_PROFILE', module.span if span.length == 0 else span, message)
    # Shape declarations must be literal parameters, rather than arbitrary constant propagation.
    if any(not isinstance(_ungroup(decl.value), IntegerLiteral) for decl in module.shapes):
        _fail('UNSUPPORTED_PROFILE', module.span, 'shape parameters must be literal declarations')
    height, width = (shapes[decl.name] for decl in module.shapes)
    # Small families first (256 input cells) on the program with small sums
    # expanded into balanced trees, keeping their identities. Any larger
    # member, or a sum of more than 256 terms, is scale-v1 with sums as loops.
    # i64 equations are scale-v1 only: the small families emit i32 code.
    wide = any(decl.element_type != 'i32' for decl in (*module.producers, *module.outputs))
    small = None if wide else expand_small_sums(module)
    profile = _profile(small) if small is not None else None
    canonical = profile == _canonical_profile()
    window = None if canonical or small is None else window_shape(profile)
    if window is not None and (height + window['input_offsets'][0]) * (width + window['input_offsets'][1]) <= 256:
        return admit_window(small, height, width, objective, profile, window)
    reduce = None if canonical or small is None else reduce_shape(profile, height, width)
    if reduce is not None and sum(r * c for r, c in reduce['input_shapes']) <= 256:
        return admit_reduce(small, height, width, objective, profile, reduce)
    if not canonical or (height + 1) * (width + 1) > 256:
        loops = _profile(module)
        scale = scale_shape(loops, height, width)
        if scale is not None:
            return admit_scale(module, height, width, objective, loops, scale)
    if wide:
        _fail('UNSUPPORTED_PROFILE', module.span, 'i64 equations need a scale-v1 program '
              '(a stencil, map or reduction over the shapes H and W)')
    if small is None:
        span, message = explain(module)
        _fail('UNSUPPORTED_PROFILE', span, message)
    if counts[1] != 1:
        span, message = explain(module)
        _fail('UNSUPPORTED_PROFILE', span, message)
    # The canonical stencil and every non-family source keep their historical
    # checks, order and diagnostics unchanged.
    if (height+1)*(width+1) > 256:
        _fail('UNSUPPORTED_PROFILE', module.span, 'input exceeds 256 cells')
    if profile != _canonical_profile():
        # Admission was decided above; the explainer only words the rejection.
        span, message = explain(module)
        _fail('UNSUPPORTED_PROFILE', span, message)
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
