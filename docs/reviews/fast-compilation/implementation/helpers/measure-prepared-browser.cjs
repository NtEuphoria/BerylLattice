#!/usr/bin/env node
'use strict';
// Scratch audit harness. Historical docs/reviews/compiled-execution/browser-compare.cjs is unchanged.
// Run only after the controller's full suite, serially with other performance work.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const {execFileSync} = require('node:child_process');
const playwrightPath = '/opt/codex/cua_node/lib/node_modules/playwright-core';
const {chromium} = require(playwrightPath);
const sha256 = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const fingerprint = bytes => ({bytes: bytes.length, sha256: sha256(bytes)});
const fileIdentity = name => ({path: fs.realpathSync(name), ...fingerprint(fs.readFileSync(name))});
const labels = ['baseline', 'candidate'];
const expectedVersions = {baseline: {backend: 'checked-plan-wasm-v1', schema_version: 1},
  candidate: {backend: 'checked-plan-wasm-v2', schema_version: 2}};
const equivalentFields = ['status', 'source_digest', 'shape', 'objective', 'workspace_cap', 'selected',
  'input', 'output', 'comparison', 'first_bad_index', 'diagnostic'];

function argumentsFrom(argv) {
  const options = {};
  for (let i = 0; i < argv.length; i += 2) {
    assert.match(argv[i], /^--(?:baseline-url|baseline-site|candidate-url|candidate-site|samples|output)$/);
    assert.ok(argv[i + 1] && !argv[i + 1].startsWith('--'), `Missing value for ${argv[i]}`);
    assert.ok(!(argv[i].slice(2) in options), `Duplicate ${argv[i]}`);
    options[argv[i].slice(2)] = argv[i + 1];
  }
  for (const name of ['baseline-url', 'baseline-site', 'candidate-url', 'candidate-site', 'output']) {
    assert.ok(options[name], `Required --${name}`);
  }
  options.samples = Number(options.samples ?? 21);
  assert.equal(options.samples, 21, 'This qualification guard requires exactly 21 measured pairs');
  return options;
}

async function responseBytes(url) {
  const response = await fetch(url, {cache: 'no-store', signal: AbortSignal.timeout(120000)});
  assert.equal(response.status, 200, `HTTP status for ${url}`);
  return Buffer.from(await response.arrayBuffer());
}

async function verifySite(url, directory) {
  const base = new URL(url);
  assert.match(base.protocol, /^https?:$/);
  // URL denotes a directory, not index.html; keep module-relative assets unambiguous.
  assert.ok(base.pathname.endsWith('/'), 'Site URL must end in /');
  const manifestBytes = fs.readFileSync(path.join(directory, 'release-manifest.json'));
  const manifest = JSON.parse(manifestBytes);
  assert.equal(manifest.schema_version, 1);
  assert.deepEqual(await responseBytes(new URL('release-manifest.json', base)), manifestBytes,
    'Served and local release manifests differ');
  const files = {'release-manifest.json': fingerprint(manifestBytes)};
  for (const [name, expected] of Object.entries(manifest.files)) {
    assert.ok(!path.isAbsolute(name) && !name.split('/').includes('..'), 'Unsafe manifest file');
    const local = fs.readFileSync(path.join(directory, name));
    assert.deepEqual(fingerprint(local), expected, `Local release file mismatch: ${name}`);
    assert.deepEqual(fingerprint(await responseBytes(new URL(name, base))), expected,
      `Served release file mismatch: ${name}`);
    files[name] = expected;
  }
  // Independently inspect all ZIP members without importing or executing compiler modules.
  const archiveMembers = JSON.parse(execFileSync('python', ['-c', `
import hashlib,json,sys,zipfile
with zipfile.ZipFile(sys.argv[1]) as archive:
    names=archive.namelist()
    assert len(names)==len(set(names)), 'duplicate archive member'
    print(json.dumps({name:dict(bytes=len(archive.read(name)),sha256=hashlib.sha256(archive.read(name)).hexdigest()) for name in names}))
`, path.join(directory, 'beryl-compiler.zip')], {encoding: 'utf8'}));
  assert.deepEqual(archiveMembers, manifest.compiler_archive_members, 'Compiler ZIP member mismatch');
  for (const [name, expected] of Object.entries(manifest.compiler_modules)) {
    assert.deepEqual(archiveMembers[name], expected, `Compiler module mismatch: ${name}`);
  }
  const runtimeConfig = JSON.parse(fs.readFileSync(path.join(directory, 'runtime-config.json')));
  assert.deepEqual(runtimeConfig, manifest.runtime);
  return {url: base.href, directory: fs.realpathSync(directory), files, archive_members: archiveMembers,
    runtime: runtimeConfig, served_files_verified_before_measurement: true};
}

function dataFor(h, w, mode, sample) {
  return Array.from({length: (h + 1) * (w + 1)}, (_, i) => mode === 'ramp'
    ? (i + 37 * (sample + 1)) % 1024
    : (1023 * ((Math.floor(i / (w + 1)) + i % (w + 1)) % 2) + 37 * (sample + 1)) % 1024);
}

function formula(h, w, input) {
  const output = [];
  for (let r = 0; r < h; r++) for (let c = 0; c < w; c++) {
    const i = r * (w + 1) + c;
    output.push([i, i + 1, i + w + 1, i + w + 2].reduce((sum, j) => sum + (input[j] + 1) ** 2, 0));
  }
  return output;
}

function auditVersion(result, label) {
  for (const [key, expected] of Object.entries(expectedVersions[label])) assert.equal(result[key], expected);
}

function auditPreparation(result, label, source, h, w) {
  auditVersion(result, label);
  assert.equal(result.status, 'prepared');
  assert.equal(result.source_digest, sha256(Buffer.from(source, 'utf8')));
  assert.deepEqual(result.shape, {height: h, width: w, input_height: h + 1, input_width: w + 1});
  assert.equal(result.reused_compilation, false, 'Each case must explicitly build before measurement');
  assert.ok(result.compilation_ms > 0 && Number.isFinite(result.compilation_ms));
  assert.equal(result.initial_compilation_ms, result.compilation_ms);
  assert.equal(result.plan_digest, result.selected.plan_digest);
  assert.match(result.module_digest, /^[0-9a-f]{64}$/);
}

function auditObservation(observed, label, request, prepared, h, w) {
  const result = observed.result;
  auditVersion(result, label);
  assert.ok(Number.isFinite(observed.milliseconds) && observed.milliseconds > 0);
  assert.equal(result.status, 'success');
  assert.equal(result.source_digest, sha256(Buffer.from(request.source, 'utf8')));
  assert.deepEqual(result.shape, prepared.shape);
  assert.deepEqual(result.selected, prepared.selected);
  assert.equal(result.objective, 'multiplication_ops');
  assert.equal(result.workspace_cap, 64);
  assert.deepEqual(result.input, request.inputs);
  assert.deepEqual(result.output, formula(h, w, request.inputs)); // Outside browser timing.
  assert.deepEqual(result.comparison, {matches: true, cells_compared: h * w});
  assert.equal(result.first_bad_index, null);
  assert.equal(result.diagnostic, null);
  assert.equal(result.timings.reused_compilation, true);
  assert.equal(result.timings.compilation_ms, 0);
  assert.equal(result.timings.initial_compilation_ms, prepared.initial_compilation_ms);
  for (const key of ['execution_ms', 'verification_ms']) {
    assert.ok(Number.isFinite(result.timings[key]) && result.timings[key] >= 0);
  }
}

function auditPair(pair) {
  for (const field of equivalentFields) {
    assert.deepEqual(pair.baseline.result[field], pair.candidate.result[field], `Paired ${field}`);
  }
  // Search policy, proof-state fields, attempt counts and work_used have changed meaning.
  // Only shared, available structural cost numbers are equivalent across report schemas.
  const before = new Map(pair.baseline.result.attempts.map(attempt => [attempt.plan_id, attempt]));
  for (const attempt of pair.candidate.result.attempts) {
    const old = before.get(attempt.plan_id);
    if (!old) continue;
    for (const key of ['workspace_bytes', 'multiplication_ops']) {
      if (typeof old[key] === 'number' && typeof attempt[key] === 'number') {
        assert.equal(old[key], attempt[key], `Equivalent ${attempt.plan_id}.${key}`);
      }
    }
  }
}

function stats(values) {
  const sorted = [...values].sort((a, b) => a - b);
  return {median_ms: sorted[10], p95_ms: sorted[Math.ceil(0.95 * sorted.length) - 1],
    p95_method: 'nearest rank ceil(0.95*n)', count: values.length};
}

async function main() {
  const options = argumentsFrom(process.argv.slice(2));
  // An existing output is never overwritten. Once created, failure progress is retained.
  const output = fs.openSync(options.output, 'wx', 0o600);
  const report = {schema_version: 1, status: 'running', created_utc: new Date().toISOString(),
    samples_per_case: 21, discarded_warmup_pairs_per_case: 1,
    performance_guard: {maximum_candidate_over_baseline_median: 1.10, all_six_cases_required: true},
    timing_noise: 'Single-host timing is noisy. All 21 raw pairs and the identified discarded warmup are retained; no retries, outlier removal or sample replacement. Ratios and the 10% median guard are descriptive measurements, not a statistical significance claim. Progress snapshots are fsynced outside request timers.',
    scope: 'Verified PREPARED browser request latency through actual UI transport.runDemo. Timer includes envelope/scalar validation, transfer, Wasm execution, observation acquisition and fresh retained original-AST verification. Explicit prepareDemo compilation and external formula auditing are outside timed requests.',
    cache_scope: 'One browser process, one context, two pages and one reused public application Worker per page. Runtime/import readiness precedes all preparation. User sources are explicitly prepared once per case, then one warmup pair is discarded. Chromium engine/code/HTTP caches may be warm and are not reset; no engine-cold claim.',
    comparison_scope: {equivalent_fields: equivalentFields,
      additional_metrics: 'Shared available numeric attempt workspace_bytes and multiplication_ops',
      preserved_but_not_equal: 'backend/schema_version, module bytes/digest, lowering metadata and search reports including attempt proof states, policy, counts, work_used'},
    options, sites: {}, cases: [], page_errors: [], worker_events: []};
  const save = () => {
    const bytes = Buffer.from(JSON.stringify(report, null, 2) + '\n');
    fs.writeSync(output, bytes, 0, bytes.length, 0);
    fs.ftruncateSync(output, bytes.length);
    fs.fsyncSync(output);
  };
  let browser;
  try {
    report.harness = fileIdentity(__filename);
    report.historical_reference = fileIdentity('/workspace/BerylLattice-o3-fixes/docs/reviews/compiled-execution/browser-compare.cjs');
    report.node = process.version;
    report.playwright = {path: playwrightPath, version: require(path.join(playwrightPath, 'package.json')).version};
    report.chromium_files = ['/usr/bin/chromium', '/usr/lib/chromium/chromium'].filter(fs.existsSync).map(fileIdentity);
    report.host = {hostname: os.hostname(), platform: os.platform(), release: os.release(), arch: os.arch(),
      cpu_model: os.cpus()[0]?.model, logical_cpus: os.cpus().length, total_memory_bytes: os.totalmem(), initial_load_average: os.loadavg()};
    save();
    for (const label of labels) {
      report.sites[label] = await verifySite(options[`${label}-url`], options[`${label}-site`]);
      save();
    }
    const launch = {executablePath: '/usr/bin/chromium', headless: true, args: ['--no-sandbox']};
    browser = await chromium.launch(launch);
    report.browser = {version: browser.version(), launch};
    const context = await browser.newContext();
    const pages = {};
    const workers = {baseline: 0, candidate: 0};
    for (const label of labels) {
      const page = await context.newPage();
      pages[label] = page;
      page.on('pageerror', error => report.page_errors.push({label, error: String(error)}));
      page.on('worker', worker => {
        workers[label]++;
        report.worker_events.push({label, url: worker.url(), created_utc: new Date().toISOString()});
      });
      const start = Date.now();
      await page.goto(options[`${label}-url`]);
      await page.waitForFunction(() => document.querySelector('#examples button')
        && !document.querySelector('#run').disabled, null, {timeout: 120000});
      const readiness = await page.evaluate(async () => {
        if (document.documentElement.dataset.runtime !== 'browser') throw new Error('Browser runtime required');
        window.preparedGuardTransport = await import('./transport.js');
        window.preparedGuardExamples = await window.preparedGuardTransport.getExamples();
        return {examples: window.preparedGuardExamples, user_agent: navigator.userAgent,
          hardware_concurrency: navigator.hardwareConcurrency};
      });
      report.sites[label].readiness = {...readiness, elapsed_wall_ms: Date.now() - start};
      assert.equal(workers[label], 1, 'Exactly one public application Worker expected');
      save();
    }
    const template = report.sites.baseline.readiness.examples.examples.find(example => example.id === 'balanced').source;
    assert.equal(report.sites.candidate.readiness.examples.examples.find(example => example.id === 'balanced').source, template);
    assert.equal((template.match(/shape H = 5;/g) ?? []).length, 1);
    assert.equal((template.match(/shape W = 7;/g) ?? []).length, 1);
    assert.match(template, /require plan_workspace_bytes <= 64;/);
    report.baseline_source_template = {source: template, ...fingerprint(Buffer.from(template, 'utf8'))};
    // Changing shapes between cases ensures prepareDemo cannot hit its single-source cache.
    for (const mode of ['ramp', 'checkerboard']) for (const [h, w] of [[1, 1], [5, 7], [15, 15]]) {
      const source = template.replace('shape H = 5;', `shape H = ${h};`).replace('shape W = 7;', `shape W = ${w};`);
      const record = {height: h, width: w, cap: 64, mode, source,
        source_utf8_sha256: sha256(Buffer.from(source, 'utf8')), preparations: {}, pairs: []};
      report.cases.push(record);
      for (const label of labels) {
        const request = {source, input_mode: 'custom', inputs: dataFor(h, w, mode, -1)};
        const prepared = await pages[label].evaluate(async request => {
          const start = performance.now();
          const result = await window.preparedGuardTransport.prepareDemo(request);
          return {milliseconds: performance.now() - start, result};
        }, request);
        record.preparations[label] = prepared;
        save();
        auditPreparation(prepared.result, label, source, h, w);
      }
      for (const field of ['source_digest', 'shape', 'selected', 'plan_digest']) {
        assert.deepEqual(record.preparations.baseline.result[field], record.preparations.candidate.result[field]);
      }
      for (let sample = -1; sample < options.samples; sample++) {
        const order = sample % 2 === 0 ? ['baseline', 'candidate'] : ['candidate', 'baseline'];
        const request = {source, input_mode: 'custom', inputs: dataFor(h, w, mode, sample)};
        const pair = {sample, discarded_warmup: sample === -1, order, request, observations: {}};
        record.pairs.push(pair);
        for (const label of order) {
          const observed = await pages[label].evaluate(async request => {
            const start = performance.now();
            const result = await window.preparedGuardTransport.runDemo(request);
            return {milliseconds: performance.now() - start, result};
          }, request);
          pair.observations[label] = observed;
          save();
          auditObservation(observed, label, request, record.preparations[label].result, h, w);
          assert.equal(workers[label], 1, 'Worker reset invalidates prepared timing');
          assert.deepEqual(report.page_errors, []);
        }
        auditPair(pair.observations);
        pair.independent_formula_and_paired_audit_passed = true;
        pair.candidate_over_baseline = pair.observations.candidate.milliseconds / pair.observations.baseline.milliseconds;
        save();
      }
      record.samples_ms = Object.fromEntries(labels.map(label => [label,
        record.pairs.filter(pair => !pair.discarded_warmup).map(pair => pair.observations[label].milliseconds)]));
      record.summary = Object.fromEntries(labels.map(label => [label, stats(record.samples_ms[label])]));
      record.summary.candidate_over_baseline = {
        median: record.summary.candidate.median_ms / record.summary.baseline.median_ms,
        p95: record.summary.candidate.p95_ms / record.summary.baseline.p95_ms};
      record.summary.performance_guard_passed = record.summary.candidate_over_baseline.median <= 1.10;
      console.log(`${h}x${w} ${mode}: median ${record.summary.baseline.median_ms.toFixed(3)} -> ${record.summary.candidate.median_ms.toFixed(3)} ms; candidate/baseline ${record.summary.candidate_over_baseline.median.toFixed(3)}`);
      save();
    }
    assert.deepEqual(report.page_errors, []);
    report.host.final_load_average = os.loadavg();
    report.performance_guard_failures = report.cases.filter(record => !record.summary.performance_guard_passed)
      .map(record => ({height: record.height, width: record.width, mode: record.mode,
        candidate_over_baseline_median: record.summary.candidate_over_baseline.median}));
    assert.deepEqual(report.performance_guard_failures, [], 'Candidate median exceeds 1.10 baseline median; all raw cases retained');
    report.status = 'passed';
    report.completed_utc = new Date().toISOString();
    save();
  } catch (error) {
    report.status = 'failed';
    report.failure = {message: String(error), stack: error.stack};
    report.completed_utc = new Date().toISOString();
    save();
    throw error;
  } finally {
    if (browser) await browser.close();
    fs.closeSync(output);
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
