"""B3 lifecycle tests, not production invocation or general allocation admission.

Native tests require explicit receipt-matching compiler selectors. Local retained
command files are diagnostic proof evidence; O1 owns transport/qualification stores.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from axiom.core_toolchain import load_toolchain
from axiom.core_native_v2 import _bind_fixture, _binding_assertions, _validate_binding
from tests.test_core_native_binding_v2 import RECEIPT, FIXTURES, capture
from tests.helpers import stencil_source
from tests.support.buffer_contract_v2 import sizes

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'native/v2'
SOURCES = ('operation_allocator.h', 'operation_allocator.c', 'buffer_host.h',
           'buffer_host.c', 'host_protocol.c')
SANITIZERS = Path(os.environ.get('AXIOM_V2_SANITIZER_ROOT',
    '/workspace/scratch/axiom-scalability-execution-20261016/sanitizer-runtime-jtv4b5ih'))
RESOURCE = SANITIZERS / 'prefix/usr/lib/llvm-19/lib/clang/19'
# Exact prerequisite inventory reviewed for this separate scratch resource prefix.
RESOURCE_INVENTORY_SHA = '4ed2d0c3bfa9c2c3507dc4b08dcf051a172c45fccca7e8f4ef8552c1a24b7b91'
SANITIZER_ENV = {'ASAN_OPTIONS': 'detect_leaks=1:halt_on_error=1:symbolize=0',
                 'UBSAN_OPTIONS': 'halt_on_error=1:print_stacktrace=1:symbolize=0',
                 'LSAN_OPTIONS': 'exitcode=23:symbolize=0'}


def identity(path):
    return {'size': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def retain_inventory(root):
    """Inventory diagnostic test outputs; not a new chunked artifact protocol."""
    files = sorted(p for p in root.rglob('*') if p.is_file())
    if any(p.is_symlink() for p in root.rglob('*')):
        raise AssertionError('symlink in local native evidence')
    if sum(p.stat().st_size for p in files) > 256 * 1024**2:
        raise AssertionError('native test evidence quota exceeded')
    inventory = {str(p.relative_to(root)): identity(p) for p in files}
    (root / 'local-evidence-inventory.json').write_text(json.dumps(inventory, sort_keys=True, indent=2) + '\n')
    for p in (*files, root / 'local-evidence-inventory.json'):
        p.chmod(0o555 if p.stat().st_mode & 0o111 else 0o444)
    root.chmod(0o555)


class PortableContractTests(unittest.TestCase):
    def test_native_lifecycle_implementation_is_present(self):
        for name in SOURCES:
            self.assertTrue((NATIVE / name).is_file(), 'missing B3 implementation: ' + name)

    def test_portable_contract_sizes_without_materializing_large_arrays(self):
        # Independent B1/C2 contract: native implementation is tested below.
        for h, w, p, q in ((1, 1, 4, 1), (8191, 1023, 8388608, 8379393),
                            (8192, 1, 16386, 8192)):
            result = sizes(stencil_source(h, w, None), p)
            self.assertEqual((result.input_cells, result.output_cells), (p, q))
            self.assertEqual(result.state_bytes, 4 * (p + q))
            self.assertEqual(result.scratch_bytes, 4 * p)
        self.assertEqual(sizes(stencil_source(1, 2), 0).scratch_bytes, 0)
        with self.assertRaises(ValueError):
            sizes(stencil_source(1, 2), 6, size_max=23)


class NativeLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (os.environ.get('AXIOM_TEST_CORE') and os.environ.get('AXIOM_TEST_CLANG')):
            if os.environ.get('AXIOM_V2_REQUIRE_NATIVE') == '1':
                raise AssertionError('required native qualification needs explicit Core/Clang selectors')
            raise unittest.SkipTest('explicit qualified Core/Clang selectors not provided')
        cls.toolchain = load_toolchain(Path(os.environ.get('AXIOM_V2_TOOLCHAIN_RECEIPT', RECEIPT)))
        if Path(os.environ['AXIOM_TEST_CORE']).resolve() != cls.toolchain.source_repository:
            raise AssertionError('Core source selector differs from qualification')
        if Path(os.environ['AXIOM_TEST_CLANG']).resolve() != cls.toolchain.clang:
            raise AssertionError('Clang selector differs from qualification')
        parent = Path(os.environ.get('AXIOM_V2_LIFECYCLE_EVIDENCE', '/tmp'))
        parent.mkdir(parents=True, exist_ok=True)
        cls.evidence = Path(tempfile.mkdtemp(prefix='axiom-B3-', dir=parent))
        cls.addClassCleanup(retain_inventory, cls.evidence)
        print('\nB3 evidence: ' + str(cls.evidence), flush=True)
        cls.source = (FIXTURES / 'tiny-1x2.be').resolve()
        code, out, err = capture([cls.toolchain.compiler, 'emit-c', cls.source],
                                 cls.evidence, cls.evidence / 'emit-c')
        if code != 0:
            raise AssertionError(err.decode())
        cls.generated = cls.evidence / 'generated.c'
        cls.generated.write_bytes(out)
        cls.binding = _bind_fixture(cls.toolchain, (cls.source,), cls.generated)
        (cls.evidence / 'binding.h').write_text(_binding_assertions(cls.binding))
        (cls.evidence / 'binding-manifest.json').write_text(cls.binding.to_json())
        shutil.copyfile(cls.toolchain.receipt_path, cls.evidence / 'toolchain.json')
        shutil.copyfile(cls.source, cls.evidence / cls.source.name)
        for name in ('beryl_rt.h', 'beryl_rt.c'):
            shutil.copyfile(cls.toolchain.snapshot / 'runtime' / name, cls.evidence / name)
        for name in SOURCES:
            if not (NATIVE / name).is_file():
                raise AssertionError('missing B3 implementation: ' + name)
            shutil.copyfile(NATIVE / name, cls.evidence / name)
        for name in ('test_buffer_host_v2.c', 'test_operation_allocator_v2.c'):
            shutil.copyfile(ROOT / 'tests/native' / name, cls.evidence / name)
        cls.inputs = {str(p): identity(p) for p in cls.evidence.iterdir() if p.is_file()}
        (cls.evidence / 'build-input-identities.json').write_text(json.dumps(cls.inputs, indent=2) + '\n')

    def revalidate(self, *, sanitizer=False):
        self.toolchain.revalidate_identity()
        _validate_binding(self.binding, self.toolchain, (self.source,), self.generated)
        for path, expected in self.inputs.items():
            self.assertEqual(identity(Path(path)), expected)
        if sanitizer:
            inventory_file = SANITIZERS / 'overridden-resource-inventory.json'
            self.assertTrue(inventory_file.is_file(), 'sanitizer prerequisite unavailable')
            self.assertEqual(identity(inventory_file)['sha256'], RESOURCE_INVENTORY_SHA)
            inventory = json.loads(inventory_file.read_text())
            actual = {str(p.relative_to(RESOURCE)) for p in RESOURCE.rglob('*')
                      if p.is_file() or p.is_symlink()}
            self.assertEqual(actual, {item['path'] for item in inventory})
            for item in inventory:
                path = RESOURCE / item['path']
                self.assertFalse(path.is_symlink(), 'admitted resource inventory has no symlinks')
                self.assertEqual(identity(path), {key: item[key] for key in ('size', 'sha256')})

    def execute(self, binary, label, *, args=(), sanitizer=False, diagnostic=None):
        self.revalidate(sanitizer=sanitizer)
        before = identity(binary)
        overrides = SANITIZER_ENV if sanitizer else {}
        argv = [str(binary), *args]
        try:
            proc = subprocess.run(argv, capture_output=True, env=os.environ | overrides, timeout=60)
            out, err, code, timed_out = proc.stdout, proc.stderr, proc.returncode, False
        except subprocess.TimeoutExpired as exc:
            out, err, code, timed_out = exc.stdout or b'', exc.stderr or b'', None, True
        stem = self.evidence / label
        stem.with_suffix('.stdout').write_bytes(out)
        stem.with_suffix('.stderr').write_bytes(err)
        stem.with_suffix('.json').write_text(json.dumps({
            'argv': argv, 'returncode': code, 'timed_out': timed_out,
            'environment_overrides': overrides, 'binary_identity': before,
        }, indent=2) + '\n')
        self.assertFalse(timed_out)
        self.assertEqual(identity(binary), before)
        self.revalidate(sanitizer=sanitizer)
        if diagnostic is None:
            self.assertEqual(code, 0, err.decode(errors='replace'))
            self.assertEqual(err, b'')
            self.assertIn(b'cleanup', out)
        else:
            self.assertNotEqual(code, 0, 'fault control was not detected')
            self.assertIn(diagnostic, err)

    def run_native(self, name, source, flags=(), sanitizer=False):
        self.revalidate(sanitizer=sanitizer)
        binary = self.evidence / name
        argv = [self.toolchain.clang, '-std=c11', '-D_GNU_SOURCE', '-DAX_BUFFER_TESTING',
                '-O1', '-g', '-fno-omit-frame-pointer', '-fno-builtin', '-fvisibility=hidden',
                '-Wall', '-Wextra', '-Werror=incompatible-pointer-types', '-Werror=int-conversion',
                '-Werror=implicit-function-declaration', *flags, '-I', self.evidence,
                self.evidence / source, self.evidence / 'buffer_host.c',
                self.evidence / 'operation_allocator.c', '-o', binary]
        code, _, err = capture(argv, self.evidence, self.evidence / (name + '-compile'))
        self.assertEqual(code, 0, err.decode(errors='replace'))
        self.execute(binary, name + '-run', sanitizer=sanitizer)
        return binary

    def test_ordinary_size_allocator_and_host_lifecycle(self):
        self.run_native('allocator', 'test_operation_allocator_v2.c')
        self.run_native('host', 'test_buffer_host_v2.c')

    def test_independent_linker_interposition_with_positive_and_uncovered_controls(self):
        binary = self.run_native('interposed', 'test_buffer_host_v2.c',
            ['-DAX_ALLOC_INTERPOSE', *[f'-Wl,--wrap={n}' for n in
                ('malloc', 'calloc', 'realloc', 'free', 'aligned_alloc', 'posix_memalign')]])
        self.execute(binary, 'interposed-detect-outside-operation-allocator',
                     args=('unexpected-body-allocation',), diagnostic=b'Assertion')

    def test_actual_host_asan_ubsan_and_lsan(self):
        self.revalidate(sanitizer=True)
        shutil.copyfile(SANITIZERS / 'overridden-resource-inventory.json',
                        self.evidence / 'sanitizer-resource-inventory.json')
        for mode in ('address,undefined', 'leak'):
            for source in ('test_operation_allocator_v2.c', 'test_buffer_host_v2.c'):
                binary = self.run_native(mode.replace(',', '-') + '-' + source[:-2], source,
                    ['-resource-dir=' + str(RESOURCE), '-fsanitize=' + mode,
                     '-fno-sanitize-recover=all'], True)
                if source == 'test_buffer_host_v2.c':
                    faults = (('uaf', b'heap-use-after-free'), ('overflow', b'signed integer overflow')) if mode != 'leak' else (
                        ('leak', b'LeakSanitizer: detected memory leaks'),)
                    for fault, diagnostic in faults:
                        self.execute(binary, mode.replace(',', '-') + '-fault-' + fault,
                                     args=('sanitizer-fault', fault), sanitizer=True, diagnostic=diagnostic)


if __name__ == '__main__':
    unittest.main()
