#!/usr/bin/env python3
"""Demo: candidate plans (for example written by AI agents), checked by beryl.

    python tools/demo-checked-candidates.py --source bench/demo_b/program.ax \\
        --candidates docs/pitch/demo/candidates --no-time

Every *.json file in the candidates folder is an untrusted beryl-loop-plan-v1
record. Each is decoded, proved or refused by the template checker, and every
accepted plan is run against the source's reference meaning before it is
timed. Accepted plans are compiled with clang and timed with the bench harness
under --out (executables stay out of the temp folder), and compared with the
planner's own direct-v1 plan. --no-time only checks and verifies.

Each refusal gets a one-line reason in plain English; --codes also prints the
checker's own reason code and detail under it. Output fits 90 columns and shows
no file paths.
"""
import argparse
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
from axiom.scale_candidates import SoundnessAlarm, load_plan, review_candidates  # noqa: E402
from axiom.scale_checker import check_loop_plan  # noqa: E402
from axiom.scale_plan import make_scale_plan  # noqa: E402

HARNESS = ROOT / 'bench' / 'impl' / 'axiom_native_harness.c'
WIDTH = 90  # nothing printed is wider


def time_plan(kernel, source, plan, name, out):
    """Median ns per call of the plan's emitted kernel, or None if it could not run."""
    check = check_loop_plan(source, plan)
    artifact = emit_scale_c(kernel, plan, sha256(source).hexdigest(), check.plan_digest)
    c = out / f'{name}.c'
    c.write_bytes(artifact.c_source.replace(b'int main(void)', b'int beryl_unused_main(void)'))
    exe = out / f'{name}.exe'
    flags = ['-DBERYL_OUT=int64_t'] if kernel.output_type == 'i64' else []
    try:
        built = subprocess.run(['clang', '-O3', '-std=c11', *flags, str(c), str(HARNESS), '-o', str(exe)],
                               capture_output=True, text=True)
    except OSError:  # no clang on this machine
        return None
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
    if ns is None:
        return '-'
    return f'{ns / 1e6:.2f} ms' if ns >= 1_000_000 else f'{ns / 1000:.1f} us' if ns >= 1000 else f'{ns} ns'


def _many(count, noun):
    return f'{count} {noun}' + ('' if count == 1 else 's')


def _coverage(plan, kernel, detail):
    """Why the loops of a refused plan miss the output, in plain words."""
    if (detail or '').startswith('producer'):
        return 'covers the intermediate image wrongly'
    try:
        (_, rows), (_, cols) = plan.stages[-1].loops
        rows, cols = int(rows), int(cols)
    except (AttributeError, IndexError, TypeError, ValueError):
        return 'does not write each output exactly once'
    if rows > kernel.height:
        return f'runs {_many(rows - kernel.height, "row")} past the edge of the image'
    if cols > kernel.width:
        return f'runs {_many(cols - kernel.width, "column")} past the edge of the image'
    if rows < kernel.height:
        missed = kernel.height - rows
        return 'never writes the last row' if missed == 1 else f'never writes the last {missed} rows'
    if cols < kernel.width:
        missed = kernel.width - cols
        return 'never writes the last column' if missed == 1 else f'never writes the last {missed} columns'
    return 'does not write each output exactly once'


def plain_reason(reason, detail, plan, kernel):
    """A checker refusal in plain English, short enough for the table."""
    if reason == 'COVERAGE_MISMATCH':
        return _coverage(plan, kernel, detail)
    if reason == 'STRUCTURAL_MISMATCH':
        return ('a different formula in the first pass' if (detail or '').startswith('producer')
                else 'computes a different formula')
    return {'SEMANTIC_DIGEST_MISMATCH': 'belongs to a different program',
            'ARITHMETIC_OVERFLOW': 'a sum could overflow its integer type',
            'LOAD_OUT_OF_BOUNDS': 'reads outside the input image',
            'INVALID_PLAN': 'is not a well-formed plan'}.get(reason, 'could not be proved')


def _printable(name, width):
    name = ''.join(ch if ch.isprintable() else '?' for ch in name)
    return name if len(name) <= width else name[:width - 1] + '~'


def _strerror(error):
    return (error.strerror or type(error).__name__).lower()


def _run(args):
    try:
        source = args.source.read_bytes()
    except OSError as error:
        print(f'beryl could not read the source program: {_strerror(error)}')
        return 1
    try:
        kernel = admit_source(parse_source(source))
    except DiagnosticError as error:
        code = f' ({error.code})' if args.codes else ''
        print(f'beryl refused the source program{code}: {error.message}'[:WIDTH])
        return 1
    if not args.candidates.is_dir():
        # A mistyped path must not read like a real "0 candidates" result.
        print('beryl could not find the candidate plans: no such folder')
        return 1
    try:
        candidates = [(f.stem, f.read_bytes()) for f in sorted(args.candidates.glob('*.json'))]
    except OSError as error:
        print(f'beryl could not read a candidate plan: {_strerror(error)}')
        return 1
    try:
        results = review_candidates(source, candidates)
    except SoundnessAlarm as alarm:
        print(str(alarm)[:WIDTH])
        return 2
    plans = dict(candidates)
    timed = not args.no_time
    baseline = None
    if timed:
        args.out.mkdir(parents=True, exist_ok=True)
        baseline = time_plan(kernel, source, make_scale_plan(kernel), 'baseline', args.out)
    header = f'{"plan":<16} {"verdict":<9} {"reason":<42}'
    print(f'{header} {"time":>9} {"vs planner":>10}' if timed else header.rstrip())
    fastest = None
    for result in results:
        if result.accepted:
            reason = 'proved equal to the program'
        else:
            reason = plain_reason(result.reason, result.detail, load_plan(plans[result.name]), kernel)
        verdict = 'ACCEPTED' if result.accepted else 'REFUSED'
        row = f'{_printable(result.name, 16):<16} {verdict:<9} {reason[:42]:<42}'
        if timed:
            ns = time_plan(kernel, source, result.plan, result.name, args.out) if result.accepted else None
            if ns and baseline:
                fastest = max(fastest or 0, baseline / ns)
            row = f'{row} {_shown(ns):>9} {f"{baseline / ns:.2f}x" if ns and baseline else "-":>10}'
        print(row.rstrip())
        if args.codes and not result.accepted:
            print(f'{"":<17}{result.reason}: {result.detail or "-"}'[:WIDTH])
    refused = sum(not r.accepted for r in results)
    accepted = len(results) - refused
    print()
    if timed:
        print(f'fastest accepted plan: {f"{fastest:.2f}x the planner" if fastest else "not measured"}')
    ending = 'every accepted plan matched the reference' if accepted else 'no plan was accepted'
    print(f'{_many(len(results), "candidate")}: {refused} REFUSED, {accepted} ACCEPTED; {ending}')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog='beryl-demo', description=__doc__.splitlines()[0])
    ap.add_argument('--source', type=Path, required=True)
    ap.add_argument('--candidates', type=Path, required=True)
    ap.add_argument('--out', type=Path, default=ROOT / '.local' / 'demo-b')
    ap.add_argument('--no-time', action='store_true', help='check and verify only')
    ap.add_argument('--codes', action='store_true', help="also print the checker's reason codes")
    args = ap.parse_args(argv)
    try:
        return _run(args)
    except Exception as error:  # one line on screen, never a traceback or a path
        print(f'beryl stopped on an unexpected error ({type(error).__name__})')
        return 1


if __name__ == '__main__':
    sys.exit(main())
