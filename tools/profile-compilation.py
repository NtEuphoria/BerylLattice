#!/usr/bin/env python3
"""Research-only fresh-source compilation measurements with isolated paired revisions."""
import argparse
import base64
import cProfile
from datetime import datetime, timezone
import hashlib
import importlib
import inspect
import json
from pathlib import Path
import platform
import pstats
import shutil
import statistics
import subprocess
import sys
import tempfile
from time import perf_counter_ns
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SHAPES = ((1, 1), (5, 7), (15, 15), (1, 127), (127, 1), (2, 4), (3, 2))
OBJECTIVES = ('multiplication_ops', 'plan_workspace_bytes')
SCOPE = ('Runtime/imports ready; fresh service source preparation including Wasm emission, '
         'excluding engine compile/instantiate, execution and verification. No program warmup. '
         'Diagnostic tracing/cProfile runs are separate from uninstrumented wall samples. '
         'Paired revisions execute in isolated Python processes, rotating revision order. '
         'Input-only reuse/execution is measured by the browser harness, not this preparation tool.')


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def build_fixtures(kind='qualification'):
    definitions = ([(1, 1, 64), (5, 7, 64), (15, 15, 64), (15, 15, 128)]
                   if kind == 'qualification' else [(1, 1, 64)] if kind == 'smoke' else
                   [(h, w, cap) for h, w in SHAPES
                    for cap in sorted({max(0, value + delta)
                                       for value in (0, 8 * (w + 1), 4 * (h + 1) * (w + 1))
                                       for delta in (-1, 0, 1)})])
    fixtures = [dict(id=f'{h}x{w}-cap{cap}-{objective}', height=h, width=w, cap=cap,
                     objective=objective, edit='base')
                for h, w, cap in definitions
                for objective in (OBJECTIVES if kind == 'boundary' else OBJECTIVES[:1])]
    if kind == 'boundary':
        for edit in ('comment', 'rename', 'cap', 'objective', 'input_only'):
            fixtures.append(dict(id=f'5x7-edit-{edit}', height=5, width=7,
                                 cap=65 if edit == 'cap' else 64,
                                 objective=OBJECTIVES[1] if edit == 'objective' else OBJECTIVES[0],
                                 edit=edit))
    return fixtures


def fixture_source(case):
    source = (f'''module demo;
shape H = {case['height']};
shape W = {case['width']};
input image: i32[H+1,W+1] in 0..=1023;
let p[r in 0..H+1,c in 0..W+1] =
  (image[r,c]+1)*(image[r,c]+1);
output result[r in 0..H,c in 0..W] =
  ((p[r,c]+p[r,c+1])+p[r+1,c])+p[r+1,c+1];
require plan_workspace_bytes <= {case['cap']};
prefer {case['objective']};
''')
    if case['edit'] == 'rename':
        source = source.replace('image', 'pixels').replace('result', 'answer')
    if case['edit'] == 'comment':
        source += '// source-only edit\n'
    return source


def reference_output(data, height, width):
    return [sum((data[index] + 1) ** 2 for index in (r * (width + 1) + c,
            r * (width + 1) + c + 1, (r + 1) * (width + 1) + c,
            (r + 1) * (width + 1) + c + 1))
            for r in range(height) for c in range(width)]


def audit_output(output, data, height, width):
    if (type(output) is not list or any(type(value) is not int for value in output)
            or output != reference_output(data, height, width)):
        raise ValueError('compiled output differs from independent stencil formula')


def wasm_local_count(module):
    """Read actual Wasm code-section local declarations, including compact backends."""
    if module[:8] != b'\x00asm\x01\x00\x00\x00':
        raise ValueError('invalid Wasm header')
    position = 8

    def leb(end):
        nonlocal position
        value = shift = 0
        while position < end and shift < 35:
            byte = module[position]
            position += 1
            value |= (byte & 127) << shift
            if byte < 128:
                return value
            shift += 7
        raise ValueError('truncated/oversized Wasm integer')

    count = 0
    while position < len(module):
        section = module[position]
        position += 1
        size = leb(len(module))
        end = position + size
        if end > len(module):
            raise ValueError('truncated Wasm section')
        if section == 10:
            for _ in range(leb(end)):
                size = leb(end)
                body_end = position + size
                if body_end > end:
                    raise ValueError('truncated Wasm body')
                for _ in range(leb(body_end)):
                    count += leb(body_end)
                    if position >= body_end:
                        raise ValueError('missing local type')
                    position += 1
                position = body_end
        position = end
    return count


def git_identity(repo, declared_revision=None):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args], text=True,
                                       stderr=subprocess.DEVNULL).strip()
    identity = dict(kind='source-snapshot', revision=None, working_tree_dirty=None,
                    declared_revision=declared_revision,
                    provenance_note='declared_revision is caller-supplied; exact module hashes identify source snapshots',
                    modules={str(path.relative_to(repo)): sha256(path.read_bytes())
                             for path in sorted((repo / 'axiom/src/axiom').glob('*.py'))})
    try:
        # An archive inside another checkout must not inherit its parent's HEAD.
        if Path(git('rev-parse', '--show-toplevel')).resolve() == repo.resolve():
            identity.update(kind='git-checkout', revision=git('rev-parse', 'HEAD'),
                            working_tree_dirty=bool(git('status', '--porcelain')))
    except (OSError, subprocess.CalledProcessError):
        pass
    return identity


def diagnostic(service, source):
    """Independent call-count audit; never a release benchmark sample."""
    profiler = cProfile.Profile()
    profiler.runcall(service.prepare_compiled_demo, source)
    functions = []
    for (filename, line, name), (_, calls, own, inclusive, _) in pstats.Stats(profiler).stats.items():
        if '/axiom/' in filename.replace('\\', '/'):
            functions.append(dict(file=Path(filename).name, line=line, function=name, calls=calls,
                                  self_ns=round(own * 1e9), inclusive_ns=round(inclusive * 1e9)))
    trace = None
    if 'trace' in inspect.signature(service.prepare_compiled_demo).parameters:
        from axiom.compilation_trace import CompilationTrace
        sink = CompilationTrace()
        checked = service.prepare_compiled_demo(source, trace=sink)
        if checked['status'] != 'prepared':
            raise ValueError(checked)
        trace = sink.report()
    return dict(scope='separate diagnostic preparations; inclusive times include overhead',
                call_counts=functions, trace=trace)


def native_pipeline():
    """Resolve the selected checkout's API before timing runtime-ready source work.

    A broken dependency in a new compiler must fail rather than silently measure
    the legacy path. Only absence of the coordinator/API enables old-checkout use.
    """
    try:
        coordinator = importlib.import_module('axiom.source_compilation')
    except ModuleNotFoundError as error:
        if error.name != 'axiom.source_compilation':
            raise
        coordinator = None
    if coordinator is not None and hasattr(coordinator, 'compile_native_source'):
        return 'source-coordinator', coordinator.compile_native_source
    from axiom.frontend import admit_source, parse_source
    from axiom.model import Limits
    from axiom.selection import select_plan
    from axiom.native_codegen import emit_native_c

    def legacy_prepare(source):
        limits = Limits()
        kernel = admit_source(parse_source(source, limits))
        search = select_plan(kernel, limits, 100000, kernel.objective)
        if search.selected_plan_bytes is None:
            raise ValueError('no eligible native plan')
        artifact = emit_native_c(source, search.selected_plan_bytes, limits)
        return SimpleNamespace(kernel=kernel, search=search, artifact=artifact, hint_failure=None)

    return 'legacy-public-bytes', legacy_prepare


def native_diagnostic(prepare, source, expected_c_digest):
    """Separate diagnostic source preparations, never part of native wall samples."""
    profiler = cProfile.Profile()
    result = profiler.runcall(prepare, source)
    if result.artifact is None or sha256(result.artifact.c_source) != expected_c_digest:
        raise ValueError('diagnostic native artifact differs from timed preparation')
    counts = []
    for (filename, line, name), (_, calls, _, _, _) in pstats.Stats(profiler).stats.items():
        if '/axiom/' in filename.replace('\\', '/'):
            counts.append(dict(file=Path(filename).name, line=line, function=name, calls=calls))
    trace = None
    if 'trace' in inspect.signature(prepare).parameters:
        from axiom.compilation_trace import CompilationTrace
        sink = CompilationTrace()
        traced = prepare(source, trace=sink)
        if traced.artifact is None or sha256(traced.artifact.c_source) != expected_c_digest:
            raise ValueError('traced native artifact differs from timed preparation')
        trace = sink.report()
    return dict(scope='separate native diagnostic preparations after wall samples and output audit',
                call_counts=counts, trace=trace)


def native_sample(source, case, cc, directory, flags, diagnostics=False):
    pipeline, prepare = native_pipeline()
    source_bytes = source.encode()
    # Imports/API resolution precede this runtime-ready interval. Both paths
    # freshly admit the entire source; no prior service proof enters this call.
    total_start = perf_counter_ns()
    compiled = prepare(source_bytes)
    source_ns = perf_counter_ns() - total_start
    artifact, selection = compiled.artifact, compiled.search
    if artifact is None or selection.selected_plan_bytes is None:
        raise ValueError('no eligible native artifact')
    # File materialization is part of total source-to-executable wall time.
    c_path, executable = directory / 'sample.c', directory / 'sample'
    c_path.write_bytes(artifact.c_source)
    command = [cc, *flags, str(c_path), '-o', str(executable)]
    start = perf_counter_ns()
    subprocess.run(command, check=True, capture_output=True, timeout=180)
    compiled_at = perf_counter_ns()
    compile_ns = compiled_at - start
    total_ns = compiled_at - total_start
    # Identity and independent execution audits occur after compilation timing.
    if (artifact.source_digest != sha256(source_bytes)
            or artifact.plan_digest != sha256(selection.selected_plan_bytes)
            or artifact.c_digest != sha256(artifact.c_source)):
        raise ValueError('native source/plan/generated-C identity mismatch')
    if (artifact.height, artifact.width, artifact.input_count, artifact.output_count) != (
            case['height'], case['width'], (case['height'] + 1) * (case['width'] + 1),
            case['height'] * case['width']):
        raise ValueError('native artifact dimensions differ from fixture')
    data = [index % 1024 for index in range(artifact.input_count)]
    raw = subprocess.check_output([str(executable)], input=' '.join(map(str,
        [case['height'], case['width'], *data])).encode(), timeout=30)
    audit_output(json.loads(raw), data, case['height'], case['width'])
    record = dict(measurement_schema_version=2, pipeline=pipeline,
                  scope=('fresh source coordinator admission/ranked proof/compact emission (or typed finite fallback), '
                         if pipeline == 'source-coordinator' else
                         'legacy fresh public admission/selection and separately fresh public byte emission, ')
                        + 'C-file materialization and real compiler/link; execution and audits excluded',
                  source_compilation_ns=source_ns, source_compilation_seconds=source_ns / 1e9,
                  native_compiler_link_ns=compile_ns, native_compiler_link_seconds=compile_ns / 1e9,
                  total_fresh_native_preparation_ns=total_ns,
                  total_fresh_native_preparation_seconds=total_ns / 1e9, flags=flags,
                  source_sha256=artifact.source_digest,
                  generated_c_bytes=len(artifact.c_source), generated_c_sha256=artifact.c_digest,
                  codegen_version=getattr(artifact, 'codegen_version', 'legacy-finite-c-unversioned'),
                  hint_sha256=getattr(artifact, 'hint_digest', None),
                  loop_version=getattr(artifact, 'loop_version', None), hint_failure=compiled.hint_failure,
                  executable_bytes=executable.stat().st_size, executable_sha256=sha256(executable.read_bytes()),
                  selected_plan_id=selection.selected_plan.plan_id,
                  policy_id=getattr(selection, 'policy_id', 'legacy-select-plan'),
                  policy_digest=getattr(selection, 'policy_digest', None),
                  deterministic_check_work=selection.total_work_used,
                  termination_reason=str(selection.termination_reason), artifact_state=str(selection.artifact_state),
                  plan_sha256=artifact.plan_digest, plan_bytes=len(selection.selected_plan_bytes),
                  plan_operations=len(selection.selected_plan.operations),
                  candidate_states=[dict(candidate_id=attempt.candidate_id,
                                         state=str(attempt.state) if hasattr(attempt, 'state') else None,
                                         reason=attempt.reason, work_used=attempt.work_used)
                                    for attempt in selection.attempts],
                  command=command, independent_audit='passed')
    if diagnostics:
        record['diagnostic'] = native_diagnostic(prepare, source_bytes, artifact.c_digest)
        object_path, ir_path, trace_path = directory / 'sample.o', directory / 'sample.ll', directory / 'sample-trace.json'
        subprocess.run([cc, *flags, '-c', str(c_path), '-o', str(object_path),
                        '-ftime-trace=' + str(trace_path)], check=True, capture_output=True, timeout=180)
        subprocess.run([cc, *flags, '-S', '-emit-llvm', str(c_path), '-o', str(ir_path)],
                       check=True, capture_output=True, timeout=180)
        record['compiler_diagnostics'] = dict(scope='separate instrumented object/IR builds, outside full-link samples',
            object_bytes=object_path.stat().st_size, optimized_ir_bytes=ir_path.stat().st_size,
            object_sha256=sha256(object_path.read_bytes()), optimized_ir_sha256=sha256(ir_path.read_bytes()),
            clang_time_trace=json.loads(trace_path.read_text()))
    return record


def worker(repo, specification):
    boot = perf_counter_ns()
    sys.path.insert(0, str(repo / 'axiom/src'))
    service = importlib.import_module('axiom.playground_service')
    if specification['cc']:
        native_pipeline()  # Preload the selected native path inside compiler boot.
    boot_ns = perf_counter_ns() - boot
    output = dict(identity=git_identity(repo, specification.get('declared_revision')), total_app_boot_ns=boot_ns,
                  boot_scope='Python compiler imports only; interpreter process startup excluded', cases=[])
    with tempfile.TemporaryDirectory(prefix='beryl-compile-profile-') as temporary:
        for case in specification['fixtures']:
            source = fixture_source(case)
            start = perf_counter_ns()
            result = service.prepare_compiled_demo(source)
            elapsed = perf_counter_ns() - start
            if result.get('status') != 'prepared':
                raise ValueError(result)
            module = base64.b64decode(result.pop('wasm_base64'))
            if sha256(source.encode()) != result['source_digest'] or sha256(module) != result['module_digest']:
                raise ValueError('artifact identity mismatch')
            record = dict(fixture=case, source=source, source_sha256=sha256(source.encode()),
                          total_fresh_source_preparation_ns=elapsed, metadata=result,
                          module_bytes=len(module), module_locals=wasm_local_count(module), module_sha256=sha256(module))
            if specification['diagnostics']:
                record['diagnostic'] = diagnostic(service, source)
            if specification['cc']:
                record['native'] = native_sample(source, case, specification['cc'], Path(temporary),
                                                  specification['flags'], specification['diagnostics'])
            output['cases'].append(record)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--baseline-repo', type=Path, help='exact baseline checkout; loaded in a separate process')
    parser.add_argument('--repo-revision', help='declared origin revision for an archived candidate (not a verified Git identity)')
    parser.add_argument('--baseline-revision', help='declared origin revision for an archived baseline (not a verified Git identity)')
    parser.add_argument('--fixture-set', choices=('smoke', 'qualification', 'boundary'), default='qualification')
    parser.add_argument('--fixture-id', action='append', help='restrict to these exact fixture IDs (repeatable)')
    parser.add_argument('--list-fixtures', action='store_true')
    parser.add_argument('--samples', type=int, default=7)
    parser.add_argument('--diagnostics', action='store_true', help='separate cProfile/trace and optional Clang trace/IR builds, first round only')
    parser.add_argument('--cc', help='also measure fresh source-native preparation and compiler/link, with old-checkout public-byte fallback')
    parser.add_argument('--cflag', action='append', help='explicit compiler experiment flags; default -O3 -std=c11')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.repo.resolve(), json.load(sys.stdin)), allow_nan=False))
        return
    fixtures = build_fixtures(args.fixture_set)
    if args.fixture_id:
        fixtures = [case for case in fixtures if case['id'] in args.fixture_id]
        if len(fixtures) != len(set(args.fixture_id)):
            parser.error('fixture ID not found in selected fixture set')
    if args.list_fixtures:
        print(json.dumps([dict(case, source=fixture_source(case)) for case in fixtures], indent=2))
        return
    if args.samples < 1 or args.output is None or args.output.exists():
        parser.error('positive samples and a new --output path are required')
    flags = args.cflag or ['-O3', '-std=c11']
    cc = shutil.which(args.cc) if args.cc else None
    if args.cc and cc is None:
        parser.error('native compiler not found')
    revisions = {'candidate': args.repo.resolve()}
    if args.baseline_repo:
        revisions['baseline'] = args.baseline_repo.resolve()
    report = dict(schema_version=1, created_utc=datetime.now(timezone.utc).isoformat(), scope=SCOPE,
                  timing_unit='ns', platform=platform.platform(), python=sys.version,
                  python_executable=dict(path=sys.executable, binary_sha256=sha256(Path(sys.executable).read_bytes())),
                  harness_sha256=sha256(Path(__file__).read_bytes()), samples=args.samples,
                  fixture_set=args.fixture_set, rounds=[], flags=flags)
    if cc:
        report['compiler'] = dict(path=cc, binary_sha256=sha256(Path(cc).read_bytes()),
            version=subprocess.check_output([cc, '--version'], text=True).splitlines()[0])
    for round_index in range(args.samples):
        names = list(revisions)
        if round_index % 2:
            names.reverse()
        round_record = dict(index=round_index, order=names, revisions={})
        for name in names:
            spec = dict(fixtures=fixtures, diagnostics=args.diagnostics and round_index == 0, cc=cc, flags=flags,
                        declared_revision=args.baseline_revision if name == 'baseline' else args.repo_revision)
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker', '--repo', str(revisions[name])],
                input=json.dumps(spec), text=True, capture_output=True, check=True, timeout=1800)
            round_record['revisions'][name] = json.loads(result.stdout)
        report['rounds'].append(round_record)
    report['status'] = 'passed'
    report['medians_ns'] = {name: {case['id']: statistics.median(
        round_record['revisions'][name]['cases'][index]['total_fresh_source_preparation_ns']
        for round_record in report['rounds']) for index, case in enumerate(fixtures)} for name in revisions}
    if cc:
        report['native_medians_ns'] = {name: {case['id']: {
            'pipeline': report['rounds'][0]['revisions'][name]['cases'][index]['native']['pipeline'],
            **{field: statistics.median(
                item['revisions'][name]['cases'][index]['native'][field]
                for item in report['rounds']) for field in (
                    'source_compilation_ns', 'native_compiler_link_ns', 'total_fresh_native_preparation_ns')}
        } for index, case in enumerate(fixtures)} for name in revisions}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(args.output)


if __name__ == '__main__':
    main()
