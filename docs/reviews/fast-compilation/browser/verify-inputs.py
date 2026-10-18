"""Verify retained measurements against their exact local and HTTP inputs."""
import hashlib
import io
import json
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile

root = Path('/workspace/scratch/beryl-compiled/site-release')
here = Path(__file__).resolve().parent
record = json.loads((here / 'phase-results.json').read_text())
checks = {}
for relative, expected in record['files'].items():
    local = (root / relative).read_bytes()
    with urlopen('http://127.0.0.1:38067/beryl-compiled/site-release/' + relative) as response:
        remote = response.read()
    assert remote == local, relative
    actual = dict(bytes=len(local), sha256=hashlib.sha256(local).hexdigest())
    assert actual == expected, relative
    checks[relative] = dict(**actual, http_matches_local=True)
manifest = json.loads((root / 'release-manifest.json').read_text())
archive_data = (root / 'beryl-compiler.zip').read_bytes()
assert record['files']['beryl-compiler.zip'] == manifest['files']['beryl-compiler.zip']
with ZipFile(io.BytesIO(archive_data)) as archive:
    assert set(archive.namelist()) == set(manifest['compiler_archive_members'])
    for name, expected in manifest['compiler_archive_members'].items():
        data = archive.read(name)
        assert dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest()) == expected, name
for name, expected in record['harness_sha256'].items():
    assert hashlib.sha256((here / name).read_bytes()).hexdigest() == expected, name
result = dict(status='passed', exact_http_inputs=checks, compiler_archive_matches_manifest=True,
              all_archive_members_match_manifest=True, retained_harness_hashes_match=True)
(here / 'input-integrity.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
