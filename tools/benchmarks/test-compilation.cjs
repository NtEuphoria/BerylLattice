const assert = require('node:assert/strict');
const {parseArgs, sampleSource, summarize, localCount} = require('./compilation.cjs');
const defaults = parseArgs(['--site', '/tmp/site', '--output', '/tmp/new.json']);
assert.equal(defaults.samples, 21);
assert.equal(defaults.mode, 'engine-cold');
assert.equal(defaults.fixtureSet, 'qualification');
assert.throws(() => parseArgs(['--samples', '0']), /samples/);
assert.throws(() => parseArgs(['--mode', 'worker-only']), /mode/);
const fixture = {source: 'module demo;\n', edit: 'input_only'};
assert.equal(sampleSource(fixture, '123'), 'module demo;\n// fresh source sample 123\n');
assert.deepEqual(summarize([{phases: {wasm_compile: {elapsed_ms: 3}}},
  {phases: {wasm_compile: {elapsed_ms: 1}}}]), {wasm_compile: 2});
assert.equal(localCount(Buffer.from([0,97,115,109,1,0,0,0,10,9,1,7,2,3,127,2,126,0,11])), 5);
assert.throws(() => localCount(Buffer.from([0,97,115,109,1,0,0,0,10,9])), /truncated/);
console.log('compilation harness contracts passed');
