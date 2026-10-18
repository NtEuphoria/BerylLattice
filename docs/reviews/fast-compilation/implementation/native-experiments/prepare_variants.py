#!/usr/bin/env python3
"""Prepare bytes only; never compile, execute generated C, or measure."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'kernel-artifacts'
manifest_bytes = (SOURCE / 'manifest.json').read_bytes()
source_manifest = json.loads(manifest_bytes)
old_signature = b'int32_t beryl_kernel(const int32_t *input, int32_t *output) {'
restrict_signature = b'int32_t beryl_kernel(const int32_t *restrict input, int32_t *restrict output) {'
inner = re.compile(rb'^(    +)(for \(int32_t ax_i_c = [^\n]+\{)$', re.MULTILINE)

def restrict(data):
    assert data.count(old_signature) == 1
    changed = data.replace(old_signature, restrict_signature, 1)
    assert changed.replace(restrict_signature, old_signature, 1) == data
    return changed

def unroll4(data):
    def replacement(match):
        indent, loop = match.groups()
        return (b'#if defined(__clang__)\n' + indent +
                b'#pragma clang loop unroll_count(4)\n#endif\n' + indent + loop)
    changed, count = inner.subn(replacement, data)
    assert count >= 1
    return changed, count

result = {
    'schema': 'beryl-native-throughput-scratch-experiment-v1',
    'created_utc': datetime.now(timezone.utc).isoformat(),
    'status': 'prepared-only; no compilation, tests, execution, or performance measurement',
    'repository_head_observed': 'ae61f155c289a84d0e71a4323d5a2bef358fbb1c',
    'source_manifest_path': str(SOURCE / 'manifest.json'),
    'source_manifest_sha256': sha256(manifest_bytes).hexdigest(),
    'source_zips': source_manifest['zips'],
    'preparer_path': str(Path(__file__).resolve()),
    'preparer_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
    'cases': [],
}
for case in source_manifest['cases']:
    directory = HERE / case['case_id']
    directory.mkdir(exist_ok=True)
    old, new = (Path(case[key]['c_path']).read_bytes() for key in ('old', 'new'))
    for key, data in [('old', old), ('new', new)]:
        assert sha256(data).hexdigest() == case[key]['c_sha256']
    unrolled, count = unroll4(new)
    variants = {'old.c': old, 'new.c': new, 'restrict.c': restrict(new),
                'inner-unroll4.c': unrolled,
                'restrict-inner-unroll4.c': restrict(unrolled)}
    entry = {'case_id': case['case_id'], 'expected_plan': case['expected_plan'],
             'metrics': case['metrics'], 'unroll_pragma_count': count, 'files': {}}
    for name, data in variants.items():
        path = directory / name
        if path.exists():
            assert path.read_bytes() == data, f'refusing to overwrite different bytes: {path}'
        else:
            path.write_bytes(data)
        entry['files'][name] = {'path': str(path), 'sha256': sha256(data).hexdigest(), 'bytes': len(data)}
    result['cases'].append(entry)
(HERE / 'manifest.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({'directory': str(HERE), 'cases': len(result['cases']),
                  'variant_files': sum(len(c['files']) for c in result['cases']),
                  'manifest_sha256': sha256((HERE / 'manifest.json').read_bytes()).hexdigest()}, indent=2))
