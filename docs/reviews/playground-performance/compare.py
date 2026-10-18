"""Same-host, alternating before/after whole-process request measurements."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
from time import perf_counter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.source.read_text())['cases'][0]['request']['source']
    roots = {'before': args.before.resolve(), 'after': args.after.resolve()}
    worker = ('import sys; sys.path.insert(0,sys.argv[1]); '
              'from axiom.playground_service import main; raise SystemExit(main())')
    report = dict(python=sys.version, platform=platform.platform(), machine=platform.machine(),
                  scope='Whole-process request wall time, including startup, parse, selection, fresh checks, interpretation, independent comparison and response serialization.',
                  methodology='Same host/interpreter/requests; serial alternating before/after order; one discarded warm-up and five measured new processes per version and case. External formula audit is untimed.',
                  module_hashes={name: {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                                        for p in sorted(root.rglob('*.py'))}
                                 for name, root in roots.items()}, cases=[])
    for h, w, cap in ((1, 1, 0), (5, 7, 0), (15, 15, 0), (15, 15, 64), (15, 15, 128)):
        for mode in ('ramp', 'checkerboard'):
            text = source.replace('H = 1;', f'H = {h};').replace('W = 1;', f'W = {w};')
            text = text.replace('<= 64;', f'<= {cap};')
            data = (list(range((h + 1) * (w + 1))) if mode == 'ramp' else
                    [1023 * ((r + c) % 2) for r in range(h + 1) for c in range(w + 1)])
            request = dict(source=text, input_mode='custom', inputs=data)
            payload = json.dumps(request).encode()
            expected = []
            for r in range(h):
                for c in range(w):
                    i = r * (w + 1) + c
                    expected.append(sum((data[j] + 1) ** 2 for j in (i, i + 1, i + w + 1, i + w + 2)))
            samples = {name: [] for name in roots}
            reference = None
            for iteration in range(6):
                order = ('before', 'after') if iteration % 2 == 0 else ('after', 'before')
                for name in order:
                    start = perf_counter()
                    proc = subprocess.run([sys.executable, '-I', '-c', worker, str(roots[name])],
                                          input=payload, capture_output=True, check=True, timeout=30)
                    milliseconds = (perf_counter() - start) * 1000
                    result = json.loads(proc.stdout)
                    assert result['status'] == 'success', result
                    assert result['comparison']['matches'] is True
                    assert result['input'] == data and result['output'] == expected
                    if reference is None:
                        reference = result
                    assert result == reference, (name, h, w, cap, mode)
                    if iteration:
                        samples[name].append(milliseconds)
            medians = {name: statistics.median(values) for name, values in samples.items()}
            row = dict(height=h, width=w, cap=cap, input_mode=mode,
                       request_sha256=hashlib.sha256(payload).hexdigest(), samples_ms=samples,
                       median_ms=medians, ratio=medians['before'] / medians['after'],
                       selected_plan=reference['selected']['plan_id'],
                       result_sha256=hashlib.sha256(json.dumps(reference, sort_keys=True).encode()).hexdigest(),
                       all_responses_identical=True, independent_formula_matches=True)
            report['cases'].append(row)
            print(f'{h}x{w} cap={cap} {mode}: {medians["before"]:.1f} -> {medians["after"]:.1f} ms ({row["ratio"]:.2f}x)', flush=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
