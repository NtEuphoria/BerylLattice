"""Invalid extremes on every emission path that can compute before its check is acted on.

Each kernel is fed several values outside its declared ranges at once (two or more
INT32_MAX, INT32_MIN, the values just past each bound, at the first, middle and last
index of each input, or in every cell) and must return the exact first-bad-index
status; under the default contract (`output_on_rejection = preserved`) the output
must be untouched. The arithmetic a kernel does on such values before rejecting
them must be free of undefined behavior. Run under sanitizers with a compiler
wrapper that adds them, for example in WSL:

    CC=../.local/harden/overflow/cc-san.sh PYTHONPATH=src python3 -m unittest tests.test_scale_invalid_extremes

where the wrapper runs `gcc -fsanitize=address,undefined -fno-sanitize-recover=all "$@"`.
A sanitizer report fails the run (nonzero exit, `runtime error` on stderr).
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from axiom.frontend import admit_source, parse_source
from axiom.model import C_TYPES, TYPE_BOUNDS
from axiom.reference import evaluate_source
from axiom.scale_c import compile_scale_native
from tests.test_scale_abi2 import QDOT, QLINEAR, REQUANT
from tests.test_scale_contract import DIAG, MIXED, ROW, WIDE, fused
from tests.test_scale_family import BOX, MATMUL, SUM
from tests.test_scale_fused import HALF
from tests.test_scale_i64 import DOT, wide
from tests.test_scale_storage import BLUR, BLUR_OUT, DENSE
from tests.test_scale_tiles import TRANSPOSE

CC = os.environ.get('CC', 'clang')
NATIVE = ('-O2', '-march=native')
PORTABLE = ('-O2',)  # baseline x86-64: no AVX2, so the portable u8 x i8 dot and other vector code
RUN_ENV = {'SYSTEMROOT': 'C:\\Windows', 'ASAN_OPTIONS': 'detect_leaks=0:abort_on_error=0',
           'UBSAN_OPTIONS': 'print_stacktrace=1:halt_on_error=1'}


def ranged(text, lo, hi):
    return text.replace('in 0..=1023', f'in {lo}..={hi}')


def harness_c(kernel, v2, init):
    """main(argc, argv): read every input cell from stdin, call the kernel, print the status,
    the number of output cells changed from `init`, and (argv[1] == "1") every output."""
    out = C_TYPES[kernel.output_type]
    if v2:
        types = [C_TYPES[t] for t in kernel.input_types]
        counts = [rows * cols for rows, cols in kernel.all_input_shapes]
        decl = f'int64_t beryl_kernel_v2({", ".join(f"const {t} *" for t in types)}, {out} *);'
    else:
        types, counts = [C_TYPES[kernel.input_type]], [kernel.input_count]
        decl = f'int32_t beryl_kernel(const {types[0]} *, {out} *);'
    n_out = kernel.height * kernel.width
    lines = ['#include <stdint.h>', '#include <stdio.h>', '#include <stdlib.h>', decl,
             'int main(int argc, char **argv) {', '    long long v;', '    if (argc != 2) return 2;']
    for k, (t, n) in enumerate(zip(types, counts)):
        lines += [f'    {t} *in{k} = malloc((size_t){n} * sizeof *in{k});', f'    if (!in{k}) return 3;',
                  f'    for (long long i = 0; i < {n}LL; i++) {{',
                  '        if (scanf("%lld", &v) != 1) return 4;', f'        in{k}[i] = ({t})v;', '    }']
    lines += [f'    {out} *out = malloc((size_t){n_out} * sizeof *out);', '    if (!out) return 3;',
              f'    for (long long i = 0; i < {n_out}LL; i++) out[i] = ({out}){init};',
              '    long long status = (long long)' + ('beryl_kernel_v2(' if v2 else 'beryl_kernel(')
              + ''.join(f'in{k}, ' for k in range(len(types))) + 'out);',
              '    long long changed = 0;',
              f'    for (long long i = 0; i < {n_out}LL; i++) changed += out[i] != ({out}){init};',
              '    printf("%lld %lld", status, changed);',
              f'    if (argv[1][0] == \'1\') for (long long i = 0; i < {n_out}LL; i++) printf(" %lld", (long long)out[i]);',
              '    printf("\\n");',
              *(f'    free(in{k});' for k in range(len(types))), '    free(out);', '    return 0;', '}', '']
    return '\n'.join(lines)


def segments(kernel):
    out, start = [], 0
    for (rows, cols), (lo, hi), storage in zip(kernel.all_input_shapes, kernel.input_intervals, kernel.input_types):
        out.append((start, start + rows * cols, lo, hi, storage))
        start += rows * cols
    return out


def extremes(lo, hi, storage):
    """Values of the storage type outside lo..=hi, by name (None where there is none)."""
    low, high = TYPE_BOUNDS[storage]
    return {'max': high if high > hi else None, 'min': low if low < lo else None,
            'above': hi + 1 if hi < high else None, 'below': lo - 1 if lo > low else None}


def pick(ext, *names):
    return next((ext[name] for name in names if ext[name] is not None), None)


# (name, baseline, bad cells of an input of m cells given its extremes)
def _spread(m):
    return sorted({0, m // 2, m - 1, *(j * m // 8 for j in range(8))})


PATTERNS = (
    ('max-spread/lo', 'lo', lambda m, e: [(i, pick(e, 'max', 'above', 'min', 'below')) for i in _spread(m)]),
    ('max-spread/hi', 'hi', lambda m, e: [(i, pick(e, 'max', 'above', 'min', 'below')) for i in _spread(m)]),
    ('min-spread/lo', 'lo', lambda m, e: [(i, pick(e, 'min', 'below', 'max', 'above')) for i in _spread(m)]),
    ('min-spread/hi', 'hi', lambda m, e: [(i, pick(e, 'min', 'below', 'max', 'above')) for i in _spread(m)]),
    ('edges', 'hash', lambda m, e: [(m // 2, pick(e, 'below', 'above')), (m - 1, pick(e, 'above', 'below')),
                                    (1 % m, pick(e, 'max', 'min'))]),
    ('mixed', 'hash', lambda m, e: [(m - 1, pick(e, 'above', 'below')), (m // 2, pick(e, 'max', 'min')),
                                    (0, pick(e, 'min', 'max'))]),
    ('last', 'hash', lambda m, e: [(max(0, m - 2), pick(e, 'min', 'max')), (m - 1, pick(e, 'max', 'min'))]),
    ('flood-max', 'hash', lambda m, e: [(i, pick(e, 'max', 'min', 'above', 'below')) for i in range(m)]),
    ('flood-min', 'hash', lambda m, e: [(i, pick(e, 'min', 'max', 'below', 'above')) for i in range(m)]),
)


def dataset(kernel, baseline, pattern, only_last=False):
    data = []
    segs = segments(kernel)
    checked = [k for k, (_, _, lo, hi, t) in enumerate(segs) if (lo, hi) != TYPE_BOUNDS[t]]
    for k, (s, e, lo, hi, t) in enumerate(segs):
        m, span = e - s, hi - lo + 1
        cells = ([lo] * m if baseline == 'lo' else [hi] * m if baseline == 'hi' else
                 [lo + ((i * 2654435761 & 0xFFFFFFFF) % span) for i in range(s, e)])
        if pattern is not None and k in checked and (not only_last or k == checked[-1]):
            for index, value in pattern(m, extremes(lo, hi, t)):
                cells[index] = value
        data += cells
    return data


def expected_status(kernel, data):
    for s, e, lo, hi, _ in segments(kernel):
        for i in range(s, e):
            if not lo <= data[i] <= hi:
                return i + 1
    return 0


class Case:
    def __init__(self, source, markers=(), absent=(), builds=(NATIVE,), reference=False, threads=('1', '4')):
        self.source = source if isinstance(source, bytes) else source.encode()
        self.markers, self.absent, self.builds = markers, absent, builds
        self.reference, self.threads = reference, threads


class InvalidExtremesBase(unittest.TestCase):
    def exercise(self, case):
        artifact = compile_scale_native(case.source).artifact
        self.assertIsNotNone(artifact)
        c_source = artifact.c_source
        for marker in case.markers:  # the case really takes the path it names
            self.assertIn(marker, c_source)
        for marker in case.absent:
            self.assertNotIn(marker, c_source)
        kernel = admit_source(parse_source(case.source))
        preserved = kernel.output_on_rejection == 'preserved'
        v2 = b'int64_t beryl_kernel_v2(' in c_source
        init = 251 if kernel.output_type == 'u8' else -9
        n_out = kernel.height * kernel.width
        multi = len([1 for _, _, lo, hi, t in segments(kernel) if (lo, hi) != TYPE_BOUNDS[t]]) > 1
        runs = [('valid', 'hash', None, False)] + [(name, base, pat, False) for name, base, pat in PATTERNS]
        if multi:
            runs += [(name + '/last-input', base, pat, True) for name, base, pat in PATTERNS if name in ('mixed', 'edges')]
        with tempfile.TemporaryDirectory() as tmp:
            kernel_c, harness = Path(tmp) / 'kernel.c', Path(tmp) / 'harness.c'
            kernel_c.write_bytes(c_source.replace(b'int main(void)', b'int beryl_unused_main(void)'))
            harness.write_text(harness_c(kernel, v2, init))
            for b, flags in enumerate(case.builds):
                exe = Path(tmp) / f'k{b}.exe'
                try:
                    built = subprocess.run([CC, *flags, '-std=c11', '-Wall', '-Werror', '-pthread', str(kernel_c),
                                            str(harness), '-o', str(exe)], capture_output=True, text=True)
                except OSError as error:
                    self.skipTest(f'no C compiler: {error}')
                self.assertEqual(built.returncode, 0, built.stderr)  # a compile error is a failure, not a skip
                for name, baseline, pattern, only_last in runs:
                    data = dataset(kernel, baseline, pattern, only_last)
                    want = expected_status(kernel, data)
                    show = case.reference and want == 0
                    for threads in case.threads:
                        try:
                            ran = subprocess.run([str(exe), '1' if show else '0'], input=' '.join(map(str, data)),
                                                 capture_output=True, text=True,
                                                 env={**RUN_ENV, 'BERYL_THREADS': threads})
                        except OSError as error:  # Windows Application Control; never bypassed
                            self.skipTest(f'executable launch refused: {error}')
                        with self.subTest(flags=' '.join(flags), pattern=name, threads=threads):
                            self.assertNotIn('runtime error', ran.stderr, ran.stderr[-3000:])
                            self.assertNotIn('AddressSanitizer', ran.stderr, ran.stderr[-3000:])
                            self.assertEqual(ran.returncode, 0, ran.stderr[-3000:])
                            status, changed, *values = map(int, ran.stdout.split())
                            self.assertEqual(status, want)
                            if want and preserved:
                                self.assertEqual(changed, 0, 'a rejected call wrote the output')
                            if show:
                                ref = evaluate_source(kernel.source_module, data, [init] * n_out)
                                self.assertEqual(tuple(values), ref.output)


FUSED_SPLIT = b'uint32_t *bad)'
PARTIAL = b'beryl_partial('


class SplitSumTests(InvalidExtremesBase):
    """One cell, one large sum split across the pool; whole-input sums check as they add."""

    def test_i32_sum_or_check(self):
        self.exercise(Case(SUM.format(n=1 << 17), (FUSED_SPLIT, b'ax_u0 |= ax_v;'), builds=(NATIVE, PORTABLE),
                           reference=True))

    def test_i32_sum_maximum_check(self):
        self.exercise(Case(ranged(SUM.format(n=1 << 17), 0, 1000), (FUSED_SPLIT, b'ax_u0 = ax_v > ax_u0'),
                           reference=True))

    def test_i32_sum_signed_range(self):
        self.exercise(Case(ranged(SUM.format(n=1 << 17), -512, 511), (FUSED_SPLIT,), reference=True))

    def test_i32_dot(self):
        self.exercise(Case(DOT.format(n=1 << 16).replace('0..=1023', '0..=127'), (FUSED_SPLIT,), reference=True))

    def test_i64_sum_in_exact_i32_blocks(self):
        self.exercise(Case(wide(SUM.format(n=1 << 17)), (FUSED_SPLIT, b'ax_b'), reference=True))

    def test_i64_dot_in_exact_i32_blocks(self):
        self.exercise(Case(wide(DOT.format(n=1 << 16)), (FUSED_SPLIT, b'ax_b'), reference=True))

    def test_i64_sum_without_blocks(self):
        # x*x reaches 65535^2 > 2^31, so the body is computed in int64_t, not in i32 blocks.
        source = wide(SUM.format(n=1 << 17).replace('x[0,k])', 'x[0,k]*x[0,k])').replace('0..=1023', '0..=65535'))
        self.exercise(Case(source, (FUSED_SPLIT, b'acc = (int64_t)((uint64_t)acc +'), (b'ax_b',), reference=True))

    def test_partial_sum_keeps_the_preflight(self):
        self.exercise(Case(HALF.format(n=1 << 17, m=1 << 16), (PARTIAL,), (FUSED_SPLIT,), reference=True))

    def test_abi2_u8_by_i8(self):
        # a in 0..=200, so 255 is rejected; 80000 terms of 255 * -128 pass -2^31.
        self.exercise(Case(QDOT.format(n=80000).replace('0..=255', '0..=200'), (FUSED_SPLIT, b'beryl_kernel_v2('),
                           reference=True))

    def test_abi2_u8_by_i8_i64(self):
        self.exercise(Case(wide(QDOT.format(n=1 << 17)), (FUSED_SPLIT, b'beryl_kernel_v2(', b'ax_b'), reference=True))


BLOCKED = b'beryl_fused('


class FusedContractTests(InvalidExtremesBase):
    """`require output_on_rejection = unspecified;`: each block computes, then checks its input."""

    def test_cells_serial(self):
        self.exercise(Case(fused(WIDE.format(h=40, w=30)), (BLOCKED,), reference=True))

    def test_cells_parallel(self):
        self.exercise(Case(fused(WIDE.format(h=700, w=900)), (BLOCKED, b'beryl_dispatch(')))

    def test_stencil(self):
        self.exercise(Case(fused(DIAG.format(h=300, w=200)), (BLOCKED,)))

    def test_carry(self):
        self.exercise(Case(fused(BOX.format(h=60, w=50)), (BLOCKED, b'beryl_produce_row('), reference=True))

    def test_carry_i64(self):
        self.exercise(Case(wide(fused(BOX.format(h=60, w=50))), (BLOCKED, b'beryl_produce_row('), reference=True))

    def test_carry_u8_shift(self):
        self.exercise(Case(fused(BLUR.format(h=60, w=50, lo=16, hi=235, out=BLUR_OUT)), (BLOCKED, b'beryl_shr_round'),
                           reference=True))

    def test_stream(self):
        self.exercise(Case(fused(ROW.format(w=1 << 21)), (BLOCKED, b'beryl_stream(')))

    def test_abi2_mixed(self):
        self.exercise(Case(fused(MIXED.format(h=600, w=500)), (BLOCKED, b'beryl_kernel_v2(')))

    def test_madd(self):
        source = fused(QLINEAR.format(w=37, n=300).replace('in 0..=255', 'in 0..=127'))
        self.exercise(Case(source, (BLOCKED, b'beryl_dot_u8i8('), builds=(NATIVE, PORTABLE), reference=True))

    def test_madd_i64_requant(self):
        source = fused(REQUANT.format(w=37, n=300).replace('in 0..=255', 'in 0..=127'))
        self.exercise(Case(source, (BLOCKED, b'beryl_dot_u8i8('), builds=(NATIVE, PORTABLE), reference=True))

    def test_i8_dense_i64_shift(self):
        self.exercise(Case(fused(DENSE.format(w=64, n=256)), (BLOCKED,), reference=True))

    def test_rows_keep_the_preflight(self):
        # Row accumulation never computes on unchecked input, under either contract.
        self.exercise(Case(fused(MATMUL.format(n=64)), (b'accumulated a row segment',), (BLOCKED,), reference=True))

    def test_tiled_keeps_the_preflight(self):
        self.exercise(Case(fused(TRANSPOSE.format(h=37, w=53, out='t[r,c]')), (b'x 16 tiles',), (BLOCKED,),
                           reference=True))

    def test_split_sum(self):
        # A whole-input sum under the fused contract takes the split path, not blocks.
        self.exercise(Case(fused(SUM.format(n=1 << 17)), (FUSED_SPLIT,), (BLOCKED,), reference=True))

    def test_unblocked_madd_keeps_the_preflight(self):
        # 4096 terms per cell: the shares would recheck too much, so the preflight stays.
        source = fused(QLINEAR.format(w=64, n=4096).replace('in 0..=255', 'in 0..=127'))
        self.exercise(Case(source, (b'beryl_dot_u8i8(',), (BLOCKED,), builds=(NATIVE, PORTABLE)))


class DefaultContractTests(InvalidExtremesBase):
    """The preflight completes before any cell is computed: output untouched on rejection."""

    def test_row_accumulation(self):
        self.exercise(Case(MATMUL.format(n=64), (b'accumulated a row segment',), reference=True))

    def test_tiled(self):
        self.exercise(Case(TRANSPOSE.format(h=37, w=53, out='t[r,c]'), (b'x 16 tiles',), reference=True))

    def test_carry(self):
        self.exercise(Case(BOX.format(h=60, w=50), (b'beryl_produce_row(',), (BLOCKED,), reference=True))

    def test_carry_u8_shift(self):
        self.exercise(Case(BLUR.format(h=60, w=50, lo=16, hi=235, out=BLUR_OUT), (b'beryl_produce_row(',),
                           reference=True))

    def test_stream(self):
        self.exercise(Case(ROW.format(w=1 << 21), (b'beryl_stream(',), (BLOCKED,)))

    def test_parallel_preflight(self):
        self.exercise(Case(WIDE.format(h=700, w=900), (b'beryl_dispatch(0,',), (BLOCKED,)))

    def test_madd(self):
        source = QLINEAR.format(w=37, n=300).replace('in 0..=255', 'in 0..=127')
        self.exercise(Case(source, (b'beryl_dot_u8i8(',), (BLOCKED,), builds=(NATIVE, PORTABLE), reference=True))

    def test_abi2_four_inputs(self):
        self.exercise(Case(REQUANT.format(w=37, n=300), (b'beryl_kernel_v2(',), reference=True))

    def test_abi2_mixed_parallel(self):
        self.exercise(Case(MIXED.format(h=600, w=500), (b'beryl_kernel_v2(', b'beryl_dispatch('), (BLOCKED,)))

    def test_i8_dense_i64_shift(self):
        self.exercise(Case(DENSE.format(w=64, n=256), (), (BLOCKED,), reference=True))


# Row-wise u8 x i8 dot products, one output column: not rows (W < 8), not split (H cells),
# so under the fused contract each block is computed before it is checked. 70000 terms of
# 255 * -128 pass -2^31, so the dot helper must add in wrapping arithmetic.
ROWDOT = '''module rowdot;
shape H = {h};
shape W = 1;
input a: u8[H,{n}] in 0..=1;
input k: i8[H,{n}] in -1..=1;
let t[r in 0..H,c in 0..W] = sum(j in 0..{n}: a[r,j]*k[r,j]);
output d[r in 0..H,c in 0..W] = t[r,c];
'''
DOT_CALL = b'beryl_dot_u8i8('


class BlockedDotTests(InvalidExtremesBase):
    """The fused contract's blocked u8 x i8 dot, long enough to overflow int32_t on invalid data."""

    def test_serial(self):
        self.exercise(Case(fused(ROWDOT.format(h=4, n=70000)), (BLOCKED, DOT_CALL), builds=(PORTABLE, NATIVE),
                           reference=True, threads=('1',)))

    def test_parallel(self):
        self.exercise(Case(fused(ROWDOT.format(h=32, n=70000)), (BLOCKED, DOT_CALL, b'beryl_dispatch('),
                           builds=(PORTABLE,), threads=('1', '4')))

    def test_i64(self):
        self.exercise(Case(wide(fused(ROWDOT.format(h=4, n=70000))), (BLOCKED, DOT_CALL), builds=(PORTABLE,),
                           reference=True, threads=('1',)))

    def test_default_contract_keeps_the_preflight(self):
        self.exercise(Case(ROWDOT.format(h=4, n=70000), (DOT_CALL,), (BLOCKED,), builds=(PORTABLE,),
                           reference=True, threads=('1',)))


if __name__ == '__main__':
    unittest.main()
