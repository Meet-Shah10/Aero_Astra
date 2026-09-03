"""
AERO-ASTRA — ORACLE Schemas
============================
Pydantic data contracts for ORACLE's request and response.

Design notes:
- SatelliteState and MonteCarloResult are imported from the simulator module
  directly and never redefined here. ORACLE is downstream infrastructure; it
  does not reimplement the simulator's data types.
- diagnosis_context is accepted as a plain str (not a SHERLOCK schema import)
  so that ORACLE has no direct dependency on backend.sherlock. The audit trail
  is preserved without coupling the modules.
- generated_at is a raw Unix float timestamp (time.time()). Note: SHERLOCK uses
  a datetime object for its equivalent field. This mismatch is intentional here
  for simplicity — SCRIBE will need to normalize both representations when
  assembling the audit trail.
"""

from __future__ import annotations

import time
import uuid
from typing import Literal

from pydantic import BaseModel, Field

from backend.simulator.schemas import MonteCarloResult, SatelliteState


# ─────────────────────────────────────────────────────────────────────────────
# Request schema
# ─────────────────────────────────────────────────────────────────────────────


class OracleRequest(BaseModel):
    """
    Input to ORACLE's validation or ranking functions.

    If proposed_actions is None or omitted, ORACLE enters fallback ranking mode:
    it tests every action in the simulator's RECOVERY_CATALOG and returns a
    ranked list. This mode exists so the full demo pipeline works before
    ATHENA is built. Once ATHENA is online, it will supply proposed_actions
    with one or more specific candidates.
    """

    current_state: SatelliteState = Field(
        ...,
        description=(
            "The satellite's current state snapshot. Typically the most recent "
            "telemetry, or a degraded state produced by the simulator for testing."
        ),
    )
    fault_name: str | None = Field(
        default=None,
        description=(
            "Name of the active fault as diagnosed by SHERLOCK. Passed through "
            "to run_monte_carlo so the simulator continues evolving the fault "
            "forward during each MC run. None means no active fault."
        ),
    )
    fault_severity: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Severity of the active fault, in [0, 1]. Ignored if fault_name is None.",
    )
    proposed_actions: list[str] | None = Field(
        default=None,
        description=(
            "Specific recovery action names to validate. If None, ORACLE falls "
            "back to testing all actions in the simulator's RECOVERY_CATALOG."
        ),
    )
    diagnosis_context: str | None = Field(
        default=None,
        description=(
            "Free-text summary of SHERLOCK's diagnosis, included verbatim in the "
            "response for audit trail purposes. ORACLE does not parse or act on it."
        ),
    )
    n_runs: int = Field(
        default=100,
        ge=1,
        le=10_000,
        description="Number of independent Monte Carlo runs per action.",
    )
    steps: int = Field(
        default=300,
        ge=1,
        le=100_000,
        description="Simulation steps per run (each step = dt seconds, default dt=10s).",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Per-action result
# ─────────────────────────────────────────────────────────────────────────────


class ActionResult(BaseModel):
    """
    ORACLE's validated result for a single recovery action.

    mc_result is the raw MonteCarloResult from the simulator — imported directly,
    not redefined. safety_score and flags are ORACLE's own additions.
    """

    action_name: str = Field(..., description="Recovery action name from RECOVERY_CATALOG.")
    mc_result: MonteCarloResult = Field(
        ...,
        description="Raw Monte Carlo output from the simulator for this action.",
    )
    safety_score: float = Field(
        ...,
        description=(
            "ORACLE's computed safety score for this action. "
            "Formula: nominal_recovery_rate - mission_loss_rate. Range [-1, +1]. "
            "Higher is safer. Isolated in scoring.py for ATHENA to replace later."
        ),
    )
    flags: list[str] = Field(
        default_factory=list,
        description=(
            "Warning flags raised by ORACLE's flagging rules. Examples: "
            "'HIGH_MISSION_LOSS_RATE', 'LOW_NOMINAL_RECOVERY_RATE', 'HIGH_SOC_VARIANCE'."
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Top-level response
# ─────────────────────────────────────────────────────────────────────────────


class OracleResponse(BaseModel):
    """
    ORACLE's full output for a validation or ranking request.

    results is always sorted by safety_score descending (ties broken by lower
    mission_loss_rate, then higher nominal_recovery_rate).

    best_action is always set to results[0].action_name — even when all scores
    are negative. The "least bad" action is still meaningful information.
    GUARDIAN receives both best_action and response_flags and decides the policy.
    When all actions score ≤ 0, response_flags will include 'ALL_ACTIONS_UNSAFE'.
    """

    request_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="UUID4 identifier for this request, for audit trail linkage.",
    )
    fault_name: str | None = Field(
        default=None,
        description="Active fault name echoed from the request.",
    )
    diagnosis_context: str | None = Field(
        default=None,
        description="SHERLOCK diagnosis context echoed from the request.",
    )
    mode: Literal["single_action", "ranking"] = Field(
        ...,
        description=(
            "'single_action' when specific actions were requested (ATHENA path). "
            "'ranking' when all catalog actions were tested (fallback path)."
        ),
    )
    results: list[ActionResult] = Field(
        ...,
        description="Per-action results, sorted by safety_score descending.",
    )
    best_action: str | None = Field(
        default=None,
        description=(
            "Action name with the highest safety_score. Set even when the score "
            "is negative (least-bad option). None only if results is empty."
        ),
    )
    response_flags: list[str] = Field(
        default_factory=list,
        description=(
            "Top-level flags for this response. 'ALL_ACTIONS_UNSAFE' is added "
            "when every action's safety_score is ≤ 0."
        ),
    )
    generated_at: float = Field(
        default_factory=time.time,
        description=(
            "Unix timestamp (seconds since epoch) when this response was generated. "
            "Note: SHERLOCK uses datetime objects for equivalent fields — SCRIBE "
            "must normalize both representations in the audit trail."
        ),
    )
