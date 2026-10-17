"""Isolated argv-only Core invocation and strict, retained lane admission.

A successful lane means the Core execution protocol completed. Independent Axiom
semantic correspondence is a separate comparison, never inferred here.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from typing import TYPE_CHECKING, Literal

from .checker import check_plan
from .codec import canonical_json, decode_plan, plan_digest
from .core_observe import decode_observation
from .core_emit import CoreBundle, EMITTER_DIGEST, EMITTER_VERSION
from .model import Limits
from .frontend import admit_source, parse_source

if TYPE_CHECKING:
    from .core_toolchain import Toolchain


@dataclass(frozen=True, slots=True)
class NativeRun:
    lane: str
    argv: tuple[str, ...]
    cwd: Path
    returncode: int | None
    reference_status: str | None
    native_status: str | None
    native_exit_code: int | None
    native_signal: int | None
    stage_timeout_ms: int
    pipeline_timeout_ms: int
    pipeline_timed_out: bool
    stage_timed_out: bool
    cleanup_verified: bool
    cleanup_method: str
    stdout_path: Path
    stderr_path: Path
    stdout_sha256: str
    stderr_sha256: str
    result_path: Path | None
    job_paths: tuple[Path, ...]
    reference_stdout_path: Path | None
    native_stdout_path: Path | None
    classification: str
    reason: str
    report_bytes: bytes | None
    report_sha256: str | None
    compiler_sha256: str
    clang_sha256: str
    generated_source_sha256: str
    forced_cleanup: bool = False
    reference_stdout_sha256: str | None = None
    native_stdout_sha256: str | None = None
    artifact_hashes: tuple[tuple[str, str], ...] = ()


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('Duplicate report key: ' + key)
        result[key] = value
    return result


def _json(raw: bytes) -> dict:
    def invalid_constant(value):
        raise ValueError('Nonfinite JSON value: ' + value)
    result = json.loads(raw, object_pairs_hook=_pairs, parse_constant=invalid_constant)
    if not isinstance(result, dict):
        raise ValueError('Report must be an object')
    return result


def _inside(path: Path, root: Path) -> Path:
    resolved = path.resolve(strict=True)
    if root not in resolved.parents:
        raise ValueError('Evidence escaped the private invocation directory')
    return resolved


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _validate_bundle(bundle: CoreBundle) -> None:
    """Recheck Axiom/plan and provenance, without assuming the emitter is correct.

    A byte-consistent faulty emitter must still reach the independent Axiom oracle;
    regenerating Core source here would hide that shared-generator negative control.
    """
    _require(isinstance(bundle, CoreBundle) and bundle.artifact_kind == 'core_witness_source',
             'Expected immutable Core witness bundle')
    limits = Limits()
    kernel = admit_source(parse_source(bundle.axiom_source_bytes, limits))
    plan = decode_plan(bundle.plan_bytes, limits=limits)
    checked = check_plan(kernel, plan, limits)
    _require(checked.eligible, 'Bound Axiom plan did not freshly pass checking: ' + checked.reason)
    _require(bundle.source_digest == kernel.source_digest and bundle.semantic_digest == kernel.semantic_digest,
             'Axiom source/semantic identity differs')
    _require(bundle.plan_digest == plan_digest(plan) and bundle.plan_bytes_sha256 == _hash(bundle.plan_bytes),
             'Bound plan identity differs')
    _require(_hash(bundle.source_bytes) == bundle.generated_source_sha256,
             'Generated Core source identity changed')
    _require(_hash(bundle.kernel_source_bytes) == bundle.kernel_source_sha256
             and bundle.source_bytes.startswith(bundle.kernel_source_bytes), 'Core kernel identity differs')
    _require(bundle.emitter_version == EMITTER_VERSION and bundle.emitter_digest == EMITTER_DIGEST,
             'Emitter identity differs')
    n, m = (kernel.height + 1) * (kernel.width + 1), kernel.height * kernel.width
    for values, count in ((bundle.data, n), (bundle.initial_output, m)):
        _require(type(values) is tuple and len(values) == count and
                 all(type(value) is int and -(2**31) <= value < 2**31 for value in values),
                 'Witness case must contain complete signed-i32 tuples')
    layout = bundle.observation_layout
    _require((layout.status_index, layout.input_start, layout.input_count, layout.output_start, layout.output_count)
             == (0, 1, n, 1+n, m), 'Witness observation layout differs')
    expected_case = _hash(canonical_json({
        'version': 1, 'artifact_kind': 'core_witness_source', 'source_digest': bundle.source_digest,
        'plan_digest': bundle.plan_digest, 'plan_bytes_sha256': bundle.plan_bytes_sha256,
        'emitter_digest': bundle.emitter_digest, 'generated_source_sha256': bundle.generated_source_sha256,
        'data': list(bundle.data), 'initial_output': list(bundle.initial_output)}))
    _require(bundle.case_digest == expected_case, 'Witness case identity differs')
    _require(type(bundle.mappings) is tuple and bool(bundle.mappings), 'Generated source mappings missing')
    for mapping in bundle.mappings:
        _require(mapping.generated_source_sha256 == bundle.generated_source_sha256
                 and mapping.generated_file_key == 'witness.be'
                 and type(mapping.generated_offset) is int and type(mapping.generated_length) is int
                 and 0 <= mapping.generated_offset < len(bundle.source_bytes)
                 and 0 < mapping.generated_length <= len(bundle.source_bytes) - mapping.generated_offset,
                 'Generated source mapping identity/bounds differ')
        _require(mapping.operation_index is None or
                 (type(mapping.operation_index) is int and 0 <= mapping.operation_index < len(plan.operations)),
                 'Generated source operation mapping differs')
        _require(type(mapping.origins) is tuple and bool(mapping.origins) and
                 all(type(span.offset) is int and type(span.length) is int and 0 <= span.offset
                     and 0 < span.length <= len(bundle.axiom_source_bytes) - span.offset for span in mapping.origins),
                 'Axiom origin mapping is out of bounds')


def _admit_report(run: NativeRun, bundle: CoreBundle) -> NativeRun:
    report = _json(run.report_bytes)
    run = replace(run, reference_status=report.get('reference_status') if type(report.get('reference_status')) is str else None,
                  native_status=report.get('native_status') if type(report.get('native_status')) is str else None,
                  native_exit_code=report.get('native_exit_code') if type(report.get('native_exit_code')) is int else None,
                  stage_timed_out=report.get('status') == 'timeout')
    # No success is possible from partial or contradictory reports.
    if report.get('status') in ('unavailable', 'timeout'):
        return replace(run, classification=report['status'], reason='Core reports ' + report['status'])
    try:
        backend = 'reference' if run.lane == 'reference' else 'differential'
        lowering = 'ir' if run.lane == 'ir' else 'ast'
        _require(run.returncode == 0, 'Core outer process did not exit successfully')
        _require(report.get('schema_version') == 1 and type(report.get('schema_version')) is int,
                 'Unsupported Core report schema')
        _require(report.get('operation') == 'test' and report.get('backend') == backend,
                 'Unexpected Core report operation/backend')
        _require(report.get('status') == 'success', 'Core report did not succeed')
        _require(report.get('requested_lowering') == lowering and report.get('selected_lowering') == lowering,
                 'Requested/selected Core lowering disagrees')
        _require(report.get('reference_attempted') is True and report.get('reference_status') == 'success',
                 'Reference execution did not complete successfully')
        _require(all(type(report.get(key)) is int and report[key] == value
                     for key, value in (('tests', 1), ('failed_tests', 0), ('assertions', 0))),
                 'Core report test counts disagree with witness protocol')
        _require(report.get('compiler_fingerprint') == run.compiler_sha256, 'Core report compiler identity differs')
        sources = [{'path': str(run.cwd/'witness.be'), 'sha256': run.generated_source_sha256}]
        _require(report.get('sources') == sources, 'Core source receipt differs from exact witness')
        fingerprint = _hash(json.dumps(sources, separators=(',', ':'), ensure_ascii=False).encode())
        _require(report.get('source_fingerprint') == fingerprint, 'Core source fingerprint differs')
        _require(isinstance(report.get('budgets'), dict) and report['budgets'].get('timeout_ms') == 120000,
                 'Core stage budget differs')
        reference = _inside(run.result_path.parent / 'reference.stdout.log', run.cwd)
        events = _inside(run.result_path.parent / 'reference.events.jsonl', run.cwd)
        raw = reference.read_bytes()
        event_bytes = events.read_bytes()
        run = replace(run, reference_stdout_path=reference, reference_stdout_sha256=_hash(raw))
        _require(_hash(raw) == report.get('reference_output_sha256'), 'Reference stdout hash differs')
        _require(event_bytes and _hash(event_bytes) == report.get('reference_events_sha256'), 'Reference events missing or hash differs')
        kernel = admit_source(parse_source(bundle.axiom_source_bytes))
        decode_observation(raw, kernel)
        if run.lane == 'reference':
            _require(report.get('compared') is False and report.get('native_status') is None
                     and report.get('native_exit_code') is None and report.get('native_job') is None,
                     'Reference lane unexpectedly describes native execution')
        else:
            _require(report.get('compared') is True and report.get('native_status') == 'exited'
                     and type(report.get('native_exit_code')) is int and report['native_exit_code'] == 0,
                     'Native execution/comparison did not complete successfully')
            native_name = report.get('native_job')
            _require(isinstance(native_name, str), 'Native job path missing')
            native_job = _inside(run.cwd / native_name, run.cwd)
            _require(native_job in run.job_paths and run.result_path.parent in native_job.parents,
                     'Native job is not a new nested invocation job')
            native = _inside(native_job / 'differential.stdout.log', run.cwd)
            native_raw = native.read_bytes()
            run = replace(run, native_stdout_path=native, native_stdout_sha256=_hash(native_raw))
            decode_observation(native_raw, kernel)
            _require(native_raw == raw, 'Core retained native/reference observations differ')
            if run.lane == 'ir':
                profile = report.get('ir_test_profile')
                _require(isinstance(profile, dict) and type(profile.get('schema_version')) is int
                         and profile['schema_version'] == 5 and profile.get('admitted') is True,
                         'IR schema5 admitted profile missing')
        return replace(run, classification='success', reason='Complete Core lane execution and scalar protocol admitted')
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        return replace(run, classification='error', reason=str(exc))


def _run_supervisor(argv: list[str], cwd: Path, stdout, stderr, receipt: Path) -> subprocess.Popen:
    """Defer caller SIGINT until the subreaper has finished bounded cleanup.

    Only the current thread's signal mask changes, and its original mask is restored.
    A fresh supervisor session avoids group SIGINT killing it during Python startup.
    No subprocess context manager/run() may kill the owner on caller exceptions.
    """
    if not hasattr(signal, 'pthread_sigmask') or not hasattr(signal, 'sigtimedwait'):
        raise RuntimeError('POSIX signal masking/wait required for safe caller cancellation')
    original_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})
    collect_sigint = (signal.SIGINT not in original_mask
                      and signal.getsignal(signal.SIGINT) == signal.default_int_handler)
    interrupted = False
    try:
        process = subprocess.Popen(argv, cwd=cwd, stdout=stdout, stderr=stderr, start_new_session=True)
        if not collect_sigint:
            signal.pthread_sigmask(signal.SIG_SETMASK, original_mask)
        try:
            while process.poll() is None:
                if collect_sigint:
                    if signal.sigtimedwait({signal.SIGINT}, 0.05) is not None:
                        interrupted = True
                        break
                else:
                    try:
                        process.wait(timeout=0.05)
                    except subprocess.TimeoutExpired:
                        pass
        except KeyboardInterrupt:
            # Also cover Python-raised interrupts/custom handlers. Blocking during
            # cleanup prevents repeated ordinary SIGINT from tearing down ownership.
            signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})
            interrupted = True
        if collect_sigint and signal.sigtimedwait({signal.SIGINT}, 0) is not None:
            interrupted = True
        if interrupted:
            deadline = time.monotonic() + 5.0
            while True:
                try:
                    if process.poll() is None:
                        process.terminate()  # cooperative SIGTERM, never SIGKILL
                    process.wait(timeout=max(0.0, deadline - time.monotonic()))
                    break
                except KeyboardInterrupt:
                    # Another thread may have received a process-directed signal.
                    # Preserve the original deadline even on repeated interruption.
                    continue
                except subprocess.TimeoutExpired as exc:
                    raise RuntimeError('Caller cancelled; supervisor cleanup did not finish within 5s; '
                                       'supervisor was left alive to retain descendant ownership') from exc
            try:
                result = _json(receipt.read_bytes())
            except (OSError, ValueError) as exc:
                raise RuntimeError('Caller cancelled; supervisor cleanup receipt missing or invalid') from exc
            _require(process.returncode == 0 and result.get('cleanup_verified') is True,
                     'Caller cancelled; supervisor descendant cleanup is unverified')
            raise KeyboardInterrupt
        return process
    finally:
        # Consume only cancellation signals collected for the default handler;
        # do not change a caller's preexisting blocked signal state or handlers.
        if collect_sigint and interrupted:
            signal.sigtimedwait({signal.SIGINT}, 0)
        signal.pthread_sigmask(signal.SIG_SETMASK, original_mask)


def run_core(bundle: CoreBundle, toolchain: Toolchain,
             lane: Literal['reference', 'ast', 'ir'], directory: Path,
             release: bool = False, pipeline_timeout_ms: int = 1200000) -> NativeRun:
    """Run in a newly created private cwd, retaining all diagnostics and exact argv.

    Stage budget is always 120000ms. The independent whole-pipeline timeout includes
    Core subprocesses; bounded cleanup may take another 3.5 seconds. No timing here
    is a performance measurement. Core's ambiguous 128+signal codes remain exit codes.
    """
    if lane not in ('reference', 'ast', 'ir'):
        raise ValueError('Unknown Core lane')
    if type(pipeline_timeout_ms) is not int or pipeline_timeout_ms <= 0:
        raise ValueError('pipeline_timeout_ms must be a positive exact integer')
    if type(release) is not bool:
        raise ValueError('release must be Boolean')
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    cwd = Path(tempfile.mkdtemp(prefix='core-' + lane + '-', dir=directory))
    stdout, stderr = cwd/'outer.stdout.log', cwd/'outer.stderr.log'
    stdout.touch(); stderr.touch()
    witness = cwd/'witness.be'
    argv = [str(toolchain.compiler), 'test', '--backend', 'reference' if lane=='reference' else 'differential',
            '--lowering', 'ir' if lane=='ir' else 'ast']
    if lane != 'reference':
        argv += ['--opt', 'off', '--clang', str(toolchain.clang), '--save-native-evidence']
    if release:
        argv += ['--release']
    argv += ['--timeout-ms', '120000', str(witness)]
    run = NativeRun(lane, tuple(argv), cwd, None, None, None, None, None, 120000,
                    pipeline_timeout_ms, False, False, False, 'linux-subreaper-proc-pidfd',
                    stdout, stderr, _hash(b''), _hash(b''), None, (), None, None,
                    'infrastructure_error', 'Execution did not start', None, None,
                    toolchain.compiler_sha256, toolchain.clang_sha256, bundle.generated_source_sha256)
    supervisor_started = False
    try:
        _require(Path(toolchain.compiler).is_absolute() and Path(toolchain.clang).is_absolute(),
                 'Explicit absolute Core/Clang paths required')
        _validate_bundle(bundle)
        toolchain.revalidate_identity()
        _require(_hash(bundle.source_bytes) == bundle.generated_source_sha256, 'Generated Core source identity changed')
        witness.write_bytes(bundle.source_bytes)
        request = cwd/'supervisor-request.json'
        receipt = cwd/'supervisor-result.json'
        request.write_text(json.dumps({'argv': argv, 'cwd': str(cwd), 'stdout': str(stdout),
                                      'stderr': str(stderr), 'timeout_ms': pipeline_timeout_ms,
                                      'receipt': str(receipt)}) + '\n')
        with (cwd/'supervisor.stdout.log').open('wb') as supervisor_out, (cwd/'supervisor.stderr.log').open('wb') as supervisor_err:
            supervisor_started = True
            result = _run_supervisor([sys.executable, str(Path(__file__).with_name('_core_supervisor.py')), str(request)],
                                     cwd, supervisor_out, supervisor_err, receipt)
        supervision = _json(receipt.read_bytes())
        run = replace(run, returncode=supervision.get('returncode'),
                      pipeline_timed_out=supervision.get('timed_out') is True,
                      cleanup_verified=supervision.get('cleanup_verified') is True,
                      forced_cleanup=supervision.get('forced_cleanup') is True,
                      stdout_sha256=_hash(stdout.read_bytes()), stderr_sha256=_hash(stderr.read_bytes()))
        jobs = tuple(sorted(_inside(path, cwd) for path in (cwd/'.beryl-cache').rglob('job-*') if path.is_dir()))
        run = replace(run, job_paths=jobs)
        reports = [path/'result.json' for path in jobs if path.parent == cwd/'.beryl-cache' and (path/'result.json').is_file()]
        if len(reports) == 1:
            report_path = _inside(reports[0], cwd)
            raw = report_path.read_bytes()
            run = replace(run, result_path=report_path, report_bytes=raw, report_sha256=_hash(raw))
        artifacts = tuple((str(path.relative_to(cwd)), _hash(_inside(path, cwd).read_bytes()))
                          for path in sorted((cwd/'.beryl-cache').rglob('*')) if path.is_file())
        run = replace(run, artifact_hashes=artifacts)
        if result.returncode != 0 or not run.cleanup_verified or supervision.get('error'):
            return replace(run, reason=supervision.get('error') or 'Supervisor cleanup unverified')
        if run.pipeline_timed_out:
            return replace(run, classification='timeout', reason='Independent whole-pipeline deadline exceeded')
        if run.report_bytes is None:
            return replace(run, classification='error', reason='Expected exactly one new retained Core test report')
        return _admit_report(run, bundle)
    except FileNotFoundError as exc:
        return replace(run, classification=('infrastructure_error' if supervisor_started and run.returncode is None
                                            else 'unavailable' if run.returncode is None else 'error'), reason=str(exc))
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        return replace(run, classification='infrastructure_error' if run.returncode is None else 'error', reason=str(exc))
