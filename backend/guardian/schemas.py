"""
AERO-ASTRA — GUARDIAN Schemas
==============================
Data contracts for GUARDIAN's input and output.

Design notes:
- SherlockDiagnosis, RecoveryPlan, and OracleResponse are imported directly —
  never redefined. GUARDIAN's whole job is synthesising all three; coupling
  is intentional, same reasoning as why ATHENA imports SHERLOCK and ORACLE.
- GuardianDecision is a pure output schema: no LLM involvement, no API key,
  no Monte Carlo. Every field is derived deterministically from the three
  upstream schemas by the rule engine in engine.py.
- auto_executes is True for both AUTOMATED_GUARDED and AUTONOMOUS_SAFED —
  it answers "does this fire without waiting for a human?". The two tiers are
  distinguished by notify_operator_post_hoc, not by auto_executes.
- notify_operator_post_hoc is always True for AUTONOMOUS_SAFED: even fully
  autonomous spacecraft actions require after-the-fact human review in real
  operations.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

# -- Upstream schemas — imported directly, never redefined ---------------------
from backend.sherlock.schemas import SherlockDiagnosis  # noqa: F401 (re-exported)
from backend.athena.schemas import RecoveryPlan          # noqa: F401 (re-exported)
from backend.oracle.schemas import OracleResponse        # noqa: F401 (re-exported)


# -----------------------------------------------------------------------------
# Enums
# -----------------------------------------------------------------------------


class DecisionTier(str, Enum):
    """
    The three execution tiers GUARDIAN can assign to a recovery action.

    AUTONOMOUS_SAFED:
        Time-critical — fewer than 5 minutes to critical. A generic, fast,
        reversible safing action (shed_nonessential_load) is executed
        immediately without any other reasoning. Operator is notified
        after the fact (notify_operator_post_hoc = True).

    MANUAL_INTERLOCK:
        Human approval required before any action executes. Triggered by
        high/critical urgency, an irreversible recommended action, an ORACLE
        all-actions-unsafe flag, or a safety score below the safety floor.

    AUTOMATED_GUARDED:
        Routine case — execute the recommended action automatically.
        Urgency is low/medium, action is reversible, ORACLE gave no unsafe
        flags, and the safety score clears the floor.
    """

    AUTONOMOUS_SAFED  = "AUTONOMOUS_SAFED"
    MANUAL_INTERLOCK  = "MANUAL_INTERLOCK"
    AUTOMATED_GUARDED = "AUTOMATED_GUARDED"


# -----------------------------------------------------------------------------
# Output schema
# -----------------------------------------------------------------------------


class GuardianDecision(BaseModel):
    """
    GUARDIAN's full output: the execution-gate decision for a single recovery
    attempt. Produced deterministically by engine.evaluate() — no LLM, no
    external calls.

    Consumed by:
        - api.py  — to decide whether to hold for human input or fire immediately
        - SCRIBE  — to include the gate decision in the mission runbook
        - Frontend — to render the correct approval UI or confirmation banner

    Audit fields (time_to_critical_minutes, urgency, safety_score, decided_at)
    are echoed here so any downstream consumer has a complete, self-contained
    record without needing to re-fetch upstream data.
    """

    # -- Decision --------------------------------------------------------------

    tier: DecisionTier = Field(
        ...,
        description=(
            "The execution tier assigned by GUARDIAN's rule engine. "
            "First-match wins across the 5-step ordered rule set."
        ),
    )
    action_name: str = Field(
        ...,
        description=(
            "The action being taken or proposed. For AUTONOMOUS_SAFED this is "
            "always shed_nonessential_load. For the other two tiers it is "
            "recovery_plan.recommended_action."
        ),
    )
    auto_executes: bool = Field(
        ...,
        description=(
            "True if this decision fires without waiting for a human. "
            "True for AUTOMATED_GUARDED and AUTONOMOUS_SAFED; "
            "False only for MANUAL_INTERLOCK."
        ),
    )
    requires_human_approval: bool = Field(
        ...,
        description=(
            "True if a human must approve before any action executes. "
            "Always the logical inverse of auto_executes — both fields are "
            "kept so consumers never have to negate one to get the other."
        ),
    )
    rationale: str = Field(
        ...,
        min_length=10,
        description=(
            "One-sentence explanation naming the specific rule that fired "
            "(e.g. 'Rule 1 fired: time_to_critical=3 min is below the 5-min "
            "emergency threshold'). Suitable for operator display and SCRIBE."
        ),
    )

    # -- Post-hoc notification -------------------------------------------------

    notify_operator_post_hoc: bool = Field(
        ...,
        description=(
            "True whenever tier is AUTONOMOUS_SAFED. Even fully autonomous "
            "actions must be flagged for after-the-fact human review in real "
            "spacecraft operations. False for all other tiers."
        ),
    )

    # -- Audit / provenance ----------------------------------------------------

    time_to_critical_minutes: int = Field(
        ...,
        description="Echoed from SherlockDiagnosis.time_to_critical_estimate_minutes.",
    )
    urgency: str = Field(
        ...,
        description="Echoed from SherlockDiagnosis.urgency (string value of UrgencyLevel enum).",
    )
    safety_score: float = Field(
        ...,
        description=(
            "The safety_score of the action being evaluated. For AUTONOMOUS_SAFED "
            "this is the score of shed_nonessential_load from ORACLE results if "
            "present, or the sentinel value -999.0 if it was not evaluated — "
            "expected and correct since Rule 1 fires before ORACLE is fully consulted."
        ),
    )
    decided_at: datetime = Field(
        ...,
        description="UTC timestamp when GUARDIAN produced this decision.",
    )
