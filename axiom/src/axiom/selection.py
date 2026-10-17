"""Deterministic selection over the three-generator portfolio.

Every candidate is independently checked. Checker work is deterministic; an
exception that supplies no work receipt conservatively consumes its entire call
allowance. Generation, encoding and source admission are outside that counter.
"""
from dataclasses import dataclass, fields, replace
from enum import StrEnum
from hashlib import sha256

from .checker import CHECK_ACCOUNTING_VERSION, CheckResult, check_plan
from .codec import canonical_json, encode_plan
from .frontend import admit_source, parse_source
from .model import AdmittedKernel, ConstraintStatus, Limits, Objective, SemanticStatus
from .plan_format import Plan
from .planner import PLAN_IDS, make_plan

BUDGET_ACCOUNTING_VERSION = CHECK_ACCOUNTING_VERSION
RANKING_VERSION = 1


class SearchStop(StrEnum):
    COMPLETED = 'completed'
    TOTAL_BUDGET_EXHAUSTED = 'total_budget_exhausted'
    OPTIONAL_BUDGET_EXHAUSTED = 'optional_budget_exhausted'
    CHECK_LIMIT_EXHAUSTED = 'check_limit_exhausted'
    INITIAL_INELIGIBLE = 'initial_ineligible'
    CHECKER_ERROR = 'checker_error'
    CANDIDATE_ERROR = 'candidate_error'
    CANCELLED = 'cancelled'


class ArtifactState(StrEnum):
    AVAILABLE = 'available'
    NONE = 'none'


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    candidate_id: str
    plan_digest: str | None
    check: CheckResult | None
    allowance: int
    work_used: int
    source_digest: str
    semantic_digest: str
    constraint_digest: str
    ranking_digest: str
    reason: str


@dataclass(frozen=True, slots=True)
class SearchResult:
    attempts: tuple[AttemptRecord, ...]
    termination_reason: SearchStop
    reason: str
    selected_plan: Plan | None
    selected_plan_bytes: bytes | None
    selected_check: CheckResult | None
    objective: Objective
    selected_key: tuple[int, int, str] | None
    budget_accounting_version: int
    total_check_steps: int
    total_work_used: int
    optional_check_steps: int | None
    optional_work_used: int
    artifact_state: ArtifactState
    limits: Limits


def ranking_digest(objective: Objective) -> str:
    """Identity of the versioned objective/secondary/stable-ID ranking policy."""
    if type(objective) is not Objective:
        raise ValueError('objective must be an Objective')
    secondary = (Objective.PLAN_WORKSPACE_BYTES if objective == Objective.MULTIPLICATION_OPS
                 else Objective.MULTIPLICATION_OPS)
    return sha256(canonical_json({'version': RANKING_VERSION,
                                 'primary': objective.value,
                                 'secondary': secondary.value,
                                 'tie_break': 'plan_id'})).hexdigest()


def _allowance(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(f'{name} must be a nonnegative exact integer')


def _key(check, plan, objective):
    muls, arena = check.multiplication_ops, check.workspace_bytes
    if type(muls) is not int or type(arena) is not int or min(muls, arena) < 0:
        raise ValueError('eligible checker receipt lacks exact complete metrics')
    if objective == Objective.MULTIPLICATION_OPS:
        return muls, arena, plan.plan_id
    return arena, muls, plan.plan_id


def select_plan(kernel: AdmittedKernel, limits: Limits, total_check_steps: int,
                objective: Objective, optional_check_steps: int | None = None) -> SearchResult:
    """Return only a fully eligible incumbent, with its exact checked bytes.

    Optional work starts after eligible inline admission, and also consumes the
    remaining total. Zero allowance never creates an invalid zero-valued Limits.
    Cancellation is best effort and is not a deterministic work-budget promise.
    """
    _allowance(total_check_steps, 'total_check_steps')
    if optional_check_steps is not None:
        _allowance(optional_check_steps, 'optional_check_steps')
    if type(kernel) is not AdmittedKernel or type(limits) is not Limits:
        raise ValueError('expected an AdmittedKernel and Limits')
    if type(objective) is not Objective or objective != kernel.objective:
        raise ValueError('objective must match the admitted request')
    # Frozen public records are not admission certificates. Re-admit before a
    # generator can observe forged dimensions or a weakened source constraint.
    fresh = admit_source(parse_source(kernel.source_module.source_bytes, limits))
    if (kernel != fresh or any(type(getattr(kernel, f.name)) is not type(getattr(fresh, f.name))
                               for f in fields(AdmittedKernel))):
        raise ValueError('kernel does not match its admitted source snapshot')
    kernel = fresh
    policy_digest = ranking_digest(objective)
    # Identify the requested context even when checking returns no receipt.
    constraint_digest = sha256(canonical_json({
        'version': 1, 'property': 'plan_workspace_bytes', 'source_cap': kernel.cap,
        'additional_cap': None, 'effective_cap': kernel.cap,
    })).hexdigest()
    attempts = []
    total_used = optional_used = 0
    incumbent = None

    def finish(stop, reason):
        plan, data, checked, key = incumbent if incumbent is not None else (None, None, None, None)
        return SearchResult(tuple(attempts), stop, reason, plan, data, checked,
                            objective, key, BUDGET_ACCOUNTING_VERSION,
                            total_check_steps, total_used, optional_check_steps,
                            optional_used, ArtifactState.AVAILABLE if incumbent else ArtifactState.NONE,
                            limits)

    for candidate_id in PLAN_IDS:
        is_optional = incumbent is not None
        total_remaining = total_check_steps - total_used
        if total_remaining == 0:
            return finish(SearchStop.TOTAL_BUDGET_EXHAUSTED, 'TOTAL_CHECK_STEPS_EXHAUSTED')
        available = min(total_remaining, limits.check_steps)
        if is_optional and optional_check_steps is not None:
            optional_remaining = optional_check_steps - optional_used
            if optional_remaining == 0:
                return finish(SearchStop.OPTIONAL_BUDGET_EXHAUSTED, 'OPTIONAL_CHECK_STEPS_EXHAUSTED')
            available = min(available, optional_remaining)
        checked = None
        charged = 0
        phase = 'generation'
        try:
            plan = make_plan(kernel, candidate_id)
            phase = 'checking'
            # If checking aborts without a receipt, retain this reservation.
            charged = available
            receipt = check_plan(kernel, plan, replace(limits, check_steps=available))
            if (type(receipt) is not CheckResult or type(receipt.work_used) is not int
                    or not 0 <= receipt.work_used <= available):
                raise ValueError('checker returned an invalid work receipt')
            checked = receipt
            charged = checked.work_used
            phase = 'encoding'
            if checked.eligible:
                data = encode_plan(plan, limits=limits)
                if (checked.source_digest != kernel.source_digest
                        or checked.plan_digest != sha256(data).hexdigest()
                        or checked.effective_cap != kernel.cap
                        or checked.constraint_digest != constraint_digest):
                    raise ValueError('checker receipt does not identify the selected artifact')
                key = _key(checked, plan, objective)
                candidate = (plan, data, checked, key)
            else:
                candidate = None
        except (Exception, KeyboardInterrupt) as error:
            total_used += charged
            if is_optional:
                optional_used += charged
            reason = 'CANCELLED' if isinstance(error, KeyboardInterrupt) else type(error).__name__ + ': ' + str(error)
            attempts.append(AttemptRecord(candidate_id, checked.plan_digest if checked else None,
                                          checked, available, charged, kernel.source_digest,
                                          kernel.semantic_digest, constraint_digest,
                                          policy_digest, reason))
            stop = (SearchStop.CANCELLED if isinstance(error, KeyboardInterrupt) else
                    SearchStop.CHECKER_ERROR if phase == 'checking' else SearchStop.CANDIDATE_ERROR)
            return finish(stop, reason)
        total_used += charged
        if is_optional:
            optional_used += charged
        attempts.append(AttemptRecord(candidate_id, checked.plan_digest, checked, available,
                                      charged, kernel.source_digest, kernel.semantic_digest,
                                      constraint_digest, policy_digest, checked.reason))
        if candidate is not None and (incumbent is None or key < incumbent[3]):
            # Commit the matching artifact as one tuple; later work cannot edit it.
            incumbent = candidate
        if not is_optional and incumbent is None:
            reason = ('CONSTRAINT_VIOLATED' if checked.constraint_status == ConstraintStatus.VIOLATED
                      and checked.semantic_status == SemanticStatus.VALID else checked.reason)
            return finish(SearchStop.INITIAL_INELIGIBLE, reason)
        if checked.reason == 'CHECK_STEPS_EXHAUSTED':
            if total_used == total_check_steps:
                return finish(SearchStop.TOTAL_BUDGET_EXHAUSTED, checked.reason)
            if optional_check_steps is not None and optional_used == optional_check_steps:
                return finish(SearchStop.OPTIONAL_BUDGET_EXHAUSTED, checked.reason)
            return finish(SearchStop.CHECK_LIMIT_EXHAUSTED, checked.reason)
    return finish(SearchStop.COMPLETED, 'PORTFOLIO_EXAMINED')
