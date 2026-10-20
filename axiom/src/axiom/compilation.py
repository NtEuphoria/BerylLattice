"""Private, transaction-owned admission, candidates and successful checks.

Public bytes APIs still admit afresh. These records are an internal ownership
protocol, not a security boundary against code executing inside this process.
No digest or caller-created receipt can install an executable artifact.
"""
from contextlib import nullcontext
from dataclasses import dataclass, fields, replace
from hashlib import sha256

from .checker import CheckResult, _check_admitted_plan
from .codec import DecodeError, _validate_plan, _encode_validated_plan
from .frontend import admit_source, parse_source
from .model import Limits


@dataclass(frozen=True, slots=True, eq=False)
class _Candidate:
    owner: object
    plan: object
    multiplication_ops: int
    workspace_bytes: int

    @property
    def plan_bytes(self):
        return self.owner._encoding(self)[0]

    @property
    def plan_digest(self):
        return self.owner._encoding(self)[1]


@dataclass(frozen=True, slots=True, eq=False)
class _OwnedCheck:
    owner: object
    candidate: _Candidate
    source: bytes
    kernel: object
    plan: object
    plan_bytes: bytes
    checked: CheckResult
    limits: Limits


class _CompilationContext:
    """One fresh source snapshot; all retained authority expires on close()."""
    __slots__ = ('_source', '_limits', '_kernel', 'trace', '_candidates', '_checks',
                 '_artifacts', '_encodings', '_closed')

    def __init__(self, source: bytes, limits: Limits = Limits(), *, trace=None):
        if type(source) is not bytes or type(limits) is not Limits:
            raise ValueError('compilation requires immutable source bytes and Limits')
        # Reconstruct exact limits: even frozen public records can be forged.
        self._limits = Limits(**{field.name: getattr(limits, field.name) for field in fields(Limits)})
        self._source = source
        self.trace = trace
        self._candidates = {}
        self._encodings = {}
        self._checks = {}
        self._artifacts = {}
        self._closed = False
        with self.phase('source_admission'):
            self._kernel = admit_source(parse_source(source, self._limits))
            self.count('source_admissions')

    @property
    def source(self):
        return self._source

    @property
    def kernel(self):
        return self._kernel

    @property
    def limits(self):
        return self._limits

    def phase(self, name):
        return nullcontext() if self.trace is None else self.trace.phase(name)

    def count(self, name, amount=1):
        if self.trace is not None:
            self.trace.count(name, amount)

    def _live(self):
        if self._closed:
            raise ValueError('compilation context is closed')

    def close(self):
        self._closed = True
        self._candidates.clear()
        self._encodings.clear()
        self._checks.clear()
        self._artifacts.clear()

    def candidate(self, plan):
        self._live()
        existing = self._candidates.get(id(plan))
        if existing is not None and existing.plan is plan:
            return existing
        with self.phase('structural_validation'):
            multiplication_ops, workspace_bytes = _validate_plan(plan, self.limits)
            self.count('plan_validations')
        candidate = _Candidate(self, plan, multiplication_ops, workspace_bytes)
        self._candidates[id(plan)] = candidate
        return candidate

    def _encoding(self, candidate):
        self._require_candidate(candidate)
        encoded = self._encodings.get(id(candidate))
        if encoded is None:
            with self.phase('canonical_encoding'):
                data = _encode_validated_plan(candidate.plan, self.limits)
                encoded = (data, sha256(data).hexdigest())
                self.count('plan_encodes')
            self._encodings[id(candidate)] = encoded
        return encoded

    def _require_candidate(self, candidate):
        self._live()
        if (type(candidate) is not _Candidate or candidate.owner is not self
                or self._candidates.get(id(candidate.plan)) is not candidate):
            raise ValueError('candidate does not belong to this compilation')

    def check(self, candidate, allowance=None, *, additional_cap=None):
        self._require_candidate(candidate)
        if allowance is None:
            allowance = self.limits.check_steps
        if type(allowance) is not int or not 0 < allowance <= self.limits.check_steps:
            raise ValueError('check allowance must fit the compilation limits')
        limits = replace(self.limits, check_steps=allowance)
        identity = candidate.plan_digest
        with self.phase('semantic_checking'):
            checked = _check_admitted_plan(self.kernel, candidate.plan, limits,
                                           identity, additional_cap=additional_cap)
            self.count('semantic_checks')
            self.count('semantic_work', checked.work_used)
        self._checks[id(checked)] = (candidate, checked, limits)
        return checked

    def authorize(self, candidate, checked):
        self._require_candidate(candidate)
        owned_check = self._checks.get(id(checked))
        if (owned_check is None or owned_check[0] is not candidate
                or owned_check[1] is not checked or not checked.eligible):
            raise ValueError('successful check is not owned by this compilation')
        artifact = _OwnedCheck(self, candidate, self.source, self.kernel, candidate.plan,
                               candidate.plan_bytes, checked, owned_check[2])
        self._artifacts[id(artifact)] = artifact
        return artifact


def _require_owned(owned):
    if type(owned) is not _OwnedCheck or type(owned.owner) is not _CompilationContext:
        raise ValueError('expected an owned successful compilation check')
    owner = owned.owner
    owner._live()
    if owner._artifacts.get(id(owned)) is not owned:
        raise ValueError('successful compilation check was not issued by its owner')
    return owned


def _select_legacy(context, total_check_steps, optional_check_steps=None):
    """Use exactly the public legacy algorithm with owned checker/codec handoff."""
    from .selection import _select_portfolio
    context._live()

    def check_candidate(kernel, plan, limits):
        try:
            candidate = context.candidate(plan)
        except DecodeError as error:
            # Preserve the legacy structural diagnostic receipt and cutpoint.
            # Invalid candidates never acquire ownership or emission authority.
            return _check_admitted_plan(kernel, plan, limits, None, validation_error=error)
        return context.check(candidate, limits.check_steps)

    def encode_candidate(plan, *, limits):
        return context.candidate(plan).plan_bytes

    def generate_candidate(kernel, candidate_id):
        from .planner import bounded, make_plan
        with context.phase('candidate_generation'):
            plan = make_plan(kernel, candidate_id, **bounded(kernel, context.limits))
            context.count('candidates_generated')
            return plan

    with context.phase('selection'):
        search = _select_portfolio(context.kernel, context.limits, total_check_steps,
                                   context.kernel.objective, optional_check_steps,
                                   check_candidate=check_candidate, encode_candidate=encode_candidate,
                                   generate_candidate=generate_candidate)
    owned = (None if search.selected_plan is None else
             context.authorize(context.candidate(search.selected_plan), search.selected_check))
    return search, owned
