# Beryl Lattice

[Try the Axiom playground](https://nteuphoria.github.io/axiom-playground/).

Project Axiom is the experimental constraint-directed language developed by Lattice. Lattice Core remains the separate Beryl 4GL compiler.

The initial implementation lives in `axiom/`. A programmer declares a two-stage stencil, an optional scratch-space constraint and an arithmetic objective. Axiom constructs three schedules, checks their actual operations independently and retains an eligible plan with replayable evidence.

Try the local web playground with `python3 tools/run-playground.py` (Python3.12+).
It runs the selected checked plan and compares every result with the independent
source evaluator. The [playground guide](axiom/docs/playground.md) includes setup,
a presentation walkthrough and the exact supported language scope. No Core build,
package installation or internet connection is needed to run the demo.
For static hosting, `python3 tools/build-playground-site.py --output /tmp/axiom-site`
builds a browser version with the same Python compiler and a pinned bundled
runtime. The first build downloads the runtime; the generated release manifest
lists the exact source and assets that a public upload would disclose.

The prototype supports fixed shapes with at most 256 input cells and checked i32 arithmetic. Its workspace metric measures the reserved plan scratch arena; it excludes scalar temporaries and native memory. Native Core witnesses are fixed-case correctness experiments. They establish neither a reusable native ABI nor a speedup.

Start with Python 3.12 or newer; the implementation uses only the standard library:

```sh
cd axiom
PYTHONPATH=src python -m axiom check examples/stencil.ax
PYTHONPATH=src python -m axiom plan examples/stencil.ax --out artifacts/demo --check-steps 100000
```

The [prototype guide](axiom/docs/prototype.md) documents exact replay, evaluation, work budgets, diagnostics and the trusted components. The [Core bridge guide](axiom/docs/core-bridge.md) covers the pinned compiler, executable witnesses, complete observations and native prerequisites.

Use the [cloud setup guide](docs/cloud-environment.md) for environment preparation. The [implementation record](docs/implementation-record.md) tracks validation, implementation decisions and remaining research gates.

Run the suites from `axiom/` in this configured cloud workspace:

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
cd research
PYTHONPATH=. python -m unittest discover -s tests -v
```

Native integration requires an explicitly selected Core checkout and Clang toolchain; missing prerequisites are reported as unavailable. The selection suite also enumerates all 955 admitted shapes and can take several minutes. Native cases and synthetic research fixtures have separate provenance.

The research adapter fixtures use the unchanged evaluator at `/workspace/beryl/tools/beryl-experiments/evaluate.py` and `/usr/bin/python3`, whose executable must fit the protocol's 16 MiB file limit. The state, manifest and receipt suites run independently of those fixture prerequisites.

Research evidence formats are documented under [research/protocol](axiom/research/protocol). Large-buffer lowering, a loop-plan checker, a reviewed native collector and an independent scalable oracle remain research gates. Native performance admission stays unavailable until those gates are established.
