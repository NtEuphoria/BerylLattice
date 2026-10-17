"""Bounded C1 research experiments, NOT a plan/certificate admission API.

The construction is a hand derivation using checked arithmetic/region operations.
It does not consume physical IR, and cannot establish production eligibility.
The independent review gate is deliberately outside this executable probe.
"""
from dataclasses import dataclass, asdict
import hashlib
import json

from axiom.model import (BinaryExpression, GroupExpression, IntegerLiteral,
                         NameReference, ReadExpression)
from axiom.source_profiles import SourceLimitsV2, SourceProfileV2, admit_source_v2


class ProbeError(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise ProbeError(reason)


class Budget:
    """research-bitwork-v1: structural visits plus bounded integer bit work."""
    def __init__(self, limit=1000000):
        self.limit, self.structural, self.bits = limit, 0, 0
        self.events = []

    def charge(self, kind, bits=0):
        require(self.structural + self.bits + 1 + bits <= self.limit, 'work quota')
        self.structural += 1
        self.bits += bits
        self.events.append(kind)

    def integer(self, value):
        require(type(value) is int and abs(value).bit_length() <= 256, 'integer width')
        return value

    def add(self, a, b):
        self.integer(a); self.integer(b)
        self.charge('integer-add', max(1, abs(a).bit_length(), abs(b).bit_length()))
        return self.integer(a+b)

    def mul(self, a, b):
        self.integer(a); self.integer(b)
        self.charge('integer-mul', max(1, abs(a).bit_length()) * max(1, abs(b).bit_length()))
        return self.integer(a*b)

    def le(self, a, b):
        self.integer(a); self.integer(b)
        self.charge('integer-compare', max(1, abs(a).bit_length(), abs(b).bit_length()))
        return a <= b


@dataclass(frozen=True)
class Affine:
    constant: int = 0
    terms: tuple = ()

    @staticmethod
    def var(name):
        return Affine(0, ((name, 1),))

    @staticmethod
    def of(value):
        return value if isinstance(value, Affine) else Affine(value)

    def __add__(self, other):
        other = Affine.of(other)
        d = dict(self.terms)
        for name, coefficient in other.terms:
            d[name] = d.get(name, 0) + coefficient
        require(len(d) <= 16, 'affine terms')
        return Affine(self.constant+other.constant, tuple(sorted((k, v) for k, v in d.items() if v)))

    __radd__ = __add__

    def __mul__(self, value):
        require(type(value) is int, 'affine literal coefficient')
        return Affine(self.constant*value, tuple((k, v*value) for k, v in self.terms if v*value))

    __rmul__ = __mul__

    def __sub__(self, other):
        return self + Affine.of(other)*-1

    def bounds(self, domain, budget):
        budget.charge('affine-normalization')
        low = high = budget.integer(self.constant)
        for name, coefficient in self.terms:
            require(name in domain, 'unbound affine variable')
            a, b = domain[name]
            require(budget.le(a, b), 'empty affine domain')
            x, y = (a, b) if coefficient >= 0 else (b, a)
            low = budget.add(low, budget.mul(coefficient, x))
            high = budget.add(high, budget.mul(coefficient, y))
        return low, high


def le(a, b, domain, budget):
    return budget.le((Affine.of(a)-b).bounds(domain, budget)[1], 0)


@dataclass(frozen=True)
class Rectangle:
    lo0: Affine
    hi0: Affine
    lo1: Affine
    hi1: Affine

    @staticmethod
    def of(*values):
        return Rectangle(*(Affine.of(x) for x in values))

    def well_formed(self, domain, budget):
        require(le(self.lo0, self.hi0, domain, budget) and
                le(self.lo1, self.hi1, domain, budget), 'reversed rectangle')

    def disjoint(self, other, domain, budget):
        budget.charge('disjoint-frame')
        return any(le(a, b, domain, budget) for a, b in (
            (self.hi0, other.lo0), (other.hi0, self.lo0),
            (self.hi1, other.lo1), (other.hi1, self.lo1)))

    def join(self, other, domain, budget):
        budget.charge('rectangle-join')
        self.well_formed(domain, budget); other.well_formed(domain, budget)
        if self.lo0 == other.lo0 and self.hi0 == other.hi0 and self.hi1 == other.lo1:
            return Rectangle(self.lo0, self.hi0, self.lo1, other.hi1)
        if self.lo1 == other.lo1 and self.hi1 == other.hi1 and self.hi0 == other.lo0:
            return Rectangle(self.lo0, other.hi0, self.lo1, self.hi1)
        raise ProbeError('gap, overlap, or incompatible rectangle join')


class Ledger:
    """Immutable transitions preserve exact write history. No forget operation."""
    def __init__(self, pieces, domain, budget=None):
        self.pieces, self.domain = tuple(pieces), domain
        self.budget = budget or Budget()

    def write(self, rectangle):
        self.budget.charge('output-store')
        rectangle.well_formed(self.domain, self.budget)
        require(all(rectangle.disjoint(p, self.domain, self.budget) for p in self.pieces),
                'duplicate output write')
        return Ledger(self.pieces+(rectangle,), self.domain, self.budget)

    def join_last(self):
        require(len(self.pieces) >= 2, 'missing pieces')
        joined = self.pieces[-2].join(self.pieces[-1], self.domain, self.budget)
        return Ledger(self.pieces[:-2]+(joined,), self.domain, self.budget)

    def require_exact(self, pieces):
        self.budget.charge('ledger-equality')
        require(self.pieces == tuple(pieces), 'output history was lost or changed')


def check_prefix(extent, mutation=None, budget=None):
    """One arbitrary iteration; extent never controls an executable loop."""
    b = budget or Budget()
    require(type(extent) is int and 0 <= extent <= 8193, 'loop bounds')
    empty = Rectangle.of(0, 1, 0, 0)
    base = Ledger((empty,), {}, b)
    base.require_exact(() if mutation == 'missing-base' else (empty,))
    if extent == 0:
        return base
    k = Affine.var('prefix-k')
    domain = {'prefix-k': (0, extent-1)}
    prefix = Rectangle.of(0, 1, 0, k)
    start = k + (1 if mutation == 'gap' else -1 if mutation == 'overlap' else 0)
    singleton = Rectangle.of(0, 1, start, k+1)
    result = Ledger((prefix,), domain, b).write(singleton).join_last()
    expected = Rectangle.of(0, 1, 0, k if mutation == 'wrong-step' else k+1)
    result.require_exact(() if mutation == 'reset' else (expected,))
    # The substitution k:=extent is the exit instantiation of this induction.
    return Ledger((Rectangle.of(0, 1, 0, extent),), {}, b)


def check_parity(cases, budget=None):
    """For arbitrary q: r=2q+p; derive next remainder by integer identities."""
    b = budget or Budget()
    require(tuple(cases) == (0, 1), 'parity cases must be complete and unique')
    pairs = []
    q = Affine.var('quotient')
    for p in cases:  # exactly two cases, never rows
        b.charge('parity-case')
        carry, next_slot = (p+1)//2, (p+1)%2
        require(2*q+p+1 == 2*(q+carry)+next_slot, 'Euclidean decomposition')
        require(p != next_slot and next_slot in (0, 1), 'parity alias')
        pairs.append((p, next_slot))
    return tuple(pairs)


def check_scratch(width, mutation=None, budget=None):
    b = budget or Budget()
    require(1 <= width <= 8192, 'width')
    for current, nxt in check_parity((0, 1), b):
        if mutation == 'alias':
            nxt = current
        current_row = Rectangle.of(current, current+1, 0, width+1)
        target_row = Rectangle.of(nxt, nxt+1, 0, width+1)
        require(current_row.disjoint(target_row, {}, b), 'refill destroys current row')
        j = Affine.var('stage-column')
        domain = {'stage-column': (0, width)}
        prefix = Rectangle.of(nxt, nxt+1, 0, j)
        cell = Rectangle.of(nxt, nxt+1, j, j+1)
        require(current_row.disjoint(cell, domain, b), 'current frame')
        require(prefix.disjoint(cell, domain, b), 'prefix frame')
        require(prefix.join(cell, domain, b) == Rectangle.of(nxt, nxt+1, 0, j+1), 'stage extension')
        # Store invalidates a previous full target-row fact, including its value.
        old_facts = [(current_row, 'current'), (target_row, 'old-target')]
        preserved = [(r, value) for r, value in old_facts if r.disjoint(cell, domain, b)]
        require((target_row, 'old-target') not in preserved, 'stale fact')
        if mutation == 'stale':
            require((target_row, 'old-target') in preserved, 'stale target value requested')
        facts = [] if mutation == 'uninitialized' else [('next', width if mutation == 'short-row' else width+1)]
        required_value = 'wrong' if mutation == 'wrong-value' else 'next'
        require(any(value == required_value and end > width for value, end in facts),
                'scratch read lacks initialized exact value through last column')
        b.charge('scratch-read-membership')
    check_prefix(width+1, budget=b)


class TermDAG:
    """Nodes refer only to earlier node IDs; hashing never expands a tree."""
    def __init__(self, budget=None, max_nodes=65536, max_depth=256):
        self.nodes, self.depths, self.intervals, self.intern = [], [], [], {}
        self.budget = budget or Budget()
        self.max_nodes, self.max_depth = max_nodes, max_depth

    def node(self, op, payload, children, check_i32=True):
        self.budget.charge('scalar-node')
        require(op in ('input', 'const', 'add', 'mul'), 'scalar operation')
        require(len(children) == (2 if op in ('add', 'mul') else 0), 'scalar arity')
        require(all(type(i) is int and 0 <= i < len(self.nodes) for i in children), 'forward/cyclic node')
        depth = 1 + max((self.depths[i] for i in children), default=0)
        require(depth <= self.max_depth, 'symbolic depth')
        if op == 'input':
            interval = (0, 1023)
        elif op == 'const':
            require(len(payload) == 1, 'constant arity')
            interval = (payload[0], payload[0])
        else:
            x, y = (self.intervals[i] for i in children)
            fn = self.budget.add if op == 'add' else self.budget.mul
            values = [fn(a, b) for a in x for b in y]
            interval = min(values), max(values)
        if check_i32:
            require(self.budget.le(-2**31, interval[0]) and self.budget.le(interval[1], 2**31-1),
                    'checked i32 overflow, including dead work')
        key = op, tuple(payload), tuple(children)
        if key in self.intern:
            return self.intern[key]
        require(len(self.nodes) < self.max_nodes, 'symbolic nodes')
        index = len(self.nodes)
        self.intern[key] = index
        self.nodes.append(key); self.depths.append(depth); self.intervals.append(interval)
        return index


def source_bytes(h, w):
    return (f'module proof; shape H = {h}; shape W = {w};\n'
            'input image: i32[H+1,W+1] in 0..=1023;\n'
            'let p[r in 0..H+1,c in 0..W+1] = (image[r,c]+1)*(image[r,c]+1);\n'
            'output result[r in 0..H,c in 0..W] = ((p[r,c]+p[r,c+1])+p[r+1,c])+p[r+1,c+1];\n'
            'prefer multiplication_ops;\n').encode()


def source_term(kernel, dag, row, column):
    """Reconstruct from retained AST, expanding producers with lexical scopes."""
    module = kernel.source_module
    producer, output = module.producers[0], module.outputs[0]

    def index(expr, env):
        dag.budget.charge('source-index')
        if isinstance(expr, NameReference):
            return env[expr.name]
        if isinstance(expr, IntegerLiteral):
            return Affine(expr.value)
        if isinstance(expr, BinaryExpression) and expr.operator == '+':
            return index(expr.left, env)+index(expr.right, env)
        raise ProbeError('unsupported source index')

    def expand(expr, env):
        dag.budget.charge('source-visit')
        if isinstance(expr, GroupExpression):
            return expand(expr.expression, env)
        if isinstance(expr, IntegerLiteral):
            return dag.node('const', (expr.value,), ())
        if isinstance(expr, BinaryExpression):
            return dag.node({'+': 'add', '*': 'mul'}[expr.operator], (),
                            (expand(expr.left, env), expand(expr.right, env)))
        if isinstance(expr, ReadExpression):
            coordinates = tuple(index(i, env) for i in expr.indices)
            if expr.name == module.inputs[0].name:
                return dag.node('input', coordinates, ())
            require(expr.name == producer.name, 'source tensor role')
            return expand(producer.expression, dict(zip((a.name for a in producer.axes), coordinates)))
        raise ProbeError('unsupported source scalar')

    return expand(output.expression, dict(zip((a.name for a in output.axes), (row, column))))


@dataclass(frozen=True)
class OutlineReceipt:
    schedule: str
    shape: tuple
    obligations: tuple
    graph_shape: str
    primitive_events: int
    trace_bytes: int
    outline_scratch_fact_bound: int
    outline_region_piece_bound: int
    parity_cases: int
    term_nodes: int
    term_depth: int
    structural_visits: int
    integer_bit_work: int
    total_work: int
    source_digest: str
    specialization_digest: str
    complete: bool


def probe_outline(schedule, height, width, *, axis_names=('row', 'column'),
                  reverse_definitions=False, column_major=False, mutation=None):
    require(schedule in ('inline', 'materialize', 'rows2'), 'unsupported outline')
    require(not (schedule == 'rows2' and column_major), 'unsupported rows2 traversal')
    require(len(set(axis_names)) == 2, 'colliding lexical binders')
    kernel = admit_source_v2(source_bytes(height, width), profile=SourceProfileV2(), limits=SourceLimitsV2())
    b, dag = Budget(), None
    dag = TermDAG(b)
    row, col = map(Affine.var, axis_names)
    domain = {axis_names[0]: (0, height-1), axis_names[1]: (0, width-1)}
    expected = source_term(kernel, dag, row, col)
    coords = [(row, col), (row, col+1), (row+1, col), (row+1, col+1)]
    values = {}
    for r, c in reversed(coords) if reverse_definitions else coords:
        require(le(0, r, domain, b) and le(r+1, height+1, domain, b), 'input row bounds')
        require(le(0, c, domain, b) and le(c+1, width+1, domain, b), 'input column bounds')
        v = dag.node('input', (r, c), ())
        one = dag.node('const', (1,), ())
        plus = dag.node('add', (), (v, one))
        values[r, c] = dag.node('mul', (), (plus, plus))
    a, x, y, z = (values[p] for p in coords)
    add = lambda u, v: dag.node('add', (), (u, v))
    actual = add(add(a, add(x, y)), z) if mutation == 'reassociate' else add(add(add(a, x), y), z)
    require(actual == expected, 'exact retained source expression')
    if mutation == 'dead-overflow':
        huge = dag.node('const', (2**31-1,), ())
        dag.node('add', (), (huge, huge))
    outer, inner = (width, height) if column_major else (height, width)
    check_prefix(inner, budget=b); check_prefix(outer, budget=b)
    obligations = ['input-bounds', 'exact-source-DAG', 'all-scalar-i32',
                   'consumer-prefix', 'outer-base-step-exit', 'output-conservation']
    if schedule != 'inline':
        check_prefix(width+1, budget=b)
        obligations += ['stage-prefix', 'scratch-initialization', 'row-major-injectivity']
    if schedule == 'materialize':
        check_prefix(height+1, budget=b)
        capacity = b.mul(height+1, width+1)
        require(b.le(capacity, kernel.input_cells), 'capacity')
    if schedule == 'rows2':
        check_scratch(width, budget=b)
        require(b.le(b.mul(2, width+1), kernel.input_cells), 'rows2 capacity')
        obligations += ['complete-parity', 'refill-disjoint-frame', 'scratch-invalidation']
    # This is a trace of bounded primitive proof work, never a physical execution.
    encoded = json.dumps({'events': b.events, 'obligations': obligations,
                          'shape': [height, width]}, separators=(',', ':')).encode()
    graph = hashlib.sha256(json.dumps(b.events, separators=(',', ':')).encode()).hexdigest()
    return OutlineReceipt(schedule, (height, width), tuple(obligations), graph,
                          len(b.events), len(encoded),
                          0 if schedule == 'inline' else 3,
                          3, 2 if schedule == 'rows2' else 0,
                          len(dag.nodes), max(dag.depths), b.structural, b.bits,
                          b.structural+b.bits, kernel.source_digest,
                          kernel.specialization_digest, True)


@dataclass(frozen=True)
class FeasibilityReceipt:
    outcome: str
    first_unresolved: str
    outlines: tuple
    supported_rules: tuple
    assumptions: tuple
    production_gaps: tuple


def run_feasibility() -> FeasibilityReceipt:
    """No reviewer argument or mutable approval flag can self-activate this gate."""
    return FeasibilityReceipt(
        'blocked', 'F1: complete hand-certificate representation and quota bound pending independent re-review',
        tuple(probe_outline(s, 2048, 2048) for s in ('inline', 'materialize', 'rows2')),
        ('affine-endpoints', 'rectangle-join', 'disjoint-frame', 'singleton-extension',
         'exact-output-ledger', 'scratch-invalidation', 'source-term-DAG',
         'checked-i32', 'complete-parity', 'finite-induction (written rule)'),
        ('exact C2 admission', 'stable disjoint sized buffers', 'input 0..1023',
         'mathematical indices', 'checked-i32 scalar transitions',
         'correct implementation of the specified rules'),
        ('physical IR coverage and scoped induction DAG decoder',
         'generic region substitution and source-origin validation',
         'whole-checker quota/work enforcement and hostile decoder limits',
         'exact dynamic operation metrics; optional SSA liveness deferred',
         'native compiler correspondence, allocation and timing gates'))


def hand_certificate_bounds(*, omit_table=None, omit_work=None,
                            claimed_bytes=None, claimed_work=None):
    """Audit the analytical slot bounds in the C1 F1 appendix.

    This computes a proposed encoding-size derivation, NOT an encoded proof or
    measured checker work. The conservative work bound exceeds the frozen
    quota: callers must not turn the partial byte-fit result into proceed.
    Mutation arguments test arithmetic-accounting omissions only, not semantics.
    """
    producer = ('input_load', 'const', 'add', 'mul', 'scratch_store')
    consumer = ('scratch_load',)*4 + ('add',)*3 + ('output_store',)
    inline = ('input_load', 'const', 'add', 'mul')*4 + ('add',)*3 + ('output_store',)
    # Each ordinary body is represented once. Rows2's arbitrary outer body is
    # represented in BOTH parity subderivations; stage zero is represented once.
    instances = {'inline': inline, 'materialize': producer+consumer,
                 'rows2': producer+(producer+consumer)*2}
    loops = {'inline': 2, 'materialize': 4, 'rows2': 6}
    physical_nodes = {'inline': 22, 'materialize': 17, 'rows2': 22}
    rows_by_outline = {}
    for name, ops in instances.items():
        n, k = len(ops), loops[name]
        stores = sum(op.endswith('_store') for op in ops)
        regions = 2*stores + 12*k + 3
        rows_by_outline[name] = {
            'proof': 32*n + 64*k + 128,
            'regions': regions,
            'states': 2*n + 4*stores + 6*k + 2,
            'terms': 16*regions + 4*n,
            'affines': 8*regions + 2*n + 4*k + 8,
            'substitutions': 4*regions + 4*n + 4*k,
            'scopes': 3*k + 6,
            'physical_operations': physical_nodes[name],
        }
    rows = {key: max(d[key] for d in rows_by_outline.values())
            for key in rows_by_outline['inline']}
    require(sum(rows.values()) < 8192, 'reference width exceeds four decimal digits')
    row_bytes = {'proof': 128, 'regions': 96, 'states': 320, 'terms': 64,
                 'affines': 64, 'substitutions': 96, 'scopes': 96,
                 'physical_operations': 160}
    table_bytes = {key: rows[key]*width for key, width in row_bytes.items()}
    table_bytes['header_and_directory'] = 4096
    if omit_table is not None:
        require(omit_table in table_bytes, 'unknown omitted table')
        del table_bytes[omit_table]
    require(set(table_bytes) == set(row_bytes) | {'header_and_directory'},
            'incomplete encoding accounting')
    byte_bound = sum(table_bytes.values())
    # Every coefficient is explained in the appendix. This algorithm uses
    # materialized value instances and local topological checks; there is no
    # assumed DAG Cartesian product, free memo lookup, or zero-cost interning.
    source_nodes = 54*33 + 2048 + 6
    work = {
        'source_admission_and_reconstruction': 8*source_nodes + 2048*6*31 + 16*4*31 + 32*rows['terms'],
        'proof_premises_and_coverage': rows['proof']*(8*13 + 16),
        'affine_normalization_bounds_and_parity': rows['affines']*(4*31 + 4*14*14 + 4*31 + 16),
        'term_keys_intervals_and_comparison': rows['terms']*(2*8*31 + 4*31*31 + 8*31 + 16),
        'region_operations': rows['regions']*(12*13 + 16),
        'state_ledger_and_fact_bookkeeping': rows['states']*(50*13 + 16),
        'substitution_and_capture_checks': rows['substitutions']*(8*13 + 8*31 + 16),
        'scope_and_hypothesis_checks': rows['scopes']*(16*13 + 16),
        'physical_metrics_origins_and_coverage': rows['physical_operations']*(8*31*31 + 16*31 + 16),
        'identity_bytes_and_directory': 65536 + 4096,
    }
    mandatory_work = frozenset(work)
    if omit_work is not None:
        require(omit_work in work, 'unknown omitted work')
        del work[omit_work]
    require(frozenset(work) == mandatory_work, 'incomplete charged-work accounting')
    work_bound = sum(work.values())
    require(claimed_bytes is None or claimed_bytes == byte_bound, 'incorrect encoded-byte bound')
    require(claimed_work is None or claimed_work == work_bound, 'incorrect charged-work bound')
    return {
        'kind': 'analytical candidate bound; not a measured certificate',
        'expansion_completeness_established': False,
        'primitive_instances': {name: len(ops) for name, ops in instances.items()},
        'induction_instances': loops,
        'proof_rows': {name: d['proof'] for name, d in rows_by_outline.items()},
        'rows_by_outline': rows_by_outline,
        'table_rows': rows, 'table_bytes': table_bytes,
        'certificate_bytes_bound': byte_bound,
        'work_categories': work, 'total_work_bound': work_bound,
        'peak_scratch_facts': {'inline': 0, 'materialize': 3, 'rows2': 3},
        'intermediate_bits_bound': 31,
        'fits_unchanged_quotas': byte_bound <= 524288 and work_bound <= 1000000,
        'remaining_obstacle': 'F1: a sufficiently tight complete charged-work bound is not established',
    }


if __name__ == '__main__':
    print(json.dumps(asdict(run_feasibility()), indent=2))
