"""Final serial qualification after b5f7d2e; no concurrent test/timing jobs."""
import hashlib,json,os,platform,subprocess,time
from pathlib import Path
ROOT=Path('/workspace/BerylLattice-o3-fixes')
BASE=Path('/workspace/scratch/beryl-fast-compilation')
OUT=BASE/'qualification-final';OUT.mkdir(exist_ok=True)
CC='/workspace/scratch/axiom-recovery/native/toolchain/usr/lib/llvm-19/bin/clang'
RUST='/workspace/scratch/beryl-compiled/rust-toolchain/installed/bin/rustc'
OLD='/workspace/scratch/beryl-compiled/site-release'
NEW=str(BASE/'candidate-native-final')
steps=[
('paired-native',['python3','tools/profile-compilation.py','--repo',str(ROOT),'--baseline-repo',str(BASE/'baseline'),'--baseline-revision','39dc2f6df136c643cfd030ce4470503e807750fe','--samples','21','--diagnostics','--cc',CC,'--output',str(OUT/'paired-native.json')]),
('direct-builds',['python3',str(BASE/'measure_direct_builds.py'),'--repo',str(ROOT),'--cc',CC,'--rustc',RUST,'--samples','21','--output',str(OUT/'direct-builds.json')]),
('public-process',['python3','tools/compare-playground.py','--cc',CC,'--rustc',RUST,'--compiler-archive',NEW+'/beryl-compiler.zip','--samples','21','--output',str(OUT/'public-process.json')]),
]
for case,h,w in [('15x15-cap0',15,15),('15x15-cap128',15,15),('5x7-cap0',5,7),('1x1-cap0',1,1)]:
 p=BASE/'kernel-artifacts-final'/case
 steps.append(('kernel-'+case,['python3','tools/measure-kernel.py','--baseline',str(p/'old.c'),'--candidate',str(p/'new.c'),'--clang',CC,'--height',str(h),'--width',str(w),'--iterations','1000000','--samples','21','--output',str(OUT/('kernel-'+case+'.json'))]))
steps += [
('paired-process',['python3',str(BASE/'measure-paired-process.py'),'--artifacts',str(BASE/'kernel-artifacts-final'),'--cc',CC,'--samples','21','--output',str(OUT/'paired-process.json')]),
('prepared-browser',['node',str(BASE/'measure-prepared-browser.cjs'),'--baseline-url','http://127.0.0.1:38067/beryl-compiled/site-release/','--baseline-site',OLD,'--candidate-url','http://127.0.0.1:38067/beryl-fast-compilation/candidate-native-final/','--candidate-site',NEW,'--samples','21','--output',str(OUT/'prepared-browser.json')]),
('engine-cold-browser',['node','tools/benchmarks/compilation.cjs','--site',NEW,'--baseline-site',OLD,'--mode','engine-cold','--samples','21','--diagnostics','--fixture-id','15x15-cap64-multiplication_ops','--fixture-id','15x15-cap128-multiplication_ops','--output',str(OUT/'engine-cold-browser.json')]),
]
assert not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip(), 'Requires clean tree'
path=OUT/'run.json';assert not path.exists()
report=dict(scope='Final serial controlled paired qualification after all functional checks and independent native review; fresh compiler/user sources, runtime-ready cold-browser profiles and prepared executions have distinct scopes. Shared host external load uncontrolled.',created_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),clean=True,host=platform.platform(),load_average_start=os.getloadavg(),steps=[])
def save():path.write_text(json.dumps(report,indent=2)+'\n')
save()
for name,command in steps:
 entry=dict(name=name,command=command,started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),load_average_start=os.getloadavg());report['steps'].append(entry);save()
 print('START',name,entry['started_utc'],flush=True)
 started=time.monotonic();log=OUT/(name+'.log')
 with log.open('x') as stream:result=subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
 entry.update(returncode=result.returncode,elapsed_seconds=time.monotonic()-started,finished_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(),load_average_finish=os.getloadavg());save()
 print('FINISH',name,result.returncode,round(entry['elapsed_seconds'],2),flush=True)
 if result.returncode and name not in ('paired-process','prepared-browser'):
  report['status']='blocked';save();raise SystemExit(result.returncode)
report.update(status='complete',load_average_finish=os.getloadavg());save()
