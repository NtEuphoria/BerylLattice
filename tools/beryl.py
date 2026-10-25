#!/usr/bin/env python3
"""The beryl command: the compiler CLI under its public name.

    python tools/beryl.py check program.ax
    python tools/beryl.py native program.ax --out kernel.c --exe kernel.exe

Only the program name and description in usage text change; commands,
arguments, exit codes and JSON results are the compiler's own.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'axiom' / 'src'))
from axiom import __main__ as cli  # noqa: E402

_build = cli._parser


def _public_parser():
    parser = _build()
    parser.prog, parser.description = 'beryl', 'beryl: checked, fast array kernels'
    for action in parser._subparsers._group_actions:
        for name, sub in action.choices.items():
            sub.prog = f'beryl {name}'
    return parser


cli._parser = _public_parser

if __name__ == '__main__':
    sys.exit(cli.main(sys.argv[1:]))
