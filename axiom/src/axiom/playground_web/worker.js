/* Classic Worker: Pyodide's loader uses importScripts inside this isolated thread. */
let python = null;
let busy = false;
let prepared = null;

async function boot() {
  if (python) return;
  const configResponse = await fetch(new URL('./runtime-config.json', self.location.href));
  if (!configResponse.ok) throw new Error('Browser runtime configuration is unavailable.');
  const config = await configResponse.json();
  const runtime = new URL(config.indexURL, self.location.href);
  importScripts(new URL('pyodide.js', runtime).href);
  python = await loadPyodide({indexURL: runtime.href});
  const archiveResponse = await fetch(new URL('./beryl-compiler.zip', self.location.href));
  if (!archiveResponse.ok) throw new Error('The beryl compiler archive is unavailable.');
  python.unpackArchive(await archiveResponse.arrayBuffer(), 'zip', {extractDir: '/beryl-compiler'});
  python.runPython(`
import sys
sys.path.insert(0, '/beryl-compiler')
from beryl.playground_service import (get_examples, compiled_request_source,
    prepare_compiled_demo, compiled_request_inputs, finish_compiled_demo)
from beryl.codec import canonical_json, strict_json_loads
`);
}

function pythonJson(expression) {
  return JSON.parse(python.runPython(`canonical_json(${expression}).decode('utf-8')`));
}

async function prepareSource(source) {
  if (prepared?.source === source) return {reused: true, milliseconds: 0};
  prepared = null;
  const start = performance.now();
  const metadata = pythonJson('prepare_compiled_demo(_beryl_request["source"])');
  if (metadata.status !== 'prepared') return {result: metadata};
  const bytes = Uint8Array.from(atob(metadata.wasm_base64), value => value.charCodeAt(0));
  const module = await WebAssembly.compile(bytes);
  if (WebAssembly.Module.imports(module).length !== 0) throw new Error('Unexpected module imports.');
  const instance = await WebAssembly.instantiate(module);
  if (!(instance.exports.memory instanceof WebAssembly.Memory)
      || instance.exports.memory.buffer.byteLength !== metadata.memory_bytes
      || typeof instance.exports.run !== 'function') throw new Error('Invalid compiled module.');
  for (const field of ['input_offset', 'output_offset', 'input_count', 'output_count']) {
    if (!Number.isSafeInteger(metadata[field]) || metadata[field] < 0) throw new Error('Invalid memory layout.');
  }
  if (metadata.input_offset % 4 || metadata.output_offset % 4
      || metadata.input_offset + 4 * metadata.input_count > metadata.output_offset
      || metadata.output_offset + 4 * metadata.output_count > metadata.memory_bytes) {
    throw new Error('Invalid memory layout.');
  }
  const milliseconds = performance.now() - start;
  prepared = {source, metadata, instance, milliseconds};
  return {reused: false, milliseconds};
}

function exactScalars(values, count) {
  if (!Array.isArray(values) || values.length !== count
      || values.some(value => !Number.isInteger(value) || value < -2147483648 || value > 2147483647)) {
    throw new Error('Invalid scalar buffer.');
  }
}

async function compiledRequest(method) {
  const envelope = pythonJson('compiled_request_source(_beryl_request)');
  if (envelope.status !== 'valid') return envelope;
  const compilation = await prepareSource(envelope.source);
  if (compilation.result) return compilation.result;
  const {metadata, instance} = prepared;
  if (method === 'prepare') {
    return {schema_version: metadata.schema_version, status: 'prepared', backend: metadata.backend,
      search: metadata.search, lowering: metadata.lowering,
      shape: metadata.shape, selected: metadata.selected, source_digest: metadata.source_digest,
      plan_digest: metadata.plan_digest, module_digest: metadata.module_digest,
      compilation_ms: compilation.milliseconds, initial_compilation_ms: prepared.milliseconds,
      reused_compilation: compilation.reused};
  }
  const buffers = pythonJson('compiled_request_inputs(_beryl_request)');
  if (buffers.status !== 'ready') return buffers;
  exactScalars(buffers.input, metadata.input_count);
  exactScalars(buffers.initial_output, metadata.output_count);
  const input = new Int32Array(instance.exports.memory.buffer, metadata.input_offset, metadata.input_count);
  const output = new Int32Array(instance.exports.memory.buffer, metadata.output_offset, metadata.output_count);
  const executionStart = performance.now();
  input.set(buffers.input);
  output.set(buffers.initial_output);
  const status = instance.exports.run();
  const observation = {status, input: Array.from(input), output: Array.from(output)};
  const executionMs = performance.now() - executionStart;
  const verificationStart = performance.now();
  python.globals.set('_beryl_observation_json', JSON.stringify(observation));
  try {
    const result = pythonJson(`finish_compiled_demo(_beryl_request, strict_json_loads(
_beryl_observation_json.encode('utf-8'), max_bytes=131072, max_items=1024, max_depth=4))`);
    result.timings = {compilation_ms: compilation.milliseconds,
      initial_compilation_ms: prepared.milliseconds, reused_compilation: compilation.reused,
      execution_ms: executionMs, verification_ms: performance.now() - verificationStart};
    if (result.status === 'error') prepared = null;
    return result;
  } finally {
    python.globals.delete('_beryl_observation_json');
  }
}

self.onmessage = async ({data}) => {
  const {id, method, request} = data;
  if (busy) {
    self.postMessage({id, error: 'The browser runtime is already busy.'});
    return;
  }
  busy = true;
  try {
    if (method === 'boot') {
      await boot();
      self.postMessage({id, result: {ready: true, runtime: 'pyodide-0.27.7'}});
    } else {
      if (!python) throw new Error('Browser runtime has not initialized.');
      let result;
      if (method === 'examples') {
        result = pythonJson('get_examples()');
      } else if (method === 'run' || method === 'prepare') {
        if (typeof request !== 'string' || new TextEncoder().encode(request).byteLength > 131072) {
          throw new Error('The request exceeds the 128 KiB demo limit.');
        }
        python.globals.set('_beryl_request_json', request);
        try {
          python.runPython(`_beryl_request = strict_json_loads(
_beryl_request_json.encode('utf-8'), max_bytes=131072, max_items=512, max_depth=4)`);
          result = await compiledRequest(method);
        } finally {
          python.globals.delete('_beryl_request_json');
          python.globals.delete('_beryl_request');
        }
      } else {
        throw new Error('Unknown browser runtime request.');
      }
      self.postMessage({id, result});
    }
  } catch (_) {
    prepared = null;
    // Do not expose Python traces or runtime paths as product diagnostics.
    self.postMessage({id, error: method === 'boot'
      ? 'The browser Python runtime could not load. Check the connection and retry.'
      : 'The browser runtime could not complete this request.'});
  } finally {
    busy = false;
  }
};
