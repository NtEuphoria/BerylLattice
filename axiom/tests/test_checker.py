"""Independent hand-authored controls; never import a physical-plan generator."""
from dataclasses import FrozenInstanceError, replace
import ast
import cProfile
from pathlib import Path
import unittest

from axiom import checker
from axiom.codec import canonical_json, decode_plan, validate_plan
from axiom.frontend import admit_source, parse_source
from axiom.model import Limits
from axiom.plan_format import Operation, Plan

FIXTURES = Path(__file__).parent / 'fixtures' / 'plans' / 'checker'


def kernel(height=1, width=1, cap=64):
    constraint = '' if cap is None else f'require plan_workspace_bytes <= {cap};'
    return admit_source(parse_source(f'''module check;
shape H={height}; shape W={width};
input image:i32[H+1,W+1] in 0..=1023;
let p[r in 0..H+1,c in 0..W+1]=(image[r,c]+1)*(image[r,c]+1);
output out[r in 0..H,c in 0..W]=((p[r,c]+p[r,c+1])+p[r+1,c])+p[r+1,c+1];
{constraint}'''.encode()))


def manual_plan(k=None):
    k = k or kernel()
    p = decode_plan((FIXTURES / 'manual-inline-1x1.json').read_bytes(), Limits())
    return replace(p, semantic_digest=k.semantic_digest)


def staged(k):
    """Independent SSA retention control, deliberately outside generator labels."""
    operations = [Operation('const', dst=0, value=1)]
    values = []
    for i in range((k.height + 1) * (k.width + 1)):
        d = 1 + 3 * i
        operations.extend((Operation('input_load', dst=d, index=i),
                           Operation('add', dst=d+1, operands=(d, 0)),
                           Operation('mul', dst=d+2, operands=(d+1, d+1))))
        values.append(d+2)
    d = 1 + 3 * len(values)
    for r in range(k.height):
        for c in range(k.width):
            i = r * (k.width+1) + c
            operations.extend((Operation('add', dst=d, operands=(values[i], values[i+1])),
                               Operation('add', dst=d+1, operands=(d, values[i+k.width+1])),
                               Operation('add', dst=d+2, operands=(d+1, values[i+k.width+2])),
                               Operation('output_store', index=r*k.width+c, operands=(d+2,))))
            d += 3
    return Plan(1, k.semantic_digest, 'arbitrary SSA retention control', 0, tuple(operations))


class CheckerTests(unittest.TestCase):
    def setUp(self):
        self.k = kernel()
        self.p = manual_plan(self.k)

    def check(self, p=None, limits=None, **context):
        return checker.check_plan(self.k, p or self.p, limits or Limits(), **context)

    def invalid(self, p):
        result = self.check(p)
        self.assertEqual(result.semantic_status, 'invalid', result)
        self.assertIsNotNone(result.witness)
        self.assertFalse(result.eligible)
        return result

    def test_manual_inline_1x1(self):
        result = self.check()
        self.assertEqual(result.semantic_status, 'valid')
        self.assertEqual(result.constraint_status, 'satisfied')
        self.assertTrue(result.check_complete)
        self.assertTrue(result.eligible)
        self.assertEqual(result.workspace_bytes, 0)
        self.assertEqual(result.multiplication_ops, 4)
        self.assertEqual(dict(result.opcode_counts), {'add': 7, 'const': 1, 'input_load': 4,
                                                    'mul': 4, 'output_store': 1})
        self.assertEqual(result.source_digest, self.k.source_digest)
        self.assertEqual(len(result.plan_digest), 64)
        with self.assertRaises(FrozenInstanceError):
            result.reason = 'forged'

    def test_check_validates_structure_once_before_symbolic_execution(self):
        # Structural validation walks every operation. Digest generation must
        # share that boundary instead of repeating the entire validation pass.
        profile = cProfile.Profile()
        result = profile.runcall(self.check)
        self.assertTrue(result.eligible, result)
        validations = sum(entry.callcount for entry in profile.getstats()
                          if entry.code is validate_plan.__code__)
        self.assertEqual(validations, 1)

    def test_ssa_staged_5x7_arbitrary_label(self):
        k = kernel(5, 7, 0)
        plan = staged(k)
        self.assertEqual(len(plan.operations), 285)
        result = checker.check_plan(k, plan, Limits())
        self.assertTrue(result.eligible, result)
        self.assertEqual(result.multiplication_ops, 48)
        self.assertEqual(result.workspace_bytes, 0)
        self.assertEqual(result.work_used, 35 * 77 + 285 + 35 * 31)

    def test_extra_reserved_cells_count(self):
        result = self.check(replace(self.p, scratch_capacity_cells=17))
        self.assertEqual(result.workspace_bytes, 68)
        self.assertEqual(result.semantic_status, 'valid')
        self.assertEqual(result.constraint_status, 'violated')
        self.assertFalse(result.eligible)

    def test_billion_cells_sparse(self):
        result = self.check(replace(self.p, scratch_capacity_cells=1000000000))
        self.assertEqual(result.workspace_bytes, 4000000000)
        self.assertEqual(result.semantic_status, 'valid')

    def test_additional_cap_binds_identity(self):
        p = replace(self.p, scratch_capacity_cells=16)
        old = self.check(p)
        tight = self.check(p, additional_cap=0)
        loose = self.check(p, additional_cap=128)
        self.assertEqual(tight.effective_cap, 0)
        self.assertEqual(tight.constraint_status, 'violated')
        self.assertEqual(loose.effective_cap, 64)
        self.assertNotEqual(old.constraint_digest, tight.constraint_digest)
        self.assertNotEqual(old.constraint_digest, loose.constraint_digest)
        for bad in (True, -1, 2147483648):
            with self.assertRaises(ValueError):
                self.check(additional_cap=bad)

    def test_exact_work_boundary_and_partial_metrics(self):
        full = self.check()
        # 5 output grouping/add nodes +20 producer-read/index nodes +52
        # producer-AST nodes, then 17 operations and 31 scalar comparison pairs.
        self.assertEqual(full.work_used, 77 + 17 + 31)
        for quota in range(1, full.work_used):
            with self.subTest(quota=quota):
                partial = self.check(limits=Limits(check_steps=quota))
                self.assertEqual(partial.work_used, quota)
                self.assertFalse(partial.check_complete)
                self.assertEqual(partial.semantic_status, 'unknown')
                self.assertEqual(partial.constraint_status, 'satisfied')
                self.assertFalse(partial.eligible)
        exact = self.check(limits=Limits(check_steps=full.work_used))
        self.assertTrue(exact.eligible)
        early = self.check(limits=Limits(check_steps=1))
        self.assertIsNone(early.multiplication_ops)
        self.assertIsNone(early.opcode_counts)
        late = self.check(limits=Limits(check_steps=full.work_used-1))
        self.assertEqual(late.multiplication_ops, 4)
        self.assertEqual(dict(late.opcode_counts)['mul'], 4)

    def test_expression_allocation_boundary(self):
        k = kernel(2, 2)
        p = staged(k)
        first_pass = None
        for cap in range(1, 200):
            result = checker.check_plan(k, p, Limits(expression_nodes=cap))
            if result.eligible:
                first_pass = cap
                break
            self.assertEqual(result.semantic_status, 'unknown')
            self.assertFalse(result.check_complete)
        self.assertEqual(first_pass, 4 * 31 + 1 + 9 * 3 + 4 * 3)
        self.assertTrue(checker.check_plan(k, p, Limits(expression_nodes=first_pass)).eligible)

    def test_quota_rejection(self):
        for limits in (Limits(plan_operations=16), Limits(plan_bytes=32)):
            result = self.check(limits=limits)
            self.assertEqual(result.semantic_status, 'unknown')
            self.assertFalse(result.check_complete)
            self.assertIsNone(result.multiplication_ops)

    def test_direct_objects_receive_structural_validation(self):
        variants = [replace(self.p.operations[1], index=True),
                    replace(self.p.operations[1], dst=0),
                    replace(self.p.operations[1], operands=(0,)),
                    replace(self.p.operations[1], opcode='teleport'),
                    replace(self.p.operations[1], dst=True)]
        for op in variants:
            with self.subTest(op=op):
                self.invalid(replace(self.p, operations=(self.p.operations[0], op)+self.p.operations[2:]))
        self.invalid(replace(self.p, operations=(Operation('add', dst=0, operands=(1, 1)),)))
        self.invalid(replace(self.p, scratch_capacity_cells=True))
        self.invalid(replace(self.p, operations=list(self.p.operations)))

    def test_bad_digest(self):
        self.invalid(replace(self.p, semantic_digest='f'*64))

    def test_input_output_bounds_and_duplicate_missing_output(self):
        self.invalid(replace(self.p, operations=self.p.operations[:1]+(
            replace(self.p.operations[1], index=4),)+self.p.operations[2:]))
        self.invalid(replace(self.p, operations=self.p.operations[:-1]+(
            replace(self.p.operations[-1], index=1),)))
        self.invalid(replace(self.p, operations=self.p.operations+(self.p.operations[-1],)))
        self.invalid(replace(self.p, operations=self.p.operations[:-1]))

    def test_scratch_read_before_write_and_bounds(self):
        self.invalid(replace(self.p, scratch_capacity_cells=1, operations=(
            Operation('scratch_load', dst=0, index=0),)))
        self.invalid(replace(self.p, scratch_capacity_cells=1, operations=(
            Operation('scratch_load', dst=0, index=1),)))

    def test_scratch_alias_and_overwrite(self):
        prefix = self.p.operations[:-1]
        good = replace(self.p, scratch_capacity_cells=1, operations=prefix+(
            Operation('scratch_store', index=0, operands=(15,)),
            Operation('scratch_load', dst=16, index=0),
            Operation('output_store', index=0, operands=(16,))))
        self.assertTrue(self.check(good).eligible)
        overwritten = replace(good, operations=prefix+(
            Operation('scratch_store', index=0, operands=(15,)),
            Operation('scratch_store', index=0, operands=(0,)),
            Operation('scratch_load', dst=16, index=0),
            Operation('output_store', index=0, operands=(16,))))
        result = self.check(overwritten)
        self.assertNotEqual(result.semantic_status, 'valid')
        if result.semantic_status == 'invalid':
            self.assertIsNotNone(result.witness)

    def test_equivalent_structural_mismatch_is_unknown(self):
        ops = list(self.p.operations)
        ops[13] = replace(ops[13], operands=(6, 3)) # commute the first two producers
        result = self.check(replace(self.p, operations=tuple(ops)))
        self.assertEqual(result.semantic_status, 'unknown')
        self.assertTrue(result.check_complete)
        self.assertIsNone(result.witness)

    def test_safe_dead_arithmetic_counts(self):
        p = replace(self.p, operations=self.p.operations+(
            Operation('mul', dst=16, operands=(0, 0)),))
        result = self.check(p)
        self.assertTrue(result.eligible)
        self.assertEqual(result.multiplication_ops, 5)

    def test_unsafe_dead_arithmetic_has_actual_witness(self):
        for tail in ((Operation('const', dst=16, value=2147483647),
                      Operation('add', dst=17, operands=(16, 0))),
                     (Operation('mul', dst=16, operands=(3, 3)),)):
            result = self.invalid(replace(self.p, operations=self.p.operations+tail))
            # Overflow values can exceed the artifact codec's ten-digit bound.
            canonical_json(dict(result.witness))

    def test_inconclusive_interval_is_unknown_not_invalid(self):
        # x + (-x) is zero, but ordinary intervals lose the correlation.
        tail = (Operation('const', dst=16, value=-1),
                Operation('mul', dst=17, operands=(1, 16)),
                Operation('add', dst=18, operands=(1, 17)),
                Operation('const', dst=19, value=2147483647),
                Operation('mul', dst=20, operands=(18, 19)))
        result = self.check(replace(self.p, operations=self.p.operations+tail))
        self.assertEqual(result.semantic_status, 'unknown')
        self.assertTrue(result.check_complete)
        self.assertIsNone(result.witness)
        self.assertEqual(result.multiplication_ops, 6)

    def test_deep_dag_and_repeated_squaring_are_bounded(self):
        for opcode in ('add', 'mul'):
            ops = list(self.p.operations)
            ops.append(Operation('const', dst=16, value=0 if opcode == 'add' else 1))
            for dst in range(17, 6017):
                args = (dst-1, 16) if opcode == 'add' else (dst-1, dst-1)
                ops.append(Operation(opcode, dst=dst, operands=args))
            result = self.check(replace(self.p, operations=tuple(ops)))
            self.assertTrue(result.eligible, result)
            limited = self.check(replace(self.p, operations=tuple(ops)), Limits(check_steps=1000))
            self.assertEqual(limited.semantic_status, 'unknown')
            self.assertFalse(limited.check_complete)

    def test_source_ast_visits_preserve_grouping_and_alpha_names(self):
        source = self.k.source_module.source_bytes.replace(
            b'=(image[r,c]+1)*(image[r,c]+1);',
            b'=((image[r,c]+1)*(image[r,c]+1));')
        source = source.replace(b'image', b'pixels').replace(b'p[', b'producer[')
        k = admit_source(parse_source(source))
        self.assertEqual(k.semantic_digest, self.k.semantic_digest)
        result = checker.check_plan(k, self.p, Limits())
        self.assertTrue(result.eligible)
        self.assertEqual(result.work_used, 125 + 4)
        self.assertEqual(result.source_digest, k.source_digest)
        self.assertNotEqual(result.source_digest, self.check().source_digest)

    def test_complete_operation_scan_is_metric_boundary(self):
        before = self.check(limits=Limits(check_steps=77+16))
        after = self.check(limits=Limits(check_steps=77+17))
        self.assertIsNone(before.multiplication_ops)
        self.assertIsNone(before.opcode_counts)
        self.assertEqual(after.multiplication_ops, 4)
        self.assertEqual(sum(dict(after.opcode_counts).values()), 17)
        self.assertFalse(after.check_complete)

    def test_plan_identity_covers_label_and_unused_scratch(self):
        original = self.check()
        label = self.check(replace(self.p, plan_id='new label'))
        arena = self.check(replace(self.p, scratch_capacity_cells=1))
        self.assertEqual(len({original.plan_digest, label.plan_digest, arena.plan_digest}), 3)
        self.assertTrue(label.eligible)
        self.assertTrue(arena.eligible)

    def test_deep_dag_used_in_comparison_returns_unknown(self):
        ops = list(self.p.operations[:-1])
        ops.append(Operation('const', dst=16, value=0))
        for dst in range(17, 6017):
            ops.append(Operation('add', dst=dst, operands=(15 if dst == 17 else dst-1, 16)))
        ops.append(Operation('output_store', index=0, operands=(6016,)))
        result = self.check(replace(self.p, operations=tuple(ops)))
        self.assertEqual(result.semantic_status, 'unknown')
        self.assertTrue(result.check_complete)
        self.assertIsNone(result.witness)

    def test_forged_kernel_cannot_weaken_source_cap(self):
        forged = replace(self.k, cap=None)
        p = replace(self.p, scratch_capacity_cells=17)
        result = checker.check_plan(forged, p, Limits())
        self.assertEqual(result.semantic_status, 'invalid')
        self.assertIsNotNone(result.witness)
        self.assertFalse(result.eligible)

    def test_forged_retained_ast_cannot_change_source_semantics(self):
        # The retained original bytes still specify the four-cell stencil.
        from axiom.model import IntegerLiteral, Span
        scalar = IntegerLiteral(1, Span(0, 1))
        changed_output = replace(self.k.source_module.outputs[0], expression=scalar)
        module = replace(self.k.source_module, outputs=(changed_output,))
        forged = replace(self.k, source_module=module,
                         source_expressions=(self.k.source_expressions[0], scalar))
        wrong_plan = replace(self.p, operations=(self.p.operations[0],
                            Operation('output_store', index=0, operands=(0,))))
        result = checker.check_plan(forged, wrong_plan, Limits())
        self.assertEqual(result.semantic_status, 'invalid')
        self.assertIsNotNone(result.witness)
        self.assertFalse(result.eligible)

    def test_forged_semantic_and_source_identities_are_invalid(self):
        for field in ('source_digest', 'semantic_digest'):
            with self.subTest(field=field):
                forged = replace(self.k, **{field: 'f'*64})
                p = replace(self.p, semantic_digest=forged.semantic_digest)
                result = checker.check_plan(forged, p, Limits())
                self.assertEqual(result.semantic_status, 'invalid')
                self.assertIsNotNone(result.witness)

    def test_check_reapplies_source_admission_byte_limit(self):
        result = self.check(limits=Limits(source_bytes=1))
        self.assertEqual(result.semantic_status, 'unknown')
        self.assertFalse(result.check_complete)
        self.assertEqual(result.work_used, 0)

    def test_wrong_in_bounds_neighbor_without_witness_is_unknown(self):
        operations = list(self.p.operations)
        operations[1] = replace(operations[1], index=1)
        result = self.check(replace(self.p, operations=tuple(operations)))
        self.assertEqual(result.semantic_status, 'unknown')
        self.assertIsNone(result.witness)
        self.assertFalse(result.eligible)

    def test_import_isolation(self):
        tree = ast.parse(Path(checker.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [alias.name for alias in node.names]
                if isinstance(node, ast.ImportFrom):
                    names.append(node.module or '')
                for name in names:
                    self.assertNotIn('planner', name)
                    self.assertNotIn('reference', name)


if __name__ == '__main__':
    unittest.main()
