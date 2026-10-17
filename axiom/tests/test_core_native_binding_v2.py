"""Real emit-c/private ABI seam probe; no test-only callback adapter executes Core."""
from dataclasses import replace
import importlib
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from axiom.core_toolchain import load_toolchain


FIXTURES = Path(__file__).parent / 'fixtures/core_native_v2'
RECEIPT = Path('/workspace/scratch/cloud-onboarding-native-20261016/'
               'qualification-57lxdp8j/receipts/toolchain.json')
TYPE = 'be_t_List_3ci32_3e'
PREFLIGHT = 'be_i_axiom_5fbuffer_5ffixture_2eax_5fpreflight'
BODY = 'be_i_axiom_5fbuffer_5ffixture_2eax_5fbody'


def capture(argv, cwd, stem, *, input_bytes=None):
    """Retain exact bytes and argv even on failed/timeout processes."""
    try:
        result = subprocess.run([str(a) for a in argv], cwd=cwd, input=input_bytes,
                                capture_output=True, timeout=60)
        out, err, code, timeout = result.stdout, result.stderr, result.returncode, False
    except subprocess.TimeoutExpired as exc:
        out, err, code, timeout = exc.stdout or b'', exc.stderr or b'', None, True
    stem.with_suffix('.stdout').write_bytes(out)
    stem.with_suffix('.stderr').write_bytes(err)
    if input_bytes is not None:
        stem.with_suffix('.stdin').write_bytes(input_bytes)
    stem.with_suffix('.json').write_text(json.dumps({
        'argv': [str(a) for a in argv], 'cwd': str(cwd), 'returncode': code,
        'timed_out': timeout,
        'stdin_sha256': None if input_bytes is None else hashlib.sha256(input_bytes).hexdigest(),
    }, indent=2) + '\n')
    return code, out, err


def seal_evidence(semantic, qualification):
    """Inventory the complete tiny evidence stores; no large-artifact claim.

    All files here fit one 1 MiB chunk. O1 owns general chunked transport. File
    modes discourage accidental edits; they do not establish same-UID isolation.
    """
    for root, quota in ((semantic, 256 * 1024**2), (qualification, 512 * 1024**2)):
        files = sorted(root.rglob('*'))
        if any(path.is_symlink() for path in files):
            raise AssertionError('symlink in evidence store')
        inventory = {}
        for path in files:
            if path.is_file():
                if path.stat().st_size > 1024**2:
                    raise AssertionError('tiny evidence file exceeds one chunk')
                path.chmod(0o555 if path.name == 'worker' else 0o444)
                inventory[str(path.relative_to(root))] = {
                    'size': path.stat().st_size,
                    'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                    'mode': path.stat().st_mode & 0o777,
                }
        record = {'quota_bytes': quota, 'files': inventory}
        index = root / 'inventory.json'
        index.write_text(json.dumps(record, sort_keys=True, indent=2) + '\n')
        index.chmod(0o444)
        if sum(item['size'] for item in inventory.values()) + index.stat().st_size > quota:
            raise AssertionError('evidence quota exceeded')
        actual = {str(path.relative_to(root)) for path in root.rglob('*') if path.is_file()}
        if actual != set(inventory) | {'inventory.json'}:
            raise AssertionError('evidence inventory differs')
        for name, identity in inventory.items():
            path = root / name
            if identity != {'size': path.stat().st_size,
                            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                            'mode': path.stat().st_mode & 0o777}:
                raise AssertionError('evidence changed while sealing')
        for directory in sorted((p for p in root.rglob('*') if p.is_dir()), reverse=True):
            directory.chmod(0o555)
        root.chmod(0o555)


class NativeBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        module_name = 'axiom.core_native_v2'
        cls.module = importlib.import_module(module_name) if importlib.util.find_spec(module_name) else None
        if cls.module is None:
            return  # Each test reports the intended missing binding assertion (RED).
        if not (os.environ.get('AXIOM_TEST_CORE') and os.environ.get('AXIOM_TEST_CLANG')):
            if os.environ.get('AXIOM_V2_REQUIRE_NATIVE') == '1':
                raise AssertionError('required native qualification needs explicit Core/Clang selectors')
            raise unittest.SkipTest('explicit qualified Core/Clang selectors not provided')
        cls.toolchain = load_toolchain(Path(os.environ.get('AXIOM_V2_TOOLCHAIN_RECEIPT', RECEIPT)))
        if Path(os.environ['AXIOM_TEST_CORE']).resolve() != cls.toolchain.source_repository:
            raise AssertionError('Core source selector differs from qualified original')
        if Path(os.environ['AXIOM_TEST_CLANG']).resolve() != cls.toolchain.clang:
            raise AssertionError('Clang selector differs from qualification')
        evidence_parent = Path(os.environ.get('AXIOM_V2_BINDING_EVIDENCE', '/tmp'))
        evidence_parent.mkdir(parents=True, exist_ok=True)
        cls.evidence = Path(tempfile.mkdtemp(prefix='axiom-B2-binding-', dir=evidence_parent))
        cls.semantic = cls.evidence / 'semantic'
        cls.qualification = cls.evidence / 'qualification'
        cls.semantic.mkdir()
        cls.qualification.mkdir()
        cls.addClassCleanup(seal_evidence, cls.semantic, cls.qualification)
        print('\nB2 evidence: ' + str(cls.evidence), flush=True)
        cls.source = FIXTURES / 'tiny-1x2.be'
        cls.source = cls.source.resolve()
        for name in ('tiny-1x2.be', 'tiny-1x2-cases.json'):
            shutil.copyfile(FIXTURES / name, cls.semantic / name)
        code, out, err = capture([cls.toolchain.compiler, 'emit-c', cls.source],
                                 cls.qualification, cls.qualification / 'emit-c')
        if code != 0:
            raise AssertionError('actual emit-c failed: ' + err.decode(errors='replace'))
        cls.generated = cls.qualification / 'generated.c'
        cls.generated.write_bytes(out)  # stdout bytes unchanged, including final newline.
        cls.manifest = cls.module._bind_fixture(cls.toolchain, (cls.source,), cls.generated)
        (cls.qualification / 'binding-manifest.json').write_text(cls.manifest.to_json())
        shutil.copyfile(cls.toolchain.receipt_path, cls.qualification / 'original-toolchain-receipt.json')
        for name in ('beryl_rt.h', 'beryl_rt.c'):
            shutil.copyfile(cls.toolchain.snapshot / 'runtime' / name, cls.qualification / name)
        cls.native_names = ('buffer_host.h', 'buffer_host.c', 'operation_allocator.h',
                            'operation_allocator.c', 'host_protocol.c')
        for name in cls.native_names:
            shutil.copyfile(Path(__file__).resolve().parents[1] / 'native/v2' / name,
                            cls.qualification / name)
        cls.assertions = cls.module._binding_assertions(cls.manifest)
        cls.host = (FIXTURES / 'tiny-binding-host.c').read_text()
        cls.good = cls.compile('qualified')
        if cls.good[0] != 0:
            raise AssertionError('private binding compile failed: ' + cls.good[2].decode(errors='replace'))
        cls.execution_inputs = {}
        for path in (cls.good[3] / 'generated.c', cls.good[3] / 'binding.h',
                     cls.good[3] / 'host.c', cls.good[3] / 'worker',
                     cls.qualification / 'beryl_rt.h', cls.qualification / 'beryl_rt.c',
                     *(cls.qualification / name for name in cls.native_names)):
            path.chmod(0o555 if path.name == 'worker' else 0o444)
            cls.execution_inputs[str(path)] = {
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'size': path.stat().st_size, 'mode': path.stat().st_mode & 0o777,
            }
        (cls.qualification / 'execution-inputs.json').write_text(json.dumps(cls.execution_inputs, indent=2) + '\n')

    @classmethod
    def compile(cls, name, *, generated=None, assertions=None, extra=''):
        directory = cls.qualification / name
        directory.mkdir()
        (directory / 'generated.c').write_bytes(cls.generated.read_bytes() if generated is None else generated)
        (directory / 'binding.h').write_text(cls.assertions if assertions is None else assertions)
        (directory / 'host.c').write_text(cls.host + '\n#include "buffer_host.c"\n#include "operation_allocator.c"\n' + extra)
        argv = [cls.toolchain.clang, '-std=c11', '-O0', '-fvisibility=hidden',
                '-Werror=incompatible-pointer-types', '-Werror=implicit-function-declaration',
                '-Werror=int-conversion', '-I', cls.qualification,
                directory / 'host.c', '-o', directory / 'worker']
        if name == 'qualified':
            cls.module._validate_binding(cls.manifest, cls.toolchain, (cls.source,), directory / 'generated.c')
        code, out, err = capture(argv, directory, directory / 'compile')
        if name == 'qualified' and code == 0:
            # Same translation unit, compiler/configuration and flags as worker.
            for label, mode in [('llvm', ['-S', '-emit-llvm']), ('assembly', ['-S'])]:
                output = directory / ('worker.ll' if label == 'llvm' else 'worker.s')
                evidence_code, _, evidence_err = capture(argv[:-2] + mode + ['-o', output],
                                                         directory, directory / label)
                if evidence_code != 0:
                    raise AssertionError(label + ' emission failed: ' + evidence_err.decode(errors='replace'))
            cls.module._validate_binding(cls.manifest, cls.toolchain, (cls.source,), directory / 'generated.c')
        return code, out, err, directory

    def setUp(self):
        self.assertIsNotNone(self.module, 'missing pinned private Core binding implementation')

    def test_emit_stdout_is_unchanged_and_manifest_revalidates(self):
        self.assertEqual(self.generated.read_bytes(), (self.qualification / 'emit-c.stdout').read_bytes())
        self.module._validate_binding(self.manifest, self.toolchain, (self.source,), self.generated)
        self.assertEqual(self.manifest.descriptor_typedef, TYPE)
        self.assertEqual(self.manifest.source_order, (str(self.source),))

    def test_all_complete_native_states_match_independent_hand_expectations(self):
        cases = json.loads((FIXTURES / 'tiny-1x2-cases.json').read_text())
        for case in cases:
            with self.subTest(case=case['name']):
                data = (' '.join(map(str, case['input'] + case['initial_output'])) + '\n').encode()
                self.revalidate_execution()
                code, out, err = capture([self.good[3] / 'worker', 'invoke'], self.qualification,
                                         self.semantic / ('run-' + case['name']), input_bytes=data)
                self.revalidate_execution()
                self.assertEqual(code, 0, err.decode(errors='replace'))
                state = json.loads(out)
                self.assertEqual(state['input'], case['input'])
                self.assertEqual(state['output'], case['final_output'])
                self.assertEqual(state['first_bad_index'], case['first_bad_index'])
                self.assertEqual(state['status'], case['status'])
                self.assertEqual(state['scratch_allocations'], int(case['status'] == 'success'))
                self.assertEqual(state['scratch_live_bytes'], 0)
                self.assertEqual(state['body_allocation_attempts'], 0)
                expected_events = ['preflight']
                if case['status'] == 'success':
                    expected_events += ['scratch_allocate', 'scratch_zero', 'body', 'descriptors', 'scratch_free']
                else:
                    expected_events += ['descriptors']
                self.assertEqual(state['events'], expected_events + ['acquire', 'input_output_free'])

    def revalidate_execution(self):
        self.module._validate_binding(self.manifest, self.toolchain, (self.source,), self.generated)
        for name, identity in self.execution_inputs.items():
            path = Path(name)
            self.assertEqual({'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                              'size': path.stat().st_size, 'mode': path.stat().st_mode & 0o777}, identity)

    def test_retained_build_closure_has_exact_emit_bytes_and_inspection_outputs(self):
        self.assertEqual((self.good[3] / 'generated.c').read_bytes(), self.generated.read_bytes())
        self.assertTrue((self.good[3] / 'worker.ll').is_file(), 'missing retained LLVM IR')
        self.assertTrue((self.good[3] / 'worker.s').is_file(), 'missing retained assembly')
        llvm = (self.good[3] / 'worker.ll').read_text()
        self.assertIn('@' + PREFLIGHT + '(', llvm)
        self.assertIn('@' + BODY + '(', llvm)
        self.revalidate_execution()

    def test_worker_protocol_cannot_select_generated_helpers(self):
        for i, operation in enumerate(('ax_body', 'ax_preflight', BODY, PREFLIGHT, 'invoke extra')):
            code, out, _ = capture([self.good[3] / 'worker', operation], self.qualification,
                                   self.qualification / ('protocol-' + str(i)))
            self.assertEqual(code, 64)
            self.assertEqual(out, b'')

    def test_executable_helpers_have_hidden_visibility_and_no_dynamic_exports(self):
        worker = self.good[3] / 'worker'
        for kind, argv in [('symbols', ['/usr/bin/readelf', '-Ws', worker]),
                           ('dynamic', ['/usr/bin/nm', '-D', '--defined-only', worker])]:
            code, out, err = capture(argv, self.qualification, self.qualification / kind)
            self.assertEqual(code, 0, err.decode(errors='replace'))
            if kind == 'dynamic':
                self.assertNotIn(BODY.encode(), out)
                self.assertNotIn(PREFLIGHT.encode(), out)
            else:
                for symbol in (BODY, PREFLIGHT):
                    lines = [line for line in out.decode().splitlines() if line.endswith(' ' + symbol)]
                    self.assertEqual(len(lines), 1)
                    self.assertRegex(lines[0], r'LOCAL\s+DEFAULT|GLOBAL\s+HIDDEN')

    def reject_compile(self, name, **kwargs):
        code, _, err, directory = self.compile(name, **kwargs)
        self.assertNotEqual(code, 0, 'binding mutant unexpectedly compiled')
        self.assertFalse((directory / 'worker').exists())
        return err.decode(errors='replace')

    def test_wrong_symbol_fails_before_execution(self):
        err = self.reject_compile('wrong-symbol', assertions=self.assertions.replace(PREFLIGHT, PREFLIGHT + '_wrong'))
        self.assertIn('undeclared', err)

    def test_wrong_const_fails_before_execution(self):
        generated = self.generated.read_bytes().replace(
            ('const ' + TYPE + ' *restrict').encode(), (TYPE + ' *restrict').encode())
        err = self.reject_compile('wrong-const', generated=generated)
        self.assertIn('preflight signature', err)
        self.assertIn('body signature', err)

    def test_wrong_return_signature_fails_before_execution(self):
        generated = self.generated.read_bytes().replace(('void ' + BODY).encode(), ('int32_t ' + BODY).encode())
        err = self.reject_compile('wrong-signature', generated=generated)
        self.assertIn('body signature', err)

    def test_changed_typedef_layout_fails_before_execution(self):
        generated = self.generated.read_bytes().replace(b'int32_t len; int32_t cap;', b'int64_t len; int32_t cap;')
        err = self.reject_compile('wrong-layout', generated=generated)
        self.assertIn('len type', err)
        self.assertIn('descriptor size', err)

    def test_separately_declared_descriptor_is_incompatible(self):
        extra = ('\ntypedef struct { int32_t *data; int32_t len; int32_t cap; } lookalike;\n'
                 'int32_t incompatible(lookalike *p) { return ' + PREFLIGHT + '(p); }\n')
        self.assertIn('incompatible pointer', self.reject_compile('lookalike', extra=extra))

    def test_modified_generated_c_is_rejected_by_manifest(self):
        altered = self.qualification / 'altered-generated.c'
        altered.write_bytes(self.generated.read_bytes() + b'\n/* changed */\n')
        with self.assertRaisesRegex(self.module.NativeBindingUnavailable, 'binding identity') as caught:
            self.module._validate_binding(self.manifest, self.toolchain, (self.source,), altered)
        (self.qualification / 'modified-generated-guard.json').write_text(json.dumps({
            'observed_error': str(caught.exception), 'execution_attempted': False,
            'original_sha256': self.manifest.generated_c_sha256,
            'modified_sha256': hashlib.sha256(altered.read_bytes()).hexdigest(),
        }, indent=2) + '\n')

    def test_wrong_core_pin_is_rejected_before_binding(self):
        with self.assertRaisesRegex(self.module.NativeBindingUnavailable, 'Core pin') as caught:
            self.module._bind_fixture(replace(self.toolchain, source_pin='0' * 40), (self.source,), self.generated)
        (self.qualification / 'wrong-pin-guard.json').write_text(json.dumps({
            'observed_error': str(caught.exception), 'execution_attempted': False,
            'wrong_pin': '0' * 40, 'expected_pin': self.manifest.core_pin,
        }, indent=2) + '\n')
        with self.assertRaisesRegex(self.module.NativeBindingUnavailable, 'binding identity'):
            self.module._validate_binding(replace(self.manifest, core_pin='0' * 40),
                                          self.toolchain, (self.source,), self.generated)

    def test_manifest_cannot_misstate_asserted_pin_or_signatures(self):
        for binding in (replace(self.manifest, core_pin='0' * 40),
                        replace(self.manifest, signatures=('incorrect', 'incorrect'))):
            with self.subTest(binding=binding), self.assertRaises(self.module.NativeBindingUnavailable):
                self.module._binding_assertions(binding)


if __name__ == '__main__':
    unittest.main()
