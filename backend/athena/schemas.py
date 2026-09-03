"""
AERO-ASTRA — ATHENA Schemas
============================
All data contracts for ATHENA's input and output.

Design notes:
- SherlockDiagnosis and OracleResponse are imported directly — not redefined.
  ATHENA's job is to synthesise both; coupling here is intentional.
- Two-schema pattern:
    AthenaLLMOption  — the schema the LLM is asked to fill (no safety_score,
                       no blended_rank). This eliminates an entire failure mode:
                       the LLM cannot hallucinate a wrong safety score because
                       it is never asked to produce one.
    RecoveryOption   — the application schema assembled by Python after
                       validation: AthenaLLMOption + ORACLE's real safety_score
                       + programmatically computed blended_rank + is_irreversible
                       from a hardcoded lookup, never LLM-decided.
- is_irreversible is derived from scoring.IRREVERSIBLE_ACTIONS, a frozenset in
  scoring.py. GUARDIAN and api.py gate on this field; it must never come from
  the LLM.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

# ── Upstream schemas — imported directly, never redefined ─────────────────────
from backend.sherlock.schemas import SherlockDiagnosis  # noqa: F401 (re-exported)
from backend.oracle.schemas import OracleResponse        # noqa: F401 (re-exported)


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────


class OperatorEffort(str, Enum):
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"


# ─────────────────────────────────────────────────────────────────────────────
# Input schemas
# ─────────────────────────────────────────────────────────────────────────────


class MissionConstraints(BaseModel):
    """
    Qualitative operator context passed to ATHENA's LLM reasoning.

    These fields are NOT fed into a constraint solver. They are included
    verbatim in the LLM prompt as context so the model can weigh them
    when judging effectiveness and effort. ATHENA does not enforce them
    programmatically — GUARDIAN enforces hard limits.
    """

    min_fuel_reserve_pct: float = Field(
        default=10.0,
        ge=0.0,
        le=100.0,
        description="Minimum acceptable fuel reserve as a percentage of tank capacity.",
    )
    max_operator_effort: OperatorEffort = Field(
        default=OperatorEffort.HIGH,
        description=(
            "Maximum acceptable operator effort level. 'low' = fully autonomous; "
            "'high' = any effort level is acceptable."
        ),
    )
    notes: str | None = Field(
        default=None,
        description=(
            "Free-text operator notes (e.g. 'next ground station pass in 12 min', "
            "'crew unavailable', 'battery cells B3 and B4 already flagged'). "
            "ATHENA includes this in the LLM context for qualitative reasoning."
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# LLM output schema (Two-Schema Pattern — Phase 1 of assembly)
# ─────────────────────────────────────────────────────────────────────────────


class AthenaLLMOption(BaseModel):
    """
    The schema the LLM is asked to produce for each recovery option.

    Critically, this schema does NOT include:
    - safety_score     — injected from ORACLE's real result after validation
    - blended_rank     — computed by scoring.blended_rank() after validation
    - is_irreversible  — looked up from scoring.IRREVERSIBLE_ACTIONS, never LLM-decided

    This eliminates the score-hallucination failure mode entirely and reduces
    the validation surface to what the LLM can actually reason about.
    """

    action_name: str = Field(
        ...,
        description=(
            "Recovery action name. MUST be one of the action names from ORACLE's "
            "validated results. Any other value will be rejected."
        ),
    )
    procedure_steps: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "Ordered, human-readable procedure steps for the operator checklist "
            "and SCRIBE runbook. 3–5 concise steps per option."
        ),
    )
    effectiveness_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Functional recovery quality beyond mere survival (0.0–1.0). "
            "ORACLE's safety_score already covers success probability — do NOT "
            "repeat it here. Effectiveness measures outcome quality: does this "
            "action restore full operational capability (1.0) or merely keep "
            "the satellite alive in degraded safe mode (0.3)?"
        ),
    )
    operator_effort: OperatorEffort = Field(
        ...,
        description=(
            "Effort level required for ground operators to execute this action. "
            "'low' = autonomous / single command; 'medium' = multi-step sequence "
            "requiring operator attention; 'high' = complex manual procedure."
        ),
    )
    predicted_outcome: str = Field(
        ...,
        min_length=10,
        description=(
            "Short narrative (2–3 sentences) describing what the satellite state "
            "will look like after successful execution of this action."
        ),
    )
    contra_indications: list[str] = Field(
        default_factory=list,
        description=(
            "Conditions under which this action should NOT be taken "
            "(e.g., 'Do not use if fuel < 5 kg', 'Avoid in eclipse'). "
            "Empty list if no contra-indications."
        ),
    )

    @field_validator("effectiveness_score")
    @classmethod
    def _validate_effectiveness(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"effectiveness_score must be in [0, 1], got {v}")
        return round(v, 4)


# ─────────────────────────────────────────────────────────────────────────────
# Application schema (Two-Schema Pattern — Phase 2 of assembly)
# ─────────────────────────────────────────────────────────────────────────────


class RecoveryOption(BaseModel):
    """
    Full application-level recovery option, assembled by Python after
    LLM validation. Never directly returned by the LLM.

    Fields beyond AthenaLLMOption:
        safety_score   — real value from ORACLE's ActionResult, injected here
        blended_rank   — computed by scoring.blended_rank(), not LLM-produced
        is_irreversible — from scoring.IRREVERSIBLE_ACTIONS frozenset, not LLM-decided

    GUARDIAN and api.py gate on action_name (machine-executable), is_irreversible,
    and blended_rank. procedure_steps and predicted_outcome are display-only for
    the React UI and SCRIBE runbook.
    """

    action_name: str = Field(
        ...,
        description="Machine-executable action identifier. Maps to RECOVERY_CATALOG in simulator/recovery.py.",
    )
    procedure_steps: list[str] = Field(
        ...,
        description="Human-readable ordered checklist for operator display and SCRIBE runbook.",
    )
    safety_score: float = Field(
        ...,
        description=(
            "ORACLE's computed safety score, passed through unchanged. "
            "Formula: nominal_recovery_rate - mission_loss_rate. Range [-1, +1]. "
            "Never produced by the LLM — injected from ORACLE's ActionResult."
        ),
    )
    effectiveness_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="LLM-judged functional recovery quality (0.0–1.0). Excludes survival probability.",
    )
    operator_effort: OperatorEffort = Field(
        ...,
        description="Operator effort level judged by the LLM.",
    )
    predicted_outcome: str = Field(
        ...,
        description="LLM-authored 2–3 sentence outcome narrative.",
    )
    contra_indications: list[str] = Field(
        default_factory=list,
        description="Conditions under which this action is contraindicated.",
    )
    blended_rank: float = Field(
        ...,
        description=(
            "Blended ranking score computed by scoring.blended_rank(). "
            "Formula: (safety*0.5) + (effectiveness*0.35) + ((1/effort_n)*0.15). "
            "Options are sorted by this field descending in RecoveryPlan."
        ),
    )
    is_irreversible: bool = Field(
        ...,
        description=(
            "True if executing this action cannot be undone without ground intervention. "
            "Sourced from scoring.IRREVERSIBLE_ACTIONS frozenset — never LLM-decided. "
            "GUARDIAN uses this to gate whether human approval is required."
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Top-level output
# ─────────────────────────────────────────────────────────────────────────────


class RecoveryPlan(BaseModel):
    """
    ATHENA's full output: a ranked recovery plan ready for GUARDIAN and SCRIBE.

    options is sorted by blended_rank descending.
    recommended_action is always options[0].action_name.

    Matches the WebSocket 'athena' message contract in backend.md §5:
        reasoning_cot: list[str]  — LLM's step-by-step reasoning chain
        steps: derived from options[0].procedure_steps for the recommended action

    Audit fields:
        llm_attempts   — number of LLM calls needed (matches SHERLOCK's pattern)
        generated_at   — UTC timestamp when ATHENA produced this plan
        diagnosis_context — echoed from SherlockDiagnosis.reasoning for trail
    """

    recommended_action: str = Field(
        ...,
        description="Action name of the top-ranked option by blended_rank. Always options[0].action_name.",
    )
    options: list[RecoveryOption] = Field(
        ...,
        min_length=1,
        description="2–3 ranked recovery options, sorted by blended_rank descending.",
    )
    reasoning_cot: list[str] = Field(
        ...,
        description=(
            "LLM's chain-of-thought reasoning steps. Exposed directly on RecoveryPlan "
            "to match the WebSocket contract (backend.md §5) — no joining/splitting in api.py."
        ),
    )
    overall_reasoning: str = Field(
        ...,
        description=(
            "LLM's prose summary of the recommendation rationale. "
            "Suitable for the SCRIBE runbook executive summary."
        ),
    )
    llm_attempts: int = Field(
        ...,
        ge=1,
        description="Number of LLM API calls needed to produce this valid plan.",
    )
    generated_at: datetime = Field(
        ...,
        description="UTC timestamp when ATHENA produced this plan.",
    )
    diagnosis_context: str = Field(
        ...,
        description="SHERLOCK's reasoning, echoed for audit trail linkage.",
    )

    def to_ws_message(self) -> dict[str, Any]:
        """
        Serialise to the 'athena' WebSocket message shape from backend.md §5.

        {
          "type": "athena",
          "primary_action": ...,
          "reasoningCoT": [...],
          "steps": [{order, action, description, estimated_duration_s, reversible}, ...]
        }
        """
        top = self.options[0]
        steps = [
            {
                "order": i + 1,
                "action": top.action_name,
                "description": step,
                "estimated_duration_s": None,   # SCRIBE may fill this later
                "reversible": not top.is_irreversible,
            }
            for i, step in enumerate(top.procedure_steps)
        ]
        return {
            "type": "athena",
            "primary_action": self.recommended_action,
            "reasoningCoT": self.reasoning_cot,
            "overall_reasoning": self.overall_reasoning,
            "steps": steps,
            "options": [opt.model_dump() for opt in self.options],
            "llm_attempts": self.llm_attempts,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Error type
# ─────────────────────────────────────────────────────────────────────────────


class AthenaError(Exception):
    """
    Raised when ATHENA exhausts all retry attempts without producing a
    valid, anti-hallucination-verified plan. Failure is always loud.
    Matches SherlockDiagnosisError's shape for consistency.
    """

    def __init__(self, message: str, last_raw_response: str | None = None) -> None:
        super().__init__(message)
        self.last_raw_response = last_raw_response
