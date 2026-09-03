"""
AERO-ASTRA — ORACLE Agent Logic
=================================
Core validation and ranking functions.

Public interface:
    run_oracle(request)          — main entry point; dispatches to validate or rank
    validate_action(request)     — ATHENA path: validate specific proposed action(s)
    rank_all_actions(request)    — fallback path: test all catalog actions, rank them

No LLM calls, no API keys. All work is delegated to the simulator's
run_monte_carlo() function. ORACLE adds safety scoring, flagging, and
structured response packaging on top.

Import boundaries:
    - Imports from backend.simulator: run_monte_carlo, RECOVERY_CATALOG, schemas
    - Does NOT import from backend.sherlock or backend.sentinel
    - Diagnosis context from SHERLOCK is accepted as a plain str in OracleRequest
"""

from __future__ import annotations

from backend.simulator import run_monte_carlo
from backend.simulator.recovery import RECOVERY_CATALOG

from .schemas import ActionResult, OracleRequest, OracleResponse
from .scoring import (
    SAFE_SCORE_THRESHOLD,
    compute_flags,
    compute_safety_score,
    ranking_sort_key,
)


# ─────────────────────────────────────────────────────────────────────────────
# Internal: run MC for one action and package into ActionResult
# ─────────────────────────────────────────────────────────────────────────────


def _evaluate_action(action_name: str, request: OracleRequest) -> ActionResult:
    """
    Run Monte Carlo for one action and return a scored, flagged ActionResult.

    Args:
        action_name: Key from RECOVERY_CATALOG.
        request:     The originating OracleRequest (provides state, fault, params).

    Returns:
        ActionResult with mc_result, safety_score, and flags populated.

    Raises:
        ValueError: If action_name is not in RECOVERY_CATALOG (propagated from
                    run_monte_carlo).
    """
    mc_result = run_monte_carlo(
        current_state=request.current_state,
        proposed_action=action_name,
        n_runs=request.n_runs,
        steps=request.steps,
        fault=request.fault_name,
        fault_severity=request.fault_severity,
    )

    score = compute_safety_score(mc_result)
    flags = compute_flags(mc_result)

    return ActionResult(
        action_name=action_name,
        mc_result=mc_result,
        safety_score=score,
        flags=flags,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Internal: assemble OracleResponse from a list of ActionResults
# ─────────────────────────────────────────────────────────────────────────────


def _build_response(
    results: list[ActionResult],
    mode: str,
    request: OracleRequest,
) -> OracleResponse:
    """
    Sort results, determine best_action, and assemble the OracleResponse.

    Sorting is deterministic: primary by safety_score descending, secondary by
    mission_loss_rate ascending, tertiary by nominal_recovery_rate descending.
    See scoring.ranking_sort_key for the full tiebreak logic.

    best_action is always set to results[0].action_name even when all scores
    are negative. The ALL_ACTIONS_UNSAFE flag is added to response_flags in
    that case — GUARDIAN decides the policy, not ORACLE.

    Args:
        results: List of ActionResult objects (unsorted).
        mode:    "single_action" or "ranking".
        request: Original OracleRequest for context fields.

    Returns:
        Fully populated OracleResponse.
    """
    sorted_results = sorted(results, key=ranking_sort_key)

    best_action: str | None = None
    response_flags: list[str] = []

    if sorted_results:
        best_action = sorted_results[0].action_name
        if all(r.safety_score <= SAFE_SCORE_THRESHOLD for r in sorted_results):
            response_flags.append("ALL_ACTIONS_UNSAFE")

    return OracleResponse(
        fault_name=request.fault_name,
        diagnosis_context=request.diagnosis_context,
        mode=mode,  # type: ignore[arg-type]
        results=sorted_results,
        best_action=best_action,
        response_flags=response_flags,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public: validate specific proposed action(s) — ATHENA path
# ─────────────────────────────────────────────────────────────────────────────


def validate_action(request: OracleRequest) -> OracleResponse:
    """
    Validate one or more specific proposed recovery actions.

    This is the primary path once ATHENA is built: ATHENA proposes candidate
    action(s), ORACLE validates each against the simulator, and returns
    outcome probabilities + safety scores for GUARDIAN to gate on.

    Args:
        request: OracleRequest with proposed_actions set to a non-empty list.

    Returns:
        OracleResponse with mode='single_action', results sorted by score,
        and best_action set to the highest-scoring action.

    Raises:
        ValueError: If proposed_actions is None or empty (use rank_all_actions
                    for the fallback ranking mode).
        ValueError: If any action name is not in RECOVERY_CATALOG.
    """
    if not request.proposed_actions:
        raise ValueError(
            "validate_action requires a non-empty proposed_actions list. "
            "Call rank_all_actions instead for fallback ranking mode."
        )

    results = [_evaluate_action(name, request) for name in request.proposed_actions]
    return _build_response(results, mode="single_action", request=request)


# ─────────────────────────────────────────────────────────────────────────────
# Public: test all catalog actions and rank them — no-ATHENA fallback
# ─────────────────────────────────────────────────────────────────────────────


def rank_all_actions(request: OracleRequest) -> OracleResponse:
    """
    Test every action in the simulator's RECOVERY_CATALOG and rank by safety score.

    This is the fallback path for when ATHENA has not yet been built (or is
    unavailable). It produces a complete ranked menu of validated options so
    that the full demo pipeline (diagnosis → validated options → GUARDIAN gate)
    works end-to-end without ATHENA.

    Once ATHENA is online, it will call validate_action with its own candidate
    list instead of relying on this full-catalog sweep.

    Args:
        request: OracleRequest. proposed_actions is ignored (all catalog actions
                 are tested regardless).

    Returns:
        OracleResponse with mode='ranking', all 6 catalog actions ranked by
        safety_score, and best_action set to the top-ranked action.

    Raises:
        ValueError: Propagated from run_monte_carlo if the catalog is inconsistent
                    (should never happen unless recovery.py is manually edited).
    """
    results = [
        _evaluate_action(action_name, request)
        for action_name in RECOVERY_CATALOG
    ]
    return _build_response(results, mode="ranking", request=request)


# ─────────────────────────────────────────────────────────────────────────────
# Public: main dispatcher
# ─────────────────────────────────────────────────────────────────────────────


def run_oracle(request: OracleRequest) -> OracleResponse:
    """
    Main ORACLE entry point. Dispatches to validate_action or rank_all_actions.

    If request.proposed_actions is None or empty, enters ranking fallback mode
    (tests all catalog actions). Otherwise validates the specified actions.

    Args:
        request: OracleRequest describing the satellite state, fault, and
                 optionally specific actions to test.

    Returns:
        OracleResponse with ranked/validated results and best_action.
    """
    if request.proposed_actions:
        return validate_action(request)
    return rank_all_actions(request)
