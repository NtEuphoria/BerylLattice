"""Explicit fixed-buffer v2 source admission, separate from v1 identities.

Admission always starts with retained source bytes. A caller-created AST is
never trusted. The shared frontend helpers validate a private alpha-renamed view
of the same scalar tree; the v1 admission function and hashes are untouched.
"""
from dataclasses import dataclass
import hashlib
import json

from .frontend import (
    _canonical_profile, _fail, _profile, _ungroup, _validate, parse_source,
)
from .model import (
    ConstraintDeclaration, DiagnosticError, IntegerLiteral, Objective, SourceModule,
)
from .source_names_v2 import _build_name_view, _original_name_diagnostic


@dataclass(frozen=True, slots=True)
class SourceProfileV2:
    """The single supported profile, including its fixed engineering envelope."""

    profile_id: str = 'axiom-stencil-fixed-buffer-v1'
    max_height: int = 8192
    max_width: int = 8192
    max_input_cells: int = 2**23
    index_semantics: str = 'checked-i32-row-major'
    version: int = 2

    def __post_init__(self):
        for name, expected in (
            ('max_height', 8192), ('max_width', 8192),
            ('max_input_cells', 2**23), ('version', 2),
        ):
            value = getattr(self, name)
            if type(value) is not int or value != expected:
                raise ValueError(f'{name} must be the exact supported integer {expected}')
        for name, expected in (
            ('profile_id', 'axiom-stencil-fixed-buffer-v1'),
            ('index_semantics', 'checked-i32-row-major'),
        ):
            value = getattr(self, name)
            if type(value) is not str or value != expected:
                raise ValueError(f'unsupported {name}')


@dataclass(frozen=True, slots=True)
class SourceLimitsV2:
    """Parser quotas may be tightened, never raised beyond the v2 bounds."""

    source_bytes: int = 65536
    expression_nodes: int = 100000
    version: int = 2

    def __post_init__(self):
        for name, maximum in (('source_bytes', 65536), ('expression_nodes', 100000)):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f'{name} must be an exact integer in 1..{maximum}')
        if type(self.version) is not int or self.version != 2:
            raise ValueError('unsupported source limits version')


def _digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False, allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _admit(source_bytes, profile, limits):
    if type(profile) is not SourceProfileV2 or type(limits) is not SourceLimitsV2:
        raise ValueError('expected SourceProfileV2 and SourceLimitsV2 records')
    # Revalidate public configuration even if passed through an unsafe serializer.
    profile.__post_init__()
    limits.__post_init__()
    module = parse_source(source_bytes, limits)
    # Necessary conditions for the existing exact profile, checked before
    # general constant/index validation. This intentionally changes diagnostic
    # precedence for already-rejected sources with conflicting errors.
    if (len(module.shapes), len(module.inputs), len(module.producers), len(module.outputs)) != (2, 1, 1, 1):
        _fail('UNSUPPORTED_PROFILE', module.span, 'requires exactly two shapes, one input, one producer and one output')
    if any(not isinstance(_ungroup(decl.value), IntegerLiteral) for decl in module.shapes):
        _fail('UNSUPPORTED_PROFILE', module.span, 'shape parameters must be literal declarations')
    if (len(module.inputs[0].dimensions) != 2
            or len(module.producers[0].axes) != 2 or len(module.outputs[0].axes) != 2):
        _fail('UNSUPPORTED_PROFILE', module.span, 'input and equations must have rank two')
    view = _build_name_view(module)
    try:
        shapes = _validate(view.module)
    except DiagnosticError as error:
        raise _original_name_diagnostic(error, view.original_names) from None
    for constraint in module.constraints:
        if constraint.property_name != 'plan_workspace_bytes':
            _fail('UNSUPPORTED_CONSTRAINT', constraint.span, 'unknown hard property')
        if type(constraint.value) is not int or not 0 <= constraint.value <= 2147483647:
            _fail('INVALID_CONSTRAINT', constraint.span, 'workspace cap must be a nonnegative i32 integer')
    try:
        objective = Objective(module.objective)
    except ValueError:
        _fail('UNSUPPORTED_OBJECTIVE', module.span, 'unknown objective')
    # Roles follow declaration order, never identifier spelling or sorting.
    height, width = (shapes[decl.name] for decl in view.module.shapes)
    if (not 1 <= height <= profile.max_height or not 1 <= width <= profile.max_width
            or (height+1)*(width+1) > profile.max_input_cells):
        _fail('UNSUPPORTED_PROFILE', module.span, 'source exceeds fixed-buffer dimension/cell envelope')
    try:
        normalized = _profile(view.module)
    except DiagnosticError as error:
        raise _original_name_diagnostic(error, view.original_names) from None
    if normalized != _canonical_profile():
        _fail('UNSUPPORTED_PROFILE', module.span, 'source is outside the exact canonical stencil profile')
    return module, height, width, objective, normalized


@dataclass(frozen=True, slots=True, init=False)
class AdmittedLoopKernel:
    """Immutable admission result derived only from a freshly parsed byte string.

    Its constructor deliberately accepts the same bytes/configuration boundary
    as admit_source_v2, rather than accepting asserted dimensions or AST records.
    """

    source_bytes: bytes
    source_digest: str
    source_module: SourceModule
    height: int
    width: int
    input_interval: tuple[int, int]
    source_constraints: tuple[ConstraintDeclaration, ...]
    cap: int | None
    objective: Objective
    family_digest: str
    specialization_digest: str
    constraint_digest: str
    objective_digest: str
    profile: SourceProfileV2
    version: int

    def __init__(self, source_bytes: bytes, *, profile: SourceProfileV2,
                 limits: SourceLimitsV2):
        module, height, width, objective, normalized = _admit(source_bytes, profile, limits)
        family_digest = _digest({
            'identity_version': 'axiom-loop-family-v2',
            'source_profile': {
                'profile_id': profile.profile_id,
                'version': profile.version,
                'max_height': profile.max_height,
                'max_width': profile.max_width,
                'max_input_cells': profile.max_input_cells,
                'index_semantics': profile.index_semantics,
            },
            'normalized_profile': normalized,
            'arithmetic': 'checked-i32-per-scalar-node-including-dead-operations',
            'boundary': 'row-major-preflight-first-invalid-preserve-input-and-original-output-before-scratch-or-body',
        })
        values = {
            'source_bytes': module.source_bytes,
            'source_digest': module.source_digest,
            'source_module': module,
            'height': height, 'width': width,
            'input_interval': module.inputs[0].input_interval,
            'source_constraints': module.constraints,
            'cap': module.cap, 'objective': objective,
            'family_digest': family_digest,
            'specialization_digest': _digest({
                'identity_version': 'axiom-loop-specialization-v2',
                'family_semantics_sha256': family_digest,
                'height': height, 'width': width,
                'dimensions': 'fixed-source-parameters-runtime-input-and-host-buffers',
            }),
            'constraint_digest': _digest({
                'identity_version': 'axiom-loop-source-constraints-v2',
                'plan_workspace_bytes': module.cap,
            }),
            'objective_digest': _digest({
                'identity_version': 'axiom-loop-source-objective-v2',
                'objective': objective.value,
            }),
            'profile': profile,
            'version': 2,
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)

    @property
    def input_cells(self) -> int:
        return (self.height+1)*(self.width+1)

    @property
    def output_cells(self) -> int:
        return self.height*self.width

    @property
    def source_sha256(self) -> str:
        return self.source_digest

    @property
    def family_semantics_sha256(self) -> str:
        return self.family_digest

    @property
    def specialization_semantics_sha256(self) -> str:
        return self.specialization_digest


def admit_source_v2(source_bytes: bytes, *, profile: SourceProfileV2,
                    limits: SourceLimitsV2) -> AdmittedLoopKernel:
    """Admit fresh exact bytes under the explicitly selected scalable profile.

    Admission establishes supported source structure and identities only. It
    neither checks a loop plan nor establishes execution or resource feasibility.
    """
    return AdmittedLoopKernel(source_bytes, profile=profile, limits=limits)
