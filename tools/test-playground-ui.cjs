#!/usr/bin/env node
/* No browser dependencies: exercise UI races and transport cancellation boundaries. */
const assert = require('node:assert/strict');
const { getEventListeners } = require('node:events');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const web = path.join(__dirname, '../axiom/src/axiom/playground_web');
const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
const appSource = fs.readFileSync(path.join(web, 'app.js'), 'utf8').replace(/^import .*;\r?\n/, '');
const transportSource = fs.readFileSync(path.join(web, 'transport.js'), 'utf8')
  .replace(/export async function/g, 'async function')
  .replace(/import\.meta\.url/g, '"http://localhost/transport.js"');
const examples = [
  { id: 'balanced', title: 'Default', description: 'Default example', source: 'default source' },
  { id: 'no-scratch', title: 'Inline', description: 'Inline example', source: 'inline source' },
];
const success = { schema_version: 1, status: 'success', attempts: [],
  selected: { plan_id: 'rows2-v1', workspace_bytes: 64, multiplication_ops: 48 },
  shape: { height: 1, width: 1, input_height: 2, input_width: 2 },
  output: [186], input: [0, 1, 2, 3], comparison: { matches: true, cells_compared: 1 } };
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const flush = () => new Promise(resolve => setImmediate(resolve));

function timers() {
  const active = new Map();
  let serial = 0;
  return { active, setTimeout(callback, delay) { const id = ++serial; active.set(id, { callback, delay }); return id; },
    clearTimeout(id) { active.delete(id); },
    fire(delay) {
      const entry = [...active].find(([, task]) => task.delay === delay);
      assert.ok(entry, `Expected a ${delay}ms timer`);
      active.delete(entry[0]);
      entry[1].callback();
    } };
}

function appHarness({ getExamples = async () => ({ examples }), runDemo = async () => success } = {}) {
  const nodes = new Map();
  const document = { activeElement: null, documentElement: { dataset: {} },
    getElementById: id => nodes.get(id), querySelector: () => nodes.get('results-panel'),
    createElement: tag => new Element(tag), addEventListener() {} };
  class Element {
    constructor(tag) {
      this.tagName = tag; this.children = []; this.dataset = {}; this.attributes = {};
      this.handlers = {}; this.value = ''; this.textContent = ''; this.hidden = false;
      this.disabled = false; this.classList = { toggle() {} };
    }
    setAttribute(key, value) { this.attributes[key] = value; }
    getAttribute(key) { return this.attributes[key]; }
    addEventListener(event, callback) { this.handlers[event] = callback; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
    querySelectorAll(tag) { return this.children.filter(node => node.tagName === tag); }
    focus() { document.activeElement = this; }
    click() { if (!this.disabled) { this.focus(); return this.handlers.click?.(); } }
    fire(event) { return this.handlers[event]?.(); }
  }
  for (const match of html.matchAll(/<([\w-]+)\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
    const node = new Element(match[1]);
    node.hidden = /\bhidden\b/.test(match[2]);
    node.disabled = /\bdisabled\b/.test(match[2]);
    nodes.set(match[3], node);
  }
  nodes.set('results-panel', new Element('section'));
  nodes.get('input-mode').value = 'ramp';
  const clock = timers();
  vm.runInNewContext(appSource, { document, window: clock, getExamples, runDemo,
    AbortController, Blob, URL, console });
  return { node: id => nodes.get(id), document, clock };
}

function assertReset(h) {
  assert.equal(h.node('source').value, examples[0].source);
  assert.equal(h.node('input-mode').value, 'ramp');
  assert.equal(h.node('custom-input').value, '');
  assert.equal(h.node('custom-input-area').hidden, true);
  assert.equal(h.node('result-content').hidden, true);
  assert.equal(h.node('diagnostic').hidden, true);
  assert.equal(h.node('download').disabled, true);
  assert.equal(h.node('empty-state').hidden, false);
  assert.equal(h.node('output-grid').children.length, 0);
  assert.equal(h.node('input-grid').children.length, 0);
  assert.equal(h.node('candidate-rows').children.length, 0);
  assert.equal(h.node('results-panel').getAttribute('aria-busy'), 'false');
  assert.equal(h.node('run').disabled, false);
  assert.equal(h.node('examples').children[0].getAttribute('aria-pressed'), 'true');
  assert.equal(h.node('examples').children[1].getAttribute('aria-pressed'), 'false');
  assert.equal(h.node('status-title').textContent, 'Ready to run');
}

test('Reset is a labelled native button, unavailable until examples load or retry succeeds', async () => {
  assert.match(html, /<button\b[^>]*id="reset"[^>]*type="button"[^>]*disabled[^>]*>Reset example<\/button>/);
  const initial = deferred();
  let calls = 0;
  const h = appHarness({ getExamples: () => ++calls === 1 ? initial.promise : Promise.resolve({ examples }) });
  assert.equal(h.node('reset').disabled, true);
  initial.reject(new Error('offline'));
  await flush();
  assert.equal(h.node('reset').disabled, true);
  await h.node('retry-examples').click();
  assert.equal(h.node('reset').disabled, false);
});

test('Reset clears a completed report, restores defaults, preserves focus, and can run again', async () => {
  const h = appHarness();
  await flush();
  h.node('examples').children[1].click();
  h.node('input-mode').value = 'custom';
  h.node('input-mode').fire('change');
  h.node('custom-input').value = '[4, 3, 2, 1]';
  await h.node('run').click();
  assert.equal(h.node('download').disabled, false);
  h.node('reset').click();
  assertReset(h);
  assert.equal(h.document.activeElement, h.node('reset'));
  await h.node('run').click();
  assert.equal(h.node('status-title').textContent, 'Run complete');
});

test('Repeated execution keeps the original compilation cost visible', async () => {
  let count = 0;
  const h = appHarness({runDemo: async () => ({...success, timings: {
    compilation_ms: count ? 0 : 73, initial_compilation_ms: 73,
    reused_compilation: Boolean(count++), execution_ms: 0.01, verification_ms: 2,
  }})});
  await flush();
  await h.node('run').click();
  assert.match(h.node('run-details').children.map(node => node.textContent).join(' '), /73\.00 ms/);
  await h.node('run').click();
  const details = h.node('run-details').children.map(node => node.textContent).join(' ');
  assert.match(details, /73\.00 ms/);
  assert.match(details, /reused/i);
});

test('Reset clears an invalid custom-input diagnostic', async () => {
  const h = appHarness();
  await flush();
  h.node('input-mode').value = 'custom';
  h.node('input-mode').fire('change');
  h.node('custom-input').value = '[';
  await h.node('run').click();
  assert.equal(h.node('diagnostic').hidden, false);
  h.node('reset').click();
  assertReset(h);
});

test('Reset aborts a run, ignores its late result, and keeps an immediate new run current', async () => {
  const jobs = [];
  const h = appHarness({ runDemo: (request, options) => {
    const job = deferred(); jobs.push({ ...job, request, signal: options?.signal }); return job.promise;
  } });
  await flush();
  const oldRun = h.node('run').click();
  h.node('reset').click();
  assert.equal(jobs[0].signal.aborted, true);
  assertReset(h);
  const newRun = h.node('run').click();
  jobs[0].resolve(success);
  await oldRun;
  assert.equal(h.node('download').disabled, true);
  assert.equal(h.node('run').disabled, true);
  assert.equal(h.node('results-panel').getAttribute('aria-busy'), 'true');
  jobs[1].resolve(success);
  await newRun;
  assert.equal(h.node('download').disabled, false);
  assert.equal(h.node('status-title').textContent, 'Run complete');
  assert.equal(h.clock.active.size, 0);
});

function transportHarness(browser = true, fetch) {
  const workers = [];
  class Worker {
    constructor() { this.messages = []; this.terminated = false; workers.push(this); }
    postMessage(message) { this.messages.push(message); }
    terminate() { this.terminated = true; }
    respond(message = this.messages.at(-1), result = {}) { this.onmessage({ data: { id: message.id, result } }); }
  }
  const clock = timers();
  const context = vm.createContext({ document: { documentElement: { dataset: { runtime: browser ? 'browser' : '' } } },
    Worker, URL, TextEncoder, AbortController, DOMException, fetch, ...clock });
  vm.runInContext(`${transportSource}\nglobalThis.api = { getExamples, runDemo, prepareDemo };`, context);
  return { ...context.api, workers, clock };
}

async function boot(h) {
  const loading = h.getExamples();
  h.workers[0].respond();
  await flush();
  h.workers[0].respond(undefined, { examples });
  await loading;
}

test('Compiled preparation uses a cancellable worker request before execution', async () => {
  const h = transportHarness();
  await boot(h);
  const controller = new AbortController();
  const preparation = h.prepareDemo({ source: 'program', input_mode: 'ramp' }, { signal: controller.signal });
  const outcome = assert.rejects(preparation, /cancelled/i);
  await flush();
  const current = h.workers[0];
  assert.equal(current.messages.at(-1).method, 'prepare');
  assert.equal(JSON.parse(current.messages.at(-1).request).source, 'program');
  controller.abort();
  await outcome;
  assert.equal(current.terminated, true);
  assert.equal(h.clock.active.size, 0);
  assert.equal(getEventListeners(controller.signal, 'abort').length, 0);
});

test('Worker cancellation terminates computation, ignores old messages, and permits immediate rerun', async () => {
  const h = transportHarness();
  await boot(h);
  const controller = new AbortController();
  const first = h.runDemo({ source: 'old' }, { signal: controller.signal });
  const cancelled = assert.rejects(first, /cancelled/i);
  await flush();
  const oldWorker = h.workers[0];
  const oldMessage = oldWorker.messages.at(-1);
  controller.abort();
  await cancelled;
  assert.equal(oldWorker.terminated, true);
  assert.equal(getEventListeners(controller.signal, 'abort').length, 0);
  assert.equal(h.clock.active.size, 0);
  const nextController = new AbortController();
  const next = h.runDemo({ source: 'new' }, { signal: nextController.signal });
  const nextWorker = h.workers[1];
  nextWorker.respond();
  await flush();
  oldWorker.respond(oldMessage, { stale: true });
  nextWorker.respond(undefined, { fresh: true });
  assert.equal((await next).fresh, true);
  assert.equal(getEventListeners(nextController.signal, 'abort').length, 0);
  assert.equal(h.clock.active.size, 0);
});

test('Cancelling while runtime boots stops that request before any computation is sent', async () => {
  const h = transportHarness();
  const controller = new AbortController();
  const run = h.runDemo({}, { signal: controller.signal });
  const cancelled = assert.rejects(run, /cancelled/i);
  controller.abort();
  await cancelled;
  h.workers[0].respond();
  await flush();
  assert.deepEqual(h.workers[0].messages.map(message => message.method), ['boot']);
  assert.equal(getEventListeners(controller.signal, 'abort').length, 0);
  assert.equal(h.clock.active.size, 0);
});

test('Local API cancellation reaches fetch and removes timers/listeners', async () => {
  let fetchSignal;
  const h = transportHarness(false, async (url, options) => {
    fetchSignal = options.signal;
    return new Promise((resolve, reject) => options.signal.addEventListener('abort', () => {
      reject(new DOMException('Aborted', 'AbortError'));
    }, { once: true }));
  });
  const controller = new AbortController();
  const run = h.runDemo({}, { signal: controller.signal });
  const cancelled = assert.rejects(run, /cancelled/i);
  controller.abort();
  await cancelled;
  assert.equal(fetchSignal.aborted, true);
  assert.equal(getEventListeners(controller.signal, 'abort').length, 0);
  assert.equal(h.clock.active.size, 0);
});

test('Successful local API request cleans its parent abort listener and timeout', async () => {
  const h = transportHarness(false, async () => ({ ok: true, json: async () => success }));
  const controller = new AbortController();
  assert.equal((await h.runDemo({}, { signal: controller.signal })).status, 'success');
  assert.equal(getEventListeners(controller.signal, 'abort').length, 0);
  assert.equal(h.clock.active.size, 0);
});

const busyResponse = () => ({ ok: false, status: 429,
  json: async () => ({ diagnostic: { code: 'WORKER_BUSY', message: 'A computation is already running.' } }) });

test('Local Reset and immediate rerun wait for the old server worker, keeping the UI running', async () => {
  let calls = 0;
  let serverBusy = true;
  const requests = [];
  const transport = transportHarness(false, async (url, options) => {
    requests.push(options.body);
    if (++calls === 1) return new Promise((resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
    });
    return serverBusy ? busyResponse() : { ok: true, json: async () => success };
  });
  const h = appHarness({ runDemo: transport.runDemo });
  await flush();
  h.node('source').value = 'edited old request';
  const first = h.node('run').click();
  h.node('reset').click();
  const next = h.node('run').click();
  await first;
  await flush();
  assert.equal(calls, 2);
  assert.equal(h.node('run').disabled, true);
  assert.equal(h.node('results-panel').getAttribute('aria-busy'), 'true');
  assert.equal(h.node('diagnostic').hidden, true);
  assert.equal(h.node('download').disabled, true);
  serverBusy = false;
  transport.clock.fire(250);
  await next;
  assert.equal(calls, 3);
  assert.equal(requests[1], requests[2]);
  assert.equal(JSON.parse(requests[2]).source, examples[0].source);
  assert.equal(h.node('status-title').textContent, 'Run complete');
  assert.equal(transport.clock.active.size, 0);
  assert.equal(h.clock.active.size, 0);
});

test('Cancelling a local busy retry stops retries and removes every listener and timer', async () => {
  let calls = 0, fetchSignal;
  const h = transportHarness(false, async (url, options) => {
    calls += 1; fetchSignal = options.signal; return busyResponse();
  });
  const controller = new AbortController();
  const run = h.runDemo({}, { signal: controller.signal });
  const outcome = run.then(result => ({ result }), error => ({ error }));
  await flush();
  assert.equal(h.clock.active.size, 2);
  controller.abort();
  assert.match((await outcome).error.message, /cancelled/i);
  assert.equal(calls, 1);
  assert.equal(getEventListeners(fetchSignal, 'abort').length, 0);
  assert.equal(getEventListeners(controller.signal, 'abort').length, 0);
  assert.equal(h.clock.active.size, 0);
});

test('Local busy retries share the original request deadline', async () => {
  let calls = 0, fetchSignal;
  const h = transportHarness(false, async (url, options) => {
    calls += 1; fetchSignal = options.signal; return busyResponse();
  });
  const controller = new AbortController();
  const run = h.runDemo({}, { signal: controller.signal });
  const outcome = run.then(result => ({ result }), error => ({ error }));
  await flush();
  h.clock.fire(250);
  await flush();
  assert.equal(calls, 2);
  h.clock.fire(15000);
  assert.match((await outcome).error.message, /time limit/i);
  assert.equal(getEventListeners(fetchSignal, 'abort').length, 0);
  assert.equal(getEventListeners(controller.signal, 'abort').length, 0);
  assert.equal(h.clock.active.size, 0);
});

test('Other HTTP 429 errors are not retried', async () => {
  let calls = 0;
  const h = transportHarness(false, async () => {
    calls += 1;
    return { ok: false, status: 429,
      json: async () => ({ diagnostic: { code: 'OTHER_LIMIT', message: 'Other limit reached.' } }) };
  });
  const controller = new AbortController();
  await assert.rejects(h.runDemo({}, { signal: controller.signal }), /Other limit reached/);
  assert.equal(calls, 1);
  assert.equal(getEventListeners(controller.signal, 'abort').length, 0);
  assert.equal(h.clock.active.size, 0);
});

test('Version 2 candidates retain costs and distinguish skipped proof from eligibility', async () => {
  const h = appHarness({runDemo: async () => ({...success, schema_version: 2,
    attempts: [{plan_id: 'inline-v1', state: 'not_checked_worse_rank', eligible: null,
      workspace_bytes: 0, multiplication_ops: 140, semantic_status: 'unknown', constraint_status: 'unknown'},
      {plan_id: 'materialize-v1', state: 'constraint_rejected', eligible: null,
        workspace_bytes: 192, multiplication_ops: 48, semantic_status: 'unknown', constraint_status: 'violated'}]})});
  await flush();
  await h.node('run').click();
  assert.equal(h.node('status-title').textContent, 'Run complete');
  const rows = h.node('candidate-rows').children;
  assert.equal(rows[0].children[1].textContent, '0 B');
  assert.equal(rows[0].children[2].textContent, '140');
  assert.equal(rows[0].children[3].textContent, 'Lower priority');
  assert.equal(rows[0].children[3].children[0].textContent, 'Not checked');
  assert.equal(rows[1].children[3].textContent, 'Exceeds storage limit');
});

test('Unknown result schema never displays a successful run', async () => {
  const h = appHarness({runDemo: async () => ({...success, schema_version: 3})});
  await flush();
  await h.node('run').click();
  assert.notEqual(h.node('status-title').textContent, 'Run complete');
  assert.equal(h.node('download').disabled, true);
});

test('An unfinished ranked search does not claim that every plan fails constraints', async () => {
  const h = appHarness({runDemo: async () => ({schema_version: 2, status: 'no_eligible_plan',
    attempts: [], selected: null, search: {termination_reason: 'check_limit_exhausted'}})});
  await flush();
  await h.node('run').click();
  assert.equal(h.node('status-title').textContent, 'No plan selected');
});
