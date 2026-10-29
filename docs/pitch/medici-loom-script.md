# 1517 Medici: Loom script, v1 (2026-10-25)

**Target length:** 5:00 at about 140 words a minute.

**Where the text comes from:**
- `[brackets]` are yours to fill in, in your own words. Spoken, not read, is best.
- Every number comes from `docs/reviews/2026-10-25-matched-benchmarks.md` ("Claims now
  allowed"). Do not round them up. The speed numbers were updated on 2026-10-26 to the AVX2
  rerun and await your review there.

**v2:** after your practice take, note what felt stiff or long. v2 applies those notes,
cuts to 4:45, and rechecks every claim.

---

## 0:00–1:00 · Who you are (about 140 words)

> Hi, I'm [your name]. I'm [a student at … / I left … to build this], and I live just
> outside Boston.
>
> [How you got into programming, in two or three sentences: the first thing you built, the
> moment you got hooked.]
>
> [Why speed and correctness: the moment you realized fast code is often quietly wrong.
> One concrete story, if you have one.]
>
> For the last [N weeks/months] I've been building beryl: a programming language where
> fast code is proved correct before it runs.

## 1:00–1:45 · The problem (about 105 words)

> Fast numeric code is everywhere: image pipelines, sensor processing, AI kernels. It's
> also where the scariest bugs live. An integer overflows, or a read goes one past the end
> of an array, and the program doesn't crash. It just gives a wrong answer.
>
> And now AI writes a lot of that code. In KernelBench, a 2025 benchmark, frontier models
> wrote GPU kernels that were both correct and faster in under 20% of the tasks.
>
> beryl's idea: let anyone, even an AI, propose how to make the code fast. Then an
> independent checker proves the optimized plan computes exactly what the program says,
> and can't overflow or read out of bounds. If it can't prove it, it won't run. The last
> step, turning a proved plan into C, is tested but not yet proved, and I'm upfront about
> that.

## 1:45–3:15 · Live demo (about 210 words of narration)

On screen, in the repository folder. Run these beforehand once, so the C compiler is warm.

**1. A program.** Open `docs/pitch/demo/energy.ax`.

> This is a whole beryl program: the energy of a 3,000-sample sensor trace, the sum of the
> squares. Every input is declared to lie between 0 and 1023.

**2. The refusal.** Run:

```bash
python tools/beryl.py native docs/pitch/demo/energy.ax --out .local/kernel.c --force
```

> beryl refuses it, and says why: 3,000 squares of up to a million each can reach three
> billion, more than 32 bits hold. At most 2,052 terms fit. It even tells me the fix.

**3. The fix.** Open `docs/pitch/demo/energy-i64.ax` and show the two `: i64`. Then run:

```bash
python tools/beryl.py native docs/pitch/demo/energy-i64.ax --out .local/kernel.c --exe .local/kernel.exe --force
```

> Declare the result 64-bit, and now it compiles to native code, with the proof that it
> can't overflow.

**4. AI-written plans, checked.** Run:

```bash
python tools/demo-checked-candidates.py --source bench/demo_b/program.ax --candidates bench/demo_b/candidates
```

> Here are candidate plans for a 3-by-3 image filter: beryl's own two, ten deliberately
> broken ones [and N written by AI agents, if you added them]. beryl refuses every plan it
> can't prove, and says why. Refused means "not proved", so it errs on the side of no.
> Its own carry plan is accepted, checked against an independent reference, and timed:
> about 1.3 times faster than the default plan.

**5. The chart.** Show the website's performance section, on the "like for like · vs hand C" tab.

> And it's fast. On one thread, against hand-written C with the same interface, beryl was
> faster in 16 of 18 cases with gcc, 1.14 times on average, and in all 12 cases with clang,
> 1.72 times. With four threads each, it beat C with OpenMP in 19 of 20 cases: 1.87 times
> faster on in-cache workloads and 1.53 times at large sizes. It still loses a few: two
> mid-size image filters against gcc, and a very large dot product on four threads. I'm
> showing those too.

## 3:15–4:15 · Why you're dedicating yourself (about 140 words)

> [Why this, why you, why now. Say it in your own words.]
>
> Where this goes: right now beryl handles integer array kernels, the kind of code inside
> image pipelines and quantized AI models. Next come more number types and operations, so
> it can express a full quantized neural-network layer, proved safe. Then floating point
> and GPUs, so the same guarantee reaches AI training kernels. And because its loops are
> bounded and its output is plain C, it fits real-time systems where a wrong number is a
> safety problem: vehicles, drones, defense.
>
> I'm building this with AI agents as my engineering team, and beryl is what makes that
> safe: the agents can write the fast code, and the checker decides what ships.

## 4:15–5:00 · What the grant does (about 105 words)

> The grant would pay for the AI development tools I use as that team, Claude and Codex,
> for the next few months, and for compute to test on more hardware.
>
> In 90 days I want to show you three things:
> - a verified int8 neural-network layer beating tuned C;
> - checked inputs folded into large image filters, so they read their data once;
> - the first real users trying beryl on their own kernels.
>
> Thanks for watching. Everything I showed is in the repository, linked in my email.

---

## Claim check (redo after each revision)

- [ ] Every number appears word for word in the matched-benchmark report's "Claims now
      allowed" section.
- [ ] No "faster than C" without its qualifier: "hand-written C with the same interface",
      or "plain C baselines" with their 64-bit outputs, plus the thread count.
- [ ] No claim about GPUs or AI training as a current capability: those are "where this goes".
- [ ] No internal names on screen: check the terminal prompt, paths and window titles.
      Record from the repository root; the commands above never enter the compiler's
      internal source folder.
- [ ] Agent-written candidates: mention them only if you added them with
      `docs/pitch/agent-plan-prompt.md`.
