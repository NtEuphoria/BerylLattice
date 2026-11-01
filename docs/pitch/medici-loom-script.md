# 1517 Medici: Loom script, v2 (2026-10-31)

**What 1517 asks for.** "Email us (any of us with firstname@1517fund.com) with a five minute
Loom video". It should cover who you are (how you got into your topic, unique hobbies), why you
want to "eat, drink, and breathe" the project, and how a grant would help
(https://www.1517fund.com/medici). They fund the person; the demo is the evidence.

**Length.**
- About 510 scripted words, plus at most 130 of yours in [brackets]: about 640 words, which is
  4:25 at 145 a minute.
- The pauses, the 15-second check and the window switches bring it to about 4:45.
- Write your bracketed parts out and time a read-aloud before recording. If a practice take
  runs past 4:50, trim your parts first.

**On screen, three things only:**
- **The runner:** `python tools/showcase.py`, from the repository root; any key advances.
  - It shows no paths or internal names.
  - It prints only "step failed" if anything breaks.
  - It keeps WSL awake while it waits, so no step opens on a blank screen.
- **The frame:** `docs/pitch/demo/frame.png`, full screen.
- **The title card:** `docs/pitch/demo/title.png`, full screen, behind your camera.

**Numbers.** Every number on screen and in the narration is in the matched-benchmark report's
"Claims for the Medici video (2026-10-31)". **All of it waits for your review.**

**Say these word for word.** Say everything else in your own words.
- The hook: "Computers can be fast and wrong at once."
- The key line: "beryl won't use the fast version until it has checked that the answer stays
  the same." Say it at the end of the cold open and again at the end of the video.
- The two verdicts: "32,512, under the limit" and "32,768, over".
- The ask.

---

## 0:00–0:30 · Cold open · runner step 0, camera bubble large

On screen when you start (run the runner first and stop at step 0). Look at the lens for one
beat, then start:

```
right answer                            9,715,500
fast instruction, no range check        5,107,068      <- about half

my own test program, no guard · not PyTorch
AMD Ryzen 3 3100 · AVX2 (vpmaddubsw + vpmaddwd)
```

> This is the right answer. This one came from a fast instruction on my own computer: about
> half. No crash, no warning. Computers can be fast and wrong at once. [I'm NAME, STATUS: "a
> senior at SCHOOL", or "I left SCHOOL to build this", from Revere, Massachusetts.] So I built
> beryl, a compiler that won't use the fast version until it has checked that the answer stays
> the same.

## 0:30–1:10 · Who I am · title card, camera big

> [How you got into programming: the first thing you built and the moment you got hooked.
> Two sentences.]
> [One hobby that has nothing to do with computers, and what you love about it. One sentence.]
> [The moment you first saw fast code be quietly wrong: a concrete story, two or three
> sentences.] [Then, in your own words, why this is the thing you can't stop thinking about.]
> This isn't for school or a grade. Let me show you.

## 1:10–1:40 · The overflow refusal · runner step 1, any key between parts

What appears: the program; `REFUSED` in red with the reason; the fixed program with the two
changed lines marked and `COMPILED` in green; then
`worst case (3,000 readings of 1,023)  ->  3,139,587,000`.

> Here's the idea in one program: add up the squares of 3,000 sensor readings, each up to
> 1,023. beryl refuses it. The total can reach three billion, more than a 32-bit signed integer
> holds. Only 2,052 terms would fit. It even names the fix: 64 bits. Now it compiles, and on
> the worst case it prints the exact answer.

## 1:40–2:16 · Plans, checked · runner step 2

Start talking as you press the key. The check takes about 15 seconds; then a six-row table
appears:

```
changed-formula  REFUSED    computes a different formula
off-by-one       REFUSED    runs 1 column past the edge of the image
planner-carry    ACCEPTED   proved equal to the program
planner-direct   ACCEPTED   proved equal to the program
skips-a-row      REFUSED    never writes the last row
wrong-program    REFUSED    belongs to a different program
```

> Anyone can propose a faster way to run a program: me, beryl's own planner, and soon AI
> agents. beryl must prove that a plan does exactly what the program says, or it isn't used.
> While it checks: four of these six plans are broken on purpose. One changes
> the formula, one runs off the edge, one skips a row, one belongs to another program. Each is
> refused, for its own reason. The planner's two pass, and match a slow reference on test
> inputs.

## 2:16–3:08 · The trap and the rule · runner step 3

What appears:
- the cold-open pair again;
- the dense layer with `in 0..=127` marked, then in green
  `pair bound 2 x 127 x 128 = 32,512 <= 32,767  ->  FAST INSTRUCTION (vpmaddubsw)`;
- the same layer with `0..=128`, then in amber `… = 32,768 > 32,767  ->  EXACT WIDE PATH`;
- the stored line
  `recorded 2026-10-31 · … full range, exact path 690 µs · inputs to 127, fast pair 327 µs`.

> Remember that wrong number? AI models often run on 8-bit numbers, and chips have a fast
> instruction for them that quietly clips any pair of products past 32,767.
> PyTorch dodges it by convention: its default settings keep inputs to half range. beryl works
> it out from the program. Inputs up to 127, weights down to minus 128: the worst pair is
> 32,512, under the limit. So it uses the fast instruction, in less than half the time. Change
> one number to 128: 32,768, over, so it takes the exact path. The honest part: this rule, and
> the step that writes the C, are tested today, not proved.

## 3:08–3:38 · "Is checked code slow?" · the frame, camera small

> Is checked code slow? Here it is against PyTorch's own int8 kernel, FBGEMM, on my four-core
> Ryzen. On one thread, on par: a tie on the big layer. On four threads, 1.1 to 1.4 times
> faster. It's not like for like. beryl checks every input and FBGEMM doesn't, but FBGEMM
> also turns its outputs back into 8 bits. Where beryl ties or loses is listed right here.

## 3:38–4:05 · Why me, where this goes · title card, camera big

> [Why you can't put it down: one specific night or weekend you lost to beryl. Two sentences.]
> I build beryl with AI agents as my engineering team. They write code fast, and that's the
> point: I don't trust fast code, theirs or mine, until something checks it. [What you
> personally do, said only if it is exactly true: for example, "I design the checker's rules
> and read every refusal."] Today beryl handles integer kernels on CPUs. Next, a full
> quantized layer. Later, floating point and GPUs.

## 4:05–4:45 · The ask · title card, camera big

> A grant of [AMOUNT; the minimum is $1,000] pays for [N months] of the AI tools I build with,
> and time on newer chips, to find where beryl loses. In 90 days: that pair
> rule proved inside the checker, and a full quantized layer measured against PyTorch. And if
> you know one compiler or ML-systems engineer who'd tell me where I'm wrong, I'd love that
> intro. This Friday I'm [the concrete next step]. Anyone can propose the fast version. beryl
> won't use it until it has checked that the answer stays the same. Thanks for watching.

---

## Never say

- "Everything I showed is in the repository", unless the repository link is clean and public.
- "proved", "verified" or "certified" int8 layer: the pair rule and the C step are tested, not
  proved.
- "faster than PyTorch" on one thread: one thread is on par. Four-thread ratios always come
  with "four threads".
- that the six plans were written by an AI. They are hand-made mutations plus beryl's own
  planner, unless you add a real agent-written one with `docs/pitch/agent-plan-prompt.md`.
- `torch._int_mm` numbers. It is an unoptimized CPU fallback, so comparing against it would
  mislead.

## Recording checklist

- **Loom:** Screen + Cam. Do a 20-second test first: resize the bubble and switch windows
  without pausing. Check your plan's length cap. Keep bullets in the speaker notes.
- **Terminal:**
  - Windows Terminal, 22pt monospace, sized to at least 90 × 32 (not just maximized). Check it
    with a 90-character line before the take.
  - Prompt `beryl $ ` (PowerShell: `function prompt {"beryl $ "}`) and window title "beryl".
  - Run the runner once end to end 1–2 minutes before each take, so the cached builds are
    warm.
- **Machine:** close everything else, including test runs. Turn on Do Not Disturb and hide the
  taskbar.
- **Takes:** three full takes; keep the most alive one, not the cleanest. Leave 1 second of
  silence after the cold-open numbers and after the 127/128 verdicts. If a step fails, stop
  the take; never scroll through an error on camera.
- **Rehearse:** talking over the 15-second check; the 2:16 beat, the densest 50 seconds; your
  parts, 130 words or fewer in total.
- **Before sending:** watch the 720p playback on a phone, and open the Loom link logged out.

## Claim check (redo after each revision)

- [ ] Every number appears in "Claims for the Medici video (2026-10-31)" in
      `docs/reviews/2026-10-25-matched-benchmarks.md`, and you have reviewed it there.
- [ ] Every win has its qualifier (threads, layer size), and the losses panel is on screen.
- [ ] No GPU or training claim as a present capability.
- [ ] No internal names on screen: the terminal prompt, window title and paths.
