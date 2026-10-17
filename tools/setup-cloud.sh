#!/usr/bin/env bash
# Standard-library prototype setup; --native additionally qualifies pinned Core.
set -euo pipefail
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
export PYTHONPATH="$repo_root/axiom/src"
exec "${PYTHON:-python3}" - "$repo_root" "$@" <<'PY'
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

if sys.version_info < (3, 12):
    sys.exit('Python 3.12 or newer is required; select it with PYTHON=/path/to/python3')

repo = Path(sys.argv[1]).resolve()
parser = argparse.ArgumentParser(description='Check Axiom; optionally bootstrap and qualify native Core.')
parser.add_argument('--native', action='store_true', help='Build fresh pinned Core and retain native evidence')
parser.add_argument('--core', type=Path, default=repo.parent / 'beryl', help='Clean exact pinned Core checkout')
parser.add_argument('--prefix', type=Path, default=repo / '.local/cloud', help='Private installation/evidence directory')
parser.add_argument('--clang', type=Path, help='Reuse an explicit verified Clang instead of bootstrapping')
args = parser.parse_args(sys.argv[2:])
if args.clang and not args.native:
    parser.error('--clang requires --native')

def run(argv, **kwargs):
    return subprocess.run([str(item) for item in argv], check=True, **kwargs)

print(f'Python {platform.python_version()}; Axiom uses only the standard library.', flush=True)
run([sys.executable, '-m', 'axiom', 'check', repo / 'axiom/examples/stencil.ax'], cwd=repo / 'axiom')
if not args.native:
    print('Portable setup check passed. Use --native for the separate Core qualification.')
    sys.exit(0)

from axiom.core_toolchain import PINNED_CORE_COMMIT
from axiom.core_toolchain import inspect_toolchain, prepare_snapshot, build_core

expected_pin = '0a678b4ae6d41190c4f5a8bf063caba05759d20d'
clang_sha = '0a3c55936ac43954fbe4914e6e73b577ca9e35e75d89ef13d3e28c187f41ca1a'
config_sha = 'bc3624e157ba6656818d5f16c70efcd0c5414ffc8f354dce80aa76d639f9587f'
# These hashes were checked against authenticated Debian trixie APT metadata.
packages = (
    ('clang-19', '1:19.1.7-3+b1', 'bbb74458d782b7792b61b0eed92746df5e6d033778c045cf8c2b3835b7c4efc4'),
    ('libclang-common-19-dev', '1:19.1.7-3+b1', '4018e40e2d4144fe38c45822e68cca63c1bf6c7872c3073ebb262ad4b2f9b8bc'),
    ('libclang-cpp19', '1:19.1.7-3+b1', 'a7d2b6df51050834f6ea5c0d5e34869c2298b0bcdaa91eff17ba3db2cd545c47'),
    ('llvm-19-linker-tools', '1:19.1.7-3+b1', '874a0a5cde797cda3e94e9310a0a9958608f526f177637414a8ce9620c804818'),
    ('libobjc-14-dev', '14.2.0-19', '60f8a34f94d46b0ae8d48335525bfaae3daef93c56d6b8bce0e76118e44a9136'),
    ('libobjc4', '14.2.0-19', 'd48411ec79114d5941256dddb1720fc65cbe4733285b29d5ecc87eb452ab30d9'),
)

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def save(path, value):
    path.write_text(json.dumps(value, indent=2, default=lambda item: str(item) if isinstance(item, Path)
                               else asdict(item)) + '\n')

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

try:
    require(PINNED_CORE_COMMIT == expected_pin, 'Unexpected Axiom Core pin')
    core = args.core.resolve(strict=True)
    head = run(['git', '--no-replace-objects', '-C', core, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    require(head == expected_pin, f'Core checkout must be pinned to {expected_pin}; found {head}')
    dirty = run(['git', '--no-replace-objects', '-C', core, 'status', '--porcelain', '--untracked-files=all'], capture_output=True).stdout
    require(not dirty, 'Core checkout must be clean, including untracked files')
    for command in ('git', 'bash', 'ldd'):
        require(shutil.which(command) is not None, f'Missing prerequisite: {command}')

    prefix = args.prefix.resolve()
    require(prefix != core and core not in prefix.parents, 'Private prefix must be outside Core checkout')
    prefix.mkdir(parents=True, exist_ok=True)
    evidence = Path(tempfile.mkdtemp(prefix='qualification-', dir=prefix))
    print(f'Fresh native evidence: {evidence}', flush=True)
    install = prefix / 'toolchain'
    clang = args.clang.resolve(strict=True) if args.clang else install / 'usr/lib/llvm-19/bin/clang'
    branch = 'reuse-explicit' if args.clang else 'reuse-private'

    if not args.clang and not install.exists():
        branch = 'bootstrap-signed-apt'
        require(platform.machine() == 'x86_64', 'Bootstrap supports Debian 13 amd64 only')
        release = platform.freedesktop_os_release()
        require(release.get('ID') == 'debian' and release.get('VERSION_ID') == '13',
                'Bootstrap supports Debian 13 only; use a verified --clang on other images')
        for command in ('apt-get', 'dpkg-query', 'dpkg-deb'):
            require(shutil.which(command) is not None, f'Missing prerequisite: {command}')
        # This is intentionally a small rootless supplement to the current image.
        host = run(['dpkg-query', '-W', '-f=${Package} ${Version} ${db:Status-Status}\n',
                    'gcc-14', 'libgcc-14-dev', 'libstdc++-14-dev', 'libc6-dev', 'libllvm19', 'binutils'],
                   capture_output=True, text=True).stdout
        require(all(line.endswith(' installed') for line in host.splitlines()) and len(host.splitlines()) == 6,
                'Required host packages are missing; use a Debian 13 development image')
        (evidence / 'host-packages.txt').write_text(host)
        keyring = Path('/usr/share/keyrings/debian-archive-keyring.gpg')
        ca = Path('/etc/ssl/certs/ca-certificates.crt')
        require(keyring.is_file() and ca.is_file(), 'Missing Debian archive keyring or system CA bundle')
        apt = evidence / 'apt'
        downloads = evidence / 'packages'
        for directory in (apt / 'lists/partial', apt / 'cache/archives/partial', apt / 'parts', downloads):
            directory.mkdir(parents=True)
        sources = apt / 'sources.list'
        sources.write_text(f'deb [signed-by={keyring}] https://deb.debian.org/debian trixie main\n')
        # JSON string quoting is valid for these APT configuration values.
        options = {
            'Dir::Etc::main': '-', 'Dir::Etc::parts': str(apt / 'parts'),
            'Dir::Etc::sourcelist': str(sources), 'Dir::Etc::sourceparts': '-',
            'Dir::State::lists': str(apt / 'lists'), 'Dir::Cache': str(apt / 'cache'),
            'Acquire::https::CaInfo': str(ca), 'Acquire::https::Verify-Peer': 'true',
            'Acquire::https::Verify-Host': 'true', 'Acquire::AllowInsecureRepositories': 'false',
            'APT::Get::AllowUnauthenticated': 'false', 'Acquire::Retries': '2',
            'APT::Get::List-Cleanup': 'false',
        }
        config = apt / 'apt.conf'
        config.write_text(''.join(f'{key} {json.dumps(value)};\n' for key, value in options.items()))
        env = dict(os.environ, APT_CONFIG=str(config))
        with (evidence / 'apt.log').open('w') as log:
            run(['/usr/bin/apt-get', 'update'], env=env, stdout=log, stderr=subprocess.STDOUT)
            run(['/usr/bin/apt-get', 'download', *[f'{name}={version}' for name, version, _ in packages]],
                cwd=downloads, env=env, stdout=log, stderr=subprocess.STDOUT)
        remaining = {sha: (name, version) for name, version, sha in packages}
        receipt = []
        for package in sorted(downloads.glob('*.deb')):
            sha = digest(package)
            require(sha in remaining, f'Unexpected package hash: {package.name}')
            name, version = remaining.pop(sha)
            actual = run(['dpkg-deb', '-f', package, 'Package', 'Version', 'Architecture'], capture_output=True, text=True).stdout
            require(actual == f'Package: {name}\nVersion: {version}\nArchitecture: amd64\n',
                    f'Unexpected package identity: {package.name}')
            receipt.append({'package': name, 'version': version, 'sha256': sha, 'path': str(package)})
        require(not remaining, 'Pinned package download set is incomplete')
        save(evidence / 'package-receipt.json', receipt)
        # Verify the whole set before extracting; never overwrite an existing prefix.
        install.mkdir()
        for item in receipt:
            run(['dpkg-deb', '-x', item['path'], install])
        (clang.parent / 'clang.cfg').write_bytes(b'-lm\n')

    clang = clang.resolve(strict=True)
    require(digest(clang) == clang_sha, 'Selected Clang binary hash differs from the pinned Debian build')
    cfg = clang.parent / 'clang.cfg'
    require(cfg.is_file() and digest(cfg) == config_sha, 'Selected Clang requires the exact adjacent -lm configuration')
    # Check configuration candidates before executing the selected driver at all.
    directories = {clang.parent, Path.home() / '.config/clang'}
    for name in ('CLANG_CONFIG_FILE_SYSTEM_DIR', 'CLANG_CONFIG_FILE_USER_DIR'):
        if os.environ.get(name):
            directories.add(Path(os.environ[name]).expanduser().resolve())
    candidates = [path for directory in directories if directory.is_dir()
                  for path in directory.glob('*.cfg') if path.is_file()]
    require(len(candidates) == 1 and candidates[0].resolve() == cfg.resolve(),
            'Unexpected Clang configuration candidates')
    preflight = inspect_toolchain(core, clang)
    save(evidence / 'preflight.json', preflight)
    require(preflight.available, f'Toolchain preflight failed: {preflight.reason}')
    require(len(preflight.clang_config) == 1 and preflight.clang_config[0].path == cfg.resolve()
            and preflight.clang_config[0].sha256 == config_sha, 'Unexpected Clang configuration candidates')
    save(evidence / 'setup.json', {'branch': branch, 'core': core, 'pin': head, 'clang': clang,
                                 'clang_sha256': clang_sha, 'config_sha256': config_sha,
                                 'python': sys.executable, 'python_version': platform.python_version()})
    print(f'Clang setup branch: {branch}; C11 compile/run passed. Building pinned Core...', flush=True)
    snapshot = prepare_snapshot(core, evidence / 'core-snapshot')
    toolchain = build_core(snapshot, clang, evidence / 'receipts')
    toolchain.revalidate_identity()
    print(f'Core build and native qualification passed; unit_status={toolchain.unit_status}')
    print(f'Core unit exit={toolchain.unit_receipt.returncode}; receipt={toolchain.receipt_path}')
    if toolchain.unit_status == 'known_pinned_baseline_failure':
        print('Core unit suite remains FAILED: 2 of 10814 checks across 583 cases (known pinned fixture).')
except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
    if 'evidence' in locals():
        failure = {'error': str(exc), 'receipts': getattr(exc, 'receipts', ())}
        save(evidence / 'setup-failure.json', failure)
        print(f'Failure evidence retained at {evidence}', file=sys.stderr)
    sys.exit(f'Cloud setup failed: {exc}')
PY
