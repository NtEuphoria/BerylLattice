# Scratch native throughput experiment — prepared, not executed

No compilation, C execution, test suite, IR generation, or performance run has
been performed for these variants. Controller release is required before those
operations to avoid contaminating the serial browser qualification. No checkout
files or public ZIPs were modified.

## Inputs and files

Repository inspected: `/workspace/BerylLattice-o3-fixes`, HEAD
`ae61f155c289a84d0e71a4323d5a2bef358fbb1c`, clean before preparation.
Sources are the exact C artifacts in `../kernel-artifacts/manifest.json`, whose
hash and full old/new ZIP identities are recorded in this directory's manifest.
Candidate public ZIP SHA-256:
`7bbed2a5c3dde8f5916ddfe6168c735315dde974432a5fe4d25a6f0a86671757`.

Each of `15x15-cap0`, `15x15-cap128`, `5x7-cap0`, and `1x1-cap0` contains:

- `old.c`: byte-identical finite baseline control.
- `new.c`: byte-identical compact candidate control.
- `restrict.c`: compact candidate with only `restrict` added to both parameters
  of `beryl_kernel`; 18 added ASCII bytes total. This is the primary hypothesis.
- `inner-unroll4.c`: unchanged parameters, guarded Clang `unroll_count(4)` on
  every generated column loop (`ax_i_c`), including the final single row.
- `restrict-inner-unroll4.c`: both changes, to distinguish interaction.

`manifest.json` records every complete file path, byte count and SHA-256, plus
input provenance. `prepare_variants.py` is the reproducible bytes-only preparer;
it checks each source hash against its original manifest and refuses to replace
an existing different variant. It does not import the compiler package.

## Correctness argument and limits

`axiom/src/axiom/native_codegen.py:88` explicitly states that the kernel borrows
exclusively owned, disjoint, initialized int32_t arrays for the entire synchronous
call. The generated comment at `_native_kernel_parts` forbids alias, offset
views, concurrent access, and lifetime changes. The compact emitter's docstring
states that pointer ownership, preflight and rejection preservation have the
same contract as the finite emitter. The shipped standalone driver provides
separate automatic input/output arrays. The throughput driver likewise owns
separate initialized arrays and passes their base addresses.

Under that contract, every input access is derived from the input parameter,
every output access from the output parameter, and those objects are disjoint.
The scratch array, when present, is independent automatic storage. Input is not
modified. Adding parameter restrict qualifiers therefore states an existing
precondition in C11; it does not impose a new requirement on valid callers.
Parameter qualification does not change the linked symbol ABI, and the separate
throughput driver's existing unqualified prototype remains compatible.

This is not dynamic alias checking. Callers violating the documented disjoint
contract are outside the supported domain; overlapping buffers must not be used
as a positive correctness test for the restricted variant. Do not add `nonnull`,
`align`, `dereferenceable`, or new array-size assumptions based on this argument.

The restrict-only transformation leaves every preflight condition and its order,
first-invalid-index status, scratch declaration/zero initialization, widened
int64 arithmetic, signed conversions, operation order and driver byte untouched.
The original input and output preservation guarantee on rejection is unchanged
at the source level. Optimized execution and rejection-state tests are still
required before adoption; source reasoning is not runtime validation.

The unroll alternatives are compiler scheduling hints, not source-level loop
expansion. They preserve iteration order, remainder handling and dependency
semantics. They target only existing column loops; input preflight, row loops,
rolling-row update order and all storage remain unchanged. A count of four is a
bounded experiment to expose multiple independent column operations without
forcing whole-height expansion or full straight-line finite output. It can
still increase optimized IR, binary size and compilation time, especially with
other automatic optimizer decisions. Clang may ignore or combine the request.
The 1x1 pragma has no expected benefit. No speed or compile-time gain is claimed.

## Hypotheses and qualification order after controller release

Primary: LLVM noalias information could remove conservative input/output memory
dependencies and facilitate vectorization/SLP while retaining compact source.
It need not help: full preflight costs, loop choice, vector remainder handling,
and register pressure remain. The narrow unroll variants are optional follow-up
experiments if restrict alone misses the thresholds; do not select on a single
noisy sample or infer benefit from emitted source size.

The original serial 21-pair, million-call medians report candidate/baseline:
5x7-cap0 1.2294348566, 15x15-cap128 1.1013023870,
15x15-cap0 1.0211593410, 1x1-cap0 0.9632222322.
Gate: each case <=1.10 under the established measurement definition.
Native complete 15x15 compile latency must also retain the existing <=250 ms
and <=2x C baseline limits; the existing passing complete result is not evidence
for any modified variant. Kernel harness build durations alone do not establish
the complete compilation gate.

Recommended release sequence:

1. Primary restrict-only case 5x7-cap0, then 15x15-cap128, each against `old.c`.
2. If promising, qualify restrict-only 15x15-cap0 and 1x1-cap0 as well, using
   the same paired audited million-call / 21-sample protocol.
3. Only if needed, compare the optional unroll variants with the same baseline
   and protocol; remeasure selected final sources without other CPU work.
4. Inspect Clang IR to explain effects, validate optimized rejection-state and
   valid-input behavior, and rerun complete native compilation latency on any
   adopted implementation. Repeat required broader checks on final artifacts.

Use `/workspace/BerylLattice-o3-fixes/tools/measure-kernel.py` with the already
qualified compiler
`/workspace/scratch/axiom-recovery/native/toolchain/usr/lib/llvm-19/bin/clang`.
For example, after release only:

```sh
python /workspace/BerylLattice-o3-fixes/tools/measure-kernel.py \
  --baseline /workspace/scratch/beryl-fast-compilation/native-throughput-experiment/5x7-cap0/old.c \
  --candidate /workspace/scratch/beryl-fast-compilation/native-throughput-experiment/5x7-cap0/restrict.c \
  --clang /workspace/scratch/axiom-recovery/native/toolchain/usr/lib/llvm-19/bin/clang \
  --height 5 --width 7 --iterations 1000000 --samples 21 \
  --output /workspace/scratch/beryl-fast-compilation/native-throughput-experiment/restrict-5x7-cap0.json
```

The harness already compiles distinct translation units with
`-O3 -std=c11 -fno-lto`, alternates paired order and audits every replay output
against an independent formula. Keep those controls and exact source hashes.
Its valid-input throughput audit does not exercise invalid-input rejection.

## If a production change is later authorized

Keep public `emit_native_c` finite C bytes exactly stable. The shared header
builder currently promises that compatibility; changing its unconditional
signature would violate it. Any implementation must opt in only for compact
emission, leaving the default finite signature and all finite fallback output
unchanged. No implementation has been made here.

A meaningful compiler contract test should emit compact C via the actual fresh
checked-ownership path, compile with the supported Clang at `-std=c11 -O0
-S -emit-llvm` and parse the definition of `@beryl_kernel`. Require exactly the
input and output pointer parameters to carry `noalias` at that IR boundary.
The low optimization level prevents optimizer-inferred attributes from masking
a missing frontend contract. As a control, compile byte-stable finite emission
at the same level and show those parameters lack `noalias`; also assert finite
bytes/digests remain pinned. Do not count finding the word `restrict` in C or
`noalias` elsewhere in the module as proof. A deliberately removed qualifier
should make the affected pointer assertion fail. Keep any toolchain skip visible.

Combine that with optimized execution checks for valid extremes, existing
scratch plans, first/last/multiple invalid positions, input immutability and
nonzero initialized output preservation on rejection. Preserve existing memory,
widening, correspondence, preflight, and bounded-storage checks; no overlap test
should intentionally invoke C undefined behavior.
