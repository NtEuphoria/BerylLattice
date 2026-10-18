from pathlib import Path
import gzip,hashlib,json,math,statistics
BASE=Path('/workspace/scratch/beryl-fast-compilation')
SRC=BASE/'qualification-final'
DEST=Path('/workspace/BerylLattice-o3-fixes/docs/reviews/fast-compilation/implementation')
RAW=DEST/'final-qualification';RAW.mkdir(exist_ok=True)
files={}
for p in sorted(SRC.glob('*.json')):
 data=p.read_bytes();stored=p.name+'.gz';packed=gzip.compress(data,compresslevel=6,mtime=0);(RAW/stored).write_bytes(packed)
 files[p.name]=dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),stored=stored,stored_bytes=len(packed),stored_sha256=hashlib.sha256(packed).hexdigest())
(RAW/'manifest.json').write_text(json.dumps(dict(scope='Final changed-artifact qualification. All failed engineering targets are retained; process return code is not an all-targets pass.',files=files),indent=2)+'\n')
(DEST/'helpers'/'run_final_qualification.py').write_bytes((BASE/'run_final_qualification.py').read_bytes())
(DEST/'helpers'/'prepare_final_kernel_artifacts.py').write_bytes((BASE/'kernel-artifacts-final'/'prepare_artifacts.py').read_bytes())
meta=(BASE/'kernel-artifacts-final'/'manifest.json').read_bytes();(RAW/'kernel-artifact-provenance.json.gz').write_bytes(gzip.compress(meta,mtime=0))
review=Path('/workspace/BerylLattice-o3-fixes/.superpowers/sdd/fast-compilation/final-qualification-review.md');(DEST/'reviews'/review.name).write_bytes(review.read_bytes())
def load(name):return json.loads((SRC/name).read_text())
def p95(values):return sorted(values)[math.ceil(len(values)*.95)-1]
native=load('paired-native.json');direct=load('direct-builds.json');browser=load('engine-cold-browser.json')
summary=dict(revision=load('run.json')['revision'],compiler_commit='b5f7d2ecfb4f89fe3ece34bfb4cca9d7d543f989',public_archive_sha256='bdea7e03ec93d3df176ba39a9670ffc6f45f754df7f83dcb68ba2ef788b243c6',baseline_private='39dc2f6df136c643cfd030ce4470503e807750fe',baseline_public_archive_sha256='cb7304afabbfee94c4184f1c34574732f0f241c2a674222d6c3a8ee014bb6634',samples=21,native=[],browser=[],kernels=[],direct_builds={name:dict(median_ms=value['median_ms'],p95_ms=value['p95_ms']) for name,value in direct['programs'].items()},scope='Bounded stencil, <=256 input values. Baseline/candidate serial paired. Runtime/imports excluded from fresh source compilation; native includes real compiler/link. Program first execution and runtime boot are separate. Shared host, no outlier removal/retries. All table medians are descriptive, not statistical confidence intervals.')
for index,case in enumerate(native['rounds'][0]['revisions']['candidate']['cases']):
 key=case['fixture']['id'];row=dict(fixture_id=key)
 for name in ['baseline','candidate']:
  records=[x['revisions'][name]['cases'][index]['native'] for x in native['rounds']]
  values=[x['total_fresh_native_preparation_ns']/1e6 for x in records]
  row[name]=dict(median_ms=statistics.median(values),p95_ms=p95(values),source_ms=statistics.median(x['source_compilation_ns']/1e6 for x in records),clang_ms=statistics.median(x['native_compiler_link_ns']/1e6 for x in records),generated_c_bytes=records[0]['generated_c_bytes'])
 row.update(speedup=row['baseline']['median_ms']/row['candidate']['median_ms'],ratio_to_C=row['candidate']['median_ms']/direct['programs']['C']['median_ms'],ratio_to_Rust=row['candidate']['median_ms']/direct['programs']['Rust']['median_ms'])
 summary['native'].append(row)
ids=sorted({x['fixture']['id'] for x in browser['cases'].values()})
for key in ids:
 row=dict(fixture_id=key)
 for name in ['baseline','candidate']:
  case=browser['cases'][name+':'+key];values=[s['phases']['total_fresh_source_preparation']['elapsed_ms'] for s in case['samples']]
  row[name]=dict(median_ms=statistics.median(values),p95_ms=p95(values),module_bytes=case['samples'][0]['module_bytes'],module_locals=case['samples'][0]['module_locals'])
 row.update(speedup=row['baseline']['median_ms']/row['candidate']['median_ms'],within_150_ms=row['candidate']['median_ms']<=150,at_least_4x=row['baseline']['median_ms']/row['candidate']['median_ms']>=4)
 summary['browser'].append(row)
for p in sorted(SRC.glob('kernel-*.json')):
 r=json.loads(p.read_text());summary['kernels'].append(dict(case=p.stem,baseline_ns=r['programs']['baseline']['median_ns_per_run'],candidate_ns=r['programs']['candidate']['median_ns_per_run'],ratio=r['median_ratio'],guard_pass=r['median_ratio']<=1.10,p95_paired_ratio=r['p95_paired_ratio']))
summary['prepared_browser']=[dict(height=x['height'],width=x['width'],mode=x['mode'],summary=x['summary']) for x in load('prepared-browser.json')['cases']]
summary['paired_process']=[dict(id=x['id'],summary=x['summary']) for x in load('paired-process.json')['cases']]
summary['misses']=[dict(target='Native <=2x same-run C build',fixture=x['fixture_id'],actual_ratio=x['ratio_to_C']) for x in summary['native'] if x['fixture_id'].startswith('15x15') and x['ratio_to_C']>2]
summary['misses'] += [dict(target='Browser <=150ms',fixture=x['fixture_id'],actual_ms=x['candidate']['median_ms']) for x in summary['browser'] if not x['within_150_ms']]
summary['misses'] += [dict(target='Prepared verified browser <=1.10 median ratio',height=x['height'],width=x['width'],mode=x['mode'],actual_ratio=x['summary']['candidate_over_baseline']['median']) for x in summary['prepared_browser'] if not x['summary']['performance_guard_passed']]
summary['misses'] += [dict(target='Paired whole process <=1.10 median ratio',fixture=x['id'],actual_ratio=x['summary']['median_ratio']) for x in summary['paired_process'] if not x['summary']['passes_median_threshold']]
(DEST/'qualification-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({k:summary[k] for k in ['native','browser','kernels','misses']},indent=2))
