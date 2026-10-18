#!/usr/bin/env python3
"""Compare verified whole-process stencil requests; not a language speed ranking."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bench', ROOT / 'tools/benchmark-playground.py')
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default='clang')
    parser.add_argument('--rustc', default='rustc')
    parser.add_argument('--rust-self-contained', action='store_true', help='use bundled linker libraries for Windows GNU Rust')
    parser.add_argument('--samples', type=int, default=5)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.samples <= 30 or args.output.exists():
        parser.error('samples must be 1..30 and output must be a new path')
    versions = {name: subprocess.run([exe, '--version'], capture_output=True, text=True,
                                   check=True, timeout=30).stdout.splitlines()[0]
                for name, exe in [('C', args.cc), ('Rust', args.rustc)]}
    rust_flags = ['-O'] + (['-C', 'link-self-contained=yes'] if args.rust_self_contained else [])
    report = dict(schema_version=1, created_utc=datetime.now(timezone.utc).isoformat(),
                  platform=platform.platform(), python=platform.python_version(), compilers=versions,
                  scope='Whole-process wall time: startup, input decoding, calculation and output transfer. beryl additionally parses source, selects and checks a plan and compares an independent evaluation. Native baselines implement the formula directly. No speed ranking or browser timing.',
                  flags={'C': ['-O3', '-std=c11'], 'Rust': rust_flags}, samples=args.samples,
                  sources={name: hashlib.sha256((ROOT / 'tools/benchmarks' / name).read_bytes()).hexdigest()
                           for name in ('stencil.c', 'stencil.rs')}, cases=[])
    with tempfile.TemporaryDirectory(prefix='beryl-compare-') as tmp:
        suffix = '.exe' if os.name == 'nt' else ''
        c, rust = Path(tmp) / ('c' + suffix), Path(tmp) / ('rust' + suffix)
        for command in ([args.cc, '-O3', '-std=c11', str(ROOT / 'tools/benchmarks/stencil.c'), '-o', str(c)],
                        [args.rustc, *rust_flags, str(ROOT / 'tools/benchmarks/stencil.rs'), '-o', str(rust)]):
            subprocess.run(command, check=True, capture_output=True, timeout=120)
        env = os.environ.copy()
        env['PYTHONPATH'] = str(ROOT / 'axiom/src')
        commands = {'beryl': [sys.executable, '-m', 'axiom.playground_service'], 'C': [str(c)], 'Rust': [str(rust)]}
        for h, w in ((1, 1), (5, 7), (15, 15)):
            for mode in ('ramp', 'checkerboard'):
                data = list(range((h+1)*(w+1))) if mode == 'ramp' else [1023*((r+c)%2) for r in range(h+1) for c in range(w+1)]
                source = bench.get_examples()['examples'][0]['source'].replace('H = 5;', f'H = {h};').replace('W = 7;', f'W = {w};')
                source = source.replace('<= 64;', '<= 0;')
                payloads = {'beryl': json.dumps(dict(source=source, input_mode='custom', inputs=data))}
                payloads['C'] = payloads['Rust'] = ' '.join(map(str, [h, w] + data))
                times = {name: [] for name in commands}
                # Rotate order to reduce a consistent first/last-run bias.
                for sample in range(args.samples + 1):
                    names = list(commands)
                    names = names[sample % 3:] + names[:sample % 3]
                    for name in names:
                        start = perf_counter()
                        result = subprocess.run(commands[name], input=payloads[name], text=True,
                                                capture_output=True, check=True, timeout=30, env=env)
                        elapsed = perf_counter() - start
                        parsed = json.loads(result.stdout)
                        if name == 'beryl':
                            if parsed['status'] != 'success' or not parsed['comparison']['matches']:
                                raise ValueError('beryl did not return a checked success')
                            parsed = parsed['output']
                        bench.audit_output(parsed, data, h, w)
                        if sample:
                            times[name].append(elapsed)
                report['cases'].append(dict(height=h, width=w, input_mode=mode, correctness='passed',
                    measurements={name: dict(seconds=values, median_ms=statistics.median(values)*1000)
                                  for name, values in times.items()}))
                print(f'{h}x{w} {mode}: all three outputs verified', flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    main()
