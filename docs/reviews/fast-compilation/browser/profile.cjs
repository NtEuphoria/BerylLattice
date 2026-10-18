const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const os = require('node:os');
const {chromium} = require('/opt/codex/cua_node/lib/node_modules/playwright-core');

const root = '/workspace/scratch/beryl-compiled/site-release';
const output = process.argv[2] || path.join(__dirname, 'phase-results.json');
const sha256 = value => crypto.createHash('sha256').update(value).digest('hex');
const describe = filename => {
  const bytes = fs.readFileSync(path.join(root, filename));
  return {bytes: bytes.length, sha256: sha256(bytes)};
};
const median = values => [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)];

(async () => {
  const files = ['runtime-config.json', 'release-manifest.json', 'beryl-compiler.zip',
    'worker.js', 'runtime/pyodide.js', 'runtime/pyodide.asm.js', 'runtime/pyodide.asm.wasm',
    'runtime/python_stdlib.zip', 'runtime/pyodide-lock.json'];
  const report = {schema_version: 1, started_utc: new Date().toISOString(),
    scope: 'Fresh-source compilation with runtime/imports already loaded; exact unmodified release ZIP; five nonce-distinct sources per case. Python wrappers record inclusive production stage timings. No artifact/module reuse by harness. JS engine-internal Wasm compilation caching is uncontrolled, because comment nonces preserve generated module bytes. Startup, formula verification and filesystem hashing are excluded from compilation timings.',
    host: {platform: os.platform(), release: os.release(), arch: os.arch(), cpus: os.cpus().length,
      cpu_model: os.cpus()[0]?.model, node: process.version},
    site_root: root, files: Object.fromEntries(files.map(filename => [filename, describe(filename)])),
    harness_sha256: Object.fromEntries(['profile.cjs', 'worker.js', 'index.html'].map(filename => [filename,
      sha256(fs.readFileSync(path.join(__dirname, filename)))])),
    cases: [], errors: []};
  const browser = await chromium.launch({executablePath: '/usr/bin/chromium', headless: true,
    args: ['--no-sandbox']});
  report.browser = browser.version();
  try {
    const page = await browser.newPage();
    page.on('pageerror', error => report.errors.push(String(error)));
    await page.goto('http://127.0.0.1:38067/beryl-compile-research/browser/');
    await page.evaluate(() => {
      const worker = new Worker('./worker.js');
      let serial = 0;
      const pending = new Map();
      worker.onmessage = ({data}) => {
        const {resolve, reject, timer} = pending.get(data.id);
        pending.delete(data.id);
        clearTimeout(timer);
        data.error ? reject(new Error(data.error)) : resolve(data.result);
      };
      window.profileCall = (method, source) => new Promise((resolve, reject) => {
        const id = ++serial;
        const timer = setTimeout(() => reject(new Error('worker timed out')), 120000);
        pending.set(id, {resolve, reject, timer});
        worker.postMessage({id, method, source});
      });
    });
    report.boot = await page.evaluate(() => window.profileCall('boot'));
    const base = report.boot.examples.examples[0].source;
    const definitions = [[1, 1, 64], [5, 7, 64], [15, 15, 64], [15, 15, 128]];
    report.cases = definitions.map(([height, width, cap]) => ({height, width, cap, samples: []}));
    for (let round = 0; round < 5; round++) {
      for (let offset = 0; offset < definitions.length; offset++) {
        const index = (round + offset) % definitions.length;
        const item = report.cases[index];
        const nonce = crypto.randomBytes(8).toString('hex');
        const source = base.replace('H = 5;', `H = ${item.height};`)
          .replace('W = 7;', `W = ${item.width};`)
          .replace('plan_workspace_bytes <= 64;', `plan_workspace_bytes <= ${item.cap};`)
          + `\n// fresh compilation nonce ${nonce}\n`;
        const observed = await page.evaluate(source => window.profileCall('prepare', source), source);
        assert.equal(observed.source_sha256, sha256(Buffer.from(source)));
        assert.equal(observed.result.source_digest, observed.source_sha256);
        assert.equal(observed.result.shape.height, item.height);
        assert.equal(observed.result.shape.width, item.width);
        assert.equal(observed.result.workspace_cap, item.cap);
        assert.equal(observed.result.selected.plan_id, item.height === 15 && item.cap === 64
          || item.height === 1 ? 'inline-v1' : 'rows2-v1');
        item.samples.push({round, chronological_sample: round * 4 + offset, nonce, source, ...observed});
        fs.writeFileSync(output, JSON.stringify(report, null, 2) + '\n');
        console.log(`${item.height}x${item.width} cap${item.cap} sample${round + 1}: ${observed.phases.worker_compilation_total_ms.toFixed(1)}ms`);
      }
    }
    for (const item of report.cases) {
      const keys = Object.keys(item.samples[0].phases);
      item.median_ms = Object.fromEntries(keys.map(key => [key, median(item.samples.map(sample => sample.phases[key]))]));
      item.module_digests = [...new Set(item.samples.map(sample => sample.result.module_digest))];
      assert.equal(new Set(item.samples.map(sample => sample.source_sha256)).size, 5);
    }
    assert.deepEqual(report.errors, []);
    report.finished_utc = new Date().toISOString();
    report.status = 'passed';
    fs.writeFileSync(output, JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify(report.cases.map(({height, width, cap, median_ms}) => ({height, width, cap, median_ms})), null, 2));
  } catch (error) {
    report.status = 'failed';
    report.errors.push(String(error.stack || error));
    fs.writeFileSync(output, JSON.stringify(report, null, 2) + '\n');
    throw error;
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
