"""Single source of truth for the cross-language benchmark suite.

Every implementation (C, Rust, Python, NumPy, Node, Axiom) receives the same
kernel name, input pattern and two integer size parameters (a, b). Inputs are
generated from the index alone, so no large data crosses process boundaries.
Outputs are verified with a positional checksum, never by trusting a label.
"""

M = 1_000_000_007
PATTERNS = ('hash', 'ramp', 'alt', 'zeros', 'max')
SIZE_TIERS = ('s', 'm', 'l')


def value(pattern, i):
    """Input scalar i for a pattern; every value lies in 0..=1023."""
    if pattern == 'hash':
        return ((i * 2654435761) & 0xFFFFFFFF) >> 22
    if pattern == 'ramp':
        return i % 1024
    if pattern == 'alt':
        return 1023 * (i & 1)
    if pattern == 'zeros':
        return 0
    if pattern == 'max':
        return 1023
    raise ValueError(f'unknown pattern {pattern!r}')


def gen_input(pattern, count):
    return [value(pattern, i) for i in range(count)]


def checksum(values):
    """Order-sensitive checksum shared by all implementations."""
    acc = 0
    for i, v in enumerate(values):
        acc = (acc + (int(v) % M) * (i % 65521 + 1)) % M
    return acc


# Each kernel: input/output counts as functions of (a, b), size tiers, and
# (since window-stencil-v1) drafts for every kernel the two-stage window
# family can express. Separable drafts compute exactly the same integers.
# what Axiom would need to express it. `axiom_draft` names a file in
# axiom_drafts/ written in today's grammar, so it is either admitted or
# rejected with a real diagnostic; None means today's grammar cannot state
# the computation at all, and `missing` lists the language features needed.
KERNELS = {
    'sq2x2': dict(
        title='Squared 2x2 window sum (Axiom canonical stencil)', family='stencil-2d',
        io=lambda a, b: ((a + 1) * (b + 1), a * b),
        sizes=dict(s=(15, 15), m=(255, 255), l=(2047, 2047)),
        axiom_draft='sq2x2.ax', missing=['inputs above 256 cells (m/l tiers)']),
    'stencil1d3': dict(
        title='1-D 3-point weighted stencil', family='stencil-1d',
        io=lambda a, b: (a + 2, a),
        sizes=dict(s=(254, 0), m=(65534, 0), l=(4194302, 0)),
        axiom_draft='stencil1d3.ax', missing=['inputs above 256 cells (m/l tiers)']),
    'box3x3': dict(
        title='3x3 box sum', family='stencil-2d',
        io=lambda a, b: ((a + 2) * (b + 2), a * b),
        sizes=dict(s=(14, 14), m=(254, 254), l=(2046, 2046)),
        axiom_draft='box3x3.ax', missing=['inputs above 256 cells (m/l tiers)']),
    'laplace5': dict(
        title='5-point Laplacian (signed)', family='stencil-2d',
        io=lambda a, b: ((a + 2) * (b + 2), a * b),
        sizes=dict(s=(14, 14), m=(254, 254), l=(2046, 2046)),
        axiom_draft='laplace5.ax', missing=['inputs above 256 cells (m/l tiers)']),
    'conv3x3': dict(
        title='3x3 weighted convolution [1 2 1; 2 4 2; 1 2 1]', family='stencil-2d',
        io=lambda a, b: ((a + 2) * (b + 2), a * b),
        sizes=dict(s=(14, 14), m=(254, 254), l=(2046, 2046)),
        axiom_draft='conv3x3.ax', missing=['inputs above 256 cells (m/l tiers)']),
    'life': dict(
        title='Game of Life step (bit 0 = alive)', family='stencil-2d-cond',
        io=lambda a, b: ((a + 2) * (b + 2), a * b),
        sizes=dict(s=(14, 14), m=(254, 254), l=(2046, 2046)),
        axiom_draft=None, missing=['bitwise ops', 'comparison', 'select/conditional']),
    'polymap': dict(
        title='Elementwise x^3 + 3x + 7', family='elementwise',
        io=lambda a, b: (a, a),
        sizes=dict(s=(256, 0), m=(65536, 0), l=(4194304, 0)),
        axiom_draft='polymap.ax', missing=['inputs above 256 cells (m/l tiers)']),
    'transpose': dict(
        title='Matrix transpose', family='layout',
        io=lambda a, b: (a * b, a * b),
        sizes=dict(s=(16, 16), m=(256, 256), l=(2048, 2048)),
        axiom_draft='transpose.ax', missing=['permuted index reads', 'layout plans']),
    'maxpool2': dict(
        title='2x2 max pooling', family='stencil-2d-cond',
        io=lambda a, b: (4 * a * b, a * b),
        sizes=dict(s=(8, 8), m=(128, 128), l=(1024, 1024)),
        axiom_draft=None, missing=['max operator', 'strided index (2*r)']),
    'sum': dict(
        title='Sum reduction', family='reduction',
        io=lambda a, b: (a, 1),
        sizes=dict(s=(256, 0), m=(65536, 0), l=(4194304, 0)),
        axiom_draft=None, missing=['reduction syntax', 'i64 accumulators']),
    'dot': dict(
        title='Dot product', family='reduction',
        io=lambda a, b: (2 * a, 1),
        sizes=dict(s=(128, 0), m=(32768, 0), l=(2097152, 0)),
        axiom_draft=None, missing=['reduction syntax', 'multiple inputs', 'i64 accumulators']),
    'scan': dict(
        title='Inclusive prefix sum', family='scan',
        io=lambda a, b: (a, a),
        sizes=dict(s=(256, 0), m=(65536, 0), l=(4194304, 0)),
        axiom_draft=None, missing=['recurrence/scan syntax', 'i64 outputs']),
    'hist': dict(
        title='64-bin histogram (x >> 4)', family='scatter',
        io=lambda a, b: (a, 64),
        sizes=dict(s=(256, 0), m=(65536, 0), l=(4194304, 0)),
        axiom_draft=None, missing=['data-dependent indexing', 'scatter/accumulate']),
    'matmul': dict(
        title='Square integer matrix multiply', family='dense-linear-algebra',
        io=lambda a, b: (2 * a * a, a * a),
        sizes=dict(s=(8, 0), m=(64, 0), l=(256, 0)),
        axiom_draft=None, missing=['reduction syntax', 'multiple inputs', 'tiling plans']),
}

# Axiom-only plan-selection sweep on the canonical stencil (size s).
AXIOM_CAPS = (0, 16, 32, 64, 128, 1024)
AXIOM_OBJECTIVES = ('multiplication_ops', 'plan_workspace_bytes')