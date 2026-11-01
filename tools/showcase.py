#!/usr/bin/env python3
"""The paced runner for the beryl Loom: four screens, Enter between beats.

    python tools/showcase.py              # live: Enter advances
    python tools/showcase.py --no-pause   # capture and tests

0  the saturation pair: an exact u8 x i8 dot product next to the unchecked
   vpmaddubsw result (a standalone intrinsics test, built once in WSL)
1  the energy program refused, fixed with i64, and its worst case run natively
2  candidate plans checked against the image-filter program
3  the pair-bound rule: inputs to 127 take the fast pair, inputs to 128 do not

The screen never shows a file path, a file name, an internal version string
or a traceback: every failure prints only "step failed". Native code is built
with gcc in WSL (or the local shell on Linux) and cached under ~/loom, never
in /tmp; Windows Application Control is never bypassed.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import textwrap
import warnings

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / 'docs' / 'pitch' / 'demo'
CANDIDATES = DEMO / 'candidates'
FILTER_PROGRAM = ROOT / 'bench' / 'demo_b' / 'program.ax'
CHECKER = ROOT / 'tools' / 'demo-checked-candidates.py'
I16_MAX, I32_MAX = 32767, 2**31 - 1
WIDTH = 90
# Shown as stored, never timed live: medians of three quiet rounds on the hardened compiler.
# Source: the scale spec's "Rerun on the hardened compiler (2026-10-31)"
# (docs/superpowers/specs/2026-10-19-scale-design.md); update both together.
STORED_LAYER = ('recorded 2026-10-31 · 256 x 256 x 256 layer, 1 thread:',
                'full range, exact path 690 µs · inputs to 127, fast pair 327 µs')
MACHINE = 'AMD Ryzen 3 3100'
ANSI = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')
FORBIDDEN = ('axiom', '.ax', 'beryllattice', 'codegen', 'termination_reason', 'traceback',
             ':\\', '/mnt/', 'appdata')
RANGE = re.compile(r'input\s+\w+\s*:\s*(\w+)\[[^\]]*\]\s*in\s*(-?\d+)\.\.=(-?\d+)')
OVERFLOW = re.compile(r'reach (\d+) > (\d+); at most (\d+) terms fit in i32;.*?`let (\w+): i64')


class StepFailed(Exception):
    """A step could not show its result honestly; the screen says only "step failed"."""


def group(n):
    return f'{int(n):,}'


def plain_refusal(reason):
    """A refusal reason in plain words: no diagnostic code, no byte offset, digits grouped."""
    known = OVERFLOW.search(reason)
    if known:
        reach, limit, fit, name = known.groups()
        return (f'the sum can reach {group(reach)} > {group(limit)} · at most {group(fit)} terms fit in '
                f'32 bits · fix: declare {name}: i64')
    text = re.sub(r'^[A-Z][A-Z0-9_]*:\s*', '', reason.strip())
    text = re.sub(r'\s+at byte \d+', '', text).replace('`', '')
    return re.sub(r'\b\d{4,}\b', lambda m: group(m.group()), text)


def ranges(source_text):
    """[(element type, low, high)] for each declared input, in order."""
    return [(kind, int(low), int(high)) for kind, low, high in RANGE.findall(source_text)]


def pair_bound(source_text):
    """(largest activation, largest weight magnitude, 2 x a x w) of a u8 x i8 program."""
    declared = {kind: (low, high) for kind, low, high in ranges(source_text)}
    activation = max(abs(v) for v in declared['u8'])
    weight = max(abs(v) for v in declared['i8'])
    return activation, weight, 2 * activation * weight


class Painter:
    """ANSI colour when the terminal takes it, plain text otherwise."""
    def __init__(self, on):
        self.on = on

    def _paint(self, code, text):
        return f'\x1b[{code}m{text}\x1b[0m' if self.on else text

    def red(self, text):
        return self._paint('1;31', text)

    def green(self, text):
        return self._paint('1;32', text)

    def amber(self, text):
        return self._paint('1;33', text)

    def mark(self, text):
        return self._paint('1;36', text)

    def dim(self, text):
        return self._paint('2', text)


def enable_vt(stream):
    """Turn on VT escape handling for a Windows console; True when colour can be shown."""
    try:
        if not stream.isatty():
            return False
        if os.name != 'nt':
            return True
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


def _compiler():
    sys.path.insert(0, str(ROOT / 'axiom' / 'src'))
    from axiom.frontend import parse_source
    from axiom.model import Limits
    from axiom.reference import ExecutionStatus, evaluate_source
    from axiom.source_compilation import compile_native_source
    return compile_native_source, Limits, parse_source, evaluate_source, ExecutionStatus


def compile_source(path):
    compile_native_source, Limits, *_ = _compiler()
    return compile_native_source(path.read_bytes(), Limits())


def native(script, data=b'', timeout=180):
    """Run a POSIX sh script in WSL (or locally on Linux); its stdout, or StepFailed.

    The script must hold no double quote or backslash, so the Windows command
    line reaches sh unchanged; file contents travel on stdin, never as paths.
    """
    if '"' in script or '\\' in script:
        raise StepFailed('unsafe script')
    shell = ['wsl', '-e', 'sh', '-c'] if os.name == 'nt' else ['sh', '-c']
    ran = subprocess.run([*shell, script], input=data, capture_output=True, timeout=timeout)
    if ran.returncode != 0:
        raise StepFailed('native run failed')
    return ran.stdout.decode('utf-8', 'replace')


def cached_build(name, c_source, flags):
    """Shell text that rebuilds ~/loom/<name> only when its C text (with flags) changed."""
    stamp = f'/* gcc {flags} */\n'.encode() + c_source
    script = (f'mkdir -p ~/loom && cd ~/loom && cat > {name}.new.c && '
              f'if cmp -s {name}.new.c {name}.c && [ -x {name} ]; then rm -f {name}.new.c; '
              f'else rm -f {name} && mv {name}.new.c {name}.c && gcc {flags} {name}.c -o {name}; fi')
    return script, stamp


def program_lines(text, marked=()):
    """A program printed without its name; marked lines get a colour and a '>' gutter."""
    return [('> ', line, True) if i in marked else ('  ', line, False)
            for i, line in enumerate(text.splitlines())]


# Steps yield ('show', [line, ...]) or ('pause',). Each computes before it shows.

def step_pair(ctx):
    script, data = cached_build('sat', (ctx.demo / 'pair-saturation.c').read_bytes(), '-O2 -mavx2')
    out = native(script + ' && ./sat', data)
    values = {}
    for line in out.splitlines():
        found = re.match(r'(.+?)\s{2,}(-?\d+)$', line.strip())
        if found:
            values[found.group(1)] = int(found.group(2))
    exact, fast = values['right answer'], values['fast instruction, no range check']
    if values['inputs to 127, right answer'] != values['inputs to 127, fast instruction']:
        raise StepFailed('in-range pair disagrees')
    ctx.pair = (exact, fast)
    yield 'show', pair_lines(ctx)
    yield 'show', ['', ctx.paint.dim('my own test program, no guard · not PyTorch'),
                   ctx.paint.dim(f'{MACHINE} · AVX2 (vpmaddubsw + vpmaddwd)')]


def pair_lines(ctx):
    exact, fast = ctx.pair
    note = '      <- about half' if 0.4 < fast / exact < 0.6 else ''
    return [f'{"right answer":<36} {group(exact):>12}',
            ctx.paint.red(f'{"fast instruction, no range check":<36} {group(fast):>12}') + note]


def step_energy(ctx):
    _, _, parse_source, evaluate_source, ExecutionStatus = _compiler()
    broken = (ctx.demo / 'energy.ax').read_text(encoding='utf-8')
    fixed = (ctx.demo / 'energy-i64.ax').read_text(encoding='utf-8')
    refused = compile_source(ctx.demo / 'energy.ax')
    if refused.artifact is not None or not refused.search.reason:
        raise StepFailed('expected a refusal')
    reason = plain_refusal(refused.search.reason).split(' · ')
    compiled = compile_source(ctx.demo / 'energy-i64.ax')
    artifact, kernel = compiled.artifact, compiled.kernel
    if artifact is None:
        raise StepFailed('expected a compile')
    [(_, _, high)] = ranges(fixed)
    count = artifact.input_count
    reference = evaluate_source(parse_source(fixed.encode()), [high] * count, [0] * artifact.output_count)
    if reference.status != ExecutionStatus.SUCCESS:
        raise StepFailed('reference refused the worst case')
    script, data = cached_build('energy', artifact.c_source, '-O2 -pthread')
    run = (f' && {{ echo {kernel.height} {kernel.width}; yes {high} | head -n {count}; }} | ./energy')
    result = json.loads(native(script + run, data))
    if list(result) != list(reference.output):
        raise StepFailed('native result differs from the reference')
    before = broken.splitlines()
    changed = {i for i, line in enumerate(fixed.splitlines())
               if line not in before and not line.lstrip().startswith('//')}
    yield 'show', program_lines(broken)
    yield 'pause',
    yield 'show', ['', f'{ctx.paint.red("REFUSED")}   {reason[0]}', *[f'{"":10}{part}' for part in reason[1:]]]
    yield 'pause',
    yield 'show', ['', *program_lines(fixed, changed), '', ctx.paint.green('COMPILED')]
    yield 'pause',
    yield 'show', ['', f'worst case ({group(count)} readings of {group(high)})  ->  '
                   f'{", ".join(group(v) for v in result)}']


CODE = re.compile(r'\b[A-Z]{2,}(?:_[A-Z0-9]+)+\b')
PLAIN_CODES = {
    'COVERAGE_MISMATCH': 'the loops do not cover every output exactly once',
    'STRUCTURAL_MISMATCH': 'the plan computes a different formula',
    'SEMANTIC_DIGEST_MISMATCH': 'the plan was made for a different program',
}
VERDICTS = {'refused': 'refused', 'rejected': 'refused', 'accepted': 'accepted'}
SUMMARY = re.compile(r'(\d+) (?:candidates|plans): (\d+) (?:rejected|refused)\b.*?(\d+) accepted', re.I)
MATCHED = 'every accepted plan matched the reference'


def _plain_code(match):
    return PLAIN_CODES.get(match.group(), match.group().lower().replace('_', ' '))


def candidate_lines(paint, text):
    """The checker's table as plain rows: verdict in caps, reasons in words, no codes or timings."""
    rows, summary, last = [], None, None
    for line in text.splitlines():
        words = line.split()
        if SUMMARY.match(line.strip()):
            summary = line.strip()
        elif len(words) >= 2 and not line[:1].isspace() and words[1].lower() in VERDICTS:
            rest = line.split(None, 2)[2] if len(words) > 2 else ''
            reason = re.split(r'\s{2,}', rest.strip())[0] if rest.strip() else ''
            last = [words[0], VERDICTS[words[1].lower()], reason, []]
            rows.append(last)
        elif line[:1].isspace() and words and last is not None:
            last[3].append(line.strip())
    if not rows or summary is None:
        raise StepFailed('unreadable checker output')
    total, refused, accepted = (int(n) for n in SUMMARY.match(summary).groups())
    if (total, refused, accepted) != (len(rows), sum(r[1] == 'refused' for r in rows),
                                      sum(r[1] == 'accepted' for r in rows)):
        raise StepFailed('summary disagrees with the rows')
    name_w = max(10, *(len(r[0]) for r in rows)) + 2
    reason_w = WIDTH - name_w - 11
    lines = [paint.dim(f'{"plan":<{name_w}}{"verdict":<11}reason')]
    for name, verdict, reason, details in rows:
        if verdict == 'accepted':
            shown = '' if CODE.fullmatch(reason) or reason.upper() == 'VALID' else reason
            lines.append(f'{name:<{name_w}}{paint.green("ACCEPTED")}{"":3}{shown}'.rstrip())
            continue
        said = [] if CODE.fullmatch(reason) and details else [reason]
        said = ' · '.join(CODE.sub(_plain_code, part) for part in [*said, *details] if part)
        wrapped = textwrap.wrap(said, reason_w) or ['']
        lines.append(f'{name:<{name_w}}{paint.red("REFUSED")}{"":4}{wrapped[0]}'.rstrip())
        lines += [' ' * (name_w + 11) + part for part in wrapped[1:]]
    tail = [f'{total} plans: {refused} refused, {accepted} accepted']
    return [*lines, '', *tail, *([MATCHED] if MATCHED in summary else [])]


def step_candidates(ctx):
    folder = ctx.candidates
    plans = sorted(folder.glob('*.json')) if folder.is_dir() else []
    if not plans or not FILTER_PROGRAM.is_file():
        raise StepFailed('no plans')
    yield 'show', [f'{len(plans)} proposed plans for one image filter, each checked against the program', '']
    ran = subprocess.run([sys.executable, str(CHECKER), '--source', str(FILTER_PROGRAM),
                          '--candidates', str(folder), '--no-time'],
                         cwd=str(ROOT), capture_output=True, timeout=900)
    if ran.returncode != 0:
        raise StepFailed('checker failed')
    yield 'show', candidate_lines(ctx.paint, ran.stdout.decode('utf-8', 'replace'))


def step_pair_bound(ctx):
    shown = []
    for name in ('dense-127.ax', 'dense-128.ax'):
        text = (ctx.demo / name).read_text(encoding='utf-8')
        activation, weight, bound = pair_bound(text)
        compiled = compile_source(ctx.demo / name)
        if compiled.artifact is None:
            raise StepFailed('expected a compile')
        fast = 'madd' in compiled.artifact.codegen_version
        if fast != (bound <= I16_MAX):
            raise StepFailed('the chosen path disagrees with the bound')
        marked = {i for i, line in enumerate(text.splitlines()) if re.search(r':\s*u8\[', line)}
        arithmetic = f'pair bound 2 x {activation} x {weight} = {group(bound)}'
        verdict = (ctx.paint.green(f'{arithmetic} <= {group(I16_MAX)}  ->  FAST INSTRUCTION (vpmaddubsw)')
                   if fast else ctx.paint.amber(f'{arithmetic} > {group(I16_MAX)}  ->  EXACT WIDE PATH'))
        shown.append((text, marked, verdict))
    if ctx.pair is not None:
        yield 'show', pair_lines(ctx)
        yield 'pause',
    for i, (text, marked, verdict) in enumerate(shown):
        yield 'show', ['', *program_lines(text, marked), '', verdict]
        if i + 1 < len(shown):
            yield 'pause',
    yield 'pause',
    yield 'show', ['', *(ctx.paint.dim(line) for line in STORED_LAYER)]


STEPS =(step_pair, step_energy, step_candidates, step_pair_bound)


class Context:
    def __init__(self, args, paint):
        self.demo, self.candidates, self.paint = args.demo_dir, args.candidates, paint
        self.pause, self.pair = not args.no_pause, None


def _guarded(line):
    plain = ANSI.sub('', line).lower()
    if any(word in plain for word in FORBIDDEN) or str(ROOT).lower() in plain:
        raise StepFailed('leak')
    return line


def _write(text):
    sys.stdout.write(text)
    sys.stdout.flush()


def _windows_console(stream):
    """True only for a real Windows console. The NUL device and pipes claim isatty() there,
    but have no console mode."""
    if os.name != 'nt':
        return False
    try:
        import ctypes
        import msvcrt
        mode = ctypes.c_uint32()
        handle = msvcrt.get_osfhandle(stream.fileno())
        return bool(ctypes.windll.kernel32.GetConsoleMode(ctypes.c_void_p(handle), ctypes.byref(mode)))
    except (OSError, ValueError, AttributeError):
        return False


def _read_enter():
    """One key press. On a Windows console it is read without echo, so pressing Enter adds no
    blank line on camera; elsewhere a line of input. EOFError when input has ended."""
    if _windows_console(sys.stdin):
        import msvcrt
        if msvcrt.getwch() == '\x03':
            raise KeyboardInterrupt
        return
    if not sys.stdin.readline():
        raise EOFError


def _wait(ctx):
    if ctx.pause:
        try:
            _read_enter()
        except EOFError:
            ctx.pause = False


def _keep_wsl_warm():
    """WSL idles out in under a minute between beats, and then a step opens on a blank screen
    for seconds. A paced run on Windows keeps one idle WSL process alive until it ends."""
    if os.name != 'nt':
        return None
    try:
        return subprocess.Popen(['wsl', '-e', 'sleep', '3600'], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return None


def _render(ctx, rendered):
    if isinstance(rendered, tuple) and len(rendered) == 3:
        gutter, line, marked = rendered
        return ctx.paint.mark(gutter + line) if marked else gutter + line
    return rendered


def run_step(ctx, step):
    try:
        for event in step(ctx):
            if event[0] == 'pause':
                _wait(ctx)
                continue
            lines = [_guarded(_render(ctx, item)) for item in event[1]]
            _write(''.join(line + '\n' for line in lines))
        return True
    except KeyboardInterrupt:
        raise
    except BaseException:
        _write('step failed\n')
        return False


def _clear(ctx):
    if ctx.paint.on:
        _write('\x1b[2J\x1b[H')
    elif sys.stdout.isatty():
        os.system('cls' if os.name == 'nt' else 'clear')
    else:
        _write('\n')


def _steps(text):
    chosen = [int(part) for part in text.split(',') if part.strip()]
    if not chosen or any(not 0 <= n < len(STEPS) for n in chosen):
        raise argparse.ArgumentTypeError('steps are 0 to 3, comma separated')
    return chosen


def main(argv=None):
    warnings.simplefilter('ignore')
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(prog='showcase', description='beryl: the paced Loom runner')
    ap.add_argument('--no-pause', action='store_true', help='run every step without waiting for Enter')
    ap.add_argument('--steps', type=_steps, default=list(range(len(STEPS))), help='e.g. 0,1,3')
    ap.add_argument('--color', choices=('auto', 'always', 'never'), default='auto')
    ap.add_argument('--demo-dir', type=Path, default=DEMO, help=argparse.SUPPRESS)
    ap.add_argument('--candidates', type=Path, default=CANDIDATES, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    vt = enable_vt(sys.stdout)
    ctx = Context(args, Painter(args.color == 'always' or (args.color == 'auto' and vt)))
    failed = 0
    warm = _keep_wsl_warm() if ctx.pause else None
    try:
        for i, number in enumerate(args.steps):
            _clear(ctx)
            failed += not run_step(ctx, STEPS[number])
            if i + 1 < len(args.steps):
                _wait(ctx)
    except KeyboardInterrupt:
        _write('\n')
        return 130
    finally:
        if warm is not None:
            warm.terminate()
    return 1 if failed else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        sys.stdout.write('step failed\n')
        sys.exit(1)
