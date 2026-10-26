#!/usr/bin/env python3
"""Sort unittest failures into known host causes and unexplained ones.

Reads `python -m unittest -v` output (a file or stdin), splits it into the
FAIL/ERROR report blocks and assigns each to the first matching cause. Anything
left over is "unexplained": a possible regression that needs a human look.
Exits 1 when an unexplained failure exists, or when --baseline is given and a
failure is missing from it.
"""
import argparse
import re
import sys
from pathlib import Path

CAUSES = [
    ('app-control', 'Windows Application Control blocked a fresh executable or a file was locked',
     # Case-insensitive: some tools lower-case the message ("[winerror 4551] an application control policy").
     re.compile(r'WinError (?:4551|5|32)\]|Application Control|being used by another process', re.I)),
    ('posix-clock', 'clock_gettime is not linked by MinGW (fixed in kernel-throughput.c)',
     re.compile(r'undefined symbol: clock_gettime')),
    ('posix-o-directory', 'os.O_DIRECTORY does not exist on Windows',
     re.compile(r"no attribute 'O_DIRECTORY'")),
    ('symlink-privilege', 'creating symlinks needs a privilege this account lacks (WinError 1314)',
     re.compile(r'WinError 1314|symbolic link privilege')),
    ('core-toolchain', 'the Core runner or toolchain is unavailable on this host',
     re.compile(r'infrastructure_error|toolchain (?:is )?unavailable|no such file.*(?:clang|cc1|ld\.lld)', re.I)),
]
# Causes the traceback cannot show, matched by test name. Each was reproduced
# on Windows; keep this list short, since a name match also hides regressions.
BY_NAME = [
    ('posix-o-directory', re.compile(r'test_cli\.CLITests\.')),  # the CLI child reports O_DIRECTORY in its JSON
    ('posix-shebang', re.compile(r'test_core_toolchain\.ToolchainNegativeTests\.')),  # '#!' fake compilers cannot run
]
BLOCK = re.compile(r'^={50,}\n(FAIL|ERROR): (\S+) \(([^)]*)\)[^\n]*\n-{50,}\n(.*?)(?=^={50,}\n|^-{50,}\nRan )',
                   re.M | re.S)


def classify(text):
    results = []
    for kind, name, where, body in BLOCK.findall(text):
        test = f'{where}.{name}' if '.' not in where else where
        cause = next((key for key, _, pattern in CAUSES if pattern.search(body)), None)
        cause = cause or next((key for key, pattern in BY_NAME if pattern.search(test)), 'unexplained')
        last = next((line for line in reversed(body.strip().splitlines()) if line.strip()), '')
        results.append({'kind': kind, 'test': test, 'cause': cause, 'last_line': last.strip()[:160]})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('log', nargs='?', help='unittest -v output (default: stdin)')
    parser.add_argument('--baseline', help='file of known failing test lines from an earlier run')
    args = parser.parse_args()
    text = Path(args.log).read_text(encoding='utf-8', errors='replace') if args.log else sys.stdin.read()
    results = classify(text.replace('\r\n', '\n'))
    labels = {key: label for key, label, _ in CAUSES}
    labels['posix-shebang'] = "'#!' scripts used as fake compilers cannot run on Windows (matched by test name)"
    labels['unexplained'] = 'no known host cause: possible regression'
    for key in [*labels]:
        group = [r for r in results if r['cause'] == key]
        if group:
            print(f'{key}: {len(group)}  ({labels[key]})')
            if key == 'unexplained':
                for r in group:
                    print(f'  {r["kind"]} {r["test"]}\n      {r["last_line"]}')
    new = []
    if args.baseline:
        known = Path(args.baseline).read_text(encoding='utf-8', errors='replace')
        new = [r for r in results if r['test'].rsplit('.', 1)[-1] not in known]
        print(f'not in baseline: {len(new)}')
        for r in new:
            print(f'  {r["kind"]} {r["test"]} [{r["cause"]}]')
    summary = re.search(r'^Ran (\d+) tests?.*?\n\n(\w+.*)$', text, re.M | re.S)
    if summary:
        print(f'ran {summary.group(1)} tests: {summary.group(2).strip()}')
    return 1 if any(r['cause'] == 'unexplained' for r in results) or new else 0


if __name__ == '__main__':
    sys.exit(main())
