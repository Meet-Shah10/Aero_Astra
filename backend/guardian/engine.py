"""
AERO-ASTRA — GUARDIAN Rule Engine
====================================
Deterministic 5-step execution gate. No LLM, no API key, no randomness.

Rule order (first match wins):
    1. time_to_critical < 5 min          ? AUTONOMOUS_SAFED
    2. urgency in {HIGH, CRITICAL}        ? MANUAL_INTERLOCK
    3. recommended option is_irreversible ? MANUAL_INTERLOCK
    4. ALL_ACTIONS_UNSAFE flag OR
       safety_score < SAFETY_FLOOR (0.2)  ? MANUAL_INTERLOCK
    5. otherwise                           ? AUTOMATED_GUARDED

The ordering is critical — Rule 1 (genuine time pressure) overrides all
other reasoning. Rule 3 (irreversibility at low urgency) is the case most
likely to be missing from naive implementations; it is tested explicitly.

Safety floor rationale:
    safety_score = nominal_recovery_rate - mission_loss_rate, range [-1, +1].
    A floor of 0.2 means the action must recover at least 20 percentage
    points more often than it causes mission loss to qualify for automated
    execution. Below 0.2 the outcome is marginal; human judgement is required.
    (The ALL_ACTIONS_UNSAFE flag from ORACLE already covers scores = 0;
    the 0.2 floor also catches marginal-but-technically-positive scores.)
"""

from __future__ import annotations

from datetime import datetime, timezone

from backend.sherlock.schemas import SherlockDiagnosis, UrgencyLevel
from backend.athena.schemas import RecoveryPlan, RecoveryOption
from backend.oracle.schemas import OracleResponse
from backend.simulator.recovery import RECOVERY_CATALOG
from backend.guardian.schemas import DecisionTier, GuardianDecision


# -----------------------------------------------------------------------------
# Constants — declared here so tests and api.py can import and assert on them
# -----------------------------------------------------------------------------

#: Minutes-to-critical threshold below which Rule 1 fires unconditionally.
TIME_CRITICAL_THRESHOLD_MINUTES: int = 5

#: Minimum safety_score required for automated execution (Rule 4).
#: Formula: nominal_recovery_rate - mission_loss_rate, range [-1, +1].
SAFETY_SCORE_FLOOR: float = 0.2

#: The flag string ORACLE places in response_flags when all actions are unsafe.
ALL_ACTIONS_UNSAFE_FLAG: str = "ALL_ACTIONS_UNSAFE"

#: Safing action for Rule 1 — imported by key from the catalog, never hardcoded.
_SAFING_ACTION_NAME: str = RECOVERY_CATALOG["shed_nonessential_load"].name

#: High-urgency levels that trigger Rule 2.
_HIGH_URGENCY_LEVELS: frozenset[UrgencyLevel] = frozenset({
    UrgencyLevel.HIGH,
    UrgencyLevel.CRITICAL,
})


# -----------------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------------


def _lookup_safety_score(
    action_name: str,
    oracle_response: OracleResponse,
) -> float:
    """
    Return the safety_score for action_name from oracle_response.results.

    Returns the sentinel -999.0 if the action was not evaluated by ORACLE
    (expected for AUTONOMOUS_SAFED where shed_nonessential_load may not have
    been in the proposed actions list).
    """
    for result in oracle_response.results:
        if result.action_name == action_name:
            return result.safety_score
    return -999.0


def _recommended_option(recovery_plan: RecoveryPlan) -> RecoveryOption:
    """
    Return the RecoveryOption corresponding to recovery_plan.recommended_action.

    RecoveryPlan guarantees options[0].action_name == recommended_action
    (per athena/schemas.py docstring), so this is always a fast O(1) lookup.
    We do a linear search as a safety belt in case options are ever reordered.
    """
    for opt in recovery_plan.options:
        if opt.action_name == recovery_plan.recommended_action:
            return opt
    # Fallback to options[0] — should never happen given RecoveryPlan's invariant
    return recovery_plan.options[0]


# -----------------------------------------------------------------------------
# Public interface
# -----------------------------------------------------------------------------


def evaluate(
    diagnosis: SherlockDiagnosis,
    recovery_plan: RecoveryPlan,
    oracle_response: OracleResponse,
) -> GuardianDecision:
    """
    Run the 5-step GUARDIAN rule engine and return a GuardianDecision.

    Rules are evaluated in strict order; the first match wins. This function
    is pure — it has no side effects and makes no external calls.

    Args:
        diagnosis:      SherlockDiagnosis from SHERLOCK.
        recovery_plan:  RecoveryPlan from ATHENA.
        oracle_response: OracleResponse from ORACLE.

    Returns:
        GuardianDecision with tier, action, rationale, and audit fields.
    """
    ttc: int = diagnosis.time_to_critical_estimate_minutes
    urgency: UrgencyLevel = diagnosis.urgency
    rec_action: str = recovery_plan.recommended_action
    rec_option: RecoveryOption = _recommended_option(recovery_plan)
    now: datetime = datetime.now(tz=timezone.utc)

    # -- Rule 1: Time pressure overrides all other reasoning -------------------
    if ttc < TIME_CRITICAL_THRESHOLD_MINUTES:
        safing_score = _lookup_safety_score(_SAFING_ACTION_NAME, oracle_response)
        return GuardianDecision(
            tier=DecisionTier.AUTONOMOUS_SAFED,
            action_name=_SAFING_ACTION_NAME,
            auto_executes=True,
            requires_human_approval=False,
            rationale=(
                f"Rule 1 fired: time_to_critical={ttc} min is below the "
                f"{TIME_CRITICAL_THRESHOLD_MINUTES}-min emergency threshold; "
                f"executing {_SAFING_ACTION_NAME} immediately."
            ),
            notify_operator_post_hoc=True,
            time_to_critical_minutes=ttc,
            urgency=urgency.value,
            safety_score=safing_score,
            decided_at=now,
        )

    # -- Rule 2: High or critical urgency requires human interlock -------------
    if urgency in _HIGH_URGENCY_LEVELS:
        return GuardianDecision(
            tier=DecisionTier.MANUAL_INTERLOCK,
            action_name=rec_action,
            auto_executes=False,
            requires_human_approval=True,
            rationale=(
                f"Rule 2 fired: urgency={urgency.value} requires human approval "
                f"before executing {rec_action}."
            ),
            notify_operator_post_hoc=False,
            time_to_critical_minutes=ttc,
            urgency=urgency.value,
            safety_score=rec_option.safety_score,
            decided_at=now,
        )

    # -- Rule 3: Irreversible action always requires human approval -------------
    if rec_option.is_irreversible:
        return GuardianDecision(
            tier=DecisionTier.MANUAL_INTERLOCK,
            action_name=rec_action,
            auto_executes=False,
            requires_human_approval=True,
            rationale=(
                f"Rule 3 fired: {rec_action} is irreversible and requires human "
                f"approval regardless of urgency ({urgency.value})."
            ),
            notify_operator_post_hoc=False,
            time_to_critical_minutes=ttc,
            urgency=urgency.value,
            safety_score=rec_option.safety_score,
            decided_at=now,
        )

    # -- Rule 4: ORACLE flagged all actions unsafe, or score below safety floor -
    oracle_all_unsafe: bool = ALL_ACTIONS_UNSAFE_FLAG in oracle_response.response_flags
    score_too_low: bool = rec_option.safety_score < SAFETY_SCORE_FLOOR

    if oracle_all_unsafe or score_too_low:
        if oracle_all_unsafe:
            reason = (
                f"Rule 4a fired: ORACLE response_flags contains "
                f"'{ALL_ACTIONS_UNSAFE_FLAG}'; holding {rec_action} for human review."
            )
        else:
            reason = (
                f"Rule 4b fired: {rec_action} safety_score={rec_option.safety_score:.3f} "
                f"is below the automated-execution floor of {SAFETY_SCORE_FLOOR}; "
                f"holding for human review."
            )
        return GuardianDecision(
            tier=DecisionTier.MANUAL_INTERLOCK,
            action_name=rec_action,
            auto_executes=False,
            requires_human_approval=True,
            rationale=reason,
            notify_operator_post_hoc=False,
            time_to_critical_minutes=ttc,
            urgency=urgency.value,
            safety_score=rec_option.safety_score,
            decided_at=now,
        )

    # -- Rule 5: Routine — automated guarded execution -------------------------
    return GuardianDecision(
        tier=DecisionTier.AUTOMATED_GUARDED,
        action_name=rec_action,
        auto_executes=True,
        requires_human_approval=False,
        rationale=(
            f"Rule 5 fired: {rec_action} cleared all safety checks "
            f"(urgency={urgency.value}, reversible, score={rec_option.safety_score:.3f} "
            f">= {SAFETY_SCORE_FLOOR}); executing automatically."
        ),
        notify_operator_post_hoc=False,
        time_to_critical_minutes=ttc,
        urgency=urgency.value,
        safety_score=rec_option.safety_score,
        decided_at=now,
    )
