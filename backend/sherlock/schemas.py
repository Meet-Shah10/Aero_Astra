"""
SHERLOCK — Pydantic Schemas
Agent 3 of AERO-ASTRA | Root-Cause Diagnosis

All input and output data contracts for SHERLOCK are defined here.
Downstream agents (ATHENA, SCRIBE) should import from this module.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


# ─────────────────────────────────────────────────────────────────────────────
# Enums — consistent style throughout (Enum, not Literal)
# ─────────────────────────────────────────────────────────────────────────────


class SeverityLevel(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class UrgencyLevel(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


# ─────────────────────────────────────────────────────────────────────────────
# Input Schemas
# ─────────────────────────────────────────────────────────────────────────────


class TelemetrySnapshot(BaseModel):
    """
    A point-in-time snapshot of one subsystem's telemetry parameters.
    Returned by TelemetryProvider.get_subsystem_snapshot().
    """

    subsystem: str = Field(..., description="Subsystem identifier, e.g. 'EPS'")
    parameters: dict[str, float] = Field(
        ...,
        description=(
            "Key-value map of telemetry parameter name → current value. "
            "E.g. {'battery_voltage': 24.1, 'soc': 0.42}"
        ),
    )
    timestamp: datetime = Field(
        ..., description="UTC timestamp of this snapshot"
    )


class AnomalyEvent(BaseModel):
    """
    The anomaly event payload SHERLOCK receives from an upstream source
    (typically SENTINEL). CHRONICLE's event log context is optional —
    SHERLOCK degrades gracefully and still produces a valid diagnosis
    without it.
    """

    anomaly_id: str = Field(..., description="Unique identifier for this anomaly event")
    flagged_subsystem: str = Field(
        ...,
        description=(
            "The subsystem in which the anomaly was detected. "
            "Must be one of the 6 modelled subsystems: "
            "EPS, TCS, ADCS, OBC, TT&C, Propulsion"
        ),
    )
    flagged_parameter: str = Field(
        ...,
        description="Specific telemetry parameter that triggered the anomaly flag",
    )
    severity: SeverityLevel = Field(
        ..., description="Severity level assigned by the upstream detector"
    )
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Upstream detector's confidence in this being a real anomaly (0–1)",
    )
    timestamp: datetime = Field(
        ..., description="UTC timestamp when the anomaly was detected"
    )
    telemetry_window: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Raw telemetry rows around the anomaly window. "
            "Each row is a dict of parameter→value. May be empty."
        ),
    )
    event_log_context: str | None = Field(
        default=None,
        description=(
            "Formatted event log context from CHRONICLE, if available. "
            "SHERLOCK works correctly without this (graceful degradation)."
        ),
    )

    @field_validator("confidence_score")
    @classmethod
    def _validate_confidence(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"confidence_score must be in [0, 1], got {v}")
        return round(v, 4)


# ─────────────────────────────────────────────────────────────────────────────
# Output Schema
# ─────────────────────────────────────────────────────────────────────────────


class SherlockDiagnosis(BaseModel):
    """
    The structured root-cause diagnosis produced by SHERLOCK.

    Core fields (per spec):
        primary_root_cause, causal_chain, affected_subsystems,
        confidence_score, urgency, time_to_critical_estimate_minutes, reasoning

    Audit/provenance fields (approved additions):
        graph_candidate_set  — what the dependency graph identified as valid candidates
        llm_attempts         — how many LLM calls were needed to produce a valid response
        diagnosis_timestamp  — when this diagnosis was produced
    """

    # ── Core output fields (required by spec) ─────────────────────────────────
    primary_root_cause: str = Field(
        ...,
        description=(
            "The subsystem identified as the originating fault. "
            "Guaranteed to be within the graph-computed candidate set."
        ),
    )
    causal_chain: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "Ordered list from root cause → intermediate effects → observed symptom. "
            "E.g. ['TCS', 'ADCS', 'TT&C']"
        ),
    )
    affected_subsystems: list[str] = Field(
        ...,
        min_length=1,
        description="All subsystems impacted, including the root cause and downstream victims",
    )
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="SHERLOCK's confidence in this diagnosis (0–1)",
    )
    urgency: UrgencyLevel = Field(
        ..., description="Operational urgency level for the response team"
    )
    time_to_critical_estimate_minutes: int = Field(
        ...,
        ge=0,
        description=(
            "Estimated minutes until the situation becomes irreversibly critical "
            "if no action is taken. 0 = already critical."
        ),
    )
    reasoning: str = Field(
        ...,
        min_length=10,
        description=(
            "Short free-text explanation of the reasoning chain, suitable for "
            "inclusion in an operator audit trail or SCRIBE runbook."
        ),
    )

    # ── Audit / provenance fields (approved additions) ─────────────────────────
    graph_candidate_set: list[str] = Field(
        ...,
        description="The set of subsystems the dependency graph identified as valid root cause candidates",
    )
    llm_attempts: int = Field(
        ...,
        ge=1,
        description="Number of LLM API calls needed to produce this valid diagnosis",
    )
    diagnosis_timestamp: datetime = Field(
        ..., description="UTC timestamp when SHERLOCK produced this diagnosis"
    )

    @field_validator("confidence_score")
    @classmethod
    def _validate_confidence(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"confidence_score must be in [0, 1], got {v}")
        return round(v, 4)

    @field_validator("causal_chain")
    @classmethod
    def _validate_chain_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("causal_chain must contain at least one entry")
        return v

    @model_validator(mode="after")
    def _validate_root_cause_in_chain(self) -> "SherlockDiagnosis":
        """The primary_root_cause must appear as the first element of causal_chain."""
        if self.causal_chain and self.causal_chain[0] != self.primary_root_cause:
            raise ValueError(
                f"causal_chain[0] must equal primary_root_cause. "
                f"Got chain[0]='{self.causal_chain[0]}' but root_cause='{self.primary_root_cause}'"
            )
        return self

    def to_audit_dict(self) -> dict[str, Any]:
        """Returns a fully serialisable dict for SCRIBE / logging."""
        d = self.model_dump()
        d["diagnosis_timestamp"] = self.diagnosis_timestamp.isoformat()
        d["urgency"] = self.urgency.value
        return d


# ─────────────────────────────────────────────────────────────────────────────
# Error types
# ─────────────────────────────────────────────────────────────────────────────


class SherlockDiagnosisError(Exception):
    """
    Raised when SHERLOCK exhausts all retry attempts without producing
    a valid, graph-consistent diagnosis. Failure is loud, never silent.
    """

    def __init__(self, message: str, last_raw_response: str | None = None):
        super().__init__(message)
        self.last_raw_response = last_raw_response


class SherlockGraphError(Exception):
    """Raised when the flagged subsystem is not recognised in the dependency graph."""

    pass
