"""Optional request-local compilation diagnostics, separate from work receipts.

Callers branch on ``trace is not None`` so disabled tracing allocates no timers.
Nested phases are inclusive; their durations must never be added as disjoint work.
A trace belongs to one synchronous request and is not a cross-thread collector.
"""
from contextlib import contextmanager
from time import perf_counter_ns

PHASES = (
    'source_admission', 'candidate_generation', 'structural_validation',
    'semantic_checking', 'canonical_encoding', 'internal_decode',
    'loop_correspondence', 'code_emission', 'native_compiler_link',
    'wasm_compile', 'wasm_instantiate', 'first_execution', 'verification',
    'total_fresh_source_preparation', 'total_app_boot',
)


class CompilationTrace:
    """Accumulate inclusive nanosecond timings and exact integer event counts."""

    __slots__ = ('_clock', '_phases', '_counts')

    def __init__(self, *, clock=perf_counter_ns):
        self._clock = clock
        self._phases = {}
        self._counts = {}

    @contextmanager
    def phase(self, name):
        start = self._clock()
        try:
            yield
        finally:
            elapsed = self._clock() - start
            record = self._phases.setdefault(name, {'elapsed_ns': 0, 'calls': 0})
            record['elapsed_ns'] += elapsed
            record['calls'] += 1

    def count(self, name, amount=1):
        if type(amount) is not int or amount < 0:
            raise ValueError('trace counter amount must be a nonnegative exact integer')
        self._counts[name] = self._counts.get(name, 0) + amount

    def report(self):
        """Return an independently mutable JSON-compatible diagnostic snapshot."""
        return {'schema_version': 1, 'timing_unit': 'ns',
                'timing_semantics': 'inclusive',
                'phases': {name: dict(record) for name, record in self._phases.items()},
                'counts': dict(self._counts)}
