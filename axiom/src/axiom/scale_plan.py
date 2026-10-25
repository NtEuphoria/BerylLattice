"""Loop plans (beryl-loop-plan-v1) for scale-v1 kernels, and their generator.

A loop plan is a structured program: stages of loop nests whose stored values
are expression trees over affine input loads and symbolic sums. Its size is
the size of the source template, not of the data. The generator is untrusted;
scale_checker proves a plan against the source before anything emits it.

    LoopPlan(semantic_digest, plan_id, stages)
    Stage(loops=((var, extent), ...), index=Affine, value=Expr)
    Expr   = ('const', v) | ('load', Affine) | ('add', a, b) | ('mul', a, b)
           | ('min', a, b) | ('max', a, b)
           | ('shr', a, ('const', k)) | ('shr_round', a, ('const', k))
           | ('sum', var, lower, upper, body)
           | ('prod', i, j)   carry-v1 output only: the producer at (r+i, c+j)
    Affine = (constant, ((var, coefficient), ...))  canonical: sorted vars,
             no zero coefficients
"""
from dataclasses import dataclass
from hashlib import sha256
import json

from .codec import DecodeError
from .model import (AdmittedKernel, BinaryExpression, GroupExpression, IntegerLiteral,
                    NameReference, ReadExpression, SCALE_PROFILE, SumExpression)

LOOP_PLAN_FORMAT = 'beryl-loop-plan-v1'
# direct-v1: one output stage, producer inlined at every read.
# carry-v1:  a producer stage plus an output stage reading it through
#            ('prod', i, j); the emitter keeps the last K producer rows
#            (K = 1 + largest i), so each producer cell is computed once.
#            This generalizes the performance report's carry1 (K = 2).
SCALE_PLAN_IDS = ('direct-v1', 'carry-v1')
# Plan node kind of each source binary operator.
PLAN_KINDS = {'+': 'add', '*': 'mul', 'min': 'min', 'max': 'max', 'shr': 'shr', 'shr_round': 'shr_round'}
BINARY_KINDS = tuple(PLAN_KINDS.values())


@dataclass(frozen=True, slots=True)
class Stage:
    loops: tuple
    index: tuple
    value: tuple


@dataclass(frozen=True, slots=True)
class LoopPlan:
    semantic_digest: str
    plan_id: str
    stages: tuple
    format: str = LOOP_PLAN_FORMAT


def affine(constant=0, **terms):
    return (constant, tuple(sorted((v, k) for v, k in terms.items() if k)))


def affine_add(a, b):
    terms = dict(a[1])
    for var, coefficient in b[1]:
        terms[var] = terms.get(var, 0) + coefficient
    return (a[0] + b[0], tuple(sorted((v, k) for v, k in terms.items() if k)))


def affine_scale(a, factor):
    if factor == 0:
        return (0, ())
    return (a[0] * factor, tuple((v, k * factor) for v, k in a[1]))


def _plain(json_value):
    """JSON-ready nested lists for an expression, affine or stage."""
    if isinstance(json_value, tuple):
        return [_plain(item) for item in json_value]
    return json_value


def plan_json(plan):
    return json.dumps({'format': plan.format, 'semantic_digest': plan.semantic_digest,
                       'plan_id': plan.plan_id,
                       'stages': [{'loops': _plain(s.loops), 'index': _plain(s.index),
                                   'value': _plain(s.value)} for s in plan.stages]},
                      sort_keys=True, separators=(',', ':')).encode('ascii')


def loop_plan_digest(plan):
    return sha256(plan_json(plan)).hexdigest()


def _ungroup(node):
    while isinstance(node, GroupExpression):
        node = node.expression
    return node


def make_scale_plan(kernel: AdmittedKernel, plan_id: str = 'direct-v1', *,
                    max_nodes: int = 20000) -> LoopPlan:
    """direct-v1 or carry-v1 for an admitted scale-v1 kernel (see SCALE_PLAN_IDS)."""
    if type(kernel) is not AdmittedKernel or kernel.profile != SCALE_PROFILE:
        raise TypeError('expected an admitted scale-v1 kernel')
    if plan_id not in SCALE_PLAN_IDS:
        raise ValueError('unsupported plan generator ID')
    module = kernel.source_module
    producer, output = module.producers[0], module.outputs[0]
    bases, offset = {}, 0
    for declaration, (rows, cols) in zip(module.inputs, kernel.all_input_shapes):
        bases[declaration.name] = (offset, cols)
        offset += rows * cols
    nodes = 0
    fresh = iter(f's{i}' for i in range(1 << 30))

    def count():
        nonlocal nodes
        nodes += 1
        if nodes > max_nodes:
            raise DecodeError('OPERATION_LIMIT', '$.stages', 'loop plan node quota exceeded')

    def index(node, env):
        node = _ungroup(node)
        if isinstance(node, IntegerLiteral):
            return affine(node.value)
        if isinstance(node, NameReference):
            return env[node.name]
        if isinstance(node, BinaryExpression) and node.operator == '+':
            return affine_add(index(node.left, env), index(node.right, env))
        raise ValueError('index outside scale-v1')

    def lower(node, env):
        count()
        node = _ungroup(node)
        if isinstance(node, IntegerLiteral):
            return ('const', node.value)
        if isinstance(node, BinaryExpression):
            return (PLAN_KINDS[node.operator], lower(node.left, env), lower(node.right, env))
        if isinstance(node, SumExpression):
            var = next(fresh)
            return ('sum', var, node.lower, node.upper,
                    lower(node.body, {**env, node.variable: affine(**{var: 1})}))
        if isinstance(node, ReadExpression):
            row, col = (index(i, env) for i in node.indices)
            if node.name in bases:
                base, cols = bases[node.name]
                return ('load', affine_add(affine(base), affine_add(affine_scale(row, cols), col)))
            if node.name == producer.name:
                return lower(producer.expression,
                             {producer.axes[0].name: row, producer.axes[1].name: col})
        raise ValueError('expression outside scale-v1')

    env = {output.axes[0].name: affine(r=1), output.axes[1].name: affine(c=1)}
    if plan_id == 'direct-v1':
        stage = Stage((('r', kernel.height), ('c', kernel.width)),
                      affine(r=kernel.width, c=1), lower(output.expression, env))
        return LoopPlan(kernel.semantic_digest, plan_id, (stage,))
    prows, pcols = kernel.producer_shape
    produce = Stage((('p', prows), ('q', pcols)), affine(p=pcols, q=1),
                    lower(producer.expression, {producer.axes[0].name: affine(p=1),
                                                producer.axes[1].name: affine(q=1)}))

    def windowed(node):
        """The output tree with producer reads as ('prod', i, j)."""
        count()
        node = _ungroup(node)
        if isinstance(node, IntegerLiteral):
            return ('const', node.value)
        if isinstance(node, BinaryExpression):
            return (PLAN_KINDS[node.operator], windowed(node.left), windowed(node.right))
        if isinstance(node, ReadExpression) and node.name == producer.name:
            row, col = (index(i, env) for i in node.indices)
            if row[1] != (('r', 1),) or col[1] != (('c', 1),):
                raise ValueError('carry-v1 needs window reads of the producer')
            return ('prod', row[0], col[0])
        raise ValueError('carry-v1 output may read only the producer')
    stage = Stage((('r', kernel.height), ('c', kernel.width)),
                  affine(r=kernel.width, c=1), windowed(output.expression))
    return LoopPlan(kernel.semantic_digest, plan_id, (produce, stage))
