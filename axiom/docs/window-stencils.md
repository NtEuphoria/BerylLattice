# Writing window stencils

Beryl admits two kinds of program: the original squared 2x2 stencil, and any
**two-stage window stencil**. A window stencil computes a *producer* grid from
the input, then the *output* grid from the producer, each from a small window of
neighbouring cells. You state the computation and a storage limit; beryl picks a
schedule (recompute, keep a few rows, or store everything), proves the schedule
correct against your source, and runs it.

Every program here is checked by `tests/test_window_guide.py`, so they stay valid.

## The shape of a program

```ax
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

The rules:

| Part | Must be |
|---|---|
| Shapes | exactly two literal shapes, rows first (`shape H = 6;`, `shape W = 8;`) |
| Input | `name: i32[H+a, W+b] in 0..=1023;` with `a`, `b` literals from 0 to 8 |
| Producer | `let p[r in 0..H+pa, c in 0..W+pb] = ...;` reading only the input |
| Output | `output o[r in 0..H, c in 0..W] = ...;` reading only the producer |
| Reads | `tensor[r + i, c + j]`: row axis first, column second, literal offsets 0 to 8 |
| Arithmetic | integer literals, `+`, `-`, `*` and parentheses |
| Size | at most 256 input cells |
| Limits | optional `require plan_workspace_bytes <= N;` and `prefer multiplication_ops;` or `prefer plan_workspace_bytes;` |

Arithmetic is exact 32-bit integer arithmetic, checked at every operation. Your
grouping is kept exactly as written: `(a+b)+c` and `a+(b+c)` are different
programs with different identities, even though they compute the same values.

## Subtraction

`a - b` means exactly `a + (-1)*b`. That is the whole definition: the `-1*b`
step is itself a checked operation, so `a - b` is rejected as an overflow when `b` can be
-2147483648, even where `a - b` itself would fit. Subtraction works anywhere in a scalar
expression, but not in indices or shapes, where offsets only go forward
(`r + 1`, never `r - 1`).

```ax
module edges;
shape H = 6;
shape W = 8;
input image: i32[H+2,W+2] in 0..=1023;
let p[r in 0..H+2,c in 0..W+2] = image[r,c];
output result[r in 0..H,c in 0..W] =
  4*p[r+1,c+1] - p[r,c+1] - p[r+2,c+1] - p[r+1,c] - p[r+1,c+2];
prefer multiplication_ops;
```

## Getting fast plans: write separable kernels separably

Beryl proves plans by matching them against the source exactly, so it never
rewrites your algebra. A 3x3 convolution written as nine terms stays nine terms
per output. Written as a row pass followed by a column pass (the blur above), the
producer row sums can be computed once and reused by three output rows, which
beryl does automatically when the storage limit allows it (`rows-v1`). The two
forms compute exactly the same integers.

## One-dimensional and elementwise kernels

Use a 1 x W grid. The output stage can be a plain copy of the producer.

```ax
module smooth;
shape H = 1;
shape W = 254;
input x: i32[H,W+2] in 0..=1023;
let t[r in 0..H,c in 0..W] = (x[r,c]+2*x[r,c+1])+x[r,c+2];
output y[r in 0..H,c in 0..W] = t[r,c];
prefer multiplication_ops;
```

```ax
module poly;
shape H = 1;
shape W = 256;
input x: i32[H,W] in 0..=1023;
let t[r in 0..H,c in 0..W] = x[r,c]*x[r,c]*x[r,c] + 3*x[r,c] - 7;
output y[r in 0..H,c in 0..W] = t[r,c];
prefer multiplication_ops;
```

## Reductions, a second input and gathers

`sum(k in L..U: e)` adds the terms `e` with `k` = `L`, `L+1`, ... `U-1` (1 to 256 terms, literal
bounds). It means exactly a balanced tree of `+`: `sum(k in 0..3: t)` is `t0 + (t1 + t2)`, splitting
each range at its midpoint. Like every `+`, each addition is a checked 32-bit operation. `k` becomes a
literal in each term, so it can index (`x[0,k]`, `b[k,c]`) or scale (`k*x[0,k]`). Its name must not
repeat a shape, an axis or an enclosing `sum`.

A program may declare two inputs. The input buffer holds the first input then the second, each row by
row, so a bad value's reported index counts from the start of the first input. Inputs together hold at
most 256 cells. These programs belong to the `reduce-v1` family, which also allows:

- literal input dimensions (`i32[1,128]`);
- producer reads indexed by a literal, by either axis in either position (`x[c,r]`), or by an axis
  plus offsets (`x[r+1+2, c]`).

The output stage still reads the producer with window indices.

```ax
module dot;
shape H = 1;
shape W = 1;
input x: i32[1,128] in 0..=1023;
input y: i32[1,128] in 0..=1023;
let t[r in 0..H,c in 0..W] = sum(k in 0..128: x[0,k]*y[0,k]);
output d[r in 0..H,c in 0..W] = t[r,c];
```

```ax
module matmul;
shape H = 8;
shape W = 8;
input a: i32[H,8] in 0..=1023;
input b: i32[8,W] in 0..=1023;
let t[r in 0..H,c in 0..W] = sum(k in 0..8: a[r,k]*b[k,c]);
output m[r in 0..H,c in 0..W] = t[r,c];
```

```ax
module transpose;
shape H = 4;
shape W = 6;
input x: i32[W,H] in 0..=1023;
let t[r in 0..H,c in 0..W] = x[c,r];
output y[r in 0..H,c in 0..W] = t[r,c];
```

## Plans beryl chooses between

| Plan | What it does | Storage |
|---|---|---|
| `inline-v1` | recomputes each producer value every time the output reads it | none |
| `rows-v1` | keeps a rolling window of the producer rows one output row reads | K rows of the producer |
| `materialize-v1` | computes the whole producer once, then the output | the whole producer |

`prefer multiplication_ops` picks the plan with the fewest multiplications that
fits the storage limit; `prefer plan_workspace_bytes` picks the least storage.

## Reading rejections

Rejections name the rule and point at the offending part of the source:

| Message | Fix |
|---|---|
| `the output may only read p, not image` | the output stage reads the producer; move input reads into the `let` |
| `the first index must be r or r + k ...` | use the row axis first, the column axis second, with forward literal offsets |
| `inputs must be declared ... in 0..=1023` | declare the input range exactly `0..=1023` |
| `input dimensions must be H or H + k ...` | write input sizes in terms of the shapes, not as literals |
| `requires exactly two shapes, one or two inputs, one producer and one output` | add a `let` stage; the message says what it found |
| `producer indices must be an axis, ...` | index inputs with `r`, `c`, `r + k` or a literal; not a shape name |
| `a sum needs between 1 and 256 terms` | use literal bounds `L..U` with `U - L` from 1 to 256 |
| `subtraction is only allowed in scalar expressions` | indices only go forward: `r + k` with `k >= 0` |
| `input exceeds 256 cells` | shrink the shapes; larger sizes are not admitted yet |

## Not supported yet

Conditionals, comparisons and `max`, strided reads (`x[2*r, c]`), 64-bit accumulators,
more than two inputs, and inputs above 256 cells.
See `docs/reviews/2026-10-19-gaps-and-improvement-plan.md` for the plan.
