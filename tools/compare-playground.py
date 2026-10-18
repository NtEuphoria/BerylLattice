#!/usr/bin/env python3
"""Audit precompiled native process latency, with compilation reported separately."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
from time import perf_counter
from types import SimpleNamespace
import zipfile

ROOT = Path(__file__).resolve().parents[1]
_COMPILER = None

SHAPES = ((1, 1), (5, 7), (15, 15))
MODES = ('ramp', 'checkerboard')
C_FLAGS = ['-O3', '-std=c11']
NATIVE_SCOPE = ('Fresh native process wall time: process startup, identical text input transfer '
                'and decoding, input preflight, calculation, JSON output and stdout transfer. '
                'All executables are compiled before any timed run. Source admission, checked '
                'plan selection, fresh checking/code emission, native compilation and external '
                'output audits are outside the samples and reported separately. beryl is '
                'specialized to each shape; the direct C/Rust formulas accept bounded shapes. '
                'This is process latency, not a kernel-only or language speed ranking.')
PYTHON_SCOPE = ('Optional full Python service request: fresh Python startup, JSON input decoding, '
                'source parsing, checked plan selection, fresh checking, interpreted execution, '
                'independent source evaluation and rich JSON output transfer. This different '
                'scope is excluded from the primary native measurements.')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    return digest(Path(path).read_bytes())


def load_compiler(archive=None):
    """Load either the private checkout or exact reviewed public archive bytes."""
    if archive is None:
        sys.path.insert(0, str(ROOT / 'axiom/src'))
        namespace = 'axiom'
        identity = dict(kind='checkout', modules={str(path.relative_to(ROOT)): file_digest(path)
                        for path in sorted((ROOT / 'axiom/src/axiom').glob('*.py'))})
    else:
        archive = Path(archive).resolve()
        if any(name == 'beryl' or name.startswith('beryl.') for name in sys.modules):
            raise ValueError('public compiler modules were loaded before archive selection')
        with zipfile.ZipFile(archive) as package:
            modules = {name: digest(package.read(name)) for name in sorted(package.namelist())
                       if name.startswith('beryl/') and name.endswith('.py')}
        if not modules:
            raise ValueError('compiler archive has no beryl Python modules')
        sys.path.insert(0, str(archive))
        namespace = 'beryl'
        identity = dict(kind='reviewed-archive', archive_sha256=file_digest(archive), modules=modules)
    modules = {name: importlib.import_module(f'{namespace}.{name}')
               for name in ('frontend', 'model', 'selection', 'native_codegen', 'playground_service')}
    source_name = f'{namespace}.source_compilation'
    if importlib.util.find_spec(source_name) is not None:
        modules['source_compilation'] = importlib.import_module(source_name)
    if archive is not None and any(not str(module.__file__).startswith(str(archive) + os.sep)
                                   for module in modules.values()):
        raise ValueError('compiler modules did not originate in the selected archive')
    return SimpleNamespace(namespace=namespace, identity=identity, archive=archive,
                           parse_source=modules['frontend'].parse_source,
                           admit_source=modules['frontend'].admit_source,
                           Limits=modules['model'].Limits,
                           select_plan=modules['selection'].select_plan,
                           emit_native_c=modules['native_codegen'].emit_native_c,
                           get_examples=modules['playground_service'].get_examples,
                           compile_native_source=(modules['source_compilation'].compile_native_source
                               if 'source_compilation' in modules else None))


def compiler():
    global _COMPILER
    if _COMPILER is None:
        _COMPILER = load_compiler()
    return _COMPILER


def audit_output(output, inputs, height, width):
    """Independent formula, outside the admitted source/plan/compiler pipeline."""
    expected = []
    for row in range(height):
        for column in range(width):
            index = row * (width + 1) + column
            expected.append(sum((inputs[cell] + 1) ** 2 for cell in
                                (index, index + 1, index + width + 1, index + width + 2)))
    if type(output) is not list or any(type(value) is not int for value in output) or output != expected:
        raise ValueError('Benchmark output disagrees with the direct stencil calculation')


def source_for_shape(height, width):
    if (height, width) not in SHAPES:
        raise ValueError('unsupported benchmark shape')
    source = compiler().get_examples()['examples'][0]['source']
    return (source.replace('H = 5;', f'H = {height};')
            .replace('W = 7;', f'W = {width};').replace('<= 64;', '<= 0;'))


def case_inputs(height, width, mode, iteration):
    """Vary runtime data without changing the compiled source or plan."""
    if (height, width) not in SHAPES or mode not in MODES or not 0 <= iteration <= 30:
        raise ValueError('unsupported benchmark inputs')
    if mode == 'ramp':
        return [(index + 37 * iteration) % 1024
                for index in range((height + 1) * (width + 1))]
    low, high = 31 * iteration % 1024, (1023 - 29 * iteration) % 1024
    return [high if (row + column + iteration) % 2 else low
            for row in range(height + 1) for column in range(width + 1)]


def compile_program(command, output):
    start = perf_counter()
    subprocess.run(command, check=True, capture_output=True, timeout=180)
    elapsed = perf_counter() - start
    return {'seconds': elapsed, 'phase': 'native_compiler_link',
            'binary_sha256': file_digest(output), 'binary_bytes': Path(output).stat().st_size,
            'command': command}


def prepare_beryl(height, width, directory, cc):
    """Select/check immutable plan bytes and compile once, independently of inputs."""
    implementation = compiler()
    limits = implementation.Limits()
    source = source_for_shape(height, width).encode('utf-8')
    start = perf_counter()
    if implementation.compile_native_source is not None:
        compiled = implementation.compile_native_source(source, limits)
        source_seconds = perf_counter() - start
        selection, artifact = compiled.search, compiled.artifact
        selection_seconds = emission_seconds = None
        scope = ('fresh source transaction: admission, ranked proof, hint correspondence and compact '
                 'code emission; native compiler/link separate; excluded from process execution samples')
    else:
        kernel = implementation.admit_source(implementation.parse_source(source, limits))
        selection = implementation.select_plan(kernel, limits, 100000, kernel.objective)
        selection_seconds = perf_counter() - start
        artifact = None
        source_seconds = None
        scope = ('legacy public source admission/selection, fresh public byte backend and native '
                 'compiler/link; excluded from process execution samples')
    if (selection.selected_plan_bytes is None or selection.selected_check is None
            or not selection.selected_check.eligible):
        raise ValueError('benchmark source has no checked eligible plan')
    plan = selection.selected_plan_bytes
    if implementation.compile_native_source is None:
        start = perf_counter()
        artifact = implementation.emit_native_c(source, plan, limits)
        emission_seconds = perf_counter() - start
    if artifact is None:
        raise ValueError('benchmark source compiler produced no artifact')
    if (artifact.height, artifact.width, artifact.input_count, artifact.output_count) != (
            height, width, (height + 1) * (width + 1), height * width):
        raise ValueError('native artifact dimensions do not match the benchmark')
    if (artifact.source_digest != digest(source) or artifact.plan_digest != digest(plan)
            or artifact.c_digest != digest(artifact.c_source)):
        raise ValueError('native artifact digests do not identify its exact inputs and output')
    c_source = directory / f'beryl-{height}x{width}.c'
    binary = directory / (f'beryl-{height}x{width}' + ('.exe' if os.name == 'nt' else ''))
    c_source.write_bytes(artifact.c_source)
    compilation = compile_program([cc, *C_FLAGS, str(c_source), '-o', str(binary)], binary)
    record = dict(height=height, width=width, scratch_cap=0,
                  plan_id=selection.selected_plan.plan_id,
                  source_sha256=digest(source), plan_sha256=digest(plan),
                  generated_c_sha256=digest(artifact.c_source),
                  generated_c_bytes=len(artifact.c_source), plan_bytes=len(plan),
                  plan_operations=len(selection.selected_plan.operations), native_flags=list(C_FLAGS),
                  compilation_scope=scope,
                  source_compilation_seconds=source_seconds,
                  search_policy=getattr(selection, 'policy_id', 'legacy'),
                  codegen_version=getattr(artifact, 'codegen_version', None),
                  hint_digest=getattr(artifact, 'hint_digest', None),
                  source=source.decode('utf-8'), generated_c=artifact.c_source.decode('utf-8'),
                  selection_and_check_seconds=selection_seconds,
                  fresh_check_and_emit_seconds=emission_seconds,
                  native_compile=compilation,
                  total_seconds=(source_seconds if source_seconds is not None else
                                 selection_seconds + emission_seconds) + compilation['seconds'])
    return {'binary': binary, 'source': source.decode('utf-8'), 'record': record}


def measure_case(commands, source, height, width, mode, samples, env, python_command=None):
    """Only child-process execution is timed; preparation and audits happen outside."""
    times = {name: [] for name in commands}
    python_times = []
    iterations = []
    for iteration in range(samples + 1):
        data = case_inputs(height, width, mode, iteration)
        payload = ' '.join(map(str, [height, width, *data]))
        python_payload = json.dumps(dict(source=source, input_mode='custom', inputs=data),
                                    separators=(',', ':'), ensure_ascii=False)
        request = dict(iteration=iteration, measured=iteration > 0,
                       input_sha256=digest(json.dumps(data, separators=(',', ':')).encode('ascii')),
                       native_request_sha256=digest(payload.encode('ascii')))
        names = list(commands)
        offset = iteration % len(names)
        names = names[offset:] + names[:offset]
        request['native_order'] = names
        for name in names:
            start = perf_counter()
            result = subprocess.run(commands[name], input=payload, text=True, capture_output=True,
                                    check=True, timeout=30, env=env)
            elapsed = perf_counter() - start
            audit_output(json.loads(result.stdout), data, height, width)
            if iteration:
                times[name].append(elapsed)
        if python_command is not None:
            # Keep this distinct scope after the native runs; it never changes
            # the rotating order or the contents of the primary measurements.
            request['python_request_sha256'] = digest(python_payload.encode('utf-8'))
            start = perf_counter()
            result = subprocess.run(python_command, input=python_payload, text=True,
                                    capture_output=True, check=True, timeout=30, env=env)
            elapsed = perf_counter() - start
            parsed = json.loads(result.stdout)
            if (parsed.get('status') != 'success'
                    or parsed.get('comparison', {}).get('matches') is not True
                    or parsed.get('input') != data):
                raise ValueError('Python service did not return an audited success for these inputs')
            audit_output(parsed['output'], data, height, width)
            if iteration:
                python_times.append(elapsed)
        iterations.append(request)
    result = dict(height=height, width=width, input_mode=mode, scratch_cap=0,
                  correctness='passed', preparation_key=f'{height}x{width}',
                  measurements={name: dict(seconds=values, median_ms=statistics.median(values) * 1000)
                                for name, values in times.items()}, requests=iterations)
    if all(name in times for name in ('beryl', 'C', 'Rust')):
        ratios = {name: statistics.median(times['beryl']) / statistics.median(times[name])
                  for name in ('C', 'Rust')}
        result['latency_target'] = dict(beryl_over_baseline=ratios,
                                        within_2x_each=all(value <= 2 for value in ratios.values()))
    if python_command is not None:
        result['python_full_request'] = dict(seconds=python_times,
                                            median_ms=statistics.median(python_times) * 1000)
    return result


def run_cases(directory, cc, rustc, rust_flags, samples, include_python=False):
    """Complete all builds before warming up or sampling any native process."""
    suffix = '.exe' if os.name == 'nt' else ''
    binaries = {'C': directory / ('c' + suffix), 'Rust': directory / ('rust' + suffix)}
    compilation = {}
    for name, compiler_path, flags, filename in (
            ('C', cc, C_FLAGS, 'stencil.c'), ('Rust', rustc, rust_flags, 'stencil.rs')):
        compilation[name] = compile_program(
            [compiler_path, *flags, str(ROOT / 'tools/benchmarks' / filename), '-o', str(binaries[name])],
            binaries[name])
    prepared = {(height, width): prepare_beryl(height, width, directory, cc)
                for height, width in SHAPES}
    compilation['beryl'] = {f'{height}x{width}': item['record']
                            for (height, width), item in prepared.items()}
    env = os.environ.copy()
    env['PYTHONPATH'] = str(ROOT / 'axiom/src')
    python_command = None
    if include_python:
        implementation = compiler()
        if implementation.archive is None:
            python_command = [sys.executable, '-m', 'axiom.playground_service']
        else:
            python_command = [sys.executable, '-I', '-c',
                              'import sys; sys.path.insert(0, sys.argv[1]); '
                              'from beryl.playground_service import main; sys.exit(main())',
                              str(implementation.archive)]
    cases = []
    for (height, width), item in prepared.items():
        commands = {'beryl': [str(item['binary'])], **{name: [str(path)] for name, path in binaries.items()}}
        for mode in MODES:
            case = measure_case(commands, item['source'], height, width, mode, samples, env,
                                python_command)
            cases.append(case)
            print(f'{height}x{width} {mode}: all three native outputs verified', flush=True)
    return compilation, cases


def tool_info(executable):
    path = shutil.which(executable)
    if path is None:
        raise FileNotFoundError(f'Compiler not found: {executable}')
    result = subprocess.run([path, '--version'], capture_output=True, text=True, check=True, timeout=30)
    # Preserve the invoked basename: rustup and other multicall drivers select
    # their compiler mode from argv[0], even when the entry is a symlink.
    return dict(path=str(Path(path).absolute()), resolved_path=str(Path(path).resolve()),
                version=result.stdout.splitlines()[0],
                binary_sha256=file_digest(path))


def provenance():
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True)
    dirty = subprocess.run(['git', 'status', '--porcelain'], cwd=ROOT, capture_output=True, text=True)
    model = platform.processor()
    cpuinfo = Path('/proc/cpuinfo')
    if cpuinfo.exists():
        model = next((line.split(':', 1)[1].strip() for line in cpuinfo.read_text().splitlines()
                      if line.startswith('model name')), model)
    paths = [Path(__file__).resolve()]
    return dict(revision=revision.stdout.strip() if revision.returncode == 0 else None,
                working_tree_dirty=bool(dirty.stdout) if dirty.returncode == 0 else None,
                cpu=dict(model=model or 'unavailable', logical_count=os.cpu_count(),
                         affinity_count=len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None),
                python_executable=dict(path=sys.executable, binary_sha256=file_digest(sys.executable),
                                       version=sys.version),
                runners={path.name: file_digest(path) for path in paths},
                modules=compiler().identity['modules'])


def main():
    global _COMPILER
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default='clang')
    parser.add_argument('--rustc', default='rustc')
    parser.add_argument('--rust-self-contained', action='store_true', help='use bundled linker libraries for Windows GNU Rust')
    parser.add_argument('--include-python', action='store_true', help='also record the separate full Python service request scope')
    parser.add_argument('--compiler-archive', type=Path, help='load beryl compiler modules from this reviewed public ZIP instead of the checkout')
    parser.add_argument('--samples', type=int, default=5, help='measured runs per case (1..30), following one warm-up')
    parser.add_argument('--output', type=Path, required=True, help='new JSON report path (will not overwrite)')
    args = parser.parse_args()
    if not 1 <= args.samples <= 30 or args.output.exists():
        parser.error('samples must be 1..30 and output must be a new path')
    _COMPILER = load_compiler(args.compiler_archive)
    toolchains = {name: tool_info(executable) for name, executable in [('C', args.cc), ('Rust', args.rustc)]}
    rust_flags = ['-O'] + (['-C', 'link-self-contained=yes'] if args.rust_self_contained else [])
    report = dict(schema_version=2, created_utc=datetime.now(timezone.utc).isoformat(),
                  platform=platform.platform(), machine=platform.machine(), python=platform.python_version(),
                  compilers={name: info['version'] for name, info in toolchains.items()},
                  toolchains=toolchains, compiler_source=compiler().identity, scope=NATIVE_SCOPE,
                  methodology=dict(warmups=1, samples=args.samples, native_order='rotating',
                                   changing_inputs=True, input_interval=[0, 1023],
                                   audit='Every warm-up and measured output checked against an external direct formula after timing.',
                                   compilation='All beryl, C and Rust executables compiled before the first warm-up.',
                                   native_target='Observe whether beryl median process latency is within 2x of each baseline; this is a target, not a guarantee.'),
                  flags={'beryl': C_FLAGS, 'C': C_FLAGS, 'Rust': rust_flags}, samples=args.samples,
                  sources={name: file_digest(ROOT / 'tools/benchmarks' / name)
                           for name in ('stencil.c', 'stencil.rs')}, provenance=provenance())
    if args.include_python:
        report['optional_scopes'] = {'python_full_request': PYTHON_SCOPE}
    with tempfile.TemporaryDirectory(prefix='beryl-compare-') as temporary:
        report['compilation'], report['cases'] = run_cases(
            Path(temporary), toolchains['C']['path'], toolchains['Rust']['path'], rust_flags,
            args.samples, args.include_python)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(f'Report: {args.output}', flush=True)


if __name__ == '__main__':
    main()
