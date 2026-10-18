// Node.js baseline (typed arrays). Run: node kernels.mjs kernel pattern a b min_ms max_reps
// Outputs use Float64Array: every value here is an exact integer below 2^53.
const [k, pat, ...nums] = process.argv.slice(2);
const [a, b, minMs, maxReps] = nums.map(Number);

const value = (i) => ({
  hash: () => Math.imul(i, 2654435761) >>> 22, ramp: () => i % 1024,
  alt: () => 1023 * (i & 1), zeros: () => 0, max: () => 1023,
}[pat] ?? (() => { throw new Error('unknown pattern'); }))();

function windowed(h, w, x, o, f) {
  const cols = w + 2;
  for (let r = 0; r < h; r++) {
    const ra = r * cols, rb = ra + cols, rc = rb + cols;
    for (let j = 0; j < w; j++) o[r * w + j] = f(x, ra + j, rb + j, rc + j);
  }
}

const K = {
  sq2x2: [(h, w) => [(h + 1) * (w + 1), h * w], (h, w, x, o) => {
    const cols = w + 1, p = (v) => (v + 1) * (v + 1);
    for (let r = 0; r < h; r++) for (let c = 0; c < w; c++) {
      const i = r * cols + c;
      o[r * w + c] = p(x[i]) + p(x[i + 1]) + p(x[i + cols]) + p(x[i + cols + 1]);
    }
  }],
  stencil1d3: [(n) => [n + 2, n], (n, _, x, o) => { for (let i = 0; i < n; i++) o[i] = x[i] + 2 * x[i + 1] + x[i + 2]; }],
  box3x3: [(h, w) => [(h + 2) * (w + 2), h * w], (h, w, x, o) => windowed(h, w, x, o,
    (x, a, b, c) => x[a] + x[a + 1] + x[a + 2] + x[b] + x[b + 1] + x[b + 2] + x[c] + x[c + 1] + x[c + 2])],
  laplace5: [(h, w) => [(h + 2) * (w + 2), h * w], (h, w, x, o) => windowed(h, w, x, o,
    (x, a, b, c) => 4 * x[b + 1] - x[a + 1] - x[c + 1] - x[b] - x[b + 2])],
  conv3x3: [(h, w) => [(h + 2) * (w + 2), h * w], (h, w, x, o) => windowed(h, w, x, o,
    (x, a, b, c) => x[a] + 2 * x[a + 1] + x[a + 2] + 2 * x[b] + 4 * x[b + 1] + 2 * x[b + 2] + x[c] + 2 * x[c + 1] + x[c + 2])],
  life: [(h, w) => [(h + 2) * (w + 2), h * w], (h, w, x, o) => windowed(h, w, x, o, (x, a, b, c) => {
    const n = (x[a] & 1) + (x[a + 1] & 1) + (x[a + 2] & 1) + (x[b] & 1) + (x[b + 2] & 1) + (x[c] & 1) + (x[c + 1] & 1) + (x[c + 2] & 1);
    return (n === 3 || (n === 2 && (x[b + 1] & 1))) ? 1 : 0;
  })],
  polymap: [(n) => [n, n], (n, _, x, o) => { for (let i = 0; i < n; i++) { const v = x[i]; o[i] = v * v * v + 3 * v + 7; } }],
  transpose: [(h, w) => [h * w, h * w], (h, w, x, o) => { for (let r = 0; r < h; r++) for (let c = 0; c < w; c++) o[c * h + r] = x[r * w + c]; }],
  maxpool2: [(h, w) => [4 * h * w, h * w], (h, w, x, o) => {
    const cols = 2 * w;
    for (let r = 0; r < h; r++) for (let c = 0; c < w; c++) {
      const t = 2 * r * cols + 2 * c, u = t + cols;
      o[r * w + c] = Math.max(x[t], x[t + 1], x[u], x[u + 1]);
    }
  }],
  sum: [(n) => [n, 1], (n, _, x, o) => { let s = 0; for (let i = 0; i < n; i++) s += x[i]; o[0] = s; }],
  dot: [(n) => [2 * n, 1], (n, _, x, o) => { let s = 0; for (let i = 0; i < n; i++) s += x[i] * x[n + i]; o[0] = s; }],
  scan: [(n) => [n, n], (n, _, x, o) => { let s = 0; for (let i = 0; i < n; i++) { s += x[i]; o[i] = s; } }],
  hist: [(n) => [n, 64], (n, _, x, o) => { o.fill(0); for (let i = 0; i < n; i++) o[x[i] >> 4]++; }],
  matmul: [(n) => [2 * n * n, n * n], (n, _, x, o) => {
    o.fill(0);
    const q0 = n * n;
    for (let i = 0; i < n; i++) for (let kk = 0; kk < n; kk++) {
      const p = x[i * n + kk], qr = q0 + kk * n, row = i * n;
      for (let j = 0; j < n; j++) o[row + j] += p * x[qr + j];
    }
  }],
};

if (!K[k]) {
  console.log(JSON.stringify({ impl: 'node', kernel: k, status: 'unsupported' }));
} else {
  const [ioFn, fn] = K[k];
  const [nIn, nOut] = ioFn(a, b);
  const x = new Int32Array(nIn);
  for (let i = 0; i < nIn; i++) x[i] = value(i);
  const o = new Float64Array(nOut);
  fn(a, b, x, o); // untimed warm-up (also lets the JIT compile)
  // Calibrate calls per sample so one sample spans >= 1 ms.
  let inner = 1;
  for (;;) {
    const t = process.hrtime.bigint();
    for (let i = 0; i < inner; i++) fn(a, b, x, o);
    if (process.hrtime.bigint() - t >= 1000000n || inner >= 1 << 22) break;
    inner *= 2;
  }
  const s = [];
  let total = 0n;
  while (s.length < 3 || (total < BigInt(minMs) * 1000000n && s.length < Math.max(3, maxReps))) {
    const t = process.hrtime.bigint();
    for (let i = 0; i < inner; i++) fn(a, b, x, o);
    const d = process.hrtime.bigint() - t;
    s.push(d / BigInt(inner)); total += d;
  }
  const M = 1000000007;
  let acc = 0;
  for (let i = 0; i < nOut; i++) acc = (acc + (((o[i] % M) + M) % M) * (i % 65521 + 1)) % M;
  s.sort((p, q) => (p < q ? -1 : p > q ? 1 : 0));
  const h = s.length >> 1, med = s.length % 2 ? s[h] : (s[h - 1] + s[h]) / 2n;
  console.log(JSON.stringify({ impl: 'node', kernel: k, status: 'ok', n_out: nOut, checksum: acc,
    reps: s.length, inner, ns_min: Number(s[0]), ns_median: Number(med), ns_total: Number(total) }));
}