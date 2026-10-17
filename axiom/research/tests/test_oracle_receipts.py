"""Temporary synthetic approvals exercise mechanics, never production qualification."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
import copy
import tempfile
import unittest
try:
    from research import oracle_receipt as receipt
except ModuleNotFoundError:
    import oracle_receipt as receipt

class QualificationBoundaryTests(unittest.TestCase):
    def test_forged_closed_handles_cannot_delete_caller_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            for handle_type in (receipt.OracleQualification, receipt.VerifiedOracle):
                with self.subTest(handle_type=handle_type.__name__):
                    victim = Path(directory)/handle_type.__name__
                    victim.mkdir()
                    marker = victim/'caller-data'
                    marker.write_text('must survive forged cleanup')
                    forged = object.__new__(handle_type)
                    forged._closed = True
                    forged._cleanup = (victim,)
                    with self.assertRaises(ValueError):
                        forged.close()
                    self.assertEqual(marker.read_text(), 'must survive forged cleanup')

    def test_forged_qualification_does_not_admit(self):
        with self.assertRaises(TypeError):
            receipt.OracleQualification()
        forged = object.__new__(receipt.OracleQualification)
        with self.assertRaises(ValueError):
            forged.revalidate()

    def test_qualification_inventory_complete_and_bounded(self):
        with self.assertRaises(ValueError):
            receipt.OracleQualificationLimits(max_qualification_bytes=536_870_913)
        with self.assertRaises(ValueError):
            receipt.OracleQualificationLimits(max_files=True)

    def test_qualification_close_and_capacity(self):
        forged = object.__new__(receipt.OracleQualification)
        with self.assertRaises(ValueError):
            forged.close()


# Temporary fictitious assertions exercise policy mechanics; never production approval.
from dataclasses import asdict, replace
import hashlib
import json
import os
import shutil
import struct
from unittest.mock import patch
from axiom import artifact_chunks_v2 as blobs
from axiom.invocation_v2 import InvocationLimits, write_invocation, verify_invocation
from axiom.source_profiles import SourceProfileV2
try:
    from research import source_oracle
    from research import state_artifacts as state
except ModuleNotFoundError:
    import source_oracle
    import state_artifacts as state


def source(h=1, w=1):
    return f'''module demo;
shape H = {h};
shape W = {w};
input image: i32[H+1,W+1] in 0..=1023;
let p[r in 0..H+1,c in 0..W+1] = (image[r,c]+1)*(image[r,c]+1);
output result[r in 0..H,c in 0..W] = ((p[r,c]+p[r,c+1])+p[r+1,c])+p[r+1,c+1];
require plan_workspace_bytes <= 64;
prefer multiplication_ops;
'''.encode()


def document(root, name, value):
    raw = blobs.canonical_json(value)
    (root/name).write_bytes(raw)
    return dict(path=name, sha256=hashlib.sha256(raw).hexdigest(), byte_length=len(raw))


def blob(root, name, blocks, length):
    ref = blobs.write_blob(blocks, length, root/name, limits=blobs.BlobLimits())
    return dict(path=ref.manifest_path.relative_to(root).as_posix(),
                manifest_sha256=ref.manifest_sha256, sha256=ref.sha256, byte_length=ref.byte_length)


def file_blocks(path):
    with path.open('rb') as stream:
        while block := stream.read(65_536):
            yield block


def synthetic_approval(root):
    """Real complete runtime bytes; expressly fictitious test/review assertions."""
    runtime = receipt._runtime_paths()
    repository = Path(__file__).resolve().parents[2]
    python = Path(sys.executable).resolve().parents[1]
    roots = (receipt.OracleLiveRoot('repository', repository),
             receipt.OracleLiveRoot('python', python), receipt.OracleLiveRoot('system', Path('/usr/lib')))
    def logical(path):
        for entry in roots:
            if path.is_relative_to(entry.directory):
                return entry.name+'/'+path.relative_to(entry.directory).as_posix()
        raise AssertionError('unmapped actual runtime path: '+str(path))
    inventory = []
    for number, (path, role) in enumerate(sorted(runtime.items())):
        inventory.append(dict(role=role, logical_path=logical(path),
            blob=blob(root, f'inventory/{number}', file_blocks(path), path.stat().st_size)))
    inventory.sort(key=lambda i: i['logical_path'])
    trusted = document(root, 'trusted.json', dict(schema='axiom-oracle-trusted-base-v1', assumptions=[
        'SYNTHETIC TEST ONLY; no actual review or production qualification.',
        'Shared parser/model/profile/state primitives; Python/runtime/OS correctness.',
        'Trusted controller/reviewer, loaded-code honesty and stable files.']))
    qualification = document(root, 'qualification.json', dict(schema='axiom-oracle-qualification-v1',
        entrypoint='source_oracle.evaluate_source_state', runtime_assumption='trusted-fresh-python-in-process-v1',
        source_profile=asdict(SourceProfileV2()), versions=receipt._VERSIONS,
        python=dict(implementation='cpython', version=list(sys.version_info[:3]),
                    executable_logical_path=logical(Path(sys.executable).resolve())),
        inventory=inventory, trusted_base=trusted))
    inputs = []
    for number, (role, path) in enumerate([
        ('test_source', Path(__file__).resolve()),
        ('test_source', repository/'research/tests/test_source_oracle.py'),
        ('test_source', repository/'research/tests/test_receipts.py'),
        ('test_source', repository/'research/tests/test_manifest.py'),
        ('test_comparator', repository/'research/experiment_manifest.py'),
        ('test_comparator', repository/'research/receipt_admission.py'),
        ('test_comparator', repository/'src/axiom/reference.py'),
        ('fixture', repository/'tests/fixtures/inputs/boundary_cases.json'),
        ('protocol', repository/'research/protocol/source-oracle-v1.md')]):
        inputs.append(dict(role=role, logical_path=logical(path),
                           blob=blob(root, f'inputs/{number}', file_blocks(path), path.stat().st_size)))
    inputs.sort(key=lambda i: i['logical_path'])
    note = b'SYNTHETIC UNIT TEST ASSERTIONS ONLY. No real test execution or independent approval.\n'
    log = blob(root, 'log', [note], len(note))
    runs = [dict(command_id=command, argv=['synthetic-only'], mode=mode,
                 tests=1, passed=1, failed=0, errors=0, skipped=0, exit_code=0, log=log)
            for command in ('o3', 'source_oracle', 'synthetic_receipts') for mode in ('normal', 'optimized')]
    evidence = document(root, 'tests.json', dict(schema='axiom-oracle-tests-v1',
        qualification_sha256=qualification['sha256'], inputs=inputs, runs=runs))
    review = document(root, 'review.json', dict(schema='axiom-oracle-review-v1',
        qualification_sha256=qualification['sha256'], test_evidence_sha256=evidence['sha256'],
        reviewer='SYNTHETIC TEMPORARY UNIT FIXTURE', decision='approved', unresolved_findings=[], record=log))
    approved = document(root, 'approval.json', dict(schema='axiom-oracle-approval-v1',
        qualification=qualification, test_evidence=evidence, review=review))
    return roots, approved['sha256']


class SelectedQualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.subject_temp = tempfile.TemporaryDirectory(prefix='o3-SYNTHETIC-policy-')
        cls.subject = Path(cls.subject_temp.name)
        cls.roots, cls.approved = synthetic_approval(cls.subject)

    @classmethod
    def tearDownClass(cls):
        cls.subject_temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='o3-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.serial = 0

    def select(self, **kwargs):
        self.serial += 1
        handle = receipt.select_oracle_qualification(self.subject/'approval.json',
            approved_root_sha256=kwargs.pop('approved', self.approved), live_roots=self.roots,
            scratch_directory=self.root/f'scratch-{self.serial}', **kwargs)
        self.addCleanup(handle.close)
        return handle

    def mutated_subject(self, change):
        root = self.root/'changed'
        shutil.copytree(self.subject, root)
        change(root)
        return root

    def select_changed(self, root, approved=None, **kwargs):
        return receipt.select_oracle_qualification(root/'approval.json',
            approved_root_sha256=approved or self.approved, live_roots=self.roots,
            scratch_directory=self.root/'bad-scratch', **kwargs)

    def test_forged_qualification_does_not_admit(self):
        with self.assertRaises(ValueError):
            self.select(approved='0'*64)
        handle = self.select()
        handle.revalidate()
        forged = object.__new__(receipt.OracleQualification)
        with self.assertRaises(ValueError):
            forged.revalidate()
        with self.assertRaises((TypeError, ValueError)):
            copy.copy(handle).revalidate()
        root = self.mutated_subject(lambda p: (p/'review.json').write_bytes(b'{}'))
        handle.close()
        with self.assertRaises(ValueError):
            self.select_changed(root)

    def test_qualification_inventory_complete_and_bounded(self):
        with patch.object(receipt._Ledger, 'verify_blob', side_effect=AssertionError('bulk read before quota')):
            with self.assertRaises(ValueError):
                self.select(limits=receipt.OracleQualificationLimits(max_qualification_bytes=100))
        root = self.mutated_subject(lambda p: None)
        data = json.loads((root/'qualification.json').read_bytes())
        executable = next(x for x in data['inventory'] if x['role'] == 'python_executable')
        self.assertGreater(executable['blob']['byte_length'], 16_777_216)
        manifest = root/executable['blob']['path']
        chunks = json.loads(manifest.read_bytes())['chunks']
        last = manifest.parent/chunks[-1]['path']
        last.chmod(0o600)
        with last.open('r+b') as stream:
            stream.seek(-1, 2)
            old = stream.read(1)
            stream.seek(-1, 2)
            stream.write(bytes([old[0]^1]))
        with self.assertRaises(ValueError):
            self.select_changed(root)
        self.assertFalse((self.root/'bad-scratch').exists())

    def test_qualification_close_and_capacity(self):
        handle = self.select()
        with self.assertRaises(ValueError):
            self.select()
        handle.close()
        handle.close()
        with self.assertRaises(ValueError):
            handle.revalidate()
        self.select()

    def test_changed_live_bytes_and_missing_runtime_fail(self):
        actual = receipt._runtime_paths()
        missing = dict(actual)
        missing.pop(next(p for p, r in missing.items() if r == 'runtime_library'))
        with patch.object(receipt, '_runtime_paths', return_value=missing):
            with self.assertRaises(ValueError):
                self.select()
        with patch.object(receipt, '_hash_live', return_value='0'*64):
            with self.assertRaises(ValueError):
                self.select()

    def test_closed_schema_paths_and_explicit_selection(self):
        root = self.mutated_subject(lambda p: None)
        approval = json.loads((root/'approval.json').read_bytes())
        approval['command'] = 'never execute'
        ref = document(root, 'approval.json', approval)
        with self.assertRaises(ValueError):
            self.select_changed(root, ref['sha256'])
        approval.pop('command')
        approval['qualification']['path'] = '../escape'
        ref = document(root, 'approval.json', approval)
        with self.assertRaises(ValueError):
            self.select_changed(root, ref['sha256'])
        with self.assertRaises(TypeError):
            receipt.select_oracle_qualification(self.subject/'approval.json',
                live_roots=self.roots, scratch_directory=self.root/'without-root')

    def completed(self, src=None, values=None, output=None, *, chunk_bytes=1_048_576):
        self.serial += 1
        src = source() if src is None else src
        values = [0, 1, 2, 3] if values is None else values
        output = [777] if output is None else output
        invlimits = InvocationLimits(blobs=blobs.BlobLimits(chunk_bytes=chunk_bytes))
        manifest = write_invocation(src, [struct.pack('<%di' % len(values), *values)],
            [struct.pack('<%di' % len(output), *output)], self.root/f'inv-{self.serial}', limits=invlimits)
        invocation = verify_invocation(manifest, limits=invlimits)
        result = source_oracle.evaluate_source_state(src, invocation, self.root/f'result-{self.serial}',
            profile=SourceProfileV2(), limits=source_oracle.OracleLimits(
                state_limits=state.ArtifactLimits(chunk_bytes=chunk_bytes)))
        self.assertIn(result.status, ('success', 'input_precondition_failed'))
        return src, invocation, result

    def test_incomplete_oracle_has_no_expected_receipt(self):
        q = self.select()
        _, _, result = self.completed()
        for status in ('unsupported_source', 'invalid_invocation', 'work_limit', 'cancelled',
                       'timeout', 'resource_limit', 'allocation_failure', 'io_failure'):
            incomplete = replace(result, status=status, state_manifest=None, failure_detail='test')
            with self.assertRaises(ValueError):
                receipt.produce_oracle_receipt(incomplete, q, self.root/'no-receipt')
            self.assertFalse((self.root/'no-receipt').exists())
        forged = replace(result)
        object.__setattr__(forged, 'scalar_evaluations', True)
        with self.assertRaises(ValueError):
            receipt.produce_oracle_receipt(forged, q, self.root/'no-receipt')
        with self.assertRaises(ValueError):
            receipt.produce_oracle_receipt(object(), q, self.root/'no-receipt')

    def test_candidate_receipt_copies_complete_state(self):
        q = self.select()
        _, _, result = self.completed(chunk_bytes=4)
        with patch.object(receipt, 'evaluate_source_state', side_effect=AssertionError('producer executed oracle')):
            claim = receipt.produce_oracle_receipt(result, q, self.root/'candidate')
        data = json.loads(claim.manifest_path.read_bytes())
        copied = state.verify_state(claim.manifest_path.parent/data['expected_state']['path'])
        self.assertEqual(list(copied.iter_scalars('input_after')), [0, 1, 2, 3])
        shutil.rmtree(result.state_manifest.parent.parent)
        self.assertEqual(list(copied.iter_scalars('output')), [30])
        self.assertFalse(hasattr(claim, 'expected_state'))

    def test_candidate_copy_preflight_and_late_failure_cleanup(self):
        _, _, result = self.completed(chunk_bytes=4)
        q = self.select(limits=receipt.OracleQualificationLimits(
            semantic_limits=state.ArtifactLimits(max_files=2)))
        with patch.object(receipt, 'verify_state', side_effect=AssertionError('bulk read before file quota')):
            with self.assertRaises(ValueError):
                receipt.produce_oracle_receipt(result, q, self.root/'candidate')
        self.assertFalse((self.root/'candidate').exists())
        q.close()
        q = self.select()
        with patch.object(receipt, '_copy_file', side_effect=OSError('injected copy failure')):
            with self.assertRaises(OSError):
                receipt.produce_oracle_receipt(result, q, self.root/'candidate')
        self.assertFalse((self.root/'candidate').exists())
        (self.root/'candidate').mkdir()
        marker = self.root/'candidate/marker'
        marker.write_text('keep')
        with self.assertRaises((FileExistsError, ValueError)):
            receipt.produce_oracle_receipt(result, q, self.root/'candidate')
        self.assertEqual(marker.read_text(), 'keep')

    def candidate(self, q, src=None, values=None, output=None):
        src, invocation, result = self.completed(src, values, output)
        claim = receipt.produce_oracle_receipt(result, q, self.root/f'candidate-{self.serial}')
        claim.manifest_path.chmod(0o600)
        return src, invocation, result, claim

    def verified(self, q, src=None, values=None, output=None, limits=None):
        src, invocation, result, claim = self.candidate(q, src, values, output)
        verified = receipt.verify_oracle_receipt(claim.manifest_path, src, invocation, q,
            limits=limits or source_oracle.OracleLimits())
        self.addCleanup(verified.close)
        return verified, src, invocation, result, claim

    def test_oracle_receipt_binds_exact_source_and_specialization(self):
        q = self.select()
        src, invocation, _, claim = self.candidate(q)
        with self.assertRaises(ValueError):
            receipt.verify_oracle_receipt(claim.manifest_path, src.replace(b'demo', b'renamed'), invocation, q,
                                          limits=source_oracle.OracleLimits())
        other, other_inv, _ = self.completed(source(1, 2), [0]*6, [777]*2)
        with self.assertRaises(ValueError):
            receipt.verify_oracle_receipt(claim.manifest_path, other, other_inv, q,
                                          limits=source_oracle.OracleLimits())
        _, wrong_output, _ = self.completed(output=[778])
        with self.assertRaises(ValueError):
            receipt.verify_oracle_receipt(claim.manifest_path, src, wrong_output, q,
                                          limits=source_oracle.OracleLimits())

    def test_renamed_source_equal_state_distinct_source_binding(self):
        q = self.select()
        first, *_ = self.verified(q)
        second, *_ = self.verified(q, source().replace(b'demo', b'renamed').replace(b'(image[r,c]+1)', b'((image[r,c]+1))'))
        self.assertNotEqual(first.source_sha256, second.source_sha256)
        self.assertEqual(first.family_semantics_sha256, second.family_semantics_sha256)
        self.assertEqual(list(first.expected_state.iter_scalars('output')), list(second.expected_state.iter_scalars('output')))
        self.assertNotEqual(first.invocation_sha256, second.invocation_sha256)

    def test_changed_expected_bytes_cannot_redefine_anchor(self):
        q = self.select()
        src, invocation, result = self.completed()
        original = state.verify_state(result.state_manifest)
        wrong = state.write_state([0, 1, 2, 3], [999], original.metadata, self.root/'forged-state')
        forged_result = replace(result, state_manifest=wrong)
        claim = receipt.produce_oracle_receipt(forged_result, q, self.root/'forged-candidate')
        with self.assertRaisesRegex(ValueError, 'state'):
            receipt.verify_oracle_receipt(claim.manifest_path, src, invocation, q,
                                          limits=source_oracle.OracleLimits())
        self.assertEqual(list((self.root/'scratch-1').iterdir()), [])

    def test_verifier_executes_once_and_compares_all_state(self):
        q = self.select()
        src, invocation, _, claim = self.candidate(q, source(1, 2), [0, -1, 2, 3, 4, 5], [123, -456])
        with patch.object(receipt, 'evaluate_source_state', wraps=receipt.evaluate_source_state) as evaluator:
            verified = receipt.verify_oracle_receipt(claim.manifest_path, src, invocation, q,
                limits=source_oracle.OracleLimits(state_limits=state.ArtifactLimits(chunk_bytes=4)))
            self.addCleanup(verified.close)
            self.assertEqual(evaluator.call_count, 1)
        self.assertEqual(list(verified.expected_state.iter_scalars('output')), [123, -456])
        self.assertEqual(list(verified.expected_state.iter_scalars('input_after')), [0, -1, 2, 3, 4, 5])
        self.assertFalse(verified.expected_state.manifest_path.is_relative_to(claim.manifest_path.parent))

    def test_independent_execution_failures_and_combined_quotas(self):
        q = self.select()
        src, invocation, _, claim = self.candidate(q)
        for limits in (source_oracle.OracleLimits(max_scalar_evaluations=1),
                       source_oracle.OracleLimits(cancelled=lambda: True),
                       source_oracle.OracleLimits(deadline_monotonic_ns=0),
                       source_oracle.OracleLimits(max_temporary_bytes=64)):
            with self.assertRaises(ValueError):
                receipt.verify_oracle_receipt(claim.manifest_path, src, invocation, q, limits=limits)
            self.assertEqual(list((self.root/'scratch-1').iterdir()), [])
        q.close()
        q = self.select(limits=receipt.OracleQualificationLimits(semantic_limits=state.ArtifactLimits(max_aggregate_bytes=4096)))
        with patch.object(receipt, 'verify_state', side_effect=AssertionError('bulk state before combined quota')):
            with self.assertRaises(ValueError):
                receipt.verify_oracle_receipt(claim.manifest_path, src, invocation, q, limits=source_oracle.OracleLimits())
        self.assertEqual(list((self.root/f'scratch-{self.serial}').iterdir()), [])

    def test_live_anchor_revalidation_never_reexecutes_ast(self):
        q = self.select()
        with patch.object(receipt, 'evaluate_source_state', wraps=receipt.evaluate_source_state) as evaluator:
            handle, _, _, _, claim = self.verified(q)
            handle.revalidate()
            handle.revalidate()
            self.assertEqual(evaluator.call_count, 1)
            claim.manifest_path.write_bytes(b'{}')
            with self.assertRaises(ValueError):
                handle.revalidate()
            self.assertEqual(evaluator.call_count, 1)

    def test_forged_copied_and_closed_oracle_handles_reject(self):
        q = self.select()
        handle, *_ = self.verified(q)
        with self.assertRaises(TypeError):
            receipt.VerifiedOracle()
        forged = object.__new__(receipt.VerifiedOracle)
        with self.assertRaises(ValueError):
            forged.revalidate()
        with self.assertRaises((TypeError, ValueError)):
            copy.copy(handle).revalidate()
        exposed = handle.expected_state
        object.__setattr__(exposed, 'closure', ())
        object.__setattr__(exposed, 'manifest_sha256', '0'*64)
        self.assertNotEqual(handle.expected_state.manifest_sha256, '0'*64)
        with self.assertRaises(AttributeError):
            handle.source_sha256 = '0'*64
        with self.assertRaises(AttributeError):
            handle.expected_state = exposed
        last = handle.expected_state.closure[-1].resolved_path
        last.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            handle.revalidate()
        q.close()
        with self.assertRaises(ValueError):
            handle.revalidate()
        handle.close()

    def test_no_receipt_command_or_prohibited_dependency(self):
        import ast
        parsed = ast.parse(Path(receipt.__file__).read_text())
        names = []
        for node in ast.walk(parsed):
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.append(node.module or '')
        forbidden = ('planner', 'checker', 'selector', 'emitter', 'native', 'reference')
        self.assertFalse([name for name in names if any(part in name for part in forbidden)])
        q = self.select()
        src, invocation, _, claim = self.candidate(q)
        data = json.loads(claim.manifest_path.read_bytes())
        for field in ('command', 'import', 'argv'):
            changed = dict(data, **{field: ['never-execute']})
            claim.manifest_path.write_bytes(blobs.canonical_json(changed))
            with self.assertRaises(ValueError):
                receipt.verify_oracle_receipt(claim.manifest_path, src, invocation, q,
                                              limits=source_oracle.OracleLimits())
        claim.manifest_path.write_bytes(blobs.canonical_json(data))
        calls = []
        def cancellation():
            if not calls:
                calls.append('entered')
                for action in (q.close, q.revalidate,
                    lambda: receipt.verify_oracle_receipt(claim.manifest_path, src, invocation, q,
                                                         limits=source_oracle.OracleLimits())):
                    with self.assertRaises(ValueError):
                        action()
            return False
        handle = receipt.verify_oracle_receipt(claim.manifest_path, src, invocation, q,
            limits=source_oracle.OracleLimits(cancelled=cancellation))
        self.addCleanup(handle.close)
        self.assertEqual(calls, ['entered'])
        handle.revalidate()

    def test_final_callback_mutation_cannot_publish(self):
        q = self.select()
        src, invocation, _, claim = self.candidate(q)
        compared = []
        real_compare = receipt.compare_state
        def compare(*args):
            answer = real_compare(*args)
            compared.append(True)
            return answer
        def cancellation():
            if compared:
                claim.manifest_path.write_bytes(b'{}')
            return False
        with patch.object(receipt, 'compare_state', side_effect=compare):
            with self.assertRaises(ValueError):
                receipt.verify_oracle_receipt(claim.manifest_path, src, invocation, q,
                    limits=source_oracle.OracleLimits(cancelled=cancellation))
        self.assertEqual(list((self.root/'scratch-1').iterdir()), [])

    def test_fresh_process_receipt_verification_executes_again(self):
        import subprocess
        q = self.select()
        handle, src, invocation, _, claim = self.verified(q)
        code = '''
import sys
sys.dont_write_bytecode = True
from pathlib import Path
from unittest.mock import patch
from research import oracle_receipt as o
from axiom.invocation_v2 import verify_invocation, InvocationLimits
roots = tuple(o.OracleLiveRoot(name, Path(path)) for name, path in __import__('json').loads(sys.argv[5]))
q = o.select_oracle_qualification(Path(sys.argv[1]), approved_root_sha256=sys.argv[2], live_roots=roots, scratch_directory=Path(sys.argv[6]))
inv = verify_invocation(Path(sys.argv[3]), limits=InvocationLimits())
with patch.object(o, 'evaluate_source_state', wraps=o.evaluate_source_state) as evaluator:
    handle = o.verify_oracle_receipt(Path(sys.argv[4]), inv.source_bytes, inv, q, limits=o.OracleLimits())
    handle.revalidate()
    if evaluator.call_count != 1:
        raise RuntimeError('fresh process did not execute exactly once')
    handle.close()
q.close()
print('FRESH_EXECUTIONS=1')
'''
        result = subprocess.run([sys.executable, *(['-O'] if sys.flags.optimize else []), '-B', '-c', code,
            str(self.subject/'approval.json'), self.approved, str(invocation.manifest_path),
            str(claim.manifest_path), json.dumps([(r.name, str(r.directory)) for r in self.roots]),
            str(self.root/'child-scratch')], cwd=Path(__file__).resolve().parents[2],
            env=dict(os.environ, PYTHONPATH='src:research'), text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('FRESH_EXECUTIONS=1', result.stdout)
        handle.revalidate()

    def test_qualification_schema_rehashing_is_not_external_approval(self):
        root = self.mutated_subject(lambda p: None)
        original = json.loads((root/'qualification.json').read_bytes())
        def rebuilt(subject):
            qref = document(root, 'qualification.json', subject)
            evidence = json.loads((root/'tests.json').read_bytes())
            evidence['qualification_sha256'] = qref['sha256']
            eref = document(root, 'tests.json', evidence)
            review = json.loads((root/'review.json').read_bytes())
            review['qualification_sha256'] = qref['sha256']
            review['test_evidence_sha256'] = eref['sha256']
            rref = document(root, 'review.json', review)
            return document(root, 'approval.json', dict(schema='axiom-oracle-approval-v1',
                qualification=qref, test_evidence=eref, review=rref))['sha256']
        missing = copy.deepcopy(original)
        missing['inventory'] = [x for x in missing['inventory'] if x['role'] != 'runtime_library']
        newroot = rebuilt(missing)
        with self.assertRaises(ValueError):
            self.select_changed(root)  # recomputed graph cannot choose controller pin
        with self.assertRaises(ValueError):
            self.select_changed(root, newroot)  # even explicit fixture pin cannot omit runtime
        duplicate = copy.deepcopy(original)
        duplicate['inventory'].append(duplicate['inventory'][-1])
        newroot = rebuilt(duplicate)
        with self.assertRaises(ValueError):
            self.select_changed(root, newroot)
        newroot = rebuilt(original)
        qualification = root/'qualification.json'
        target = root/'symlink-target.json'
        qualification.rename(target)
        qualification.symlink_to(target.name)
        with self.assertRaises(ValueError):
            self.select_changed(root, newroot)

    def test_final_chunk_and_qualification_failure_leave_no_candidate(self):
        q = self.select()
        _, _, result = self.completed(chunk_bytes=4)
        calls = []
        real_copy = receipt._copy_file
        closure_count = len(state.verify_state(result.state_manifest).closure)
        def late_copy(*args):
            real_copy(*args)
            calls.append(True)
            if len(calls) == closure_count:
                raise OSError('after final complete copy')
        with patch.object(receipt, '_copy_file', side_effect=late_copy):
            with self.assertRaises(OSError):
                receipt.produce_oracle_receipt(result, q, self.root/'candidate')
        self.assertEqual(len(calls), closure_count)
        self.assertFalse((self.root/'candidate').exists())
        real_check = receipt._check_qualification
        calls.clear()
        def late_qualification(record):
            calls.append(True)
            if len(calls) == 2:
                raise ValueError('qualification changed at publication')
            return real_check(record)
        with patch.object(receipt, '_check_qualification', side_effect=late_qualification):
            with self.assertRaises(ValueError):
                receipt.produce_oracle_receipt(result, q, self.root/'candidate')
        self.assertFalse((self.root/'candidate').exists())

    def test_all_scalar_mismatches_including_last_chunk_reject(self):
        q = self.select()
        src, invocation, result = self.completed(source(1, 2), [0, -1, 2, 3, 4, 5], [123, -456], chunk_bytes=4)
        original = state.verify_state(result.state_manifest)
        for number, (values, output) in enumerate((([0, -1, 2, 3, 4, 6], [123, -456]),
                                                   ([0, -1, 2, 3, 4, 5], [123, -455]))):
            wrong = state.write_state(values, output, original.metadata, self.root/f'wrong-{number}',
                                      limits=state.ArtifactLimits(chunk_bytes=4))
            claim = receipt.produce_oracle_receipt(replace(result, state_manifest=wrong), q, self.root/f'claim-{number}')
            with self.assertRaises(ValueError):
                receipt.verify_oracle_receipt(claim.manifest_path, src, invocation, q,
                    limits=source_oracle.OracleLimits(state_limits=state.ArtifactLimits(chunk_bytes=4)))
        self.assertEqual(list((self.root/'scratch-1').iterdir()), [])

    def test_existing_anchors_share_capacity_and_semantic_quota(self):
        limits = receipt.OracleQualificationLimits(max_live_oracles=1)
        q = self.select(limits=limits)
        handle, src, invocation, _, claim = self.verified(q)
        with patch.object(receipt, 'evaluate_source_state', side_effect=AssertionError('capacity not reserved')):
            with self.assertRaises(ValueError):
                receipt.verify_oracle_receipt(claim.manifest_path, src, invocation, q, limits=source_oracle.OracleLimits())
        handle.close()
        second = receipt.verify_oracle_receipt(claim.manifest_path, src, invocation, q, limits=source_oracle.OracleLimits())
        self.addCleanup(second.close)
        second.close()
        q.close()
        # One conservative anchor fits. A second reservation plus the retained
        # first anchor and candidate crosses the same selected session budget.
        q = self.select(limits=receipt.OracleQualificationLimits(
            semantic_limits=state.ArtifactLimits(max_aggregate_bytes=1_051_000)))
        first = receipt.verify_oracle_receipt(claim.manifest_path, src, invocation, q, limits=source_oracle.OracleLimits())
        self.addCleanup(first.close)
        with patch.object(receipt, 'verify_state', side_effect=AssertionError('combined quota before bulk')):
            with self.assertRaises(ValueError):
                receipt.verify_oracle_receipt(claim.manifest_path, src, invocation, q, limits=source_oracle.OracleLimits())

    def test_allocation_io_cleanup_failure_and_recovery(self):
        q = self.select()
        src, invocation, _, claim = self.candidate(q)
        for failure in (MemoryError('allocation'), OSError(5, 'io')):
            with patch.object(source_oracle, 'write_state', side_effect=failure):
                with self.assertRaises(ValueError):
                    receipt.verify_oracle_receipt(claim.manifest_path, src, invocation, q, limits=source_oracle.OracleLimits())
            self.assertEqual(list((self.root/'scratch-1').iterdir()), [])
        handle = receipt.verify_oracle_receipt(claim.manifest_path, src, invocation, q, limits=source_oracle.OracleLimits())
        with patch.object(receipt, '_remove_owned', side_effect=OSError('cleanup unavailable')):
            with self.assertRaises(OSError):
                handle.close()
        with self.assertRaises(ValueError):
            handle.revalidate()
        self.assertTrue(receipt._CLEANUP_DEBTS)
        self.assertGreater(receipt._qualification(q).leaked_bytes, 0)
        handle.close()  # retry has no authority, but can release actual cleanup debt
        self.assertFalse(receipt._CLEANUP_DEBTS)
        self.assertEqual(receipt._qualification(q).leaked_bytes, 0)

    def test_caller_records_cannot_mutate_issuer_limits_or_anchor_pins(self):
        supplied = receipt.OracleQualificationLimits()
        q = self.select(limits=supplied)
        object.__setattr__(supplied.semantic_limits, 'max_files', 1)
        exposed_limits = q.limits
        object.__setattr__(exposed_limits.semantic_limits, 'max_files', 1)
        self.assertEqual(q.limits.semantic_limits.max_files, 16_384)
        handle, *_ = self.verified(q)
        exposed_state = handle.expected_state
        object.__setattr__(exposed_state.limits, 'max_files', 1)
        handle.revalidate()
        self.assertEqual(handle.expected_state.limits.max_files, 16_384)


    def test_handle_registration_failure_is_not_authority(self):
        q = self.select()
        src, invocation, _, claim = self.candidate(q)
        class FailingRegistration(dict):
            def __setitem__(self, key, value):
                raise MemoryError('issuer registration allocation')
        with patch.object(receipt, '_ORACLES', FailingRegistration()):
            with self.assertRaises(MemoryError):
                receipt.verify_oracle_receipt(claim.manifest_path, src, invocation, q,
                                              limits=source_oracle.OracleLimits())
        self.assertEqual(receipt._qualification(q).children, set())
        self.assertEqual(list((self.root/'scratch-1').iterdir()), [])

    def test_session_guard_rejects_concurrent_close(self):
        import threading
        q = self.select()
        src, invocation, _, claim = self.candidate(q)
        observed = []
        def close_from_other_thread():
            try:
                q.close()
            except ValueError:
                observed.append('rejected')
        def callback():
            if not observed:
                thread = threading.Thread(target=close_from_other_thread)
                thread.start()
                thread.join(timeout=2)
                if thread.is_alive():
                    raise RuntimeError('nonblocking guard blocked close')
            return False
        handle = receipt.verify_oracle_receipt(claim.manifest_path, src, invocation, q,
            limits=source_oracle.OracleLimits(cancelled=callback))
        self.addCleanup(handle.close)
        self.assertEqual(observed, ['rejected'])

    def test_original_invocation_and_selected_files_stay_pinned(self):
        q = self.select()
        handle, _, invocation, _, _ = self.verified(q)
        invocation.manifest_path.chmod(0o600)
        invocation.manifest_path.write_bytes(b'{}')
        with self.assertRaises(ValueError):
            handle.revalidate()
        handle.close()
        q.close()
        root = self.mutated_subject(lambda p: None)
        q = self.select_changed(root)
        self.addCleanup(q.close)
        handle, *_ = self.verified(q)
        (root/'review.json').write_bytes(b'{}')
        with self.assertRaises(ValueError):
            handle.revalidate()


    def test_successful_close_does_not_reclaim_reused_path(self):
        q = self.select()
        handle, *_ = self.verified(q)
        directory = handle.expected_state.manifest_path.parent.parent
        handle.close()
        directory.mkdir()
        marker = directory/'new-caller-file'
        marker.write_text('not the old anchor')
        handle.close()
        self.assertTrue(marker.exists())
        scratch = self.root/'scratch-1'
        q.close()
        scratch.mkdir()
        marker = scratch/'new-caller-file'
        marker.write_text('not the old qualification')
        q.close()
        self.assertTrue(marker.exists())


    def test_parent_cleanup_retires_closed_child_cleanup_paths(self):
        q = self.select()
        child, *_ = self.verified(q)
        directory = child.expected_state.manifest_path.parent.parent
        with patch.object(receipt, '_remove_owned', side_effect=OSError('injected child cleanup refusal')):
            with self.assertRaises(OSError):
                child.close()
        q.close()
        directory.mkdir(parents=True)
        marker = directory/'new-caller-data'
        marker.write_text('new owner after parent cleanup')
        child.close()
        self.assertTrue(marker.exists(), 'closed child retried stale cleanup after parent completion')
        self.assertEqual(marker.read_text(), 'new owner after parent cleanup')

    def test_issued_handle_fields_cannot_redirect_cleanup(self):
        q = self.select()
        child, *_ = self.verified(q)
        for handle in (child, q):
            with self.subTest(handle_type=type(handle).__name__):
                victim = self.root/type(handle).__name__
                victim.mkdir()
                marker = victim/'caller-data'
                marker.write_text('not owned by the issuer')
                try:
                    handle._closed = True
                    handle._cleanup = (victim,)
                    handle.close()
                    self.assertTrue(marker.exists())
                    with self.assertRaises(ValueError):
                        handle.revalidate()
                    handle._closed = False
                    handle._cleanup = (victim,)
                    handle.close()
                    self.assertEqual(marker.read_text(), 'not owned by the issuer')
                finally:
                    # Also clean the vulnerable implementation during RED: its
                    # forged flag otherwise leaves live issuer state behind.
                    handle._closed = False
                    handle._cleanup = ()
                    handle.close()

    def test_parent_transfers_child_debt_before_external_cleanup_retry(self):
        q = self.select()
        child, _, _, result, _ = self.verified(q)
        directory = child.expected_state.manifest_path.parent.parent
        external = self.root/'failed-candidate'
        # Insert the external debt first: parent cleanup can fail there before
        # reaching a stale child entry after successfully removing scratch.
        with patch.object(receipt, '_copy_file', side_effect=OSError('copy unavailable')):
            with patch.object(receipt, '_remove_owned', side_effect=OSError('cleanup unavailable')):
                with self.assertRaises(OSError):
                    receipt.produce_oracle_receipt(result, q, external)
                with self.assertRaises(OSError):
                    child.close()
        remove = receipt._remove_owned
        def fail_external(path):
            if path == external:
                raise OSError('external cleanup still unavailable')
            remove(path)
        with patch.object(receipt, '_remove_owned', side_effect=fail_external):
            with self.assertRaises(OSError):
                q.close()
        self.assertFalse(directory.exists())
        directory.mkdir(parents=True)
        marker = directory/'new-caller-data'
        marker.write_text('new owner after scratch removal')
        child.close()
        self.assertTrue(marker.exists())
        with self.assertRaises(ValueError):
            self.select()  # external cleanup debt still blocks a new session
        q.close()
        self.assertFalse(external.exists())
        self.assertFalse(receipt._CLEANUP_DEBTS)
        self.assertEqual(marker.read_text(), 'new owner after scratch removal')
        self.select()

    def test_closed_child_retry_obeys_active_session_guard(self):
        q = self.select()
        child, *_ = self.verified(q)
        directory = child.expected_state.manifest_path.parent.parent
        with patch.object(receipt, '_remove_owned', side_effect=OSError('cleanup unavailable')):
            with self.assertRaises(OSError):
                child.close()
        check = receipt._check_qualification
        def reentrant_check(record):
            with self.assertRaisesRegex(ValueError, 'reentry'):
                child.close()
            self.assertTrue(directory.exists())
            check(record)
        with patch.object(receipt, '_check_qualification', side_effect=reentrant_check):
            q.revalidate()
        child.close()
        selected = receipt._qualification(q)
        self.assertEqual((selected.leaked_bytes, selected.leaked_files), (0, 0))
        child.close()
        self.assertEqual((selected.leaked_bytes, selected.leaked_files), (0, 0))

    def test_closed_parent_retries_are_serialized(self):
        import threading
        q = self.select()
        with patch.object(receipt, '_remove_owned', side_effect=OSError('cleanup unavailable')):
            with self.assertRaises(OSError):
                q.close()
        entered, release = threading.Event(), threading.Event()
        errors = []
        remove = receipt._remove_owned
        def blocked_remove(path):
            if threading.current_thread() is worker:
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('cleanup retry was not released')
            remove(path)
        def retry():
            try:
                q.close()
            except BaseException as error:
                errors.append(error)
        worker = threading.Thread(target=retry)
        with patch.object(receipt, '_remove_owned', side_effect=blocked_remove):
            worker.start()
            try:
                self.assertTrue(entered.wait(5))
                with self.assertRaisesRegex(ValueError, 'reentry'):
                    q.close()
            finally:
                release.set()
                worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertFalse(receipt._CLEANUP_DEBTS)
        q.close()

    def test_child_close_rechecks_authority_after_acquiring_session_guard(self):
        import threading
        q = self.select()
        child, *_ = self.verified(q)
        directory = child.expected_state.manifest_path.parent.parent
        entered, release = threading.Event(), threading.Event()
        errors = []
        lookup = receipt._oracle
        def paused_lookup(handle):
            record = lookup(handle)
            if threading.current_thread() is worker and not entered.is_set():
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('issuer lookup was not released')
            return record
        def close_child():
            try:
                child.close()
            except BaseException as error:
                errors.append(error)
        worker = threading.Thread(target=close_child)
        with patch.object(receipt, '_oracle', side_effect=paused_lookup):
            worker.start()
            try:
                self.assertTrue(entered.wait(5))
                child.close()
                directory.mkdir()
                marker = directory/'new-caller-data'
                marker.write_text('new owner after concurrent close')
            finally:
                release.set()
                worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ValueError)
        child.close()
        self.assertEqual(marker.read_text(), 'new owner after concurrent close')
        self.assertEqual(receipt._qualification(q).pending_closes, {})
        self.assertFalse(receipt._CLEANUP_DEBTS)


if __name__ == '__main__':
    unittest.main()
