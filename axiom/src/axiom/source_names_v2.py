"""Private, deterministic alpha-renaming for fresh v2 source admission.

An accepted stencil has five global declarations and four bound-axis roles,
so it uses at most nine distinct semantic spellings. One global injective map
preserves equality across namespaces, including axis shadowing. The unchanged
frontend still performs all semantic validation; its maps see only one-character
aliases. This view is never an admitted source or a source-origin authority.

Only semantic names change. Original bytes, spans, literals, groups, operators,
child/declaration order, properties, types and objectives remain intact. The
caller retains the original parsed module, not this transient view.

The counters describe this actual traversal and scan. They are not a complete
admission work bound, a charge-before-work checker, or a feasibility approval.
"""
from dataclasses import dataclass

from .model import (
    AxisBinding, BinaryExpression, ConstraintDeclaration, DiagnosticError,
    EquationDeclaration, GroupExpression, InputDeclaration, IntegerLiteral,
    NameReference, ReadExpression, ShapeDeclaration, SourceModule,
)


_ALIASES = tuple('abcdefghi')


@dataclass(slots=True)
class _NameWork:
    name_occurrences: int = 0
    identifier_bytes: int = 0
    candidate_comparisons: int = 0
    character_comparisons: int = 0
    declaration_visits: int = 0
    axis_visits: int = 0
    expression_visits: int = 0
    rebuilt_records: int = 0


class _BoundedNames:
    """At most nine resident strings, no original-name hashing or sorting."""

    __slots__ = ('originals', 'work')

    def __init__(self, work):
        self.originals = []
        self.work = work

    def _matches(self, name, resident):
        # Each resident is tested once per lookup. Unequal lengths need no
        # character comparisons; equal lengths are scanned once left to right.
        self.work.candidate_comparisons += 1
        if len(name) != len(resident):
            return False
        for index in range(len(name)):
            self.work.character_comparisons += 1
            if name[index] != resident[index]:
                return False
        return True

    def lookup(self, name, span):
        self.work.name_occurrences += 1
        self.work.identifier_bytes += len(name)  # The parser admits ASCII names.
        for index, resident in enumerate(self.originals):
            if self._matches(name, resident):
                return _ALIASES[index]
        if len(self.originals) == len(_ALIASES):
            raise DiagnosticError('UNSUPPORTED_PROFILE', span,
                                  'source uses more than nine distinct semantic names')
        alias = _ALIASES[len(self.originals)]
        self.originals.append(name)
        return alias


@dataclass(frozen=True, slots=True)
class _NameView:
    module: SourceModule
    original_names: tuple[str, ...]
    work: _NameWork


def _build_name_view(module):
    """Build a private view of a freshly parsed, structurally guarded module.

    Categorized tuples are derived from the same rebuilt declaration objects.
    Walking those tuples as additional trees would count and copy expressions
    twice. This private helper does not validate or authorize supplied ASTs.
    """
    work = _NameWork()
    names = _BoundedNames(work)

    def expression(node):
        work.expression_visits += 1
        if isinstance(node, IntegerLiteral):
            return node
        work.rebuilt_records += 1
        if isinstance(node, NameReference):
            return NameReference(names.lookup(node.name, node.span), node.span)
        if isinstance(node, BinaryExpression):
            return BinaryExpression(node.operator, expression(node.left),
                                    expression(node.right), node.span)
        if isinstance(node, ReadExpression):
            name = names.lookup(node.name, node.name_span)
            return ReadExpression(name, tuple(expression(i) for i in node.indices),
                                  node.span, node.name_span)
        if isinstance(node, GroupExpression):
            return GroupExpression(expression(node.expression), node.span)
        raise TypeError('unexpected freshly parsed expression')

    declarations, shapes, inputs, producers, outputs, constraints = [], [], [], [], [], []
    for decl in module.declarations:
        work.declaration_visits += 1
        if isinstance(decl, ConstraintDeclaration):
            rebuilt = decl
            constraints.append(rebuilt)
        else:
            name = names.lookup(decl.name, decl.name_span)
            work.rebuilt_records += 1
            if isinstance(decl, ShapeDeclaration):
                rebuilt = ShapeDeclaration(name, expression(decl.value), decl.span, decl.name_span)
                shapes.append(rebuilt)
            elif isinstance(decl, InputDeclaration):
                rebuilt = InputDeclaration(name, decl.element_type,
                    tuple(expression(d) for d in decl.dimensions), decl.input_interval,
                    decl.span, decl.name_span)
                inputs.append(rebuilt)
            elif isinstance(decl, EquationDeclaration):
                axes = []
                for axis in decl.axes:
                    work.axis_visits += 1
                    axis_name = names.lookup(axis.name, axis.name_span)
                    lower, upper = expression(axis.lower), expression(axis.upper)
                    axes.append(AxisBinding(axis_name, lower, upper, axis.span, axis.name_span))
                    work.rebuilt_records += 1
                rebuilt = EquationDeclaration(name, tuple(axes), expression(decl.expression),
                                               decl.span, decl.name_span, decl.kind)
                (producers if decl.kind == 'producer' else outputs).append(rebuilt)
            else:
                raise TypeError('unexpected freshly parsed declaration')
        declarations.append(rebuilt)
    work.rebuilt_records += 1
    view = SourceModule(module.source_bytes, module.source_digest, module.module_name,
                        tuple(shapes), tuple(inputs), tuple(producers), tuple(outputs),
                        module.cap, module.objective, module.span, tuple(declarations),
                        tuple(constraints))
    return _NameView(view, tuple(names.originals), work)


def _original_name_diagnostic(error, original_names):
    """Translate only the complete known quoted-name forms, once.

    Substring replacement would corrupt ordinary words and cascade when a user
    name equals another alias. An unrecognized diagnostic is left unchanged.
    """
    for code, prefix in (('UNDEFINED_NAME', 'undefined shape'),
                         ('UNDEFINED_NAME', 'undefined index'),
                         ('UNDEFINED_NAME', 'undefined tensor'),
                         ('DUPLICATE_NAME', 'duplicate declaration')):
        if error.code == code:
            for alias, original in zip(_ALIASES, original_names):
                if error.message == f'{prefix} {alias!r}':
                    return DiagnosticError(code, error.span, f'{prefix} {original!r}')
    return error
