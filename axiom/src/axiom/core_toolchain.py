"""Explicit, byte-bound Core/Clang qualification without modifying Core checkouts.

Receipts describe observed commands, not authorization to execute receipt metadata.
Only this module's fixed argument lists are executed. No PATH search selects Clang.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import signal
import subprocess
import sys
import tempfile
from typing import Any

PINNED_CORE_COMMIT = '0a678b4ae6d41190c4f5a8bf063caba05759d20d'
_MARKER = '.axiom-source.json'
_GENERATED = frozenset({'src/back/runtime_embed.h'})
_BASELINE_FIXTURE = 'IR: initialized SET destination remains readable during later scalar capture'


class ToolchainError(RuntimeError):
    """No qualified toolchain was produced; partial commands remain inspectable."""
    def __init__(self, message: str, receipts: tuple[CommandReceipt, ...] = ()):
        super().__init__(message)
        self.receipts = receipts


@dataclass(frozen=True)
class FileIdentity:
    path: Path
    sha256: str
    size: int
    lookup_path: Path | None = None


@dataclass(frozen=True)
class CommandReceipt:
    argv: tuple[str, ...]
    cwd: Path
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    error: str | None = None


@dataclass(frozen=True)
class CompilerInvocation:
    """Argument vector observed immediately before the private adapter execs Clang."""
    stage: str
    argv: tuple[str, ...]
    cwd: Path
    selected_sha256: str


@dataclass(frozen=True)
class ToolchainPreflight:
    status: str
    reason: str
    clang: Path | None = None
    clang_sha256: str | None = None
    clang_config: tuple[FileIdentity, ...] = ()
    source_pin: str | None = None
    source_inventory_sha256: str | None = None
    clang_version: str = ''
    receipts: tuple[CommandReceipt, ...] = ()
    clang_components: tuple[FileIdentity, ...] = ()

    @property
    def available(self) -> bool:
        return self.status == 'available'


@dataclass(frozen=True)
class Toolchain:
    compiler: Path
    clang: Path
    compiler_sha256: str
    clang_sha256: str
    clang_config: tuple[FileIdentity, ...]
    source_pin: str
    source_inventory_sha256: str
    compiler_version: str
    clang_version: str
    build_receipt: CommandReceipt
    unit_receipt: CommandReceipt
    native_receipt: CommandReceipt
    unit_status: str
    snapshot: Path
    source_repository: Path
    source_inventory: tuple[tuple[str, str, int], ...]
    snapshot_inventory: tuple[tuple[str, str, int], ...]
    generated_changes: tuple[str, ...]
    preflight_receipts: tuple[CommandReceipt, ...]
    native_artifacts: tuple[FileIdentity, ...]
    receipt_path: Path
    identity_limits: tuple[str, ...] = (
        'Selected executable/configuration bytes; transitive SDK, linker and dynamic library identity is not complete.',
        'Core loaded-source fingerprints include paths and are distinct from binary byte hashes.',
        'Known pinned unit-suite failure is retained; native qualification is not Axiom conformance.',
    )

    clang_components: tuple[FileIdentity, ...] = ()

    clang_invocations: tuple[CompilerInvocation, ...] = ()

    def revalidate_identity(self) -> None:
        if _identity(self.compiler).sha256 != self.compiler_sha256:
            raise ToolchainError('Core compiler identity changed')
        if _identity(self.clang).sha256 != self.clang_sha256:
            raise ToolchainError('Clang identity changed')
        if _configuration(self.clang) != self.clang_config:
            raise ToolchainError('Clang configuration identity changed')
        for component in self.clang_components:
            if _identity(component.lookup_path or component.path) != component:
                raise ToolchainError('Known Clang component identity changed')
        for item in self.clang_config:
            if _identity(item.lookup_path or item.path) != item:
                raise ToolchainError('Clang configuration bytes changed')
        _, inventory = _source_identity(self.source_repository)
        if inventory != self.source_inventory:
            raise ToolchainError('Original Core source inventory changed')
        if _inventory(self.snapshot, exclude_build=True) != self.snapshot_inventory:
            raise ToolchainError('Built Core snapshot inventory changed')
        for artifact in self.native_artifacts:
            if _identity(artifact.lookup_path or artifact.path) != artifact:
                raise ToolchainError('Native qualification artifact identity changed')


def _identity(path: Path) -> FileIdentity:
    lookup = Path(os.path.abspath(path))
    path = lookup.resolve(strict=True)
    if not path.is_file():
        raise ToolchainError(f'Not a regular file: {path}')
    return FileIdentity(path, hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size,
                        lookup if lookup != path else None)


def _configuration(clang: Path) -> tuple[FileIdentity, ...]:
    # Bind every candidate in the standard driver configuration directories.
    directories = {clang.parent, Path.home() / '.config' / 'clang'}
    for name in ('CLANG_CONFIG_FILE_SYSTEM_DIR', 'CLANG_CONFIG_FILE_USER_DIR'):
        if os.environ.get(name):
            directories.add(Path(os.environ[name]).expanduser().resolve())
    return tuple(sorted((_identity(path) for directory in directories if directory.is_dir()
                         for path in directory.glob('*.cfg') if path.is_file()),
                        key=lambda item: str(item.path)))


def _command(argv: list[str], cwd: Path, *, env: dict[str, str] | None = None,
             timeout: int = 180) -> CommandReceipt:
    try:
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            return CommandReceipt(tuple(argv), cwd, process.returncode,
                                  stdout.decode('utf-8', 'replace'), stderr.decode('utf-8', 'replace'))
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
            return CommandReceipt(tuple(argv), cwd, process.returncode,
                                  stdout.decode('utf-8', 'replace'), stderr.decode('utf-8', 'replace'), True)
    except OSError as exc:
        return CommandReceipt(tuple(argv), cwd, None, '', '', error=str(exc))


def _good(receipt: CommandReceipt) -> bool:
    return receipt.returncode == 0 and not receipt.timed_out and receipt.error is None


def _git(source: Path, *arguments: str) -> bytes:
    result = subprocess.run(['git', '--no-replace-objects', '-C', str(source), *arguments], capture_output=True)
    if result.returncode:
        raise ToolchainError('Core source must be an accessible Git checkout: ' +
                             result.stderr.decode('utf-8', 'replace'))
    return result.stdout


def _source_identity(source: Path) -> tuple[str, tuple[tuple[str, str, int], ...]]:
    pin = _git(source, 'rev-parse', 'HEAD').decode().strip()
    if pin != PINNED_CORE_COMMIT:
        raise ToolchainError(f'Core commit {pin} differs from pinned commit {PINNED_CORE_COMMIT}')
    if _git(source, 'status', '--porcelain', '--untracked-files=all'):
        raise ToolchainError('Core source has dirty tracked or untracked inventory')
    entries = _git(source, 'ls-tree', '-r', '-z', 'HEAD').decode().split('\0')
    inventory = []
    for entry in entries:
        if not entry:
            continue
        metadata, name = entry.split('\t', 1)
        mode, kind, object_id = metadata.split(' ')
        path = source / name
        if kind != 'blob' or path.is_symlink() or not path.is_file():
            raise ToolchainError(f'Unsupported Core source file: {name}')
        raw = path.read_bytes()
        actual_object = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        actual_mode = path.stat().st_mode & 0o777
        expected_executable = mode == '100755'
        if actual_object != object_id or bool(actual_mode & 0o111) != expected_executable:
            raise ToolchainError(f'Core source inventory differs from pinned Git bytes: {name}')
        inventory.append((name, hashlib.sha256(raw).hexdigest(), actual_mode))
    return pin, tuple(sorted(inventory))


def _digest(inventory: tuple[tuple[str, str, int], ...]) -> str:
    return hashlib.sha256(json.dumps(inventory, separators=(',', ':')).encode()).hexdigest()


def _inventory(root: Path, *, exclude_build: bool = False) -> tuple[tuple[str, str, int], ...]:
    items = []
    for path in root.rglob('*'):
        name = path.relative_to(root).as_posix()
        if name == _MARKER or (exclude_build and name.split('/')[0] == 'build'):
            continue
        if path.is_symlink():
            raise ToolchainError(f'Snapshot inventory contains symlink: {name}')
        if path.is_file():
            items.append((name, _identity(path).sha256, path.stat().st_mode & 0o777))
    return tuple(sorted(items))


def prepare_snapshot(source: Path, destination: Path) -> Path:
    """Copy a clean exact pin; save source origin and independently checked inventory."""
    source = Path(source).resolve(strict=True)
    destination = Path(destination).resolve()
    if destination.exists():
        raise ToolchainError('Snapshot destination must not exist')
    if source == destination or source in destination.parents:
        raise ToolchainError('Snapshot must be outside the Core checkout')
    pin, inventory = _source_identity(source)
    destination.mkdir(parents=True)
    for name, _, mode in inventory:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
        target.chmod(mode)
    if _inventory(destination) != inventory or _source_identity(source)[1] != inventory:
        raise ToolchainError('Source inventory changed while preparing snapshot')
    (destination / _MARKER).write_text(json.dumps({
        'source': str(source), 'pin': pin, 'inventory': inventory,
        'inventory_sha256': _digest(inventory)}, indent=2) + '\n')
    return destination.resolve()


def inspect_toolchain(core_source: Path, clang: Path) -> ToolchainPreflight:
    """Check explicitly selected executable, actual C11 compile/run and clean pin."""
    receipts: list[CommandReceipt] = []
    try:
        clang = Path(clang).resolve(strict=True)
        if not clang.is_file() or not os.access(clang, os.X_OK):
            return ToolchainPreflight('unavailable', 'Selected Clang is not executable')
        identity = _identity(clang)
        configuration = _configuration(clang)
        with tempfile.TemporaryDirectory(prefix='axiom c11 probe ') as directory:
            root = Path(directory)
            version = _command([str(clang), '--version'], root)
            receipts.append(version)
            if not _good(version) or not version.stdout.strip():
                return ToolchainPreflight('unavailable', 'Clang version probe failed', receipts=tuple(receipts))
            components: tuple[FileIdentity, ...] = ()
            if shutil.which('ldd'):
                linked = _command(['ldd', str(clang)], root)
                receipts.append(linked)
                if _good(linked):
                    candidates = re.findall(r'=> (/.+?) \(', linked.stdout)
                    candidates += re.findall(r'^\s*(/.+?) \(', linked.stdout, re.MULTILINE)
                    components = tuple(sorted({_identity(Path(name)) for name in candidates},
                                              key=lambda item: str(item.path)))
            witness = root / 'probe.c'
            witness.write_text('#include <stdio.h>\nint main(void) { _Static_assert(sizeof(int)>=4,"C11"); puts("42"); return 0; }\n')
            executable = root / 'probe'
            compile_receipt = _command([str(clang), '-std=c11', '-O0', str(witness), '-o', str(executable)], root)
            receipts.append(compile_receipt)
            if not _good(compile_receipt) or not executable.is_file():
                return ToolchainPreflight('unavailable', 'C11 compilation failed', receipts=tuple(receipts))
            run = _command([str(executable)], root)
            receipts.append(run)
            if not _good(run) or run.stdout != '42\n':
                return ToolchainPreflight('unavailable', 'C11 execution failed', receipts=tuple(receipts))
        pin, inventory = _source_identity(Path(core_source).resolve(strict=True))
        if _identity(clang) != identity or _configuration(clang) != configuration:
            raise ToolchainError('Clang bytes/configuration changed during preflight')
        return ToolchainPreflight('available', 'Selected Clang C11 compile/run and clean pinned source verified',
                                  clang, identity.sha256, configuration, pin, _digest(inventory),
                                  version.stdout, tuple(receipts), components)
    except (OSError, ValueError, ToolchainError) as exc:
        status = 'error' if isinstance(exc, ToolchainError) else 'unavailable'
        return ToolchainPreflight(status, str(exc), receipts=tuple(receipts))


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, default=lambda item: str(item) if isinstance(item, Path)
                               else asdict(item), indent=2) + '\n')


def _install_clang_adapter(output: Path, clang: Path, selected_sha256: str) -> tuple[Path, Path, Path]:
    """Capture actual argv before exec, including calls whose compilation fails."""
    private_bin = output / 'bin'
    private_bin.mkdir()
    log = output / 'clang-invocations.jsonl'
    helper = private_bin / 'capture-clang.py'
    helper.write_text(
        'import hashlib, json, os, sys\n'
        + 'selected = ' + repr(str(clang)) + '\n'
        + 'expected_sha256 = ' + repr(selected_sha256) + '\n'
        + 'log = ' + repr(str(log)) + '\n'
        + 'argv = [selected, *sys.argv[1:]]\n'
        + 'with open(selected, "rb") as stream:\n'
        + '    observed_sha256 = hashlib.sha256(stream.read()).hexdigest()\n'
        + 'record = {"stage": os.environ["AXIOM_CLANG_CAPTURE_STAGE"], "argv": argv, '
          '"cwd": os.getcwd(), "selected_sha256": observed_sha256}\n'
        + 'with open(log, "a", encoding="utf-8") as stream:\n'
        + '    stream.write(json.dumps(record, ensure_ascii=True) + "\\n")\n'
        + 'if observed_sha256 != expected_sha256:\n'
        + '    sys.exit("selected Clang identity changed before exec")\n'
        + 'os.execv(selected, argv)\n')
    wrapper = private_bin / 'clang'
    wrapper.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' '
                       + shlex.quote(str(helper)) + ' "$@"\n')
    wrapper.chmod(0o700)
    return private_bin, log, helper


def _captured_invocations(log: Path, snapshot: Path, clang: Path,
                          selected_sha256: str) -> tuple[CompilerInvocation, ...]:
    records = [json.loads(line) for line in log.read_text().splitlines()]
    if [item.get('stage') for item in records] != ['build', 'unit']:
        raise ToolchainError('Actual build/unit Clang invocation capture is incomplete')
    invocations = []
    for item in records:
        argv = item['argv']
        if (not isinstance(argv, list) or not all(isinstance(arg, str) for arg in argv)
                or not argv or argv[0] != str(clang) or Path(item['cwd']) != snapshot
                or item['selected_sha256'] != selected_sha256):
            raise ToolchainError('Actual Clang invocation identity or argument capture is invalid')
        invocations.append(CompilerInvocation(item['stage'], tuple(argv), Path(item['cwd']),
                                               item['selected_sha256']))
    return tuple(invocations)


def _known_baseline(receipt: CommandReceipt) -> bool:
    text = receipt.stdout + receipt.stderr
    failures = re.findall(r'^FAIL (.+)$', text, re.MULTILINE)
    summaries = re.findall(r'^FAILED\s+(\d+) of (\d+) checks across (\d+) cases$', text, re.MULTILINE)
    return (receipt.returncode == 1 and not receipt.timed_out and receipt.error is None
            and failures == [_BASELINE_FIXTURE, _BASELINE_FIXTURE]
            and summaries == [('2', '10814', '583')]
            and 'error[BE0401]: overlapping exclusive borrows of `n`' in text)


def build_core(snapshot: Path, clang: Path, output: Path) -> Toolchain:
    """Build fixed scripts in a verified disposable copy and qualify native evidence.

    The one independently diagnosed pinned unit defect is retained verbatim and
    explicitly classified; every other unit failure blocks this return value.
    """
    receipts: list[CommandReceipt] = []
    try:
        snapshot = Path(snapshot).resolve(strict=True)
        marker = json.loads((snapshot / _MARKER).read_text())
        source = Path(marker['source']).resolve(strict=True)
        pin, inventory = _source_identity(source)
        recorded = tuple(tuple(entry) for entry in marker['inventory'])
        if (marker['pin'] != pin or marker['inventory_sha256'] != _digest(inventory)
                or recorded != inventory or _inventory(snapshot) != inventory):
            raise ToolchainError('Snapshot inventory does not match clean pinned source')
        preflight = inspect_toolchain(source, clang)
        receipts.extend(preflight.receipts)
        if not preflight.available or preflight.clang is None or preflight.clang_sha256 is None:
            raise ToolchainError('Toolchain preflight failed: ' + preflight.reason)
        clang = preflight.clang
        if 'IR_SCHEMA_VERSION 5u' not in (snapshot / 'src/ir/ir.h').read_text():
            raise ToolchainError('Pinned Core schema5 source contract missing')
        output = Path(output).resolve()
        if output.exists():
            raise ToolchainError('Toolchain output directory must not exist')
        if output == snapshot or snapshot in output.parents or source in output.parents:
            raise ToolchainError('Build receipts must be outside Core source directories')
        output.mkdir(parents=True)
        private_bin, invocation_log, capture_helper = _install_clang_adapter(
            output, clang, preflight.clang_sha256)
        env = dict(os.environ, PATH=str(private_bin) + os.pathsep + os.environ.get('PATH', os.defpath))
        build = _command(['bash', 'scripts/build.sh', '--debug'], snapshot, env=dict(env, AXIOM_CLANG_CAPTURE_STAGE='build'), timeout=300)
        receipts.append(build)
        _write_json(output / 'build.json', build)
        if not _good(build):
            raise ToolchainError('Core debug build failed')
        compiler = snapshot / 'build/beryl.exe'
        compiler_identity = _identity(compiler)
        version = _command([str(compiler), 'version'], output)
        receipts.append(version)
        if not _good(version) or not version.stdout.startswith('beryl '):
            raise ToolchainError('Core compiler version probe failed')
        unit = _command(['bash', 'scripts/test.sh'], snapshot,
                        env=dict(env, AXIOM_CLANG_CAPTURE_STAGE='unit'), timeout=300)
        receipts.append(unit)
        _write_json(output / 'unit.json', unit)
        if _good(unit):
            unit_status = 'passed'
        elif _known_baseline(unit):
            unit_status = 'known_pinned_baseline_failure'
        else:
            raise ToolchainError('Core unit suite has an unqualified failure')
        invocations = _captured_invocations(invocation_log, snapshot, clang, preflight.clang_sha256)
        after = _inventory(snapshot, exclude_build=True)
        old = {row[0]: row[1:] for row in inventory}
        new = {row[0]: row[1:] for row in after}
        changes = tuple(sorted(name for name in old.keys() | new.keys() if old.get(name) != new.get(name)))
        if set(changes) - _GENERATED:
            raise ToolchainError('Core build changed source inventory outside expected generated header')
        witness_dir = output / 'native-probe'
        witness_dir.mkdir()
        witness = witness_dir / 'witness.be'
        witness.write_text('module toolchain_witness\nfn main() {\n    println(42)\n}\n')
        native = _command([str(compiler), 'run', '--clang', str(clang), '--timeout-ms', '120000',
                           '--save-native-evidence', '--lowering', 'ast', '--opt', 'off', str(witness)],
                          witness_dir, env=env, timeout=150)
        receipts.append(native)
        _write_json(output / 'native.json', native)
        if not _good(native) or native.stdout.splitlines()[0:1] != ['42']:
            raise ToolchainError('Core native compile/run/evidence qualification failed')
        jobs = list((witness_dir / '.beryl-cache').glob('job-*'))
        if len(jobs) != 1:
            raise ToolchainError('Native qualification did not create exactly one fresh job')
        job = jobs[0]
        evidence = json.loads((job / 'native-evidence.json').read_text())
        result = json.loads((job / 'result.json').read_text())
        passes = evidence.get('passes', [])
        if (evidence.get('status') != 'success' or evidence.get('tool_unchanged') is not True
                or evidence.get('compiler_fingerprint') != compiler_identity.sha256
                or evidence.get('clang', {}).get('sha256') != preflight.clang_sha256
                or {item.get('name') for item in passes} != {'llvm-ir', 'assembly', 'driver-jobs'}
                or any(item.get('process', {}).get('status') != 'exited'
                       or item.get('process', {}).get('exit_code') != 0 for item in passes)
                or result.get('status') != 'success'
                or any(result.get(stage, {}).get('status') != 'exited'
                       or result.get(stage, {}).get('exit_code') != 0 for stage in ('compile', 'run'))):
            raise ToolchainError('Native evidence receipt did not qualify requested capabilities')
        artifacts = tuple(_identity(job / name) for name in
                          ('out.ll', 'out.s', 'driver-jobs.stderr.log', 'native-evidence.json', 'result.json'))
        if any(item.size == 0 for item in artifacts):
            raise ToolchainError('Native evidence artifact is empty')
        pass_hashes = {item['name']: item.get('output_sha256') for item in passes}
        if pass_hashes['llvm-ir'] != artifacts[0].sha256 or pass_hashes['assembly'] != artifacts[1].sha256:
            raise ToolchainError('Native evidence output hashes do not match artifact bytes')
        # Observe loaded configuration as reported by the real selected driver.
        driver_text = (job / 'driver-jobs.stderr.log').read_text()
        observed = {Path(name).resolve() for name in re.findall(r'^Configuration file: (.+)$', driver_text, re.MULTILINE)}
        if not observed.issubset({item.path for item in preflight.clang_config}):
            raise ToolchainError('Clang loaded a configuration outside the bound candidates')
        artifacts += tuple(_identity(path) for path in (invocation_log, capture_helper, private_bin / 'clang'))
        toolchain = Toolchain(compiler, clang, compiler_identity.sha256, preflight.clang_sha256,
                              preflight.clang_config, pin, _digest(inventory), version.stdout,
                              preflight.clang_version, build, unit, native, unit_status, snapshot,
                              source, inventory, after, changes, tuple(preflight.receipts), artifacts,
                              output / 'toolchain.json', clang_components=preflight.clang_components,
                              clang_invocations=invocations)
        toolchain.revalidate_identity()
        _write_json(toolchain.receipt_path, toolchain)
        return toolchain
    except (OSError, ValueError, KeyError, TypeError, ToolchainError) as exc:
        raise ToolchainError(str(exc), tuple(receipts)) from exc


def _strict_json(raw: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ToolchainError(f'Duplicate receipt field: {key}')
            result[key] = value
        return result

    def constant(value: str) -> Any:
        raise ToolchainError(f'Nonfinite receipt value: {value}')

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ToolchainError(message)


def _record(value: Any, keys: Any) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == set(keys), 'Receipt record fields differ from supported schema')
    return value


def _text(value: Any) -> str:
    _require(type(value) is str and '\0' not in value, 'Receipt string required')
    return value


def _path(value: Any) -> Path:
    value = _text(value)
    _require(Path(value).is_absolute() and os.path.abspath(value) == value, 'Receipt path must be normalized and absolute')
    return Path(value)


def _sha(value: Any) -> str:
    _require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None, 'Receipt SHA256 required')
    return value


def _array(value: Any, decode: Any) -> tuple[Any, ...]:
    _require(type(value) is list, 'Receipt array required')
    return tuple(decode(item) for item in value)


def _load_command(value: Any) -> CommandReceipt:
    value = _record(value, CommandReceipt.__dataclass_fields__)
    _require(value['returncode'] is None or type(value['returncode']) is int, 'Receipt returncode must be an integer or null')
    _require(type(value['timed_out']) is bool, 'Receipt timed_out must be boolean')
    _require(value['error'] is None or type(value['error']) is str, 'Receipt error must be string or null')
    return CommandReceipt(_array(value['argv'], _text), _path(value['cwd']), value['returncode'],
                          _text(value['stdout']), _text(value['stderr']), value['timed_out'], value['error'])


def _load_file(value: Any) -> FileIdentity:
    value = _record(value, FileIdentity.__dataclass_fields__)
    _require(type(value['size']) is int and value['size'] >= 0, 'Receipt size must be a nonnegative integer')
    return FileIdentity(_path(value['path']), _sha(value['sha256']), value['size'],
                        None if value['lookup_path'] is None else _path(value['lookup_path']))


def _load_invocation(value: Any) -> CompilerInvocation:
    value = _record(value, CompilerInvocation.__dataclass_fields__)
    return CompilerInvocation(_text(value['stage']), _array(value['argv'], _text),
                              _path(value['cwd']), _sha(value['selected_sha256']))


def _load_inventory(value: Any) -> tuple[tuple[str, str, int], ...]:
    def row(item: Any) -> tuple[str, str, int]:
        _require(type(item) is list and len(item) == 3, 'Receipt inventory row required')
        name = _text(item[0])
        _require(name != '' and not Path(name).is_absolute() and '..' not in Path(name).parts,
                 'Receipt inventory path invalid')
        _require(type(item[2]) is int and 0 <= item[2] <= 0o777, 'Receipt inventory mode invalid')
        return name, _sha(item[1]), item[2]
    result = _array(value, row)
    _require(result == tuple(sorted(result)) and len({item[0] for item in result}) == len(result),
             'Receipt inventory must be sorted and unique')
    return result


def _qualification_process(value: Any, job: Path, name: str) -> None:
    value = _record(value, ('status', 'exit_code', 'os_error', 'stdout_log', 'stderr_log'))
    _require(value['status'] == 'exited' and type(value['exit_code']) is int and value['exit_code'] == 0
             and type(value['os_error']) is int and value['os_error'] == 0,
             'Native qualification process did not exit successfully')
    for stream in ('stdout', 'stderr'):
        path = _path(value[stream + '_log'])
        _require(path == job / f'{name}.{stream}.log' and path.is_file(), 'Native process log binding invalid')


def _validate_retained_qualification(toolchain: Toolchain) -> None:
    root, snapshot, clang = toolchain.receipt_path.parent, toolchain.snapshot, toolchain.clang
    _require(toolchain.compiler == snapshot / 'build/beryl.exe', 'Core compiler path binding invalid')
    _require(toolchain.compiler_version == 'beryl 0.1.0-dev\n' and bool(toolchain.clang_version.strip()),
             'Toolchain version receipt invalid')
    for filename, receipt, argv, cwd in (
        ('build.json', toolchain.build_receipt, ('bash', 'scripts/build.sh', '--debug'), snapshot),
        ('unit.json', toolchain.unit_receipt, ('bash', 'scripts/test.sh'), snapshot),
        ('native.json', toolchain.native_receipt,
         (str(toolchain.compiler), 'run', '--clang', str(clang), '--timeout-ms', '120000',
          '--save-native-evidence', '--lowering', 'ast', '--opt', 'off',
          str(root / 'native-probe/witness.be')), root / 'native-probe'),
    ):
        _require(receipt.argv == argv and receipt.cwd == cwd, 'Qualification command binding invalid')
        _require(_load_command(_strict_json((root / filename).read_text())) == receipt,
                 'Retained command receipt differs from toolchain record')
    _require(_good(toolchain.build_receipt), 'Core build receipt did not qualify')
    expected_unit = 'passed' if _good(toolchain.unit_receipt) else (
        'known_pinned_baseline_failure' if _known_baseline(toolchain.unit_receipt) else None)
    _require(expected_unit is not None and toolchain.unit_status == expected_unit,
             'Unit qualification status differs from exact retained result')
    _require(_good(toolchain.native_receipt) and toolchain.native_receipt.stdout.splitlines()[0:1] == ['42'],
             'Native command did not qualify')
    preflight = toolchain.preflight_receipts
    _require(len(preflight) in (3, 4) and all(_good(item) for item in preflight), 'Preflight qualification incomplete')
    probe = preflight[0].cwd
    _require(all(item.cwd == probe for item in preflight)
             and preflight[0].argv == (str(clang), '--version')
             and preflight[0].stdout == toolchain.clang_version
             and preflight[-2].argv == (str(clang), '-std=c11', '-O0', str(probe / 'probe.c'), '-o', str(probe / 'probe'))
             and preflight[-1].argv == (str(probe / 'probe'),) and preflight[-1].stdout == '42\n',
             'Preflight version or C11 command binding invalid')
    components = ()
    if len(preflight) == 4:
        linked = preflight[1]
        _require(linked.argv == ('ldd', str(clang)), 'Preflight component command binding invalid')
        names = re.findall(r'=> (/.+?) \(', linked.stdout)
        names += re.findall(r'^\s*(/.+?) \(', linked.stdout, re.MULTILINE)
        components = tuple(sorted({_identity(Path(name)) for name in names}, key=lambda item: str(item.path)))
    _require(components == toolchain.clang_components, 'Known Clang component inventory differs from preflight')
    invocations = tuple(_load_invocation(_strict_json(line))
                        for line in (root / 'clang-invocations.jsonl').read_text().splitlines())
    _require(invocations == toolchain.clang_invocations and tuple(item.stage for item in invocations) == ('build', 'unit')
             and all(item.cwd == snapshot and item.argv and item.argv[0] == str(clang)
                     and item.selected_sha256 == toolchain.clang_sha256 for item in invocations),
             'Observed Clang invocation capture differs from receipt')
    jobs = list((root / 'native-probe/.beryl-cache').glob('job-*'))
    _require(len(jobs) == 1, 'Native qualification requires one retained job')
    job = jobs[0]
    expected_paths = tuple(job / name for name in ('out.ll', 'out.s', 'driver-jobs.stderr.log', 'native-evidence.json', 'result.json'))
    expected_paths += (root / 'clang-invocations.jsonl', root / 'bin/capture-clang.py', root / 'bin/clang')
    _require(tuple(item.path for item in toolchain.native_artifacts) == expected_paths
             and all(item.size > 0 for item in toolchain.native_artifacts), 'Native qualification artifacts incomplete')
    evidence = _record(_strict_json((job / 'native-evidence.json').read_text()), (
        'schema_version', 'operation', 'stage', 'required_capability', 'source_fingerprint',
        'compiler_fingerprint', 'artifact_fingerprint', 'generated_c_fingerprint', 'clang',
        'requested_lowering', 'selected_lowering', 'optimization_policy', 'selected_optimizations',
        'disabled_optimizations', 'runtime_fingerprints', 'measurement_status', 'program_execution',
        'passes', 'tool_unchanged', 'status'))
    result = _record(_strict_json((job / 'result.json').read_text()), (
        'schema_version', 'operation', 'artifact_id', 'status', 'selected_lowering', 'source_fingerprint',
        'sources', 'compiler_fingerprint', 'artifact_fingerprint', 'binding_fingerprint', 'native_evidence',
        'compiler_identity', 'compiler_evidence_process', 'compile', 'run'))
    for data, operation in ((evidence, 'native_evidence'), (result, 'native_build')):
        _require(type(data['schema_version']) is int and data['schema_version'] == 1
                 and data['operation'] == operation and data['status'] == 'success'
                 and data['selected_lowering'] == 'ast' and data['compiler_fingerprint'] == toolchain.compiler_sha256,
                 'Native receipt schema or qualification identity invalid')
        _sha(data['source_fingerprint'])
        _sha(data['artifact_fingerprint'])
    _require(evidence['source_fingerprint'] == result['source_fingerprint']
             and evidence['artifact_fingerprint'] == result['artifact_fingerprint']
             and evidence['stage'] == 'compiler_evidence'
             and evidence['required_capability'] == 'clang.c11.ir.assembly'
             and evidence['requested_lowering'] == 'ast' and evidence['optimization_policy'] == 'off'
             and evidence['selected_optimizations'] == [] and evidence['disabled_optimizations'] == []
             and evidence['measurement_status'] == 'not_measured'
             and evidence['program_execution'] == 'not_executed_by_evidence_capture'
             and evidence['tool_unchanged'] is True, 'Native capability receipt invalid')
    _sha(evidence['generated_c_fingerprint'])
    runtime = _record(evidence['runtime_fingerprints'], ('header', 'implementation'))
    for value in runtime.values():
        _sha(value)
    selected = _record(evidence['clang'], ('path', 'sha256', 'version', 'identity_scope'))
    _require(_path(selected['path']) == clang and _sha(selected['sha256']) == toolchain.clang_sha256,
             'Native selected Clang identity invalid')
    _text(selected['identity_scope'])
    _qualification_process(selected['version'], job, 'version')
    _require((job / 'version.stdout.log').read_text() == toolchain.clang_version, 'Native Clang version differs')
    passes = _array(evidence['passes'], lambda item: _record(item, ('name', 'process', 'output_sha256')))
    _require(tuple(item['name'] for item in passes) == ('llvm-ir', 'assembly', 'driver-jobs'), 'Native evidence passes incomplete')
    for item, artifact in zip(passes, toolchain.native_artifacts):
        _qualification_process(item['process'], job, item['name'])
        _require(item['output_sha256'] == (None if item['name'] == 'driver-jobs' else artifact.sha256),
                 'Native evidence output hash differs')
    for key, name in (('compiler_identity', 'version'), ('compiler_evidence_process', 'driver-jobs'),
                      ('compile', 'compile'), ('run', 'run')):
        _qualification_process(result[key], job, name)
    _require(_path(result['artifact_id']) == job and _path(result['native_evidence']) == job / 'native-evidence.json'
             and result['binding_fingerprint'] is None, 'Native result path binding invalid')
    sources = _array(result['sources'], lambda item: _record(item, ('path', 'sha256')))
    witness = root / 'native-probe/witness.be'
    _require(len(sources) == 1 and _path(sources[0]['path']) == witness
             and _sha(sources[0]['sha256']) == _identity(witness).sha256
             and witness.read_text() == 'module toolchain_witness\nfn main() {\n    println(42)\n}\n'
             and (job / 'run.stdout.log').read_text() == '42\n', 'Native qualification witness identity or output differs')
    driver = (job / 'driver-jobs.stderr.log').read_text()
    observed = {Path(name).resolve() for name in re.findall(r'^Configuration file: (.+)$', driver, re.MULTILINE)}
    _require(observed.issubset({item.path for item in toolchain.clang_config}), 'Native Clang configuration unbound')


def load_toolchain(receipt: Path) -> Toolchain:
    """Restore and recheck a retained local qualification, without executing its argv.

    This validates identities and consistency of trusted local build observations;
    it is not cryptographic attestation against an author who rewrites all records.
    Original runtime paths must remain available. An exact exported receipt copy is
    accepted only while its original bound receipt remains byte-identical.
    """
    try:
        receipt = Path(receipt).resolve(strict=True)
        raw = receipt.read_text()
        record = _record(_strict_json(raw), Toolchain.__dataclass_fields__)
        paths = ('compiler', 'clang', 'snapshot', 'source_repository', 'receipt_path')
        values = {key: _path(record[key]) for key in paths}
        for key in ('compiler_sha256', 'clang_sha256', 'source_inventory_sha256'):
            values[key] = _sha(record[key])
        for key in ('compiler_version', 'clang_version', 'unit_status', 'source_pin'):
            values[key] = _text(record[key])
        for key in ('build_receipt', 'unit_receipt', 'native_receipt'):
            values[key] = _load_command(record[key])
        for key in ('clang_config', 'clang_components', 'native_artifacts'):
            values[key] = _array(record[key], _load_file)
        values['preflight_receipts'] = _array(record['preflight_receipts'], _load_command)
        values['clang_invocations'] = _array(record['clang_invocations'], _load_invocation)
        for key in ('source_inventory', 'snapshot_inventory'):
            values[key] = _load_inventory(record[key])
        for key in ('generated_changes', 'identity_limits'):
            values[key] = _array(record[key], _text)
        toolchain = Toolchain(**values)
        _require(toolchain.receipt_path == receipt or toolchain.receipt_path.read_bytes() == receipt.read_bytes(),
                 'Provided receipt differs from its bound original receipt')
        _require(toolchain.source_pin == PINNED_CORE_COMMIT, 'Receipt Core source pin invalid')
        _require(toolchain.identity_limits == Toolchain.__dataclass_fields__['identity_limits'].default,
                 'Receipt identity trust limits differ from supported qualification')
        _require(_digest(toolchain.source_inventory) == toolchain.source_inventory_sha256,
                 'Receipt source inventory digest differs')
        old = {item[0]: item[1:] for item in toolchain.source_inventory}
        new = {item[0]: item[1:] for item in toolchain.snapshot_inventory}
        changes = tuple(sorted(name for name in old.keys() | new.keys() if old.get(name) != new.get(name)))
        _require(changes == toolchain.generated_changes and not set(changes) - _GENERATED,
                 'Receipt snapshot inventory changes invalid')
        _validate_retained_qualification(toolchain)
        toolchain.revalidate_identity()
        return toolchain
    except (OSError, ValueError, KeyError, TypeError, ToolchainError) as exc:
        raise ToolchainError(f'Cannot load retained toolchain: {exc}') from exc
