"""Exact-source v2 invocation transport, independent of plans and execution.

The buffer contract describes required host behavior. It does not attest actual
pointer ownership or disjointness. Native admission must acquire real buffers.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
from typing import Iterable

from .artifact_chunks_v2 import (
    BlobLimits, BlobReference, VerifiedBlob, _absolute, _decode_json, _identity,
    _integer, _keys, _limits, _relative, _validate_reference, _write_immutable, canonical_json,
    read_manifest, verify_blob, write_blob,
)
from .source_profiles import SourceLimitsV2, SourceProfileV2, admit_source_v2

BUFFER_CONTRACT = 'axiom-core-buffer-host-v1'


@dataclass(frozen=True, slots=True)
class InvocationLimits:
    blobs: BlobLimits = BlobLimits()
    source_profile: SourceProfileV2 = SourceProfileV2()
    source_limits: SourceLimitsV2 = SourceLimitsV2()

    def __post_init__(self):
        _limits(self.blobs)
        if type(self.source_profile) is not SourceProfileV2 or type(self.source_limits) is not SourceLimitsV2:
            raise ValueError('expected source profile and source limits records')
        self.source_profile.__post_init__()
        self.source_limits.__post_init__()


def _invocation_limits(limits):
    if type(limits) is not InvocationLimits:
        raise ValueError('expected InvocationLimits')
    limits.__post_init__()


def _content(reference):
    return dict(byte_length=reference.byte_length, sha256=reference.sha256)


@dataclass(frozen=True, slots=True)
class InvocationManifest:
    source: BlobReference
    source_sha256: str
    family_semantics_sha256: str
    specialization_semantics_sha256: str
    source_profile: SourceProfileV2
    H: int
    W: int
    input: BlobReference
    initial_output: BlobReference
    buffer_contract: str = BUFFER_CONTRACT

    def __post_init__(self):
        if type(self.source_profile) is not SourceProfileV2:
            raise ValueError('expected SourceProfileV2')
        self.source_profile.__post_init__()
        for name in ('source', 'input', 'initial_output'):
            value = getattr(self, name)
            if type(value) is not BlobReference:
                raise ValueError(f'{name} must be BlobReference')
            _validate_reference(value)
        for name in ('source_sha256', 'family_semantics_sha256', 'specialization_semantics_sha256'):
            _identity(getattr(self, name), name)
        _integer(self.H, 'H', 1, self.source_profile.max_height)
        _integer(self.W, 'W', 1, self.source_profile.max_width)
        cells = (self.H+1)*(self.W+1)
        if cells > self.source_profile.max_input_cells:
            raise ValueError('invocation exceeds profile cell envelope')
        if self.input.byte_length != 4*cells or self.initial_output.byte_length != 4*self.H*self.W:
            raise ValueError('input/output lengths do not match source extents')
        if (self.source.sha256 != self.source_sha256 or type(self.buffer_contract) is not str
                or self.buffer_contract != BUFFER_CONTRACT):
            raise ValueError('invalid source identity or host buffer contract')

    @property
    def invocation_sha256(self):
        self.__post_init__()
        return hashlib.sha256(canonical_json(dict(
            identity_version='axiom-exact-source-invocation-v2',
            source=_content(self.source), source_sha256=self.source_sha256,
            family_semantics_sha256=self.family_semantics_sha256,
            specialization_semantics_sha256=self.specialization_semantics_sha256,
            source_profile=asdict(self.source_profile), H=self.H, W=self.W,
            input=_content(self.input), initial_output=_content(self.initial_output),
            buffer_contract=self.buffer_contract))).hexdigest()


def _reference_record(reference, root):
    try:
        path = reference.manifest_path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError('blob reference escapes invocation root') from exc
    return dict(path=_relative(path), manifest_sha256=reference.manifest_sha256,
                byte_length=reference.byte_length, sha256=reference.sha256)


def _reference(record, root):
    _keys(record, ('path', 'manifest_sha256', 'byte_length', 'sha256'), 'blob reference')
    return BlobReference(root/_relative(record['path']), record['manifest_sha256'],
                         record['byte_length'], record['sha256'])


@dataclass(frozen=True)
class VerifiedInvocation:
    manifest_path: Path
    manifest_sha256: str
    manifest: InvocationManifest
    limits: InvocationLimits
    source_bytes: bytes
    source: VerifiedBlob
    input: VerifiedBlob
    initial_output: VerifiedBlob

    @property
    def source_sha256(self):
        return self.manifest.source_sha256

    @property
    def family_semantics_sha256(self):
        return self.manifest.family_semantics_sha256

    @property
    def specialization_semantics_sha256(self):
        return self.manifest.specialization_semantics_sha256

    @property
    def H(self):
        return self.manifest.H

    @property
    def W(self):
        return self.manifest.W

    @property
    def invocation_sha256(self):
        return self.manifest.invocation_sha256

    @property
    def source_profile(self):
        return self.manifest.source_profile

    @property
    def buffer_contract(self):
        return self.manifest.buffer_contract

    def state_v1_invocation_sha256(self, logical_semantics_sha256=None):
        """Explicit domain mapping; default logical semantics is specialization.

        This does not enlarge v1 admission limits or authorize a v1 receipt.
        """
        logical = self.specialization_semantics_sha256 if logical_semantics_sha256 is None else logical_semantics_sha256
        _identity(logical, 'logical_semantics_sha256')
        return hashlib.sha256(canonical_json(dict(
            logical_semantics_sha256=logical, shape=dict(H=self.H, W=self.W),
            original_input_sha256=self.input.sha256,
            initial_output_sha256=self.initial_output.sha256))).hexdigest()

    def revalidate(self):
        _invocation_limits(self.limits)
        if not isinstance(self.manifest_path, Path) or _absolute(self.manifest_path) != self.manifest_path:
            raise ValueError('expected absolute invocation manifest Path')
        _identity(self.manifest_sha256, 'manifest_sha256')
        if type(self.source_bytes) is not bytes:
            raise ValueError('retained source must be exact immutable bytes')
        if type(self.manifest) is not InvocationManifest:
            raise ValueError('expected immutable InvocationManifest')
        self.manifest.__post_init__()
        for blob in (self.source, self.input, self.initial_output):
            if type(blob) is not VerifiedBlob:
                raise ValueError('expected VerifiedBlob')
            blob._validate_metadata()
            if blob.limits != self.limits.blobs:
                raise ValueError('verified blob limits differ from invocation limits')
        fresh = verify_invocation(self.manifest_path, limits=self.limits)
        if (fresh.manifest_sha256 != self.manifest_sha256 or fresh.manifest != self.manifest
                or fresh.source_bytes != self.source_bytes
                or fresh.source.reference != self.source.reference
                or fresh.input.reference != self.input.reference
                or fresh.initial_output.reference != self.initial_output.reference
                or fresh.source.chunks != self.source.chunks
                or fresh.input.chunks != self.input.chunks
                or fresh.initial_output.chunks != self.initial_output.chunks):
            raise ValueError('invocation changed since verification')
        self.source._cache.clear()
        self.input._cache.clear()
        self.initial_output._cache.clear()


def verify_invocation(manifest: Path, *, limits: InvocationLimits) -> VerifiedInvocation:
    _invocation_limits(limits)
    path = _absolute(manifest)
    record, digest = read_manifest(path, limits=limits.blobs)
    _keys(record, ('schema', 'source', 'source_sha256', 'family_semantics_sha256',
                   'specialization_semantics_sha256', 'source_profile', 'H', 'W',
                   'input', 'initial_output', 'buffer_contract', 'invocation_sha256'), 'invocation manifest')
    if record['schema'] != 'axiom-invocation-v2':
        raise ValueError('unsupported invocation schema')
    _keys(record['source_profile'], asdict(limits.source_profile), 'source profile')
    profile = SourceProfileV2(**record['source_profile'])
    if profile != limits.source_profile:
        raise ValueError('invocation source profile differs from selected profile')
    # Check shape/counts before opening any potentially large buffer streams.
    bound = InvocationManifest(
        source=_reference(record['source'], path.parent), source_sha256=record['source_sha256'],
        family_semantics_sha256=record['family_semantics_sha256'],
        specialization_semantics_sha256=record['specialization_semantics_sha256'],
        source_profile=profile, H=record['H'], W=record['W'],
        input=_reference(record['input'], path.parent), initial_output=_reference(record['initial_output'], path.parent),
        buffer_contract=record['buffer_contract'])
    if bound.source.byte_length > limits.source_limits.source_bytes:
        raise ValueError('source byte limit exceeded')
    source = verify_blob(bound.source, limits=limits.blobs)
    source_bytes = b''.join(source.iter_bytes())
    admitted = admit_source_v2(source_bytes, profile=profile, limits=limits.source_limits)
    if (bound.source_sha256, bound.family_semantics_sha256, bound.specialization_semantics_sha256,
            bound.H, bound.W) != (admitted.source_sha256, admitted.family_semantics_sha256,
                                 admitted.specialization_semantics_sha256, admitted.height, admitted.width):
        raise ValueError('source admission identities or dimensions differ')
    _identity(record['invocation_sha256'], 'invocation_sha256')
    if record['invocation_sha256'] != bound.invocation_sha256:
        raise ValueError('invocation identity differs')
    input_blob = verify_blob(bound.input, limits=limits.blobs)
    output_blob = verify_blob(bound.initial_output, limits=limits.blobs)
    return VerifiedInvocation(path, digest, bound, limits, source_bytes, source, input_blob, output_blob)


def write_invocation(source_bytes: bytes, input_blocks: Iterable[bytes], initial_output_blocks: Iterable[bytes],
                     directory: Path, *, limits: InvocationLimits) -> Path:
    """Admit exact source/extents before iterating either buffer; retain i32 bytes."""
    _invocation_limits(limits)
    admitted = admit_source_v2(source_bytes, profile=limits.source_profile, limits=limits.source_limits)
    directory = _absolute(directory)
    source = write_blob([admitted.source_bytes], len(admitted.source_bytes), directory/'source', limits=limits.blobs)
    input_blob = write_blob(input_blocks, 4*admitted.input_cells, directory/'input', limits=limits.blobs)
    output_blob = write_blob(initial_output_blocks, 4*admitted.output_cells, directory/'initial_output', limits=limits.blobs)
    bound = InvocationManifest(source, admitted.source_sha256, admitted.family_semantics_sha256,
                               admitted.specialization_semantics_sha256, admitted.profile,
                               admitted.height, admitted.width, input_blob, output_blob)
    record = dict(schema='axiom-invocation-v2', source=_reference_record(source, directory),
                  source_sha256=bound.source_sha256, family_semantics_sha256=bound.family_semantics_sha256,
                  specialization_semantics_sha256=bound.specialization_semantics_sha256,
                  source_profile=asdict(bound.source_profile), H=bound.H, W=bound.W,
                  input=_reference_record(input_blob, directory), initial_output=_reference_record(output_blob, directory),
                  buffer_contract=bound.buffer_contract, invocation_sha256=bound.invocation_sha256)
    raw = canonical_json(record)
    _decode_json(raw, limits.blobs)
    if len(raw) > limits.blobs.max_file_bytes:
        raise ValueError('manifest exceeds file bound')
    _write_immutable(directory, 'invocation.json', raw)
    return directory/'invocation.json'
