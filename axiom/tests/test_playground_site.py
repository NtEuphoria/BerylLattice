"""The distributable playground must contain runnable, scoped compiler sources."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
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
            with zipfile.ZipFile(output / 'axiom-compiler.zip') as archive:
                self.assertEqual(set(archive.namelist()), {
                    'axiom/' + name + '.py' for name in (
                        '__init__', 'runtime', 'playground_service', 'frontend', 'model',
                        'checker', 'codec', 'plan_format', 'planner', 'selection', 'reference')} | {'LICENSE'})
                self.assertEqual(archive.read('LICENSE').decode('utf-8'), license_text)
            # The real release ZIP, without the repository on sys.path, must execute.
            executed = subprocess.run([sys.executable, '-I', '-c',
                'import sys,json; sys.path.insert(0,sys.argv[1]); '
                'from axiom.playground_service import get_examples,run_demo; '
                'r=run_demo(dict(source=get_examples()["examples"][0]["source"],'
                'input_mode="ramp")); print(json.dumps(r))',
                str(output / 'axiom-compiler.zip')], capture_output=True, text=True)
            self.assertEqual(executed.returncode, 0, executed.stderr)
            result = json.loads(executed.stdout)
            self.assertEqual(result['status'], 'success')
            self.assertEqual(result['selected']['plan_id'], 'rows2-v1')
            self.assertEqual(result['output'][0], 186)
            self.assertEqual(result['output'][-1], 7634)
            self.assertTrue(result['comparison']['matches'])
            manifest = json.loads((output / 'release-manifest.json').read_text())
            with zipfile.ZipFile(output / 'axiom-compiler.zip') as archive:
                self.assertEqual(set(archive.namelist()), set(manifest['compiler_archive_members']))
                for name, entry in manifest['compiler_archive_members'].items():
                    raw = archive.read(name)
                    self.assertEqual(entry['sha256'], hashlib.sha256(raw).hexdigest())
                    self.assertEqual(entry['bytes'], len(raw))
            self.assertEqual(set(manifest['files']),
                             {p.relative_to(output).as_posix() for p in output.rglob('*')
                              if p.is_file()} - {'release-manifest.json'})
            for name, entry in manifest['files'].items():
                raw = (output / name).read_bytes()
                self.assertEqual(entry['sha256'], hashlib.sha256(raw).hexdigest())
                self.assertEqual(entry['bytes'], len(raw))

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


if __name__ == '__main__':
    unittest.main()
