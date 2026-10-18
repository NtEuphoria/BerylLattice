/* Classic Worker: Pyodide's loader uses importScripts inside this isolated thread. */
let python = null;
let busy = false;

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
from beryl.playground_service import get_examples, run_demo
from beryl.codec import canonical_json, strict_json_loads
`);
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
      let encoded;
      if (method === 'examples') {
        encoded = python.runPython('canonical_json(get_examples()).decode("utf-8")');
      } else if (method === 'run') {
        if (typeof request !== 'string' || new TextEncoder().encode(request).byteLength > 131072) {
          throw new Error('The request exceeds the 128 KiB demo limit.');
        }
        python.globals.set('_beryl_request_json', request);
        try {
          encoded = python.runPython(`canonical_json(run_demo(strict_json_loads(
_beryl_request_json.encode('utf-8'), max_bytes=131072, max_items=512, max_depth=4
))).decode('utf-8')`);
        } finally {
          python.globals.delete('_beryl_request_json');
        }
      } else {
        throw new Error('Unknown browser runtime request.');
      }
      self.postMessage({id, result: JSON.parse(encoded)});
    }
  } catch (_) {
    // Do not expose Python traces or runtime paths as product diagnostics.
    self.postMessage({id, error: method === 'boot'
      ? 'The browser Python runtime could not load. Check the connection and retry.'
      : 'The browser runtime could not complete this request.'});
  } finally {
    busy = false;
  }
};
