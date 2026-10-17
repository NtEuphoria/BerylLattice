"""Original-source streaming evaluator for the admitted fixed-buffer family.

This module issues complete state artifacts, never oracle qualification. See
protocol/source-oracle-v1.md for resource units and cooperative boundaries.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict, dataclass, field
import errno
import hashlib
import os
from pathlib import Path
import shutil
import struct
import tempfile
import time
from typing import Callable

from axiom.invocation_v2 import VerifiedInvocation
from axiom.model import (BinaryExpression, DiagnosticError, EquationDeclaration,
                         GroupExpression, InputDeclaration, IntegerLiteral,
                         NameReference, ReadExpression, ShapeDeclaration)
from axiom.source_profiles import SourceLimitsV2, SourceProfileV2, admit_source_v2
if __package__:
    from .state_artifacts import ArtifactLimits, StateMetadata, canonical_json, verify_state, write_state
else:
    from state_artifacts import ArtifactLimits, StateMetadata, canonical_json, verify_state, write_state


@dataclass(frozen=True, slots=True)
class OracleLimits:
    max_source_bytes: int = 65_536
    max_cached_input_bytes: int = 2_097_152
    max_scalar_evaluations: int = 1_000_000_000
    max_temporary_bytes: int = 268_435_456
    max_input_snapshot_bytes: int = 33_554_432
    state_limits: ArtifactLimits = field(default_factory=ArtifactLimits)
    deadline_monotonic_ns: int | None = None
    cancelled: Callable[[], bool] | None = None

    def __post_init__(self):
        for name, minimum, maximum in (
            ('max_source_bytes', 1, 65_536),
            ('max_cached_input_bytes', 4, 2_097_152),
            ('max_scalar_evaluations', 1, 1_000_000_000),
            ('max_temporary_bytes', 1, 268_435_456),
            ('max_input_snapshot_bytes', 1, 33_554_432),
        ):
            value = getattr(self, name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f'invalid {name}')
        if type(self.state_limits) is not ArtifactLimits:
            raise ValueError('expected ArtifactLimits')
        self.state_limits.__post_init__()
        ceiling = ArtifactLimits()
        for name, value in asdict(self.state_limits).items():
            if value > getattr(ceiling, name):
                raise ValueError(f'state limit may only tighten: {name}')
        if (self.deadline_monotonic_ns is not None and
                (type(self.deadline_monotonic_ns) is not int or not 0 <= self.deadline_monotonic_ns <= (1 << 63)-1)):
            raise ValueError('invalid monotonic deadline')
        if self.cancelled is not None and not callable(self.cancelled):
            raise ValueError('invalid cancellation callable')


@dataclass(frozen=True, slots=True)
class OracleResult:
    status: str
    state_manifest: Path | None
    first_bad_index: int | None
    source_sha256: str | None
    family_semantics_sha256: str | None
    specialization_semantics_sha256: str | None
    invocation_sha256: str | None
    state_invocation_sha256: str | None
    scalar_evaluations: int
    input_preflight_scalars: int
    emitted_state_scalars: int
    input_read_scalars: int
    input_snapshot_bytes: int
    failure_detail: str | None
    acquired_input_bytes: int = 0
    snapshot_read_bytes: int = 0
    cache_misses: int = 0
    peak_cached_input_bytes: int = 0

    def __post_init__(self):
        complete = self.status in ('success', 'input_precondition_failed')
        if type(self.status) is not str or self.status not in (
                'success', 'input_precondition_failed', 'unsupported_source', 'invalid_invocation',
                'work_limit', 'cancelled', 'timeout', 'resource_limit', 'allocation_failure', 'io_failure'):
            raise ValueError('invalid oracle status')
        if complete != isinstance(self.state_manifest, Path) or (not complete and self.state_manifest is not None):
            raise ValueError('only complete outcomes have a state manifest')
        if self.status == 'input_precondition_failed':
            if type(self.first_bad_index) is not int or self.first_bad_index < 0:
                raise ValueError('invalid first bad index')
        elif self.first_bad_index is not None:
            raise ValueError('only rejected input has a first bad index')
        for name in ('source_sha256', 'family_semantics_sha256', 'specialization_semantics_sha256',
                     'invocation_sha256', 'state_invocation_sha256'):
            value = getattr(self, name)
            if value is None:
                if complete:
                    raise ValueError('complete outcomes require all identities')
            elif type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
                raise ValueError('invalid oracle identity')
        for name in ('scalar_evaluations', 'input_preflight_scalars', 'emitted_state_scalars',
                     'input_read_scalars', 'input_snapshot_bytes', 'acquired_input_bytes',
                     'snapshot_read_bytes', 'cache_misses', 'peak_cached_input_bytes'):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError('invalid oracle counter')
        if complete:
            if self.failure_detail is not None:
                raise ValueError('complete outcomes have no operational failure detail')
        elif type(self.failure_detail) is not str or not 1 <= len(self.failure_detail) <= 128:
            raise ValueError('incomplete outcomes require bounded failure detail')


class _Stop(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail
        super().__init__(detail)


class _Work:
    def __init__(self, limits):
        self.limits = limits
        self.scalar_evaluations = self.input_preflight_scalars = 0
        self.emitted_state_scalars = self.input_read_scalars = 0
        self.input_snapshot_bytes = self.acquired_input_bytes = 0
        self.snapshot_read_bytes = self.cache_misses = self.peak_cached_input_bytes = 0

    def poll(self):
        callback = self.limits.cancelled
        if callback is not None:
            answer = callback()
            if type(answer) is not bool:
                raise TypeError('cancellation callable must return exact bool')
            if answer:
                raise _Stop('cancelled', 'cancelled')
        if (self.limits.deadline_monotonic_ns is not None and
                time.monotonic_ns() >= self.limits.deadline_monotonic_ns):
            raise _Stop('timeout', 'deadline_expired')

    def charge(self):
        self.poll()
        if self.scalar_evaluations >= self.limits.max_scalar_evaluations:
            raise _Stop('work_limit', 'ast_visit_limit')
        self.scalar_evaluations += 1

    def result(self, status, identities, *, manifest=None, bad=None, detail=None):
        return OracleResult(status=status, state_manifest=manifest, first_bad_index=bad,
            **identities, **{name: getattr(self, name) for name in (
                'scalar_evaluations', 'input_preflight_scalars', 'emitted_state_scalars',
                'input_read_scalars', 'input_snapshot_bytes', 'acquired_input_bytes',
                'snapshot_read_bytes', 'cache_misses', 'peak_cached_input_bytes')}, failure_detail=detail)


def _checked_i32(value):
    if type(value) is not int or not -(1 << 31) <= value < (1 << 31):
        # Admitted expressions with valid input cannot overflow. This is an
        # operational integrity failure, never an input precondition rejection.
        raise _Stop('resource_limit', 'source_i32_failure')
    return value


def _evaluate_expression(node, scalars, tensors, work):
    """Visit original nodes, charging before dispatch; preserve source order."""
    work.charge()
    if isinstance(node, IntegerLiteral):
        value = node.value
    elif isinstance(node, NameReference):
        value = scalars[node.name]
    elif isinstance(node, GroupExpression):
        value = _evaluate_expression(node.expression, scalars, tensors, work)
    elif isinstance(node, BinaryExpression):
        left = _evaluate_expression(node.left, scalars, tensors, work)
        right = _evaluate_expression(node.right, scalars, tensors, work)
        if node.operator == '+':
            value = left + right
        elif node.operator == '*':
            value = left * right
        else:
            raise RuntimeError('admission allowed unknown operator')
    elif isinstance(node, ReadExpression):
        indices = tuple(_evaluate_expression(index, scalars, tensors, work) for index in node.indices)
        value = tensors[node.name].read(indices)
    else:
        raise RuntimeError('admission allowed unknown expression')
    return _checked_i32(value)


class _SnapshotI32Reader:
    """At most two aligned byte chunks; evict before allocating the next."""
    def __init__(self, stream, cells, work):
        self.fd, self.cells, self.work = stream.fileno(), cells, work
        budget = work.limits.max_cached_input_bytes
        self.chunk_bytes = min(1_048_576, max(4, (budget//2)//4*4))
        self.capacity = min(2, budget//self.chunk_bytes)
        self.cache = OrderedDict()
        self.retained = 0

    def read(self, index):
        self.work.poll()
        if type(index) is not int or not 0 <= index < self.cells:
            raise RuntimeError('snapshot scalar index outside bounds')
        self.work.input_read_scalars += 1
        offset = 4*index
        start = offset//self.chunk_bytes*self.chunk_bytes
        if start in self.cache:
            self.cache.move_to_end(start)
        else:
            if len(self.cache) >= self.capacity:
                _, old = self.cache.popitem(last=False)
                self.retained -= len(old)
                del old
            length = min(self.chunk_bytes, 4*self.cells-start)
            raw = os.pread(self.fd, length, start)
            self.work.snapshot_read_bytes += len(raw)
            if len(raw) != length:
                raise _Stop('io_failure', 'snapshot_short_read')
            self.cache[start] = raw
            self.retained += len(raw)
            self.work.cache_misses += 1
            self.work.peak_cached_input_bytes = max(self.work.peak_cached_input_bytes, self.retained)
            del raw
        return struct.unpack_from('<i', self.cache[start], offset-start)[0]


class _InputTensor:
    def __init__(self, dimensions, reader):
        self.dimensions, self.reader = dimensions, reader

    def read(self, indices):
        if len(indices) != len(self.dimensions):
            raise RuntimeError('source tensor arity mismatch')
        offset = 0
        for index, dimension in zip(indices, self.dimensions):
            _checked_i32(index)
            if not 0 <= index < dimension:
                raise RuntimeError('source tensor index outside bounds')
            offset = _checked_i32(offset*dimension+index)
        return self.reader.read(offset)


class _ProducerTensor:
    def __init__(self, declaration, bounds, shapes, tensors, work):
        self.declaration, self.bounds = declaration, bounds
        self.shapes, self.tensors, self.work = shapes, tensors, work

    def read(self, indices):
        if len(indices) != len(self.bounds):
            raise RuntimeError('source producer arity mismatch')
        scalars = dict(self.shapes)
        for axis, index, (lower, upper) in zip(self.declaration.axes, indices, self.bounds):
            _checked_i32(index)
            if not lower <= index < upper:
                raise RuntimeError('source producer index outside bounds')
            scalars[axis.name] = index
        return _evaluate_expression(self.declaration.expression, scalars, self.tensors, self.work)


def _bounds(declaration, shapes, tensors, work):
    return tuple((_evaluate_expression(axis.lower, shapes, tensors, work),
                  _evaluate_expression(axis.upper, shapes, tensors, work)) for axis in declaration.axes)


def _iter_output(module, reader, work):
    shapes, tensors = {}, {}
    output = None
    for declaration in module.declarations:
        if isinstance(declaration, ShapeDeclaration):
            shapes[declaration.name] = _evaluate_expression(declaration.value, shapes, tensors, work)
        elif isinstance(declaration, InputDeclaration):
            dimensions = tuple(_evaluate_expression(node, shapes, tensors, work) for node in declaration.dimensions)
            tensors[declaration.name] = _InputTensor(dimensions, reader)
        elif isinstance(declaration, EquationDeclaration):
            bounds = _bounds(declaration, shapes, tensors, work)
            if declaration.kind == 'producer':
                tensors[declaration.name] = _ProducerTensor(declaration, bounds, shapes, tensors, work)
            elif declaration.kind == 'output':
                output = declaration, bounds
            else:
                raise RuntimeError('admission allowed unknown declaration kind')
    if output is None:
        raise RuntimeError('admission omitted output')
    declaration, bounds = output
    # product caches its input ranges; recurse instead to retain only one
    # coordinate per axis, including the large supported thin shapes.
    scalars = dict(shapes)
    def coordinates(axis_number):
        if axis_number == len(bounds):
            yield _evaluate_expression(declaration.expression, scalars, tensors, work)
            return
        lower, upper = bounds[axis_number]
        for index in range(lower, upper):
            scalars[declaration.axes[axis_number].name] = index
            yield from coordinates(axis_number+1)
    yield from coordinates(0)


def _metadata_items(item):
    if type(item) is dict:
        return 1 + sum(1+_metadata_items(value) for value in item.values())
    if type(item) in (tuple, list):
        return 1 + sum(_metadata_items(value) for value in item)
    return 1


def _reserve_payload(admitted, invocation, work):
    """Conservative no-dedup logical reservation, before input acquisition."""
    limits, state = work.limits, work.limits.state_limits
    input_bytes, output_bytes = 4*admitted.input_cells, 4*admitted.output_cells
    logical = input_bytes+output_bytes
    counts = [(length+state.chunk_bytes-1)//state.chunk_bytes for length in (input_bytes, output_bytes)]
    chunk_count = sum(counts)
    if (input_bytes > limits.max_input_snapshot_bytes or logical > state.max_logical_bytes or
            chunk_count+1 > state.max_files or chunk_count > state.max_metadata_items//11):
        raise _Stop('resource_limit', 'state_or_snapshot_quota')
    # Failure status and largest first-bad offset are the longest supported
    # metadata. Hash/path strings have fixed lengths independent of contents.
    metadata = StateMetadata(admitted.specialization_semantics_sha256, admitted.height, admitted.width,
        invocation.input.sha256, invocation.initial_output.sha256, 'input_precondition_failed', admitted.input_cells-1)
    record = dict(schema='axiom-state-v1', metadata=metadata.to_record(), chunks=[])
    metadata_bytes = len(canonical_json(record))
    metadata_items = _metadata_items(record)+11*chunk_count
    if state.max_metadata_depth < 3 or metadata_items > state.max_metadata_items:
        raise _Stop('resource_limit', 'state_metadata_quota')
    for role, length in (('input_after', input_bytes), ('output', output_bytes)):
        for offset in range(0, length, state.chunk_bytes):
            work.poll()
            size = min(state.chunk_bytes, length-offset)
            if size > state.max_file_bytes:
                raise _Stop('resource_limit', 'state_file_quota')
            chunk = dict(role=role, offset=offset, byte_length=size, sha256='0'*64, path='chunks/'+'0'*64+'.i32')
            metadata_bytes += len(canonical_json(chunk))
    metadata_bytes += max(0, chunk_count-1)
    if metadata_bytes > min(state.max_metadata_bytes, state.max_file_bytes):
        raise _Stop('resource_limit', 'state_metadata_quota')
    if logical+metadata_bytes > state.max_aggregate_bytes:
        raise _Stop('resource_limit', 'state_aggregate_quota')
    if input_bytes+logical+state.max_metadata_bytes > limits.max_temporary_bytes:
        raise _Stop('resource_limit', 'temporary_payload_quota')


class _Operation:
    """Exclusive pinned directory; caller-owned ancestors are never created."""
    def __init__(self, destination):
        self.path = Path(os.path.abspath(destination))
        self.parent_fd = self.fd = None
        self.created = self.committed = False

    def __enter__(self):
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        self.parent_fd = os.open(self.path.anchor, flags)
        try:
            for component in self.path.parent.parts[1:]:
                child = os.open(component, flags, dir_fd=self.parent_fd)
                previous = self.parent_fd
                self.parent_fd = child
                os.close(previous)
            descriptor = self.parent_fd
            os.mkdir(self.path.name, 0o700, dir_fd=descriptor)
            self.created = True
            self.fd = os.open(self.path.name, flags, dir_fd=descriptor)
            os.mkdir('.pending', 0o700, dir_fd=self.fd)
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def publish(self):
        os.rename('.pending', 'completed', src_dir_fd=self.fd, dst_dir_fd=self.fd)
        self.committed = True

    def __exit__(self, *args):
        # Nothing after publication changes its semantic status. In the stable
        # filesystem model these cleanup operations close/remove all owned data.
        if not self.committed and self.fd is not None:
            try:
                shutil.rmtree('.pending', dir_fd=self.fd)
            except OSError:
                pass
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
        if self.created and not self.committed:
            try:
                os.rmdir(self.path.name, dir_fd=self.parent_fd)
            except OSError:
                pass
        if self.parent_fd is not None:
            try:
                os.close(self.parent_fd)
            except OSError:
                pass
            self.parent_fd = None


def _artifact_failure(exc):
    cause = exc
    while cause is not None:
        if isinstance(cause, OSError) and cause.errno in (errno.ENOSPC, errno.EDQUOT, errno.EFBIG):
            return _Stop('resource_limit', 'storage_quota')
        cause = cause.__cause__
    return _Stop('io_failure', 'artifact_verification_failed')


def _verified_blocks(blob):
    iterator = iter(blob.iter_bytes())
    while True:
        try:
            block = next(iterator)
        except StopIteration:
            return
        except ValueError as exc:
            raise _artifact_failure(exc) from exc
        yield block


class _InterpreterError(Exception):
    """Keep programmer ValueErrors distinct from state helper ValueErrors."""
    def __init__(self, original):
        self.original = original


def _copy_input(invocation, snapshot, admitted, work):
    digest, carry, total, bad = hashlib.sha256(), b'', 0, None
    lower, upper = admitted.input_interval
    for block in _verified_blocks(invocation.input):
        work.poll()
        total += len(block)
        work.acquired_input_bytes += len(block)
        if total > invocation.input.byte_length:
            raise _Stop('invalid_invocation', 'input_length_changed')
        digest.update(block)
        written = snapshot.write(block)
        if type(written) is not int or not 0 <= written <= len(block):
            raise _Stop('io_failure', 'snapshot_invalid_write_count')
        work.input_snapshot_bytes += written
        if written != len(block):
            raise _Stop('io_failure', 'snapshot_short_write')
        # A generic blob block may split a scalar. Only the unfinished suffix
        # survives a block; this decoding buffer is not an evaluation cache.
        raw = carry+block
        aligned = len(raw)//4*4
        for offset in range(0, aligned, 4):
            work.poll()
            value = struct.unpack_from('<i', raw, offset)[0]
            index = work.input_preflight_scalars
            if bad is None and not lower <= value <= upper:
                bad = index
            work.input_preflight_scalars += 1
        carry = raw[aligned:]
        del raw, block
    if carry or total != invocation.input.byte_length or digest.hexdigest() != invocation.input.sha256:
        raise _Stop('invalid_invocation', 'input_content_changed')
    snapshot.flush()
    work.poll()
    return bad


def _snapshot_scalars(snapshot, cells, work):
    # Sequential preservation pass uses bounded blocks and bypasses the random
    # cache, leaving its payload allowance solely for expression reads.
    for offset in range(0, cells*4, 65_536):
        work.poll()
        length = min(65_536, cells*4-offset)
        raw = os.pread(snapshot.fileno(), length, offset)
        work.snapshot_read_bytes += len(raw)
        if len(raw) != length:
            raise _Stop('io_failure', 'snapshot_short_read')
        for (value,) in struct.iter_unpack('<i', raw):
            work.poll()
            yield value


def _blob_scalars(blob, work):
    carry = b''
    for block in _verified_blocks(blob):
        work.poll()
        raw = carry+block
        aligned = len(raw)//4*4
        for offset in range(0, aligned, 4):
            work.poll()
            yield struct.unpack_from('<i', raw, offset)[0]
        carry = raw[aligned:]
    if carry:
        raise _Stop('invalid_invocation', 'output_alignment_changed')


def _emitted(values, expected, work):
    count = 0
    iterator = iter(values)
    while True:
        try:
            work.poll()
            value = next(iterator)
        except StopIteration:
            break
        except ValueError as exc:
            raise _InterpreterError(exc) from exc
        if count >= expected:
            raise RuntimeError('source emitted too many scalars')
        count += 1
        work.emitted_state_scalars += 1
        yield value
    if count != expected:
        raise RuntimeError('source emitted too few scalars')


def _revalidate(invocation, work):
    work.poll()
    try:
        invocation.revalidate()
    except (ValueError, OSError) as exc:
        raise _Stop('invalid_invocation', 'invocation_revalidation_failed') from exc
    work.poll()


def evaluate_source_state(source_bytes: bytes, invocation: VerifiedInvocation, destination: Path,
                          *, profile: SourceProfileV2, limits: OracleLimits) -> OracleResult:
    """Produce one complete state from exact source bytes, or an incomplete result.

    Invalid configuration raises ValueError; unrelated programming exceptions
    propagate. Operational controls have bounded diagnostic codes in results.
    """
    if type(limits) is not OracleLimits or type(profile) is not SourceProfileV2:
        raise ValueError('expected OracleLimits and SourceProfileV2')
    limits.__post_init__()
    profile.__post_init__()
    if not isinstance(destination, Path):
        raise ValueError('destination must be Path')
    work = _Work(limits)
    identities = dict.fromkeys(('source_sha256', 'family_semantics_sha256',
        'specialization_semantics_sha256', 'invocation_sha256', 'state_invocation_sha256'))
    try:
        work.poll()
        if type(source_bytes) is not bytes:
            raise _Stop('unsupported_source', 'expected_exact_source_bytes')
        try:
            admitted = admit_source_v2(source_bytes, profile=profile,
                limits=SourceLimitsV2(source_bytes=limits.max_source_bytes))
        except (DiagnosticError, ValueError, UnicodeError) as exc:
            raise _Stop('unsupported_source', 'source_admission_failed') from exc
        identities.update(source_sha256=admitted.source_sha256,
            family_semantics_sha256=admitted.family_semantics_sha256,
            specialization_semantics_sha256=admitted.specialization_semantics_sha256)
        if type(invocation) is not VerifiedInvocation:
            raise _Stop('invalid_invocation', 'expected_verified_invocation')
        _revalidate(invocation, work)
        if (invocation.source_bytes != source_bytes or invocation.source_profile != profile or
                (invocation.source_sha256, invocation.family_semantics_sha256,
                 invocation.specialization_semantics_sha256, invocation.H, invocation.W) !=
                (admitted.source_sha256, admitted.family_semantics_sha256,
                 admitted.specialization_semantics_sha256, admitted.height, admitted.width)):
            raise _Stop('invalid_invocation', 'source_invocation_mismatch')
        identities.update(invocation_sha256=invocation.invocation_sha256,
                          state_invocation_sha256=invocation.state_v1_invocation_sha256())
        _reserve_payload(admitted, invocation, work)
        work.poll()
        with _Operation(destination) as operation:
            with tempfile.TemporaryFile(mode='w+b', dir=operation.path) as snapshot:
                bad = _copy_input(invocation, snapshot, admitted, work)
                status = 'success' if bad is None else 'input_precondition_failed'
                metadata = StateMetadata(admitted.specialization_semantics_sha256, admitted.height,
                    admitted.width, invocation.input.sha256, invocation.initial_output.sha256, status, bad)
                if metadata.invocation_sha256 != identities['state_invocation_sha256']:
                    raise _Stop('invalid_invocation', 'state_identity_mismatch')
                reader = _SnapshotI32Reader(snapshot, admitted.input_cells, work)
                output = (_iter_output(admitted.source_module, reader, work) if bad is None else
                          _blob_scalars(invocation.initial_output, work))
                work.poll()
                try:
                    manifest = write_state(
                        _emitted(_snapshot_scalars(snapshot, admitted.input_cells, work), admitted.input_cells, work),
                        _emitted(output, admitted.output_cells, work), metadata, operation.path/'.pending',
                        limits=limits.state_limits)
                except ValueError as exc:
                    raise _artifact_failure(exc) from exc
                work.poll()
                try:
                    checked = verify_state(manifest, limits=limits.state_limits)
                except ValueError as exc:
                    raise _artifact_failure(exc) from exc
                if checked.metadata != metadata or checked.metadata.invocation_sha256 != identities['state_invocation_sha256']:
                    raise _Stop('io_failure', 'state_verification_mismatch')
                _revalidate(invocation, work)
                # Allocate the result and close snapshot before the final poll
                # and commit. No fallible verification follows publication.
                result = work.result(status, identities, manifest=operation.path/'completed'/'state.json', bad=bad)
            work.poll()
            operation.publish()
            return result
    except _InterpreterError as exc:
        raise exc.original
    except _Stop as exc:
        return work.result(exc.status, identities, detail=exc.detail)
    except MemoryError:
        return work.result('allocation_failure', identities, detail='allocation_failed')
    except RecursionError:
        return work.result('resource_limit', identities, detail='expression_recursion_limit')
    except OSError as exc:
        status = 'resource_limit' if exc.errno in (errno.ENOSPC, errno.EDQUOT, errno.EFBIG) else 'io_failure'
        return work.result(status, identities, detail='storage_quota' if status == 'resource_limit' else 'artifact_io_failed')
