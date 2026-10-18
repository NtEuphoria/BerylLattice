# Compiled bounded execution

The user wants the bounded beryl demo to approach C/Rust execution latency. The
existing comparison compiles C/Rust before timing but starts Python and compiles,
checks and interprets beryl on each request. Both costs must remain visible.

## Compilation boundary

Admit exact immutable source bytes, decode exact immutable plan bytes and check
semantics/constraints before either backend emits code. Reuse one internal
`runtime._checked_plan(source, plan_bytes, limits)` boundary returning the fresh
kernel, decoded plan and successful check; its rejection behavior matches the
current execution entry. No saved receipt or caller-created record grants trust.

The finite v1 plan has seven opcodes. A direct C backend and a binary WebAssembly
backend lower these operations, rather than substituting the stencil formula.
Core remains the separate 4GL project and its qualification protocols stay intact.

Both backends scan every input against the admitted interval before any output
write, report the first invalid index, and preserve every initialized destination
on failure. Validity proves every intermediate fits signed i32. C uses widened
arithmetic before conversion; WebAssembly uses i32 arithmetic under this proof.
Backend storage is bounded; reject unsupported scratch allocations explicitly
without changing the declared logical workspace metric or source limits.

## Native code

`native_codegen.emit_native_c(source, plan_bytes, limits)` returns an immutable
artifact containing complete C source, dimensions and source/plan digests. The
standalone program accepts dimensions followed by exact signed-i32 inputs over
stdin and emits an output JSON array. Its callable kernel also returns status
and preserves initialized output on failure for independent boundary tests.
No input values are embedded during compilation. Clang is explicitly selected.

## Browser code

`wasm.compile_wasm(source, plan_bytes, limits)` returns an immutable module and
metadata. A fixed, owned memory contains disjoint input/output/scratch regions.
`run() -> i32` returns zero for success or first-invalid-index plus one. The
wrapper validates exact scalar types, i32 ranges and lengths before typed-array
conversion. Modules have no imports or host filesystem/network capability.

The Worker owns at most one prepared source and Wasm instance. Source edits
replace preparation; changes to inputs reuse it. Existing cancellation terminates
the worker and preparation. Python retains the admitted source evaluator and
verifies each complete observation; public reports retain comparison semantics.
Compilation and execution durations are separate fields.

## Benchmarks and acceptance

Build beryl, C and Rust before timing. Time fresh native processes over identical
varying input data and the same output transfer boundary. Audit every output
outside timing. Record source/plan/compiler/binary hashes, flags, raw samples and
compilation durations. Keep the previous full Python request scope identifiable.
Aim for native median latency within 2x of both baselines across the existing
1x1, 5x7 and 15x15 workloads; report measured failures of this target honestly.

Browser benchmarks report source-to-ready preparation separately from repeated
compiled requests. Do not compare browser time with native process time. Use
changing inputs, observable results and independent audits to prevent constant
folding/hoisting artifacts. Cold compilation must not disappear from the UI.

## Verification and release

Test all three schedules, representative dimensions, repeated changing inputs,
negative/extreme destination sentinels, first/middle/last precondition failures,
arithmetic/structural/constraint rejection and unsupported backend storage.
Execute emitted C and Wasm and compare full observations with the source evaluator
and existing interpreter. Preserve existing golden digests and boundary tests.
Run the complete Python suite, UI tests and actual Chromium under the existing CSP.

Export only the reviewed bounded demo compiler and its Wasm backend. Private Core
bindings, scalable research, recovery records and native tooling stay private.
Keep MIT notices, branding validation and manifest integrity. Publish only after
independent review and same-host C/Rust measurements.
