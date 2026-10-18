#!/usr/bin/env python3
"""Run the cross-language benchmark suite and append verified results to a JSONL log.

Every result is checked against bench/oracle.py (a literal, NumPy-free
definition of each kernel) by output count and positional checksum. Logs are
append-only: one `run` header line, then one `build` line per compiled
baseline and one `result` line per (kernel, size, pattern, implementation).
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from catalog import AXIOM_CAPS, AXIOM_OBJECTIVES, KERNELS, PATTERNS, SIZE_TIERS  # noqa: E402
from oracle import expected_checksum  # noqa: E402

IMPLS = ('c', 'rust', 'node', 'numpy', 'python', 'axiom', 'axiom-native')
SOURCES = ('impl/kernels.c', 'impl/kernels.rs', 'impl/kernels.mjs', 'impl/kernels.py',
           'impl/kernels_numpy.py', 'impl/pyharness.py', 'impl/axiom_native_harness.c',
           'axiom_adapter.py', 'axiom_native.py', 'catalog.py', 'oracle.py')
REJECT_CASES = ('reject_range', 'reject_shape', 'reject_profile')


def git(*args):
    r = subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def tool_version(cmd):
    if shutil.which(cmd[0]) is None:
        return None
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return (r.stdout or r.stderr).strip().splitlines()[0] if r.returncode == 0 else None


def build(args, out_dir, log):
    """Compile native baselines; compile time is logged, never measured as runtime."""
    exe = '.exe' if os.name == 'nt' else ''
    jobs = {
        'c': ([args.cc, *args.cflags.split(), '-std=c11', str(HERE / 'impl/kernels.c'),
               '-o', str(out_dir / f'kernels_c{exe}')], out_dir / f'kernels_c{exe}'),
        'rust': ([args.rustc, *args.rustflags.split(), str(HERE / 'impl/kernels.rs'),
                  '-o', str(out_dir / f'kernels_rs{exe}')], out_dir / f'kernels_rs{exe}'),
    }
    host = subprocess.run([args.rustc, '-vV'], capture_output=True, text=True).stdout if 'rust' in args.impls else ''
    if 'windows-gnu' in host and 'link-self-contained' not in args.rustflags:
        # Windows GNU Rust needs its bundled linker libraries (libgcc, libgcc_eh).
        jobs['rust'][0][1:1] = ['-C', 'link-self-contained=yes']
    built = {}
    for name, (cmd, path) in jobs.items():
        if name not in args.impls:
            continue
        start = time.perf_counter()
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        log(dict(type='build', impl=name, command=cmd, ok=r.returncode == 0,
                 seconds=round(time.perf_counter() - start, 3), stderr=r.stderr[-2000:] or None))
        if r.returncode == 0:
            built[name] = [str(path)]
        else:
            print(f'build failed for {name}:\n{r.stderr}', file=sys.stderr)
    return built


def commands(args, built):
    py = [sys.executable]
    cmds = dict(built)
    cmds['node'] = [args.node, str(HERE / 'impl/kernels.mjs')]
    cmds['numpy'] = py + [str(HERE / 'impl/kernels_numpy.py')]
    cmds['python'] = py + [str(HERE / 'impl/kernels.py')]
    cmds['axiom'] = py + [str(HERE / 'axiom_adapter.py')]
    cmds['axiom-native'] = py + [str(HERE / 'axiom_native.py')]
    return {k: v for k, v in cmds.items() if k in args.impls}


def invoke(cmd, argv, timeout):
    start = time.perf_counter()
    try:
        r = subprocess.run(cmd + [str(v) for v in argv], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return dict(status='timeout'), (time.perf_counter() - start) * 1000
    except OSError as error:
        # e.g. Windows Application Control refusing a fresh executable. Logged, never bypassed.
        return dict(status='blocked', diagnostic=dict(code='OS_LAUNCH_REFUSED', message=str(error))), 0.0
    wall = (time.perf_counter() - start) * 1000
    lines = [line for line in r.stdout.splitlines() if line.strip()]
    if r.returncode != 0 and not lines:
        return dict(status='error', stderr=r.stderr[-2000:]), wall
    try:
        data = json.loads(lines[-1])
    except (IndexError, json.JSONDecodeError):
        return dict(status='error', stderr=(r.stderr or r.stdout)[-2000:]), wall
    if r.returncode != 0 and data.get('status') == 'ok':
        data['status'] = 'error'
    return data, wall


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--kernels', default=','.join(KERNELS), help='comma list (default: all)')
    ap.add_argument('--sizes', default='s,m', help=f'comma list of {SIZE_TIERS} (default s,m)')
    ap.add_argument('--patterns', default='hash', help=f'comma list of {PATTERNS} or "all"')
    ap.add_argument('--impls', default=','.join(IMPLS), help='comma list (default: all)')
    ap.add_argument('--min-ms', type=int, default=100, help='minimum timed milliseconds per case')
    ap.add_argument('--max-reps', type=int, default=1000)
    ap.add_argument('--timeout', type=int, default=900, help='seconds per implementation call')
    ap.add_argument('--python-max-inputs', type=int, default=1_100_000,
                    help='skip pure Python above this many input cells (it can take minutes)')
    ap.add_argument('--no-axiom-sweep', action='store_true', help='skip cap/objective sweep and rejection cases')
    ap.add_argument('--label', default='', help='free-text note stored in the run header')
    ap.add_argument('--cc', default='clang')
    ap.add_argument('--cflags', default='-O3')
    ap.add_argument('--rustc', default='rustc')
    ap.add_argument('--rustflags', default='-C opt-level=3')
    ap.add_argument('--node', default='node')
    ap.add_argument('--results', type=Path, default=HERE / 'results')
    args = ap.parse_args()
    args.kernels = args.kernels.split(',')
    args.sizes = args.sizes.split(',')
    args.patterns = list(PATTERNS) if args.patterns == 'all' else args.patterns.split(',')
    args.impls = args.impls.split(',')
    # axiom_native.py compiles generated C with the same compiler and flags as the C baseline.
    os.environ['BENCH_CC'], os.environ['BENCH_CFLAGS'] = args.cc, args.cflags
    for name, values, allowed in (('kernel', args.kernels, KERNELS), ('size', args.sizes, SIZE_TIERS),
                                  ('pattern', args.patterns, PATTERNS), ('impl', args.impls, IMPLS)):
        bad = [v for v in values if v not in allowed]
        if bad:
            ap.error(f'unknown {name}: {", ".join(bad)}')

    rev = git('rev-parse', 'HEAD')
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + (f'-{rev[:7]}' if rev else '')
    args.results.mkdir(parents=True, exist_ok=True)
    path = args.results / f'{run_id}.jsonl'
    stream = path.open('x', encoding='utf-8')

    def log(record):
        stream.write(json.dumps(dict(run_id=run_id, **record), sort_keys=True) + '\n')
        stream.flush()

    log(dict(type='run', schema_version=1, created_utc=datetime.now(timezone.utc).isoformat(),
             label=args.label, git_revision=rev, git_branch=git('rev-parse', '--abbrev-ref', 'HEAD'),
             git_dirty=bool(git('status', '--porcelain', '--', 'axiom', 'bench')),
             platform=platform.platform(), machine=platform.machine(), processor=platform.processor(),
             cpu_count=os.cpu_count(), python=sys.version.split()[0],
             versions=dict(c=tool_version([args.cc, '--version']), rust=tool_version([args.rustc, '--version']),
                           node=tool_version([args.node, '--version']),
                           numpy=tool_version([sys.executable, '-c', 'import numpy; print(numpy.__version__)'])),
             flags=dict(c=args.cflags, rust=args.rustflags),
             settings=dict(min_ms=args.min_ms, max_reps=args.max_reps, sizes=args.sizes, patterns=args.patterns),
             source_sha256={s: hashlib.sha256((HERE / s).read_bytes()).hexdigest() for s in SOURCES}))

    build_dir = ROOT / '.local' / 'bench-build'
    build_dir.mkdir(parents=True, exist_ok=True)
    cmds = commands(args, build(args, build_dir, log))
    failures = 0

    def record(kernel, tier, a, b, pattern, impl, extra=(), expect=None):
        nonlocal failures
        data, wall = invoke(cmds[impl], [kernel, pattern, a, b, args.min_ms, args.max_reps, *extra], args.timeout)
        status = data.get('status')
        if status == 'ok' and expect is not None:
            verified = (data.get('n_out'), data.get('checksum')) == expect
            if not verified:
                status = data['status'] = 'mismatch'
        if status in ('mismatch', 'error', 'timeout'):
            failures += 1
        spec = KERNELS.get(kernel, {})
        entry = {k: v for k, v in data.items() if k != 'kernel'}
        entry.update(type='result', kernel=kernel, family=spec.get('family', 'axiom-rejection'), tier=tier,
                     a=a, b=b, pattern=pattern, impl=impl, status=status, wall_ms=round(wall, 3),
                     expected=dict(n_out=expect[0], checksum=expect[1]) if expect else None)
        log(entry)
        shown = f'{data["ns_median"] / 1e3:,.1f} us' if status == 'ok' else (data.get('diagnostic') or {}).get('code', '')
        print(f'{kernel:<11} {tier} {pattern:<6} {impl:<7}{"" if not extra else str(list(extra)):<32} {status:<12} {shown}', flush=True)

    for kernel in args.kernels:
        for tier in args.sizes:
            a, b = KERNELS[kernel]['sizes'][tier]
            n_in, _ = KERNELS[kernel]['io'](a, b)
            for case, pattern in enumerate(args.patterns):
                expect = expected_checksum(kernel, a, b, pattern)
                order = list(cmds)
                order = order[case % len(order):] + order[:case % len(order)]  # rotate first-run bias
                for impl in order:
                    if impl == 'python' and n_in > args.python_max_inputs:
                        log(dict(type='result', kernel=kernel, family=KERNELS[kernel]['family'], tier=tier,
                                 a=a, b=b, pattern=pattern, impl=impl, status='skipped',
                                 note=f'{n_in} inputs > --python-max-inputs'))
                        continue
                    record(kernel, tier, a, b, pattern, impl, expect=expect)

    axioms = [impl for impl in ('axiom', 'axiom-native') if impl in cmds]
    if axioms and not args.no_axiom_sweep and 'sq2x2' in args.kernels:
        a, b = KERNELS['sq2x2']['sizes']['s']
        for pattern in args.patterns:
            expect = expected_checksum('sq2x2', a, b, pattern)
            for objective in AXIOM_OBJECTIVES:
                for cap in AXIOM_CAPS:
                    for impl in axioms:
                        record('sq2x2', 'sweep', a, b, pattern, impl, (cap, objective), expect)
    if 'axiom' in cmds and not args.no_axiom_sweep:
        for kernel in REJECT_CASES:
            record(kernel, 'reject', 15 if kernel != 'reject_profile' else 14,
                   15 if kernel != 'reject_profile' else 14, args.patterns[0], 'axiom')

    stream.close()
    print(f'\nLog: {path}\nSummarize: py -3 bench/summarize.py {path}')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())