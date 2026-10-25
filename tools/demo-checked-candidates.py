#!/usr/bin/env python3
"""Demo: candidate plans (for example written by AI agents), checked by beryl.

    python tools/demo-checked-candidates.py --source bench/demo_b/program.ax \\
        --candidates bench/demo_b/candidates

Every *.json file in the candidates folder is an untrusted beryl-loop-plan-v1
record. Each is decoded, proved or refused by the template checker, and every
accepted plan is run against the source's reference meaning before it is
timed. Accepted plans are compiled with clang and timed with the bench harness
under --out (executables stay out of the temp folder), and compared with the
planner's own direct-v1 plan.
"""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'axiom' / 'src'))
from axiom.frontend import admit_source, parse_source  # noqa: E402
from axiom.model import DiagnosticError  # noqa: E402
from axiom.scale_c import emit_scale_c  # noqa: E402
from axiom.scale_candidates import SoundnessAlarm, review_candidates  # noqa: E402
from axiom.scale_checker import check_loop_plan  # noqa: E402
from axiom.scale_plan import make_scale_plan  # noqa: E402

HARNESS = ROOT / 'bench' / 'impl' / 'axiom_native_harness.c'


def time_plan(kernel, source, plan, name, out):
    """Median ns per call of the plan's emitted kernel, or None if it could not run."""
    check = check_loop_plan(source, plan)
    artifact = emit_scale_c(kernel, plan, sha256(source).hexdigest(), check.plan_digest)
    c = out / f'{name}.c'
    c.write_bytes(artifact.c_source.replace(b'int main(void)', b'int beryl_unused_main(void)'))
    exe = out / f'{name}.exe'
    flags = ['-DBERYL_OUT=int64_t'] if kernel.output_type == 'i64' else []
    built = subprocess.run(['clang', '-O3', '-std=c11', *flags, str(c), str(HARNESS), '-o', str(exe)],
                           capture_output=True, text=True)
    if built.returncode != 0:
        return None
    try:
        ran = subprocess.run([str(exe), 'hash', str(kernel.height), str(kernel.width), '200', '200',
                              str(artifact.input_count), str(artifact.output_count)],
                             capture_output=True, text=True, timeout=600)
        return json.loads(ran.stdout.strip().splitlines()[-1])['ns_median']
    except (OSError, ValueError, IndexError, KeyError):  # e.g. Application Control; never bypassed
        return None


def _shown(ns):
    return '-' if ns is None else f'{ns / 1000:.1f} us' if ns >= 1000 else f'{ns} ns'


def main(argv=None):
    ap = argparse.ArgumentParser(prog='beryl-demo', description=__doc__.splitlines()[0])
    ap.add_argument('--source', type=Path, required=True)
    ap.add_argument('--candidates', type=Path, required=True)
    ap.add_argument('--out', type=Path, default=ROOT / '.local' / 'demo-b')
    ap.add_argument('--no-time', action='store_true', help='check and verify only')
    args = ap.parse_args(argv)
    try:
        source = args.source.read_bytes()
        kernel = admit_source(parse_source(source))
        files = sorted(args.candidates.glob('*.json'))
        results = review_candidates(source, [(f.stem, f.read_bytes()) for f in files])
    except SoundnessAlarm as alarm:
        print(alarm)
        return 2
    except DiagnosticError as error:
        print(f'beryl refused {args.source.name}: {error.code}: {error.message}')
        return 1
    except OSError as error:
        print(f'beryl could not read {error.filename}: {error.strerror}')
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    baseline = None if args.no_time else time_plan(kernel, source, make_scale_plan(kernel), 'baseline', args.out)
    print(f'{"candidate":<26} {"verdict":<9} {"reason":<22} {"time":>10} {"vs planner":>10}')
    fastest = None
    for result in results:
        ns = None if args.no_time or not result.accepted else time_plan(kernel, source, result.plan, result.name, args.out)
        speed = f'{baseline / ns:.2f}x' if ns and baseline else '-'
        if ns and baseline:
            fastest = max(fastest or 0, baseline / ns)
        verdict = 'accepted' if result.accepted else 'refused'
        print(f'{result.name:<26} {verdict:<9} {result.reason:<22} {_shown(ns):>10} {speed:>10}')
        if not result.accepted and result.detail:
            print(f'{"":<26}   {result.detail[:100]}')
    refused = Counter(r.reason for r in results if not r.accepted)
    accepted = sum(r.accepted for r in results)
    by_reason = ', '.join(f'{reason} {count}' for reason, count in sorted(refused.items()))
    print(f'\n{len(results)} candidates: {sum(refused.values())} rejected ({by_reason or "none"}), '
          f'{accepted} accepted; fastest {f"{fastest:.2f}x" if fastest else "not timed"}; '
          'every accepted plan matched the reference')
    return 0


if __name__ == '__main__':
    sys.exit(main())
