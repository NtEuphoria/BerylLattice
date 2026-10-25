"""Independent template proof of a loop plan against fresh scale-v1 source.

The plan is untrusted structured data. The checker re-admits the source from
its bytes and proves, in time linear in the template (never in the data):

  coverage     one stage, loops (H, W) over distinct variables, store index
               exactly v0*W + v1: every output cell is written exactly once
  equivalence  the stored expression equals the output template structurally;
               input reads equal load(base + row*cols + col) as canonical
               affine forms; producer reads match the producer template under
               the read's indices; sums match range and body under binding
  bounds       every load's affine minimum and maximum over its variable box
               lies within the input buffer
  arithmetic   interval analysis over the template from the input interval:
               every + and * fits its equation's declared type (i32 or i64),
               and every symbolic sum satisfies terms * max|term| <= that
               type's maximum, so any accumulation order is exact

Every cell evaluates the same template, every input shares one interval, and
indices are affine, so these facts hold for every cell at once.
"""
from dataclasses import dataclass

from .frontend import admit_source, parse_source
from .model import (BinaryExpression, DiagnosticError, GroupExpression, IntegerLiteral, Limits,
                    NameReference, ReadExpression, SCALE_PROFILE, SumExpression, VALUE_BOUNDS)
from .scale_plan import LOOP_PLAN_FORMAT, LoopPlan, Stage, loop_plan_digest

SCALE_CHECKER_VERSION = 'beryl-template-checker-v1'


@dataclass(frozen=True, slots=True)
class TemplateCheck:
    valid: bool
    reason: str
    detail: str | None
    plan_digest: str | None
    multiplication_nodes: int | None
    work_used: int
    checker_version: str = SCALE_CHECKER_VERSION

    # Reporting fields shared with finite CheckResult records.
    @property
    def workspace_bytes(self):
        return 0 if self.valid else None

    @property
    def multiplication_ops(self):
        return self.multiplication_nodes


class _Stop(Exception):
    def __init__(self, reason, detail=None):
        self.reason, self.detail = reason, detail


def _ungroup(node):
    while isinstance(node, GroupExpression):
        node = node.expression
    return node


def _affine_ok(value):
    """A canonical affine: (int, sorted unique (str, nonzero int) pairs)."""
    if type(value) is not tuple or len(value) != 2 or type(value[0]) is not int:
        return False
    terms = value[1]
    if type(terms) is not tuple:
        return False
    names = []
    for term in terms:
        if type(term) is not tuple or len(term) != 2 or type(term[0]) is not str \
                or type(term[1]) is not int or term[1] == 0:
            return False
        names.append(term[0])
    return names == sorted(set(names))


def _add(a, b):
    terms = dict(a[1])
    for var, k in b[1]:
        terms[var] = terms.get(var, 0) + k
    return (a[0] + b[0], tuple(sorted((v, k) for v, k in terms.items() if k)))


def _scale(a, factor):
    return (0, ()) if factor == 0 else (a[0] * factor, tuple((v, k * factor) for v, k in a[1]))


def check_loop_plan(source: bytes, plan: LoopPlan, limits: Limits = Limits()) -> TemplateCheck:
    """Prove `plan` against freshly admitted `source`; never trust a label."""
    work = 0
    muls = 0

    def charge():
        nonlocal work
        work += 1
        if work > limits.check_steps:
            raise _Stop('CHECK_STEPS_EXHAUSTED')

    digest = None
    try:
        if type(plan) is not LoopPlan or plan.format != LOOP_PLAN_FORMAT:
            raise _Stop('INVALID_PLAN', 'expected a beryl-loop-plan-v1 record')
        try:
            kernel = admit_source(parse_source(source, limits))
        except DiagnosticError as error:
            raise _Stop(error.code, error.message)
        if kernel.profile != SCALE_PROFILE:
            raise _Stop('UNSUPPORTED_PROFILE', 'template checking covers scale-v1 kernels')
        if plan.semantic_digest != kernel.semantic_digest:
            raise _Stop('SEMANTIC_DIGEST_MISMATCH')
        # One stage: direct (producer inlined). Two: carry, a producer stage then
        # an output stage reading it through ('prod', i, j). Labels are not trusted.
        if (type(plan.stages) is not tuple or len(plan.stages) not in (1, 2)
                or any(type(s) is not Stage for s in plan.stages)):
            raise _Stop('INVALID_PLAN', 'a plan has an output stage, optionally after a producer stage')
        carry = len(plan.stages) == 2
        stage = plan.stages[-1]
        module = kernel.source_module
        producer, output = module.producers[0], module.outputs[0]
        inputs, input_ranges, base = {}, {}, 0
        for declaration, (rows, cols) in zip(module.inputs, kernel.all_input_shapes, strict=True):
            inputs[declaration.name] = (base, cols)
            input_ranges[declaration.name] = tuple(declaration.input_interval)
            base += rows * cols
        input_count = base
        distinct = set(input_ranges.values())
        range_text = (f'for inputs in {min(distinct)[0]}..{min(distinct)[1]}' if len(distinct) == 1
                      else 'for the declared input ranges')

        # Coverage.
        loops = stage.loops
        if (type(loops) is not tuple or len(loops) != 2
                or any(type(l) is not tuple or len(l) != 2 or type(l[0]) is not str for l in loops)):
            raise _Stop('INVALID_PLAN', 'malformed loops')
        (v0, h), (v1, w) = loops
        if v0 == v1 or (h, w) != (kernel.height, kernel.width) or type(h) is not int or type(w) is not int:
            raise _Stop('COVERAGE_MISMATCH', 'loops must be (H, W) over distinct variables')
        expected_index = (0, tuple(sorted(((v0, kernel.width), (v1, 1)))))
        if not _affine_ok(stage.index) or stage.index != expected_index:
            raise _Stop('COVERAGE_MISMATCH', 'store index must be v0*W + v1')

        # Arithmetic: interval of each source node, position-independent.
        intervals = {}

        def interval(node, element_type):
            node = _ungroup(node)
            low, high = VALUE_BOUNDS[element_type]
            hint = ('; declare the equation i64 (`let t: i64[...]`) for 64-bit values'
                    if element_type == 'i32' else '')
            key = id(node)
            if key in intervals:
                return intervals[key]
            charge()
            if isinstance(node, IntegerLiteral):
                result = (node.value, node.value)
            elif isinstance(node, ReadExpression):
                result = (input_ranges[node.name] if node.name in inputs
                          else interval(producer.expression, producer.element_type))
                if result[0] < low or result[1] > high:
                    # An i64 producer read where an i32 value is required.
                    raise _Stop('ARITHMETIC_OVERFLOW',
                                f'the read of {node.name!r} at byte {node.span.offset} can reach '
                                f'{result[0]}..{result[1]}, outside {element_type} ({low}..{high}){hint}')
            elif isinstance(node, BinaryExpression):
                (a, b), (c, d) = interval(node.left, element_type), interval(node.right, element_type)
                if node.operator == '+':
                    result = (a + c, b + d)
                else:
                    ends = (a * c, a * d, b * c, b * d)
                    result = (min(ends), max(ends))
                if result[0] < low or result[1] > high:
                    raise _Stop('ARITHMETIC_OVERFLOW',
                                f"the '{node.operator}' at byte {node.span.offset} can reach "
                                f'{result[0]}..{result[1]}, outside {element_type} '
                                f'({low}..{high}) {range_text}{hint}')
            elif isinstance(node, SumExpression):
                a, b = interval(node.body, element_type)
                terms = node.upper - node.lower
                biggest = max(abs(a), abs(b))
                if terms * biggest > high:
                    raise _Stop('ARITHMETIC_OVERFLOW',
                                f'the sum at byte {node.span.offset} adds {terms} terms of up to {biggest} each, '
                                f'so it can reach {terms * biggest} > {high}; at most '
                                f'{high // max(biggest, 1)} terms fit in {element_type}{hint}')
                result = (terms * a, terms * b)
            else:
                raise _Stop('UNSUPPORTED_SOURCE_EXPRESSION')
            intervals[key] = result
            return result

        # Every producer node is bounded by the producer's type, every output
        # node by the output's; a producer read takes the producer's interval.
        interval(producer.expression, producer.element_type)
        interval(output.expression, output.element_type)

        # Equivalence and bounds, one walk; ranges holds each plan variable's box.
        ranges = {v0: (0, kernel.height - 1), v1: (0, kernel.width - 1)}
        prows, pcols = kernel.producer_shape
        if carry:
            produce = plan.stages[0]
            p_loops = produce.loops
            if (type(p_loops) is not tuple or len(p_loops) != 2
                    or any(type(l) is not tuple or len(l) != 2 or type(l[0]) is not str for l in p_loops)):
                raise _Stop('INVALID_PLAN', 'malformed producer loops')
            (u0, ph), (u1, pw) = p_loops
            if len({u0, u1, v0, v1}) != 4 or (ph, pw) != (prows, pcols):
                raise _Stop('COVERAGE_MISMATCH', 'producer loops must be the producer shape over fresh variables')
            if not _affine_ok(produce.index) or produce.index != (0, tuple(sorted(((u0, pcols), (u1, 1))))):
                raise _Stop('COVERAGE_MISMATCH', 'producer store index must be u0*PW + u1')

        def index_affine(node, env):
            node = _ungroup(node)
            if isinstance(node, IntegerLiteral):
                return (node.value, ())
            if isinstance(node, NameReference) and node.name in env:
                return env[node.name]
            if isinstance(node, BinaryExpression) and node.operator == '+':
                return _add(index_affine(node.left, env), index_affine(node.right, env))
            raise _Stop('UNSUPPORTED_SOURCE_INDEX')

        def same(p, s, env, depth):
            nonlocal muls
            charge()
            if depth > 512:
                raise _Stop('INVALID_PLAN', 'expression too deep')
            s = _ungroup(s)
            if type(p) is not tuple or not p:
                raise _Stop('INVALID_PLAN', 'malformed expression')
            if isinstance(s, IntegerLiteral):
                return p == ('const', s.value) and type(p[1]) is int
            if isinstance(s, BinaryExpression):
                if p[0] != ('add' if s.operator == '+' else 'mul') or len(p) != 3:
                    return False
                muls += p[0] == 'mul'
                return same(p[1], s.left, env, depth + 1) and same(p[2], s.right, env, depth + 1)
            if isinstance(s, SumExpression):
                if len(p) != 5 or p[0] != 'sum' or type(p[1]) is not str or p[1] in ranges:
                    return False
                if (p[2], p[3]) != (s.lower, s.upper) or type(p[2]) is not int or type(p[3]) is not int:
                    return False
                ranges[p[1]] = (s.lower, s.upper - 1)
                try:
                    return same(p[4], s.body, {**env, s.variable: (0, ((p[1], 1),))}, depth + 1)
                finally:
                    del ranges[p[1]]
            if isinstance(s, ReadExpression):
                row, col = (index_affine(i, env) for i in s.indices)
                if s.name in inputs:
                    base, cols = inputs[s.name]
                    wanted = _add((base, ()), _add(_scale(row, cols), col))
                    if len(p) != 2 or p[0] != 'load' or not _affine_ok(p[1]) or p[1] != wanted:
                        return False
                    low = high = p[1][0]
                    for var, k in p[1][1]:
                        a, b = ranges[var]
                        low += min(k * a, k * b)
                        high += max(k * a, k * b)
                    if low < 0 or high >= input_count:
                        raise _Stop('LOAD_OUT_OF_BOUNDS', f'load range {low}..{high}')
                    return True
                if s.name == producer.name and carry_reads and p[0] == 'prod':
                    # The producer cell at (v0 + i, v1 + j): exactly the source read's offsets.
                    if (len(p) != 3 or type(p[1]) is not int or type(p[2]) is not int
                            or row != (p[1], ((v0, 1),)) or col != (p[2], ((v1, 1),))
                            or not 0 <= p[1] <= 8 or not 0 <= p[2] <= 8):
                        return False
                    if kernel.height - 1 + p[1] >= prows or kernel.width - 1 + p[2] >= pcols:
                        raise _Stop('PRODUCER_OUT_OF_BOUNDS', f'window read ({p[1]}, {p[2]})')
                    return True
                if s.name == producer.name:
                    return same(p, producer.expression,
                                {producer.axes[0].name: row, producer.axes[1].name: col}, depth + 1)
            return False

        carry_reads = False
        if carry:
            ranges.update({u0: (0, prows - 1), u1: (0, pcols - 1)})
            if not same(produce.value, producer.expression,
                        {producer.axes[0].name: (0, ((u0, 1),)), producer.axes[1].name: (0, ((u1, 1),))}, 0):
                raise _Stop('STRUCTURAL_MISMATCH', 'producer stage differs from the producer template')
            carry_reads = True
        env = {output.axes[0].name: (0, ((v0, 1),)), output.axes[1].name: (0, ((v1, 1),))}
        if not same(stage.value, output.expression, env, 0):
            raise _Stop('STRUCTURAL_MISMATCH', 'stored expression differs from the source template')
        digest = loop_plan_digest(plan)
        return TemplateCheck(True, 'VALID', None, digest, muls, work)
    except _Stop as stop:
        return TemplateCheck(False, stop.reason, stop.detail, digest, None, work)
    except (TypeError, ValueError, KeyError, RecursionError) as error:
        return TemplateCheck(False, 'INVALID_PLAN', type(error).__name__, digest, None, work)
