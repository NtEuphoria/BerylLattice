"""Read-only current-compiler profile; no proposed architecture is implemented."""
import argparse
import cProfile
import hashlib
import json
import platform
import pstats
import statistics
import subprocess
import sys
import time
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--clang', type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    sys.path[:0] = [str(args.repo / 'axiom/src'), str(args.repo / 'axiom')]
    from axiom.frontend import admit_source, parse_source
    from axiom.model import Limits
    from axiom.selection import select_plan
    from axiom.native_codegen import emit_native_c
    from axiom.playground_service import prepare_compiled_demo
    from tests.helpers import stencil_source

    report = dict(revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=args.repo, text=True).strip(),
        platform=platform.platform(), python=sys.version,
        scope='Warm imports/runtime and filesystem; fresh source preparation without artifact cache; timings descriptive, no implemented speedup. Profiled timings separate from unprofiled samples.',
        clang_version=subprocess.check_output([str(args.clang), '--version'], text=True).splitlines()[0],
        samples=7, cases=[], native=[])
    for h, w, cap in [(1, 1, 64), (5, 7, 64), (15, 15, 64), (15, 15, 128), (1, 127, 1024), (127, 1, 16)]:
        source = stencil_source(h, w, cap)
        prepared = prepare_compiled_demo(source.decode())
        assert prepared['status'] == 'prepared', prepared
        times = []
        for _ in range(7):
            start = time.perf_counter_ns()
            result = prepare_compiled_demo(source.decode())
            times.append((time.perf_counter_ns() - start) / 1e6)
            assert result['status'] == 'prepared'
        profiler = cProfile.Profile()
        profiler.runcall(prepare_compiled_demo, source.decode())
        stats = pstats.Stats(profiler)
        functions = []
        for (filename, line, name), (primitive, calls, self_s, total_s, _) in stats.stats.items():
            if '/axiom/' in filename:
                functions.append(dict(file=str(Path(filename).relative_to(args.repo)), line=line,
                    name=name, calls=calls, primitive_calls=primitive, self_ms=self_s*1000, cumulative_ms=total_s*1000))
        functions.sort(key=lambda f: f['cumulative_ms'], reverse=True)
        report['cases'].append(dict(h=h, w=w, cap=cap, source_sha256=hashlib.sha256(source).hexdigest(),
            selected=result['selected'], samples_ms=times, median_ms=statistics.median(times),
            wasm_bytes=len(__import__('base64').b64decode(result['wasm_base64'])), profile=functions))

    for cap in (0, 128):
        source = stencil_source(15, 15, cap)
        kernel = admit_source(parse_source(source, Limits()))
        selected = select_plan(kernel, Limits(), 100000, kernel.objective)
        artifact = emit_native_c(source, selected.selected_plan_bytes)
        stem = args.output / f'15x15-cap{cap}'
        c_path = stem.with_suffix('.c')
        c_path.write_bytes(artifact.c_source)
        compile_samples = {level: [] for level in ('-O1', '-O2', '-O3')}
        for sample in range(5):
            levels = list(compile_samples)
            for level in levels[sample % 3:] + levels[:sample % 3]:
                executable = Path(str(stem) + level)
                start = time.perf_counter_ns()
                subprocess.run([str(args.clang), level, '-std=c11', str(c_path), '-o', str(executable)], check=True, capture_output=True)
                elapsed = (time.perf_counter_ns() - start) / 1e6
                compile_samples[level].append(elapsed)
                data = [i % 1024 for i in range(256)]
                raw = subprocess.check_output([str(executable)], input=('15 15\n' + ' '.join(map(str, data)) + '\n').encode())
                expected = []
                for r in range(15):
                    for c in range(15):
                        i = r*16+c
                        expected.append(sum((data[j]+1)**2 for j in (i, i+1, i+16, i+17)))
                assert json.loads(raw) == expected
        object_file = Path(str(stem) + '.o')
        trace_path = Path(str(stem) + '-trace.json')
        subprocess.run([str(args.clang), '-O3', '-std=c11', '-c', str(c_path), '-o', str(object_file),
            '-ftime-trace=' + str(trace_path)], check=True, capture_output=True)
        trace = json.loads(trace_path.read_text())
        totals = {item['name']: item['dur']/1000 for item in trace['traceEvents'] if item.get('name', '').startswith('Total ')}
        report['native'].append(dict(h=15, w=15, cap=cap, selected=selected.selected_plan.plan_id,
            plan_operations=len(selected.selected_plan.operations), c_bytes=len(artifact.c_source), c_sha256=artifact.c_digest,
            samples_ms=compile_samples, median_ms={k:statistics.median(v) for k,v in compile_samples.items()},
            object_bytes=object_file.stat().st_size, clang_trace_totals_ms=totals,
            flags_note='Optimization levels are throwaway compilation experiments only; runtime throughput is not evaluated and no release policy is changed.'))
    target = args.output / 'profile.json'
    target.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({ 'path': str(target), 'cases':[{k:v for k,v in c.items() if k in ('h','w','cap','median_ms','wasm_bytes')} for c in report['cases']], 'native':report['native']}, indent=2))


if __name__ == '__main__':
    main()
