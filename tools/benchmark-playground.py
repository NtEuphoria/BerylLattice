#!/usr/bin/env python3
"""Correctness-audited local benchmarks; no third-party dependencies."""
import argparse
from datetime import datetime, timezone
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
sys.path.insert(0, str(ROOT / 'axiom' / 'src'))
from axiom.playground_service import get_examples, run_demo


def audit_output(output, inputs, height, width):
    expected = []
    for row in range(height):
        for column in range(width):
            index = row * (width + 1) + column
            expected.append(sum((inputs[i] + 1) ** 2 for i in
                                (index, index + 1, index + width + 1, index + width + 2)))
    if output != expected:
        raise ValueError('Benchmark output disagrees with the direct stencil calculation')


def measure_case(height, width, mode, cap, repeats):
    source = get_examples()['examples'][0]['source']
    source = source.replace('H = 5;', f'H = {height};').replace('W = 7;', f'W = {width};')
    source = source.replace('<= 64;', f'<= {cap};')
    request = {'source': source, 'input_mode': mode}
    expected_input = (list(range((height + 1) * (width + 1))) if mode == 'ramp' else
                      [1023 * ((row + column) % 2)
                       for row in range(height + 1) for column in range(width + 1)])
    samples = []
    for iteration in range(repeats + 1):
        start = perf_counter()
        result = run_demo(request)
        elapsed = perf_counter() - start
        if result['status'] != 'success' or result['comparison']['matches'] is not True:
            raise ValueError(f'Benchmark run failed: {result}')
        if result['input'] != expected_input:
            raise ValueError('Benchmark input pattern is incorrect')
        audit_output(result['output'], expected_input, height, width)
        if iteration:  # One untimed warm-up; all runs still audited.
            samples.append(elapsed)
    median = statistics.median(samples)
    return dict(height=height, width=width, input_mode=mode, scratch_cap=cap,
                plan=result['selected']['plan_id'], output_cells=height * width,
                output_sum=sum(result['output']), seconds=samples,
                median_seconds=median, min_seconds=min(samples), max_seconds=max(samples),
                output_cells_per_second=height * width / median, correctness='passed')


def write_numbers(path, count):
    # Bounded chunks avoid a 20-million-element list or terminal flood.
    with path.open('wb') as stream:
        for start in range(0, count, 10000):
            stream.write(''.join(f'{i}\n' for i in range(start, min(start + 10000, count))).encode('ascii'))
        stream.flush()
        os.fsync(stream.fileno())


def measure_io(count):
    with tempfile.TemporaryDirectory(prefix='beryl-benchmark-') as directory:
        path = Path(directory) / 'numbers.txt'
        start = perf_counter()
        write_numbers(path, count)
        elapsed = perf_counter() - start
        size = path.stat().st_size
        start = perf_counter()
        seen = 0
        with path.open('rb') as stream:
            for index, line in enumerate(stream):
                if line != f'{index}\n'.encode('ascii'):
                    raise ValueError(f'Incorrect number at line {index}')
                seen += 1
        if seen != count:
            raise ValueError(f'Expected {count} numbers, found {seen}')
        return dict(kind='Python file-output baseline, NOT beryl execution', numbers=count,
                    bytes=size, write_and_fsync_seconds=elapsed, numbers_per_second=count / elapsed,
                    verification_seconds=perf_counter() - start, correctness='passed',
                    temporary_file_deleted=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats', type=int, default=3, help='timed samples per case (1..100)')
    parser.add_argument('--io-numbers', type=int, default=0, help='optional Python file-output baseline (up to 20,000,000)')
    parser.add_argument('--output', type=Path, required=True, help='new JSON report path (will not overwrite)')
    args = parser.parse_args()
    if not 1 <= args.repeats <= 100 or not 0 <= args.io_numbers <= 20000000:
        parser.error('repeats must be 1..100 and io-numbers must be 0..20000000')
    if args.output.exists():
        parser.error('output already exists; choose a new report path')
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True)
    dirty = subprocess.run(['git', 'status', '--porcelain'], cwd=ROOT, capture_output=True, text=True)
    report = dict(schema_version=1, created_utc=datetime.now(timezone.utc).isoformat(),
                  python=sys.version, platform=platform.platform(), machine=platform.machine(),
                  revision=revision.stdout.strip() if revision.returncode == 0 else None,
                  working_tree_dirty=bool(dirty.stdout) if dirty.returncode == 0 else None,
                  scope='Warm in-process parse, plan selection, fresh checking, interpreter execution and reference comparison. No HTTP, browser, startup or terminal rendering.',
                  cases=[])
    for height, width in ((1, 1), (5, 7), (15, 15)):
        for mode in ('ramp', 'checkerboard'):
            for cap in (0, 128):
                result = measure_case(height, width, mode, cap, args.repeats)
                report['cases'].append(result)
                print(f'{height}x{width} {mode} cap={cap}: {result["median_seconds"] * 1000:.2f} ms, verified', flush=True)
    if args.io_numbers:
        print(f'Writing and verifying {args.io_numbers:,} numbers (Python I/O baseline)...', flush=True)
        report['io_baseline'] = measure_io(args.io_numbers)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(f'Report: {args.output}')


if __name__ == '__main__':
    main()
