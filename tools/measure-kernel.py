#!/usr/bin/env python3
"""Serial native callable-kernel comparison; execution and audits live in C.

Example: python tools/measure-kernel.py --baseline old.c --candidate new.c
 --clang /path/to/clang --height 15 --width 15 --iterations 1000000
 --samples 21 --output /tmp/kernel-comparison.json

Only supports the bounded 0..1023 direct stencil and its beryl_kernel ABI.
Each source is snapshotted byte-for-byte, built in its own translation unit
with main renamed, and linked to the separately compiled shared driver.
"""
import argparse
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
from time import perf_counter


FLAGS = ['-O3', '-std=c11', '-fno-lto']
DRIVER = Path(__file__).resolve().parent / 'benchmarks' / 'kernel-throughput.c'


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def command(argv):
    return subprocess.run([str(arg) for arg in argv], check=True,
                          text=True, capture_output=True)


def p95(values):
    return sorted(values)[math.ceil(len(values) * .95) - 1]


def cpu_model():
    try:
        for line in Path('/proc/cpuinfo').read_text().splitlines():
            if line.startswith('model name'):
                return line.split(':', 1)[1].strip()
    except OSError:
        pass
    return platform.processor()


def measure(args):
    # Keep a compiler symlink's invoked name (multicall drivers depend on it).
    compiler_path = shutil.which(args.clang)
    if compiler_path is None:
        raise ValueError('Clang must be an available executable')
    clang = str(Path(compiler_path).absolute())
    version = command([clang, '--version']).stdout.strip()
    if 'clang' not in version.lower():
        raise ValueError('--clang must be Clang')
    source_bytes = {name: path.read_bytes() for name, path in
                    [('baseline', args.baseline), ('candidate', args.candidate)]}
    driver_bytes = DRIVER.read_bytes()
    result = dict(
        schema='beryl-kernel-throughput-v1', height=args.height, width=args.width,
        iterations=args.iterations, sample_count=args.samples, flags=FLAGS,
        timed_scope='one input-cell mutation + external kernel call + status and one rotating output capture per iteration; loop/index bookkeeping and two monotonic clock reads',
        untimed_scope='process startup, allocation/initialization, checksum, independent direct-formula reference and full-output/input-preservation replay',
        audit_scope='every timed status and rotating output cell; every output and unchanged input on identical untimed replay; complete final timed input/output state',
        warmup_policy='one separately timed/audited first call in each process; reset buffers before measured loop; executables built before all samples; OS/compiler caches uncontrolled',
        ratio_definition='candidate/baseline; >1 means candidate slower',
        driver_sha256=sha256(driver_bytes).hexdigest(),
        toolchain=dict(path=clang, resolved_path=str(Path(clang).resolve()),
                       binary_sha256=digest(clang), version=version),
        host=dict(platform=platform.platform(), machine=platform.machine(),
                  processor=cpu_model(), cpu_count=os.cpu_count(),
                  python_version=platform.python_version(),
                  load_average=list(os.getloadavg()) if hasattr(os, 'getloadavg') else None),
        programs={}, sample_order=[], paired_ratios=[])
    with tempfile.TemporaryDirectory(prefix='beryl-kernel-measure-') as directory:
        root = Path(directory)
        driver = root / 'kernel-throughput.c'
        driver.write_bytes(driver_bytes)
        driver_object = root / 'driver.o'
        driver_command = [clang, *FLAGS, '-c', str(driver), '-o', str(driver_object)]
        start = perf_counter()
        command(driver_command)
        result['driver_build_seconds'] = perf_counter() - start
        result['driver_build_command'] = driver_command
        executables = {}
        for name, data in source_bytes.items():
            source = root / (name + '.c')
            source.write_bytes(data)
            # clang appends .exe on Windows whatever -o says.
            obj, executable = root / (name + '.o'), root / (name + ('.exe' if os.name == 'nt' else ''))
            compile_command = [clang, *FLAGS, '-Dmain=beryl_generated_main',
                               '-c', str(source), '-o', str(obj)]
            link_command = [clang, '-fno-lto', str(obj), str(driver_object), '-o', str(executable)]
            start = perf_counter()
            command(compile_command)
            compile_seconds = perf_counter() - start
            start = perf_counter()
            command(link_command)
            link_seconds = perf_counter() - start
            executables[name] = executable
            original = args.baseline if name == 'baseline' else args.candidate
            result['programs'][name] = dict(
                source_path=str(original.absolute()), source_sha256=sha256(data).hexdigest(),
                source_bytes=len(data), executable_sha256=digest(executable),
                object_sha256=digest(obj), build_seconds=compile_seconds + link_seconds,
                compile_seconds=compile_seconds, link_seconds=link_seconds,
                compile_command=compile_command, link_command=link_command,
                samples=[], ns_per_run=[])
        for index in range(args.samples):
            order = ['baseline', 'candidate'] if index % 2 == 0 else ['candidate', 'baseline']
            result['sample_order'].append(order)
            for name in order:
                process = command([executables[name], args.height, args.width,
                                   args.iterations, index + 1])
                sample = json.loads(process.stdout)
                if sample.get('audit_ok') is not True:
                    raise ValueError('kernel audit did not succeed')
                result['programs'][name]['samples'].append(sample)
                result['programs'][name]['ns_per_run'].append(sample['ns_per_run'])
            left = result['programs']['baseline']['samples'][-1]
            right = result['programs']['candidate']['samples'][-1]
            for field in ('seed', 'checksum', 'final_output'):
                if left[field] != right[field]:
                    raise ValueError(f'paired kernel audit mismatch: {field}')
            result['paired_ratios'].append(right['ns_per_run'] / left['ns_per_run'])
    for program in result['programs'].values():
        values = program['ns_per_run']
        program['median_ns_per_run'] = statistics.median(values)
        program['p95_ns_per_run'] = p95(values)
        program['min_ns_per_run'] = min(values)
        program['max_ns_per_run'] = max(values)
        program['stdev_ns_per_run'] = statistics.stdev(values) if len(values) > 1 else 0
    result['median_ratio'] = (result['programs']['candidate']['median_ns_per_run'] /
                              result['programs']['baseline']['median_ns_per_run'])
    result['p95_paired_ratio'] = p95(result['paired_ratios'])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--clang', required=True)
    parser.add_argument('--height', type=int, required=True)
    parser.add_argument('--width', type=int, required=True)
    parser.add_argument('--iterations', type=int, required=True)
    parser.add_argument('--samples', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if (not 1 <= args.height <= 255 or not 1 <= args.width <= 255 or
            (args.height + 1) * (args.width + 1) > 256):
        parser.error('height/width must be positive with at most 256 input cells')
    if not 1 <= args.iterations <= min(sys.maxsize // 4, (1 << 64) - 1):
        parser.error('iterations must be positive and fit capture storage')
    if not 1 <= args.samples <= (1 << 64) - 1:
        parser.error('samples must be positive and fit uint64 seeds')
    if os.path.lexists(args.output):
        parser.error('output already exists; choose a new output JSON path')
    try:
        result = measure(args)
        # Exclusive creation also protects against a path appearing mid-run.
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2)
            stream.write('\n')
    except subprocess.CalledProcessError as error:
        parser.exit(1, f'kernel build/audit failed: {error.stderr}\n')
    except (OSError, ValueError, ZeroDivisionError) as error:
        parser.exit(1, f'kernel measurement failed: {error}\n')
    print(args.output)


if __name__ == '__main__':
    main()
