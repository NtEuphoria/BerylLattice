#!/usr/bin/env python3
"""Start the bundled local Axiom playground without installing a package."""
from pathlib import Path
import sys

if sys.version_info < (3, 12):
    raise SystemExit('Axiom requires Python 3.12 or newer.')

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'axiom' / 'src'))

from axiom.playground import main

if __name__ == '__main__':
    main()
