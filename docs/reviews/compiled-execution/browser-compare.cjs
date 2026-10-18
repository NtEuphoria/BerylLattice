const assert = require('node:assert/strict');
const fs = require('node:fs');
const { chromium } = require('/opt/codex/cua_node/lib/node_modules/playwright-core');

(async () => {
  const browser = await chromium.launch({executablePath: '/usr/bin/chromium', headless: true, args: ['--no-sandbox']});
  const report = {browser: browser.version(), scope: 'Same-host repeated verified browser requests. Before interprets and recompiles each request; after reuses a freshly checked compiled module. Initial runtime startup excluded; first request and compilation are recorded separately.', cases: []};
  const pages = {};
  const errors = [];
  try {
    for (const [name, url] of [['before', process.argv[2]], ['after', process.argv[3]]]) {
      const page = await browser.newPage();
      pages[name] = page;
      page.on('pageerror', error => errors.push(String(error)));
      await page.goto(url);
      await page.waitForFunction(() => document.querySelector('#examples button')
        && !document.querySelector('#run').disabled, null, {timeout: 120000});
      await page.evaluate(async () => {
        window.measureTransport = await import('./transport.js');
        window.measureExamples = await window.measureTransport.getExamples();
      });
    }
    for (const [h, w, mode] of [[5, 7, 'ramp'], [15, 15, 'ramp'], [15, 15, 'checkerboard']]) {
      const samples = {before: [], after: []};
      let reference;
      let firstAfter;
      for (let sample = 0; sample < 6; sample++) {
        for (const name of sample % 2 ? ['after', 'before'] : ['before', 'after']) {
          const observed = await pages[name].evaluate(async ({h, w, mode, sample}) => {
            const source = window.measureExamples.examples[0].source.replace('H = 5;', `H = ${h};`).replace('W = 7;', `W = ${w};`);
            const inputs = Array.from({length: (h + 1) * (w + 1)}, (_, i) => mode === 'ramp' ? (i + 7 * sample) % 1024 : (1023 * ((Math.floor(i / (w + 1)) + i % (w + 1)) % 2) + 7 * sample) % 1024);
            const request = {source, input_mode: 'custom', inputs};
            const start = performance.now();
            const result = await window.measureTransport.runDemo(request);
            return {milliseconds: performance.now() - start, result};
          }, {h, w, mode, sample});
          const result = observed.result;
          assert.equal(result.status, 'success');
          assert.equal(result.comparison.matches, true);
          const data = Array.from({length: (h + 1) * (w + 1)}, (_, i) => mode === 'ramp' ? (i + 7 * sample) % 1024 : (1023 * ((Math.floor(i / (w + 1)) + i % (w + 1)) % 2) + 7 * sample) % 1024);
          const expected = [];
          for (let r = 0; r < h; r++) for (let c = 0; c < w; c++) {
            const i = r * (w + 1) + c;
            expected.push([i, i + 1, i + w + 1, i + w + 2].reduce((sum, j) => sum + (data[j] + 1) ** 2, 0));
          }
          assert.deepEqual(result.input, data);
          assert.deepEqual(result.output, expected);
          const {backend, timings, ...observation} = result;
          if (name === 'before') reference = observation;
          else {
            assert.equal(backend, 'checked-plan-wasm-v1');
            if (sample) assert.equal(timings.reused_compilation, true);
            if (!sample) firstAfter = {request_ms: observed.milliseconds, ...timings};
          }
          // Order alternates; compare corresponding results after both execute.
          (samples.observations ??= {})[name] = observation;
          if (Object.keys(samples.observations).length === 2) {
            assert.deepEqual(samples.observations.before, samples.observations.after);
            samples.observations = {};
          }
          if (sample) samples[name].push(observed.milliseconds);
        }
      }
      delete samples.observations;
      const medians = Object.fromEntries(Object.entries(samples).map(([name, values]) => [name, [...values].sort((a, b) => a - b)[2]]));
      report.cases.push({height: h, width: w, cap: 64, mode, first_compiled_request: firstAfter, samples_ms: samples, median_ms: medians, ratio: medians.before / medians.after, observations_and_plan_reports_identical: true, independent_formula_matches: true});
      console.log(`${h}x${w} ${mode}: ${medians.before.toFixed(1)} -> ${medians.after.toFixed(1)} ms`);
    }
    assert.deepEqual(errors, []);
    fs.writeFileSync(process.argv[4], JSON.stringify(report, null, 2) + '\n');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
