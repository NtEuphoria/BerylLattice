"""Rank the complete validated portfolio, then prove its first eligible member.

This is a separate policy from public legacy selection. An unknown never grants
an incumbent or an optimality claim. Structural costs describe actual complete
streams; neither labels nor generator formulas establish costs or eligibility.
"""
from dataclasses import dataclass, replace
from enum import StrEnum
from hashlib import sha256

from .checker import CHECKER_VERSION, CheckResult
from .codec import DecodeError, canonical_json
from .compilation import _CompilationContext
from .model import ConstraintStatus, Limits, Objective, SemanticStatus
from .plan_format import Plan
from .planner import PLAN_IDS, bounded, make_plan, plan_ids
from .selection import ArtifactState, BUDGET_ACCOUNTING_VERSION, _allowance, ranking_digest

POLICY_ID = 'ranked-proof-v1'
REPORT_VERSION = 2


class AttemptState(StrEnum):
    STRUCTURALLY_REJECTED = 'structurally_rejected'
    CONSTRAINT_REJECTED = 'constraint_rejected'
    PROVED_INVALID = 'proved_invalid'
    PROVED_ELIGIBLE = 'proved_eligible'
    NOT_CHECKED_WORSE_RANK = 'not_checked_worse_rank'
    NOT_CHECKED = 'not_checked'
    UNKNOWN = 'unknown'


class FastSearchStop(StrEnum):
    COMPLETED = 'completed'
    NO_ELIGIBLE_CANDIDATE = 'no_eligible_candidate'
    TOTAL_BUDGET_EXHAUSTED = 'total_budget_exhausted'
    CHECK_LIMIT_EXHAUSTED = 'check_limit_exhausted'
    UNKNOWN = 'unknown'
    CHECKER_ERROR = 'checker_error'
    CANDIDATE_ERROR = 'candidate_error'
    CANCELLED = 'cancelled'


@dataclass(frozen=True, slots=True)
class FastAttemptRecord:
    candidate_id: str
    state: AttemptState
    multiplication_ops: int | None
    workspace_bytes: int | None
    operation_count: int | None
    ranking_key: tuple[int, int, str] | None
    plan_digest: str | None
    check: CheckResult | None
    allowance: int
    work_used: int
    source_digest: str
    semantic_digest: str
    constraint_digest: str
    ranking_digest: str
    policy_digest: str
    reason: str


@dataclass(frozen=True, slots=True)
class FastSearchResult:
    attempts: tuple[FastAttemptRecord, ...]
    termination_reason: FastSearchStop
    reason: str
    selected_plan: Plan | None
    selected_plan_bytes: bytes | None
    selected_check: CheckResult | None
    objective: Objective
    selected_key: tuple[int, int, str] | None
    budget_accounting_version: int
    total_check_steps: int
    total_work_used: int
    artifact_state: ArtifactState
    limits: Limits
    report_version: int
    policy_id: str
    policy_digest: str
    portfolio_optimal: bool


def ranked_policy_digest(objective: Objective, portfolio: tuple[str, ...] = PLAN_IDS) -> str:
    """Bind the ranked policy separately from unchanged tuple-ranking identity."""
    return sha256(canonical_json({
        'policy': POLICY_ID, 'report_version': REPORT_VERSION,
        'ranking_digest': ranking_digest(objective), 'portfolio': list(portfolio),
        'identical_key_tie_break': 'portfolio_order',
        'structural_metrics': ['multiplication_ops', 'workspace_bytes', 'operation_count'],
        'unknown': 'stop_without_artifact', 'generation': 'complete_before_proof',
        'budget_accounting_version': BUDGET_ACCOUNTING_VERSION,
        'budget': 'shared_total_bounded_per_call',
        'exception_without_receipt': 'charge_call_allowance',
    })).hexdigest()


def _receipt_identity(checked, candidate, context, constraint_digest):
    """Check context binding before interpreting any semantic status."""
    if (type(checked.semantic_status) is not SemanticStatus
            or type(checked.constraint_status) is not ConstraintStatus
            or type(checked.check_complete) is not bool
            or checked.source_digest != context.kernel.source_digest
            or checked.plan_digest != candidate.plan_digest
            or checked.checker_version != CHECKER_VERSION
            or type(checked.effective_cap) is not type(context.kernel.cap)
            or checked.effective_cap != context.kernel.cap
            or checked.constraint_digest != constraint_digest):
        raise ValueError('checker receipt does not identify this compilation')


def _eligible_metrics(checked, candidate):
    """A complete proof must agree with the metrics used to order its stream."""
    counts = checked.opcode_counts
    if (type(checked.multiplication_ops) is not int
            or type(checked.workspace_bytes) is not int
            or checked.multiplication_ops != candidate.multiplication_ops
            or checked.workspace_bytes != candidate.workspace_bytes
            or type(counts) is not tuple
            or any(type(pair) is not tuple or len(pair) != 2
                   or type(pair[0]) is not str or type(pair[1]) is not int or pair[1] <= 0
                   for pair in counts)
            or len(dict(counts)) != len(counts)
            or sum(count for _, count in counts) != len(candidate.plan.operations)
            or dict(counts).get('mul', 0) != candidate.multiplication_ops):
        raise ValueError('eligible receipt disagrees with complete structural metrics')


def _select_ranked(context, total_check_steps):
    """Return a version-2 report and optional transaction-owned successful check.

    Attempts retain portfolio order. ``not_checked`` means no semantic claim;
    only success turns later feasible attempts into ``not_checked_worse_rank``.
    ``portfolio_optimal`` means the returned eligible plan minimizes the exact
    existing tuple over this fully examined fixed portfolio, with stable ties.
    It is false without an artifact, including conclusive empty portfolios.
    """
    _allowance(total_check_steps, 'total_check_steps')
    if type(context) is not _CompilationContext:
        raise ValueError('expected an owned compilation context')
    context._live()
    kernel = context.kernel
    objective = kernel.objective
    policy = ranked_policy_digest(objective, plan_ids(kernel))
    ranking = ranking_digest(objective)
    constraint = sha256(canonical_json({
        'version': 1, 'property': 'plan_workspace_bytes', 'source_cap': kernel.cap,
        'additional_cap': None, 'effective_cap': kernel.cap,
    })).hexdigest()
    attempts = []
    candidates = []
    total_used = 0

    def finish(stop, reason, owned=None):
        result = FastSearchResult(
            tuple(attempts), stop, reason,
            None if owned is None else owned.plan,
            None if owned is None else owned.plan_bytes,
            None if owned is None else owned.checked,
            objective, None if owned is None else next(
                a.ranking_key for a in attempts if a.state == AttemptState.PROVED_ELIGIBLE),
            BUDGET_ACCOUNTING_VERSION, total_check_steps, total_used,
            ArtifactState.NONE if owned is None else ArtifactState.AVAILABLE,
            context.limits, REPORT_VERSION, POLICY_ID, policy, owned is not None)
        return result, owned

    def fail(index, error, stage, checked=None, allowance=0, charged=0):
        nonlocal total_used
        total_used += charged
        reason = 'CANCELLED' if isinstance(error, KeyboardInterrupt) else str(error)
        if isinstance(error, KeyboardInterrupt):
            stop = FastSearchStop.CANCELLED
        elif isinstance(error, DecodeError):
            stop = FastSearchStop.UNKNOWN
            reason = error.code
        else:
            stop = FastSearchStop.CHECKER_ERROR if stage == 'checking' else FastSearchStop.CANDIDATE_ERROR
            reason = type(error).__name__ + ': ' + reason
        attempts[index] = replace(attempts[index], state=AttemptState.UNKNOWN,
                                  check=checked, allowance=allowance, work_used=charged, reason=reason)
        return finish(stop, reason)

    # No proof can establish the fixed portfolio's optimum until every generator
    # has completed and every actual stream has been structurally examined.
    for candidate_id in plan_ids(kernel):
        index = len(attempts)
        attempts.append(FastAttemptRecord(
            candidate_id, AttemptState.NOT_CHECKED, None, None, None, None, None,
            None, 0, 0, kernel.source_digest, kernel.semantic_digest,
            constraint, ranking, policy, 'NOT_CHECKED'))
        stage = 'generation'
        try:
            with context.phase('candidate_generation'):
                plan = make_plan(kernel, candidate_id, **bounded(kernel, context.limits))
                context.count('candidates_generated')
            stage = 'validation'
            candidate = context.candidate(plan)
            muls, workspace = candidate.multiplication_ops, candidate.workspace_bytes
            key = ((muls, workspace, plan.plan_id) if objective == Objective.MULTIPLICATION_OPS
                   else (workspace, muls, plan.plan_id))
            rejected = kernel.cap is not None and workspace > kernel.cap
            attempts[index] = replace(
                attempts[index], multiplication_ops=muls, workspace_bytes=workspace,
                operation_count=len(plan.operations), ranking_key=key,
                state=AttemptState.CONSTRAINT_REJECTED if rejected else AttemptState.NOT_CHECKED,
                reason='CONSTRAINT_VIOLATED' if rejected else 'NOT_CHECKED')
            if not rejected:
                candidates.append((key, index, candidate))
        except (Exception, KeyboardInterrupt) as error:
            # Only a known conclusive malformed-record diagnostic is discardable.
            # Unknown opcodes, new versions and all resource limits stop the policy.
            if stage == 'validation' and isinstance(error, DecodeError) and error.code == 'INVALID_PLAN':
                attempts[index] = replace(attempts[index], state=AttemptState.STRUCTURALLY_REJECTED,
                                          reason=error.code)
                continue
            return fail(index, error, stage)

    # Python's stable sort preserves original portfolio order for identical keys.
    candidates.sort(key=lambda item: item[0])
    for _, index, candidate in candidates:
        available = min(total_check_steps - total_used, context.limits.check_steps)
        if available == 0:
            return finish(FastSearchStop.TOTAL_BUDGET_EXHAUSTED, 'TOTAL_CHECK_STEPS_EXHAUSTED')
        checked = None
        allowance = charged = 0
        stage = 'encoding'
        try:
            # Encoding is lazy and outside conceptual semantic work. In
            # particular its failure does not consume a checker reservation.
            attempts[index] = replace(attempts[index], plan_digest=candidate.plan_digest)
            stage = 'checking'
            allowance = charged = available
            receipt = context.check(candidate, available)
            if (type(receipt) is not CheckResult or type(receipt.work_used) is not int
                    or not 0 <= receipt.work_used <= available):
                raise ValueError('checker returned an invalid work receipt')
            checked = receipt
            charged = checked.work_used
            _receipt_identity(checked, candidate, context, constraint)
            attempts[index] = replace(attempts[index], check=checked,
                                      allowance=allowance, work_used=charged, reason=checked.reason)
            if checked.semantic_status == SemanticStatus.UNKNOWN or checked.constraint_status == ConstraintStatus.UNKNOWN:
                total_used += charged
                attempts[index] = replace(attempts[index], state=AttemptState.UNKNOWN)
                stop = FastSearchStop.UNKNOWN
                if checked.reason == 'CHECK_STEPS_EXHAUSTED':
                    stop = (FastSearchStop.TOTAL_BUDGET_EXHAUSTED if total_used == total_check_steps
                            else FastSearchStop.CHECK_LIMIT_EXHAUSTED)
                return finish(stop, checked.reason)
            if checked.semantic_status == SemanticStatus.INVALID:
                total_used += charged
                attempts[index] = replace(attempts[index], state=AttemptState.PROVED_INVALID)
                continue
            if not checked.eligible:
                raise ValueError('checker receipt contradicts structural cap eligibility')
            _eligible_metrics(checked, candidate)
            owned = context.authorize(candidate, checked)
        except (Exception, KeyboardInterrupt) as error:
            return fail(index, error, stage, checked, allowance, charged)
        total_used += charged
        attempts[index] = replace(attempts[index], state=AttemptState.PROVED_ELIGIBLE)
        for other_index, attempt in enumerate(attempts):
            if attempt.state == AttemptState.NOT_CHECKED:
                attempts[other_index] = replace(attempt, state=AttemptState.NOT_CHECKED_WORSE_RANK,
                                                reason='NOT_CHECKED_WORSE_RANK')
        return finish(FastSearchStop.COMPLETED, 'PORTFOLIO_OPTIMUM_PROVED', owned)
    return finish(FastSearchStop.NO_ELIGIBLE_CANDIDATE, 'NO_ELIGIBLE_CANDIDATE')
