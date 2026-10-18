/* Separate profiling run; its cProfile overhead is never used as phase timing. */
importScripts('./worker.js');
const prepareHandler = self.onmessage;
self.onmessage = async ({data}) => {
  if (data.method !== 'counts') return prepareHandler({data});
  try {
    python.globals.set('_counts_source', data.source);
    const value = python.runPython(`
import cProfile
_profile = cProfile.Profile()
_count_result = _profile.runcall(service.prepare_compiled_demo, _counts_source)
_wanted = {'parse_source', 'admit_source', 'check_plan', 'validate_plan', 'encode_plan',
           'decode_plan', '_source_expression', '_equal', 'canonical_json', 'strict_json_loads',
           'make_plan'}
_entries = []
for _entry in _profile.getstats():
    _code = _entry.code
    if hasattr(_code, 'co_filename') and _code.co_name in _wanted and '/beryl-release/' in _code.co_filename:
        _entries.append({'function': _code.co_name, 'file': _code.co_filename,
            'line': _code.co_firstlineno, 'calls': _entry.callcount,
            'recursive_calls': _entry.reccallcount})
json.dumps({'status': _count_result['status'], 'selected': _count_result.get('selected'),
    'source_sha256': hashlib.sha256(_counts_source.encode()).hexdigest(),
    'entries': sorted(_entries, key=lambda entry: (entry['function'], entry['file']))})
`);
    python.globals.delete('_counts_source');
    self.postMessage({id: data.id, result: JSON.parse(value)});
  } catch (error) {
    self.postMessage({id: data.id, error: String(error.stack || error)});
  }
};
