"""Qualification of direct C/Rust build costs; executions/audits are untimed."""
import argparse
import hashlib
import json
import math
import platform
import statistics
import subprocess
import tempfile
import time
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', type=Path, required=True)
    ap.add_argument('--cc', required=True)
    ap.add_argument('--rustc', required=True)
    ap.add_argument('--samples', type=int, default=21)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    assert args.samples >= 21 and not args.output.exists()
    tools = {'C': (args.cc, ['-O3', '-std=c11'], 'stencil.c'),
             'Rust': (args.rustc, ['-O'], 'stencil.rs')}
    report = dict(scope='Fresh compiler process source-to-executable build wall time; warm filesystem/compiler infrastructure, no incremental user-program cache. Executable runs and independent audits excluded.',
        host=platform.platform(), samples=args.samples, order=[], programs={})
    with tempfile.TemporaryDirectory(prefix='beryl-direct-builds-') as scratch:
        temporary = Path(scratch)
        for name, (exe, flags, filename) in tools.items():
            source = args.repo / 'tools/benchmarks' / filename
            report['programs'][name] = dict(source_sha256=digest(source), compiler_path=exe,
                compiler_sha256=digest(exe), version=subprocess.check_output([exe, '--version'], text=True).strip(),
                flags=flags, raw_ms=[], binaries=[])
        for sample in range(args.samples):
            for name in (['C', 'Rust'] if sample % 2 == 0 else ['Rust', 'C']):
                exe, flags, filename = tools[name]
                source = args.repo / 'tools/benchmarks' / filename
                binary = temporary / f'{name}-{sample}'
                start = time.perf_counter_ns()
                subprocess.run([exe, *flags, str(source), '-o', str(binary)], capture_output=True, check=True)
                elapsed = (time.perf_counter_ns()-start)/1e6
                record = report['programs'][name]
                record['raw_ms'].append(elapsed)
                record['binaries'].append(digest(binary))
                report['order'].append(dict(sample=sample, program=name))
                for mode in ('ramp', 'checkerboard'):
                    values = [(i+sample*37)%1024 if mode=='ramp' else (1023*((i//16+i%16)%2)+sample*7)%1024 for i in range(256)]
                    output = json.loads(subprocess.check_output([str(binary)], input=('15 15\n'+' '.join(map(str, values))+'\n').encode()))
                    expected = [sum((values[j]+1)**2 for j in (r*16+c,r*16+c+1,r*16+c+16,r*16+c+17)) for r in range(15) for c in range(15)]
                    assert output == expected, (name,sample,mode)
        for record in report['programs'].values():
            record['median_ms'] = statistics.median(record['raw_ms'])
            record['p95_ms'] = sorted(record['raw_ms'])[math.ceil(args.samples*.95)-1]
    report['every_build_independently_audited'] = True
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print({name:record['median_ms'] for name,record in report['programs'].items()})


if __name__ == '__main__':
    main()
