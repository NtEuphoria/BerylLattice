"""Independent bounded expansion; matching grants no semantic eligibility.

The internal caller must separately own a successful complete finite check.
These functions accept a freshly owned admitted kernel, not public proof records.
Only exact bytes are decoded; labels/origins are bounded metadata, never authority.
"""
from dataclasses import dataclass
import hashlib

from .bounded_loop_model import (CORRESPONDENCE_VERSION, I32_MIN, I32_MAX,
                                 HintError, HintLimits, Loop, LoopProgram)
from .bounded_loop_codec import decode_loop_program, validate_loop_program
from .codec import encode_plan, validate_plan
from .model import AdmittedKernel, Limits
from .plan_format import Operation, Plan


@dataclass(frozen=True, slots=True)
class LoopCorrespondence:
    plan: Plan
    program: LoopProgram
    expanded_plan: Plan | None
    hint_bytes: bytes
    hint_digest: str
    plan_digest: str
    source_digest: str
    semantic_digest: str
    expanded_operations: int
    work_steps: int
    version: str = CORRESPONDENCE_VERSION


def _specialization(kernel, program):
    if type(kernel) is not AdmittedKernel:
        raise HintError('HINT_SPECIALIZATION', 'expected freshly owned admitted kernel')
    if (program.source_digest, program.semantic_digest, program.height, program.width) != (
            kernel.source_digest, kernel.semantic_digest, kernel.height, kernel.width):
        raise HintError('HINT_SPECIALIZATION', 'source or shape binding differs')


def _i32(value):
    if not I32_MIN <= value <= I32_MAX:
        raise HintError('HINT_INDEX_OVERFLOW', 'index intermediate exceeds i32')
    return value


def evaluate_index(expr, variables, charge):
    """Evaluate the validated IndexExpr order documented in bounded_loop_model.

    ``charge`` is called for the constant and four steps per term (variable
    offset, optional parity, multiply, add). The parity step is charged even
    when absent so static traversal accounting is exact for either form.
    """
    charge(1)
    value = _i32(expr.constant)
    for term in expr.terms:
        charge(1)
        component = _i32(variables[term.variable] + term.offset)
        charge(1)
        if term.modulo2:
            component = _i32(component % 2)
        charge(1)
        component = _i32(term.coefficient * component)
        charge(1)
        value = _i32(value + component)
    if value < 0:
        raise HintError('HINT_INDEX_BOUNDS', 'negative final index')
    return value


def _cost(body, work_limit, operation_limit):
    """Saturating precheck includes empty iterations and zero-trip controls."""
    work = operations = 0
    for node in body:
        if type(node) is Loop:
            child_work, child_ops = _cost(node.body, work_limit, operation_limit)
            trips = node.stop-node.start
            node_work = min(work_limit+1, 1+trips*(2+child_work))
            node_ops = min(operation_limit+1, trips*child_ops)
        else:
            node_work = 1+len(node.operands)+(2 if node.dst is not None else 0)
            if node.index is not None:
                node_work += 1+4*len(node.index.terms)
            node_ops = 1
        work = min(work_limit+1, work+node_work)
        operations = min(operation_limit+1, operations+node_ops)
    return work, operations


def _expand_operations(kernel, program, limits, hint_limits):
    if type(limits) is not Limits:
        raise HintError('INVALID_HINT', 'expected explicit finite Limits')
    validate_loop_program(program, hint_limits)
    _specialization(kernel, program)
    predicted_work, predicted_ops = _cost(program.body, hint_limits.work_steps, limits.plan_operations)
    if predicted_work > hint_limits.work_steps:
        raise HintError('HINT_WORK_LIMIT', 'saturating traversal precheck exceeded')
    if predicted_ops > limits.plan_operations:
        raise HintError('HINT_OPERATION_LIMIT', 'expanded operation quota exceeded')
    used = 0
    def charge(amount=1):
        nonlocal used
        used += amount
        if used > hint_limits.work_steps:
            raise HintError('HINT_WORK_LIMIT', 'charged traversal quota exceeded')
    operations = []
    scalars, variables = {}, {}
    next_dst = 0
    def block(body):
        nonlocal next_dst
        definitions = []
        for node in body:
            charge()
            if type(node) is Loop:
                for value in range(node.start, node.stop):
                    charge()
                    variables[node.variable] = value
                    block(node.body)
                    charge()
                    del variables[node.variable]
                continue
            if len(operations) >= limits.plan_operations:
                raise HintError('HINT_OPERATION_LIMIT', 'expanded operation quota exceeded')
            operands = []
            for operand in node.operands:
                charge()
                operands.append(scalars[operand])
            index = None
            if node.index is not None:
                index = evaluate_index(node.index, variables, charge)
                bound = (program.scratch_capacity_cells if node.opcode.startswith('scratch_')
                         else kernel.height*kernel.width if node.opcode == 'output_store'
                         else (kernel.height+1)*(kernel.width+1))
                if index >= bound:
                    raise HintError('HINT_INDEX_BOUNDS', 'index outside specialized arena')
            dst = None
            if node.dst is not None:
                charge()
                dst = next_dst
                next_dst += 1
                scalars[node.dst] = dst
                definitions.append(node.dst)
            operations.append(Operation(node.opcode, dst, tuple(operands), index, node.value, node.origins))
        for name in definitions:
            charge()
            del scalars[name]
    block(program.body)
    if used != predicted_work or len(operations) != predicted_ops:
        raise HintError('HINT_ACCOUNTING', 'internal traversal accounting disagreement')
    return tuple(operations), used


def _expand(kernel, program, limits, hint_limits):
    operations, used = _expand_operations(kernel, program, limits, hint_limits)
    expanded = Plan(1, program.semantic_digest, program.label,
                    program.scratch_capacity_cells, operations)
    validate_plan(expanded, limits)
    return expanded, used


def expand_loop_program(kernel, program, limits, hint_limits=HintLimits()):
    """Expand an untrusted immutable hint under separate hint and finite limits."""
    return _expand(kernel, program, limits, hint_limits)[0]


def validate_loop_correspondence(kernel, plan, loop_bytes, limits, hint_limits=HintLimits()):
    """Bind the complete actual stream; a successful match is not a proof."""
    validate_plan(plan, limits)
    program = decode_loop_program(loop_bytes, hint_limits)
    expanded, work = _expand(kernel, program, limits, hint_limits)
    _match_operations(kernel, plan, program, expanded.operations)
    return LoopCorrespondence(plan, program, expanded, loop_bytes,
                              hashlib.sha256(loop_bytes).hexdigest(),
                              hashlib.sha256(encode_plan(plan, limits=limits)).hexdigest(),
                              kernel.source_digest, kernel.semantic_digest,
                              len(expanded.operations), work)


def _match_operations(kernel, plan, program, operations):
    """Compare all executable fields, including dead and trailing operations."""
    if plan.semantic_digest != kernel.semantic_digest:
        raise HintError('HINT_SPECIALIZATION', 'finite plan source binding differs')
    if (plan.scratch_capacity_cells != program.scratch_capacity_cells or
            len(plan.operations) != len(operations)):
        raise HintError('HINT_MISMATCH', 'reservation or complete operation count differs')
    for actual, expected in zip(plan.operations, operations):
        if (actual.opcode, actual.dst, actual.operands, actual.index, actual.value) != (
                expected.opcode, expected.dst, expected.operands, expected.index, expected.value):
            raise HintError('HINT_MISMATCH', 'complete executable operation stream differs')


def _validate_owned_loop_correspondence(owned, loop_bytes, hint_limits=HintLimits()):
    """Freshly match a hint to the exact live, owned, successfully checked plan.

    The owning transaction already validated and encoded this immutable finite
    plan. Reuse its retained identity; do not validate/encode it a second time or
    construct an artificial expanded Plan whose label/origins are not emitted.
    All hint decoding, lexical validation, work/index checks and complete stream
    comparisons are shared with the public path. No caller-created result grants
    backend authority. ``expanded_plan`` is None on this private path.
    """
    from .compilation import _require_owned
    _require_owned(owned)
    program = decode_loop_program(loop_bytes, hint_limits)
    operations, work = _expand_operations(owned.kernel, program, owned.limits, hint_limits)
    _match_operations(owned.kernel, owned.plan, program, operations)
    return LoopCorrespondence(owned.plan, program, None, loop_bytes,
                              hashlib.sha256(loop_bytes).hexdigest(),
                              owned.checked.plan_digest, owned.kernel.source_digest,
                              owned.kernel.semantic_digest, len(operations), work)
