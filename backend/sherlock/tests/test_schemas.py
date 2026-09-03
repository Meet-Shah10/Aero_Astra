"""
SHERLOCK — Schema Unit Tests

Tests Pydantic validation for AnomalyEvent and SherlockDiagnosis:
- Valid construction succeeds
- Required fields enforced
- Type coercion and bounds checking
- causal_chain[0] == primary_root_cause invariant
- audit_dict serialisation
"""

import pytest
from datetime import datetime, timezone
from backend.sherlock.schemas import (
    AnomalyEvent,
    SherlockDiagnosis,
    SeverityLevel,
    UrgencyLevel,
    TelemetrySnapshot,
    SherlockDiagnosisError,
    SherlockGraphError,
)
from pydantic import ValidationError


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

NOW = datetime.now(timezone.utc)

VALID_EVENT_DATA = {
    "anomaly_id": "ANO-001",
    "flagged_subsystem": "EPS",
    "flagged_parameter": "battery_voltage_v",
    "severity": SeverityLevel.HIGH,
    "confidence_score": 0.87,
    "timestamp": NOW,
    "telemetry_window": [{"battery_voltage_v": 21.3, "soc": 0.18}],
    "event_log_context": None,
}

VALID_DIAGNOSIS_DATA = {
    "primary_root_cause": "EPS",
    "causal_chain": ["EPS", "TCS", "ADCS"],
    "affected_subsystems": ["EPS", "TCS", "ADCS"],
    "confidence_score": 0.82,
    "urgency": UrgencyLevel.HIGH,
    "time_to_critical_estimate_minutes": 45,
    "reasoning": "Battery voltage drop indicates EPS primary fault, cascading to thermal and attitude systems.",
    "graph_candidate_set": ["EPS", "TCS", "ADCS", "OBC"],
    "llm_attempts": 1,
    "diagnosis_timestamp": NOW,
}


# ─────────────────────────────────────────────────────────────────────────────
# AnomalyEvent tests
# ─────────────────────────────────────────────────────────────────────────────

class TestAnomalyEvent:
    def test_valid_event(self):
        event = AnomalyEvent(**VALID_EVENT_DATA)
        assert event.anomaly_id == "ANO-001"
        assert event.flagged_subsystem == "EPS"
        assert event.severity == SeverityLevel.HIGH
        assert event.event_log_context is None

    def test_event_with_chronicle_context(self):
        data = {**VALID_EVENT_DATA, "event_log_context": "Heater A tripped at T-120s."}
        event = AnomalyEvent(**data)
        assert event.event_log_context == "Heater A tripped at T-120s."

    def test_empty_telemetry_window_defaults(self):
        data = {k: v for k, v in VALID_EVENT_DATA.items() if k != "telemetry_window"}
        event = AnomalyEvent(**data)
        assert event.telemetry_window == []

    def test_confidence_score_bounds(self):
        # Valid bounds
        AnomalyEvent(**{**VALID_EVENT_DATA, "confidence_score": 0.0})
        AnomalyEvent(**{**VALID_EVENT_DATA, "confidence_score": 1.0})
        AnomalyEvent(**{**VALID_EVENT_DATA, "confidence_score": 0.5})

    def test_confidence_score_out_of_bounds(self):
        with pytest.raises(ValidationError):
            AnomalyEvent(**{**VALID_EVENT_DATA, "confidence_score": 1.1})
        with pytest.raises(ValidationError):
            AnomalyEvent(**{**VALID_EVENT_DATA, "confidence_score": -0.01})

    def test_severity_enum_values(self):
        for sev in SeverityLevel:
            event = AnomalyEvent(**{**VALID_EVENT_DATA, "severity": sev})
            assert event.severity == sev

    def test_severity_string_coercion(self):
        """Pydantic should accept string values for Enum fields."""
        event = AnomalyEvent(**{**VALID_EVENT_DATA, "severity": "CRITICAL"})
        assert event.severity == SeverityLevel.CRITICAL

    def test_missing_required_field_raises(self):
        for required_field in ["anomaly_id", "flagged_subsystem", "flagged_parameter",
                                "severity", "confidence_score", "timestamp"]:
            data = {k: v for k, v in VALID_EVENT_DATA.items() if k != required_field}
            with pytest.raises(ValidationError):
                AnomalyEvent(**data)


# ─────────────────────────────────────────────────────────────────────────────
# TelemetrySnapshot tests
# ─────────────────────────────────────────────────────────────────────────────

class TestTelemetrySnapshot:
    def test_valid_snapshot(self):
        snap = TelemetrySnapshot(
            subsystem="EPS",
            parameters={"battery_voltage_v": 21.3, "soc": 0.18},
            timestamp=NOW,
        )
        assert snap.subsystem == "EPS"
        assert snap.parameters["battery_voltage_v"] == 21.3

    def test_empty_parameters(self):
        """Empty parameters dict should be valid."""
        snap = TelemetrySnapshot(subsystem="OBC", parameters={}, timestamp=NOW)
        assert snap.parameters == {}


# ─────────────────────────────────────────────────────────────────────────────
# SherlockDiagnosis tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSherlockDiagnosis:
    def test_valid_diagnosis(self):
        diag = SherlockDiagnosis(**VALID_DIAGNOSIS_DATA)
        assert diag.primary_root_cause == "EPS"
        assert diag.urgency == UrgencyLevel.HIGH
        assert diag.llm_attempts == 1

    def test_causal_chain_first_must_equal_root_cause(self):
        """If causal_chain[0] != primary_root_cause, validation should fail."""
        data = {
            **VALID_DIAGNOSIS_DATA,
            "primary_root_cause": "TCS",
            "causal_chain": ["EPS", "TCS"],  # first != primary_root_cause
        }
        with pytest.raises(ValidationError, match="causal_chain"):
            SherlockDiagnosis(**data)

    def test_causal_chain_cannot_be_empty(self):
        data = {**VALID_DIAGNOSIS_DATA, "causal_chain": []}
        with pytest.raises(ValidationError):
            SherlockDiagnosis(**data)

    def test_confidence_score_clamped(self):
        # Boundary values
        diag_low = SherlockDiagnosis(**{**VALID_DIAGNOSIS_DATA, "confidence_score": 0.0})
        assert diag_low.confidence_score == 0.0
        diag_high = SherlockDiagnosis(**{**VALID_DIAGNOSIS_DATA, "confidence_score": 1.0})
        assert diag_high.confidence_score == 1.0

    def test_confidence_score_out_of_bounds_raises(self):
        with pytest.raises(ValidationError):
            SherlockDiagnosis(**{**VALID_DIAGNOSIS_DATA, "confidence_score": 1.5})

    def test_time_to_critical_must_be_non_negative(self):
        with pytest.raises(ValidationError):
            SherlockDiagnosis(**{**VALID_DIAGNOSIS_DATA, "time_to_critical_estimate_minutes": -1})

    def test_time_to_critical_zero_allowed(self):
        diag = SherlockDiagnosis(**{**VALID_DIAGNOSIS_DATA, "time_to_critical_estimate_minutes": 0})
        assert diag.time_to_critical_estimate_minutes == 0

    def test_urgency_enum_all_values(self):
        for urgency in UrgencyLevel:
            diag = SherlockDiagnosis(**{**VALID_DIAGNOSIS_DATA, "urgency": urgency})
            assert diag.urgency == urgency

    def test_urgency_string_coercion(self):
        diag = SherlockDiagnosis(**{**VALID_DIAGNOSIS_DATA, "urgency": "CRITICAL"})
        assert diag.urgency == UrgencyLevel.CRITICAL

    def test_missing_required_field_raises(self):
        for required_field in [
            "primary_root_cause", "causal_chain", "affected_subsystems",
            "confidence_score", "urgency", "time_to_critical_estimate_minutes",
            "reasoning", "graph_candidate_set", "llm_attempts", "diagnosis_timestamp",
        ]:
            data = {k: v for k, v in VALID_DIAGNOSIS_DATA.items() if k != required_field}
            with pytest.raises(ValidationError):
                SherlockDiagnosis(**data)

    def test_to_audit_dict_serializable(self):
        diag = SherlockDiagnosis(**VALID_DIAGNOSIS_DATA)
        audit = diag.to_audit_dict()
        import json
        # Should be JSON-serializable
        dumped = json.dumps(audit)
        reloaded = json.loads(dumped)
        assert reloaded["primary_root_cause"] == "EPS"
        assert reloaded["urgency"] == "HIGH"  # Enum → string

    def test_llm_attempts_must_be_positive(self):
        with pytest.raises(ValidationError):
            SherlockDiagnosis(**{**VALID_DIAGNOSIS_DATA, "llm_attempts": 0})

    def test_reasoning_minimum_length(self):
        """reasoning must be at least 10 characters."""
        with pytest.raises(ValidationError):
            SherlockDiagnosis(**{**VALID_DIAGNOSIS_DATA, "reasoning": "short"})


# ─────────────────────────────────────────────────────────────────────────────
# Error classes
# ─────────────────────────────────────────────────────────────────────────────

class TestErrorClasses:
    def test_sherlock_diagnosis_error_message(self):
        err = SherlockDiagnosisError("All 3 retries failed.", last_raw_response="bad json{")
        assert "All 3 retries failed." in str(err)
        assert err.last_raw_response == "bad json{"

    def test_sherlock_graph_error(self):
        err = SherlockGraphError("Unknown subsystem 'Battery'")
        assert "Battery" in str(err)
