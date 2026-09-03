"""
SHERLOCK — Agent Integration Tests (Mocked LLM)

Tests SherlockAgent with a mocked Anthropic client — no real API calls.
Tests cover:
  - Happy path: valid LLM response → SherlockDiagnosis returned
  - JSON parse failure → retry with reprompt → eventual success
  - Schema validation failure → retry → success
  - Graph validation failure (root cause outside candidates) → retry → success
  - All retries exhausted → SherlockDiagnosisError raised (loud failure)
  - Markdown fence stripping in JSON parser
  - Unknown subsystem → SherlockGraphError
"""

from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

from backend.sherlock.agent import SherlockAgent
from backend.sherlock.schemas import (
    AnomalyEvent,
    SherlockDiagnosis,
    SherlockDiagnosisError,
    SherlockGraphError,
    SeverityLevel,
    UrgencyLevel,
)
from backend.sherlock.telemetry_interface import MockTelemetryProvider


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

NOW = datetime.now(timezone.utc)


def make_event(
    flagged_subsystem: str = "EPS",
    flagged_parameter: str = "battery_voltage_v",
    severity: SeverityLevel = SeverityLevel.HIGH,
    confidence: float = 0.85,
    anomaly_id: str = "TEST-001",
) -> AnomalyEvent:
    return AnomalyEvent(
        anomaly_id=anomaly_id,
        flagged_subsystem=flagged_subsystem,
        flagged_parameter=flagged_parameter,
        severity=severity,
        confidence_score=confidence,
        timestamp=NOW,
        telemetry_window=[{"battery_voltage_v": 21.3}],
    )


def make_valid_llm_json(
    root_cause: str = "EPS",
    chain: list[str] | None = None,
    urgency: str = "HIGH",
    time_to_critical: int = 45,
) -> str:
    chain = chain or [root_cause, "TCS"]
    return json.dumps({
        "primary_root_cause": root_cause,
        "causal_chain": chain,
        "affected_subsystems": chain,
        "confidence_score": 0.82,
        "urgency": urgency,
        "time_to_critical_estimate_minutes": time_to_critical,
        "reasoning": "Battery voltage critically low indicating EPS primary fault cascading to thermal control.",
    })


def make_agent(api_key: str = "test-key-xxxx") -> SherlockAgent:
    """Create a SherlockAgent with a fake API key (OpenAI client will be mocked)."""
    with patch("backend.sherlock.agent.OpenAI"):
        agent = SherlockAgent(api_key=api_key, max_retries=3)
    return agent


def mock_llm_response(agent: SherlockAgent, *responses: str) -> None:
    """
    Patch the agent's _call_llm to return responses in sequence.
    If more calls are made than responses provided, the last response is repeated.
    """
    call_count = {"n": 0}

    def _fake_call(messages):
        idx = min(call_count["n"], len(responses) - 1)
        call_count["n"] += 1
        return responses[idx]

    agent._call_llm = _fake_call


# ─────────────────────────────────────────────────────────────────────────────
# Happy path tests
# ─────────────────────────────────────────────────────────────────────────────

class TestHappyPath:
    def test_valid_first_attempt(self):
        agent = make_agent()
        mock_llm_response(agent, make_valid_llm_json(root_cause="EPS", chain=["EPS", "TCS"]))

        event = make_event(flagged_subsystem="EPS")
        diagnosis = agent.diagnose(event)

        assert isinstance(diagnosis, SherlockDiagnosis)
        assert diagnosis.primary_root_cause == "EPS"
        assert diagnosis.llm_attempts == 1
        assert "EPS" in diagnosis.graph_candidate_set
        assert diagnosis.diagnosis_timestamp is not None

    def test_diagnosis_for_propulsion_fault(self):
        agent = make_agent()
        # For Propulsion flagged, valid candidates at depth=1: Propulsion, EPS, TCS
        valid_json = make_valid_llm_json(
            root_cause="EPS",
            chain=["EPS", "Propulsion"],
            urgency="CRITICAL",
            time_to_critical=10,
        )
        mock_llm_response(agent, valid_json)

        event = make_event(flagged_subsystem="Propulsion", flagged_parameter="tank_pressure_bar")
        diagnosis = agent.diagnose(event)

        assert diagnosis.primary_root_cause == "EPS"
        assert "Propulsion" in diagnosis.affected_subsystems or "EPS" in diagnosis.affected_subsystems
        assert diagnosis.urgency == UrgencyLevel.CRITICAL

    def test_diagnosis_with_chronicle_context(self):
        agent = make_agent()
        mock_llm_response(agent, make_valid_llm_json(root_cause="EPS", chain=["EPS"]))

        event = make_event(flagged_subsystem="EPS")
        event_with_context = AnomalyEvent(
            **{**event.model_dump(), "event_log_context": "Heater A disabled 2 hours prior."}
        )

        diagnosis = agent.diagnose(event_with_context)
        assert isinstance(diagnosis, SherlockDiagnosis)

    def test_diagnosis_with_mock_telemetry_provider(self):
        agent = make_agent()
        mock_llm_response(agent, make_valid_llm_json(root_cause="TCS", chain=["TCS", "ADCS"]))

        provider = MockTelemetryProvider()
        provider.inject_fault("TCS", {"obc_board_temp_c": 78.0})  # overtemp

        event = make_event(flagged_subsystem="ADCS")
        diagnosis = agent.diagnose(event, telemetry_provider=provider)

        assert isinstance(diagnosis, SherlockDiagnosis)

    def test_audit_fields_populated(self):
        agent = make_agent()
        mock_llm_response(agent, make_valid_llm_json(root_cause="EPS", chain=["EPS"]))

        event = make_event(flagged_subsystem="EPS")
        diagnosis = agent.diagnose(event)

        assert isinstance(diagnosis.graph_candidate_set, list)
        assert len(diagnosis.graph_candidate_set) > 0
        assert isinstance(diagnosis.llm_attempts, int)
        assert diagnosis.llm_attempts >= 1
        assert isinstance(diagnosis.diagnosis_timestamp, datetime)


# ─────────────────────────────────────────────────────────────────────────────
# Retry behaviour tests
# ─────────────────────────────────────────────────────────────────────────────

class TestRetryBehaviour:
    def test_json_parse_failure_then_success(self):
        """First response is not JSON; second is valid."""
        agent = make_agent()
        good_json = make_valid_llm_json(root_cause="EPS", chain=["EPS"])
        mock_llm_response(agent, "Sorry, I cannot help with that.", good_json)

        event = make_event(flagged_subsystem="EPS")
        diagnosis = agent.diagnose(event)

        assert isinstance(diagnosis, SherlockDiagnosis)
        assert diagnosis.llm_attempts == 2

    def test_schema_validation_failure_then_success(self):
        """First response is JSON but missing required fields; second is valid."""
        agent = make_agent()
        bad_json = json.dumps({"primary_root_cause": "EPS"})  # missing many fields
        good_json = make_valid_llm_json(root_cause="EPS", chain=["EPS"])
        mock_llm_response(agent, bad_json, good_json)

        event = make_event(flagged_subsystem="EPS")
        diagnosis = agent.diagnose(event)

        assert diagnosis.llm_attempts == 2

    def test_graph_validation_failure_then_success(self):
        """
        First response claims a root cause NOT in the candidate set for Propulsion
        (e.g. ADCS — which is NOT a direct predecessor of Propulsion).
        Second response correctly picks EPS (which IS a candidate).
        """
        agent = make_agent()
        # ADCS is not a predecessor of Propulsion at depth=1
        bad_root = make_valid_llm_json(
            root_cause="ADCS",
            chain=["ADCS", "Propulsion"],
        )
        good_root = make_valid_llm_json(
            root_cause="EPS",
            chain=["EPS", "Propulsion"],
        )
        mock_llm_response(agent, bad_root, good_root)

        event = make_event(flagged_subsystem="Propulsion")
        diagnosis = agent.diagnose(event)

        assert diagnosis.primary_root_cause == "EPS"
        assert diagnosis.llm_attempts == 2

    def test_all_retries_exhausted_raises_loud_error(self):
        """Three consecutive failures → SherlockDiagnosisError, never silent."""
        agent = make_agent()
        # All responses are invalid JSON
        mock_llm_response(agent, "not json", "also not json", "still not json")

        event = make_event(flagged_subsystem="EPS")
        with pytest.raises(SherlockDiagnosisError) as exc_info:
            agent.diagnose(event)

        err = exc_info.value
        assert "3" in str(err)  # mentions retry count
        assert err.last_raw_response is not None

    def test_three_graph_failures_raises(self):
        """If LLM always returns a root cause outside candidates → exhausts retries."""
        agent = make_agent()
        # OBC is not a predecessor of Propulsion at depth=1
        bad = make_valid_llm_json(root_cause="OBC", chain=["OBC", "Propulsion"])
        mock_llm_response(agent, bad, bad, bad)

        event = make_event(flagged_subsystem="Propulsion")
        with pytest.raises(SherlockDiagnosisError):
            agent.diagnose(event)


# ─────────────────────────────────────────────────────────────────────────────
# JSON parser edge cases
# ─────────────────────────────────────────────────────────────────────────────

class TestJsonParserEdgeCases:
    def test_strips_markdown_json_fence(self):
        """LLM sometimes wraps response in ```json ... ``` — parser should handle it."""
        agent = make_agent()
        fenced = "```json\n" + make_valid_llm_json(root_cause="EPS", chain=["EPS"]) + "\n```"
        mock_llm_response(agent, fenced)

        event = make_event(flagged_subsystem="EPS")
        diagnosis = agent.diagnose(event)

        assert isinstance(diagnosis, SherlockDiagnosis)

    def test_strips_plain_fence(self):
        agent = make_agent()
        fenced = "```\n" + make_valid_llm_json(root_cause="EPS", chain=["EPS"]) + "\n```"
        mock_llm_response(agent, fenced)

        event = make_event(flagged_subsystem="EPS")
        diagnosis = agent.diagnose(event)

        assert isinstance(diagnosis, SherlockDiagnosis)


# ─────────────────────────────────────────────────────────────────────────────
# Error cases
# ─────────────────────────────────────────────────────────────────────────────

class TestErrorCases:
    def test_unknown_subsystem_raises_graph_error(self):
        agent = make_agent()
        event = AnomalyEvent(
            anomaly_id="BAD-001",
            flagged_subsystem="Battery",  # not in graph
            flagged_parameter="voltage",
            severity=SeverityLevel.HIGH,
            confidence_score=0.9,
            timestamp=NOW,
        )
        with pytest.raises(SherlockGraphError):
            agent.diagnose(event)

    def test_missing_api_key_raises_environment_error(self):
        import os
        original = os.environ.pop("OPENROUTER_API_KEY", None)
        try:
            with pytest.raises(EnvironmentError, match="OPENROUTER_API_KEY"):
                SherlockAgent(api_key=None)
        finally:
            if original:
                os.environ["OPENROUTER_API_KEY"] = original

    def test_get_candidates_for_utility(self):
        agent = make_agent()
        candidates = agent.get_candidates_for("Propulsion", depth=1)
        assert "EPS" in candidates
        assert "TCS" in candidates
        assert "ADCS" not in candidates  # not a direct predecessor of Propulsion

    def test_graph_summary_utility(self):
        agent = make_agent()
        summary = agent.get_graph_summary()
        assert "EPS" in summary
        assert "18 edges" in summary
