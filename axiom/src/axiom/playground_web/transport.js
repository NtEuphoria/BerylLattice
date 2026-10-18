/* The UI uses the same Python service through a local API or a browser worker. */
const REQUEST_LIMIT = 131072;
const BOOT_TIMEOUT_MS = 60000;
const RUN_TIMEOUT_MS = 15000;
const BUSY_RETRY_MS = 250;
const browserRuntime = document.documentElement.dataset.runtime === 'browser';
let worker = null;
let bootPromise = null;
let serial = 0;
const pending = new Map();

function cancelled() {
  return new DOMException('Run cancelled.', 'AbortError');
}

function resetWorker(reason) {
  const current = worker;
  worker = null;
  bootPromise = null;
  if (current) current.terminate();
  for (const task of pending.values()) {
    task.cleanup();
    task.reject(typeof reason === 'string' ? new Error(reason) : reason);
  }
  pending.clear();
}

function sendWorker(method, request, timeout, signal) {
  if (signal?.aborted) return Promise.reject(cancelled());
  const id = ++serial;
  return new Promise((resolve, reject) => {
    // Python runs synchronously in its worker, so termination is the reliable
    // way to cancel it. The next request starts a fresh runtime.
    const abort = () => resetWorker(cancelled());
    const timer = setTimeout(() => {
      resetWorker(method === 'boot'
        ? 'The browser runtime took too long to load. Check your connection and retry.'
        : 'This computation exceeded the browser time limit. The runtime was reset.');
    }, timeout);
    const cleanup = () => {
      clearTimeout(timer);
      signal?.removeEventListener('abort', abort);
    };
    pending.set(id, {resolve, reject, cleanup});
    signal?.addEventListener('abort', abort, {once: true});
    try {
      worker.postMessage({id, method, request});
    } catch (error) {
      resetWorker(error);
    }
  });
}

async function ensureWorker() {
  if (bootPromise) return bootPromise;
  const instance = new Worker(new URL('./worker.js', import.meta.url));
  worker = instance;
  instance.onmessage = ({data}) => {
    if (worker !== instance) return;
    const task = pending.get(data.id);
    if (!task) return;
    pending.delete(data.id);
    task.cleanup();
    if (typeof data.error === 'string') task.reject(new Error(data.error));
    else task.resolve(data.result);
  };
  instance.onerror = () => {
    if (worker === instance) resetWorker('The browser runtime could not load. Check the connection and retry.');
  };
  bootPromise = sendWorker('boot', undefined, BOOT_TIMEOUT_MS).catch(error => {
    if (worker === instance) resetWorker(error.message);
    throw error;
  });
  return bootPromise;
}

function waitForBoot(signal) {
  if (signal?.aborted) return Promise.reject(cancelled());
  const ready = ensureWorker();
  if (!signal) return ready;
  // Cancelling a caller waiting for startup must not cancel shared startup.
  return new Promise((resolve, reject) => {
    const abort = () => { cleanup(); reject(cancelled()); };
    const cleanup = () => signal.removeEventListener('abort', abort);
    signal.addEventListener('abort', abort, {once: true});
    ready.then(value => { cleanup(); resolve(value); }, error => { cleanup(); reject(error); });
  });
}

async function callWorker(method, request, signal) {
  await waitForBoot(signal);
  if (signal?.aborted) throw cancelled();
  if (pending.size) throw new Error('A computation is already running. Please wait for it to finish.');
  return sendWorker(method, request, RUN_TIMEOUT_MS, signal);
}

function waitForRetry(signal) {
  if (signal.aborted) return Promise.reject(cancelled());
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      clearTimeout(timer);
      signal.removeEventListener('abort', abort);
    };
    const abort = () => { cleanup(); reject(cancelled()); };
    const timer = setTimeout(() => { cleanup(); resolve(); }, BUSY_RETRY_MS);
    signal.addEventListener('abort', abort, {once: true});
  });
}

async function callApi(path, request, signal) {
  if (signal?.aborted) throw cancelled();
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener('abort', abort, {once: true});
  const timer = setTimeout(() => controller.abort(), RUN_TIMEOUT_MS);
  try {
    const options = request === undefined
      ? {signal: controller.signal}
      : {method: 'POST', headers: {'Content-Type': 'application/json'},
         body: JSON.stringify(request), signal: controller.signal};
    while (true) {
      const response = await fetch(new URL(path, import.meta.url), options);
      const result = await response.json();
      // An aborted fetch may leave the old server worker finishing its run.
      // Only this explicit rejection is safe to retry: no new run was started.
      if (request !== undefined && response.status === 429 && result.diagnostic?.code === 'WORKER_BUSY') {
        await waitForRetry(controller.signal);
        continue;
      }
      if (!response.ok) throw new Error(result.diagnostic?.message || 'The playground could not complete the request.');
      return result;
    }
  } catch (error) {
    if (signal?.aborted) throw cancelled();
    if (error.name === 'AbortError') throw new Error('The playground request exceeded its time limit.');
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', abort);
  }
}

export async function getExamples() {
  return browserRuntime ? callWorker('examples') : callApi('./api/examples');
}

export async function runDemo(request, {signal} = {}) {
  const encoded = JSON.stringify(request);
  if (new TextEncoder().encode(encoded).byteLength > REQUEST_LIMIT) {
    throw new Error('The request exceeds the 128 KiB demo limit.');
  }
  return browserRuntime ? callWorker('run', encoded, signal) : callApi('./api/run', request, signal);
}

export async function prepareDemo(request, {signal} = {}) {
  if (!browserRuntime) throw new Error('Compiled benchmarks require the browser playground.');
  const encoded = JSON.stringify(request);
  if (new TextEncoder().encode(encoded).byteLength > REQUEST_LIMIT) {
    throw new Error('The request exceeds the 128 KiB demo limit.');
  }
  return callWorker('prepare', encoded, signal);
}
