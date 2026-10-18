"""The distributable playground must contain runnable, scoped compiler sources."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'tools' / 'build-playground-site.py'


class PlaygroundSiteTests(unittest.TestCase):
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
                    'beryl/' + name + '.py' for name in (
                        '__init__', 'runtime', 'playground_service', 'frontend', 'model',
                        'checker', 'codec', 'plan_format', 'planner', 'selection', 'reference')} | {'LICENSE'})
                self.assertEqual(archive.read('LICENSE').decode('utf-8'), license_text)
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
                            request['inputs'] = [3] * 48
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
            self.assertEqual(len(report['cases']), 16)
            for index, case in enumerate(report['cases']):
                with self.subTest(case=case['name']):
                    public, private = case['public'], case['private']
                    if index < 12:
                        self.assertEqual(public['status'], 'success')
                        self.assertNotEqual(public['selected']['plan_digest'],
                                            private['selected']['plan_digest'])
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


if __name__ == '__main__':
    unittest.main()
