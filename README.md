# beryl

beryl compiles array kernels to fast C, and proves each one before it emits it.

You write a kernel as exact integer equations over arrays, and you declare the range each
input may hold. beryl's planner proposes loop schedules. A separate checker proves each
schedule against your source: every read stays in bounds, no value overflows its type, and
the result equals what the equations say. Only a proved schedule becomes C. The planner is
untrusted, so a better or faster planner never puts correctness at risk.

The proofs work by template, so checking a kernel costs the same at 16 cells as at two
billion.

> **Status: research prototype.** Integer arithmetic on the CPU, emitted as C11, with a
> built-in thread pool. Floating point, GPUs and a PyTorch integration come next.

## An example

A quantized dense layer: u8 activations, i8 weights stored `[out, in]`, an i32 bias, and an
i8 output rounded and clamped from the sum.

```
module layer;
shape H = 1;
shape W = 256;
input x: u8[1,1024] in 0..=255;
input w: i8[W,1024] in -127..=127;
input b: i32[1,W] in -100000..=100000;
let t[r in 0..H,c in 0..W] = sum(k in 0..1024: x[0,k]*w[c,k]) + b[0,c];
output y: i8[r in 0..H,c in 0..W] = clamp(shr_round(t[r,c], 12), -128, 127);
```

Compile it to C and build an executable (Python 3.12 or newer, standard library only, and
any C11 compiler):

```sh
python tools/beryl.py check layer.ax
python tools/beryl.py native layer.ax --out layer.c --exe layer
```

`check` admits the program. `native` proves a schedule and writes `layer.c`, with a small
driver that reads the inputs as whitespace-separated integers on standard input. To call
the kernel from your own code, compile `layer.c` and call its kernel function (see
[The interface](#the-interface)).

beryl refuses the program if any value could leave its type. Here, the sum is proved to fit
i32, and the output is proved to fit i8, because the clamp comes after the shift.

## What the language covers

- **Shapes and arrays.** Two shape parameters, `H` and `W`. One to four inputs, a `let`
  producer, and one output, each a 2-D array.
- **Storage types.** u8, i8, i16 and i32 inputs, with each input in its own type. Outputs
  are u8, i8, i16, i32 or i64.
- **Arithmetic.** Exact i32 or i64, declared per equation: `+`, `*`, `min`, `max`,
  `clamp`, `shr` (floor shift) and `shr_round` (round half up), and `sum` over a range.
- **Shapes of kernels.** Stencils and filters, maps, reductions, transposes, matrix
  multiplies and dense layers.
- **Sizes.** Up to 2^31 − 1 cells per array, and up to 2^31 − 1 terms per sum.

## The input contract

Every input is checked against its declared range before any output is written. If a value
is out of range, the kernel returns the index of the first bad value plus one, counting
through the inputs in declaration order, and leaves the output untouched. Otherwise it
returns 0.

The check is fused into the computation where that is free: a single-cell sum that reads
every input checks each value as it adds it.

## The interface

- **ABI 1**, the default where it fits: `int32_t beryl_kernel(const T *input, OUT *output)`.
  The inputs are joined in declaration order in one buffer.
- **ABI 2**: `int64_t beryl_kernel_v2(const T0 *in0, ..., OUT *output)`, with one pointer
  per input, each of its own type. It is used when the inputs mix storage types or hold
  more than 2^31 − 1 cells in total. Any other program can request it, and then also keeps
  the ABI 1 entry point as a wrapper.

Large kernels split their work across a persistent thread pool. Set `BERYL_THREADS=n` to cap
it, or `BERYL_THREADS=1` to disable it. The result never depends on the thread count.

## Performance

Measured on one machine with every side built for the host CPU (`-O3 -march=native`), and
every output verified. Ratios are the baseline's time over beryl's.

| comparison | faster in | geomean |
|---|---|---|
| hand-written C with the same interface, one thread, gcc | 16 of 18 | 1.14x |
| the same, clang, medium and large sizes | 12 of 12 | 1.72x |
| C with OpenMP, four threads each | 19 of 20 | 1.87x in cache, 1.53x out of cache |

beryl loses in some cases: two mid-size image filters against gcc's hand-written C (1.29x
and 1.03x slower), a 64-value dot product against plain C, and a four-million-value dot
product at four threads against OpenMP (1.04–1.40x slower). Every case, setup, log and loss
is in the [benchmark report](docs/reviews/2026-10-25-matched-benchmarks.md).

## What is proved, and what is tested

The checker proves each schedule against the source. The C emitter is trusted, along with
a documented set of emitter optimizations, such as tiles, row accumulation and streaming
stores. Each of those is argued in the report and covered by tests:

- native runs against the reference, with bad values at the edges of every input;
- runs at one and four threads;
- runs under ThreadSanitizer, AddressSanitizer and UndefinedBehaviorSanitizer.

A reference interpreter evaluates the source equations directly, and a sampled version of
it checks chosen output cells of full-size data.

## Repository layout

| path | contents |
|---|---|
| `axiom/` | the compiler (`src/`), its tests and examples; the folder keeps an internal name |
| `tools/beryl.py` | the `beryl` command |
| `bench/` | the matched benchmark suite against C, Rust, OpenMP and Rayon |
| `docs/superpowers/specs/` | design documents, including the [roadmap](docs/superpowers/specs/2026-10-25-beryl-roadmap-design.md) |
| `docs/reviews/` | benchmark reports and reviews |

## Running the tests

```sh
cd axiom
PYTHONPATH=src python -m unittest discover -s tests -t .
```

Native tests need clang on the path; they are skipped when no compiler is found.

## License

Licensed under the [Apache License, Version 2.0](LICENSE).
