"""The distributable playground must contain runnable, scoped compiler sources."""
import ast
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'tools' / 'build-playground-site.py'
PUBLIC_MODULES = {
    '__init__', 'runtime', 'playground_service', 'frontend', 'model', 'checker',
    'codec', 'plan_format', 'planner', 'selection', 'reference', 'wasm', 'native_codegen',
    'compilation', 'compilation_trace', 'compilation_selection', 'source_compilation', 'bounded_loop_model',
    'bounded_loop_codec', 'bounded_loop_planner', 'bounded_loop_correspondence',
    'bounded_loop_c', 'bounded_loop_wasm', 'window_family', 'window_planner', 'window_loop_planner', 'window_explain', 'reduce_family',
}

_NODE_COMPILED_RUNNER = r'''
const fs = require('node:fs');
const {prepared, runs} = JSON.parse(fs.readFileSync(0, 'utf8'));
const compiledModule = new WebAssembly.Module(Buffer.from(prepared.wasm_base64, 'base64'));
if (WebAssembly.Module.imports(compiledModule).length) throw new Error('Unexpected Wasm import');
const {memory, run} = new WebAssembly.Instance(compiledModule).exports;
const i32 = new Int32Array(memory.buffer);
const observed = runs.map(item => {
  i32.fill(0);
  i32.set(item.input, prepared.input_offset / 4);
  i32.set(item.initial_output, prepared.output_offset / 4);
  return {status: run(),
    input: Array.from(i32.slice(prepared.input_offset / 4,
                               prepared.input_offset / 4 + prepared.input_count)),
    output: Array.from(i32.slice(prepared.output_offset / 4,
                                prepared.output_offset / 4 + prepared.output_count))};
});
process.stdout.write(JSON.stringify(observed));
'''


class PlaygroundSiteTests(unittest.TestCase):
    def build_release(self, output):
        result = subprocess.run([sys.executable, str(BUILD), '--output', str(output),
                                 '--runtime', 'cdn'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def run_public_source(self, output, script, *arguments):
        # -I excludes the checkout and caller environment; only this ZIP is added.
        setup = 'import sys\nsys.path.insert(0, sys.argv[1])\n'
        result = subprocess.run([sys.executable, '-I', '-c', setup + textwrap.dedent(script),
                                 str(output / 'beryl-compiler.zip'), *arguments],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_static_release_runs_same_compiler_without_private_sources(self):
        with tempfile.TemporaryDirectory() as scratch:
            output = Path(scratch) / 'site'
            built = subprocess.run([sys.executable, str(BUILD), '--output', str(output),
                                    '--runtime', 'cdn'], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            self.assertIn('data-runtime="browser"', (output / 'index.html').read_text())
            self.assertTrue((output / '.nojekyll').is_file(), 'Pages must serve this static release verbatim')
            self.assertEqual((output / '.nojekyll').read_bytes(), b'')
            self.assertTrue((output / 'LICENSE').is_file(), 'public demo needs its approved license')
            license_text = (output / 'LICENSE').read_text()
            self.assertIn('MIT License', license_text)
            self.assertIn('Copyright (c) 2026 NtEuphoria', license_text)
            self.assertIn('Permission is hereby granted, free of charge', license_text)
            self.assertEqual(license_text, (ROOT / 'axiom/playground-LICENSE').read_text())
            with zipfile.ZipFile(output / 'beryl-compiler.zip') as archive:
                self.assertEqual(set(archive.namelist()), {
                    'beryl/' + name + '.py' for name in PUBLIC_MODULES} | {'LICENSE'})
                self.assertEqual(archive.read('LICENSE').decode('utf-8'), license_text)
                for name in PUBLIC_MODULES:
                    tree = ast.parse(archive.read(f'beryl/{name}.py'))
                    for node in ast.walk(tree):
                        if isinstance(node, ast.ImportFrom):
                            if node.level:
                                self.assertEqual(node.level, 1)
                                self.assertIn(node.module.split('.')[0], PUBLIC_MODULES)
                            else:
                                self.assertIn(node.module.split('.')[0], sys.stdlib_module_names)
                        elif isinstance(node, ast.Import):
                            for imported in node.names:
                                self.assertIn(imported.name.split('.')[0], sys.stdlib_module_names)
            # The real release ZIP, without the repository on sys.path, must execute.
            executed = subprocess.run([sys.executable, '-I', '-c',
                'import sys,json; sys.path.insert(0,sys.argv[1]); '
                'from beryl.playground_service import get_examples,run_demo; '
                'r=run_demo(dict(source=get_examples()["examples"][0]["source"],'
                'input_mode="ramp")); print(json.dumps(r))',
                str(output / 'beryl-compiler.zip')], capture_output=True, text=True)
            self.assertEqual(executed.returncode, 0, executed.stderr)
            result = json.loads(executed.stdout)
            self.assertEqual(result['status'], 'success')
            self.assertEqual(result['selected']['plan_id'], 'rows2-v1')
            self.assertEqual(result['output'][0], 186)
            self.assertEqual(result['output'][-1], 7634)
            self.assertTrue(result['comparison']['matches'])
            manifest = json.loads((output / 'release-manifest.json').read_text())
            with zipfile.ZipFile(output / 'beryl-compiler.zip') as archive:
                self.assertEqual(set(archive.namelist()), set(manifest['compiler_archive_members']))
                for name, entry in manifest['compiler_archive_members'].items():
                    raw = archive.read(name)
                    self.assertEqual(entry['sha256'], hashlib.sha256(raw).hexdigest())
                    self.assertEqual(entry['bytes'], len(raw))
                    self.assertNotIn('axiom', name.lower())
                    self.assertNotIn(b'axiom', raw.lower(), name)
            self.assertEqual(set(manifest['files']),
                             {p.relative_to(output).as_posix() for p in output.rglob('*')
                              if p.is_file()} - {'release-manifest.json'})
            for name, entry in manifest['files'].items():
                raw = (output / name).read_bytes()
                self.assertEqual(entry['sha256'], hashlib.sha256(raw).hexdigest())
                self.assertEqual(entry['bytes'], len(raw))
                self.assertNotIn('axiom', name.lower())
                if not name.endswith('.zip'):
                    self.assertNotIn(b'axiom', raw.lower(), name)
            self.assertNotIn('axiom', (output / 'release-manifest.json').read_text().lower())

    def test_standalone_public_preparation_exports_checked_wasm_metadata(self):
        with tempfile.TemporaryDirectory() as scratch:
            output = Path(scratch) / 'site'
            self.build_release(output)
            report = self.run_public_source(output, '''
                import base64
                import json
                from beryl.codec import encode_plan
                from beryl.frontend import admit_source, parse_source
                from beryl.model import Limits
                from beryl.playground_service import (compiled_request_inputs,
                    compiled_request_source, get_examples, prepare_compiled_demo)
                from beryl.selection import select_plan
                from beryl.wasm import compile_wasm
                source = get_examples()['examples'][0]['source']
                source = source.replace('H = 5;', 'H = 1;').replace('W = 7;', 'W = 2;')
                request = dict(source=source, input_mode='ramp')
                kernel = admit_source(parse_source(source.encode()))
                search = select_plan(kernel, Limits(), 100000, kernel.objective)
                artifact = compile_wasm(source.encode(), encode_plan(search.selected_plan))
                prepared = prepare_compiled_demo(source)
                print(json.dumps(dict(prepared=prepared,
                    source=compiled_request_source(request),
                    inputs=compiled_request_inputs(request),
                    direct_module=base64.b64encode(artifact.module_bytes).decode(),
                    module_digest=artifact.module_digest, plan_digest=artifact.plan_digest,
                    source_digest=artifact.source_digest)))
                ''')
            prepared = report['prepared']
            self.assertEqual(prepared['status'], 'prepared')
            self.assertEqual(report['source']['status'], 'valid')
            self.assertEqual(report['inputs'], dict(status='ready', input=list(range(6)),
                                                   initial_output=[-9, -9]))
            self.assertEqual(prepared['schema_version'], 2)
            self.assertEqual(prepared['search']['policy_id'], 'ranked-proof-v1')
            self.assertIsNotNone(prepared['lowering']['hint_digest'])
            self.assertEqual(report['module_digest'], hashlib.sha256(base64.b64decode(report['direct_module'])).hexdigest())
            module_bytes = base64.b64decode(prepared['wasm_base64'], validate=True)
            self.assertTrue(module_bytes.startswith(b'\0asm\x01\0\0\0'))
            self.assertEqual(prepared['module_digest'], hashlib.sha256(module_bytes).hexdigest())
            self.assertEqual((prepared['input_count'], prepared['output_count']), (6, 2))
            self.assertEqual((prepared['input_offset'], prepared['output_offset']), (0, 24))
            self.assertEqual(prepared['memory_bytes'], 65536)
            for field in ('plan_digest', 'source_digest'):
                self.assertEqual(prepared[field], report[field])
            self.assertNotIn('axiom', json.dumps(report).lower())

    def test_standalone_public_trace_is_optional_diagnostics_not_authority(self):
        with tempfile.TemporaryDirectory() as scratch:
            output = Path(scratch) / 'site'
            self.build_release(output)
            report = self.run_public_source(output, """
                import json
                from beryl.compilation_trace import CompilationTrace
                from beryl.playground_service import (get_examples, prepare_compiled_demo,
                    compiled_request_source, compiled_request_inputs)
                source = get_examples()['examples'][0]['source']
                plain = prepare_compiled_demo(source)
                trace = CompilationTrace()
                traced = prepare_compiled_demo(source, trace=trace)
                snapshot = trace.report()
                snapshot['counts']['semantic_checks'] = 999
                request = dict(source=source, input_mode='ramp')
                forged = compiled_request_source(dict(request, trace=snapshot))
                invalid = prepare_compiled_demo('module ;', trace=trace)
                stale = compiled_request_inputs(request)
                print(json.dumps(dict(plain=plain, traced=traced, trace=trace.report(),
                                      forged=forged, invalid=invalid, stale=stale)))
                """)
            self.assertEqual(report['plain'], report['traced'])
            self.assertEqual(report['traced']['schema_version'], 2)
            self.assertEqual(report['trace']['counts']['source_admissions'], 1)
            self.assertEqual(report['trace']['counts']['plan_validations'], 3)
            self.assertEqual(report['trace']['counts']['semantic_checks'], 1)
            self.assertEqual(report['trace']['phases']['loop_correspondence']['calls'], 1)
            self.assertEqual(report['trace']['phases']['code_emission']['calls'], 1)
            self.assertEqual(report['trace']['phases']['total_fresh_source_preparation']['calls'], 2)
            self.assertEqual(report['trace']['timing_semantics'], 'inclusive')
            self.assertEqual(report['forged']['diagnostic']['code'], 'INVALID_REQUEST')
            self.assertEqual(report['invalid']['status'], 'error')
            self.assertEqual(report['stale']['diagnostic']['code'], 'NOT_PREPARED')

    def test_standalone_public_wasm_reuses_module_and_compares_every_output(self):
        node = shutil.which('node')
        if node is None:
            self.skipTest('Node is required to execute public Wasm modules')
        with tempfile.TemporaryDirectory() as scratch:
            output = Path(scratch) / 'site'
            self.build_release(output)
            report = self.run_public_source(output, '''
                import json
                import subprocess
                from unittest.mock import patch
                from beryl import playground_service as service
                source = service.get_examples()['examples'][0]['source']
                source = source.replace('H = 5;', 'H = 1;').replace('W = 7;', 'W = 2;')
                requests = [dict(source=source, input_mode=mode)
                            for mode in ('ramp', 'zeros', 'checkerboard')]
                requests.extend([dict(source=source, input_mode='custom', inputs=values)
                                 for values in ([1024, 0, 0, 0, 0, -1], [0, 0, 0, 0, 0, 1024])])
                legacy = [service.run_demo(request) for request in requests]
                prepared = service.prepare_compiled_demo(source)
                inputs = [service.compiled_request_inputs(request) for request in requests]
                execution = subprocess.run([sys.argv[2], '-e', sys.argv[3]],
                    input=json.dumps(dict(prepared=prepared, runs=inputs)),
                    capture_output=True, text=True, check=True, timeout=15)
                observations = json.loads(execution.stdout)
                with patch.object(service, 'parse_source', side_effect=RuntimeError('reparsed')), \\
                     patch.object(service, 'select_plan', side_effect=RuntimeError('reselected')), \\
                     patch.object(service, 'compile_wasm_source', side_effect=RuntimeError('recompiled')), \\
                     patch.object(service, 'execute_plan', side_effect=RuntimeError('interpreted')), \\
                     patch.object(service, 'evaluate_source', wraps=service.evaluate_source) as evaluator:
                    results = [service.finish_compiled_demo(request, observation)
                               for request, observation in zip(requests, observations)]
                    observations[0]['output'][0] += 1
                    rejected = service.finish_compiled_demo(requests[0], observations[0])
                    comparisons = evaluator.call_count
                prepared['selected']['plan_id'] = 'forged'
                prepared['lowering']['hint_digest'] = 'forged'
                untampered = service.finish_compiled_demo(requests[1], observations[1])
                service.prepare_compiled_demo('module ;')
                invalidated = service.compiled_request_inputs(requests[0])
                print(json.dumps(dict(results=results, legacy=legacy,
                                      rejected=rejected, comparisons=comparisons,
                                      untampered=untampered, invalidated=invalidated)))
                ''', node, _NODE_COMPILED_RUNNER)
            self.assertEqual(report['comparisons'], 6)
            self.assertEqual(len(report['results']), 5)
            for compiled, legacy in zip(report['results'], report['legacy']):
                self.assertEqual(compiled['status'], legacy['status'])
                self.assertEqual(compiled['first_bad_index'], legacy['first_bad_index'])
                self.assertEqual(compiled['schema_version'], 2)
                self.assertEqual(compiled['backend'], 'checked-plan-wasm-v2')
                self.assertEqual(compiled['comparison'], dict(matches=True, cells_compared=2))
                self.assertEqual(compiled['output'], legacy['output'])
                self.assertEqual(compiled['input'], legacy['input'])
            self.assertEqual(report['results'][0]['output'], [46, 74])
            self.assertEqual(report['results'][1]['output'], [4, 4])
            self.assertEqual(report['results'][3]['first_bad_index'], 0)
            self.assertEqual(report['results'][4]['first_bad_index'], 5)
            self.assertEqual(report['results'][4]['output'], [-9, -9])
            self.assertNotEqual(report['untampered']['selected']['plan_id'], 'forged')
            self.assertNotEqual(report['untampered']['lowering']['hint_digest'], 'forged')
            self.assertEqual(report['invalidated']['diagnostic']['code'], 'NOT_PREPARED')
            self.assertEqual(report['rejected']['diagnostic']['code'], 'INDEPENDENT_COMPARISON_FAILED')
            self.assertNotIn('axiom', json.dumps(report).lower())

    def test_standalone_public_native_source_is_reproducible_and_branded(self):
        with tempfile.TemporaryDirectory() as scratch:
            output = Path(scratch) / 'site'
            self.build_release(output)
            report = self.run_public_source(output, '''
                import json
                from beryl.codec import encode_plan
                from beryl.frontend import admit_source, parse_source
                from beryl.native_codegen import emit_native_c
                from beryl.planner import make_plan
                from beryl.playground_service import get_examples
                source = get_examples()['examples'][0]['source']
                source = source.replace('H = 5;', 'H = 1;').replace('W = 7;', 'W = 2;')
                plan = make_plan(admit_source(parse_source(source.encode())), 'rows2-v1')
                plan_bytes = encode_plan(plan)
                artifact = emit_native_c(source.encode(), plan_bytes)
                print(json.dumps(dict(c_source=artifact.c_source.decode(),
                    c_digest=artifact.c_digest, source=source, plan=plan_bytes.decode(),
                    source_digest=artifact.source_digest, plan_digest=artifact.plan_digest,
                    counts=[artifact.input_count, artifact.output_count],
                    repeated=artifact == emit_native_c(source.encode(), plan_bytes))))
                ''')
            self.assertTrue(report['repeated'])
            self.assertEqual(report['counts'], [6, 2])
            self.assertIn('freshly checked finite beryl physical plan', report['c_source'])
            self.assertIn('int32_t beryl_kernel(', report['c_source'])
            self.assertIn('int main(void)', report['c_source'])
            self.assertEqual(report['c_digest'], hashlib.sha256(report['c_source'].encode()).hexdigest())
            self.assertEqual(report['source_digest'], hashlib.sha256(report['source'].encode()).hexdigest())
            self.assertEqual(report['plan_digest'], hashlib.sha256(report['plan'].encode()).hexdigest())
            self.assertNotIn('axiom', json.dumps(report).lower())

    def test_identical_inputs_produce_identical_public_release_bytes(self):
        with tempfile.TemporaryDirectory() as scratch:
            outputs = [Path(scratch) / name for name in ('first', 'second')]
            for output in outputs:
                self.build_release(output)
            first = {path.relative_to(outputs[0]): path.read_bytes()
                     for path in outputs[0].rglob('*') if path.is_file()}
            second = {path.relative_to(outputs[1]): path.read_bytes()
                      for path in outputs[1].rglob('*') if path.is_file()}
            self.assertEqual(first, second)
            readme = first[Path('README.md')].decode()
            self.assertIn('28 compiler/runtime Python modules', readme)
            self.assertIn('compiled Wasm instance is reused', readme)
            self.assertIn('independent evaluation of the source', readme)
            self.assertIn('finite-plan native C generator', readme)
            self.assertIn('C and Rust programs are compiled before timing', readme)

    def test_public_source_preserves_demo_behavior_with_distinct_plan_identity(self):
        with tempfile.TemporaryDirectory() as scratch:
            output = Path(scratch) / 'site'
            built = subprocess.run([sys.executable, str(BUILD), '--output', str(output),
                                    '--runtime', 'cdn'], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            compared = subprocess.run([sys.executable, '-I', '-c', textwrap.dedent('''
                import json
                import sys
                sys.path[:0] = sys.argv[1:]
                from beryl.playground_service import get_examples, run_demo
                from axiom.playground_service import get_examples as private_examples
                from axiom.playground_service import run_demo as private_run
                from beryl.model import SEMANTICS_VERSION
                from beryl.checker import CHECKER_VERSION
                cases = []
                for example in get_examples()['examples']:
                    for mode in ('ramp', 'zeros', 'checkerboard', 'custom'):
                        request = dict(source=example['source'], input_mode=mode)
                        if mode == 'custom':
                            request['inputs'] = [3] * len(cases[-3]['public']['input'])
                        cases.append(dict(name=example['id'] + '/' + mode,
                                          public=run_demo(request), private=private_run(request)))
                source = get_examples()['examples'][0]['source']
                rejected = (
                    ('syntax', dict(source='invalid', input_mode='ramp')),
                    ('input-mode', dict(source=source, input_mode='invalid')),
                    ('input-length', dict(source=source, input_mode='custom', inputs=[])),
                    ('scope', dict(source=source.replace('shape H = 5;', 'shape H = 256;'),
                                   input_mode='ramp')),
                )
                for name, request in rejected:
                    cases.append(dict(name=name, public=run_demo(request), private=private_run(request)))
                print(json.dumps(dict(catalog=get_examples(), private_catalog=private_examples(),
                                      semantics_version=SEMANTICS_VERSION,
                                      checker_version=CHECKER_VERSION, cases=cases)))
                '''), str(output / 'beryl-compiler.zip'), str(ROOT / 'axiom/src')],
                capture_output=True, text=True)
            self.assertEqual(compared.returncode, 0, compared.stderr)
            report = json.loads(compared.stdout)
            self.assertEqual(report['catalog'], report['private_catalog'])
            self.assertEqual(report['semantics_version'], 'beryl-stencil-i32-v1')
            self.assertEqual(report['checker_version'], 'beryl-checker-v1')
            demos = 4 * len(report['catalog']['examples'])
            self.assertEqual(len(report['catalog']['examples']), 5)
            self.assertEqual(len(report['cases']), demos + 4)
            for index, case in enumerate(report['cases']):
                with self.subTest(case=case['name']):
                    public, private = case['public'], case['private']
                    if index < demos:
                        self.assertEqual(public['status'], 'success')
                        # Only the canonical identity carries the renamed semantics
                        # version; window-family identities are the same in both builds.
                        family = case['name'].split('/')[0] in ('separable-blur', 'laplacian')
                        (self.assertEqual if family else self.assertNotEqual)(
                            public['selected']['plan_digest'], private['selected']['plan_digest'])
                        del public['selected']['plan_digest']
                        del private['selected']['plan_digest']
                    else:
                        self.assertEqual(public['status'], 'error')
                    self.assertEqual(public, private)

    def test_nonempty_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as scratch:
            output = Path(scratch)
            sentinel = output / 'my-file.txt'
            sentinel.write_text('keep this')
            result = subprocess.run([sys.executable, str(BUILD), '--output', str(output),
                                     '--runtime', 'cdn'], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(sentinel.read_text(), 'keep this')
            self.assertEqual(list(output.iterdir()), [sentinel])

    def test_unreviewed_source_branding_is_rejected(self):
        spec = importlib.util.spec_from_file_location('playground_site_build', BUILD)
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        original = (ROOT / 'axiom/src/axiom/__init__.py').read_bytes()
        cases = (
            ('missing marker', b'"""A different package description."""\n'),
            ('duplicate marker', original + original),
            ('additional codename', original + b'# Unexpected AXIOM reference.\n'),
        )
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            source = root / 'axiom/src/axiom/__init__.py'
            source.parent.mkdir(parents=True)
            with patch.object(builder, 'ROOT', root), patch.object(builder, 'MODULES', ('__init__',)):
                for name, raw in cases:
                    with self.subTest(case=name):
                        source.write_bytes(raw)
                        with self.assertRaises(ValueError):
                            builder.archive_modules()

    def test_unreviewed_native_source_branding_is_rejected(self):
        spec = importlib.util.spec_from_file_location('playground_site_build', BUILD)
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        original = (ROOT / 'axiom/src/axiom/native_codegen.py').read_bytes()
        cases = [('additional codename', original + b'# Unexpected AXIOM reference.\n')]
        for old, _ in builder.PUBLIC_SOURCE_REPLACEMENTS['native_codegen']:
            cases.extend((('missing ' + old.decode(), original.replace(old, b'unreviewed', 1)),
                          ('duplicate ' + old.decode(), original + b'\n' + old)))
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            source = root / 'axiom/src/axiom/native_codegen.py'
            source.parent.mkdir(parents=True)
            with patch.object(builder, 'ROOT', root), patch.object(builder, 'MODULES', ('native_codegen',)):
                for name, raw in cases:
                    with self.subTest(case=name):
                        source.write_bytes(raw)
                        with self.assertRaises(ValueError):
                            builder.archive_modules()


if __name__ == '__main__':
    unittest.main()
