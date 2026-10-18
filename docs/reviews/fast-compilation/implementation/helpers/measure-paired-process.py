#!/usr/bin/env python3
"""Serial whole-process latency guard for reviewed public-ZIP C artifacts.

Example:
  python measure-paired-process.py --artifacts kernel-artifacts --cc /path/to/clang \
      --samples 21 --output NEW.json

Build six executables once before all timed subprocesses. Measure three shapes
times two patterns with one separately retained, excluded warmup pair per case.
No output parsing, formula calculation, or validation enters a measured interval.
Any threshold miss is reported without retries or selective sample removal.
Exit 0: all six guards pass; 2: complete measurement with threshold miss;
1: setup, build, subprocess, or audit failure (partial evidence retained).
"""
import argparse
import base64
from datetime import datetime, timezone
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
from time import perf_counter_ns

FLAGS = ['-O3', '-std=c11']
SHAPES = ((1, 1), (5, 7), (15, 15))
PATTERNS = ('ramp', 'checkerboard')
THRESHOLD = 1.10
TIMEOUT_SECONDS = 30


def digest(data):
    return sha256(data).hexdigest()


def identity(path):
    data = path.read_bytes()
    return dict(path=str(path), bytes=len(data), sha256=digest(data))


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def b64(data):
    return base64.b64encode(data).decode('ascii')


def p95(values):
    return sorted(values)[math.ceil(len(values) * 0.95) - 1]


def reference(data, height, width):
    stride = width + 1
    return [sum((data[index] + 1) ** 2 for index in
                (row * stride + col, row * stride + col + 1,
                 (row + 1) * stride + col, (row + 1) * stride + col + 1))
            for row in range(height) for col in range(width)]


def make_input(height, width, pattern, seed):
    # Seeds 0..21 are all distinct in both families. Both programs receive
    # exactly the same bytes for a pair, including dimensions and final newline.
    if pattern == 'ramp':
        data = [(index + 37 * seed) % 1024
                for index in range((height + 1) * (width + 1))]
    else:
        low = (17 * seed) % 512
        high = 512 + (29 * seed) % 512
        data = [high if (row + col) % 2 else low
                for row in range(height + 1) for col in range(width + 1)]
    assert all(type(value) is int and 0 <= value <= 1023 for value in data)
    stdin = (' '.join(map(str, [height, width, *data])) + '\n').encode('ascii')
    return data, stdin


def run_pair(case, phase, seed, order, executables, journal):
    height, width, pattern = case['height'], case['width'], case['pattern']
    data, stdin = make_input(height, width, pattern, seed)
    pair = dict(phase=phase, seed=seed, order=order,
                input=data, stdin_utf8=stdin.decode('ascii'),
                stdin_sha256=digest(stdin), runs={})
    journal.append(pair)
    outputs = {}
    for variant in order:
        argv = [str(executables[variant])]
        # The only timed operations are this fresh subprocess and its pipes.
        # No check=True exception, decoding, JSON work, reference, or audit is timed.
        start_ns = perf_counter_ns()
        process = subprocess.run(argv, input=stdin, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, check=False,
                                 timeout=TIMEOUT_SECONDS)
        elapsed_ns = perf_counter_ns() - start_ns
        run = dict(command=argv, elapsed_ns=elapsed_ns,
                   returncode=process.returncode,
                   stdout_base64=b64(process.stdout), stderr_base64=b64(process.stderr),
                   stdout_bytes=len(process.stdout), stderr_bytes=len(process.stderr),
                   audit_ok=False)
        pair['runs'][variant] = run
        # All audit work follows the timer. Store raw bytes before any audit can
        # fail, so malformed output and nonzero return codes remain reviewable.
        if process.returncode != 0:
            raise ValueError(f"{case['id']} {phase} seed {seed}: {variant} returned {process.returncode}")
        output = json.loads(process.stdout)
        run['parsed_output'] = output
        if type(output) is not list or any(type(value) is not int for value in output):
            raise ValueError(f"{case['id']} {phase} seed {seed}: {variant} malformed output")
        expected = reference(data, height, width)
        pair['expected_output'] = expected
        if output != expected:
            raise ValueError(f"{case['id']} {phase} seed {seed}: {variant} formula mismatch")
        run['audit_ok'] = True
        outputs[variant] = output
    if outputs['old'] != outputs['new']:
        raise ValueError(f"{case['id']} {phase} seed {seed}: paired full outputs differ")
    pair['paired_full_outputs_equal'] = True
    pair['candidate_baseline_ratio'] = (
        pair['runs']['new']['elapsed_ns'] / pair['runs']['old']['elapsed_ns'])
    return pair


def load_artifacts(root, result):
    manifest_path = root / 'manifest.json'
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest['schema'] != 'beryl-public-zip-native-kernel-pairs-v1':
        raise ValueError('unsupported artifact manifest')
    result['source_provenance'] = dict(
        manifest=dict(path=str(manifest_path), sha256=digest(manifest_bytes), content=manifest),
        cases={})
    sources = {}
    indexed = {case['case_id']: case for case in manifest['cases']}
    for height, width in SHAPES:
        case_id = f'{height}x{width}-cap0'
        case = indexed[case_id]
        directory = root / case_id
        source_bytes = (directory / 'source.bryl').read_bytes()
        if digest(source_bytes) != case['source_sha256']:
            raise ValueError(f'{case_id}: fixture source hash mismatch')
        source_record = dict(source=identity(directory / 'source.bryl'), variants={})
        result['source_provenance']['cases'][case_id] = source_record
        for variant in ('old', 'new'):
            c_path = directory / (variant + '.c')
            c_bytes = c_path.read_bytes()
            plan_path = directory / (variant + '.plan')
            plan_bytes = plan_path.read_bytes()
            provenance_path = directory / (variant + '.provenance.json')
            provenance_bytes = provenance_path.read_bytes()
            provenance = json.loads(provenance_bytes)
            if not (digest(c_bytes) == case[variant]['c_sha256']
                    == provenance['artifact']['c_sha256']):
                raise ValueError(f'{case_id} {variant}: C hash mismatch')
            if not (digest(plan_bytes) == case['selected_plan_sha256']
                    == provenance['selected']['plan_sha256']):
                raise ValueError(f'{case_id} {variant}: plan hash mismatch')
            if provenance['fixture']['source_sha256'] != digest(source_bytes):
                raise ValueError(f'{case_id} {variant}: source provenance mismatch')
            source_record['variants'][variant] = dict(
                c_source=identity(c_path), plan=identity(plan_path),
                provenance=dict(path=str(provenance_path), sha256=digest(provenance_bytes),
                                content=provenance))
            sources[(height, width, variant)] = c_bytes
    return sources


def measure(args, result):
    artifacts = args.artifacts.resolve()
    sources = load_artifacts(artifacts, result)
    cc_found = shutil.which(args.cc)
    if cc_found is None:
        raise ValueError('Clang executable not found')
    # Preserve the invoked symlink name; multicall compiler drivers depend on it.
    cc = Path(cc_found).absolute()
    version_process = subprocess.run([str(cc), '--version'], capture_output=True,
                                     check=True, timeout=TIMEOUT_SECONDS)
    version = version_process.stdout.decode('utf-8')
    if 'clang' not in version.lower():
        raise ValueError('--cc must identify Clang')
    compiler_identity = identity(cc)
    compiler_identity.update(resolved_path=str(cc.resolve()), version=version)
    result['compiler'] = compiler_identity
    build_root = Path(tempfile.mkdtemp(prefix=args.output.stem + '-binaries-',
                                       dir=str(args.output.parent.resolve())))
    result['retained_build_directory'] = str(build_root)
    result['programs'] = {}
    executables = {}
    # Finish every build before even the first warmup/timed process.
    for height, width in SHAPES:
        shape_id = f'{height}x{width}-cap0'
        result['programs'][shape_id] = {}
        for variant in ('old', 'new'):
            source = build_root / f'{shape_id}-{variant}.c'
            binary = build_root / f'{shape_id}-{variant}'
            source.write_bytes(sources[(height, width, variant)])
            command = [str(cc), *FLAGS, str(source), '-o', str(binary)]
            process = subprocess.run(command, capture_output=True, check=False, timeout=180)
            record = dict(command=command, source=identity(source),
                          returncode=process.returncode,
                          stdout_base64=b64(process.stdout), stderr_base64=b64(process.stderr))
            result['programs'][shape_id][variant] = record
            if process.returncode != 0:
                raise ValueError(f'{shape_id} {variant}: Clang build failed')
            record['binary'] = identity(binary)
            executables[(height, width, variant)] = binary
    result['all_six_binaries_built_before_timings'] = True
    result['timings_started_utc'] = utc_now()
    result['cases'] = []
    for height, width in SHAPES:
        for pattern in PATTERNS:
            case_index = len(result['cases'])
            case = dict(id=f'{height}x{width}-cap0-{pattern}', height=height,
                        width=width, cap=0, pattern=pattern, warmup_pairs=[], samples=[])
            result['cases'].append(case)
            pair_executables = {variant: executables[(height, width, variant)]
                                for variant in ('old', 'new')}
            warmup_order = ['old', 'new'] if case_index % 2 == 0 else ['new', 'old']
            run_pair(case, 'excluded_warmup', 0, warmup_order,
                     pair_executables, case['warmup_pairs'])
            for index in range(args.samples):
                order = (['old', 'new'] if (index + case_index) % 2 == 0
                         else ['new', 'old'])
                run_pair(case, 'measured', index + 1, order,
                         pair_executables, case['samples'])
            if len({pair['stdin_sha256'] for pair in
                    case['warmup_pairs'] + case['samples']}) != args.samples + 1:
                raise ValueError(f"{case['id']}: repeated input bytes")
            summary = {}
            for variant in ('old', 'new'):
                values = [pair['runs'][variant]['elapsed_ns'] for pair in case['samples']]
                summary[variant] = dict(sample_count=len(values), median_ns=statistics.median(values),
                                        p95_ns=p95(values), minimum_ns=min(values), maximum_ns=max(values))
            ratios = [pair['candidate_baseline_ratio'] for pair in case['samples']]
            median_ratio = summary['new']['median_ns'] / summary['old']['median_ns']
            p95_ratio = summary['new']['p95_ns'] / summary['old']['p95_ns']
            case['summary'] = dict(programs=summary, median_ratio=median_ratio, p95_ratio=p95_ratio,
                                   median_paired_ratio=statistics.median(ratios),
                                   p95_paired_ratio=p95(ratios),
                                   threshold=THRESHOLD, passes_median_threshold=median_ratio <= THRESHOLD)
    result['timings_finished_utc'] = utc_now()
    result['all_audits_passed'] = True
    result['threshold_misses'] = [case['id'] for case in result['cases']
                                  if not case['summary']['passes_median_threshold']]
    result['all_six_median_guards_pass'] = not result['threshold_misses']
    result['complete'] = True
    return 0 if result['all_six_median_guards_pass'] else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--cc', required=True)
    parser.add_argument('--samples', type=int, choices=[21], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    helper = Path(__file__).resolve()
    result = dict(
        schema='beryl-whole-process-latency-guard-v1', complete=False, started_utc=utc_now(),
        harness=identity(helper), invocation=sys.argv,
        python=dict(executable=sys.executable, version=platform.python_version()),
        host=dict(platform=platform.platform(), machine=platform.machine(), cpu_count=os.cpu_count(),
                  load_average_start=list(os.getloadavg()) if hasattr(os, 'getloadavg') else None),
        config=dict(flags=FLAGS, samples_per_case=args.samples, patterns=PATTERNS, shapes=SHAPES,
                    threshold=THRESHOLD, timeout_seconds=TIMEOUT_SECONDS,
                    concurrency=1, builds_per_program=1,
                    warmup_policy='one fresh process per program per case; seed 0 retained separately and excluded from summaries',
                    input_policy='seeds 1..21 measured; changing bounded paired-equal stdin; shape dimensions precede all cells',
                    ordering_policy='alternate old/new by sample index, with initial order alternating by case index',
                    timed_scope='perf_counter_ns immediately around subprocess.run; fresh process startup, stdin/stdout/stderr pipe handling, subprocess management and wait',
                    excluded_scope='C compilation, JSON parsing, input/reference creation, return-code checks, every output/formula audit and pair equality checks',
                    ratio_definition='candidate/new divided by baseline/old; median_ratio is ratio of medians; p95_ratio is ratio of nearest-rank p95s',
                    p95_definition='nearest-rank sorted[ceil(n*0.95)-1]',
                    discarded_measured_samples=0, retries=0),
        limitations=[
            'Process scheduling, OS caches, CPU frequency and concurrent host activity are uncontrolled.',
            'Fresh processes may reuse operating-system executable and filesystem caches.',
            'For small programs startup and pipe overhead can dominate the kernel time.',
            'One excluded warmup pair and 21 measured pairs provide a latency guard, not statistical proof of equivalence.',
            'Threshold misses are retained as observed; this harness does not label or discard noisy samples.',
        ])
    # Reserve a new result file before any build or measurement. Never overwrite.
    try:
        stream = args.output.open('x', encoding='utf-8')
    except OSError as error:
        parser.exit(1, f'cannot exclusively create output: {error}\n')
    status = 1
    try:
        status = measure(args, result)
    except Exception as error:
        result['error'] = dict(type=type(error).__name__, message=str(error))
        if isinstance(error, subprocess.TimeoutExpired):
            result['error'].update(command=error.cmd, timeout_seconds=error.timeout,
                                   stdout_base64=b64(error.stdout or b''),
                                   stderr_base64=b64(error.stderr or b''))
        elif isinstance(error, subprocess.CalledProcessError):
            result['error'].update(command=error.cmd, returncode=error.returncode,
                                   stdout_base64=b64(error.stdout or b''),
                                   stderr_base64=b64(error.stderr or b''))
    finally:
        result['finished_utc'] = utc_now()
        result['host']['load_average_end'] = list(os.getloadavg()) if hasattr(os, 'getloadavg') else None
        result['exit_status'] = status
        with stream:
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write('\n')
    print(args.output.resolve())
    if result.get('error'):
        print(f"measurement failed; partial evidence retained: {result['error']['message']}", file=sys.stderr)
    elif result.get('threshold_misses'):
        print('median guard misses retained: ' + ', '.join(result['threshold_misses']), file=sys.stderr)
    return status


if __name__ == '__main__':
    raise SystemExit(main())
