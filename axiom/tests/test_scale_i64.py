"""i64 equations in scale-v1: 64-bit values proved per node, emitted as int64_t."""
import dataclasses
from pathlib import Path
import random
import subprocess
import tempfile
import unittest

from axiom.frontend import admit_source, parse_source
from axiom.model import DiagnosticError
from axiom.reference import evaluate_source
from axiom.scale_c import compile_scale_native
from axiom.scale_carry import plan_costs, window_rows
from axiom.scale_checker import check_loop_plan
from axiom.scale_plan import LoopPlan, Stage, make_scale_plan
from axiom.scale_runtime import execute_loop_plan
from tests.test_scale_family import BOX, MATMUL, SUM
from tests.test_scale_oracle import _mutate


def wide(text, producer='i64', output='i64'):
    """The program with typed equations (`let t: i64[...]`)."""
    lines = []
    for line in text.splitlines(keepends=True):
        for keyword, element in (('let ', producer), ('output ', output)):
            if line.startswith(keyword) and element:
                name, rest = line[len(keyword):].split('[', 1)
                line = f'{keyword}{name}: {element}[{rest}'
        lines.append(line)
    return ''.join(lines).encode()


DOT = '''module dot;
shape H = 1;
shape W = 1;
input x: i32[1,{n}] in 0..=1023;
input y: i32[1,{n}] in 0..=1023;
let t[r in 0..H,c in 0..W] = sum(k in 0..{n}: x[0,k]*y[0,k]);
output d[r in 0..H,c in 0..W] = t[r,c];
'''
# An i32 producer read by an i64 output: each row sum fits i32, its square does not.
MIXED = '''module mixed;
shape H = 4;
shape W = 1;
input x: i32[H,3000] in 0..=1023;
let p[r in 0..H,c in 0..W] = sum(k in 0..3000: x[r,k]);
output s[r in 0..H,c in 0..W] = p[r,c]*p[r,c]+p[r,c];
'''
# No sum at all: x^4 reaches 1023^4, past i32.
QUARTIC = '''module quartic;
shape H = 1;
shape W = {n};
input x: i32[H,W] in 0..=1023;
let t[r in 0..H,c in 0..W] = (x[r,c]*x[r,c])*(x[r,c]*x[r,c]);
output y[r in 0..H,c in 0..W] = t[r,c];
'''
SQUARES = SUM.replace('x[0,k])', 'x[0,k]*x[0,k])')  # 3000 * 1023^2 > 2^31


def data_for(n, seed=0, top=False):
    rng = random.Random(seed)
    return [1023] * n if top else [rng.randrange(1024) for _ in range(n)]


class I64AdmissionTests(unittest.TestCase):
    def test_types_parse_and_default_to_i32(self):
        module = parse_source(wide(SUM.format(n=5000), 'i64', None))
        self.assertEqual((module.producers[0].element_type, module.outputs[0].element_type), ('i64', 'i32'))
        with self.assertRaises(DiagnosticError) as caught:
            admit_source(parse_source(wide(SUM.format(n=5000), 'u8', None)))
        self.assertEqual(caught.exception.code, 'UNSUPPORTED_TYPE')

    def test_i32_identities_are_unchanged(self):
        # Writing `: i32` is the same program as writing nothing, in every family.
        for text in (SUM.format(n=200), SUM.format(n=5000), BOX.format(h=4, w=4), BOX.format(h=60, w=50)):
            plain, typed = (admit_source(parse_source(s)) for s in (text.encode(), wide(text, 'i32', 'i32')))
            with self.subTest(text=text[:40]):
                self.assertEqual((plain.profile, plain.semantic_digest, plain.semantics_version),
                                 (typed.profile, typed.semantic_digest, typed.semantics_version))
                self.assertFalse(typed.wide)

    def test_i64_programs_are_scale_v1_with_their_own_identity(self):
        narrow = admit_source(parse_source(SUM.format(n=5000).encode()))
        for text in (SUM.format(n=200), SUM.format(n=5000), BOX.format(h=4, w=4)):
            kernel = admit_source(parse_source(wide(text)))
            with self.subTest(text=text[:40]):
                self.assertEqual((kernel.profile, kernel.semantics_version), ('scale-v1', 'scale-i64-v1'))
                self.assertTrue(kernel.wide)
        mixed = admit_source(parse_source(wide(SUM.format(n=5000), None, 'i64')))
        self.assertNotEqual(mixed.semantic_digest, narrow.semantic_digest)
        self.assertNotEqual(mixed.semantic_digest, admit_source(parse_source(wide(SUM.format(n=5000)))).semantic_digest)

    def test_i64_outside_scale_v1_is_refused(self):
        text = BOX.format(h=4, w=4).replace('output o[r in 0..H,c in 0..W] = (p[r,c]+p[r+1,c])+p[r+2,c];',
                                            'output o[r in 0..H,c in 0..W] = p[r,c]+x[r,c];')
        with self.assertRaises(DiagnosticError) as caught:
            admit_source(parse_source(wide(text)))
        self.assertEqual(caught.exception.code, 'UNSUPPORTED_PROFILE')
        self.assertIn('i64 equations', caught.exception.message)

    def test_boundary_follows_the_output_type(self):
        source = wide(SUM.format(n=300))
        kernel = admit_source(parse_source(source))
        data = data_for(kernel.input_count)
        initial = [1 << 40]
        self.assertEqual(evaluate_source(kernel.source_module, data, initial).output, (sum(data),))
        plan = make_scale_plan(kernel)
        self.assertEqual(execute_loop_plan(source, plan, data, initial).output, (sum(data),))
        with self.assertRaises(DiagnosticError) as caught:
            evaluate_source(parse_source(SUM.format(n=300).encode()), data, initial)
        self.assertEqual(caught.exception.code, 'BOUNDARY_I32')


class I64ProofTests(unittest.TestCase):
    def test_sums_too_large_for_i32_are_proved_in_i64(self):
        refused = compile_scale_native(SQUARES.format(n=3000).encode())
        self.assertEqual(refused.reason, 'ARITHMETIC_OVERFLOW')
        self.assertIn('declare the equation i64', refused.check.detail)
        for source in (wide(SQUARES.format(n=3000)), wide(SUM.format(n=1 << 23)), wide(DOT.format(n=1 << 21)),
                       wide(MIXED, None, 'i64'), wide(QUARTIC.format(n=5000))):
            with self.subTest(source=source[:30]):
                self.assertEqual(compile_scale_native(source).reason, 'VALID')

    def test_every_node_is_bounded_by_its_own_type(self):
        cases = {
            # An i64 producer read where the output's i32 value is required.
            'narrowing read': (wide(SQUARES.format(n=3000), 'i64', None), "the read of 't'"),
            # The squares are i32 nodes of the producer; their sum is i64.
            'i32 node inside': (wide(MIXED.replace('x[r,k])', 'x[r,k]*x[r,k])'), None, 'i64'), 'terms fit in i32'),
            'past i64': (wide(SUM.format(n=3000).replace('x[0,k])', '((x[0,k]*x[0,k])*(x[0,k]*x[0,k]))*((x[0,k]*x[0,k])*(x[0,k]*x[0,k])))')),
                         'outside i64'),
            'sum past i64': (wide(SUM.format(n=3000).replace('x[0,k])', '((x[0,k]*x[0,k])*(x[0,k]*x[0,k]))*(x[0,k]*x[0,k]))')),
                             'terms fit in i64'),
        }
        for label, (source, detail) in cases.items():
            with self.subTest(case=label):
                result = compile_scale_native(source)
                self.assertEqual(result.reason, 'ARITHMETIC_OVERFLOW', result.check and result.check.detail)
                self.assertIn(detail, result.check.detail)
        # A narrowing read that provably fits is accepted.
        self.assertEqual(compile_scale_native(wide(SUM.format(n=5000), 'i64', None)).reason, 'VALID')

    def test_the_reference_agrees_with_the_refusals(self):
        source = wide(SQUARES.format(n=3000), 'i64', None)
        kernel = admit_source(parse_source(source))
        with self.assertRaises(DiagnosticError) as caught:
            evaluate_source(kernel.source_module, data_for(kernel.input_count, top=True), [0])
        self.assertEqual(caught.exception.code, 'EVALUATION_I32')

    def test_plans_match_the_reference(self):
        sources = [wide(SQUARES.format(n=3000)), wide(DOT.format(n=1500)), wide(MATMUL.format(n=24)),
                   wide(MIXED, None, 'i64'), wide(BOX.format(h=30, w=25)), wide(QUARTIC.format(n=900))]
        for source in sources:
            kernel = admit_source(parse_source(source))
            for plan_id in ('direct-v1', 'carry-v1'):
                try:
                    plan = make_scale_plan(kernel, plan_id)
                except Exception:
                    continue  # carry-v1 needs a windowed producer read
                if not check_loop_plan(source, plan).valid:
                    continue
                for top, bad in ((False, None), (True, None), (False, kernel.input_count - 1)):
                    data = data_for(kernel.input_count, top=top)
                    if bad is not None:
                        data[bad] = 1024
                    initial = [-9] * kernel.output_count
                    with self.subTest(module=source.split(b';')[0], plan=plan_id, top=top, bad=bad):
                        self.assertEqual(execute_loop_plan(source, plan, data, initial),
                                         evaluate_source(kernel.source_module, data, initial))

    def test_carry_ring_is_counted_in_eight_byte_cells(self):
        source = wide(BOX.format(h=60, w=50))
        kernel = admit_source(parse_source(source))
        carry = make_scale_plan(kernel, 'carry-v1')
        self.assertEqual(plan_costs(carry, kernel)[2], 8 * window_rows(carry.stages[-1].value) * 50)
        self.assertEqual(compile_scale_native(source).plan.plan_id, 'carry-v1')

    def test_accepted_mutants_compute_the_reference(self):
        rng = random.Random(64)
        rejected = 0
        for source in (wide(SQUARES.format(n=2000)), wide(DOT.format(n=600)), wide(MIXED, None, 'i64')):
            kernel = admit_source(parse_source(source))
            plan = make_scale_plan(kernel)
            stage = plan.stages[0]
            for _ in range(60):
                mutant = LoopPlan(plan.semantic_digest, plan.plan_id,
                                  (Stage(stage.loops, stage.index, _mutate(stage.value, rng)),))
                if not check_loop_plan(source, mutant).valid:
                    rejected += 1
                    continue
                for top in (False, True):
                    data = data_for(kernel.input_count, top=top)
                    initial = [-9] * kernel.output_count
                    self.assertEqual(execute_loop_plan(source, mutant, data, initial),
                                     evaluate_source(kernel.source_module, data, initial))
        self.assertGreater(rejected, 120)


class I64NativeTests(unittest.TestCase):
    def test_emitted_c_is_int64(self):
        artifact = compile_scale_native(wide(SUM.format(n=1 << 20))).artifact
        self.assertEqual(artifact.codegen_version, 'beryl-loop-c-parallel-v1')
        for text in (b'static int64_t beryl_partial(', b'static int64_t beryl_job_partial',
                     b'int32_t beryl_kernel(const int32_t *restrict input, int64_t *restrict output)',
                     b'static int beryl_put_i64(int64_t value)'):
            self.assertIn(text, artifact.c_source)
        self.assertNotIn(b'beryl_put_i32(', artifact.c_source)
        # The streaming copy moves int32_t cells; i64 outputs keep ordinary stores.
        self.assertNotIn(b'beryl_stream', compile_scale_native(wide(QUARTIC.format(n=1 << 22))).artifact.c_source)

    def test_native_c_matches_the_reference(self):
        harness = Path(__file__).parent / 'fixtures' / 'scale_harness.c'
        sources = [wide(SUM.format(n=1 << 17)), wide(DOT.format(n=40000)), wide(MATMUL.format(n=40)),
                   wide(MIXED, None, 'i64'), wide(BOX.format(h=40, w=37)), wide(BOX.format(h=50, w=41), None, 'i64'),
                   wide(BOX.format(h=120, w=100)),
                   wide(QUARTIC.format(n=70000)),
                   wide(SUM.format(n=5000), 'i64', None)]
        with tempfile.TemporaryDirectory() as tmp:
            for number, source in enumerate(sources):
                kernel = admit_source(parse_source(source))
                artifact = compile_scale_native(source).artifact
                c = Path(tmp) / f'k{number}.c'
                c.write_bytes(artifact.c_source.replace(b'int main(void)', b'int beryl_unused_main(void)'))
                exe = Path(tmp) / f'k{number}.exe'
                out = 'int64_t' if kernel.output_type == 'i64' else 'int32_t'
                try:
                    subprocess.run(['clang', '-O2', '-std=c11', f'-DBERYL_OUT={out}', str(c), str(harness),
                                    '-o', str(exe)], check=True, capture_output=True)
                except (OSError, subprocess.CalledProcessError) as error:
                    self.skipTest(f'no working C toolchain: {error}')
                for top, bad in ((True, None), (False, None), (False, kernel.input_count - 1)):
                    data = data_for(kernel.input_count, number, top)
                    if bad is not None:
                        data[bad] = 5000
                    try:
                        ran = subprocess.run([str(exe), str(kernel.input_count), str(kernel.output_count)],
                                             input=' '.join(map(str, data)), capture_output=True, text=True, check=True)
                    except OSError as error:  # Windows Application Control; never bypassed
                        self.skipTest(f'executable launch refused: {error}')
                    status, *values = map(int, ran.stdout.split())
                    ref = evaluate_source(kernel.source_module, data, [-9] * kernel.output_count)
                    with self.subTest(module=source.split(b';')[0], top=top, bad=bad):
                        self.assertEqual(status, 0 if ref.first_bad_index is None else ref.first_bad_index + 1)
                        self.assertEqual(tuple(values), ref.output)


if __name__ == '__main__':
    unittest.main()
