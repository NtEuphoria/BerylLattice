from pathlib import Path
from hashlib import sha256
import json
from axiom.source_compilation import compile_native_source
from axiom.native_codegen import emit_native_c

root = Path('/workspace/scratch/beryl-fast-compilation/native-throughput-experiment')
manifest = json.loads((root.parent/'kernel-artifacts/manifest.json').read_bytes())
records = []
for case in manifest['cases']:
    original = root.parent/'kernel-artifacts'/case['case_id']
    source = (original/'source.bryl').read_bytes()
    result = compile_native_source(source)
    assert result.hint_failure is None
    assert result.artifact.codegen_version == 'beryl-bounded-loop-c-v1'
    # Public namespace changes the semantic digest, so compare final C bytes.
    compact = result.artifact.c_source
    probe = (root/case['case_id']/'restrict-preflight-reduction.c').read_bytes()
    assert compact == probe
    finite = emit_native_c(source, result.search.selected_plan_bytes).c_source
    # The public archive's existing namespace transformation changes the finite
    # generated banner. Account for that exact banner only, never normalize code.
    public_finite = finite.replace(b'/* Generated from a freshly checked finite Axiom physical plan. */',
                                  b'/* Generated from a freshly checked finite beryl physical plan. */', 1)
    old = (original/'old.c').read_bytes()
    assert public_finite == old, (case['case_id'], public_finite[:100], old[:100])
    records.append({'case_id':case['case_id'], 'compact_equals_measured_probe':True,
                    'compact_sha256':sha256(compact).hexdigest(),
                    'finite_public_bytes_unchanged':True,
                    'finite_public_sha256':sha256(public_finite).hexdigest()})
(root/'production-byte-check.json').write_text(json.dumps(records,indent=2)+'\n')
print(json.dumps(records,indent=2))
