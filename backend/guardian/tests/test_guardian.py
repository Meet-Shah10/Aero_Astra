"""
AERO-ASTRA — GUARDIAN Tests
============================
Unit tests for the 5-step GUARDIAN rule engine.

Each test class targets a specific rule or boundary condition. Tests use
synthetic SherlockDiagnosis, RecoveryPlan, and OracleResponse objects —
no simulator calls, no LLM calls, no external dependencies.

Test inventory:
    TestRule1AutonomousSafed
        - time_to_critical=3  -> AUTONOMOUS_SAFED
        - time_to_critical=0  -> AUTONOMOUS_SAFED  (already critical)
        - BOUNDARY: time_to_critical=5 -> does NOT trigger Rule 1 (stray <= guard)

    TestRule2ManualInterlockHighUrgency
        - urgency=HIGH,     time_to_critical=60 -> MANUAL_INTERLOCK
        - urgency=CRITICAL, time_to_critical=30 -> MANUAL_INTERLOCK

    TestRule3ManualInterlockIrreversible  ? THE CRITICAL MISSING CASE
        - low urgency + is_irreversible=True    -> MANUAL_INTERLOCK
          (must NOT fall through to AUTOMATED_GUARDED)

    TestRule4ManualInterlockOracleUnsafe
        - ALL_ACTIONS_UNSAFE in response_flags  -> MANUAL_INTERLOCK
        - safety_score below floor (0.19)       -> MANUAL_INTERLOCK
        - BOUNDARY: safety_score=0.20 exactly   -> does NOT trigger Rule 4

    TestRule5AutomatedGuarded
        - clean happy path                       -> AUTOMATED_GUARDED

    TestRuleOrdering
        - Rule 1 beats Rule 2 when both conditions hold
          (time_to_critical=3 AND urgency=CRITICAL -> AUTONOMOUS_SAFED, not MANUAL_INTERLOCK)

    TestOutputFieldInvariants
        - auto_executes is always inverse of requires_human_approval
        - notify_operator_post_hoc is True iff tier==AUTONOMOUS_SAFED
        - decided_at is a timezone-aware UTC datetime
        - rationale is non-empty for every tier
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from backend.sherlock.schemas import SherlockDiagnosis, UrgencyLevel
from backend.athena.schemas import RecoveryPlan, RecoveryOption, OperatorEffort
from backend.oracle.schemas import OracleResponse, ActionResult
from backend.simulator.schemas import MonteCarloResult
from backend.simulator.recovery import RECOVERY_CATALOG
from backend.guardian import evaluate, DecisionTier, SAFETY_SCORE_FLOOR, TIME_CRITICAL_THRESHOLD_MINUTES


# -----------------------------------------------------------------------------
# Factories — minimal valid objects for each upstream schema
# -----------------------------------------------------------------------------

_SAFING_ACTION = RECOVERY_CATALOG["shed_nonessential_load"].name
_GOOD_ACTION   = "switch_redundant_power_bus"
_IRREVERSIBLE_ACTION = "thruster_isolation"   # must be in IRREVERSIBLE_ACTIONS set

_NOW = datetime(2026, 9, 4, 0, 0, 0, tzinfo=timezone.utc)


def _make_mc(
    nominal: float = 0.75,
    loss: float = 0.05,
    action: str = _GOOD_ACTION,
) -> MonteCarloResult:
    degraded = round(1.0 - nominal - loss, 9)
    return MonteCarloResult(
        proposed_action=action,
        n_runs=100,
        steps=300,
        nominal_recovery_rate=nominal,
        degraded_operation_rate=degraded,
        mission_loss_rate=loss,
        mean_final_battery_soc=0.65,
        mean_final_attitude_error=3.0,
        std_final_battery_soc=0.04,
        outcome_counts={
            "nominal_recovery": int(nominal * 100),
            "degraded_operation": int(degraded * 100),
            "mission_loss": int(loss * 100),
        },
    )


def _make_action_result(
    action_name: str = _GOOD_ACTION,
    safety_score: float = 0.70,
    flags: list[str] | None = None,
) -> ActionResult:
    return ActionResult(
        action_name=action_name,
        mc_result=_make_mc(action=action_name),
        safety_score=safety_score,
        flags=flags or [],
    )


def _make_oracle(
    results: list[ActionResult] | None = None,
    response_flags: list[str] | None = None,
) -> OracleResponse:
    if results is None:
        results = [_make_action_result()]
    return OracleResponse(
        fault_name="eps_battery_degradation",
        diagnosis_context="test context",
        mode="single_action",
        results=results,
        best_action=results[0].action_name if results else None,
        response_flags=response_flags or [],
    )


def _make_option(
    action_name: str = _GOOD_ACTION,
    safety_score: float = 0.70,
    is_irreversible: bool = False,
) -> RecoveryOption:
    return RecoveryOption(
        action_name=action_name,
        procedure_steps=["Step 1", "Step 2"],
        safety_score=safety_score,
        effectiveness_score=0.80,
        operator_effort=OperatorEffort.LOW,
        predicted_outcome="System recovers to nominal state within 15 minutes.",
        contra_indications=[],
        blended_rank=0.75,
        is_irreversible=is_irreversible,
    )


def _make_plan(
    action_name: str = _GOOD_ACTION,
    safety_score: float = 0.70,
    is_irreversible: bool = False,
) -> RecoveryPlan:
    opt = _make_option(action_name=action_name, safety_score=safety_score, is_irreversible=is_irreversible)
    return RecoveryPlan(
        recommended_action=action_name,
        options=[opt],
        reasoning_cot=["Assessed fault.", "Identified best action."],
        overall_reasoning="Recommend immediate power bus switch to restore EPS.",
        llm_attempts=1,
        generated_at=_NOW,
        diagnosis_context="EPS battery degradation detected.",
    )


def _make_diagnosis(
    urgency: UrgencyLevel = UrgencyLevel.LOW,
    time_to_critical: int = 60,
) -> SherlockDiagnosis:
    return SherlockDiagnosis(
        primary_root_cause="EPS",
        causal_chain=["EPS"],
        affected_subsystems=["EPS"],
        confidence_score=0.90,
        urgency=urgency,
        time_to_critical_estimate_minutes=time_to_critical,
        reasoning="Battery SOC declining due to degradation.",
        graph_candidate_set=["EPS"],
        llm_attempts=1,
        diagnosis_timestamp=_NOW,
    )


# -----------------------------------------------------------------------------
# Rule 1 — AUTONOMOUS_SAFED
# -----------------------------------------------------------------------------


class TestRule1AutonomousSafed:
    def test_time_critical_3_triggers_autonomous_safed(self):
        """3 minutes to critical — well below threshold, must fire Rule 1."""
        decision = evaluate(
            diagnosis=_make_diagnosis(urgency=UrgencyLevel.LOW, time_to_critical=3),
            recovery_plan=_make_plan(),
            oracle_response=_make_oracle(),
        )
        assert decision.tier == DecisionTier.AUTONOMOUS_SAFED

    def test_action_is_shed_nonessential_load(self):
        """Rule 1 must always use the catalog-sourced safing action name."""
        decision = evaluate(
            diagnosis=_make_diagnosis(time_to_critical=2),
            recovery_plan=_make_plan(),
            oracle_response=_make_oracle(),
        )
        assert decision.action_name == _SAFING_ACTION

    def test_auto_executes_true(self):
        decision = evaluate(
            diagnosis=_make_diagnosis(time_to_critical=1),
            recovery_plan=_make_plan(),
            oracle_response=_make_oracle(),
        )
        assert decision.auto_executes is True

    def test_requires_human_approval_false(self):
        decision = evaluate(
            diagnosis=_make_diagnosis(time_to_critical=1),
            recovery_plan=_make_plan(),
            oracle_response=_make_oracle(),
        )
        assert decision.requires_human_approval is False

    def test_notify_operator_post_hoc_true(self):
        """Post-hoc notification is mandatory for autonomous safed actions."""
        decision = evaluate(
            diagnosis=_make_diagnosis(time_to_critical=4),
            recovery_plan=_make_plan(),
            oracle_response=_make_oracle(),
        )
        assert decision.notify_operator_post_hoc is True

    def test_time_critical_zero_triggers_autonomous_safed(self):
        """Zero minutes (already critical) must also fire Rule 1."""
        decision = evaluate(
            diagnosis=_make_diagnosis(time_to_critical=0),
            recovery_plan=_make_plan(),
            oracle_response=_make_oracle(),
        )
        assert decision.tier == DecisionTier.AUTONOMOUS_SAFED

    def test_boundary_exactly_5_minutes_does_not_trigger_rule1(self):
        """
        BOUNDARY TEST — time_to_critical=5 exactly.

        The rule is strictly 'time_to_critical < 5'. Five minutes flat must
        NOT trigger AUTONOMOUS_SAFED — it must fall through to the urgency check.
        A stray '<=' would break this silently.
        """
        decision = evaluate(
            diagnosis=_make_diagnosis(urgency=UrgencyLevel.LOW, time_to_critical=5),
            recovery_plan=_make_plan(),
            oracle_response=_make_oracle(),
        )
        assert decision.tier != DecisionTier.AUTONOMOUS_SAFED, (
            f"time_to_critical=5 must NOT trigger AUTONOMOUS_SAFED "
            f"(rule is < {TIME_CRITICAL_THRESHOLD_MINUTES}), got {decision.tier}"
        )


# -----------------------------------------------------------------------------
# Rule 2 — MANUAL_INTERLOCK via high/critical urgency
# -----------------------------------------------------------------------------


class TestRule2ManualInterlockHighUrgency:
    def test_high_urgency_triggers_manual_interlock(self):
        decision = evaluate(
            diagnosis=_make_diagnosis(urgency=UrgencyLevel.HIGH, time_to_critical=60),
            recovery_plan=_make_plan(),
            oracle_response=_make_oracle(),
        )
        assert decision.tier == DecisionTier.MANUAL_INTERLOCK

    def test_critical_urgency_triggers_manual_interlock(self):
        decision = evaluate(
            diagnosis=_make_diagnosis(urgency=UrgencyLevel.CRITICAL, time_to_critical=30),
            recovery_plan=_make_plan(),
            oracle_response=_make_oracle(),
        )
        assert decision.tier == DecisionTier.MANUAL_INTERLOCK

    def test_rule2_proposes_recommended_action(self):
        """Rule 2 holds the plan's recommended action for human approval."""
        plan = _make_plan(action_name=_GOOD_ACTION)
        decision = evaluate(
            diagnosis=_make_diagnosis(urgency=UrgencyLevel.HIGH, time_to_critical=60),
            recovery_plan=plan,
            oracle_response=_make_oracle(),
        )
        assert decision.action_name == _GOOD_ACTION

    def test_medium_urgency_does_not_trigger_rule2(self):
        """MEDIUM urgency must not trip Rule 2; should fall through to Rules 3-5."""
        decision = evaluate(
            diagnosis=_make_diagnosis(urgency=UrgencyLevel.MEDIUM, time_to_critical=60),
            recovery_plan=_make_plan(is_irreversible=False),
            oracle_response=_make_oracle(results=[_make_action_result(safety_score=0.70)]),
        )
        assert decision.tier != DecisionTier.MANUAL_INTERLOCK or True  # will be AUTOMATED_GUARDED
        assert decision.tier == DecisionTier.AUTOMATED_GUARDED


# -----------------------------------------------------------------------------
# Rule 3 — MANUAL_INTERLOCK via irreversible action  ? THE CRITICAL MISSING CASE
# -----------------------------------------------------------------------------


class TestRule3ManualInterlockIrreversible:
    def test_low_urgency_irreversible_triggers_manual_interlock(self):
        """
        THE CRITICAL MISSING CASE.

        Low urgency + high safety score + clean ORACLE + irreversible action.
        Without Rule 3, this would fall through to AUTOMATED_GUARDED —
        incorrectly allowing autonomous execution of an irreversible action.
        """
        decision = evaluate(
            diagnosis=_make_diagnosis(urgency=UrgencyLevel.LOW, time_to_critical=90),
            recovery_plan=_make_plan(
                action_name=_IRREVERSIBLE_ACTION,
                safety_score=0.80,
                is_irreversible=True,
            ),
            oracle_response=_make_oracle(
                results=[_make_action_result(action_name=_IRREVERSIBLE_ACTION, safety_score=0.80)]
            ),
        )
        assert decision.tier == DecisionTier.MANUAL_INTERLOCK, (
            f"Low-urgency irreversible action must land on MANUAL_INTERLOCK, got {decision.tier}. "
            f"This is the case that was explicitly identified as missing from the original design."
        )

    def test_medium_urgency_irreversible_triggers_manual_interlock(self):
        """MEDIUM urgency + irreversible also requires human approval via Rule 3."""
        decision = evaluate(
            diagnosis=_make_diagnosis(urgency=UrgencyLevel.MEDIUM, time_to_critical=45),
            recovery_plan=_make_plan(
                action_name=_IRREVERSIBLE_ACTION,
                safety_score=0.75,
                is_irreversible=True,
            ),
            oracle_response=_make_oracle(
                results=[_make_action_result(action_name=_IRREVERSIBLE_ACTION, safety_score=0.75)]
            ),
        )
        assert decision.tier == DecisionTier.MANUAL_INTERLOCK

    def test_rule3_rationale_mentions_irreversible(self):
        """Rationale must name the irreversibility as the reason."""
        decision = evaluate(
            diagnosis=_make_diagnosis(urgency=UrgencyLevel.LOW, time_to_critical=90),
            recovery_plan=_make_plan(is_irreversible=True),
            oracle_response=_make_oracle(),
        )
        assert "irreversible" in decision.rationale.lower(), (
            f"Rule 3 rationale should mention 'irreversible', got: {decision.rationale!r}"
        )

    def test_reversible_low_urgency_good_score_is_not_manual_interlock(self):
        """
        Confirm the complement: reversible + low urgency + good score = AUTOMATED_GUARDED.
        Ensures Rule 3 is only about irreversibility, not just about the action name.
        """
        decision = evaluate(
            diagnosis=_make_diagnosis(urgency=UrgencyLevel.LOW, time_to_critical=90),
            recovery_plan=_make_plan(
                action_name=_GOOD_ACTION,
                safety_score=0.70,
                is_irreversible=False,
            ),
            oracle_response=_make_oracle(
                results=[_make_action_result(action_name=_GOOD_ACTION, safety_score=0.70)]
            ),
        )
        assert decision.tier == DecisionTier.AUTOMATED_GUARDED


# -----------------------------------------------------------------------------
# Rule 4 — MANUAL_INTERLOCK via ORACLE unsafe flag or low score
# -----------------------------------------------------------------------------


class TestRule4ManualInterlockOracleUnsafe:
    def test_all_actions_unsafe_flag_triggers_manual_interlock(self):
        """
        LOW-URGENCY + ALL_ACTIONS_UNSAFE ? MANUAL_INTERLOCK.
        ORACLE explicitly flagged the entire action set as unsafe.
        """
        decision = evaluate(
            diagnosis=_make_diagnosis(urgency=UrgencyLevel.LOW, time_to_critical=60),
            recovery_plan=_make_plan(safety_score=0.10, is_irreversible=False),
            oracle_response=_make_oracle(
                results=[_make_action_result(safety_score=0.10)],
                response_flags=["ALL_ACTIONS_UNSAFE"],
            ),
        )
        assert decision.tier == DecisionTier.MANUAL_INTERLOCK

    def test_safety_score_below_floor_triggers_manual_interlock(self):
        """safety_score=0.19 is below the 0.20 floor ? MANUAL_INTERLOCK."""
        decision = evaluate(
            diagnosis=_make_diagnosis(urgency=UrgencyLevel.LOW, time_to_critical=60),
            recovery_plan=_make_plan(safety_score=0.19, is_irreversible=False),
            oracle_response=_make_oracle(
                results=[_make_action_result(safety_score=0.19)],
            ),
        )
        assert decision.tier == DecisionTier.MANUAL_INTERLOCK

    def test_negative_safety_score_triggers_manual_interlock(self):
        """Negative scores are clearly unsafe even without the flag."""
        decision = evaluate(
            diagnosis=_make_diagnosis(urgency=UrgencyLevel.LOW, time_to_critical=60),
            recovery_plan=_make_plan(safety_score=-0.30, is_irreversible=False),
            oracle_response=_make_oracle(
                results=[_make_action_result(safety_score=-0.30)],
            ),
        )
        assert decision.tier == DecisionTier.MANUAL_INTERLOCK

    def test_boundary_exactly_safety_floor_does_not_trigger_rule4(self):
        """
        BOUNDARY TEST — safety_score == SAFETY_SCORE_FLOOR (0.20) exactly.

        The rule is 'score < SAFETY_FLOOR'. At exactly 0.20 the action clears
        the floor and should NOT trigger MANUAL_INTERLOCK. A stray '<=' would
        silently break this boundary.
        """
        decision = evaluate(
            diagnosis=_make_diagnosis(urgency=UrgencyLevel.LOW, time_to_critical=60),
            recovery_plan=_make_plan(safety_score=SAFETY_SCORE_FLOOR, is_irreversible=False),
            oracle_response=_make_oracle(
                results=[_make_action_result(safety_score=SAFETY_SCORE_FLOOR)],
            ),
        )
        assert decision.tier != DecisionTier.MANUAL_INTERLOCK, (
            f"safety_score={SAFETY_SCORE_FLOOR} exactly at the floor must NOT trigger "
            f"MANUAL_INTERLOCK (rule is strictly <), got {decision.tier}"
        )
        assert decision.tier == DecisionTier.AUTOMATED_GUARDED

    def test_rule4a_rationale_mentions_all_actions_unsafe(self):
        decision = evaluate(
            diagnosis=_make_diagnosis(urgency=UrgencyLevel.LOW, time_to_critical=60),
            recovery_plan=_make_plan(safety_score=0.10, is_irreversible=False),
            oracle_response=_make_oracle(
                results=[_make_action_result(safety_score=0.10)],
                response_flags=["ALL_ACTIONS_UNSAFE"],
            ),
        )
        assert "ALL_ACTIONS_UNSAFE" in decision.rationale

    def test_rule4b_rationale_mentions_score_floor(self):
        decision = evaluate(
            diagnosis=_make_diagnosis(urgency=UrgencyLevel.LOW, time_to_critical=60),
            recovery_plan=_make_plan(safety_score=0.15, is_irreversible=False),
            oracle_response=_make_oracle(
                results=[_make_action_result(safety_score=0.15)],
            ),
        )
        assert "floor" in decision.rationale.lower() or str(SAFETY_SCORE_FLOOR) in decision.rationale


# -----------------------------------------------------------------------------
# Rule 5 — AUTOMATED_GUARDED (happy path)
# -----------------------------------------------------------------------------


class TestRule5AutomatedGuarded:
    def test_clean_scenario_is_automated_guarded(self):
        """All checks pass — must land on AUTOMATED_GUARDED."""
        decision = evaluate(
            diagnosis=_make_diagnosis(urgency=UrgencyLevel.LOW, time_to_critical=90),
            recovery_plan=_make_plan(
                action_name=_GOOD_ACTION,
                safety_score=0.70,
                is_irreversible=False,
            ),
            oracle_response=_make_oracle(
                results=[_make_action_result(action_name=_GOOD_ACTION, safety_score=0.70)]
            ),
        )
        assert decision.tier == DecisionTier.AUTOMATED_GUARDED

    def test_automated_guarded_auto_executes_true(self):
        decision = evaluate(
            diagnosis=_make_diagnosis(urgency=UrgencyLevel.LOW, time_to_critical=90),
            recovery_plan=_make_plan(safety_score=0.70, is_irreversible=False),
            oracle_response=_make_oracle(results=[_make_action_result(safety_score=0.70)]),
        )
        assert decision.auto_executes is True

    def test_automated_guarded_requires_human_approval_false(self):
        decision = evaluate(
            diagnosis=_make_diagnosis(urgency=UrgencyLevel.LOW, time_to_critical=90),
            recovery_plan=_make_plan(safety_score=0.70, is_irreversible=False),
            oracle_response=_make_oracle(results=[_make_action_result(safety_score=0.70)]),
        )
        assert decision.requires_human_approval is False

    def test_automated_guarded_notify_post_hoc_false(self):
        decision = evaluate(
            diagnosis=_make_diagnosis(urgency=UrgencyLevel.LOW, time_to_critical=90),
            recovery_plan=_make_plan(safety_score=0.70, is_irreversible=False),
            oracle_response=_make_oracle(results=[_make_action_result(safety_score=0.70)]),
        )
        assert decision.notify_operator_post_hoc is False

    def test_medium_urgency_reversible_good_score_is_automated_guarded(self):
        """MEDIUM urgency does not trip Rule 2; reversible + clean score = AUTOMATED_GUARDED."""
        decision = evaluate(
            diagnosis=_make_diagnosis(urgency=UrgencyLevel.MEDIUM, time_to_critical=30),
            recovery_plan=_make_plan(safety_score=0.60, is_irreversible=False),
            oracle_response=_make_oracle(results=[_make_action_result(safety_score=0.60)]),
        )
        assert decision.tier == DecisionTier.AUTOMATED_GUARDED


# -----------------------------------------------------------------------------
# Rule ordering — first-match-wins verification
# -----------------------------------------------------------------------------


class TestRuleOrdering:
    def test_rule1_beats_rule2_when_both_hold(self):
        """
        time_to_critical=3 AND urgency=CRITICAL.
        Both Rule 1 and Rule 2 conditions are true simultaneously.
        Rule 1 must win — genuine time pressure overrides all other reasoning.
        """
        decision = evaluate(
            diagnosis=_make_diagnosis(urgency=UrgencyLevel.CRITICAL, time_to_critical=3),
            recovery_plan=_make_plan(),
            oracle_response=_make_oracle(),
        )
        assert decision.tier == DecisionTier.AUTONOMOUS_SAFED, (
            f"Rule 1 (time pressure) must beat Rule 2 (urgency). "
            f"Got {decision.tier} instead of AUTONOMOUS_SAFED."
        )

    def test_rule2_beats_rule3_when_both_hold(self):
        """
        urgency=HIGH AND is_irreversible=True.
        Rule 2 fires first; Rule 3 result is the same tier but rationale differs.
        Both land on MANUAL_INTERLOCK — verify the action is still the recommended one.
        """
        decision = evaluate(
            diagnosis=_make_diagnosis(urgency=UrgencyLevel.HIGH, time_to_critical=30),
            recovery_plan=_make_plan(
                action_name=_IRREVERSIBLE_ACTION,
                safety_score=0.75,
                is_irreversible=True,
            ),
            oracle_response=_make_oracle(
                results=[_make_action_result(action_name=_IRREVERSIBLE_ACTION, safety_score=0.75)]
            ),
        )
        assert decision.tier == DecisionTier.MANUAL_INTERLOCK
        # Rule 2 rationale must mention urgency, not irreversibility
        assert "urgency" in decision.rationale.lower() or "HIGH" in decision.rationale

    def test_rule1_beats_rule3_irreversible_under_time_pressure(self):
        """
        time_to_critical=2 AND is_irreversible=True.
        Rule 1 fires, overriding even the irreversibility check.
        The safing action (reversible) is used, not the irreversible recommended action.
        """
        decision = evaluate(
            diagnosis=_make_diagnosis(urgency=UrgencyLevel.LOW, time_to_critical=2),
            recovery_plan=_make_plan(
                action_name=_IRREVERSIBLE_ACTION,
                safety_score=0.80,
                is_irreversible=True,
            ),
            oracle_response=_make_oracle(
                results=[_make_action_result(action_name=_IRREVERSIBLE_ACTION, safety_score=0.80)]
            ),
        )
        assert decision.tier == DecisionTier.AUTONOMOUS_SAFED
        assert decision.action_name == _SAFING_ACTION

    def test_rule1_beats_rule4_all_actions_unsafe_under_time_pressure(self):
        """
        time_to_critical=1 AND ALL_ACTIONS_UNSAFE flag set.
        Rule 1 still wins — time pressure overrides Oracle's unsafe flag.
        """
        decision = evaluate(
            diagnosis=_make_diagnosis(urgency=UrgencyLevel.LOW, time_to_critical=1),
            recovery_plan=_make_plan(safety_score=0.10, is_irreversible=False),
            oracle_response=_make_oracle(
                results=[_make_action_result(safety_score=0.10)],
                response_flags=["ALL_ACTIONS_UNSAFE"],
            ),
        )
        assert decision.tier == DecisionTier.AUTONOMOUS_SAFED


# -----------------------------------------------------------------------------
# Output field invariants — apply across all tiers
# -----------------------------------------------------------------------------


class TestOutputFieldInvariants:
    """These invariants must hold regardless of which rule fired."""

    def _all_decisions(self):
        """Generate one decision per tier to check invariants across all tiers."""
        # AUTONOMOUS_SAFED
        yield evaluate(
            diagnosis=_make_diagnosis(time_to_critical=2),
            recovery_plan=_make_plan(),
            oracle_response=_make_oracle(),
        )
        # MANUAL_INTERLOCK (Rule 2)
        yield evaluate(
            diagnosis=_make_diagnosis(urgency=UrgencyLevel.HIGH, time_to_critical=60),
            recovery_plan=_make_plan(),
            oracle_response=_make_oracle(),
        )
        # AUTOMATED_GUARDED
        yield evaluate(
            diagnosis=_make_diagnosis(urgency=UrgencyLevel.LOW, time_to_critical=90),
            recovery_plan=_make_plan(safety_score=0.70, is_irreversible=False),
            oracle_response=_make_oracle(results=[_make_action_result(safety_score=0.70)]),
        )

    def test_auto_executes_is_inverse_of_requires_human_approval(self):
        for d in self._all_decisions():
            assert d.auto_executes != d.requires_human_approval, (
                f"auto_executes and requires_human_approval must always be inverses, "
                f"got auto={d.auto_executes} requires_human={d.requires_human_approval} "
                f"for tier={d.tier}"
            )

    def test_notify_post_hoc_iff_autonomous_safed(self):
        for d in self._all_decisions():
            expected = d.tier == DecisionTier.AUTONOMOUS_SAFED
            assert d.notify_operator_post_hoc == expected, (
                f"notify_operator_post_hoc must be True iff tier==AUTONOMOUS_SAFED. "
                f"Got notify={d.notify_operator_post_hoc} for tier={d.tier}"
            )

    def test_rationale_is_non_empty_for_all_tiers(self):
        for d in self._all_decisions():
            assert d.rationale and len(d.rationale) >= 10, (
                f"rationale must be non-empty for tier={d.tier}"
            )

    def test_decided_at_is_timezone_aware_utc(self):
        for d in self._all_decisions():
            assert d.decided_at.tzinfo is not None, (
                f"decided_at must be timezone-aware, got {d.decided_at!r}"
            )

    def test_time_to_critical_echoed_correctly(self):
        diag = _make_diagnosis(urgency=UrgencyLevel.HIGH, time_to_critical=42)
        d = evaluate(
            diagnosis=diag,
            recovery_plan=_make_plan(),
            oracle_response=_make_oracle(),
        )
        assert d.time_to_critical_minutes == 42

    def test_urgency_echoed_as_string_value(self):
        diag = _make_diagnosis(urgency=UrgencyLevel.HIGH, time_to_critical=60)
        d = evaluate(
            diagnosis=diag,
            recovery_plan=_make_plan(),
            oracle_response=_make_oracle(),
        )
        assert d.urgency == "HIGH"
