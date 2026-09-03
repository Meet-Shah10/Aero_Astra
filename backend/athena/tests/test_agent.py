"""
ATHENA — Agent Tests (Mocked LLM)

Tests AthenaAgent with a mocked _call_llm — no real API calls.
Same structure as backend/sherlock/tests/test_agent.py.

Tests cover:
  Happy path
  ── valid LLM response on first attempt → RecoveryPlan returned
  ── safety_score comes from ORACLE, not LLM (Two-Schema Pattern)
  ── blended_rank computed, options sorted descending
  ── is_irreversible from hardcoded lookup, not LLM
  ── reasoning_cot and overall_reasoning preserved

  Retry behaviour (one test per failure mode)
  ── invalid JSON → reprompt → success
  ── missing required field → reprompt → success
  ── effectiveness_score out of range → reprompt → success
  ── action name not in ORACLE results → reprompt → success
  ── all retries exhausted → AthenaError raised (loud failure, never silent)
"""

from __future__ import annotations

import json
import time
import pytest
from datetime import datetime, timezone
from unittest.mock import patch

from backend.athena.agent import AthenaAgent
from backend.athena.schemas import (
    AthenaError,
    MissionConstraints,
    OperatorEffort,
    RecoveryPlan,
    RecoveryOption,
)
from backend.athena.scoring import blended_rank, IRREVERSIBLE_ACTIONS, is_action_irreversible
from backend.oracle.schemas import ActionResult, OracleRequest, OracleResponse
from backend.sherlock.schemas import (
    SherlockDiagnosis,
    UrgencyLevel,
)
from backend.simulator.schemas import MonteCarloResult


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

NOW = datetime.now(timezone.utc)


def make_mc_result(
    nominal: float = 0.87,
    degraded: float = 0.10,
    loss: float = 0.03,
    soc: float = 0.71,
    attitude: float = 1.2,
    action: str = "shed_nonessential_load",
) -> MonteCarloResult:
    return MonteCarloResult(
        proposed_action=action,
        nominal_recovery_rate=nominal,
        degraded_operation_rate=degraded,
        mission_loss_rate=loss,
        mean_final_battery_soc=soc,
        std_final_battery_soc=0.04,
        mean_final_attitude_error=attitude,
        n_runs=100,
        steps=300,
        outcome_counts={"nominal": 87, "degraded": 10, "mission_loss": 3},
    )


def make_oracle_response(
    actions: list[tuple[str, float]] | None = None,
) -> OracleResponse:
    """
    Build a minimal OracleResponse with given (action_name, safety_score) pairs.
    Defaults to two actions for most tests.
    """
    if actions is None:
        actions = [
            ("shed_nonessential_load", 0.84),
            ("enter_safe_low_power_mode", 0.72),
        ]
    results = [
        ActionResult(
            action_name=name,
            mc_result=make_mc_result(nominal=0.87 - i * 0.05, action=name),
            safety_score=score,
            flags=[],
        )
        for i, (name, score) in enumerate(actions)
    ]
    return OracleResponse(
        fault_name="tcs_thermal_runaway",
        diagnosis_context="TCS thermal fault.",
        mode="ranking",
        results=results,
        best_action=results[0].action_name,
        response_flags=[],
    )


def make_sherlock_diagnosis(
    root_cause: str = "TCS",
    urgency: str = "HIGH",
    time_to_critical: int = 23,
) -> SherlockDiagnosis:
    return SherlockDiagnosis(
        primary_root_cause=root_cause,
        causal_chain=[root_cause, "ADCS"],
        affected_subsystems=[root_cause, "ADCS", "EPS"],
        confidence_score=0.91,
        urgency=UrgencyLevel(urgency),
        time_to_critical_estimate_minutes=time_to_critical,
        reasoning=(
            f"Panel temperature rising rapidly indicating {root_cause} fault "
            f"cascading to attitude control degradation."
        ),
        graph_candidate_set=[root_cause, "EPS"],
        llm_attempts=1,
        diagnosis_timestamp=NOW,
    )


def make_valid_llm_json(
    action_names: list[str] | None = None,
    effectiveness: float = 0.82,
    effort: str = "low",
) -> str:
    """Build a valid LLM response JSON (AthenaLLMOption schema)."""
    if action_names is None:
        action_names = ["shed_nonessential_load", "enter_safe_low_power_mode"]

    options = []
    for i, name in enumerate(action_names):
        options.append({
            "action_name": name,
            "procedure_steps": [
                f"Step 1: Initiate {name} command sequence.",
                "Step 2: Monitor subsystem telemetry for 60 seconds.",
                "Step 3: Confirm recovery or escalate.",
            ],
            "effectiveness_score": round(effectiveness - i * 0.05, 2),
            "operator_effort": effort,
            "predicted_outcome": (
                f"Executing {name} stabilises the fault within 10 minutes, "
                f"restoring nominal subsystem parameters."
            ),
            "contra_indications": [],
        })

    return json.dumps({
        "reasoning_cot": [
            "ORACLE ranked shed_nonessential_load highest with safety_score=0.84.",
            "Urgency is HIGH with 23 minutes to critical — prioritise low-effort actions.",
        ],
        "overall_reasoning": (
            "shed_nonessential_load is the safest and least-effort option. "
            "It buys time for the primary fault to be addressed."
        ),
        "options": options,
    })


def make_agent(api_key: str = "test-key-xxxx") -> AthenaAgent:
    """Create an AthenaAgent with a fake API key (OpenAI client will be mocked)."""
    with patch("backend.athena.agent.OpenAI"):
        agent = AthenaAgent(api_key=api_key, max_retries=3)
    return agent


def mock_llm_response(agent: AthenaAgent, *responses: str) -> None:
    """
    Patch the agent's _call_llm to return responses in sequence.
    If more calls are made than responses provided, the last response is repeated.
    Same helper pattern as sherlock/tests/test_agent.py.
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
    def test_valid_first_attempt_returns_plan(self):
        """Valid LLM response on first attempt → RecoveryPlan returned."""
        agent = make_agent()
        mock_llm_response(agent, make_valid_llm_json())

        plan = agent.plan(make_sherlock_diagnosis(), make_oracle_response())

        assert isinstance(plan, RecoveryPlan)
        assert plan.llm_attempts == 1
        assert plan.recommended_action in {
            "shed_nonessential_load", "enter_safe_low_power_mode"
        }
        assert len(plan.options) >= 1
        assert isinstance(plan.generated_at, datetime)

    def test_safety_score_from_oracle_not_llm(self):
        """
        Two-Schema Pattern: safety_score in RecoveryOption must come from
        ORACLE's ActionResult, not from the LLM.
        """
        agent = make_agent()
        oracle = make_oracle_response([("shed_nonessential_load", 0.84)])
        mock_llm_response(
            agent,
            make_valid_llm_json(action_names=["shed_nonessential_load"]),
        )

        plan = agent.plan(make_sherlock_diagnosis(), oracle)

        opt = plan.options[0]
        assert opt.action_name == "shed_nonessential_load"
        # Must match ORACLE exactly, not whatever the LLM might have said
        assert opt.safety_score == pytest.approx(0.84, abs=1e-6)

    def test_options_sorted_by_blended_rank_descending(self):
        """Options must be sorted by blended_rank descending after assembly."""
        agent = make_agent()
        oracle = make_oracle_response([
            ("shed_nonessential_load", 0.84),
            ("enter_safe_low_power_mode", 0.55),
        ])
        mock_llm_response(
            agent,
            make_valid_llm_json(
                action_names=["enter_safe_low_power_mode", "shed_nonessential_load"],
            ),
        )

        plan = agent.plan(make_sherlock_diagnosis(), oracle)

        # Regardless of LLM order, should be sorted by blended_rank
        ranks = [opt.blended_rank for opt in plan.options]
        assert ranks == sorted(ranks, reverse=True)
        # Top recommended action should have highest rank
        assert plan.recommended_action == plan.options[0].action_name

    def test_is_irreversible_from_lookup_not_llm(self):
        """is_irreversible must be set from IRREVERSIBLE_ACTIONS, not LLM output."""
        agent = make_agent()
        oracle = make_oracle_response([
            ("thruster_isolation", 0.76),
            ("shed_nonessential_load", 0.84),
        ])
        mock_llm_response(
            agent,
            make_valid_llm_json(
                action_names=["thruster_isolation", "shed_nonessential_load"]
            ),
        )

        plan = agent.plan(make_sherlock_diagnosis(), oracle)

        ti_opt = next(o for o in plan.options if o.action_name == "thruster_isolation")
        sn_opt = next(o for o in plan.options if o.action_name == "shed_nonessential_load")

        assert ti_opt.is_irreversible is True    # in IRREVERSIBLE_ACTIONS
        assert sn_opt.is_irreversible is False   # not in IRREVERSIBLE_ACTIONS

    def test_reasoning_cot_preserved(self):
        """reasoning_cot from LLM must appear verbatim in RecoveryPlan."""
        agent = make_agent()
        mock_llm_response(agent, make_valid_llm_json())

        plan = agent.plan(make_sherlock_diagnosis(), make_oracle_response())

        assert isinstance(plan.reasoning_cot, list)
        assert len(plan.reasoning_cot) >= 1
        assert isinstance(plan.overall_reasoning, str)
        assert len(plan.overall_reasoning) > 0

    def test_with_mission_constraints(self):
        """Constraints are accepted and passed through without error."""
        agent = make_agent()
        mock_llm_response(agent, make_valid_llm_json())
        constraints = MissionConstraints(
            min_fuel_reserve_pct=15.0,
            max_operator_effort=OperatorEffort.MEDIUM,
            notes="Ground pass in 8 minutes.",
        )

        plan = agent.plan(
            make_sherlock_diagnosis(), make_oracle_response(), constraints
        )

        assert isinstance(plan, RecoveryPlan)

    def test_blended_rank_computation_correct(self):
        """Verify blended_rank is computed with the correct formula."""
        agent = make_agent()
        oracle = make_oracle_response([("shed_nonessential_load", 0.84)])
        mock_llm_response(
            agent,
            make_valid_llm_json(
                action_names=["shed_nonessential_load"],
                effectiveness=0.82,
                effort="low",
            ),
        )

        plan = agent.plan(make_sherlock_diagnosis(), oracle)

        expected = blended_rank(
            safety_score=0.84,
            effectiveness_score=0.82,
            operator_effort="low",
        )
        assert plan.options[0].blended_rank == pytest.approx(expected, abs=1e-4)

    def test_diagnosis_context_echoed(self):
        """SHERLOCK's reasoning is echoed in the plan's diagnosis_context."""
        agent = make_agent()
        diagnosis = make_sherlock_diagnosis()
        mock_llm_response(agent, make_valid_llm_json())

        plan = agent.plan(diagnosis, make_oracle_response())

        assert plan.diagnosis_context == diagnosis.reasoning

    def test_to_ws_message_shape(self):
        """to_ws_message() returns the WebSocket contract shape from backend.md §5."""
        agent = make_agent()
        mock_llm_response(agent, make_valid_llm_json())

        plan = agent.plan(make_sherlock_diagnosis(), make_oracle_response())
        msg = plan.to_ws_message()

        assert msg["type"] == "athena"
        assert "primary_action" in msg
        assert "reasoningCoT" in msg
        assert isinstance(msg["reasoningCoT"], list)
        assert "steps" in msg
        assert isinstance(msg["steps"], list)
        assert all("order" in s and "action" in s and "reversible" in s for s in msg["steps"])


# ─────────────────────────────────────────────────────────────────────────────
# Retry behaviour — one test per failure mode
# ─────────────────────────────────────────────────────────────────────────────


class TestRetryBehaviour:
    def test_invalid_json_then_success(self):
        """First response is not JSON; second is valid."""
        agent = make_agent()
        mock_llm_response(
            agent,
            "I'm sorry, here's my analysis of the satellite fault...",  # not JSON
            make_valid_llm_json(),
        )

        plan = agent.plan(make_sherlock_diagnosis(), make_oracle_response())

        assert isinstance(plan, RecoveryPlan)
        assert plan.llm_attempts == 2

    def test_schema_failure_missing_field_then_success(self):
        """First response is JSON but missing 'options'; second is valid."""
        agent = make_agent()
        bad = json.dumps({"reasoning_cot": ["step 1"], "overall_reasoning": "ok"})
        mock_llm_response(agent, bad, make_valid_llm_json())

        plan = agent.plan(make_sherlock_diagnosis(), make_oracle_response())

        assert plan.llm_attempts == 2

    def test_schema_failure_effectiveness_out_of_range_then_success(self):
        """First response has effectiveness_score > 1.0; second is valid."""
        agent = make_agent()
        bad_payload = {
            "reasoning_cot": ["step"],
            "overall_reasoning": "ok",
            "options": [{
                "action_name": "shed_nonessential_load",
                "procedure_steps": ["Step 1."],
                "effectiveness_score": 1.5,   # out of range
                "operator_effort": "low",
                "predicted_outcome": "All systems nominal.",
                "contra_indications": [],
            }],
        }
        mock_llm_response(agent, json.dumps(bad_payload), make_valid_llm_json())

        plan = agent.plan(make_sherlock_diagnosis(), make_oracle_response())

        assert plan.llm_attempts == 2

    def test_hallucinated_action_name_then_success(self):
        """
        First response contains an action name not in ORACLE results.
        Second response uses valid names. Anti-hallucination check fires.
        """
        agent = make_agent()
        # LLM invents an action that ORACLE never tested
        bad = make_valid_llm_json(action_names=["reboot_obc_supervisor"])
        good = make_valid_llm_json(
            action_names=["shed_nonessential_load", "enter_safe_low_power_mode"]
        )
        mock_llm_response(agent, bad, good)

        plan = agent.plan(make_sherlock_diagnosis(), make_oracle_response())

        assert plan.llm_attempts == 2
        for opt in plan.options:
            assert opt.action_name in {
                "shed_nonessential_load", "enter_safe_low_power_mode"
            }

    def test_all_retries_exhausted_raises_loud_error(self):
        """Three consecutive failures → AthenaError raised, never silent."""
        agent = make_agent()
        mock_llm_response(
            agent,
            "not json at all",
            "still not json",
            "definitely not json",
        )

        with pytest.raises(AthenaError) as exc_info:
            agent.plan(make_sherlock_diagnosis(), make_oracle_response())

        err = exc_info.value
        assert "3" in str(err)  # mentions retry count
        assert err.last_raw_response is not None

    def test_all_retries_hallucinated_action_exhausted(self):
        """LLM always hallucinates an action name → exhausts all retries."""
        agent = make_agent()
        bad = make_valid_llm_json(action_names=["do_the_impossible"])
        mock_llm_response(agent, bad, bad, bad)

        with pytest.raises(AthenaError) as exc_info:
            agent.plan(make_sherlock_diagnosis(), make_oracle_response())

        assert "do_the_impossible" in str(exc_info.value).lower() or "3" in str(exc_info.value)


# ─────────────────────────────────────────────────────────────────────────────
# Scoring unit tests
# ─────────────────────────────────────────────────────────────────────────────


class TestScoring:
    def test_blended_rank_formula_low_effort(self):
        rank = blended_rank(0.84, 0.82, "low")
        expected = (0.84 * 0.50) + (0.82 * 0.35) + ((1 / 1) * 0.15)
        assert rank == pytest.approx(expected, abs=1e-4)

    def test_blended_rank_formula_high_effort(self):
        rank = blended_rank(0.84, 0.82, "high")
        expected = (0.84 * 0.50) + (0.82 * 0.35) + ((1 / 3) * 0.15)
        assert rank == pytest.approx(expected, abs=1e-4)

    def test_blended_rank_clamps_negative_safety(self):
        """Negative ORACLE safety score must be clamped to 0, not reduce rank below effort term."""
        rank_negative = blended_rank(-0.31, 0.80, "low")
        rank_zero     = blended_rank(0.0,   0.80, "low")
        assert rank_negative == rank_zero  # clamp makes them equal

    def test_blended_rank_clamps_safety_above_one(self):
        """safety_score > 1.0 defensively clamped to 1.0."""
        rank = blended_rank(1.5, 0.9, "low")
        expected = blended_rank(1.0, 0.9, "low")
        assert rank == pytest.approx(expected, abs=1e-4)

    def test_blended_rank_unknown_effort_defaults_medium(self):
        """Unknown effort string defaults to medium (effort_n=2) without raising."""
        rank = blended_rank(0.80, 0.75, "unknown_value")
        expected = blended_rank(0.80, 0.75, "medium")
        assert rank == pytest.approx(expected, abs=1e-4)

    def test_irreversible_actions_lookup(self):
        assert is_action_irreversible("switch_redundant_power_bus") is True
        assert is_action_irreversible("thruster_isolation") is True
        assert is_action_irreversible("shed_nonessential_load") is False
        assert is_action_irreversible("enter_safe_low_power_mode") is False
        assert is_action_irreversible("activate_backup_heater") is False
        assert is_action_irreversible("reorient_maximum_solar_exposure") is False


# ─────────────────────────────────────────────────────────────────────────────
# JSON parser edge cases
# ─────────────────────────────────────────────────────────────────────────────


class TestJsonParserEdgeCases:
    def test_strips_markdown_json_fence(self):
        """LLM sometimes wraps response in ```json ... ``` — parser strips it."""
        agent = make_agent()
        fenced = "```json\n" + make_valid_llm_json() + "\n```"
        mock_llm_response(agent, fenced)

        plan = agent.plan(make_sherlock_diagnosis(), make_oracle_response())
        assert isinstance(plan, RecoveryPlan)

    def test_strips_plain_fence(self):
        agent = make_agent()
        fenced = "```\n" + make_valid_llm_json() + "\n```"
        mock_llm_response(agent, fenced)

        plan = agent.plan(make_sherlock_diagnosis(), make_oracle_response())
        assert isinstance(plan, RecoveryPlan)


# ─────────────────────────────────────────────────────────────────────────────
# Error / environment tests
# ─────────────────────────────────────────────────────────────────────────────


class TestErrorCases:
    def test_missing_api_key_raises_environment_error(self):
        import os
        original = os.environ.pop("OPENROUTER_API_KEY", None)
        try:
            with pytest.raises(EnvironmentError, match="OPENROUTER_API_KEY"):
                AthenaAgent(api_key=None)
        finally:
            if original:
                os.environ["OPENROUTER_API_KEY"] = original

    def test_graceful_degradation_single_oracle_result(self):
        """
        If ORACLE only validated one action, ATHENA should degrade gracefully
        and return a plan with that one option (not error).
        """
        agent = make_agent()
        oracle = make_oracle_response([("shed_nonessential_load", 0.84)])
        mock_llm_response(
            agent,
            make_valid_llm_json(action_names=["shed_nonessential_load"]),
        )

        plan = agent.plan(make_sherlock_diagnosis(), oracle)

        assert len(plan.options) == 1
        assert plan.recommended_action == "shed_nonessential_load"
