#!/usr/bin/env node
/* Research-only browser compilation audit. No product Worker changes or monkeypatching. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const http = require('node:http');
const os = require('node:os');
const {execFileSync} = require('node:child_process');
const {performance} = require('node:perf_hooks');
const ROOT = path.resolve(__dirname, '../..');
const sha256 = value => crypto.createHash('sha256').update(value).digest('hex');
const CSP = "default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; connect-src 'self'; worker-src 'self'; style-src 'self'; img-src 'self'; base-uri 'none'";

function parseArgs(argv) {
  const args = {samples: 21, mode: 'engine-cold', fixtureSet: 'qualification', diagnostics: false,
    chromium: process.env.CHROMIUM || '/usr/bin/chromium', python: process.env.PYTHON || 'python3',
    fixtureIds: []};
  const fields = {'--site': 'site', '--baseline-site': 'baselineSite', '--output': 'output',
    '--mode': 'mode', '--samples': 'samples', '--fixture-set': 'fixtureSet',
    '--chromium': 'chromium', '--python': 'python', '--playwright': 'playwright'};
  for (let index = 0; index < argv.length; index++) {
    const flag = argv[index];
    if (flag === '--diagnostics') { args.diagnostics = true; continue; }
    if (flag === '--fixture-id') { args.fixtureIds.push(argv[++index]); continue; }
    if (!Object.hasOwn(fields, flag) || argv[index + 1] === undefined) throw new Error(`unknown/missing option ${flag}`);
    args[fields[flag]] = argv[++index];
  }
  args.samples = Number(args.samples);
  if (!Number.isInteger(args.samples) || args.samples < 1) throw new Error('samples must be a positive integer');
  if (!['engine-cold', 'source-fresh'].includes(args.mode)) throw new Error('mode must be engine-cold or source-fresh');
  if (!['qualification', 'boundary', 'smoke'].includes(args.fixtureSet)) throw new Error('unknown fixture-set');
  return args;
}

function sampleSource(fixture, nonce) {
  return `${fixture.source}// fresh source sample ${nonce}\n`;
}

function summarize(samples) {
  const names = new Set(samples.flatMap(sample => Object.keys(sample.phases)));
  return Object.fromEntries([...names].map(name => {
    const values = samples.map(sample => sample.phases[name]?.elapsed_ms).filter(Number.isFinite).sort((a, b) => a - b);
    const middle = Math.floor(values.length / 2);
    return [name, values.length % 2 ? values[middle] : (values[middle - 1] + values[middle]) / 2];
  }));
}

const {localCount} = require('./compilation-wasm.js');

function describeSite(directory) {
  const filenames = ['runtime-config.json', 'release-manifest.json', 'beryl-compiler.zip'];
  const config = JSON.parse(fs.readFileSync(path.join(directory, 'runtime-config.json')));
  if (/^https?:/.test(config.indexURL)) throw new Error('research audit requires self-hosted runtime, not a CDN');
  for (const name of ['pyodide.js', 'pyodide.asm.js', 'pyodide.asm.wasm', 'python_stdlib.zip', 'pyodide-lock.json']) {
    filenames.push(path.posix.join(config.indexURL, name));
  }
  return Object.fromEntries(filenames.map(filename => {
    const data = fs.readFileSync(path.join(directory, filename));
    return [filename, {bytes: data.length, sha256: sha256(data)}];
  }));
}

async function serve(sites, servedFiles) {
  const server = http.createServer((request, response) => {
    try {
      const pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
      response.setHeader('Content-Security-Policy', CSP);
      response.setHeader('Cache-Control', 'no-store');
      if (pathname === '/') {
        response.setHeader('Content-Type', 'text/html');
        response.end('<!doctype html><meta charset="utf-8"><title>Compilation research</title>');
        return;
      }
      let filename;
      if (['/compilation-worker.js', '/compilation-wasm.js'].includes(pathname)) filename = path.join(__dirname, pathname.slice(1));
      else {
        const [, site, ...relative] = pathname.split('/');
        if (!Object.hasOwn(sites, site)) throw new Error('unknown site');
        filename = path.resolve(sites[site], ...relative);
        if (!filename.startsWith(path.resolve(sites[site]) + path.sep)) throw new Error('outside site');
      }
      const data = fs.readFileSync(filename);
      servedFiles[pathname] = {bytes: data.length, sha256: sha256(data)};
      response.setHeader('Content-Type', filename.endsWith('.wasm') ? 'application/wasm'
        : /\.(?:js|cjs)$/.test(filename) ? 'text/javascript' : filename.endsWith('.json') ? 'application/json' : 'application/octet-stream');
      response.end(data);
    } catch (_) { response.writeHead(404); response.end(); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  return {server, origin: `http://127.0.0.1:${server.address().port}`};
}

async function launch(chromium, args, origin) {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'beryl-compilation-profile-'));
  let context;
  try {
    context = await chromium.launchPersistentContext(profile, {executablePath: args.chromium,
      headless: true, args: ['--no-sandbox', '--enable-automation']});
    const page = context.pages()[0] || await context.newPage();
    const cdp = await context.newCDPSession(page);
    const commandLine = await cdp.send('Browser.getBrowserCommandLine');
    const engineIdentity = await cdp.send('Browser.getVersion');
    await cdp.detach();
    const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.goto(origin);
    await page.evaluate(() => {
      const worker = new Worker('/compilation-worker.js');
      let serial = 0;
      const pending = new Map();
      worker.onmessage = ({data}) => {
        const waiter = pending.get(data.id);
        if (!waiter) return;
        pending.delete(data.id);
        clearTimeout(waiter.timer);
        data.error ? waiter.reject(new Error(data.error)) : waiter.resolve(data.result);
      };
      worker.onerror = event => {
        for (const waiter of pending.values()) { clearTimeout(waiter.timer); waiter.reject(new Error(event.message)); }
        pending.clear();
      };
      window.compilationCall = (method, payload) => new Promise((resolve, reject) => {
        const id = ++serial;
        const timer = setTimeout(() => { pending.delete(id); reject(new Error('research Worker timeout')); }, 180000);
        pending.set(id, {resolve, reject, timer});
        worker.postMessage({id, method, payload});
      });
    });
    return {context, page, errors, profile, commandLine, engineIdentity, close: async () => {
      try { await context.close(); } finally { fs.rmSync(profile, {recursive: true, force: true}); }
    }};
  } catch (error) {
    if (context) await context.close();
    fs.rmSync(profile, {recursive: true, force: true});
    throw error;
  }
}

async function main(argv = process.argv.slice(2)) {
  const args = parseArgs(argv);
  if (!args.site || !args.output || fs.existsSync(args.output)) throw new Error('--site and new --output path are required');
  let engine;
  if (args.playwright) engine = require(args.playwright);
  else {
    try { engine = require('playwright-core'); }
    catch (_) { engine = require('/opt/codex/cua_node/lib/node_modules/playwright-core'); }
  }
  const fixtureArgs = [path.join(ROOT, 'tools/profile-compilation.py'), '--list-fixtures', '--fixture-set', args.fixtureSet];
  for (const id of args.fixtureIds) fixtureArgs.push('--fixture-id', id);
  const fixtures = JSON.parse(execFileSync(args.python, fixtureArgs, {encoding: 'utf8'}));
  const sites = {candidate: path.resolve(args.site)};
  if (args.baselineSite) sites.baseline = path.resolve(args.baselineSite);
  const servedFiles = {};
  const report = {schema_version: 1, created_utc: new Date().toISOString(), status: 'running',
    mode: args.mode, samples: args.samples, fixture_set: args.fixtureSet, timing_unit: 'ms', timing_semantics: 'inclusive',
    scope: 'Source-fresh preparation after runtime/import readiness, Python bridge/emission plus JS Wasm compile/instantiate; runtime boot, first execution and original-AST/external verification retained separately. No warmup of the user program.',
    engine_cache_scope: args.mode === 'engine-cold'
      ? 'Fresh browser process, new temporary persistent profile and new Worker per case/sample/revision. Runtime boot/imports precede the first user program; engine may perform lazy work during first execution.'
      : 'One browser process/profile/Worker per revision. Comment nonces change source identity but may emit identical modules. Engine code reuse is uncontrolled; a fresh source is not an engine-cold sample.',
    sites: Object.fromEntries(Object.entries(sites).map(([name, directory]) => [name, {directory, files: describeSite(directory)}])),
    browser_executable: {path: path.resolve(args.chromium), sha256: sha256(fs.readFileSync(args.chromium)),
      requested_arguments: ['--headless', '--no-sandbox', '--enable-automation'], note: 'Selected launcher identity; system Chromium launchers may be wrapper scripts.'},
    host: {platform: os.platform(), release: os.release(), arch: os.arch(), node: process.version, cpus: os.cpus().length, cpu_model: os.cpus()[0]?.model},
    harness_sha256: Object.fromEntries(['compilation.cjs', 'compilation-worker.js', 'compilation-wasm.js'].map(name => [name, sha256(fs.readFileSync(path.join(__dirname, name)))])),
    fixtures, rounds: [], cases: {}, served_files: servedFiles};
  const {server, origin} = await serve(sites, servedFiles);
  const retained = {};
  fs.mkdirSync(path.dirname(path.resolve(args.output)), {recursive: true});
  const write = () => fs.writeFileSync(args.output, JSON.stringify(report, null, 2) + '\n');
  try {
    for (let round = 0; round < args.samples; round++) {
      const names = Object.keys(sites);
      if (round % 2) names.reverse();
      const roundRecord = {round, order: names, samples: []};
      report.rounds.push(roundRecord);
      for (const fixture of fixtures.slice(round % fixtures.length).concat(fixtures.slice(0, round % fixtures.length))) {
        // Equal source bytes for both revisions within each pair.
        const nonce = crypto.randomBytes(8).toString('hex');
        const source = sampleSource(fixture, nonce);
        for (const name of names) {
          let session = args.mode === 'source-fresh' ? retained[name] : null;
          const launched = !session;
          const appStart = performance.now();
          if (!session) {
            session = await launch(engine.chromium, args, origin);
            report.browser = session.context.browser().version();
            report.engine_identity = session.engineIdentity;
            try {
              session.boot = await session.page.evaluate(payload => window.compilationCall('boot', payload), {
                site: `${origin}/${name}/`, archive_sha256: report.sites[name].files['beryl-compiler.zip'].sha256});
            } catch (error) {
              await session.close();
              throw error;
            }
            session.browserLaunchAndBootMs = performance.now() - appStart;
            if (args.mode === 'source-fresh') retained[name] = session;
          }
          try {
            const observed = await session.page.evaluate(payload => window.compilationCall('prepare', payload), {source});
            assert.equal(observed.metadata.source_digest, sha256(Buffer.from(source)));
            assert.equal(observed.metadata.shape.height, fixture.height);
            assert.equal(observed.metadata.shape.width, fixture.width);
            const executions = [];
            for (const iteration of [0, 1]) executions.push(await session.page.evaluate(payload => window.compilationCall('execute', payload), {iteration}));
            const sample = {revision: name, fixture_id: fixture.id, round, nonce, source,
              browser_process_fresh: launched, temporary_profile_fresh: launched,
              browser_command_line: session.commandLine.arguments,
              total_app_boot: session.boot, browser_launch_and_boot_ms: session.browserLaunchAndBootMs,
              ...observed, executions};
            sample.phases.first_execution = {elapsed_ms: executions[0].execution_ms, calls: 1};
            sample.phases.verification = {elapsed_ms: executions[0].verification_ms, calls: 1};
            if (args.diagnostics && round === 0) {
              sample.diagnostic = await session.page.evaluate(payload => window.compilationCall('diagnose', payload), {source});
            }
            assert.deepEqual(session.errors, []);
            roundRecord.samples.push(sample);
            const key = `${name}:${fixture.id}`;
            (report.cases[key] ||= {revision: name, fixture, samples: []}).samples.push(sample);
            write();
            console.log(`${name} ${fixture.id} ${round + 1}/${args.samples}: ${observed.phases.total_fresh_source_preparation.elapsed_ms.toFixed(1)}ms`);
          } finally {
            if (args.mode === 'engine-cold') await session.close();
          }
        }
      }
    }
    for (const item of Object.values(report.cases)) {
      item.median_ms = summarize(item.samples);
      item.module_digests = [...new Set(item.samples.map(sample => sample.metadata.module_digest))];
      item.source_digests = [...new Set(item.samples.map(sample => sample.metadata.source_digest))];
    }
    // Every served file is audited against its local bytes, including dynamic runtime dependencies.
    for (const [pathname, identity] of Object.entries(servedFiles)) {
      const [, name, ...relative] = pathname.split('/');
      const filename = ['/compilation-worker.js', '/compilation-wasm.js'].includes(pathname) ? path.join(__dirname, pathname.slice(1)) : path.join(sites[name], ...relative);
      assert.equal(identity.sha256, sha256(fs.readFileSync(filename)));
    }
    report.served_file_audit = 'passed';
    report.status = 'passed';
  } catch (error) {
    report.status = 'failed';
    report.error = String(error.stack || error);
    throw error;
  } finally {
    for (const session of Object.values(retained)) await session.close();
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
    report.finished_utc = new Date().toISOString();
    write();
  }
}

module.exports = {parseArgs, sampleSource, summarize, localCount, main};
if (require.main === module) main().catch(error => {console.error(error); process.exitCode = 1;});
