"""Shared timing protocol for the Python and NumPy baselines.

argv: kernel pattern a b min_ms max_reps
stdout: one JSON object (see bench/README.md, "Implementation protocol").
"""
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog import KERNELS, checksum, gen_input  # noqa: E402


def run(impl, kernels, prepare=lambda x: x, to_list=list):
    kernel, pattern = sys.argv[1], sys.argv[2]
    a, b, min_ms, max_reps = (int(v) for v in sys.argv[3:7])
    if kernel not in kernels:
        print(json.dumps(dict(impl=impl, kernel=kernel, status='unsupported')))
        return 0
    n_in, _ = KERNELS[kernel]['io'](a, b)
    x = prepare(gen_input(pattern, n_in))
    fn = kernels[kernel]
    out = fn(a, b, x)  # untimed warm-up
    inner = 1  # calibrate calls per sample so one sample spans >= 1 ms
    while True:
        start = time.perf_counter_ns()
        for _ in range(inner):
            out = fn(a, b, x)
        if time.perf_counter_ns() - start >= 1_000_000 or inner >= 1 << 22:
            break
        inner *= 2
    samples, total = [], 0
    while len(samples) < 3 or (total < min_ms * 1_000_000 and len(samples) < max_reps):
        start = time.perf_counter_ns()
        for _ in range(inner):
            out = fn(a, b, x)
        batch = time.perf_counter_ns() - start
        samples.append(batch // inner)
        total += batch
    values = to_list(out)
    print(json.dumps(dict(impl=impl, kernel=kernel, status='ok', n_out=len(values),
                          checksum=checksum(values), reps=len(samples), inner=inner, ns_min=min(samples),
                          ns_median=int(statistics.median(samples)), ns_total=total)))
    return 0