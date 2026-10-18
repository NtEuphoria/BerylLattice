/* Research-only Worker; production assets and compiler modules are unchanged. */
importScripts('/compilation-wasm.js');
let python;
let prepared;
const milliseconds = (phases, name, start) => {
  phases[name] = {elapsed_ms: performance.now() - start, calls: 1};
};
const digest = async bytes => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)))
  .map(value => value.toString(16).padStart(2, '0')).join('');
function pythonJson(expression) {
  return JSON.parse(python.runPython(`json.dumps(${expression})`));
}

async function boot({site, archive_sha256}) {
  const start = performance.now();
  const base = new URL(site);
  const response = await fetch(new URL('runtime-config.json', base));
  if (!response.ok) throw new Error('runtime configuration unavailable');
  const config = await response.json();
  const runtime = new URL(config.indexURL, base);
  importScripts(new URL('pyodide.js', runtime).href);
  python = await loadPyodide({indexURL: runtime.href});
  if (python.version !== config.version) throw new Error('runtime version mismatch');
  const archive = await fetch(new URL('beryl-compiler.zip', base));
  if (!archive.ok) throw new Error('compiler archive unavailable');
  const bytes = await archive.arrayBuffer();
  const observedArchive = await digest(bytes);
  if (observedArchive !== archive_sha256) throw new Error('served compiler archive hash mismatch');
  python.unpackArchive(bytes, 'zip', {extractDir: '/beryl-profile'});
  python.runPython(`
import sys, json, hashlib, inspect, cProfile, pstats
sys.path.insert(0, '/beryl-profile')
from beryl import playground_service as service

def _compilation_diagnostic(source):
    profiler = cProfile.Profile()
    result = profiler.runcall(service.prepare_compiled_demo, source)
    if result.get('status') != 'prepared':
        raise ValueError(result)
    counts = []
    for (filename, line, name), (_, calls, own, inclusive, _) in pstats.Stats(profiler).stats.items():
        if '/beryl/' in filename:
            counts.append(dict(file=filename.rsplit('/', 1)[-1], line=line, function=name, calls=calls))
    trace = None
    if 'trace' in inspect.signature(service.prepare_compiled_demo).parameters:
        from beryl.compilation_trace import CompilationTrace
        sink = CompilationTrace()
        result = service.prepare_compiled_demo(source, trace=sink)
        if result.get('status') != 'prepared':
            raise ValueError(result)
        trace = sink.report()
    return dict(call_counts=counts, trace=trace,
        scope='separate diagnostic preparations after measured executions; not wall-time samples')
`);
  return {total_app_boot_ms: performance.now() - start, runtime: python.version,
    archive_sha256: observedArchive, python: python.runPython('sys.version'),
    scope: 'Runtime loading, compiler archive unpacking and imports; excludes browser launch/page load. User program has not run.'};
}

async function prepare({source}) {
  prepared = null;
  const start = performance.now();
  const phases = {};
  python.globals.set('_compilation_source', source);
  let metadata;
  const pythonStart = performance.now();
  try {
    metadata = pythonJson('service.prepare_compiled_demo(_compilation_source)');
  } finally {
    python.globals.delete('_compilation_source');
  }
  milliseconds(phases, 'python_prepare_bridge', pythonStart);
  if (metadata.status !== 'prepared') throw new Error(JSON.stringify(metadata));
  const bytes = Uint8Array.from(atob(metadata.wasm_base64), value => value.charCodeAt(0));
  const compileStart = performance.now();
  const module = await WebAssembly.compile(bytes);
  milliseconds(phases, 'wasm_compile', compileStart);
  if (WebAssembly.Module.imports(module).length) throw new Error('unexpected Wasm imports');
  const instantiateStart = performance.now();
  const instance = await WebAssembly.instantiate(module);
  milliseconds(phases, 'wasm_instantiate', instantiateStart);
  milliseconds(phases, 'total_fresh_source_preparation', start);
  // Hashes and ABI audits are outside preparation timing.
  if (await digest(new TextEncoder().encode(source)) !== metadata.source_digest
      || await digest(bytes) !== metadata.module_digest) throw new Error('artifact hash mismatch');
  if (!(instance.exports.memory instanceof WebAssembly.Memory)
      || instance.exports.memory.buffer.byteLength !== metadata.memory_bytes
      || typeof instance.exports.run !== 'function') throw new Error('invalid Wasm ABI');
  for (const key of ['input_offset', 'output_offset', 'input_count', 'output_count']) {
    if (!Number.isSafeInteger(metadata[key]) || metadata[key] < 0) throw new Error('invalid layout scalar');
  }
  if (metadata.input_offset % 4 || metadata.output_offset % 4
      || metadata.input_offset + 4 * metadata.input_count > metadata.output_offset
      || metadata.output_offset + 4 * metadata.output_count > metadata.memory_bytes) throw new Error('overlapping layout');
  delete metadata.wasm_base64;
  prepared = {source, metadata, instance};
  return {phases, timing_unit: 'ms', timing_semantics: 'inclusive', metadata, module_bytes: bytes.length, module_locals: localCount(bytes)};
}

function execute({iteration}) {
  if (!prepared) throw new Error('program not prepared');
  const {source, metadata, instance} = prepared;
  const data = Array.from({length: metadata.input_count}, (_, index) => (index + iteration * 37) % 1024);
  const request = {source, input_mode: 'custom', inputs: data};
  python.globals.set('_compilation_request_json', JSON.stringify(request));
  let buffers;
  try {
    python.runPython('_compilation_request = json.loads(_compilation_request_json)');
    buffers = pythonJson('service.compiled_request_inputs(_compilation_request)');
    if (buffers.status !== 'ready') throw new Error(JSON.stringify(buffers));
    const input = new Int32Array(instance.exports.memory.buffer, metadata.input_offset, metadata.input_count);
    const output = new Int32Array(instance.exports.memory.buffer, metadata.output_offset, metadata.output_count);
    const start = performance.now();
    input.set(buffers.input);
    output.set(buffers.initial_output);
    const status = instance.exports.run();
    const observation = {status, input: Array.from(input), output: Array.from(output)};
    const execution_ms = performance.now() - start;
    const verifyStart = performance.now();
    python.globals.set('_compilation_observation_json', JSON.stringify(observation));
    const report = pythonJson('service.finish_compiled_demo(_compilation_request, json.loads(_compilation_observation_json))');
    if (report.status !== 'success' || report.comparison?.matches !== true || status !== 0) throw new Error('source evaluator mismatch');
    const {height, width} = metadata.shape;
    if (observation.output.length !== height * width || observation.input.some((value, index) => value !== data[index])) {
      throw new Error('observation shape/input preservation mismatch');
    }
    for (let r = 0; r < height; r++) for (let c = 0; c < width; c++) {
      const index = r * (width + 1) + c;
      const expected = [index, index + 1, index + width + 1, index + width + 2]
        .reduce((sum, position) => sum + (data[position] + 1) ** 2, 0);
      if (observation.output[r * width + c] !== expected) throw new Error('external formula mismatch');
    }
    return {iteration, execution_ms, verification_ms: performance.now() - verifyStart,
      reused_preparation: iteration > 0, input: data, observation,
      independent_formula_matched: true, original_ast_matched: true,
      execution_scope: 'input/output initialization, first exported run and complete observation snapshot; engine-lazy work may occur here'};
  } finally {
    for (const name of ['_compilation_request_json', '_compilation_request', '_compilation_observation_json']) python.globals.delete(name);
  }
}

function diagnose({source}) {
  python.globals.set('_compilation_source', source);
  try {
    return pythonJson('_compilation_diagnostic(_compilation_source)');
  } finally {
    python.globals.delete('_compilation_source');
    // Diagnostic preparations replace service state; no further execution is permitted.
    prepared = null;
  }
}

self.onmessage = async ({data}) => {
  try {
    const actions = {boot, prepare, execute, diagnose};
    if (!Object.hasOwn(actions, data.method)) throw new Error('unknown research method');
    self.postMessage({id: data.id, result: await actions[data.method](data.payload)});
  } catch (error) {
    self.postMessage({id: data.id, error: String(error.stack || error)});
  }
};
