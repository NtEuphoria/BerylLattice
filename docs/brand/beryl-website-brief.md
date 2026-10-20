# beryl: website brief

This brief is for a designer or developer building a showcase website for **beryl** in the style of
an Awwwards Site of the Day. It is self-contained: everything you need to know about what beryl is,
how it works, what is true about it today, and how it should feel is below. Every number in it was
measured; keep claims within what this document says (see "Claims guardrails").

Always write the name in lowercase: **beryl**.

---

## 1. One-line positioning

> **beryl: say what to compute. beryl finds the fastest way, proves it right, then runs it.**

Alternates for the hero:
- "Describe the math. Get proven-correct native code."
- "Fast code you never have to trust."
- "Every plan, checked against your source, before it runs."

## 2. What beryl is

beryl is an experimental **declarative language and compiler for array computations**: stencils,
convolutions, reductions, matrix products, element-wise maps and transposes over grids of integers.

You write what each output cell *is*, as a formula over input cells. You do not write loops,
buffers, scheduling or memory management. You may also state a storage limit
(`require plan_workspace_bytes <= 128;`) and a goal (`prefer multiplication_ops;`).

beryl then:

1. **Admits** the program. It checks that the program is well-formed and within a family it knows
   how to prove. If not, the rejection names the broken rule and points at the exact characters in
   your source.
2. **Plans.** It generates several candidate execution plans: recompute everything, keep a rolling
   window of rows, or store an intermediate grid. It ranks them by your goal and storage limit.
3. **Proves.** An **independent checker**, separate from the planner, verifies the chosen plan
   against your source:
   - every output is exactly the formula you wrote (same operations, same grouping, no algebraic
     shortcuts);
   - every memory read is in bounds;
   - no 32-bit integer operation can overflow for any allowed input.

   The planner is never trusted; only the checker's verdict lets a plan run.
4. **Runs.** The proven plan is compiled to **native C** (built by clang) or **WebAssembly** (in the
   browser playground).
   - Before computing, every input is validated against its declared range (`0..=1023`).
   - If any input is bad, nothing is written: the output is left untouched, and beryl reports the
     exact index of the first bad value.
5. **Cross-checks.** In the playground, the result is also compared against a separate **reference
   evaluator**, a third implementation that interprets your source directly.

The philosophy: **performance work is automated, and trust is earned by proof, not assumed.**

## 3. Who it is for

- Engineers and researchers who write numerical kernels and want speed without hand-tuning loops.
- People who care about correctness: safety-minded systems engineers, verification and
  compiler enthusiasts, educators.
- The curious: the playground lets anyone write a program, watch beryl choose a plan, and see the
  proof results.

Tone: **precise, calm, confident, honest.** Think of a well-cut gemstone: clarity, facets, light.
No hype words like "revolutionary" or "10x". Let the numbers and the proof story do the work.

## 4. The language, by example

All examples below are real, working beryl programs.

**The shape of a program.** A separable blur: a row pass, then a column pass.

```
module blur;
shape H = 6;
shape W = 8;
input image: i32[H+2,W+2] in 0..=1023;
let rows[r in 0..H+2,c in 0..W] =
  (image[r,c]+2*image[r,c+1])+image[r,c+2];
output result[r in 0..H,c in 0..W] =
  (rows[r,c]+2*rows[r+1,c])+rows[r+2,c];
require plan_workspace_bytes <= 128;
prefer multiplication_ops;
```

- `shape` declares sizes.
- `input` declares an integer grid and the range its values must lie in.
- `let` defines an intermediate grid by a formula.
- `output` defines the result.
- `require` sets a hard storage limit; `prefer` sets the optimization goal.

**Edge detection (Laplacian), with subtraction.**

```
module edges;
shape H = 6;
shape W = 8;
input image: i32[H+2,W+2] in 0..=1023;
let p[r in 0..H+2,c in 0..W+2] = image[r,c];
output result[r in 0..H,c in 0..W] =
  4*p[r+1,c+1] - p[r,c+1] - p[r+2,c+1] - p[r+1,c] - p[r+1,c+2];
```

**Reductions and two inputs: dot product.**

```
module dot;
shape H = 1;
shape W = 1;
input x: i32[1,128] in 0..=1023;
input y: i32[1,128] in 0..=1023;
let t[r in 0..H,c in 0..W] = sum(k in 0..128: x[0,k]*y[0,k]);
output d[r in 0..H,c in 0..W] = t[r,c];
```

**Matrix multiply.**

```
module matmul;
shape H = 8;
shape W = 8;
input a: i32[H,8] in 0..=1023;
input b: i32[8,W] in 0..=1023;
let t[r in 0..H,c in 0..W] = sum(k in 0..8: a[r,k]*b[k,c]);
output m[r in 0..H,c in 0..W] = t[r,c];
```

**A sum over a million values.** It compiles in about 0.2 s, and the proof is no larger than for ten
values.

```
module total;
shape H = 1;
shape W = 1;
input x: i32[1,1048576] in 0..=1023;
let t[r in 0..H,c in 0..W] = sum(k in 0..1048576: x[0,k]);
output s[r in 0..H,c in 0..W] = t[r,c];
```

**Language facts worth showing:**
- Arithmetic: integer literals, `+`, `-`, `*` and parentheses, all exact 32-bit integer math, with
  overflow ruled out by proof.
- Your grouping is preserved exactly: `(a+b)+c` and `a+(b+c)` are treated as different programs.
  beryl never silently rewrites your math.
- `a - b` is defined as exactly `a + (-1)*b`.
- `sum(k in L..U: e)` adds terms. Up to 256 terms it means a fixed balanced tree of additions.
  Above that it is an exact sum, which beryl accepts only when it can prove that no partial sum, in
  any order, overflows.
- Reads use offsets (`x[r+1, c+2]`), literals (`x[0, k]`) and transposes (`x[c, r]`).
- Rejections are specific. Example: *"the output may only read `p`, not `image`"*, highlighted at
  the offending name.

## 5. How it works

Animate this as the centerpiece of the "How it works" section:

```
source  ->  admit  ->  plan candidates  ->  independent checker  ->  native C / WebAssembly
  |                                                                          |
  +-------------------------> reference evaluator (cross-check) <-----------+
```

Key ideas to visualize:

- **Many plans, one proof gate.** The planner proposes, for example, *inline* (no extra memory,
  most work), *rolling rows* (a small buffer, less work) and *materialize* (store everything).
  Each is ranked by your goal and checked. The best plan that passes the checker wins.
- **Untrusted helpers.** Even the loop-structure hints used to emit compact code are untrusted.
  They are expanded and matched against the proven plan, operation by operation, or discarded.
- **Proof that does not grow with your data.** At large sizes, beryl proves a *template*: the
  formula every cell shares, with symbolic indices. Its correctness, bounds and overflow facts then
  hold for every cell at once.
  - A 20x20 grid and a 2000x2000 grid take the same number of checker steps (49).
  - A sum over 1,000 values and one over 1,048,576 take the same small proof.
  - This is the "framework for scale". It is a strong visual: a single faceted crystal (the
    template) that tiles into an enormous lattice (the data).
- **Fail-safe boundaries.** Bad input means no output is written, and you get the exact position
  of the first bad value.

## 6. Performance (measured)

Measured on one Windows 11 machine with clang 22.1.6 at `-O3`, comparing beryl's native output with
equivalent hand-written C (and, at small sizes, Rust 1.96). The figures are median time per call
over repeated runs, and every result was verified against an independent reference by checksum.
Present ratios with this context and include a "methodology" note.

**Small kernels (up to 256 inputs).** beryl's native code against plain C:

| Kernel | beryl | C | beryl vs C |
|---|---|---|---|
| sum of 256 | 35 ns | 56 ns | 1.6x faster |
| dot product (2x128) | 49 ns | 58 ns | 1.2x faster |
| 8x8 matrix multiply | 152 ns | 343 ns | 2.3x faster |
| 16x16 transpose | 93 ns | 98 ns | about even (5% faster) |
| 2x2 / 3x3 stencils (6 kernels) | | | faster in all 6 (about 0.4x C time overall) |

beryl's times **include** validating every input before computing; the C baselines do no
validation.

**Large kernels (up to 4.2 million cells).** The fair control is **hand-written C with the same
interface** (32-bit outputs, input validation, same flags). Use the "vs hand C" column as the
headline; the plain-C column (64-bit outputs) is secondary.

| Kernel | size | beryl | hand C | beryl vs hand C | beryl vs plain C |
|---|---|---|---|---|---|
| 3x3 convolution | 254x254 | 32.6 µs | 42.4 µs | 1.3x faster | 4.5x faster |
| 3x3 convolution | 2046x2046 | 3.53 ms | 3.85 ms | 1.09x faster | 2.7x faster |
| 3x3 box sum | 254x254 | 32.4 µs | 41.0 µs | 1.27x faster | 3.2x faster |
| 5-point Laplacian | 254x254 | 22.3 µs | 31.4 µs | 1.41x faster | 2.9x faster |
| 1-D 3-point stencil | 65,534 | 18.0 µs | 26.4 µs | 1.46x faster | 2.3x faster |
| x^3 + 3x + 7 (map) | 4.2M | 3.42 ms | 3.95 ms | 1.16x faster | 1.2x faster |
| transpose | 256x256 | 77.7 µs | | | 5.2x faster |
| sum | 65,536 | 8.5 µs | | | 1.8x faster |
| matrix multiply | 64x64 | 50.4 µs | | | 3.0x faster |
| matrix multiply | 256x256 | 18.4 ms | | | **1.9x slower** |

Compile time, from source to a verified native executable (proof plus C generation plus clang), is
about **0.2 s** at every size.

Honest gaps to show, because candor sells this product:
- Large matrix multiply is about 2x slower than C today; the fix is planned loop-order and tiling
  schedules.
- Sums above 32-bit range and large dot products are refused, because beryl will not risk
  overflow; 64-bit accumulators are planned.

**Chart data (JSON), ready for a visualization:**

```json
{
  "machine": "Windows 11, clang 22.1.6 -O3; medians; all outputs checksum-verified",
  "small_vs_c": [
    {"kernel": "sum 256", "beryl_ns": 35, "c_ns": 56},
    {"kernel": "dot 2x128", "beryl_ns": 49, "c_ns": 58},
    {"kernel": "matmul 8x8", "beryl_ns": 152, "c_ns": 343},
    {"kernel": "transpose 16x16", "beryl_ns": 93, "c_ns": 98}
  ],
  "large_vs_hand_c": [
    {"kernel": "conv3x3 254^2", "beryl_us": 32.6, "hand_c_us": 42.4, "plain_c_us": 145.4},
    {"kernel": "box3x3 254^2", "beryl_us": 32.4, "hand_c_us": 41.0, "plain_c_us": 103.0},
    {"kernel": "laplace5 254^2", "beryl_us": 22.3, "hand_c_us": 31.4, "plain_c_us": 65.4},
    {"kernel": "stencil1d3 65534", "beryl_us": 18.0, "hand_c_us": 26.4, "plain_c_us": 41.5},
    {"kernel": "sq2x2 255^2", "beryl_us": 54.7, "hand_c_us": 61.6, "plain_c_us": 111.8},
    {"kernel": "polymap 65536", "beryl_us": 30.3, "hand_c_us": 38.4, "plain_c_us": 44.5},
    {"kernel": "conv3x3 2046^2", "beryl_us": 3525.6, "hand_c_us": 3849.4, "plain_c_us": 9362.4},
    {"kernel": "box3x3 2046^2", "beryl_us": 3711.1, "hand_c_us": 3860.0, "plain_c_us": 6954.9}
  ],
  "proof_steps": [
    {"grid": "20x20", "checker_steps": 49},
    {"grid": "2000x2000", "checker_steps": 49}
  ]
}
```

## 7. The playground (existing product)

There is an existing **browser playground**: Python compiled to WebAssembly (Pyodide), fully
client-side, no server.

- It ships five examples: a balanced stencil, no-scratch, small-memory, separable blur and
  Laplacian.
- You choose an input mode (ramp, zeros, checkerboard, or custom values).
- It shows the input grid, the output grid, which plan was chosen and why, every candidate's
  proof status and cost, and the reference cross-check ("N values checked").
- Today it runs programs of up to **256 input cells**; larger programs compile natively.

The website should link to it as **"Try it in your browser"**. A great homepage moment would be a
live, editable mini-playground or a scripted replay of one.

## 8. Roadmap (for a "What's next" section)

| Stage | Adds | Unlocks |
|---|---|---|
| Now | stencils, reductions, two inputs, transposes; proofs that scale to millions of cells | most numerical kernels at real sizes |
| Next | 64-bit accumulators, per-input ranges | large sums, dot products, any input range |
| Then | proven schedules: tiling, rolling buffers, loop order | fast large matrix multiply, cache-optimal stencils |
| Then | large programs in the browser playground | interactive work at scale |
| Later | `max`/`min`, comparisons and conditionals, strided reads, more equations | pooling, cellular automata, scans |

## 9. Creative direction

**Name and metaphor.** Beryl is a gemstone mineral (emerald and aquamarine are both beryl). It
grows as **hexagonal crystals**, and its atomic structure is a **lattice**. Use:
- the crystal lattice, for the data grid;
- facets, for the plan candidates;
- clarity, for proof and transparency;
- light refraction, for one source becoming many proven outputs.

**Palette.**
- Deep near-black ink (`#0B0F0E`).
- Beryl greens and blue-greens: emerald `#1F8A70`, aquamarine `#7FD1C7`, pale beryl `#D8F3EE`.
- One warm accent, used sparingly for "proven" states, such as soft gold `#E8C468`.
- Both light and dark themes are welcome; dark-first suits the gem-in-light look.

**Typography.**
- Headings: a sharp, high-contrast display face (a geometric or neo-grotesk sans with crisp
  terminals).
- Code and numbers: a precise monospace (JetBrains Mono, Berkeley Mono or IBM Plex Mono).
- Write numbers with tabular figures.

**Motion and interaction.**
- **Hero:** a slowly rotating hexagonal crystal, in WebGL or Three.js, built from a grid of cells.
  As the user scrolls, it fractures into a lattice and recomposes, symbolizing one template proving
  millions of cells.
- **"How it works":** scroll-driven. Source code types in; candidate plans fan out as facets; the
  checker "lights up" each facet as valid or rejected; the winner turns gold; output cells fill in.
- **Proof that scales:** a slider from 20x20 to 2000x2000. The grid explodes in size while the
  "checker steps: 49" counter stays fixed. This is the most memorable single interaction available.
- **Benchmarks:** horizontal bars with hover details and a methodology toggle. Show beryl against
  hand C as the headline.
- **Fail-safe:** type a bad value (`1024`) into a small grid. Nothing is written, and the first bad
  index pulses.
- Respect `prefers-reduced-motion`; every animation needs a static fallback.

**Suggested site structure.**
1. **Hero:** positioning line, crystal visual, "Try it in your browser" and "Read how it works".
2. **The idea:** "Say what, not how." A side-by-side of a beryl program (8 lines) against the
   equivalent tuned C (loops, buffers, checks).
3. **How it works:** the animated pipeline (section 5).
4. **Proof that scales:** the slider interaction.
5. **Performance:** charts with honest methodology and gaps.
6. **Language tour:** tabs for blur, Laplacian, dot, matmul and the million-value sum, each with a
   plain-English caption.
7. **Safety by design:** checked overflow, bounds, fail-safe inputs, untrusted planner, independent
   reference.
8. **Roadmap.**
9. **Playground and contact.**

**Accessibility and quality bar.**
- WCAG AA contrast and keyboard navigation for every interaction.
- Real text, not text in images. Code blocks must be selectable.
- Fast first paint: lazy-load WebGL, and show a static crystal image before it loads.
- Mobile layout first-class: the crystal simplifies and charts stack.

## 10. Claims guardrails (important)

**Say:**
- "experimental", "research-grade", "every plan is checked against your source by an independent
  checker before it runs";
- "faster than equivalent hand-written C on the measured stencil and map kernels";
- "proof cost independent of data size" (for the large-program path).

**Do not say:**
- "production-ready", "formally verified" (it is not machine-checked in a proof assistant),
  "always faster than C", or "general-purpose language";
- any benchmark number without its context (one machine, clang `-O3`, medians).

**Always disclose:**
- large matrix multiply is currently slower than C;
- 64-bit results are not supported yet;
- the playground handles up to 256 input cells.

**Use only the public name "beryl".** Do not invent other product names, team names, logos of
real companies, testimonials or user counts.
