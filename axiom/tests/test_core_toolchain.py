"""Behavioral tests: path confusion, failed probes and mutable source must fail closed."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from axiom.core_toolchain import (
    PINNED_CORE_COMMIT, CommandReceipt, Toolchain, ToolchainError, build_core, inspect_toolchain,
    prepare_snapshot, _identity,
)


class ToolchainNegativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='axiom toolchain ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def executable(self, text):
        path = self.root / 'compiler with spaces'
        path.write_text('#!/usr/bin/env python3\n' + text)
        path.chmod(0o700)
        return path

    def test_dependency_symlink_retarget_is_rejected_with_old_target_intact(self):
        executable = self.executable('print("negative identity fixture")\n')
        target_a = self.root / 'libA.so'
        target_b = self.root / 'libB.so'
        target_a.write_bytes(b'old observed component')
        target_b.write_bytes(b'new different component')
        lookup = self.root / 'libdep.so'
        lookup.symlink_to(target_a)
        component = _identity(lookup)
        receipt = CommandReceipt((), self.root, 0, '', '')
        toolchain = Toolchain(
            compiler=executable, clang=executable,
            compiler_sha256=_identity(executable).sha256,
            clang_sha256=_identity(executable).sha256, clang_config=(),
            source_pin=PINNED_CORE_COMMIT, source_inventory_sha256='',
            compiler_version='', clang_version='', build_receipt=receipt,
            unit_receipt=receipt, native_receipt=receipt, unit_status='unqualified_fixture',
            snapshot=self.root, source_repository=self.root, source_inventory=(),
            snapshot_inventory=(), generated_changes=(), preflight_receipts=(),
            native_artifacts=(), receipt_path=self.root / 'unused.json',
            clang_components=(component,))
        lookup.unlink()
        lookup.symlink_to(target_b)
        self.assertTrue(target_a.is_file())
        with self.assertRaisesRegex(ToolchainError, 'component'):
            toolchain.revalidate_identity()

    def test_missing_executable_is_unavailable(self):
        result = inspect_toolchain(self.root, self.root / 'missing clang')
        self.assertEqual(result.status, 'unavailable')
        self.assertFalse(result.available)

    def test_nonzero_version_probe_is_unavailable(self):
        clang = self.executable('import sys\nsys.exit(9)\n')
        result = inspect_toolchain(self.root, clang)
        self.assertEqual(result.status, 'unavailable')
        self.assertEqual(result.receipts[0].returncode, 9)

    def test_version_success_does_not_establish_c11_capability(self):
        clang = self.executable('import sys\nprint("negative test driver")\nsys.exit(0 if "--version" in sys.argv else 17)\n')
        result = inspect_toolchain(self.root, clang)
        self.assertEqual(result.status, 'unavailable')
        self.assertIn('C11', result.reason)

    def test_compile_success_without_executable_is_unavailable(self):
        clang = self.executable('print("pretend clang")\n')
        result = inspect_toolchain(self.root, clang)
        self.assertEqual(result.status, 'unavailable')
        self.assertIn('C11', result.reason)

    def test_unsuccessful_run_is_unavailable(self):
        clang = self.executable('''import sys
from pathlib import Path
if "--version" in sys.argv:
    print("test negative driver")
else:
    out = Path(sys.argv[sys.argv.index("-o") + 1])
    out.write_text("#!/bin/sh\\nexit 23\\n")
    out.chmod(0o700)
''')
        result = inspect_toolchain(self.root, clang)
        self.assertEqual(result.status, 'unavailable')
        self.assertEqual(result.receipts[-1].returncode, 23)

    def test_different_source_commit_is_rejected(self):
        source = self.root / 'other source'
        source.mkdir()
        subprocess.run(['git', 'init', '-q', str(source)], check=True)
        (source / 'file').write_text('different')
        subprocess.run(['git', '-C', str(source), 'add', 'file'], check=True)
        subprocess.run(['git', '-C', str(source), '-c', 'user.name=Test',
                        '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'other'], check=True)
        with self.assertRaisesRegex(ToolchainError, 'commit'):
            prepare_snapshot(source, self.root / 'snapshot')

    def test_unmarked_snapshot_is_rejected_without_receipt(self):
        output = self.root / 'output'
        with self.assertRaises(ToolchainError):
            build_core(self.root, Path('/bin/false'), output)
        self.assertFalse((output / 'toolchain.json').exists())


@unittest.skipUnless(os.environ.get('AXIOM_TEST_CLANG') and os.environ.get('AXIOM_TEST_CORE'),
                     'actual pinned Core/Clang paths must be explicitly selected')
class ActualToolchainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='axiom actual paths with spaces ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = Path(os.environ['AXIOM_TEST_CORE'])
        self.clang = Path(os.environ['AXIOM_TEST_CLANG'])

    def test_selected_clang_preflight_has_c11_run_receipt(self):
        result = inspect_toolchain(self.source, self.clang)
        self.assertTrue(result.available, result.reason)
        self.assertEqual(result.source_pin, PINNED_CORE_COMMIT)
        self.assertEqual(result.receipts[-1].stdout, '42\n')
        self.assertTrue(any(identity.path.name == 'clang.cfg' for identity in result.clang_config))
        self.assertTrue(any('libclang-cpp' in identity.path.name for identity in result.clang_components))

    def test_snapshot_inventory_rejects_dirty_source_and_extra_files(self):
        snapshot = prepare_snapshot(self.source, self.root / 'snapshot')
        (snapshot / 'src/ir/ir.h').write_text('dirty')
        with self.assertRaisesRegex(ToolchainError, 'inventory'):
            build_core(snapshot, self.clang, self.root / 'out')
        with self.assertRaisesRegex(ToolchainError, 'Git|git'):
            prepare_snapshot(snapshot, self.root / 'other')

    def test_git_assume_unchanged_cannot_hide_dirty_source(self):
        snapshot = prepare_snapshot(self.source, self.root / 'snapshot')
        (snapshot / '.axiom-source.json').unlink()
        subprocess.run(['git', 'init', '-q', str(snapshot)], check=True)
        alternates = snapshot / '.git/objects/info/alternates'
        alternates.write_text(str((self.source / '.git/objects').resolve()) + '\n')
        subprocess.run(['git', '-C', str(snapshot), 'read-tree', PINNED_CORE_COMMIT], check=True)
        subprocess.run(['git', '-C', str(snapshot), 'update-ref', 'HEAD', PINNED_CORE_COMMIT], check=True)
        target = 'src/ir/ir.h'
        subprocess.run(['git', '-C', str(snapshot), 'update-index', '--assume-unchanged', target], check=True)
        (snapshot / target).write_text('hidden dirty source')
        result = inspect_toolchain(snapshot, self.clang)
        self.assertEqual(result.status, 'error')
        self.assertIn('inventory', result.reason)

    def test_snapshot_parent_symlink_cannot_write_into_core_source(self):
        # Use a pinned disposable checkout to keep a failure away from the original.
        snapshot = prepare_snapshot(self.source, self.root / 'pinned copy')
        (snapshot / '.axiom-source.json').unlink()
        subprocess.run(['git', 'init', '-q', str(snapshot)], check=True)
        (snapshot / '.git/objects/info/alternates').write_text(
            str((self.source / '.git/objects').resolve()) + '\n')
        subprocess.run(['git', '-C', str(snapshot), 'read-tree', PINNED_CORE_COMMIT], check=True)
        subprocess.run(['git', '-C', str(snapshot), 'update-ref', 'HEAD', PINNED_CORE_COMMIT], check=True)
        alias = self.root / 'source alias'
        alias.symlink_to(snapshot, target_is_directory=True)
        with self.assertRaises(ToolchainError):
            prepare_snapshot(snapshot, alias / 'must not exist')
        self.assertFalse((snapshot / 'must not exist').exists())

    def test_untracked_snapshot_file_is_rejected(self):
        snapshot = prepare_snapshot(self.source, self.root / 'snapshot')
        (snapshot / 'extra.c').write_text('untracked')
        with self.assertRaisesRegex(ToolchainError, 'inventory'):
            build_core(snapshot, self.clang, self.root / 'out')

    def test_unbuildable_selected_compiler_produces_no_success_receipt(self):
        snapshot = prepare_snapshot(self.source, self.root / 'snapshot')
        wrapper = self.root / 'clang rejects Core with spaces'
        wrapper.write_text('#!/usr/bin/env python3\nimport os, sys\n'
                           + 'real = ' + repr(str(self.clang)) + '\n'
                           + 'if "--version" in sys.argv or any(a.endswith("probe.c") for a in sys.argv):\n'
                           + '    os.execv(real, [real, *sys.argv[1:]])\n'
                           + 'sys.exit(31)\n')
        wrapper.chmod(0o700)
        output = self.root / 'failed output'
        with self.assertRaisesRegex(ToolchainError, 'build failed') as caught:
            build_core(snapshot, wrapper, output)
        self.assertEqual(caught.exception.receipts[-1].returncode, 31)
        self.assertFalse((output / 'toolchain.json').exists())
        self.assertTrue((output / 'build.json').is_file())
        captured = [json.loads(line) for line in (output / 'clang-invocations.jsonl').read_text().splitlines()]
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]['stage'], 'build')
        self.assertEqual(captured[0]['argv'][0], str(wrapper.resolve()))
        self.assertEqual(captured[0]['selected_sha256'], _identity(wrapper).sha256)
        self.assertIn('src/driver/main.c', captured[0]['argv'])
        self.assertIn('-o', captured[0]['argv'])

    def test_real_isolated_build_keeps_failed_baseline_and_qualifies_native(self):
        if os.environ.get('AXIOM_TEST_RETAIN_BUILD'):
            self.root = Path(os.environ['AXIOM_TEST_RETAIN_BUILD']).resolve()
            self.root.mkdir(parents=True, exist_ok=False)
        before = subprocess.check_output(['git', '-C', str(self.source), 'status', '--porcelain'])
        snapshot = prepare_snapshot(self.source, self.root / 'snapshot with spaces')
        toolchain = build_core(snapshot, self.clang, self.root / 'output with spaces')
        self.assertTrue(toolchain.compiler.is_absolute())
        self.assertEqual(toolchain.source_pin, PINNED_CORE_COMMIT)
        self.assertEqual(toolchain.build_receipt.returncode, 0)
        self.assertEqual(toolchain.unit_receipt.returncode, 1)
        self.assertEqual(toolchain.unit_status, 'known_pinned_baseline_failure')
        self.assertEqual(toolchain.native_receipt.returncode, 0)
        self.assertEqual(toolchain.native_receipt.stdout.splitlines()[0], '42')
        toolchain.revalidate_identity()
        config = toolchain.clang_config[0]
        with self.assertRaises(ToolchainError):
            replace(toolchain, clang_config=(replace(config, sha256='0' * 64),)).revalidate_identity()
        with self.assertRaises(ToolchainError):
            replace(toolchain, compiler_sha256='0' * 64).revalidate_identity()
        self.assertEqual(subprocess.check_output(['git', '-C', str(self.source), 'status', '--porcelain']), before)
        self.assertTrue((toolchain.receipt_path).is_file())
        self.assertEqual([call.stage for call in toolchain.clang_invocations], ['build', 'unit'])
        build_call, unit_call = toolchain.clang_invocations
        self.assertEqual(build_call.argv[0], str(self.clang.resolve()))
        self.assertEqual(build_call.selected_sha256, toolchain.clang_sha256)
        self.assertEqual(build_call.cwd, snapshot)
        self.assertIn('src/driver/main.c', build_call.argv)
        self.assertNotIn('src/driver/main.c', unit_call.argv)
        self.assertIn('tests/unit/test_ir.c', unit_call.argv)
        for call in toolchain.clang_invocations:
            candidate = snapshot / call.argv[call.argv.index('-o') + 1]
            self.assertTrue(candidate.is_file())
        capture = json.loads((toolchain.receipt_path.parent / 'clang-invocations.jsonl').read_text().splitlines()[0])
        self.assertEqual(capture['argv'], list(build_call.argv))


if __name__ == '__main__':
    unittest.main()
