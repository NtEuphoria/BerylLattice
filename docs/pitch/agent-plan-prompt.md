# Prompt: ask an AI agent for faster beryl plans

Paste everything below the line into a fresh Claude or Codex chat. Save each JSON block
it returns as its own file, `bench/demo_b/candidates/agent-<tool>-<n>.json`, for example
`agent-codex-3.json`. Then run:

```bash
python tools/demo-checked-candidates.py --source bench/demo_b/program.ax --candidates bench/demo_b/candidates
```

---

You are optimizing a numeric kernel for a compiler called beryl. beryl takes a program, a
"loop plan" saying how to compute it, and an independent checker that refuses any plan
that does not compute exactly what the program says. Your job is to write loop plans that
compute the same result faster.

## The program

```
module box;
shape H = 254;
shape W = 254;
input x: i32[H+2,W+2] in 0..=1023;
let p[r in 0..H+2,c in 0..W] = (x[r,c]+x[r,c+1])+x[r,c+2];
output o[r in 0..H,c in 0..W] = (p[r,c]+p[r+1,c])+p[r+2,c];
```

The input `x` is a 256x256 array stored row by row, so `x[r,c]` is at flat index
`256*r + c`. The output `o` is 254x254, stored row by row.

## The plan format: JSON, `beryl-loop-plan-v1`

```json
{"format": "beryl-loop-plan-v1", "semantic_digest": "<copy from the examples>",
 "plan_id": "<any name>", "stages": [ <stage>, ... ]}
```

A stage is `{"loops": [[var, count], [var, count]], "index": <affine>, "value": <expr>}`.
It runs its two loops (outer, then inner) and stores `value` at flat position `index`.

- **affine:** `[constant, [[var, coefficient], ...]]`, with variables sorted by name and
  no zero coefficients. For example, `[1, [["c", 1], ["r", 256]]]` means
  `1 + c + 256*r`.
- **expr:** one of the following.
  - `["const", n]`
  - `["load", affine]`: read the input at that flat index.
  - `["add", e1, e2]` or `["mul", e1, e2]`
  - `["sum", var, lo, hi, e]`: the sum of `e` for `var = lo .. hi-1`.
  - `["prod", i, j]`: only in the last stage of a two-stage plan. It reads the value
    the first stage stored for position `(r+i, c+j)`.

A one-stage plan computes the output directly. A two-stage plan computes `p` in stage 1,
over loops `[["p", 256], ["q", 254]]` with index `[0, [["p", 254], ["q", 1]]]`, then the
output in stage 2 using `prod`.

## Two correct example plans

Direct (one stage):

```json
{"format":"beryl-loop-plan-v1","plan_id":"direct-v1","semantic_digest":"27e8cb1a24c504b078c8a37bbcde3205fea39f311b119e3745b78a1b0722b212","stages":[{"index":[0,[["c",1],["r",254]]],"loops":[["r",254],["c",254]],"value":["add",["add",["add",["add",["load",[0,[["c",1],["r",256]]]],["load",[1,[["c",1],["r",256]]]]],["load",[2,[["c",1],["r",256]]]]],["add",["add",["load",[256,[["c",1],["r",256]]]],["load",[257,[["c",1],["r",256]]]]],["load",[258,[["c",1],["r",256]]]]]],["add",["add",["load",[512,[["c",1],["r",256]]]],["load",[513,[["c",1],["r",256]]]]],["load",[514,[["c",1],["r",256]]]]]]}]}
```

Carry (two stages, each row sum computed once):

```json
{"format":"beryl-loop-plan-v1","plan_id":"carry-v1","semantic_digest":"27e8cb1a24c504b078c8a37bbcde3205fea39f311b119e3745b78a1b0722b212","stages":[{"index":[0,[["p",254],["q",1]]],"loops":[["p",256],["q",254]],"value":["add",["add",["load",[0,[["p",256],["q",1]]]],["load",[1,[["p",256],["q",1]]]]],["load",[2,[["p",256],["q",1]]]]]},{"index":[0,[["c",1],["r",254]]],"loops":[["r",254],["c",254]],"value":["add",["add",["prod",0,0],["prod",1,0]],["prod",2,0]]}]}
```

## Your task

Write **10 candidate plans** that you believe compute exactly the same output as the
program, and that could run faster.

beryl proves plans structurally. Every expression must keep the program's grouping and
operand order exactly, so reordered or regrouped additions are refused, even when they are
mathematically equal. What can change: whether `p` is computed once and reused (two stages)
or recomputed (one stage); the loop variable names; and the form of each index, as long as
it is the same affine function. A refusal means "not proved", not necessarily "wrong".

For each one, give one sentence on the idea, then the JSON in its own code block. Copy the
`semantic_digest` exactly.
