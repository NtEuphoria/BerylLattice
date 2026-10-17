"""Retained qualification loading must independently reject stale or invented records."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from axiom import core_toolchain as module

RETAINED = Path('/workspace/scratch/axiom-toolchain-task1-review1/output with spaces/toolchain.json')


@unittest.skipUnless(RETAINED.is_file(), 'retained local qualification is not present')
class LoadToolchainTests(unittest.TestCase):
    def setUp(self):
        self.record = json.loads(RETAINED.read_text())

    def load_record(self, record):
        """Substitute receipt bytes only; every referenced identity remains real."""
        original = Path.read_text
        raw = record if isinstance(record, str) else json.dumps(record)
        def read(path, *args, **kwargs):
            return raw if path == RETAINED else original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', read):
            return module.load_toolchain(RETAINED)

    def test_actual_receipt_restores_frozen_records_and_exact_baseline(self):
        loader = getattr(module, 'load_toolchain', None)
        self.assertTrue(callable(loader), 'missing strict load_toolchain API')
        toolchain = loader(RETAINED)
        self.assertEqual(toolchain.receipt_path, RETAINED)
        self.assertEqual(toolchain.unit_status, 'known_pinned_baseline_failure')
        self.assertEqual(toolchain.unit_receipt.returncode, 1)
        self.assertIsInstance(toolchain.native_receipt, module.CommandReceipt)
        self.assertIsInstance(toolchain.clang_config[0], module.FileIdentity)
        self.assertIsInstance(toolchain.clang_invocations[0], module.CompilerInvocation)
        self.assertIsInstance(toolchain.source_inventory, tuple)
        self.assertIsInstance(toolchain.source_inventory[0], tuple)
        self.assertIn('snapshot with spaces', str(toolchain.compiler))

    def test_bad_records_rejected(self):
        mutations = [
            ('extra field', lambda d: d.update(qualified=True)),
            ('missing field', lambda d: d.pop('clang_invocations')),
            ('wrong pin', lambda d: d.update(source_pin='0' * 40)),
            ('invented unit pass', lambda d: d.update(unit_status='passed')),
            ('bool returncode', lambda d: d['build_receipt'].update(returncode=False)),
            ('bool size', lambda d: d['clang_config'][0].update(size=True)),
            ('bool mode', lambda d: d['source_inventory'][0].__setitem__(2, True)),
            ('nested extra', lambda d: d['native_receipt'].update(success=True)),
            ('wrong version type', lambda d: d.update(compiler_version=1)),
            ('compiler hash', lambda d: d.update(compiler_sha256='0' * 64)),
            ('clang hash', lambda d: d.update(clang_sha256='0' * 64)),
            ('source digest', lambda d: d.update(source_inventory_sha256='0' * 64)),
            ('snapshot bytes', lambda d: d['snapshot_inventory'][0].__setitem__(1, '0' * 64)),
            ('config hash', lambda d: d['clang_config'][0].update(sha256='0' * 64)),
            ('component hash', lambda d: d['clang_components'][0].update(sha256='0' * 64)),
            ('native artifact hash', lambda d: d['native_artifacts'][0].update(sha256='0' * 64)),
            ('omit native receipts', lambda d: d.update(native_artifacts=[])),
            ('omit known components', lambda d: d.update(clang_components=[])),
            ('fabricated baseline', lambda d: d['unit_receipt'].update(stdout='FAILED  2 of 10814 checks across 583 cases\n')),
            ('invented native success', lambda d: d['native_receipt'].update(stdout='success')),
            ('invented native argv', lambda d: d['native_receipt']['argv'].__setitem__(1, 'version')),
            ('invented observed argv', lambda d: d['clang_invocations'][0]['argv'].append('--invented')),
            ('relative path', lambda d: d.update(compiler='build/beryl.exe')),
            ('moved receipt', lambda d: d.update(receipt_path='/tmp/toolchain.json')),
        ]
        for name, mutate in mutations:
            with self.subTest(name=name):
                data = copy.deepcopy(self.record)
                mutate(data)
                with self.assertRaises(module.ToolchainError):
                    self.load_record(data)

    def test_compiler_version_must_match_pinned_source(self):
        self.record['compiler_version'] = 'beryl 99.fabricated\n'
        with self.assertRaisesRegex(module.ToolchainError, 'version'):
            self.load_record(self.record)

    def test_duplicate_keys_and_nonfinite_values_rejected(self):
        for raw in ['{"compiler": 1, "compiler": 2}', '{"unexpected": NaN}',
                    '{"unexpected": Infinity}', '{"unexpected": -Infinity}']:
            with self.subTest(raw=raw), self.assertRaises(module.ToolchainError):
                self.load_record(raw)

    def test_receipt_metadata_cannot_execute_commands(self):
        self.record['build_receipt']['argv'] = ['/bin/sh', '-c', 'exit 0']
        with patch.object(module, '_command', side_effect=AssertionError('executed receipt')), \
             self.assertRaises(module.ToolchainError):
            self.load_record(self.record)

    def test_new_config_is_detected(self):
        with tempfile.TemporaryDirectory(prefix='new config with spaces ') as directory:
            (Path(directory) / 'injected.cfg').write_text('-O1\n')
            with patch.dict(os.environ, CLANG_CONFIG_FILE_USER_DIR=directory), \
                 self.assertRaisesRegex(module.ToolchainError, 'configuration'):
                module.load_toolchain(RETAINED)

    def test_native_success_status_does_not_replace_capability_checks(self):
        artifacts = {Path(item['path']).name: Path(item['path']) for item in self.record['native_artifacts']}
        changes = [
            ('native-evidence.json', lambda d: d.update(schema_version=True)),
            ('native-evidence.json', lambda d: d.update(schema_version=2)),
            ('native-evidence.json', lambda d: d.update(extra='unknown')),
            ('native-evidence.json', lambda d: d.update(passes=[])),
            ('native-evidence.json', lambda d: d['passes'][0]['process'].update(exit_code=False)),
            ('native-evidence.json', lambda d: d['passes'][0].update(output_sha256='0' * 64)),
            ('native-evidence.json', lambda d: d['clang'].update(sha256='0' * 64)),
            ('result.json', lambda d: d.update(schema_version=True)),
            ('result.json', lambda d: d['run'].update(exit_code=9)),
            ('result.json', lambda d: d.update(sources=[])),
            ('result.json', lambda d: d.update(native_evidence='/tmp/invented.json')),
        ]
        original = Path.read_text
        for filename, mutate in changes:
            data = json.loads(original(artifacts[filename]))
            mutate(data)
            target, replacement = artifacts[filename], json.dumps(data)
            def read(path, *args, **kwargs):
                return replacement if path == target else original(path, *args, **kwargs)
            with self.subTest(file=filename, data=data), patch.object(Path, 'read_text', read), \
                 self.assertRaises(module.ToolchainError):
                module.load_toolchain(RETAINED)

    def test_exact_exported_copy_keeps_original_paths(self):
        with tempfile.TemporaryDirectory(prefix='receipt copy with spaces ') as directory:
            receipt = Path(directory) / 'toolchain.json'
            receipt.write_bytes(RETAINED.read_bytes())
            toolchain = module.load_toolchain(receipt)
            self.assertEqual(toolchain.receipt_path, RETAINED)
            self.assertEqual(toolchain.compiler, Path(self.record['compiler']))

    def test_modified_copy_cannot_claim_original_receipt_binding(self):
        with tempfile.TemporaryDirectory(prefix='receipt copy with spaces ') as directory:
            receipt = Path(directory) / 'toolchain.json'
            receipt.write_bytes(RETAINED.read_bytes().replace(b'\n', b'\r\n'))
            with self.assertRaisesRegex(module.ToolchainError, 'bound original'):
                module.load_toolchain(receipt)

    def test_component_current_lookup_is_checked(self):
        with tempfile.TemporaryDirectory(prefix='component with spaces ') as directory:
            root = Path(directory)
            old, replacement, lookup = root / 'old.so', root / 'new.so', root / 'lib.so'
            old.write_bytes(b'old retained dependency')
            replacement.write_bytes(b'changed dependency')
            lookup.symlink_to(old)
            identity = module._identity(lookup)
            self.record['clang_components'][0] = {
                'path': str(identity.path), 'sha256': identity.sha256,
                'size': identity.size, 'lookup_path': str(lookup)}
            lookup.unlink()
            lookup.symlink_to(replacement)
            with self.assertRaises(module.ToolchainError):
                self.load_record(self.record)
            self.assertTrue(old.is_file())


class StrictToolchainReceiptTests(unittest.TestCase):
    def test_malformed_receipts_raise_toolchain_error_without_native_tools(self):
        records = ['{}', '[]', 'null', '{', '{"schema_version": 1}',
                   '{"a": 1, "a": 2}', '{"a": NaN}', '{"a": Infinity}', '{"a": -Infinity}']
        with tempfile.TemporaryDirectory(prefix='malformed receipt ') as directory:
            receipt = Path(directory) / 'toolchain.json'
            for raw in records:
                with self.subTest(raw=raw):
                    receipt.write_text(raw)
                    with self.assertRaises(module.ToolchainError):
                        module.load_toolchain(receipt)
