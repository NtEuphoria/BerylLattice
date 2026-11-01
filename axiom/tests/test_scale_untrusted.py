"""Untrusted plan strings never reach the emitted C.

A candidate plan (scale_candidates.load_plan) carries strings the checker has
no reason to trust: its plan_id label and its variable names. The checker
proves a plan up to the names of its variables, so a proved plan may still
name them anything. The emitter must not paste any of those strings into C: a
plan_id could close the header comment, and a variable name could be C code,
a keyword or one of the emitter's own identifiers (acc, input, from, ax_s0...).
Every plan below is proved by the checker, and its C must be the C of the
planner's own plan, byte for byte (the header names only a trusted plan ID).
"""
from hashlib import sha256
import dataclasses
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from axiom.frontend import admit_source, parse_source
from axiom.reference import evaluate_source
from axiom.scale_c import emit_scale_c
from axiom.scale_candidates import load_plan, review_candidates
from axiom.scale_checker import check_loop_plan
from axiom.scale_plan import LoopPlan, Stage, make_scale_plan, plan_json
from tests.test_scale_contract import fused
from tests.test_scale_family import BOX, MATMUL, ROWSUM, SUM, TRANSPOSE, data_for
from tests.test_scale_i64 import DOT, MIXED, wide

CC = os.environ.get('CC', 'clang')
MARK = 'beryl_injected'
INJECTED = f'*/ int {MARK} = 1; /*\n#define beryl_kernel {MARK}_kernel\n/* '
# C code, keywords, emitter identifiers, and strings that are no identifier at all.
HOSTILE = (f'r) {{ }} int {MARK} = (1', 'int', 'while', 'return', 'acc', 'input', 'output', 'from', 'to',
           'first', 'last', 'at', 'ax_s0', 'ax_s0_b', 'ax_u0', 'ax_v', 'ax_b', 'ax_k', 'ax_e', 'ax_rb', 'ax_p',
           'ax_row0', 'ax_out', 'ax_invalid', 'beryl_kernel', 'beryl_partial', 'beryl_cells', 'stack', 'block',
           'start', 'end', 'ring', 'dst', 'total', 'threads', 'o', 'e', 's', 't', 'u', 'i', 'c', 'k', 'n', 'r',
           'p', 'q', 's0', 's1', 'in0', 'bad', 'BERYL_WIDTH', 'main', 'int32_t', '', '1x', 'a b', '/*', '*/',
           '#define', 'x\n#include <stdio.h>', '\u00e9', '\x00', 'x;' * 40)
TWIN = '''module twin;
shape H = 1;
shape W = 1;
input x: i32[1,{n}] in 0..=1023;
let t[r in 0..H,c in 0..W] = sum(k in 0..{h}: x[0,k]) + sum(k in 1..{n}: x[0,k]);
output s[r in 0..H,c in 0..W] = t[r,c];
'''
# (source, plan_id, abi): direct, carry, split and fused sums, row accumulation,
# tiles, the fused contract, i64 and ABI 2.
PROGRAMS = (
    (SUM.format(n=2000).encode(), 'direct-v1', None),
    (SUM.format(n=1 << 17).encode(), 'direct-v1', None),
    (wide(DOT.format(n=1 << 16)), 'direct-v1', None),
    (MATMUL.format(n=16).encode(), 'direct-v1', None),
    (TRANSPOSE.encode(), 'direct-v1', None),
    (ROWSUM.encode(), 'direct-v1', 2),
    (BOX.format(h=30, w=25).encode(), 'direct-v1', None),
    (BOX.format(h=30, w=25).encode(), 'carry-v1', None),
    (fused(BOX.format(h=300, w=250)).encode(), 'carry-v1', None),
    (fused(BOX.format(h=300, w=250)).encode(), 'direct-v1', 2),
    (wide(MIXED, None, 'i64'), 'direct-v1', None),
    (TWIN.format(n=2000, h=1000).encode(), 'direct-v1', None),
)


def _variables(plan):
    """Every variable a plan binds, in stage order: loops, then sums in pre-order."""
    found = []

    def walk(e):
        if e[0] == 'sum':
            found.append(e[1])
            walk(e[4])
        elif e[0] in ('add', 'mul', 'min', 'max', 'shr', 'shr_round'):
            walk(e[1])
            walk(e[2])
    for stage in plan.stages:
        found += [var for var, _ in stage.loops]
        walk(stage.value)
    return list(dict.fromkeys(found))


def renamed(plan, names):
    """`plan` with each variable renamed by `names`, its affines kept canonical (sorted)."""
    def affine(value):
        constant, terms = value
        return (constant, tuple(sorted((names.get(v, v), k) for v, k in terms)))

    def expr(e):
        if e[0] == 'load':
            return ('load', affine(e[1]))
        if e[0] == 'sum':
            return ('sum', names.get(e[1], e[1]), e[2], e[3], expr(e[4]))
        if e[0] in ('add', 'mul', 'min', 'max', 'shr', 'shr_round'):
            return (e[0], expr(e[1]), expr(e[2]))
        return e
    return LoopPlan(plan.semantic_digest, plan.plan_id,
                    tuple(Stage(tuple((names.get(v, v), n) for v, n in s.loops), affine(s.index), expr(s.value))
                          for s in plan.stages), plan.format)


def emitted(source, plan, abi=None):
    """The C of a plan the checker proves for `source`."""
    check = check_loop_plan(source, plan)
    assert check.valid, (check.reason, check.detail)
    kernel = admit_source(parse_source(source))
    return emit_scale_c(kernel, plan, sha256(source).hexdigest(), check.plan_digest, abi).c_source


def hostile_plans(source, plan_id):
    """The planner's plan, then copies whose variables take each hostile name in turn."""
    plan = make_scale_plan(admit_source(parse_source(source)), plan_id)
    variables = _variables(plan)
    yield plan
    for offset in range(0, len(HOSTILE), len(variables)):
        names = {v: HOSTILE[(offset + k) % len(HOSTILE)] for k, v in enumerate(variables)}
        yield renamed(plan, names)


class UntrustedStringTests(unittest.TestCase):
    def test_hostile_plan_ids_never_reach_the_c(self):
        for source, plan_id, abi in PROGRAMS[:8]:
            plan = make_scale_plan(admit_source(parse_source(source)), plan_id)
            trusted = emitted(source, plan, abi)
            self.assertTrue(trusted.startswith(f'/* Generated from a template-checked scale-v1 loop plan '
                                               f'({plan_id}). */\n'.encode()), trusted[:100])
            for label in (INJECTED, 'candidate-7', '', '\u00e9', 'x' * 300, 5, None, ['direct-v1'],
                          {'*/': 1}, 'direct-v1 ', 'DIRECT-V1'):
                hostile = dataclasses.replace(plan, plan_id=label)
                with self.subTest(source=source[:14], plan_id=plan_id, label=repr(label)[:30]):
                    c = emitted(source, hostile, abi)
                    self.assertNotIn(MARK.encode(), c)
                    first, rest = c.split(b'\n', 1)
                    self.assertEqual(first, b'/* Generated from a template-checked scale-v1 loop plan (candidate). */')
                    self.assertEqual(rest, trusted.split(b'\n', 1)[1])

    def test_a_hostile_plan_id_from_json(self):
        # The demo path: candidate JSON bytes, load_plan, review_candidates, emit.
        source = SUM.format(n=2000).encode()
        plan = make_scale_plan(admit_source(parse_source(source)))
        data = plan_json(dataclasses.replace(plan, plan_id=INJECTED))
        self.assertIn(b'beryl_injected', data)
        result, = review_candidates(source, [('hostile', data)])
        self.assertTrue(result.accepted, result.reason)
        c = emitted(source, load_plan(data))
        self.assertNotIn(MARK.encode(), c)
        self.assertNotIn(b'#define', c)
        self.assertEqual(c.split(b'\n', 1)[1], emitted(source, plan).split(b'\n', 1)[1])

    def test_hostile_variable_names_emit_the_planners_c(self):
        for source, plan_id, abi in PROGRAMS:
            plans = hostile_plans(source, plan_id)
            trusted = emitted(source, next(plans), abi)
            for number, plan in enumerate(plans):
                with self.subTest(source=source[:14], plan_id=plan_id, abi=abi, number=number):
                    c = emitted(source, plan, abi)
                    self.assertNotIn(MARK.encode(), c)
                    self.assertEqual(c, trusted)

    def test_sibling_sums_may_share_a_name(self):
        # The checker allows sibling sums to reuse a variable; they still bind it separately.
        source = TWIN.format(n=2000, h=1000).encode()
        plan = make_scale_plan(admit_source(parse_source(source)))
        self.assertEqual(_variables(plan), ['r', 'c', 's0', 's1'])
        for name in ('k', 's0', 's1', 'acc'):
            with self.subTest(name=name):
                self.assertEqual(emitted(source, renamed(plan, {'s0': name, 's1': name})), emitted(source, plan))

    def test_hostile_plans_compute_the_reference_natively(self):
        harness = Path(__file__).parent / 'fixtures' / 'scale_harness.c'
        cases = [(SUM.format(n=1 << 17).encode(), 'direct-v1', 'int32_t'),
                 (BOX.format(h=30, w=25).encode(), 'carry-v1', 'int32_t'),
                 (BOX.format(h=30, w=25).encode(), 'direct-v1', 'int32_t'),
                 (wide(DOT.format(n=1 << 16)), 'direct-v1', 'int64_t'),
                 (TWIN.format(n=2000, h=1000).encode(), 'direct-v1', 'int32_t')]
        with tempfile.TemporaryDirectory() as tmp:
            for number, (source, plan_id, out) in enumerate(cases):
                kernel = admit_source(parse_source(source))
                plans = list(hostile_plans(source, plan_id))
                # The last hostile renaming, with the injected label too.
                plan = dataclasses.replace(plans[-1], plan_id=INJECTED)
                c = Path(tmp) / f'k{number}.c'
                c.write_bytes(emitted(source, plan).replace(b'int main(void)', b'int beryl_unused_main(void)'))
                exe = Path(tmp) / f'k{number}.exe'
                try:
                    built = subprocess.run([CC, '-O2', '-std=c11', '-Wall', '-Werror', '-pthread',
                                            f'-DBERYL_OUT={out}', str(c), str(harness), '-o', str(exe)],
                                           capture_output=True, text=True)
                except OSError as error:
                    self.skipTest(f'no C compiler: {error}')
                self.assertEqual(built.returncode, 0, built.stderr)  # a compile error is a failure, not a skip
                n = kernel.input_count
                for data in (data_for(n), [1023] * n, data_for(n)[:-1] + [1024]):
                    try:
                        ran = subprocess.run([str(exe), str(n), str(kernel.output_count)],
                                             input=' '.join(map(str, data)), capture_output=True, text=True,
                                             check=True, env={'BERYL_THREADS': '4', 'SYSTEMROOT': 'C:\\Windows'})
                    except OSError as error:  # Windows Application Control; never bypassed
                        self.skipTest(f'executable launch refused: {error}')
                    status, *values = map(int, ran.stdout.split())
                    ref = evaluate_source(kernel.source_module, data, [-9] * kernel.output_count)
                    with self.subTest(case=number, top=data[0]):
                        self.assertEqual(status, 0 if ref.first_bad_index is None else ref.first_bad_index + 1)
                        self.assertEqual(tuple(values), ref.output)


if __name__ == '__main__':
    unittest.main()
