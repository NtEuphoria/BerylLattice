"""Serial qualification; run only after full-suite completion and idle test jobs."""
import hashlib,json,os,platform,subprocess,time
from pathlib import Path
ROOT=Path('/workspace/BerylLattice-o3-fixes')
OUT=Path('/workspace/scratch/beryl-fast-compilation')
CC='/workspace/scratch/axiom-recovery/native/toolchain/usr/lib/llvm-19/bin/clang'
RUST='/workspace/scratch/beryl-compiled/rust-toolchain/installed/bin/rustc'
OLD='/workspace/scratch/beryl-compiled/site-release'
NEW=str(OUT/'candidate-final')
steps=[
('paired-native',['python3','tools/profile-compilation.py','--repo',str(ROOT),'--baseline-repo',str(OUT/'baseline'),'--baseline-revision','39dc2f6df136c643cfd030ce4470503e807750fe','--samples','21','--diagnostics','--cc',CC,'--output',str(OUT/'paired-native-final.json')]),
('direct-builds',['python3',str(OUT/'measure_direct_builds.py'),'--repo',str(ROOT),'--cc',CC,'--rustc',RUST,'--samples','21','--output',str(OUT/'direct-builds-final.json')]),
('public-process',['python3','tools/compare-playground.py','--cc',CC,'--rustc',RUST,'--compiler-archive',NEW+'/beryl-compiler.zip','--samples','21','--output',str(OUT/'public-process-final.json')]),
]
for case,h,w in [('15x15-cap0',15,15),('15x15-cap128',15,15),('5x7-cap0',5,7),('1x1-cap0',1,1)]:
    p=OUT/'kernel-artifacts'/case
    steps.append(('kernel-'+case,['python3','tools/measure-kernel.py','--baseline',str(p/'old.c'),'--candidate',str(p/'new.c'),'--clang',CC,'--height',str(h),'--width',str(w),'--iterations','1000000','--samples','21','--output',str(OUT/('kernel-'+case+'-final.json'))]))
steps += [
('prepared-browser',['node',str(OUT/'measure-prepared-browser.cjs'),'--baseline-url','http://127.0.0.1:38067/beryl-compiled/site-release/','--baseline-site',OLD,'--candidate-url','http://127.0.0.1:38067/beryl-fast-compilation/candidate-final/','--candidate-site',NEW,'--samples','21','--output',str(OUT/'prepared-browser-final.json')]),
('engine-cold-browser',['node','tools/benchmarks/compilation.cjs','--site',NEW,'--baseline-site',OLD,'--mode','engine-cold','--samples','21','--diagnostics','--output',str(OUT/'engine-cold-browser-final.json')]),
]
assert not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip(), 'Qualification requires a clean tree'
assert not (OUT/'qualification-run.json').exists()
report=dict(scope='Serial controlled paired qualification, after full test suite. Runtime/imports/filesystem/compiler infrastructure warm where explicitly stated by each tool; fresh user source/compiler process/browser profile scopes remain distinct. Shared host external load uncontrolled.',created_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),working_tree_clean=True,host=platform.platform(),load_average_start=os.getloadavg(),steps=[])
report_path=OUT/'qualification-run.json'
def save():report_path.write_text(json.dumps(report,indent=2)+'\n')
save()
for name,command in steps:
    log=OUT/(name+'-final.log')
    entry=dict(name=name,command=command,log=str(log),started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),load_average_start=os.getloadavg())
    report['steps'].append(entry);save()
    print('START',name,entry['started_utc'],flush=True)
    started=time.monotonic()
    with log.open('x') as stream:
        result=subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
    entry.update(returncode=result.returncode,elapsed_seconds=time.monotonic()-started,finished_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(),load_average_finish=os.getloadavg())
    save();print('FINISH',name,result.returncode,round(entry['elapsed_seconds'],2),flush=True)
    if result.returncode and name!='prepared-browser':
        report['status']='blocked';save();raise SystemExit(result.returncode)
report['status']='complete';report['load_average_finish']=os.getloadavg();save()
