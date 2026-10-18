/* Research instrumentation only; the release ZIP and runtime are unmodified. */
let python;
const site = new URL('/beryl-compiled/site-release/', self.location.href);

async function boot() {
  const start = performance.now();
  const response = await fetch(new URL('runtime-config.json', site));
  if (!response.ok) throw new Error('runtime configuration unavailable');
  const config = await response.json();
  const runtime = new URL(config.indexURL, site);
  importScripts(new URL('pyodide.js', runtime).href);
  python = await loadPyodide({indexURL: runtime.href});
  if (python.version !== config.version) throw new Error('runtime version mismatch');
  const archive = await fetch(new URL('beryl-compiler.zip', site));
  if (!archive.ok) throw new Error('release compiler archive unavailable');
  python.unpackArchive(await archive.arrayBuffer(), 'zip', {extractDir: '/beryl-release'});
  python.runPython(`
import sys, json, hashlib, platform
from time import perf_counter
sys.path.insert(0, '/beryl-release')
from beryl import playground_service as service
from beryl import wasm as wasm_backend

_timings = None
def _timed(owner, name, phase):
    original = getattr(owner, name)
    def wrapped(*args, **kwargs):
        start = perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            if _timings is not None:
                _timings[phase] = _timings.get(phase, 0.0) + (perf_counter() - start) * 1000
    setattr(owner, name, wrapped)

for _name in ('_request_source', 'parse_source', 'admit_source'):
    _timed(service, _name, 'initial_admission_ms')
_timed(service, 'select_plan', 'selection_ms')
_timed(service, 'compile_wasm', 'backend_total_ms')
_timed(wasm_backend, '_checked_plan', 'fresh_check_ms')

def _profile_prepare(source):
    global _timings
    _timings = {}
    start = perf_counter()
    try:
        result = service.prepare_compiled_demo(source)
        elapsed = (perf_counter() - start) * 1000
        phases = dict(_timings)
        phases['python_prepare_ms'] = elapsed
        phases['wasm_emit_ms'] = phases.get('backend_total_ms', 0) - phases.get('fresh_check_ms', 0)
        phases['service_other_ms'] = elapsed - sum(phases.get(key, 0) for key in (
            'initial_admission_ms', 'selection_ms', 'backend_total_ms'))
        return {'phases': phases, 'result': result,
                'source_sha256': hashlib.sha256(source.encode('utf-8')).hexdigest()}
    finally:
        _timings = None

_boot_identity = json.dumps({'python': sys.version, 'implementation': platform.python_implementation(),
    'platform': platform.platform(), 'service_file': service.__file__,
    'wasm_file': wasm_backend.__file__, 'examples': service.get_examples()})
`);
  return {runtime: python.version, runtime_base_url: runtime.href,
    compiler_archive_url: new URL('beryl-compiler.zip', site).href,
    boot_ms: performance.now() - start,
    ...JSON.parse(python.globals.get('_boot_identity'))};
}

async function prepare(source) {
  const start = performance.now();
  python.globals.set('_profile_source', source);
  let report;
  try {
    report = JSON.parse(python.runPython('json.dumps(_profile_prepare(_profile_source))'));
  } finally {
    python.globals.delete('_profile_source');
  }
  report.phases.python_bridge_ms = performance.now() - start;
  const metadata = report.result;
  if (metadata.status !== 'prepared') throw new Error(JSON.stringify(metadata));
  const decodeStart = performance.now();
  const bytes = Uint8Array.from(atob(metadata.wasm_base64), value => value.charCodeAt(0));
  report.phases.base64_decode_ms = performance.now() - decodeStart;
  const compileStart = performance.now();
  const module = await WebAssembly.compile(bytes);
  report.phases.js_wasm_compile_ms = performance.now() - compileStart;
  if (WebAssembly.Module.imports(module).length !== 0) throw new Error('unexpected imports');
  const instantiateStart = performance.now();
  const instance = await WebAssembly.instantiate(module);
  report.phases.js_wasm_instantiate_ms = performance.now() - instantiateStart;
  report.phases.worker_compilation_total_ms = performance.now() - start;
  if (instance.exports.memory.buffer.byteLength !== metadata.memory_bytes) throw new Error('memory mismatch');
  const input = new Int32Array(instance.exports.memory.buffer, metadata.input_offset, metadata.input_count);
  const output = new Int32Array(instance.exports.memory.buffer, metadata.output_offset, metadata.output_count);
  for (let index = 0; index < input.length; index++) input[index] = index % 1024;
  output.fill(-777);
  if (instance.exports.run() !== 0) throw new Error('module execution rejected valid inputs');
  const {height, width} = metadata.shape;
  for (let row = 0; row < height; row++) for (let column = 0; column < width; column++) {
    const index = row * (width + 1) + column;
    const expected = [index, index + 1, index + width + 1, index + width + 2]
      .reduce((sum, position) => sum + (input[position] + 1) ** 2, 0);
    if (output[row * width + column] !== expected) throw new Error('independent formula mismatch');
  }
  delete metadata.wasm_base64;
  report.validation = {webassembly_compiled: true, no_imports: true, memory_layout_checked: true,
    independent_formula_matched: true, output_cells: output.length};
  return report;
}

self.onmessage = async ({data}) => {
  try {
    self.postMessage({id: data.id, result: data.method === 'boot' ? await boot() : await prepare(data.source)});
  } catch (error) {
    self.postMessage({id: data.id, error: String(error.stack || error)});
  }
};
