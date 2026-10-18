#!/usr/bin/env python3
"""Prepare byte-exact public ZIP native artifacts; never build or benchmark C.

Run: python -I prepare_artifacts.py
Each public API operation runs in a fresh isolated Python process loading one
ZIP as the public beryl package. No checkout compiler module is imported.
"""
import argparse
import dataclasses
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import platform
import subprocess
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
ZIPS = {
    'old': Path('/workspace/scratch/beryl-compiled/site-release/beryl-compiler.zip'),
    'new': Path('/workspace/scratch/beryl-fast-compilation/candidate-native-final/beryl-compiler.zip'),
}
CASES = ((15, 15, 0, 'inline-v1'), (15, 15, 128, 'rows2-v1'),
         (5, 7, 0, 'inline-v1'), (1, 1, 0, 'inline-v1'))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def reject_private_name(data):
    # Keep private package spelling out of public artifacts and manifests.
    forbidden = bytes((97, 120, 105, 111, 109))
    assert forbidden not in data.lower(), 'non-public package spelling found'


def zip_identity(path):
    with ZipFile(path) as archive:
        modules = {name: sha(archive.read(name)) for name in sorted(archive.namelist())
                   if name.startswith('beryl/') and name.endswith('.py')}
    return dict(path=str(path), sha256=sha(path.read_bytes()), modules_sha256=modules)


def check_origins(zip_path):
    origins = {}
    for name, module in sorted(sys.modules.items()):
        if name == 'beryl' or name.startswith('beryl.'):
            origin = module.__spec__.origin
            prefix = str(zip_path) + '/'
            assert origin.startswith(prefix), (name, origin)
            member = origin[len(prefix):]
            with ZipFile(zip_path) as archive:
                module_hash = sha(archive.read(member))
            origins[name] = dict(origin=origin, zip_member=member, sha256=module_hash)
    assert origins
    return origins


def worker(args):
    assert sys.flags.isolated == 1
    assert not any(name == 'beryl' or name.startswith('beryl.') for name in sys.modules)
    zip_path = Path(args.zip).resolve()
    sys.path.insert(0, str(zip_path))
    service = importlib.import_module('beryl.playground_service')
    examples = service.get_examples()
    base = next(item['source'].encode('utf-8') for item in examples['examples']
                if item['id'] == 'no-scratch')
    if args.example:
        check_origins(zip_path)
        print(json.dumps(dict(source_utf8=base.decode('utf-8'), source_sha256=sha(base))))
        return
    from beryl.model import Limits
    from beryl.checker import CHECKER_VERSION
    source_path = Path(args.source).resolve()
    source = source_path.read_bytes()
    limits = Limits()
    if args.variant == 'old':
        from beryl.frontend import admit_source, parse_source
        from beryl.selection import select_plan
        from beryl.native_codegen import emit_native_c
        kernel = admit_source(parse_source(source, limits))
        search = select_plan(kernel, limits, 100000, kernel.objective)
        assert search.selected_plan_bytes is not None
        artifact = emit_native_c(source, search.selected_plan_bytes, limits)
        failure = None
        pipeline = 'fresh parse_source/admit_source/select_plan + public emit_native_c'
    else:
        from beryl.source_compilation import compile_native_source
        result = compile_native_source(source, limits)
        kernel, search, artifact = result.kernel, result.search, result.artifact
        failure = result.hint_failure
        pipeline = 'compile_native_source'
        assert artifact is not None
        assert failure is None
        assert artifact.codegen_version == 'beryl-bounded-loop-c-v1'
        assert artifact.hint_digest is not None and artifact.loop_version is not None
    assert artifact is not None and search.selected_plan_bytes is not None
    assert search.selected_plan is not None and search.selected_check is not None
    plan = search.selected_plan_bytes
    checked = search.selected_check
    assert checked.eligible
    assert artifact.source_digest == kernel.source_digest == sha(source)
    assert artifact.plan_digest == checked.plan_digest == sha(plan)
    assert artifact.c_digest == sha(artifact.c_source)
    assert search.selected_plan.plan_id == args.expected_plan
    assert (artifact.height, artifact.width) == (kernel.height, kernel.width)
    assert artifact.input_count == (kernel.height + 1) * (kernel.width + 1)
    assert artifact.output_count == kernel.height * kernel.width
    output_dir = source_path.parent
    c_path = output_dir / (args.variant + '.c')
    plan_path = output_dir / (args.variant + '.plan')
    reject_private_name(artifact.c_source)
    reject_private_name(source)
    reject_private_name(plan)
    c_path.write_bytes(artifact.c_source)
    plan_path.write_bytes(plan)
    report = dict(
        schema='beryl-public-zip-native-artifact-v1', variant=args.variant,
        zip=zip_identity(zip_path), imports=check_origins(zip_path),
        python=dict(executable=sys.executable, version=platform.python_version(), isolated=True),
        pipeline=pipeline, options=dict(limits=dataclasses.asdict(limits),
                                      total_check_steps=100000,
                                      objective=kernel.objective.value),
        fixture=dict(source_path=str(source_path), source_sha256=sha(source),
                     source_bytes=len(source), height=kernel.height, width=kernel.width,
                     workspace_cap=kernel.cap, base_public_example_id='no-scratch',
                     base_public_example_sha256=sha(base)),
        selected=dict(plan_id=search.selected_plan.plan_id, plan_path=str(plan_path),
                      plan_sha256=sha(plan), plan_bytes=len(plan),
                      multiplication_ops=checked.multiplication_ops,
                      workspace_bytes=checked.workspace_bytes,
                      operation_count=len(search.selected_plan.operations),
                      opcode_counts=dict(checked.opcode_counts),
                      ranking_key=search.selected_key,
                      checker_version=CHECKER_VERSION,
                      semantics_version=kernel.semantics_version,
                      check_complete=checked.check_complete,
                      semantic_status=checked.semantic_status.value,
                      constraint_status=checked.constraint_status.value),
        selection=dict(termination_reason=search.termination_reason.value,
                       total_work_used=search.total_work_used,
                       budget_accounting_version=search.budget_accounting_version,
                       report_version=getattr(search, 'report_version', 1),
                       policy_id=getattr(search, 'policy_id', 'legacy-public-selection'),
                       policy_digest=getattr(search, 'policy_digest', None)),
        artifact=dict(c_path=str(c_path), c_sha256=sha(artifact.c_source),
                      c_bytes=len(artifact.c_source),
                      codegen_version=getattr(artifact, 'codegen_version', 'beryl-finite-c-v1'),
                      codegen_version_declared_on_artifact=hasattr(artifact, 'codegen_version'),
                      hint_digest=getattr(artifact, 'hint_digest', None),
                      loop_version=getattr(artifact, 'loop_version', None),
                      hint_failure=failure),
    )
    encoded = json.dumps(report).encode()
    reject_private_name(encoded)
    write_json(output_dir / (args.variant + '.provenance.json'), report)


def invoke(*args):
    command = [sys.executable, '-I', str(Path(__file__).resolve()), '--worker', *args]
    process = subprocess.run(command, check=True, capture_output=True, text=True,
                             cwd='/tmp', timeout=180)
    return process.stdout


def main():
    examples = {name: json.loads(invoke('--zip', str(path), '--example'))
                for name, path in ZIPS.items()}
    assert examples['old'] == examples['new'], 'public example bytes differ'
    base = examples['old']['source_utf8'].encode('utf-8')
    records = []
    for height, width, cap, expected_plan in CASES:
        case_id = f'{height}x{width}-cap{cap}'
        directory = ROOT / case_id
        directory.mkdir(exist_ok=True)
        substitutions = [(b'shape H = 5;', f'shape H = {height};'.encode()),
                         (b'shape W = 7;', f'shape W = {width};'.encode()),
                         (b'require plan_workspace_bytes <= 0;',
                          f'require plan_workspace_bytes <= {cap};'.encode())]
        source = base
        for before, after in substitutions:
            assert source.count(before) == 1
            source = source.replace(before, after)
        source_path = directory / 'source.bryl'
        source_path.write_bytes(source)
        for name, path in ZIPS.items():
            invoke('--zip', str(path), '--variant', name, '--source', str(source_path),
                   '--expected-plan', expected_plan)
        reports = {name: json.loads((directory / (name + '.provenance.json')).read_text())
                   for name in ZIPS}
        assert reports['old']['fixture'] == reports['new']['fixture']
        assert reports['old']['selected'] | {'plan_path': None} == reports['new']['selected'] | {'plan_path': None}
        assert (directory / 'old.plan').read_bytes() == (directory / 'new.plan').read_bytes()
        record = dict(case_id=case_id, expected_plan=expected_plan,
                      substitutions=[dict(before=a.decode(), after=b.decode()) for a, b in substitutions],
                      source_sha256=sha(source),
                      selected_plan_sha256=reports['old']['selected']['plan_sha256'],
                      metrics={key: reports['old']['selected'][key] for key in
                               ('multiplication_ops', 'workspace_bytes', 'operation_count')},
                      old=reports['old']['artifact'], new=reports['new']['artifact'],
                      provenance_paths={name: str(directory / (name + '.provenance.json')) for name in ZIPS})
        records.append(record)
    manifest = dict(schema='beryl-public-zip-native-kernel-pairs-v1',
                    created_utc=datetime.now(timezone.utc).isoformat(),
                    helper_path=str(Path(__file__).resolve()),
                    helper_sha256=sha(Path(__file__).read_bytes()),
                    invocation=[sys.executable, '-I', str(Path(__file__).resolve())],
                    scope='Artifact preparation only; no C compilation, execution, or timing.',
                    public_namespace='beryl', fresh_process_per_zip_and_case=True,
                    public_example=examples['old'],
                    zips={name: zip_identity(path) for name, path in ZIPS.items()},
                    cases=records,
                    assertions=dict(identical_source_bytes=True, identical_plan_bytes=True,
                                    identical_selected_metrics=True, all_import_origins_in_selected_zip=True,
                                    candidate_compact_path=True, public_spelling_only=True),
                    execution_audit='Deferred to tools/measure-kernel.py by controller after tests are idle.')
    manifest_bytes = json.dumps(manifest).encode()
    reject_private_name(manifest_bytes)
    write_json(ROOT / 'manifest.json', manifest)
    for path in ROOT.rglob('*'):
        if path.is_file():
            reject_private_name(path.read_bytes())
    print(ROOT / 'manifest.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--zip')
    parser.add_argument('--example', action='store_true')
    parser.add_argument('--variant', choices=('old', 'new'))
    parser.add_argument('--source')
    parser.add_argument('--expected-plan')
    args = parser.parse_args()
    worker(args) if args.worker else main()
