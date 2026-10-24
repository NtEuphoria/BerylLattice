"""Public Axiom JSON commands; all compiler logic stays in its owner module."""
import argparse
from pathlib import Path
import sys

from .codec import DecodeError, canonical_json, strict_json_loads
from .evidence import MANIFEST_BYTES, json_record, replay, verify_references, write_attempt
from .frontend import admit_source, parse_source
from .model import DiagnosticError, Limits
from .reference import ExecutionStatus, evaluate_source
from .selection import SearchStop, select_plan


class _UsageError(ValueError):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _UsageError(message)


def _nonnegative(text):
    if not text.isascii() or not text.isdecimal() or len(text)>10:
        raise argparse.ArgumentTypeError('expected a nonnegative decimal integer of at most ten digits')
    value=int(text)
    if value>9999999999:
        raise argparse.ArgumentTypeError('integer exceeds CLI quota')
    return value


def _cap(text):
    value=_nonnegative(text)
    if value>2147483647:
        raise argparse.ArgumentTypeError('cap must be at most 2147483647')
    return value


def _read(path, maximum):
    with Path(path).open('rb') as stream:
        data=stream.read(maximum+1)
    if len(data)>maximum:
        raise _UsageError('file exceeds byte quota: '+str(path))
    return data


def _source(args):
    limits=Limits()
    module=parse_source(_read(args.source,limits.source_bytes),limits)
    return module,admit_source(module),limits


def _check(args):
    _,kernel,_=_source(args)
    return 0,{'status':'admitted','source_digest':kernel.source_digest,
              'semantic_digest':kernel.semantic_digest,'height':kernel.height,'width':kernel.width,
              'source_cap':kernel.cap,'objective':kernel.objective.value}


def _plan(args):
    module,kernel,limits=_source(args)
    result=select_plan(kernel,limits,args.check_steps,kernel.objective,args.optional_check_steps)
    path=write_attempt(Path(args.out),module,result)
    selected=result.selected_plan
    code=0 if selected is not None else 4
    if selected is None and result.termination_reason in (SearchStop.CHECKER_ERROR,SearchStop.CANDIDATE_ERROR,SearchStop.CANCELLED):
        code=5
    return code,{'status':'eligible' if selected is not None else 'no_eligible_plan',
                 'artifact_state':result.artifact_state.value,'termination_reason':result.termination_reason.value,
                 'reason':result.reason,'selected_plan_id':None if selected is None else selected.plan_id,
                 'selected_key':json_record(result.selected_key),'check':json_record(result.selected_check),
                 'total_work_used':result.total_work_used,'optional_work_used':result.optional_work_used,
                 'manifest':str(path)}


def _replay(args):
    limits=Limits()
    source=_read(args.source,limits.source_bytes)
    plan_bytes=_read(args.plan,limits.plan_bytes)
    manifest_bytes=_read(args.manifest,MANIFEST_BYTES)
    checked=replay(source,plan_bytes,manifest_bytes,limits,args.cap)
    verify_references(Path(args.manifest).parent,source,plan_bytes,manifest_bytes)
    return (0 if checked.eligible else 4),{'status':'eligible' if checked.eligible else 'ineligible',
                                         'check':json_record(checked)}


def _eval(args):
    module,_,_=_source(args)
    # Source cells <=256, output cells <256. JSON quotas are independent of
    # checker work; the evaluator validates exact shape and scalar i32 values.
    data=strict_json_loads(_read(args.input,65536),max_bytes=65536,max_items=256,max_depth=2)
    initial=strict_json_loads(_read(args.output_initial,65536),max_bytes=65536,max_items=256,max_depth=2)
    result=evaluate_source(module,data,initial)
    return (0 if result.status==ExecutionStatus.SUCCESS else 6),{'status':result.status.value,
                                                              'execution':json_record(result)}


def _native(args):
    """Compile source to checked native C, and optionally to an executable."""
    import os
    import subprocess
    from .source_compilation import compile_native_source
    limits=Limits()
    source=_read(args.source,limits.source_bytes)
    compiled=compile_native_source(source,limits)
    artifact=compiled.artifact
    if artifact is None:
        return 4,{'status':'no_eligible_plan','termination_reason':compiled.search.termination_reason.value,
                  'reason':compiled.search.reason}
    out=Path(args.out)
    if out.exists() and not args.force:
        raise _UsageError('output exists (use --force to replace): '+str(out))
    out.write_bytes(artifact.c_source)
    kernel=compiled.kernel
    result={'status':'compiled','c':str(out),'family':kernel.profile,'codegen_version':artifact.codegen_version,
            'parallel':artifact.codegen_version.endswith('parallel-v1'),
            'height':kernel.height,'width':kernel.width,
            'input_count':artifact.input_count,'output_count':artifact.output_count,
            'c_sha256':artifact.c_digest}
    if args.exe:
        command=[args.cc,'-O3','-std=c11',str(out),'-o',args.exe]
        if os.name!='nt' and result['parallel']:
            command.insert(1,'-pthread')
        built=subprocess.run(command,capture_output=True,text=True)
        if built.returncode!=0:
            return 5,{**result,'status':'cc_failed','cc':command,'stderr':built.stderr[-2000:]}
        result.update(exe=args.exe,
                      usage=f'{args.exe} < input.txt  (stdin: "{kernel.height} {kernel.width}" then '
                            f'{artifact.input_count} integers; prints the {artifact.output_count} outputs as JSON)')
    return 0,result


def _parser():
    parser=_Parser(prog='axiom',description='Bounded Axiom correctness prototype')
    commands=parser.add_subparsers(dest='command',required=True,parser_class=_Parser)
    p=commands.add_parser('check',help='parse and admit one source snapshot')
    p.add_argument('source'); p.set_defaults(handler=_check)
    p=commands.add_parser('plan',help='independently check and rank the fixed portfolio')
    p.add_argument('source'); p.add_argument('--out',required=True)
    p.add_argument('--check-steps',type=_nonnegative,default=100000)
    p.add_argument('--optional-check-steps',type=_nonnegative)
    p.set_defaults(handler=_plan)
    p=commands.add_parser('replay',help='freshly check exact recorded source and plan')
    p.add_argument('source'); p.add_argument('plan'); p.add_argument('--manifest',required=True)
    p.add_argument('--cap',type=_cap); p.set_defaults(handler=_replay)
    p=commands.add_parser('eval',help='evaluate original source through its checked boundary')
    p.add_argument('source'); p.add_argument('--input',required=True); p.add_argument('--output-initial',required=True)
    p.set_defaults(handler=_eval)
    p=commands.add_parser('native',help='compile to checked native C (and an executable with --exe)')
    p.add_argument('source'); p.add_argument('--out',required=True); p.add_argument('--exe')
    p.add_argument('--cc',default='clang'); p.add_argument('--force',action='store_true')
    p.set_defaults(handler=_native)
    p=commands.add_parser('witness',help='build and observe one exact checked fixed-plan Core witness')
    p.add_argument('source'); p.add_argument('--plan',required=True); p.add_argument('--case',required=True)
    p.add_argument('--clang',required=True); p.add_argument('--core',required=True); p.add_argument('--out',required=True)
    p.add_argument('--lane',choices=('reference','ast','ir'),default='ast'); p.add_argument('--release',action='store_true')
    from .core_capsule import witness_command, conformance_command
    p.set_defaults(handler=witness_command)
    p=commands.add_parser('conformance',help='run exact embedded cases against an independently evaluated oracle')
    p.add_argument('--manifest',required=True); p.add_argument('--toolchain',required=True); p.add_argument('--out',required=True)
    p.add_argument('--workers',type=int,choices=(1,2,3,4),default=4)
    p.set_defaults(handler=conformance_command)
    return parser


def main(argv=None):
    try:
        args=_parser().parse_args(argv)
        code,result=args.handler(args)
    except (_UsageError,DiagnosticError,DecodeError,ValueError) as error:
        diagnostic=getattr(error,'code','INVALID_INPUT')
        code=3 if diagnostic.startswith('UNSUPPORTED_') else 2
        if diagnostic=='NO_REPLAY_ARTIFACT': code=4
        result={'status':'unsupported' if code==3 else 'no_eligible_plan' if code==4 else 'invalid',
                'diagnostic':{'code':diagnostic,'message':str(error)}}
        if hasattr(error,'span'):
            result['diagnostic']['span']=json_record(error.span)
        if hasattr(error,'field_path'):
            result['diagnostic']['field_path']=error.field_path
    except (Exception,KeyboardInterrupt) as error:
        code=5
        result={'status':'infrastructure_failure','diagnostic':{'code':type(error).__name__,'message':str(error)}}
    print(canonical_json(result).decode('utf-8'))
    return code


if __name__=='__main__':
    sys.exit(main())
