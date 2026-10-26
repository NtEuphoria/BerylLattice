"""Axiom native backend for the benchmark protocol: check once, then run many.

argv: kernel pattern a b min_ms max_reps [cap] [objective]
env:  BENCH_CC (default clang), BENCH_CFLAGS (default -O3; bench/run.py passes its --cflags, -O3 -march=native by default)

Compile time, logged as `compile_ns`, is everything before the first run:
compile_native_source (fresh admission, ranked checked selection, C emission;
per-phase times from its own trace) plus the C compiler and linker.
`ns_median` is one call of the generated beryl_kernel, timed by
impl/axiom_native_harness.c with the same protocol and checksum as the C and
Rust baselines. Kernels Axiom cannot admit report the real diagnostic.
"""
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'axiom' / 'src'))

from axiom_adapter import request  # noqa: E402
from catalog import KERNELS  # noqa: E402
from axiom.compilation_trace import CompilationTrace  # noqa: E402
from axiom.frontend import admit_source, parse_source  # noqa: E402
from axiom.model import DiagnosticError  # noqa: E402
from axiom.source_compilation import compile_native_source  # noqa: E402


def harness_object(cc, flags):
    """Compile the timing harness once per (compiler, flags, source) and reuse it.

    The harness is benchmark infrastructure, not part of an Axiom program, and
    its windows.h include alone costs about 0.6 s, so it is cached under
    .local/bench-build and its one-time compile is logged separately.
    """
    src = HERE / 'impl' / 'axiom_native_harness.c'
    key = hashlib.sha256(json.dumps([cc, flags, src.read_bytes().hex()]).encode()).hexdigest()[:16]
    out = HERE.parent / '.local' / 'bench-build' / f'harness-{key}.o'
    if out.exists():
        return out, 0
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_suffix(f'.{os.getpid()}.tmp')
    start = time.perf_counter_ns()
    built = subprocess.run([cc, *flags, '-std=c11', '-fno-lto', '-c', str(src), '-o', str(partial)],
                           capture_output=True, text=True, timeout=600)
    if built.returncode != 0:
        raise RuntimeError(built.stderr[-2000:])
    os.replace(partial, out)  # atomic publish: a concurrent run never sees a partial object
    return out, time.perf_counter_ns() - start


def _unquote(token):
    """Undo `clang -###` quoting: "..." with backslash-escaped backslashes and quotes."""
    if len(token) < 2 or token[0] != '"' or token[-1] != '"':
        return token
    out, chars, i = [], token[1:-1], 0
    while i < len(chars):
        if chars[i] == '\\' and i + 1 < len(chars) and chars[i + 1] in '\\"':
            out.append(chars[i + 1])
            i += 2
        else:
            out.append(chars[i])
            i += 1
    return ''.join(out)


class _Toolchain:
    """Run clang's own internal compile (-cc1) and link (ld.lld) commands directly.

    On Windows the clang driver spends about 70-100 ms per call detecting its
    toolchain before doing any work. The exact commands it would run are read
    once from `clang -###` with placeholder paths, then reused with real paths.
    On first resolution both direct commands are checked to produce
    byte-identical output to the driver; otherwise the driver is used.
    """

    def __init__(self, cc, flags, harness, workdir, resolve=True):
        self.cc, self.flags, self.harness = cc, flags, harness
        self.compile_argv = self.link_argv = None
        if not resolve:
            return
        cache = harness.with_name(harness.stem + '-toolchain.json')
        if cache.exists():
            self.compile_argv, self.link_argv = json.loads(cache.read_text(encoding='utf-8'))
            return
        try:
            self._resolve(workdir)
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            self.compile_argv = self.link_argv = None
        # Cache only a verified direct plan; a failed check is retried next time.
        if self.direct:
            partial = cache.with_suffix(f'.{os.getpid()}.tmp')
            partial.write_text(json.dumps([self.compile_argv, self.link_argv]), encoding='utf-8')
            os.replace(partial, cache)

    def _internal(self, driver_argv, marker):
        listing = subprocess.run([*driver_argv, '-###'], capture_output=True, text=True, timeout=120).stderr
        lines = [line for line in listing.splitlines() if marker in line]
        if len(lines) != 1:
            raise ValueError('unexpected driver plan')
        return [_unquote(token) for token in shlex.split(lines[0], posix=False)]

    def _resolve(self, work):
        src, obj, exe = work / 'probe.c', work / 'probe.o', work / 'probe.exe'
        src.write_text('#include <stdint.h>\nint32_t beryl_kernel(const int32_t *i, int32_t *o) '
                       '{ o[0] = i[0]; return 0; }\n', encoding='utf-8', newline='\n')
        compile_argv = self._internal(self._compile_driver(src, obj), '"-cc1"')
        subprocess.run(self._compile_driver(src, obj), check=True, capture_output=True, timeout=120)
        # Resolve the link plan only once its input exists; the driver drops missing inputs.
        link_argv = self._internal(self._link_driver(obj, exe), 'ld.lld')
        subprocess.run(self._link_driver(obj, exe), check=True, capture_output=True, timeout=120)
        reference_obj, reference_exe = obj.read_bytes(), exe.read_bytes()
        subprocess.run(compile_argv, check=True, capture_output=True, timeout=120)
        subprocess.run(link_argv, check=True, capture_output=True, timeout=120)
        if obj.read_bytes() == reference_obj and exe.read_bytes() == reference_exe:
            self.compile_argv = self._template(compile_argv, {str(src): '{src}', str(obj): '{obj}'})
            self.link_argv = self._template(link_argv, {str(obj): '{obj}', str(exe): '{exe}'})

    @staticmethod
    def _template(argv, names):
        out = [names.get(a, a) for a in argv]
        if sum(a in names.values() for a in out) != len(names):
            raise ValueError('placeholder not found exactly once')
        return out

    def _compile_driver(self, src, obj):
        return [self.cc, *self.flags, '-std=c11', '-fno-lto', '-Dmain=beryl_generated_main', '-c', str(src), '-o', str(obj)]

    def _link_driver(self, obj, exe):
        return [self.cc, str(self.harness), str(obj), '-o', str(exe)]

    def compile(self, src, obj):
        if self.compile_argv is None:
            return self._compile_driver(src, obj)
        return [a.replace('{src}', str(src)).replace('{obj}', str(obj)) for a in self.compile_argv]

    def link(self, obj, exe):
        if self.link_argv is None:
            return self._link_driver(obj, exe)
        return [a.replace('{obj}', str(obj)).replace('{exe}', str(exe)) for a in self.link_argv]

    @property
    def direct(self):
        return self.compile_argv is not None


def emit(record):
    print(json.dumps(record))
    return 0


def main():
    kernel, pattern = sys.argv[1], sys.argv[2]
    a, b, min_ms, max_reps = (int(v) for v in sys.argv[3:7])
    cap = int(sys.argv[7]) if len(sys.argv) > 7 else None
    objective = sys.argv[8] if len(sys.argv) > 8 else None
    base = dict(impl='axiom-native', kernel=kernel, backend='native-c', cap=cap, objective=objective)
    source, _, n_out, _ = request(kernel, pattern, a, b, cap, objective)
    if source is None:
        return emit(dict(base, status='unsupported', diagnostic=dict(
            stage='grammar', code='NOT_EXPRESSIBLE', missing=KERNELS[kernel]['missing'])))
    try:
        admitted = admit_source(parse_source(source))
    except DiagnosticError as error:
        return emit(dict(base, status='unsupported', diagnostic=dict(
            stage='admit', code=error.code, message=error.message,
            missing=KERNELS[kernel]['missing'])))

    trace = CompilationTrace()
    start = time.perf_counter_ns()
    compiled = compile_native_source(source, trace=trace)
    axiom_ns = time.perf_counter_ns() - start
    artifact = compiled.artifact
    if artifact is None:
        return emit(dict(base, status='error', diagnostic=dict(
            stage='compile', code=compiled.search.termination_reason.value, message=compiled.search.reason)))
    cc = os.environ.get('BENCH_CC', 'clang')
    flags = shlex.split(os.environ.get('BENCH_CFLAGS', '-O3'))
    if admitted.output_type == 'i64':
        flags.append('-DBERYL_OUT=int64_t')  # the harness's output array type (its own cached object)
    exe ='.exe' if os.name == 'nt' else ''
    try:
        harness, harness_cc_ns = harness_object(cc, flags)
    except RuntimeError as error:
        return emit(dict(base, status='error', diagnostic=dict(stage='cc', code='CC_FAILED', message=str(error))))
    with tempfile.TemporaryDirectory(prefix='axiom-native-') as tmp:
        tmp = Path(tmp)
        (tmp / 'kernel.c').write_bytes(artifact.c_source)
        # compile_ns covers only what a fresh Axiom program costs: its own C and the link.
        steps = {}
        # BENCH_DRIVER=1 forces the plain clang driver (for comparison runs).
        tools = _Toolchain(cc, flags, harness, tmp, resolve=os.environ.get('BENCH_DRIVER') != '1')
        for step, cmd in (('kernel_cc', tools.compile(tmp / 'kernel.c', tmp / 'kernel.o')),
                          ('link', tools.link(tmp / 'kernel.o', tmp / f'run{exe}'))):
            start = time.perf_counter_ns()
            built = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            steps[step] = time.perf_counter_ns() - start
            if built.returncode != 0:
                return emit(dict(base, status='error', diagnostic=dict(
                    stage='cc', code='CC_FAILED', message=built.stderr[-2000:])))
        cc_ns = steps['kernel_cc'] + steps['link']
        argv = [pattern, str(a), str(b), str(min_ms), str(max_reps),
                str(artifact.input_count), str(artifact.output_count)]
        try:
            ran = subprocess.run([str(tmp / f'run{exe}'), *argv], capture_output=True, text=True, timeout=900)
        except OSError as error:  # e.g. Windows Application Control; logged, never bypassed
            return emit(dict(base, status='blocked', diagnostic=dict(code='OS_LAUNCH_REFUSED', message=str(error))))
        hand = None
        hand_src = HERE / 'impl' / 'hand' / f'{kernel}.c'
        if hand_src.exists():
            # Like-for-like control: hand-written C, same ABI, shape, types, harness and flags.
            built = subprocess.run([cc, *flags, '-std=c11', '-fno-lto', f'-DBERYL_H={artifact.height}',
                                    f'-DBERYL_W={artifact.width}', '-c', str(hand_src), '-o', str(tmp / 'hand.o')],
                                   capture_output=True, text=True, timeout=600)
            if built.returncode == 0:
                built = subprocess.run([cc, str(harness), str(tmp / 'hand.o'), '-o', str(tmp / f'hand{exe}')],
                                       capture_output=True, text=True, timeout=600)
            try:
                if built.returncode == 0:
                    out = subprocess.run([str(tmp / f'hand{exe}'), *argv], capture_output=True, text=True, timeout=900)
                    hand = json.loads(out.stdout.strip().splitlines()[-1]) if out.returncode == 0 else None
            except (OSError, ValueError, IndexError):
                hand = None
    if ran.returncode != 0 or not ran.stdout.strip():
        return emit(dict(base, status='error', diagnostic=dict(stage='run', code=f'EXIT_{ran.returncode}',
                                                               message=(ran.stderr or ran.stdout)[-2000:])))
    result = json.loads(ran.stdout.strip().splitlines()[-1])
    phases = {name: record['elapsed_ns'] for name, record in trace.report()['phases'].items()}
    selected = compiled.search.selected_plan
    check = compiled.search.selected_check
    return emit(dict(base, **{k: v for k, v in result.items() if k != 'impl'},
                     compile_ns=axiom_ns + cc_ns, axiom_compile_ns=axiom_ns, cc_ns=cc_ns,
                     kernel_cc_ns=steps['kernel_cc'], link_ns=steps['link'], harness_cc_ns=harness_cc_ns,
                     cc_mode='direct' if tools.direct else 'driver',
                     hand_c=hand, compile_phases_ns=phases, codegen=artifact.codegen_version,
                     loop_version=artifact.loop_version, c_bytes=len(artifact.c_source),
                     plan=dict(id=selected.plan_id if selected else None,
                               workspace_bytes=check.workspace_bytes if check else None,
                               multiplication_ops=check.multiplication_ops if check else None)))


if __name__ == '__main__':
    sys.exit(main())
