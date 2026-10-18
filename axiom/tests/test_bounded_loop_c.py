"""Compact C observations are checked against two independent interpreters."""
import ctypes
from dataclasses import replace
from hashlib import sha256
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from axiom.bounded_loop_codec import encode_loop_program
from axiom.bounded_loop_model import HintError, HintLimits, IndexExpr, IndexTerm, Loop, Primitive
from axiom.bounded_loop_planner import make_loop_program
from axiom.compilation import _CompilationContext
from axiom.native_codegen import _emit_native_c_checked, emit_native_c
from axiom.planner import PLAN_IDS, make_plan
from axiom.plan_format import Operation
from axiom.reference import evaluate_source
from axiom.frontend import parse_source
from axiom.runtime import _execute_checked
from tests.helpers import stencil_source


class CompactCTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = os.environ.get('AXIOM_TEST_NATIVE_CLANG') or shutil.which('clang')
        if not cls.compiler:
            raise unittest.SkipTest('compact C execution requires Clang')

    def setUp(self):
        self.backend = importlib.import_module('axiom.bounded_loop_c')
        self.temporary = tempfile.TemporaryDirectory(prefix='beryl-compact-c-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.serial = 0

    def owned(self, h=2, w=3, schedule='rows2-v1', transform=None):
        context = _CompilationContext(stencil_source(h, w, None))
        self.addCleanup(context.close)
        plan = make_plan(context.kernel, schedule)
        if transform:
            plan = transform(plan)
        candidate = context.candidate(plan)
        owned = context.authorize(candidate, context.check(candidate))
        hint = encode_loop_program(make_loop_program(context.kernel, schedule))
        return owned, hint

    def build(self, artifact, shared=True, source=None):
        self.assertEqual(artifact.c_digest, sha256(artifact.c_source).hexdigest())
        self.serial += 1
        path = self.root / f'kernel{self.serial}.c'
        path.write_bytes(artifact.c_source if source is None else source)
        binary = path.with_suffix('.so' if shared else '.exe')
        flags = ['-shared', '-fPIC'] if shared else []
        built = subprocess.run([self.compiler, '-std=c11', '-O3', '-Wall', '-Wextra',
                                '-Werror', *flags, str(path), '-o', str(binary)],
                               capture_output=True, text=True, timeout=60)
        self.assertEqual(built.returncode, 0, built.stderr)
        if not shared:
            return binary
        library = ctypes.CDLL(str(binary))
        library.beryl_kernel.argtypes = [ctypes.POINTER(ctypes.c_int32)] * 2
        library.beryl_kernel.restype = ctypes.c_int32
        return library

    def invoke(self, library, data, initial):
        # Independent arenas include canaries on both sides of each owned view.
        guard = -19088743
        inputs = (ctypes.c_int32 * (len(data)+2))(guard, *data, guard)
        output = (ctypes.c_int32 * (len(initial)+2))(guard, *initial, guard)
        pointer = ctypes.POINTER(ctypes.c_int32)
        status = library.beryl_kernel(ctypes.cast(ctypes.byref(inputs, 4), pointer),
                                      ctypes.cast(ctypes.byref(output, 4), pointer))
        self.assertEqual((inputs[0], inputs[-1], output[0], output[-1]), (guard,)*4)
        return status, tuple(inputs)[1:-1], tuple(output)[1:-1]

    def observation(self, owned, data, initial):
        ast = evaluate_source(parse_source(owned.source), data, initial)
        finite = _execute_checked(owned, data, initial)
        self.assertEqual(ast, finite)
        status = 0 if finite.first_bad_index is None else finite.first_bad_index + 1
        return status, finite.input_after, finite.output

    def llvm_ir(self, artifact, optimization='-O0'):
        self.serial += 1
        source = self.root / f'contract{self.serial}.c'
        source.write_bytes(artifact.c_source)
        # O0 makes these frontend parameter contracts, not inferred O3 facts.
        compiled = subprocess.run(
            [self.compiler, '-std=c11', optimization, '-S', '-emit-llvm',
             str(source), '-o', '-'], capture_output=True, text=True, timeout=60)
        self.assertEqual(compiled.returncode, 0, compiled.stderr)
        return compiled.stdout

    def test_compact_disjoint_parameters_have_llvm_noalias_contract(self):
        for schedule in PLAN_IDS:
            with self.subTest(schedule=schedule):
                owned, hint = self.owned(schedule=schedule)
                compact = self.backend._emit_native_c_compact(owned, hint)
                finite = emit_native_c(owned.source, owned.plan_bytes)
                for artifact, expected in ((finite, False), (compact, True)):
                    ir = self.llvm_ir(artifact)
                    definition = re.search(
                        r'^define\b[^\n]*@beryl_kernel\(([^)]*)\)', ir, re.MULTILINE)
                    self.assertIsNotNone(definition, ir)
                    parameters = definition.group(1).split(',')
                    self.assertEqual(len(parameters), 2)
                    for index, parameter in enumerate(parameters):
                        self.assertEqual(bool(re.search(r'\bnoalias\b', parameter)),
                                         expected, (schedule, index, parameter))

    def test_public_finite_bytes_remain_stable_for_all_schedules(self):
        digests = {
            'inline-v1': '592f4da51fa1ce2bcd365c89992f2c7adfeaa8b5fa7ed5b83d90566edae00b07',
            'rows2-v1': '164542d739eca49bbccd586a42a0a3ad64ac81df91947c4c6a52c6b5564d49a6',
            'materialize-v1': 'f10df14be14edc955ee6357edcdd52877d17639e62aace1972dbf6fe074a687c',
        }
        for schedule in PLAN_IDS:
            with self.subTest(schedule=schedule):
                owned, hint = self.owned(schedule=schedule)
                before = emit_native_c(owned.source, owned.plan_bytes)
                self.backend._emit_native_c_compact(owned, hint)
                after = emit_native_c(owned.source, owned.plan_bytes)
                self.assertEqual(before.c_digest, digests[schedule])
                self.assertEqual(before.c_source, after.c_source)
                self.assertEqual(_emit_native_c_checked(owned).c_source, before.c_source)

    def test_valid_preflight_has_an_optimized_vector_reduction(self):
        owned, hint = self.owned(15, 15)
        compact = self.backend._emit_native_c_compact(owned, hint)
        ir = self.llvm_ir(compact, '-O3')
        kernel = re.search(r'^define\b[^\n]*@beryl_kernel\([^\n]*\{\n(.*?)^}',
                           ir, re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(kernel, ir)
        # The valid-input check must reduce lane predicates, not branch once
        # per scalar cell. A missing reduction cannot hide in the I/O driver.
        self.assertRegex(kernel.group(1), r'@llvm\.vector\.reduce\.or\.')
        self.assertRegex(kernel.group(1), r'icmp \w+ <\d+ x i32>')

    def test_rejection_preserves_full_buffers_across_vector_lanes_and_reuse(self):
        for schedule in PLAN_IDS:
            with self.subTest(schedule=schedule):
                owned, hint = self.owned(3, 4, schedule)
                artifact = self.backend._emit_native_c_compact(owned, hint)
                library = self.build(artifact)
                n, m = artifact.input_count, artifact.output_count
                initial = tuple(-2147483648 + i*7919 for i in range(m))
                valid = tuple((i*277+41)%1024 for i in range(n))
                for first in range(n):
                    for invalid in (-2147483648, -1, 1024, 2147483647):
                        data = list(valid)
                        # Two invalid values must still report the first one;
                        # every lane, including the final partial group, occurs.
                        data[-1] = 2147483647
                        data[first] = invalid
                        expected = (first+1, tuple(data), initial)
                        self.assertEqual(self.observation(owned, data, initial), expected)
                        self.assertEqual(self.invoke(library, data, initial), expected)
                    # Reusing the same compiled kernel after rejection must not
                    # retain either invalid predicates or scratch state.
                    self.assertEqual(self.invoke(library, valid, initial),
                                     self.observation(owned, valid, initial))

    def test_boundaries_all_schedules_repeated_inputs_and_scratch_poison(self):
        for shape in ((1, 1), (1, 127), (127, 1), (3, 4), (15, 15)):
            for schedule in PLAN_IDS:
                with self.subTest(shape=shape, schedule=schedule):
                    owned, hint = self.owned(*shape, schedule)
                    artifact = self.backend._emit_native_c_compact(owned, hint)
                    source = artifact.c_source
                    capacity = owned.plan.scratch_capacity_cells
                    if capacity:
                        # Every reached scratch load must follow its defining store.
                        declaration = f'int32_t scratch[{capacity}] = {{0}};'.encode()
                        poisoned = (f'struct {{ int32_t before; int32_t cells[{capacity}]; int32_t after; }} '
                                    f'ax_guard = {{-19088743, {{0}}, -19088743}};\n'
                                    f'    int32_t *scratch = ax_guard.cells;\n'
                                    f'    for (int32_t ax_p = 0; ax_p < {capacity}; ++ax_p) scratch[ax_p] = INT32_MIN;').encode()
                        self.assertIn(declaration, source)
                        source = source.replace(declaration, poisoned).replace(
                            b'    return 0;\n}',
                            b'    if (ax_guard.before != -19088743 || ax_guard.after != -19088743) return -1;\n    return 0;\n}', 1)
                    library = self.build(artifact, source=source)
                    n, m = artifact.input_count, artifact.output_count
                    initial = tuple(-2147483648 if i % 2 else 2147483647 for i in range(m))
                    for data in ((0,)*n, (1023,)*n, tuple(range(n)),
                                 tuple((i*277+41)%1024 for i in range(n)), (1,)*n):
                        self.assertEqual(self.invoke(library, data, initial),
                                         self.observation(owned, data, initial))
                    for first in (0, n//2, n-1):
                        data = [0]*n
                        data[first] = -1
                        data[-1] = 1024
                        self.assertEqual(self.invoke(library, data, initial),
                                         self.observation(owned, data, initial))

    def test_exact_metadata_labels_and_receipts_are_not_authority(self):
        owned, hint = self.owned(transform=lambda p: replace(p, plan_id='arbitrary name'))
        program = replace(make_loop_program(owned.kernel, 'rows2-v1'), label='unrelated label')
        hint = encode_loop_program(program)
        artifact = self.backend._emit_native_c_compact(owned, hint)
        spaced = self.backend._emit_native_c_compact(owned, b' '+hint+b'\n')
        self.assertEqual(artifact.plan_digest, sha256(owned.plan_bytes).hexdigest())
        self.assertEqual(artifact.source_digest, sha256(owned.source).hexdigest())
        self.assertEqual(artifact.hint_digest, sha256(hint).hexdigest())
        self.assertNotEqual(artifact.hint_digest, spaced.hint_digest)
        self.assertEqual(artifact.c_source, spaced.c_source)
        self.assertEqual(artifact.codegen_version, 'beryl-bounded-loop-c-v1')
        self.assertEqual(artifact.loop_version, 'beryl-bounded-correspondence-v1')
        with self.assertRaises(ValueError):
            self.backend._emit_native_c_compact(replace(owned), hint)
        other, other_hint = self.owned(2, 3, 'inline-v1')
        with self.assertRaises(HintError):
            self.backend._emit_native_c_compact(other, hint)
        with self.assertRaises(ValueError):
            self.backend._emit_native_c_compact(replace(owned, owner=other.owner), other_hint)
        with self.assertRaises(HintError):
            self.backend._emit_native_c_compact(owned, hint, hint_limits=HintLimits(encoded_bytes=32))
        from axiom.bounded_loop_correspondence import _validate_owned_loop_correspondence
        with patch('axiom.bounded_loop_correspondence._validate_owned_loop_correspondence',
                   wraps=_validate_owned_loop_correspondence) as validate:
            self.backend._emit_native_c_compact(owned, hint)
            self.backend._emit_native_c_compact(owned, hint)
            self.assertEqual(validate.call_count, 2)
        owned.owner.close()
        with self.assertRaises(ValueError):
            self.backend._emit_native_c_compact(owned, hint)

    def test_negative_parity_and_checked_index_intermediates(self):
        owned, _ = self.owned(3, 4)
        program = make_loop_program(owned.kernel, 'rows2-v1')
        def parity(nodes):
            return tuple(replace(n, body=parity(n.body)) if type(n) is Loop else
                         replace(n, index=replace(n.index, terms=tuple(
                             replace(t, offset=t.offset-2) if t.modulo2 else t
                             for t in n.index.terms))) if n.index is not None else n
                         for n in nodes)
        hint = encode_loop_program(replace(program, body=parity(program.body)))
        artifact = self.backend._emit_native_c_compact(owned, hint)
        self.assertIn(b'uint32_t', artifact.c_source)
        library = self.build(artifact)
        data = tuple((i*37)%1024 for i in range(20))
        self.assertEqual(self.invoke(library, data, (-7,)*12), self.observation(owned, data, (-7,)*12))
        for body in ((Loop('r', 0, 1, (Primitive('input_load', 'x', index=IndexExpr(
                         2147483647, (IndexTerm(1, 'r', 1), IndexTerm(-1, 'r', 1)))),)),),
                     (Loop('r', 0, 1, (Primitive('input_load', 'x', index=IndexExpr(
                         0, (IndexTerm(2147483647, 'r', 2),))),)),)):
            with self.assertRaisesRegex(HintError, 'HINT_INDEX_OVERFLOW'):
                self.backend._emit_native_c_compact(owned, encode_loop_program(replace(program, body=body)))
        for bad in (b'{}', b'\xff', bytearray(hint), hint+b' x', b'['*1000):
            with self.assertRaises(HintError):
                self.backend._emit_native_c_compact(owned, bad)

    def test_arbitrary_checked_dead_primitives_are_lowered_in_order(self):
        def extend(plan):
            dst = max(op.dst for op in plan.operations if op.dst is not None)+1
            return replace(plan, plan_id='arbitrary extended stream', operations=plan.operations+(
                Operation('const', dst, (), None, 2147483647, ()),
                Operation('const', dst+1, (), None, -2147483648, ()),
                Operation('add', dst+2, (dst, dst+1), None, None, ()),
                Operation('mul', dst+3, (dst+2, dst), None, None, ())))
        owned, _ = self.owned(transform=extend)
        program = make_loop_program(owned.kernel, 'rows2-v1')
        extra = (Primitive('const', 'maximum', value=2147483647),
                 Primitive('const', 'minimum', value=-2147483648),
                 Primitive('add', 'dead_sum', ('maximum', 'minimum')),
                 Primitive('mul', 'dead_product', ('dead_sum', 'maximum')))
        hint = encode_loop_program(replace(program, body=program.body+extra))
        artifact = self.backend._emit_native_c_compact(owned, hint)
        self.assertIn(b'2147483647LL', artifact.c_source)
        self.assertIn(b'-2147483648LL', artifact.c_source)
        self.assertLess(artifact.c_source.index(b'ax_v_dead_sum ='),
                        artifact.c_source.index(b'ax_v_dead_product ='))
        library = self.build(artifact)
        data = tuple(range(12))
        self.assertEqual(self.invoke(library, data, (-7,)*6),
                         self.observation(owned, data, (-7,)*6))
        # The original built-in hint omits dead primitives and must not match.
        with self.assertRaises(HintError):
            self.backend._emit_native_c_compact(owned, encode_loop_program(program))

    def test_zero_trip_loops_with_unreachable_arena_operations_compile(self):
        owned, base_hint = self.owned(schedule='inline-v1')
        self.assertEqual(owned.plan.scratch_capacity_cells, 0)
        program = make_loop_program(owned.kernel, 'inline-v1')
        baseline = self.backend._emit_native_c_compact(owned, base_hint)
        # Syntax is validated even when no iteration reaches an index. These
        # unreachable operations reserve no scratch and expand to no finite ops.
        # Their indices would be negative, out of bounds or overflow if reached.
        unreachable = (
            Primitive('input_load', 'never_input', index=IndexExpr(2147483647)),
            Primitive('scratch_load', 'never_scratch', index=IndexExpr(0)),
            Primitive('scratch_store', operands=('one',), index=IndexExpr(0)),
            Primitive('output_store', operands=('one',), index=IndexExpr(-1)),
            Loop('nested', 0, 1, (Primitive('scratch_store', operands=('one',),
                 index=IndexExpr(2147483647, (IndexTerm(1, 'nested', 1),))),)))
        data, initial = tuple(range(12)), (-2147483648,)*6
        for bound in (0, 256):
            with self.subTest(bound=bound):
                extra = Loop('never', bound, bound, unreachable)
                hint = encode_loop_program(replace(program, body=program.body+(extra,)))
                artifact = self.backend._emit_native_c_compact(owned, hint)
                # Real strict compilation detects undeclared zero-capacity
                # arenas even when the C optimizer could eliminate the body.
                library = self.build(artifact)
                self.assertEqual(self.invoke(library, data, initial),
                                 self.observation(owned, data, initial))
                invalid = (-1,)+data[1:]
                self.assertEqual(self.invoke(library, invalid, initial),
                                 self.observation(owned, invalid, initial))
                self.assertEqual(artifact.c_source, baseline.c_source)
                self.assertEqual(artifact.source_digest, baseline.source_digest)
                self.assertEqual(artifact.plan_digest, baseline.plan_digest)
                self.assertEqual(artifact.hint_digest, sha256(hint).hexdigest())
                self.assertNotEqual(artifact.hint_digest, baseline.hint_digest)
        # Skipping emission cannot skip fresh syntax validation of dead bodies.
        malformed = json.loads(hint)
        malformed['body'][-1]['body'][2]['operands'] = ['missing']
        with self.assertRaises(HintError):
            self.backend._emit_native_c_compact(owned, json.dumps(malformed).encode())

    def test_trace_records_fresh_correspondence_and_code_emission(self):
        from axiom.compilation_trace import CompilationTrace
        owned, hint = self.owned()
        trace = CompilationTrace()
        owned.owner.trace = trace
        for _ in range(2):
            self.backend._emit_native_c_compact(owned, hint)
        report = trace.report()
        self.assertEqual(report['phases']['loop_correspondence']['calls'], 2)
        self.assertEqual(report['phases']['code_emission']['calls'], 2)
        self.assertEqual(report['counts']['loop_correspondences'], 2)
        self.assertEqual(report['counts']['code_emissions'], 2)
        self.assertGreater(report['counts']['loop_correspondence_work'], 0)

    def test_source_reduction_at_15_by_15(self):
        for schedule in PLAN_IDS:
            owned, hint = self.owned(15, 15, schedule)
            compact = self.backend._emit_native_c_compact(owned, hint)
            finite = _emit_native_c_checked(owned)
            self.assertGreaterEqual(len(finite.c_source)/len(compact.c_source), 10)

    def test_driver_exact_dimensions_and_malformed_tokens(self):
        owned, hint = self.owned(1, 2)
        binary = self.build(self.backend._emit_native_c_compact(owned, hint), shared=False)
        good = '1 2 0 1 2 3 4 5'
        result = subprocess.run([binary], input=good, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), list(self.observation(owned, tuple(range(6)), (-1, -1))[2]))
        for payload in ('', '1', '2 1 0 1 2 3 4 5', good+' 6', good[:-2],
                        '1 2 0 1 2 3 4 1024', '1 2 0 1 2 3 4 -1',
                        '1 2 0 1 2 3 4 2147483648', '1 2 0 1 2 3 4 -2147483649',
                        '1 2 0 1 2 3 4 9223372036854775808',
                        '1 2 0 1 2 3 4 0x1', '1 2 0 1 2 3 4 +',
                        '1 2 0 1 2 3 4 1.0', '1 2 0 1 2 3 4 0\x00suffix',
                        '1 2 '+'0'*70+' 0 0 0 0 0'):
            with self.subTest(payload=payload):
                result = subprocess.run([binary], input=payload, capture_output=True, text=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')

    def test_rehashed_faulty_emitters_are_caught_by_observations(self):
        owned, hint = self.owned(3, 4)
        artifact = self.backend._emit_native_c_compact(owned, hint)
        text = artifact.c_source.decode()
        store = next(line for line in text.splitlines() if 'output[' in line and '= ax_v_' in line)
        omitted = text.replace(store, '    /* deliberately omitted store */', 1)
        changed = text.replace(store, store[:store.index('output[')]+'output[0]'+store[store.index(']')+1:], 1)
        # In rows2's rolling loop, swapping consume/refill overwrites a live row.
        start = text.index('    for (int32_t ax_i_r')
        first = text.index('        for (int32_t ax_i_c', start)
        second = text.index('        for (int32_t ax_i_c', first+1)
        end = text.index('\n    }', second)
        early = text[:first]+text[second:end]+text[first:second]+text[end:]
        data = tuple((i*71+3)%1024 for i in range(20))
        initial = (-2147483648,)*12
        expected = self.observation(owned, data, initial)
        for faulty in (omitted, changed, early):
            raw = faulty.encode()
            rehashed = replace(artifact, c_source=raw, c_digest=sha256(raw).hexdigest())
            library = self.build(rehashed)
            self.assertNotEqual(self.invoke(library, data, initial), expected)


if __name__ == '__main__':
    unittest.main()
