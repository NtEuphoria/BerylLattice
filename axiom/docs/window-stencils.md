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

## Larger programs and 64-bit values

A program with more than 256 input cells, or with a sum of more than 256 terms, belongs to the
`scale-v1` family: up to 2^24 cells, with sums kept as loops instead of expanded into trees. It is
still checked. Before any code is emitted, beryl proves from the input range that no `+`, `*` or
partial sum, added in any order, can leave its type.

A `let` or `output` holds i32 values unless it declares `i64` after its name:

```ax
module dot;
shape H = 1;
shape W = 1;
input x: i32[1,4096] in 0..=1023;
input y: i32[1,4096] in 0..=1023;
let t: i64[r in 0..H,c in 0..W] = sum(k in 0..4096: x[0,k]*y[0,k]);
output d: i64[r in 0..H,c in 0..W] = t[r,c];
```

How the types work:

- Each value is checked against its own equation's type. Here each product fits i32, but their
  total (up to 4096 x 1023²) needs i64.
- An i32 equation that reads an i64 one must still fit i32, or the program is refused.
- Inputs are always i32.
- i64 equations are `scale-v1` only; the 256-cell families above stay i32.
- When a sum could overflow i32, the refusal says how many terms fit and suggests declaring the
  equation i64.

### Input ranges

In `scale-v1`, each input may declare its own range, signed included, anywhere inside i32.
The checker bounds every read by that input's range, and the check before computing tests
each input against its own range. That makes quantized arithmetic provable. Here unsigned
8-bit activations meet signed 8-bit weights, and the proof shows the 32-bit total cannot
overflow: 40,000 × 255 × 128 < 2³¹.

```ax
module int8dot;
shape H = 1;
shape W = 1;
input a: i32[1,40000] in 0..=255;
input w: i32[1,40000] in -128..=127;
let t[r in 0..H,c in 0..W] = sum(k in 0..40000: a[0,k]*w[0,k]);
output d[r in 0..H,c in 0..W] = t[r,c];
```

At 70,000 terms the same program is refused, with the number of terms that fit. The
256-cell families keep `0..=1023`, so a small program with another range becomes `scale-v1`.

### min, max and clamp

`min(a, b)` and `max(a, b)` are the exact integer minimum and maximum. They cannot
overflow, but their operands are checked like any other node. `clamp(x, lo, hi)` is
defined as exactly `min(max(x, lo), hi)`; literal bounds with `lo > hi` are refused.
All three work anywhere in a scalar expression, inside sums included, but not in indices.

The checker carries their bounds through the proof. `max(t, 0)` is at least 0, and
`min(x, 255)` is at most 255, so a sum of `min(x[0,k], 255)` may have four times as many
terms as a sum of `x[0,k]` before it can overflow. Here a quantized dense-layer cell
applies ReLU to its int8 dot product:

```ax
module relu;
shape H = 1;
shape W = 1;
input a: i32[1,40000] in 0..=255;
input w: i32[1,40000] in -128..=127;
let t[r in 0..H,c in 0..W] = sum(k in 0..40000: a[0,k]*w[0,k]);
output y[r in 0..H,c in 0..W] = max(t[r,c], 0);
```

And a signed edge filter whose result is clamped back into 8 bits:

```ax
module sharpen;
shape H = 30;
shape W = 25;
input x: i32[H+2,W+2] in -1000..=1000;
let p[r in 0..H+2,c in 0..W] = (x[r,c]+2*x[r,c+1])+x[r,c+2];
output o[r in 0..H,c in 0..W] = clamp(4*p[r+1,c] - p[r,c] - p[r+2,c], 0, 255);
```

The 256-cell families have no `min` or `max`, so a small program that uses them becomes
`scale-v1`.

### Shifts and rounding

`shr(x, k)` shifts right by `k` bits, rounding toward minus infinity: it is exactly
`floor(x / 2^k)`, so `shr(-7, 1)` is -4. `shr_round(x, k)` rounds halves up: it is exactly
`floor(x / 2^k + 1/2)`, so `shr_round(5, 1)` is 3 and `shr_round(-5, 1)` is -2. This is
the rounding of Arm's rounding shift instructions.

- `k` is an integer literal: 0 to 63 for `shr`, 1 to 63 for `shr_round`. Shifting past the
  value's width gives 0 or -1, never undefined behavior.
- Neither can overflow, and the checker carries their bounds through the proof like
  `min` and `max`.
- There is no left shift; write `x * 256`, which is checked like any product.
- Like `min` and `max`, a program that uses them is `scale-v1`.

Together with `clamp`, they express the requantization step of an int8 layer. Here the
64-bit accumulator is multiplied by a fixed-point scale (1518500250 / 2⁴⁰, about
0.00138), rounded, offset by a zero point of 3, and saturated to int8. The proof shows
the shifted value fits the 32-bit output:

```ax
module requant;
shape H = 1;
shape W = 1;
input a: i32[1,40000] in 0..=255;
input w: i32[1,40000] in -128..=127;
let t: i64[r in 0..H,c in 0..W] = shr_round(sum(k in 0..40000: a[0,k]*w[0,k]) * 1518500250, 40);
output y[r in 0..H,c in 0..W] = clamp(t[r,c] + 3, -128, 127);
```

### 8-bit and 16-bit storage

Inputs and the output may be stored as `u8` (0 to 255), `i8` (-128 to 127) or `i16`
(-32768 to 32767). These are storage types only: arithmetic stays i32, or i64 in an i64
program, so an intermediate value may be as wide as it needs. The generated kernel takes
`uint8_t`, `int8_t` or `int16_t` arrays, which moves a quarter or half of the bytes of an
i32 kernel.

- An input still declares its range, which must lie inside its type. When the range is the
  whole type, there is nothing to check before computing.
- An output's value must be proved to fit its type, so saturate it with `clamp` or narrow it
  with a shift. Without that, the program is refused with the range the output can reach.
- Every input of a program has the same storage type, because the input buffer is one
  array. A `let` stays i32 or i64.
- The standalone driver refuses a token that does not fit the input type (exit 65). It never
  wraps the value.
- Like `min` and `max`, a program that uses them is `scale-v1`.

Here a [1, 2, 1] × [1, 2, 1] blur of 8-bit pixels sums to at most 4,080, then a rounding
shift by 4 divides by 16 and brings it back to 0..255:

```ax
module blur;
shape H = 120;
shape W = 100;
input x: u8[H+2,W+2] in 0..=255;
let p[r in 0..H+2,c in 0..W] = (x[r,c]+2*x[r,c+1])+x[r,c+2];
output o: u8[r in 0..H,c in 0..W] = shr_round(p[r,c] + 2*p[r+1,c] + p[r+2,c], 4);
```

And the int8 dense layer, now on int8 arrays end to end: 16 output channels, each a dot
product of 1,024 int8 activations with that channel's int8 weights, requantized and
saturated to int8:

```ax
module dense;
shape H = 1;
shape W = 16;
input a: i8[1,1024] in -128..=127;
input k: i8[W,1024] in -127..=127;
let t: i64[r in 0..H,c in 0..W] = shr_round(sum(j in 0..1024: a[0,j]*k[c,j]) * 1518500250, 40);
output y: i8[r in 0..H,c in 0..W] = clamp(t[r,c] + 3, -128, 127);
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
| `inputs must be declared ... in 0..=1023` | the 256-cell window and reduction families need `0..=1023`; other ranges are `scale-v1` (see "Input ranges") |
| `input dimensions must be H or H + k ...` | write input sizes in terms of the shapes, not as literals |
| `requires exactly two shapes, one or two inputs, one producer and one output` | add a `let` stage; the message says what it found |
| `producer indices must be an axis, ...` | index inputs with `r`, `c`, `r + k` or a literal; not a shape name |
| `a sum needs between 1 and 256 terms` | use literal bounds `L..U` with `U - L` from 1 to 256 |
| `subtraction is only allowed in scalar expressions` | indices only go forward: `r + k` with `k >= 0` |
| `input exceeds 256 cells` | shrink the shapes, or write a `scale-v1` program (see "Larger programs and 64-bit values") |
| `... at most N terms fit in i32; declare the equation i64 ...` | add `: i64` to the `let` and `output` (see "Larger programs and 64-bit values") |
| `the output ... outside its storage type u8 ...` | saturate it with `clamp` or narrow it with a shift (see "8-bit and 16-bit storage") |

## Not supported yet

Conditionals and comparisons, left shifts and bitwise operators, strided reads (`x[2*r, c]`), more than two inputs,
i64 inputs, inputs of different storage types in one program, and i64 equations or narrow
storage in the 256-cell families.
See `docs/reviews/2026-10-19-gaps-and-improvement-plan.md` for the plan.
