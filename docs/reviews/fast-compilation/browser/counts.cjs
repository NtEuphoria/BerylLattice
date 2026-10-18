const fs = require('node:fs');
const crypto = require('node:crypto');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require('/opt/codex/cua_node/lib/node_modules/playwright-core');

(async () => {
  const browser = await chromium.launch({executablePath: '/usr/bin/chromium', headless: true, args: ['--no-sandbox']});
  try {
    const page = await browser.newPage();
    await page.goto('http://127.0.0.1:38067/beryl-compile-research/browser/');
    await page.evaluate(() => {
      const worker = new Worker('./counts-worker.js');
      let serial = 0;
      const pending = new Map();
      worker.onmessage = ({data}) => {
        const {resolve, reject, timer} = pending.get(data.id);
        pending.delete(data.id);
        clearTimeout(timer);
        data.error ? reject(new Error(data.error)) : resolve(data.result);
      };
      window.countsCall = (method, source) => new Promise((resolve, reject) => {
        const id = ++serial;
        const timer = setTimeout(() => reject(new Error('counts worker timed out')), 120000);
        pending.set(id, {resolve, reject, timer});
        worker.postMessage({id, method, source});
      });
    });
    const boot = await page.evaluate(() => window.countsCall('boot'));
    const measured = JSON.parse(fs.readFileSync(path.join(__dirname, 'phase-results.json')));
    const report = {browser: browser.version(), runtime: boot.runtime, python: boot.python,
      scope: 'Separate cProfile run for call counts only. These runs are excluded from phase timing samples.',
      compiler_archive: measured.files['beryl-compiler.zip'],
      harness_sha256: Object.fromEntries(['counts.cjs', 'counts-worker.js', 'worker.js'].map(filename => [filename,
        crypto.createHash('sha256').update(fs.readFileSync(path.join(__dirname, filename))).digest('hex')])),
      cases: []};
    for (const item of measured.cases) {
      const source = item.samples[0].source;
      const observation = await page.evaluate(source => window.countsCall('counts', source), source);
      assert.equal(observation.status, 'prepared');
      report.cases.push({height: item.height, width: item.width, cap: item.cap, ...observation});
    }
    report.status = 'passed';
    fs.writeFileSync(path.join(__dirname, 'call-counts.json'), JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify(report, null, 2));
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
