import { getExamples, runDemo } from './transport.js';

const run = document.getElementById('benchmark-run');
const cancel = document.getElementById('benchmark-cancel');
const status = document.getElementById('benchmark-status');
const rows = document.getElementById('browser-rows');
let active = null;

function row(target, values) {
  const tr = document.createElement('tr');
  for (const value of values) {
    const td = document.createElement('td');
    td.textContent = value;
    tr.append(td);
  }
  target.append(tr);
}

fetch('./benchmark-results.json').then(response => {
  if (!response.ok) throw new Error('Saved results unavailable');
  return response.json();
}).then(report => {
  document.getElementById('comparison-environment').textContent = `${report.platform}; Python ${report.python}; ${report.compilers.C}; ${report.compilers.Rust}. Measured ${report.created_utc.slice(0, 10)}. C: -O3; Rust: -O. Full flags in the download.`;
  for (const item of report.cases) {
    row(document.getElementById('native-rows'), [
      `${item.height} × ${item.width} · ${item.input_mode}`,
      ...['beryl', 'C', 'Rust'].map(name => `${item.measurements[name].median_ms.toFixed(2)} ms`),
    ]);
  }
}).catch(() => { document.getElementById('comparison-environment').textContent = 'Saved measurements could not load. Reload to retry.'; });

cancel.addEventListener('click', () => active?.abort());
run.addEventListener('click', async () => {
  if (active) return;
  const controller = new AbortController();
  active = controller;
  run.disabled = true;
  cancel.disabled = false;
  rows.replaceChildren();
  status.textContent = 'Preparing the runtime…';
  const deadline = setTimeout(() => controller.abort(), 120000);
  try {
    // Cancellation also stops waiting for shared runtime startup.
    const data = await Promise.race([
      getExamples(),
      new Promise((_, reject) => controller.signal.addEventListener('abort', () => reject(new DOMException('Cancelled', 'AbortError')), { once: true })),
    ]);
    for (const [h, w] of [[1, 1], [5, 7], [15, 15]]) {
      const samples = [];
      const source = data.examples[0].source.replace('H = 5;', `H = ${h};`).replace('W = 7;', `W = ${w};`);
      for (let sample = 0; sample < 4; sample++) {
        if (controller.signal.aborted) throw new DOMException('Cancelled', 'AbortError');
        status.textContent = `${h} × ${w}: ${sample === 0 ? 'warming up' : `sample ${sample} of 3`}…`;
        const start = performance.now();
        const result = await runDemo({ source, input_mode: 'ramp' }, { signal: controller.signal });
        const elapsed = performance.now() - start;
        if (controller.signal.aborted) throw new DOMException('Cancelled', 'AbortError');
        if (result.status !== 'success' || result.comparison?.matches !== true || result.output?.length !== h * w) throw new Error('Correctness check failed');
        for (let r = 0; r < h; r++) for (let c = 0; c < w; c++) {
          const i = r * (w + 1) + c;
          const expected = [i, i + 1, i + w + 1, i + w + 2].reduce((sum, x) => sum + (x + 1) ** 2, 0);
          if (result.output[r * w + c] !== expected) throw new Error('Output mismatch');
        }
        if (sample) samples.push(elapsed);
      }
      samples.sort((a, b) => a - b);
      row(rows, [`${h} × ${w}`, `${samples[1].toFixed(2)} ms`, 'All values verified']);
    }
    status.textContent = 'Complete. All three workloads passed correctness checks.';
  } catch (error) {
    rows.replaceChildren();
    status.textContent = controller.signal.aborted ? 'Stopped (cancelled or two-minute limit reached). You can run again.' : `Benchmark failed: ${error.message}. You can retry.`;
  } finally {
    clearTimeout(deadline);
    active = null;
    run.disabled = false;
    cancel.disabled = true;
  }
});
