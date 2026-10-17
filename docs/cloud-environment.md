# Cloud environment setup

Run the tracked setup script from any working directory:

```sh
bash /workspace/BerylLattice/tools/setup-cloud.sh
```

Python 3.12 or newer and Bash are the only portable prerequisites. Set
`PYTHON=/path/to/python3` to select Python explicitly. Axiom uses the Python
standard library; no pip installation, package index, virtual environment or
third-party dependency is required. The script sets `PYTHONPATH` for its own
process and checks `axiom/examples/stencil.ax`. This default check is small;
the full portable suites and exhaustive selection suite are separate commands
in the repository README.

Suggested cloud environment `install_script`:

```sh
bash /workspace/BerylLattice/tools/setup-cloud.sh
```

Save this as an environment configuration draft for review. A local commit or
local file alone does not prove a fresh task can restore the script: the selected
repository revision must contain it. This procedure does not publish a repository
revision or prove a fresh-task restoration.

## Optional native qualification

```sh
bash /workspace/BerylLattice/tools/setup-cloud.sh --native \
  --core /workspace/beryl --prefix /workspace/BerylLattice/.local/cloud
```

Core must be a clean checkout, including untracked files, at exactly
`0a678b4ae6d41190c4f5a8bf063caba05759d20d`. The script never builds inside that
checkout. Each invocation retains a new `qualification-*` directory containing
a disposable snapshot and receipts; it does not overwrite earlier qualifications.
No Core source, dependency file or global compiler selection is changed.

Without `--clang`, the script reuses its private toolchain when present or
bootstraps the six pinned Debian packages below into `PREFIX/toolchain`.
Bootstrap supports the current Debian 13 amd64 image and requires existing
`gcc-14`, `libgcc-14-dev`, `libstdc++-14-dev`, `libc6-dev`, `libllvm19`, and
`binutils` development packages, plus Git, Bash, ldd, APT, dpkg-deb, the Debian
archive keyring, and the system CA bundle. Missing prerequisites fail setup;
the script does not install system packages or use sudo.

| Packages | Exact version |
| --- | --- |
| clang-19, libclang-common-19-dev, libclang-cpp19, llvm-19-linker-tools | 1:19.1.7-3+b1 |
| libobjc-14-dev, libobjc4 | 14.2.0-19 |

APT uses a private configuration with HTTPS `deb.debian.org/debian trixie main`,
signed Debian archive metadata, verified package checksums, and the system CA
bundle. TLS, signatures and authentication remain enabled. The script also
checks each package's pinned SHA256, name, version and architecture before any
extraction. Exact hashes are in `tools/setup-cloud.sh`; downloads, APT metadata,
APT log, host package versions and a package receipt remain in the new evidence
directory. Packages are extracted rootlessly, outside the system dpkg database.
If these exact versions leave the signed mirror, setup fails; it never selects
new versions automatically. Existing incomplete or mismatched installations
fail closed; use a new prefix to retry without deleting evidence.

To reuse the already selected installation explicitly:

```sh
bash /workspace/BerylLattice/tools/setup-cloud.sh --native \
  --core /workspace/beryl --prefix /workspace/BerylLattice/.local/cloud \
  --clang /workspace/scratch/axiom-toolchain-setup/toolchain/usr/lib/llvm-19/bin/clang
```

All reuse paths require Clang SHA256
`0a3c55936ac43954fbe4914e6e73b577ca9e35e75d89ef13d3e28c187f41ca1a`
and its exact adjacent `clang.cfg` containing four bytes `-lm\n`, SHA256
`bc3624e157ba6656818d5f16c70efcd0c5414ffc8f354dce80aa76d639f9587f`.
Additional discovered Clang configuration files fail setup. The math-library
configuration supplies the Linux `-lm` omitted by the pinned Core build scripts.

The script calls the public `inspect_toolchain`, `prepare_snapshot`, and
`build_core` APIs. Actual C11 compilation/execution, Core build, Core unit suite,
native witness execution, LLVM IR, assembly, and driver-job evidence capture
are mandatory for `--native`. The final receipt is printed as
`qualification-*/receipts/toolchain.json`; `setup.json` records the selected
bootstrap/reuse branch. Command receipts preserve return codes and diagnostics;
failures retain `setup-failure.json`. Reuse a retained qualification through
`axiom.core_toolchain.load_toolchain` and revalidate its identities before use.

The pinned Core unit suite has a known failure: two of 10814 checks across 583
cases fail in `IR: initialized SET destination remains readable during later
scalar capture`, with BE0401 overlapping exclusive borrows of `n`. The API admits
only that exact known failure pattern, retains unit exit 1, and records
`unit_status=known_pinned_baseline_failure`. Setup can finish after successful
native qualification with this explicit status; it never reports a green unit
suite. Any unexpected unit failure blocks qualification.

Executable and configuration hashes and known loaded compiler libraries are
recorded. The current image supplies runtime libraries, headers, GCC support,
linker and SDK components; their complete transitive identity is not established.
A successful qualification demonstrates this local Core/toolchain capability,
not Axiom conformance, performance admission, or portability to a different image.
Core source fingerprints include paths and differ from binary-byte hashes.
See [the Core bridge guide](../axiom/docs/core-bridge.md) for the receipt contract.
