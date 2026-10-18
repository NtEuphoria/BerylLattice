"""Independent, bounded symbolic checking of the actual finite operation stream.

Source expressions are interpreted from the retained AST. Expression edges use
integer arena indices: neither hashing nor equality traverses an expression DAG.
Only explicitly reserved scratch counts toward the workspace constraint.
"""
from dataclasses import dataclass
from hashlib import sha256

from .codec import DecodeError, canonical_json, validate_plan, validated_plan_digest
from .frontend import admit_source, parse_source
from .model import (AdmittedKernel, BinaryExpression, ConstraintStatus, DiagnosticError,
                    GroupExpression, IntegerLiteral, Limits, NameReference,
                    ReadExpression, SemanticStatus, SourceModule, SEMANTICS_VERSION)
from .plan_format import Plan

CHECKER_VERSION = 'axiom-checker-v1'
CHECK_ACCOUNTING_VERSION = 1
ACCOUNTING_VERSION = CHECK_ACCOUNTING_VERSION
_I32_MIN = -2147483648
_I32_MAX = 2147483647
Witness = tuple[tuple[str, int | str], ...]


@dataclass(frozen=True, slots=True)
class CheckResult:
    semantic_status: SemanticStatus
    constraint_status: ConstraintStatus
    check_complete: bool
    reason: str
    witness: Witness | None
    workspace_bytes: int | None
    multiplication_ops: int | None
    opcode_counts: tuple[tuple[str, int], ...] | None
    work_used: int
    source_digest: str
    plan_digest: str | None
    checker_version: str
    effective_cap: int | None
    constraint_digest: str

    @property
    def eligible(self) -> bool:
        return (self.check_complete and self.semantic_status == SemanticStatus.VALID
                and self.constraint_status == ConstraintStatus.SATISFIED)


class _Stop(Exception):
    def __init__(self, reason, witness=None):
        self.reason = reason
        self.witness = witness


class _Work:
    def __init__(self, limit):
        self.limit = limit
        self.used = 0

    def charge(self):
        if self.used >= self.limit:
            raise _Stop('CHECK_STEPS_EXHAUSTED')
        self.used += 1


class _Node:
    """Private arena node; identity equality, written once in __init__ only.

    A plain slots class: frozen dataclass construction (object.__setattr__
    per field) dominated checking. No code mutates a node after allocation.
    """
    __slots__ = ('kind', 'atom', 'left', 'right', 'lower', 'upper', 'samples')

    def __init__(self, kind, atom, left, right, lower, upper, samples):
        self.kind = kind
        self.atom = atom
        self.left = left
        self.right = right
        self.lower = lower
        self.upper = upper
        self.samples = samples


class _Expressions:
    def __init__(self, limit, input_interval):
        self.nodes = []
        self.limit = limit
        self.input_interval = input_interval
        self.inconclusive = False

    def allocate(self, node):
        if len(self.nodes) >= self.limit:
            raise _Stop('EXPRESSION_NODES_EXHAUSTED')
        self.nodes.append(node)
        return len(self.nodes) - 1

    def literal(self, value):
        return self.allocate(_Node('const', value, None, None, value, value, (value, value)))

    def input(self, index):
        lower, upper = self.input_interval
        return self.allocate(_Node('input', index, None, None, lower, upper, (lower, upper)))

    def binary(self, kind, left, right, origin):
        # All bounds and samples entering this method are i32. Even an
        # inconclusive interval cannot cause exponentially growing Python ints.
        a, b = self.nodes[left], self.nodes[right]
        (a0, a1), (b0, b1) = a.samples, b.samples  # samples at (lower, upper) uniform inputs
        if kind == 'add':
            lower, upper = a.lower + b.lower, a.upper + b.upper
            samples = (a0 + b0, a1 + b1)
        else:
            endpoints = (a.lower*b.lower, a.lower*b.upper,
                         a.upper*b.lower, a.upper*b.upper)
            lower, upper = min(endpoints), max(endpoints)
            samples = (a0 * b0, a1 * b1)
        if not (_I32_MIN <= samples[0] <= _I32_MAX and _I32_MIN <= samples[1] <= _I32_MAX):
            for input_value, result in zip(self.input_interval, samples):
                if not _I32_MIN <= result <= _I32_MAX:
                    raise _Stop('ARITHMETIC_OVERFLOW',
                                (('location', origin), ('uniform_input', input_value),
                                 ('result', str(result))))
        if lower < _I32_MIN or upper > _I32_MAX:
            self.inconclusive = True
            # Conditional bounds on executions that have not overflowed. The
            # global inconclusive flag prevents these bounds proving validity.
            lower, upper = max(lower, _I32_MIN), min(upper, _I32_MAX)
        return self.allocate(_Node(kind, None, left, right, lower, upper, samples))


def _source_expression(expression, environment, kernel, dag, work):
    """Interpret scalar and index ASTs with an explicit continuation stack.

    Read expansion visits the original producer AST anew each time, including
    each index expression and grouping node. There is no producer-token shortcut.
    Index computations are integers; scalar computations create expression nodes.
    """
    module = kernel.source_module
    producer = module.producers[0]
    input_name = module.inputs[0].name
    stack = [('visit', expression, environment, 'scalar')]
    values = []
    pop, push, charge = stack.pop, stack.append, work.charge
    while stack:
        frame = pop()
        action = frame[0]
        if action == 'visit':
            _, node, env, mode = frame
            charge()
            kind = type(node)
            # Exact-type fast paths for the two hottest node kinds; anything
            # else takes the original isinstance chain in its original order.
            if kind is ReadExpression:
                push(('read', node.name, len(node.indices), env))
                for index in reversed(node.indices):
                    push(('visit', index, env, 'index'))
            elif kind is BinaryExpression:
                push(('binary', node.operator, mode))
                push(('visit', node.right, env, mode))
                push(('visit', node.left, env, mode))
            elif isinstance(node, GroupExpression):
                stack.append(('visit', node.expression, env, mode))
            elif isinstance(node, IntegerLiteral):
                values.append(node.value if mode == 'index' else dag.literal(node.value))
            elif isinstance(node, NameReference):
                value = env[node.name]
                values.append(value if mode == 'index' else dag.literal(value))
            elif isinstance(node, BinaryExpression):
                stack.append(('binary', node.operator, mode))
                stack.append(('visit', node.right, env, mode))
                stack.append(('visit', node.left, env, mode))
            elif isinstance(node, ReadExpression):
                stack.append(('read', node.name, len(node.indices), env))
                for index in reversed(node.indices):
                    stack.append(('visit', index, env, 'index'))
            else:
                raise _Stop('UNSUPPORTED_SOURCE_EXPRESSION')
        elif action == 'binary':
            _, operator, mode = frame
            right, left = values.pop(), values.pop()
            if operator not in ('+', '*'):
                raise _Stop('UNSUPPORTED_SOURCE_OPERATOR')
            if mode == 'index':
                values.append(left + right if operator == '+' else left * right)
            else:
                values.append(dag.binary('add' if operator == '+' else 'mul',
                                         left, right, 'source'))
        else:
            _, name, arity, env = frame
            if arity != 2:
                raise _Stop('UNSUPPORTED_SOURCE_READ')
            column, row = values.pop(), values.pop()
            if not (0 <= row <= kernel.height and 0 <= column <= kernel.width):
                raise _Stop('INVALID_SOURCE_INDEX', (('row', row), ('column', column)))
            if name == input_name:
                values.append(dag.input(row * (kernel.width + 1) + column))
            elif name == producer.name:
                producer_env = dict(env)
                producer_env[producer.axes[0].name] = row
                producer_env[producer.axes[1].name] = column
                stack.append(('visit', producer.expression, producer_env, 'scalar'))
            else:
                raise _Stop('UNSUPPORTED_SOURCE_READ')
    return values[0]


def _equal(left, right, dag, work):
    """Charge every conceptual node pair, even repeated shared subexpressions."""
    pending = [(left, right)]
    while pending:
        left, right = pending.pop()
        work.charge()
        a, b = dag.nodes[left], dag.nodes[right]
        if a.kind != b.kind or a.atom != b.atom:
            return False
        if a.kind in ('add', 'mul'):
            pending.append((a.right, b.right))
            pending.append((a.left, b.left))
    return True


def _cap(value, name):
    if value is not None and (type(value) is not int or not 0 <= value <= _I32_MAX):
        raise ValueError(f'{name} must be None or a nonnegative exact i32 integer')


def check_plan(kernel: AdmittedKernel, plan: Plan, limits: Limits, *,
               additional_cap: int | None = None) -> CheckResult:
    """Check under the minimum source/additional arena cap; never trust a label.

    The work counter covers source AST construction visits, physical execution
    visits, and exact-comparison pairs. Structural decoding/validation and digest
    computation have separate byte/operation bounds and are outside that counter.
    Counters become available only after all physical operations are processed.
    """
    if type(kernel) is not AdmittedKernel or type(limits) is not Limits:
        raise ValueError('expected an AdmittedKernel and Limits')
    _cap(kernel.cap, 'source cap')
    _cap(additional_cap, 'additional cap')
    caps = [value for value in (kernel.cap, additional_cap) if value is not None]
    effective_cap = min(caps) if caps else None
    constraint_digest = sha256(canonical_json({
        'version': 1, 'property': 'plan_workspace_bytes', 'source_cap': kernel.cap,
        'additional_cap': additional_cap, 'effective_cap': effective_cap,
    })).hexdigest()
    work = _Work(limits.check_steps)
    workspace = None
    identity = None
    multiplication_ops = None
    opcode_counts = None
    constraint = ConstraintStatus.UNKNOWN

    def result(status, complete, reason, witness=None):
        return CheckResult(status, constraint, complete, reason, witness, workspace,
                           multiplication_ops, opcode_counts, work.used,
                           kernel.source_digest, identity, CHECKER_VERSION,
                           effective_cap, constraint_digest)

    try:
        validate_plan(plan, limits)
        identity = validated_plan_digest(plan, limits)
    except DecodeError as error:
        unknown = error.code.endswith('_LIMIT') or error.code.startswith('UNSUPPORTED_')
        return result(SemanticStatus.UNKNOWN if unknown else SemanticStatus.INVALID,
                      False, error.code,
                      None if unknown else (('field', error.field_path), ('detail', str(error))))
    workspace = 4 * plan.scratch_capacity_cells
    constraint = (ConstraintStatus.SATISFIED if effective_cap is None or workspace <= effective_cap
                  else ConstraintStatus.VIOLATED)
    if kernel.semantics_version != SEMANTICS_VERSION:
        return result(SemanticStatus.UNKNOWN, False, 'UNSUPPORTED_SEMANTICS_VERSION')
    if plan.semantic_digest != kernel.semantic_digest:
        return result(SemanticStatus.INVALID, False, 'SEMANTIC_DIGEST_MISMATCH',
                      (('expected', kernel.semantic_digest), ('actual', plan.semantic_digest)))
    if type(kernel.source_module) is not SourceModule:
        return result(SemanticStatus.INVALID, False, 'INVALID_SOURCE_RECORD',
                      (('field', 'source_module'),))
    try:
        # A frozen record is not an admission certificate. Rebuild from the
        # bytes so replaced metadata/ASTs cannot weaken the source contract.
        fresh = admit_source(parse_source(kernel.source_module.source_bytes, limits))
    except DiagnosticError as error:
        unknown = error.code.endswith('_LIMIT') or error.code.startswith('UNSUPPORTED_')
        return result(SemanticStatus.UNKNOWN if unknown else SemanticStatus.INVALID,
                      False, error.code,
                      None if unknown else (('offset', error.span.offset), ('detail', str(error))))
    caps = [value for value in (fresh.cap, additional_cap) if value is not None]
    effective_cap = min(caps) if caps else None
    constraint_digest = sha256(canonical_json({
        'version': 1, 'property': 'plan_workspace_bytes', 'source_cap': fresh.cap,
        'additional_cap': additional_cap, 'effective_cap': effective_cap,
    })).hexdigest()
    constraint = (ConstraintStatus.SATISFIED if effective_cap is None or workspace <= effective_cap
                  else ConstraintStatus.VIOLATED)
    for field in ('height', 'width', 'cap', 'input_interval', 'objective',
                  'source_digest', 'semantic_digest', 'semantics_version'):
        supplied, actual = getattr(kernel, field), getattr(fresh, field)
        if type(supplied) is not type(actual) or supplied != actual:
            return result(SemanticStatus.INVALID, False, 'SOURCE_IDENTITY_MISMATCH',
                          (('field', field),))
    if (any(type(value) is not int for value in kernel.input_interval)
            or kernel.source_module.source_digest != fresh.source_digest):
        return result(SemanticStatus.INVALID, False, 'SOURCE_IDENTITY_MISMATCH',
                      (('field', 'source_module'),))
    kernel = fresh  # Only the freshly parsed AST supplies symbolic semantics.
    dag = _Expressions(limits.expression_nodes, kernel.input_interval)
    try:
        output = kernel.source_module.outputs[0]
        expected = []
        shapes = {'H': kernel.height, 'W': kernel.width}
        for row in range(kernel.height):
            for column in range(kernel.width):
                env = dict(shapes)
                env[output.axes[0].name] = row
                env[output.axes[1].name] = column
                expected.append(_source_expression(output.expression, env, kernel, dag, work))
        registers = []
        scratch = {}  # Capacity is a bound, never an allocation request.
        outputs = {}
        counts = {}
        for position, operation in enumerate(plan.operations):
            work.charge()
            opcode = operation.opcode
            counts[opcode] = counts.get(opcode, 0) + 1
            if opcode == 'const':
                registers.append(dag.literal(operation.value))
            elif opcode == 'input_load':
                if operation.index >= (kernel.height + 1) * (kernel.width + 1):
                    raise _Stop('INPUT_INDEX_OUT_OF_BOUNDS',
                                (('operation', position), ('index', operation.index)))
                registers.append(dag.input(operation.index))
            elif opcode in ('add', 'mul'):
                a, b = operation.operands
                registers.append(dag.binary(opcode, registers[a], registers[b], position))
            elif opcode == 'scratch_store':
                scratch[operation.index] = registers[operation.operands[0]]
            elif opcode == 'scratch_load':
                if operation.index not in scratch:
                    raise _Stop('UNINITIALIZED_SCRATCH',
                                (('operation', position), ('index', operation.index)))
                registers.append(scratch[operation.index])
            else:  # The structural validator admits only output_store here.
                if operation.index >= len(expected):
                    raise _Stop('OUTPUT_INDEX_OUT_OF_BOUNDS',
                                (('operation', position), ('index', operation.index)))
                if operation.index in outputs:
                    raise _Stop('DUPLICATE_OUTPUT',
                                (('operation', position), ('index', operation.index)))
                outputs[operation.index] = registers[operation.operands[0]]
        opcode_counts = tuple(sorted(counts.items()))
        multiplication_ops = counts.get('mul', 0)
        if len(outputs) != len(expected):
            missing = next(index for index in range(len(expected)) if index not in outputs)
            raise _Stop('MISSING_OUTPUT', (('index', missing),))
        mismatched = False
        for index, source_node in enumerate(expected):
            plan_node = outputs[index]
            if not _equal(source_node, plan_node, dag, work):
                a, b = dag.nodes[source_node], dag.nodes[plan_node]
                for input_value, wanted, actual in zip(kernel.input_interval, a.samples, b.samples):
                    if wanted != actual:
                        raise _Stop('OUTPUT_VALUE_MISMATCH',
                                    (('index', index), ('uniform_input', input_value),
                                     ('expected', wanted), ('actual', actual)))
                mismatched = True
        if dag.inconclusive:
            return result(SemanticStatus.UNKNOWN, True, 'INCONCLUSIVE_INTERVAL')
        if mismatched:
            return result(SemanticStatus.UNKNOWN, True, 'STRUCTURAL_MISMATCH')
        return result(SemanticStatus.VALID, True, 'VALID')
    except _Stop as stop:
        return result(SemanticStatus.INVALID if stop.witness is not None else SemanticStatus.UNKNOWN,
                      False, stop.reason, stop.witness)
