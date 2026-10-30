"""The fused contract: `require output_on_rejection = unspecified;` checks each block of
input just before computing it, so the input is read once. The status stays exact."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from axiom.model import C_TYPES, DiagnosticError
from axiom.reference import evaluate_cells
from axiom.scale_c import compile_scale_native
from tests.test_scale_abi2 import HARNESS, bad_value
from tests.test_scale_family import BOX, TRANSPOSE
from tests.test_scale_large import generator, kernel_of

FUSED = 'require output_on_rejection = unspecified;\n'
SAMPLED = Path(__file__).parent / 'fixtures' / 'scale_sampled_harness.c'


def fused(text):
    """`text` with the fused contract declared after its module line."""
    head, rest = text.split('\n', 1)
    return f'{head}\n{FUSED}{rest}'


# A map over an input three columns wider than the output: those columns are never read.
WIDE = '''module wide;
shape H = {h};
shape W = {w};
input x: i32[H,W+3] in 0..=1023;
let t[r in 0..H,c in 0..W] = 3*x[r,c] + 1;
output y[r in 0..H,c in 0..W] = t[r,c];
'''
# Two inputs, two storage types: ABI 2.
MIXED = '''module mixed;
shape H = {h};
shape W = {w};
input x: i32[H,W] in -1000..=1000;
input g: u8[H,W] in 0..=200;
let t[r in 0..H,c in 0..W] = x[r,c]*g[r,c];
output y[r in 0..H,c in 0..W] = t[r,c];
'''
# A stencil inlined into the cells loop (no producer reuse).
DIAG = '''module diag;
shape H = {h};
shape W = {w};
input x: i32[H+1,W+2] in 0..=1023;
let p[r in 0..H,c in 0..W] = x[r,c] + 2*x[r+1,c+2];
output o[r in 0..H,c in 0..W] = p[r,c];
'''
# One output row: blocks are runs of cells; large enough for streaming stores.
ROW = '''module row;
shape H = 1;
shape W = {w};
input x: i32[1,W+2] in 0..=1023;
let t[r in 0..H,c in 0..W] = (x[r,c] + x[r,c+1]) + x[r,c+2];
output y[r in 0..H,c in 0..W] = t[r,c];
'''


class ContractTests(unittest.TestCase):
    def fails(self, text, code):
        with self.assertRaises(DiagnosticError) as raised:
            kernel_of(text)
        self.assertEqual(raised.exception.code, code)
        return str(raised.exception)

    def test_the_contract_is_part_of_the_identity(self):
        plain, declared = kernel_of(WIDE.format(h=40, w=30)), kernel_of(fused(WIDE.format(h=40, w=30)))
        self.assertEqual((plain.output_on_rejection, declared.output_on_rejection), ('preserved', 'unspecified'))
        self.assertNotEqual(plain.semantic_digest, declared.semantic_digest)

    def test_small_programs_with_the_contract_are_scale_v1(self):
        self.assertEqual(kernel_of(BOX.format(h=4, w=4)).profile, 'window-stencil-v1')
        self.assertEqual(kernel_of(fused(BOX.format(h=4, w=4))).profile, 'scale-v1')

    def test_only_the_one_spelling_is_accepted(self):
        text = WIDE.format(h=40, w=30)
        for line in ('require output_on_rejection = preserved;\n', 'require output_on_rejection <= 3;\n',
                     'require plan_workspace_bytes = unspecified;\n', FUSED + FUSED):
            with self.subTest(line=line):
                self.fails(text.replace('shape H', line + 'shape H', 1), 'INVALID_CONSTRAINT')
        self.fails(text.replace('shape H', 'require output = unspecified;\nshape H', 1), 'UNSUPPORTED_CONSTRAINT')

    def test_programs_outside_scale_v1_refuse_it(self):
        # The output reads the input directly, which no scale-v1 program does.
        text = fused(WIDE.format(h=40, w=30)).replace('= t[r,c];', '= x[r,c];')
        self.assertIn('scale-v1', self.fails(text, 'UNSUPPORTED_PROFILE'))


class EmissionTests(unittest.TestCase):
    def test_maps_and_stencils_check_block_by_block(self):
        for text in (WIDE.format(h=40, w=30), DIAG.format(h=40, w=30), BOX.format(h=60, w=50),
                     ROW.format(w=1 << 21)):
            with self.subTest(program=text.split(';')[0]):
                artifact = compile_scale_native(fused(text).encode()).artifact
                self.assertIn('fused', artifact.codegen_version)
                self.assertIn(b'beryl_fused(', artifact.c_source)
                plain = compile_scale_native(text.encode()).artifact
                self.assertNotIn('fused', plain.codegen_version)
                self.assertNotIn(b'beryl_fused(', plain.c_source)

    def test_programs_that_read_far_from_their_row_keep_the_preflight(self):
        # A transpose reads a column of the input for each output row.
        artifact = compile_scale_native(fused(TRANSPOSE).encode()).artifact
        self.assertNotIn('fused', artifact.codegen_version)
        self.assertNotIn(b'beryl_fused(', artifact.c_source)


class NativeTests(unittest.TestCase):
    """Fused kernels against the sampled reference; on rejection only the status is defined."""
    PROGRAMS = (
        WIDE.format(h=40, w=30), WIDE.format(h=700, w=900), MIXED.format(h=40, w=30),
        MIXED.format(h=600, w=500), DIAG.format(h=300, w=200), BOX.format(h=60, w=50),
        BOX.format(h=400, w=300), ROW.format(w=1 << 21), TRANSPOSE,
    )

    def build(self, kernel, artifact, abi, tmp):
        c, exe = Path(tmp) / f'k{abi}.c', Path(tmp) / f'k{abi}.exe'
        c.write_bytes(artifact.c_source.replace(b'int main(void)', b'int beryl_unused_main(void)'))
        types = [C_TYPES[t] for t in kernel.input_types]
        flags = ([f'-DBERYL_NIN={len(types)}', *(f'-DBERYL_IN{k}={t}' for k, t in enumerate(types))]
                 if abi == 2 else [f'-DBERYL_IN={types[0]}'])
        try:
            built = subprocess.run(['clang', '-O2', '-std=c11', '-Wall', '-Werror', *flags,
                                    f'-DBERYL_OUT={C_TYPES[kernel.output_type]}', str(c),
                                    str(HARNESS if abi == 2 else SAMPLED), '-o', str(exe)],
                                   capture_output=True, text=True)
        except OSError as error:
            self.skipTest(f'no C compiler: {error}')
        self.assertEqual(built.returncode, 0, built.stderr)
        return exe

    def run_program(self, text, tmp):
        kernel = kernel_of(fused(text))
        n_out = kernel.output_count
        segments, value_at = generator(kernel)
        samples = sorted(set(range(min(n_out, 40))) | {n_out // 2, n_out - 2, n_out - 1})
        expected = list(evaluate_cells(kernel.source_module, value_at, samples))
        cases, start = [(-1, 0)], 0
        for (end, lo, hi), storage in zip(segments, kernel.input_types):
            value = bad_value(storage, lo, hi)
            cases += [(index, value) for index in (start, (start + end) // 2, end - 1)]
            start = end
        if text.startswith('module wide'):
            # The last unread column of the middle row.
            cols = kernel.all_input_shapes[0][1]
            cases.append(((kernel.height // 2) * cols + cols - 1, 1024))
        abis = (2,) if len(set(kernel.input_types)) > 1 else (1, 2)
        for abi in abis:
            exe = self.build(kernel, compile_scale_native(fused(text).encode(), abi=abi).artifact, abi, tmp)
            if abi == 2:
                spec, start = [], 0
                for end, lo, hi in segments:
                    spec += [end - start, lo, hi]
                    start = end
                head = [n_out]
            else:
                spec = [len(segments), *(v for segment in segments for v in segment)]
                head = [kernel.input_count, n_out]
            for bad, value in cases:
                for threads in ('1', '4'):
                    args = [*head, bad, value, *spec, *samples]
                    try:
                        ran = subprocess.run([str(exe), *map(str, args)], capture_output=True, text=True,
                                             check=True, timeout=120,
                                             env={'BERYL_THREADS': threads, 'SYSTEMROOT': 'C:\\Windows'})
                    except OSError as error:  # Windows Application Control; never bypassed
                        self.skipTest(f'executable launch refused: {error}')
                    got = list(map(int, ran.stdout.split()))
                    with self.subTest(program=text.split(';')[0], abi=abi, bad=bad, threads=threads):
                        if bad < 0:
                            self.assertEqual(got, [0, *expected])
                        else:
                            self.assertEqual(got[0], bad + 1)  # the output is unspecified

    def test_status_is_exact_and_good_data_computes(self):
        for text in self.PROGRAMS:
            with self.subTest(program=text.split(';')[0], size=text.split('\n')[1:3]), \
                    tempfile.TemporaryDirectory() as tmp:
                self.run_program(text, tmp)


if __name__ == '__main__':
    unittest.main()
