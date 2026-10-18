/* The UI uses the same Python service through a local API or a browser worker. */
const REQUEST_LIMIT = 131072;
const BOOT_TIMEOUT_MS = 60000;
const RUN_TIMEOUT_MS = 15000;
const browserRuntime = document.documentElement.dataset.runtime === 'browser';
let worker = null;
let bootPromise = null;
let serial = 0;
const pending = new Map();

function resetWorker(message) {
  const current = worker;
  worker = null;
  bootPromise = null;
  if (current) current.terminate();
  for (const task of pending.values()) {
    clearTimeout(task.timer);
    task.reject(new Error(message));
  }
  pending.clear();
}

function sendWorker(method, request, timeout) {
  const id = ++serial;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      resetWorker(method === 'boot'
        ? 'The browser runtime took too long to load. Check your connection and retry.'
        : 'This computation exceeded the browser time limit. The runtime was reset.');
    }, timeout);
    pending.set(id, {resolve, reject, timer});
    worker.postMessage({id, method, request});
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
    clearTimeout(task.timer);
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

async function callWorker(method, request) {
  await ensureWorker();
  if (pending.size) throw new Error('A computation is already running. Please wait for it to finish.');
  return sendWorker(method, request, RUN_TIMEOUT_MS);
}

async function callApi(path, request) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), RUN_TIMEOUT_MS);
  try {
    const response = await fetch(new URL(path, import.meta.url), request === undefined
      ? {signal: controller.signal}
      : {method: 'POST', headers: {'Content-Type': 'application/json'},
         body: JSON.stringify(request), signal: controller.signal});
    const result = await response.json();
    if (!response.ok) throw new Error(result.diagnostic?.message || 'The playground could not complete the request.');
    return result;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('The playground request exceeded its time limit.');
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

export async function getExamples() {
  return browserRuntime ? callWorker('examples') : callApi('./api/examples');
}

export async function runDemo(request) {
  const encoded = JSON.stringify(request);
  if (new TextEncoder().encode(encoded).byteLength > REQUEST_LIMIT) {
    throw new Error('The request exceeds the 128 KiB demo limit.');
  }
  return browserRuntime ? callWorker('run', encoded) : callApi('./api/run', request);
}
