#!/usr/bin/env python3
"""Turn benchmark JSONL logs into Markdown tables, or compare two runs.

  py -3 bench/summarize.py                     # latest run in bench/results
  py -3 bench/summarize.py RUN.jsonl --write report.md
  py -3 bench/summarize.py --compare OLD.jsonl NEW.jsonl
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from catalog import KERNELS  # noqa: E402

ORDER = ('c', 'rust', 'node', 'numpy', 'python', 'axiom', 'axiom-native')


def load(path):
    header, results = None, []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        rec = json.loads(line)
        if rec['type'] == 'run':
            header = rec
        elif rec['type'] == 'result':
            results.append(rec)
    return header, results


def latest():
    runs = sorted((HERE / 'results').glob('*.jsonl'))
    if not runs:
        sys.exit('no logs in bench/results; run bench/run.py first')
    return runs[-1]


def fmt_ns(ns):
    if ns is None:
        return '-'
    for unit, scale in (('s', 1e9), ('ms', 1e6), ('us', 1e3)):
        if ns >= scale:
            return f'{ns / scale:.3g} {unit}'
    return f'{ns:.0f} ns'


def cell(rec, base):
    if rec is None:
        return ''
    status = rec['status']
    if status != 'ok':
        return {'unsupported': 'n/a', 'skipped': 'skip', 'blocked': 'blocked'}.get(status, status.upper())
    text = fmt_ns(rec['ns_median'])
    if base and rec['impl'] != 'c':
        text += f' ({rec["ns_median"] / base:.3g}x)'
    return text


def key(rec):
    return (rec['kernel'], rec['tier'], rec['pattern'], rec['impl'], rec.get('cap'), rec.get('objective'))


def report(header, results):
    out = [f'# Benchmark run {header["run_id"]}', '',
           f'- Revision: `{header["git_revision"]}` on `{header["git_branch"]}`'
           f'{" (dirty)" if header["git_dirty"] else ""}',
           f'- Platform: {header["platform"]}, {header["cpu_count"]} logical CPUs',
           f'- Toolchains: ' + ', '.join(f'{k}: {v}' for k, v in header['versions'].items() if v),
           f'- Label: {header["label"] or "(none)"}', '']
    main = [r for r in results if r['tier'] in ('s', 'm', 'l')]
    impls = [i for i in ORDER if any(r['impl'] == i for r in main)]
    out += ['## Kernel time (median per call; ratio vs C)', '',
            'Axiom = execute phase of the checked interpreter pipeline. "n/a" = Axiom cannot accept it yet.', '',
            '| kernel | size | pattern | ' + ' | '.join(impls) + ' |',
            '|---|---|---|' + '---|' * len(impls)]
    groups = defaultdict(dict)
    for r in main:
        groups[(r['kernel'], r['tier'], r['pattern'])][r['impl']] = r
    for (kernel, tier, pattern), row in groups.items():
        c = row.get('c')
        base = c['ns_median'] if c and c['status'] == 'ok' else None
        out.append(f'| {kernel} | {tier} | {pattern} | ' + ' | '.join(cell(row.get(i), base) for i in impls) + ' |')

    ax = [r for r in main if r['impl'] == 'axiom']
    if ax:
        out += ['', '## Axiom coverage', '', '| kernel | size | status | diagnostic |', '|---|---|---|---|']
        gaps = Counter()
        for r in ax:
            d = r.get('diagnostic') or {}
            if r['status'] != 'ok':
                gaps.update(d.get('missing') or KERNELS.get(r['kernel'], {}).get('missing', []))
            detail = f'{d.get("code", "")}: {d.get("message", ", ".join(d.get("missing") or []))}' if d else ''
            out.append(f'| {r["kernel"]} | {r["tier"]} | {r["status"]} | {detail} |')
        accepted = sum(r['status'] == 'ok' for r in ax)
        out += ['', f'Accepted {accepted} of {len(ax)} cases.', '',
                '### Missing features, ranked by how many cases they block', '',
                '| feature | blocked cases |', '|---|---|']
        out += [f'| {f} | {n} |' for f, n in gaps.most_common()]

    native = [r for r in results if r['impl'] == 'axiom-native' and r['status'] == 'ok']
    if native:
        base = {(r['kernel'], r['pattern'], r['impl'], r['a'], r['b']): r for r in main if r['status'] == 'ok'}
        out += ['', '## Axiom native: check once, run many', '',
                'Run = one call of the generated `beryl_kernel`, same protocol as the C/Rust kernels. '
                'Compile = Axiom admission, checked selection and C emission, plus the C compiler. '
                'Generated kernels are shape-specialized with 32-bit outputs; the C/Rust baselines '
                'take sizes at runtime and store 64-bit outputs. "Hand C" removes that difference: hand-written '
                'C with the same ABI, compile-time shape, int32 types, harness and flags.', '',
                '| case | cap | objective | plan | mults | run | hand C | vs hand C | vs C | vs Rust | Axiom check+emit | C compiler |',
                '|---|---|---|---|---|---|---|---|---|---|---|---|']
        for r in native:
            c, rust = (base.get((r['kernel'], r['pattern'], impl, r['a'], r['b'])) for impl in ('c', 'rust'))
            ratio = lambda other: f'{r["ns_median"] / other["ns_median"]:.2f}x' if other else '-'
            out.append(f'| {r["kernel"]} {r["tier"]} {r["pattern"]} | {"" if r.get("cap") is None else r["cap"]} | '
                       f'{r.get("objective") or ""} | {r["plan"]["id"]} | {r["plan"]["multiplication_ops"]} | '
                       f'{fmt_ns(r["ns_median"])} | {fmt_ns((r.get("hand_c") or {}).get("ns_median"))} | '
                       f'{ratio(r.get("hand_c"))} | {ratio(c)} | {ratio(rust)} | '
                       f'{fmt_ns(r["axiom_compile_ns"])} | {fmt_ns(r["cc_ns"])} |')

    phased = [r for r in results if r['impl'] == 'axiom' and r['status'] == 'ok']
    if phased:
        out += ['', '## Axiom pipeline phases (median)', '',
                '| case | cap | objective | plan | scratch B | mults | parse | admit | select | execute | reference | total |',
                '|---|---|---|---|---|---|---|---|---|---|---|---|']
        for r in phased:
            p, plan = r['phases_ns_median'], r['plan']
            out.append(f'| {r["kernel"]} {r["tier"]} {r["pattern"]} | {'' if r.get('cap') is None else r['cap']} | {r.get("objective") or ""} | '
                       f'{plan["id"]} | {plan["workspace_bytes"]} | {plan["multiplication_ops"]} | '
                       + ' | '.join(fmt_ns(p[k]) for k in ('parse', 'admit', 'select', 'execute', 'reference'))
                       + f' | {fmt_ns(r["pipeline_ns_median"])} |')
    rejects = [r for r in results if r['tier'] == 'reject']
    if rejects:
        out += ['', '## Axiom rejection latency', '', '| case | outcome | time to refuse |', '|---|---|---|']
        for r in rejects:
            if 'reject_ns_median' in r:
                when, what = fmt_ns(r['reject_ns_median']), (r.get('diagnostic') or {}).get('code')
            else:
                when = fmt_ns(sum((r.get('phases_ns') or {}).values()))
                what = f'{r.get("result_status")} at index {r.get("first_bad_index")}'
            out.append(f'| {r["kernel"]} ({r.get("note") or ""}) | {what} | {when} |')
    bad = [r for r in results if r['status'] in ('mismatch', 'error', 'timeout', 'blocked')]
    if bad:
        out += ['', '## Problems', '']
        out += [f'- {r["kernel"]} {r["tier"]} {r["pattern"]} {r["impl"]}: **{r["status"]}** '
                f'{(r.get("diagnostic") or {}).get("message", r.get("stderr", ""))}' for r in bad[:20]]
    return '\n'.join(out) + '\n'


def compare(old_path, new_path, threshold):
    (h0, r0), (h1, r1) = load(old_path), load(new_path)
    old = {key(r): r for r in r0}
    out = [f'# {h0["run_id"]} -> {h1["run_id"]}', '',
           f'Threshold: {threshold:.0%}. Ratio = new / old median (lower is faster).', '',
           '| case | impl | old | new | ratio | verdict |', '|---|---|---|---|---|---|']
    counts = Counter()
    for r in r1:
        o = old.get(key(r))
        if o is None:
            continue
        name = f'{r["kernel"]} {r["tier"]} {r["pattern"]}' + (f' cap={r["cap"]} {r["objective"]}' if r.get('cap') is not None else '')
        if o['status'] != r['status']:
            gained = r['status'] == 'ok' and o['status'] == 'unsupported'
            verdict = 'COVERAGE GAIN' if gained else f'STATUS {o["status"]} -> {r["status"]}'
            counts[verdict.split()[0]] += 1
            out.append(f'| {name} | {r["impl"]} | {o["status"]} | {r["status"]} | | **{verdict}** |')
            continue
        if r['status'] != 'ok':
            continue
        ratio = r['ns_median'] / o['ns_median']
        verdict = 'regression' if ratio > 1 + threshold else 'improvement' if ratio < 1 - threshold else 'same'
        counts[verdict] += 1
        if verdict != 'same':
            out.append(f'| {name} | {r["impl"]} | {fmt_ns(o["ns_median"])} | {fmt_ns(r["ns_median"])} | {ratio:.2f}x | {verdict} |')
    out += ['', 'Totals: ' + ', '.join(f'{k}: {v}' for k, v in sorted(counts.items()))]
    return '\n'.join(out) + '\n', counts['regression']


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('run', nargs='?', type=Path)
    ap.add_argument('--compare', nargs=2, type=Path, metavar=('OLD', 'NEW'))
    ap.add_argument('--threshold', type=float, default=0.10, help='relative change counted as real (default 0.10)')
    ap.add_argument('--write', type=Path, help='also write the Markdown to this path')
    args = ap.parse_args()
    if args.compare:
        text, regressions = compare(*args.compare, args.threshold)
    else:
        text, regressions = report(*load(args.run or latest())), 0
    sys.stdout.reconfigure(encoding='utf-8')
    print(text)
    if args.write:
        args.write.write_text(text, encoding='utf-8')
    return 1 if regressions else 0


if __name__ == '__main__':
    sys.exit(main())