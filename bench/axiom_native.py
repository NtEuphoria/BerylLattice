"""Axiom native backend for the benchmark protocol: check once, then run many.

argv: kernel pattern a b min_ms max_reps [cap] [objective]
env:  BENCH_CC (default clang), BENCH_CFLAGS (default -O3)

Compile time, logged as `compile_ns`, is everything before the first run:
compile_native_source (fresh admission, ranked checked selection, C emission;
per-phase times from its own trace) plus the C compiler and linker.
`ns_median` is one call of the generated beryl_kernel, timed by
impl/axiom_native_harness.c with the same protocol and checksum as the C and
Rust baselines. Kernels Axiom cannot admit report the real diagnostic.
"""
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
        admit_source(parse_source(source))
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
    exe = '.exe' if os.name == 'nt' else ''
    with tempfile.TemporaryDirectory(prefix='axiom-native-') as tmp:
        tmp = Path(tmp)
        (tmp / 'kernel.c').write_bytes(artifact.c_source)
        start = time.perf_counter_ns()
        for cmd in ([cc, *flags, '-std=c11', '-fno-lto', '-Dmain=beryl_generated_main',
                     '-c', str(tmp / 'kernel.c'), '-o', str(tmp / 'kernel.o')],
                    [cc, *flags, '-std=c11', '-fno-lto', str(HERE / 'impl' / 'axiom_native_harness.c'),
                     str(tmp / 'kernel.o'), '-o', str(tmp / f'run{exe}')]):
            built = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if built.returncode != 0:
                return emit(dict(base, status='error', diagnostic=dict(
                    stage='cc', code='CC_FAILED', message=built.stderr[-2000:])))
        cc_ns = time.perf_counter_ns() - start
        argv = [pattern, str(a), str(b), str(min_ms), str(max_reps),
                str(artifact.input_count), str(artifact.output_count)]
        try:
            ran = subprocess.run([str(tmp / f'run{exe}'), *argv], capture_output=True, text=True, timeout=900)
        except OSError as error:  # e.g. Windows Application Control; logged, never bypassed
            return emit(dict(base, status='blocked', diagnostic=dict(code='OS_LAUNCH_REFUSED', message=str(error))))
        hand = None
        if kernel == 'sq2x2':
            # Like-for-like control: hand-written C, same ABI, shape, types, harness and flags.
            built = subprocess.run([cc, *flags, '-std=c11', '-fno-lto', f'-DBERYL_H={a}', f'-DBERYL_W={b}',
                                    str(HERE / 'impl' / 'sq2x2_specialized.c'),
                                    str(HERE / 'impl' / 'axiom_native_harness.c'), '-o', str(tmp / f'hand{exe}')],
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
                     hand_c=hand, compile_phases_ns=phases, codegen=artifact.codegen_version,
                     loop_version=artifact.loop_version, c_bytes=len(artifact.c_source),
                     plan=dict(id=selected.plan_id if selected else None,
                               workspace_bytes=check.workspace_bytes if check else None,
                               multiplication_ops=check.multiplication_ops if check else None)))


if __name__ == '__main__':
    sys.exit(main())
