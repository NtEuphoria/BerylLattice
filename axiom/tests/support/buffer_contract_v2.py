"""B1 observable Python fixture, NOT a native host or qualification mechanism.

Only sizes consumes arbitrary admitted shapes. Execution deliberately supports
only the hand-reviewed 1x2 fixture. Callback faults/controls are tests, never
selectable production lifecycle behavior.
"""
from dataclasses import dataclass, field
import unittest

from axiom.reference import evaluate_source
from axiom.source_profiles import SourceLimitsV2, SourceProfileV2, admit_source_v2


def admit(source):
    return admit_source_v2(source, profile=SourceProfileV2(), limits=SourceLimitsV2())


@dataclass(frozen=True)
class Sizes:
    input_cells: int
    output_cells: int
    input_bytes: int
    output_bytes: int
    state_bytes: int
    scratch_bytes: int


def sizes(source, capacity, *, size_max=2**64-1):
    return _sizes(admit(source), capacity, size_max)


def _sizes(kernel, capacity, size_max=2**64-1):
    if type(capacity) is not int or not 0 <= capacity <= kernel.input_cells:
        raise ValueError('reserved scratch capacity must be an exact integer in 0..P')
    if type(size_max) is not int or size_max < 0:
        raise ValueError('invalid target SIZE_MAX')
    p, q = kernel.input_cells, kernel.output_cells
    # Python's mathematical arithmetic precedes any target narrowing/allocation.
    quantities = (p, q, capacity, 4*p, 4*q, 4*(p+q), 4*capacity)
    if max(p, q, capacity) > 2**31-1 or any(n > size_max for n in quantities):
        raise ValueError('count/byte arithmetic does not fit target')
    if kernel.cap is not None and 4*capacity > kernel.cap:
        raise ValueError('reserved scratch exceeds effective source cap')
    return Sizes(p, q, 4*p, 4*q, 4*(p+q), 4*capacity)


@dataclass
class Descriptor:
    data: list | None
    length: int
    capacity: int


@dataclass
class Owner:
    data: list
    role: str
    identity: object = field(default_factory=object)
    generation: int = 1
    live: bool = True
    alignment: int = 4
    initialized: int = field(init=False)
    descriptor: Descriptor = field(init=False)

    def __post_init__(self):
        self.initialized = len(self.data)
        self.descriptor = Descriptor(self.data, len(self.data), len(self.data))


@dataclass
class Invocation:
    source: bytes
    compiled_source_sha256: str
    input: Owner
    output: Owner
    original_input: tuple
    original_output: tuple


def prepare(source, values, initial):
    kernel = admit(source)
    if (kernel.height, kernel.width) != (1, 2):
        raise ValueError('execution fixture is specialized to 1x2 only')
    for data, count in ((values, kernel.input_cells), (initial, kernel.output_cells)):
        if type(data) not in (list, tuple) or len(data) != count:
            raise ValueError('wrong owned-buffer extent')
        if any(type(x) is not int or not -2**31 <= x < 2**31 for x in data):
            raise ValueError('buffer values must be exact i32 integers')
    return Invocation(source, kernel.source_sha256, Owner(list(values), 'input'),
                      Owner(list(initial), 'output'), tuple(values), tuple(initial))


@dataclass(frozen=True)
class Result:
    completion: str
    status: str | None = None
    first_bad_index: int | None = None
    state: tuple | None = None


_UNSET = object()


class Callbacks:
    """Real Python callbacks with observable allocation, reads and mutation."""
    def __init__(self, *, fault=None, preflight_result=_UNSET):
        self.fault = fault
        self.preflight_result = preflight_result
        self.events = []
        self.allocations = []
        self.allocated = []
        self.freed = []
        self.body_scratch = None
        self.read_indices = []
        self.scratch_was_zero = False

    def preflight(self, input):
        self.events.append('preflight')
        if self.preflight_result is not _UNSET:
            return self.preflight_result
        for index, value in enumerate(input.data):
            self.read_indices.append(index)
            if not 0 <= value <= 1023:
                return index
        return -1

    def allocate(self, capacity):
        self.events.append(f'allocate:{capacity}')
        if self.fault == 'oom':
            raise MemoryError('injected scratch OOM')
        storage = [None]*capacity
        self.allocations.append((capacity, 4*capacity))
        self.allocated.append(storage)
        return storage

    def zero(self, storage):
        self.events.append(f'zero:{len(storage)}')
        for index in range(len(storage)):
            storage[index] = 0

    def body(self, input, output, scratch):
        self.events.append('body')
        self.body_scratch = (scratch.data, scratch.length, scratch.capacity)
        self.scratch_was_zero = scratch.data is None or all(value == 0 for value in scratch.data)
        if self.fault == 'trap':
            raise RuntimeError('injected body trap')
        producers = [(value+1)*(value+1) for value in input.data]
        if scratch.capacity:
            for index, value in enumerate(producers):
                scratch.data[index] = value
        for c in range(2):
            output.data[c] = ((producers[c]+producers[c+1])+producers[c+3])+producers[c+4]
        if self.fault == 'descriptor':
            # Cleanup must still receive the original recorded storage.
            scratch.data = [999]
            output.capacity += 1
        if self.fault == 'input_mutation':
            input.data[-1] += 1
        if self.fault == 'mismatch':
            output.data[-1] += 1

    def free(self, storage):
        self.events.append(f'free:{len(storage)}')
        self.freed.append(storage)

    def acquire(self, invocation):
        self.events.append('acquire')
        if self.fault == 'acquire':
            raise OSError('injected incomplete acquisition')
        if self.fault == 'partial_acquire':
            return tuple(invocation.input.data), tuple(invocation.output.data[:-1])
        return tuple(invocation.input.data), tuple(invocation.output.data)

    def compare(self, invocation, state, status, bad):
        self.events.append('compare')
        expected = evaluate_source(admit(invocation.source).source_module,
                                   invocation.original_input, invocation.original_output)
        if state[0] != expected.input_after:
            return 'integrity_error'
        if (state[1], status, bad) != (expected.output, expected.status.value, expected.first_bad_index):
            return 'comparison_error'
        return None


def _snapshot(descriptor):
    return descriptor.data, descriptor.length, descriptor.capacity


def _same(descriptor, recorded):
    return descriptor.data is recorded[0] and (descriptor.length, descriptor.capacity) == recorded[1:]


def checked_call(invocation, callbacks, *, scratch_capacity):
    # Fresh source-byte validation/binding belongs to fixture preparation, outside
    # the checked-call event interval. There is no caller validation bit.
    kernel = admit(invocation.source)
    callbacks.events.extend(['timer_start', 'metadata'])
    owners = (invocation.input, invocation.output)
    for owner, role, count in zip(owners, ('input', 'output'), (kernel.input_cells, kernel.output_cells)):
        numeric_metadata = (owner.generation, owner.alignment, owner.initialized,
                            owner.descriptor.length, owner.descriptor.capacity)
        if (any(type(value) is not int for value in numeric_metadata)
                or owner.live is not True or owner.generation != 1 or owner.role != role
                or owner.alignment < 4 or owner.alignment % 4 or owner.initialized != count
                or len(owner.data) != count or owner.descriptor.data is not owner.data
                or (owner.descriptor.length, owner.descriptor.capacity) != (count, count)):
            callbacks.events.append('timer_end')
            return Result('boundary_error')
    if (owners[0].identity is owners[1].identity or owners[0].data is owners[1].data
            or invocation.compiled_source_sha256 != kernel.source_sha256):
        callbacks.events.append('timer_end')
        return Result('boundary_error')
    descriptors = [owner.descriptor for owner in owners]
    records = [_snapshot(d) for d in descriptors]
    storage = None
    completion = None
    status, bad = None, None
    try:
        preflight = callbacks.preflight(descriptors[0])
        if type(preflight) is not int or not -1 <= preflight < kernel.input_cells:
            completion = 'process_error'
        elif preflight >= 0:
            status, bad = 'input_precondition_failed', preflight
        else:
            _sizes(kernel, scratch_capacity)
            if scratch_capacity not in (0, 6):
                raise ValueError('tiny fixture supports only inline or six-cell materialization')
            scratch = Descriptor(None, 0, 0)
            if scratch_capacity:
                storage = callbacks.allocate(scratch_capacity)
                callbacks.zero(storage)
                scratch = Descriptor(storage, scratch_capacity, scratch_capacity)
            descriptors.append(scratch)
            records.append(_snapshot(scratch))
            callbacks.body(descriptors[0], descriptors[1], scratch)
            status = 'success'
        if completion is None:
            callbacks.events.append('integrity')
            if not all(_same(d, record) for d, record in zip(descriptors, records)):
                completion = 'integrity_error'
    except MemoryError:
        completion = 'resource_error'
    except ValueError:
        completion = 'boundary_error'
    except RuntimeError:
        completion = 'process_error'
    finally:
        if storage is not None:
            callbacks.free(storage)
        callbacks.events.append('timer_end')
    if completion is not None:
        return Result(completion)
    try:
        state = callbacks.acquire(invocation)
    except OSError:
        return Result('acquisition_error')
    if (type(state) is not tuple or len(state) != 2
            or any(type(part) is not tuple for part in state)
            or (len(state[0]), len(state[1])) != (kernel.input_cells, kernel.output_cells)):
        return Result('acquisition_error')
    failure = callbacks.compare(invocation, state, status, bad)
    return Result(failure) if failure else Result('complete', status, bad, state)


def exercise_control(mutation):
    """Deliberately bad proposals; unchanged behavioral assertions reject each."""
    from tests.helpers import stencil_source
    check = unittest.TestCase()
    invocation = prepare(stencil_source(1, 2, None), [-1, 1, 2, 3, 4, 5], [-99, 77])
    cb = Callbacks()
    if mutation == 'scratch_before_preflight':
        storage = cb.allocate(6)
        cb.zero(storage)
        cb.preflight(invocation.input.descriptor)
        cb.free(storage)
        check.assertEqual(cb.allocations, [], 'invalid input must not allocate scratch')
    elif mutation == 'caller_validation_bit':
        # Model a proposed validated=True API that skips the actual preflight.
        validated = True
        if validated:
            cb.body(invocation.input.descriptor, invocation.output.descriptor, Descriptor(None, 0, 0))
        check.assertEqual(invocation.output.data, [-99, 77], 'validation bit bypass changed output')
    elif mutation == 'used_capacity':
        # Real reservation of six cells, incorrectly charged as one used cell.
        storage = cb.allocate(6)
        reported_bytes = 4
        cb.free(storage)
        check.assertEqual(reported_bytes, sum(size for _, size in cb.allocations),
                          'every reserved cell must be charged')
    else:
        raise ValueError('unknown control')
