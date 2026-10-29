"""scale-v1: template proofs over loop plans, independent of data size."""
import dataclasses
from pathlib import Path
import subprocess
import tempfile
import unittest

from axiom.frontend import admit_source, parse_source
from axiom.model import DiagnosticError, Limits
from axiom.reference import evaluate_source
from axiom.scale_c import compile_scale_native
from axiom.scale_checker import check_loop_plan
from axiom.scale_plan import LoopPlan, Stage, make_scale_plan
from axiom.scale_runtime import execute_loop_plan
from tests.helpers import stencil_source

BOX = '''module box;
shape H = {h};
shape W = {w};
input x: i32[H+2,W+2] in 0..=1023;
let p[r in 0..H+2,c in 0..W] = (x[r,c]+x[r,c+1])+x[r,c+2];
output o[r in 0..H,c in 0..W] = (p[r,c]+p[r+1,c])+p[r+2,c];
'''
SUM = '''module total;
shape H = 1;
shape W = 1;
input x: i32[1,{n}] in 0..=1023;
let t[r in 0..H,c in 0..W] = sum(k in 0..{n}: x[0,k]);
output s[r in 0..H,c in 0..W] = t[r,c];
'''
MATMUL = '''module matmul;
shape H = {n};
shape W = {n};
input a: i32[H,{n}] in 0..=1023;
input b: i32[{n},W] in 0..=1023;
let t[r in 0..H,c in 0..W] = sum(k in 0..{n}: a[r,k]*b[k,c]);
output m[r in 0..H,c in 0..W] = t[r,c];
'''
ROWSUM = '''module rows;
shape H = 3;
shape W = 1;
input x: i32[H,400] in 0..=1023;
let t[r in 0..H,c in 0..W] = sum(k in 0..400: 2*x[r,k] + -1);
output s[r in 0..H,c in 0..W] = t[r,c];
'''
TRANSPOSE = '''module transpose;
shape H = 30;
shape W = 20;
input x: i32[W,H] in 0..=1023;
let t[r in 0..H,c in 0..W] = x[c,r];
output y[r in 0..H,c in 0..W] = t[r,c];
'''


def data_for(n):
    return [(i * 2654435761 & 0xFFFFFFFF) >> 22 for i in range(n)]


class ScaleFamilyTests(unittest.TestCase):
    def compiled(self, source):
        result = compile_scale_native(source)
        self.assertEqual(result.reason, 'VALID', result.check and result.check.detail)
        return result

    def test_admission_order_and_limits(self):
        self.assertEqual(admit_source(parse_source(stencil_source(5, 7))).profile, 'canonical-stencil-v1')
        self.assertEqual(admit_source(parse_source(stencil_source(40, 30))).profile, 'scale-v1')
        self.assertEqual(admit_source(parse_source(BOX.format(h=4, w=4).encode())).profile, 'window-stencil-v1')
        self.assertEqual(admit_source(parse_source(BOX.format(h=60, w=50).encode())).profile, 'scale-v1')
        self.assertEqual(admit_source(parse_source(SUM.format(n=200).encode())).profile, 'reduce-v1')
        self.assertEqual(admit_source(parse_source(SUM.format(n=5000).encode())).profile, 'scale-v1')
        # 46341^2 cells and 2^31 terms: one past the 2^31 - 1 limits.
        for source, code in ((stencil_source(46341, 46341), 'UNSUPPORTED_PROFILE'),
                             (SUM.format(n=5000).replace('0..5000', '-1..2147483647').encode(), 'INVALID_RANGE'),
                             (SUM.format(n=5000).replace('x[0,k])', 'k*x[0,k])').encode(), 'UNDEFINED_NAME')):
            with self.subTest(code=code), self.assertRaises(DiagnosticError) as caught:
                admit_source(parse_source(source))
            self.assertEqual(caught.exception.code, code)

    def test_loop_plans_match_the_reference_on_good_and_bad_inputs(self):
        sources = [stencil_source(40, 30), BOX.format(h=30, w=25).encode(), SUM.format(n=3000).encode(),
                   MATMUL.format(n=12).encode(), ROWSUM.encode(), TRANSPOSE.encode()]
        for source in sources:
            kernel = admit_source(parse_source(source))
            plan = make_scale_plan(kernel)
            n = kernel.input_count
            for bad in (None, 0, n // 2, n - 1):
                with self.subTest(module=source.split(b';')[0], bad=bad):
                    data = data_for(n)
                    if bad is not None:
                        data[bad] = 1024 if bad % 2 else -1
                    initial = [-9] * kernel.output_count
                    self.assertEqual(execute_loop_plan(source, plan, data, initial),
                                     evaluate_source(kernel.source_module, data, initial))

    def test_proof_cost_does_not_grow_with_size(self):
        small = self.compiled(stencil_source(20, 20)).check.work_used
        large = self.compiled(stencil_source(2000, 2000)).check.work_used
        self.assertEqual(small, large)
        self.assertEqual(self.compiled(SUM.format(n=1000).encode()).check.work_used,
                         self.compiled(SUM.format(n=1 << 20).encode()).check.work_used)

    def test_forged_plans_are_rejected(self):
        source = MATMUL.format(n=300).encode()  # over 256 terms: a symbolic sum
        kernel = admit_source(parse_source(source))
        plan = make_scale_plan(kernel)
        stage = plan.stages[0]
        self.assertTrue(check_loop_plan(source, plan).valid)

        def with_value(value):
            return dataclasses.replace(plan, stages=(dataclasses.replace(stage, value=value),))
        _, var, lo, hi, body = stage.value
        forged = {
            'operands swapped': with_value(('sum', var, lo, hi, (body[0], body[2], body[1]))),
            'range shortened': with_value(('sum', var, lo, hi - 1, body)),
            'add for mul': with_value(('sum', var, lo, hi, ('add', body[1], body[2]))),
            'shifted load': with_value(('sum', var, lo, hi, (body[0], ('load', (body[1][1][0] + 1, body[1][1][1])), body[2]))),
            'sum var reuses a loop var': with_value(('sum', 'r', lo, hi, body)),
            'wrong extent': dataclasses.replace(plan, stages=(dataclasses.replace(stage, loops=(('r', 300), ('c', 299))),)),
            'wrong store': dataclasses.replace(plan, stages=(dataclasses.replace(stage, index=(0, (('c', 300), ('r', 1)))),)),
            'two stages': dataclasses.replace(plan, stages=(stage, stage)),
            'digest': dataclasses.replace(plan, semantic_digest='0' * 64),
            'garbage': dataclasses.replace(plan, stages=('x',)),
            'not canonical': with_value(('sum', var, lo, hi, (body[0], ('load', (body[1][1][0], body[1][1][1][::-1])), body[2]))),
        }
        for label, bad in forged.items():
            with self.subTest(forgery=label):
                self.assertFalse(check_loop_plan(source, bad).valid)
        self.assertFalse(check_loop_plan(source, LoopPlan(plan.semantic_digest, 'x', (Stage((), (0, ()), ('const', 0)),))).valid)

    def test_overflow_is_refused_by_the_proof(self):
        cases = [SUM.format(n=3000).replace('x[0,k])', 'x[0,k]*x[0,k])'),  # 3000 * 1023^2 > 2^31
                 SUM.format(n=3000).replace('x[0,k])', 'x[0,k]*2100000)')]
        for source in cases:
            with self.subTest(source=source.splitlines()[4]):
                result = compile_scale_native(source.encode())
                self.assertIsNone(result.artifact)
                self.assertEqual(result.reason, 'ARITHMETIC_OVERFLOW')

    def test_native_dispatch_and_emitted_c(self):
        from axiom.source_compilation import compile_native_source, compile_wasm_source
        source = SUM.format(n=1 << 20).encode()
        compiled = compile_native_source(source)
        # A large single-cell sum splits its range across the worker pool.
        self.assertEqual(compiled.artifact.codegen_version, 'beryl-loop-c-parallel-v2')
        self.assertIn(b'static int32_t beryl_partial(', compiled.artifact.c_source)
        self.assertIn(b'beryl_claim_chunks', compiled.artifact.c_source)
        small = compile_native_source(SUM.format(n=300).encode()).artifact
        self.assertEqual(small.codegen_version, 'beryl-loop-c-v2')  # below the parallel threshold
        self.assertEqual(compiled.artifact.input_count, 1 << 20)
        self.assertIn(b'for (int32_t s0 = 0; s0 < 1048576; ++s0)', compiled.artifact.c_source)
        with self.assertRaises(DiagnosticError):
            compile_wasm_source(source)

    def test_native_c_matches_the_reference(self):
        harness = Path(__file__).parent / 'fixtures' / 'scale_harness.c'
        for source in (BOX.format(h=40, w=37).encode(), MATMUL.format(n=20).encode(), SUM.format(n=4000).encode()):
            kernel = admit_source(parse_source(source))
            artifact = compile_scale_native(source).artifact
            with tempfile.TemporaryDirectory() as tmp:
                c = Path(tmp) / 'k.c'
                c.write_bytes(artifact.c_source.replace(b'int main(void)', b'int beryl_unused_main(void)'))
                exe = Path(tmp) / 'k.exe'
                try:
                    subprocess.run(['clang', '-O2', '-std=c11', str(c), str(harness), '-o', str(exe)],
                                   check=True, capture_output=True)
                except (OSError, subprocess.CalledProcessError) as error:
                    self.skipTest(f'no working C toolchain: {error}')
                for bad in (None, kernel.input_count - 1):
                    data = data_for(kernel.input_count)
                    if bad is not None:
                        data[bad] = 5000
                    try:
                        ran = subprocess.run([str(exe), str(kernel.input_count), str(kernel.output_count)],
                                             input=' '.join(map(str, data)), capture_output=True, text=True, check=True)
                    except OSError as error:  # Windows Application Control; never bypassed
                        self.skipTest(f'executable launch refused: {error}')
                    status, *values = map(int, ran.stdout.split())
                    ref = evaluate_source(kernel.source_module, data, [-9] * kernel.output_count)
                    self.assertEqual(status, 0 if ref.first_bad_index is None else ref.first_bad_index + 1)
                    self.assertEqual(tuple(values), ref.output)


if __name__ == '__main__':
    unittest.main()
