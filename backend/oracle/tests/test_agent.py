"""
AERO-ASTRA — ORACLE Tests: Agent Logic
=======================================
Integration tests for validate_action() and rank_all_actions().

These tests call the simulator's real run_monte_carlo() — no mocking.
They verify:
  1. Single-action validation correctly wraps run_monte_carlo's real output
  2. Ranking fallback actually picks the action with the best outcome in a
     scenario where one action is clearly better than another (not just
     returning results in input order)

Empirical basis for Test 2 assertions (settled by probe run before writing):
  Scenario: eps_cascade_power_failure, severity=0.9, 10 min of degradation
  starting from nominal state (seed=0).
  Actual degraded state: SOC≈0.818, attitude_err≈0.94deg
  Results (n_runs=100, steps=300):
    - switch_redundant_power_bus: score=1.000
    - shed_nonessential_load:     score=1.000
    - reorient_max_solar:         score=1.000
    - enter_safe_low_power_mode:  score=1.000
    - thruster_isolation:         score=1.000
    - activate_backup_heater:     score=0.000  ← TCS-only, no EPS effect

  Therefore:
    - We assert activate_backup_heater ranks LAST (score meaningfully lower)
    - We do NOT assert which of the 5 EPS-affecting actions wins among themselves
      (they're statistically indistinguishable at this run count)
    - We assert best_action is NOT activate_backup_heater

n_runs=30, steps=150 used in tests (approved: Q1). If tests flake intermittently,
check whether the lower run count is colliding with a borderline scenario before
assuming a logic bug.
"""

from __future__ import annotations

import pytest

from backend.simulator import simulate_scenario
from backend.simulator.recovery import RECOVERY_CATALOG
from backend.simulator.schemas import MonteCarloResult, SatelliteState
from backend.oracle import rank_all_actions, run_oracle, validate_action
from backend.oracle.schemas import ActionResult, OracleRequest, OracleResponse


# ─────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def degraded_eps_state() -> SatelliteState:
    """
    Satellite state after 10 minutes of eps_cascade_power_failure (severity=0.9).
    Reuses the same scenario as the simulator demo (seed=0, fault_onset=0.0).
    """
    result = simulate_scenario(
        fault="eps_cascade_power_failure",
        severity=0.9,
        duration=600.0,
        dt=10.0,
        fault_onset=0.0,
        seed=0,
    )
    return result.frames[-1].state


@pytest.fixture(scope="module")
def eps_cascade_request(degraded_eps_state) -> OracleRequest:
    """OracleRequest for the eps_cascade_power_failure scenario."""
    return OracleRequest(
        current_state=degraded_eps_state,
        fault_name="eps_cascade_power_failure",
        fault_severity=0.9,
        n_runs=30,
        steps=150,
        diagnosis_context="EPS cascade power failure diagnosed by SHERLOCK. "
                          "Solar array loss affecting all downstream subsystems.",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: Single-action validation wraps run_monte_carlo correctly
# ─────────────────────────────────────────────────────────────────────────────


class TestValidateAction:
    """Test 1: validate_action correctly wraps run_monte_carlo's real output."""

    @pytest.fixture(scope="class")
    @classmethod
    def single_action_response(cls, eps_cascade_request) -> OracleResponse:
        request = eps_cascade_request.model_copy(
            update={"proposed_actions": ["switch_redundant_power_bus"]}
        )
        return validate_action(request)

    def test_response_is_oracle_response_instance(self, single_action_response):
        assert isinstance(single_action_response, OracleResponse)

    def test_mode_is_single_action(self, single_action_response):
        assert single_action_response.mode == "single_action"

    def test_results_has_exactly_one_entry(self, single_action_response):
        assert len(single_action_response.results) == 1

    def test_action_result_is_correct_type(self, single_action_response):
        result = single_action_response.results[0]
        assert isinstance(result, ActionResult)
        assert result.action_name == "switch_redundant_power_bus"

    def test_mc_result_is_simulator_type_not_redefined(self, single_action_response):
        """mc_result must be an instance of the simulator's MonteCarloResult, not a copy."""
        mc = single_action_response.results[0].mc_result
        assert isinstance(mc, MonteCarloResult)

    def test_mc_result_proposed_action_matches(self, single_action_response):
        mc = single_action_response.results[0].mc_result
        assert mc.proposed_action == "switch_redundant_power_bus"

    def test_mc_result_rates_sum_to_one(self, single_action_response):
        mc = single_action_response.results[0].mc_result
        total = mc.nominal_recovery_rate + mc.degraded_operation_rate + mc.mission_loss_rate
        assert total == pytest.approx(1.0, abs=1e-9)

    def test_mc_result_n_runs_matches_request(self, single_action_response):
        mc = single_action_response.results[0].mc_result
        assert mc.n_runs == 30

    def test_mc_result_steps_matches_request(self, single_action_response):
        mc = single_action_response.results[0].mc_result
        assert mc.steps == 150

    def test_safety_score_equals_formula(self, single_action_response):
        """safety_score must equal nominal_recovery_rate - mission_loss_rate exactly."""
        result = single_action_response.results[0]
        expected = result.mc_result.nominal_recovery_rate - result.mc_result.mission_loss_rate
        assert result.safety_score == pytest.approx(expected, abs=1e-9)

    def test_safety_score_is_in_valid_range(self, single_action_response):
        score = single_action_response.results[0].safety_score
        assert -1.0 <= score <= 1.0

    def test_flags_is_a_list(self, single_action_response):
        flags = single_action_response.results[0].flags
        assert isinstance(flags, list)

    def test_best_action_is_set(self, single_action_response):
        assert single_action_response.best_action == "switch_redundant_power_bus"

    def test_fault_name_echoed(self, single_action_response):
        assert single_action_response.fault_name == "eps_cascade_power_failure"

    def test_diagnosis_context_echoed(self, single_action_response):
        assert single_action_response.diagnosis_context is not None
        assert "SHERLOCK" in single_action_response.diagnosis_context

    def test_request_id_is_nonempty_string(self, single_action_response):
        assert isinstance(single_action_response.request_id, str)
        assert len(single_action_response.request_id) > 0

    def test_generated_at_is_positive_float(self, single_action_response):
        assert isinstance(single_action_response.generated_at, float)
        assert single_action_response.generated_at > 0.0

    def test_outcome_counts_sum_to_n_runs(self, single_action_response):
        mc = single_action_response.results[0].mc_result
        total_counts = sum(mc.outcome_counts.values())
        assert total_counts == mc.n_runs

    def test_raises_on_empty_proposed_actions(self, eps_cascade_request):
        request = eps_cascade_request.model_copy(update={"proposed_actions": []})
        with pytest.raises(ValueError, match="non-empty"):
            validate_action(request)

    def test_raises_on_none_proposed_actions(self, eps_cascade_request):
        request = eps_cascade_request.model_copy(update={"proposed_actions": None})
        with pytest.raises(ValueError):
            validate_action(request)

    def test_raises_on_unknown_action(self, eps_cascade_request):
        request = eps_cascade_request.model_copy(
            update={"proposed_actions": ["nonexistent_action"]}
        )
        with pytest.raises(ValueError):
            validate_action(request)

    def test_multiple_proposed_actions(self, eps_cascade_request):
        """validate_action handles multiple proposed actions in one call."""
        request = eps_cascade_request.model_copy(
            update={"proposed_actions": [
                "switch_redundant_power_bus",
                "shed_nonessential_load",
            ]}
        )
        response = validate_action(request)
        assert response.mode == "single_action"
        assert len(response.results) == 2
        action_names = {r.action_name for r in response.results}
        assert action_names == {"switch_redundant_power_bus", "shed_nonessential_load"}


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: Ranking fallback picks the clearly better action
# ─────────────────────────────────────────────────────────────────────────────


class TestRankAllActions:
    """
    Test 2: rank_all_actions tests all catalog actions and ranks correctly.

    Key empirical finding (from probe run at n_runs=100):
      Under eps_cascade_power_failure at severity=0.9, activate_backup_heater
      is the clear loser (score=0.000) because it targets TCS only and has
      zero modifier effect on EPS. All 5 EPS-affecting actions score 1.000.

    Assertions are structured around this provable gap:
      - activate_backup_heater is last
      - best_action is not activate_backup_heater
      - The top action scores higher than activate_backup_heater by >= 0.10
      - Results are sorted descending (not input order)
      - All 6 catalog actions are present
    """

    @pytest.fixture(scope="class")
    @classmethod
    def ranking_response(cls, eps_cascade_request) -> OracleResponse:
        return rank_all_actions(eps_cascade_request)

    def test_response_is_oracle_response_instance(self, ranking_response):
        assert isinstance(ranking_response, OracleResponse)

    def test_mode_is_ranking(self, ranking_response):
        assert ranking_response.mode == "ranking"

    def test_results_contains_all_six_catalog_actions(self, ranking_response):
        """All actions in RECOVERY_CATALOG must be tested, regardless of input order."""
        result_names = {r.action_name for r in ranking_response.results}
        catalog_names = set(RECOVERY_CATALOG.keys())
        assert result_names == catalog_names

    def test_results_has_exactly_six_entries(self, ranking_response):
        assert len(ranking_response.results) == len(RECOVERY_CATALOG)

    def test_results_sorted_descending_by_safety_score(self, ranking_response):
        """Results must be sorted by safety_score descending — not input order."""
        scores = [r.safety_score for r in ranking_response.results]
        assert scores == sorted(scores, reverse=True), (
            "Results are not sorted by safety_score descending. "
            f"Got: {list(zip([r.action_name for r in ranking_response.results], scores))}"
        )

    def test_best_action_is_results_zero_action_name(self, ranking_response):
        """best_action must point to the top-ranked result."""
        assert ranking_response.best_action == ranking_response.results[0].action_name

    def test_best_action_is_not_activate_backup_heater(self, ranking_response):
        """
        activate_backup_heater targets TCS only and has zero EPS modifier effect.
        Under an EPS cascade fault, it cannot recover the satellite.
        It must never be the best_action in this scenario.
        """
        assert ranking_response.best_action != "activate_backup_heater", (
            "activate_backup_heater should NOT be the best action under an EPS fault — "
            "it targets TCS only with zero modifier effect on EPS."
        )

    def test_activate_backup_heater_ranks_last(self, ranking_response):
        """
        activate_backup_heater must be the last-ranked action under eps_cascade_power_failure.
        Empirically confirmed: it scores 0.000 while all EPS-affecting actions score 1.000.
        """
        last = ranking_response.results[-1]
        assert last.action_name == "activate_backup_heater", (
            f"Expected activate_backup_heater last, got: {last.action_name} "
            f"(score={last.safety_score:.3f}). "
            f"Full ranking: {[(r.action_name, r.safety_score) for r in ranking_response.results]}"
        )

    def test_top_action_beats_activate_backup_heater_by_meaningful_margin(self, ranking_response):
        """
        The winner must beat activate_backup_heater by >= 0.10 safety score points.
        This confirms the ranking is signal, not noise — even at n_runs=30.
        """
        top_score = ranking_response.results[0].safety_score
        heater_result = next(
            r for r in ranking_response.results if r.action_name == "activate_backup_heater"
        )
        gap = top_score - heater_result.safety_score
        assert gap >= 0.10, (
            f"Gap between winner ({ranking_response.results[0].action_name}, "
            f"score={top_score:.3f}) and activate_backup_heater "
            f"(score={heater_result.safety_score:.3f}) is only {gap:.3f}. "
            f"Expected >= 0.10."
        )

    def test_all_results_have_rates_summing_to_one(self, ranking_response):
        for result in ranking_response.results:
            mc = result.mc_result
            total = mc.nominal_recovery_rate + mc.degraded_operation_rate + mc.mission_loss_rate
            assert total == pytest.approx(1.0, abs=1e-9), (
                f"Rates don't sum to 1.0 for {result.action_name}: {total}"
            )

    def test_all_results_have_safety_score_matching_formula(self, ranking_response):
        for result in ranking_response.results:
            expected = result.mc_result.nominal_recovery_rate - result.mc_result.mission_loss_rate
            assert result.safety_score == pytest.approx(expected, abs=1e-9), (
                f"Safety score mismatch for {result.action_name}"
            )

    def test_all_results_have_correct_n_runs(self, ranking_response):
        for result in ranking_response.results:
            assert result.mc_result.n_runs == 30

    def test_all_results_have_correct_steps(self, ranking_response):
        for result in ranking_response.results:
            assert result.mc_result.steps == 150

    def test_best_action_is_in_recovery_catalog(self, ranking_response):
        assert ranking_response.best_action in RECOVERY_CATALOG


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: run_oracle dispatcher
# ─────────────────────────────────────────────────────────────────────────────


class TestRunOracleDispatcher:
    """Verify run_oracle correctly dispatches based on proposed_actions."""

    def test_dispatches_to_ranking_when_no_proposed_actions(self, eps_cascade_request):
        """None proposed_actions → ranking mode."""
        assert eps_cascade_request.proposed_actions is None
        response = run_oracle(eps_cascade_request)
        assert response.mode == "ranking"
        assert len(response.results) == len(RECOVERY_CATALOG)

    def test_dispatches_to_validate_when_proposed_actions_given(self, eps_cascade_request):
        """Non-empty proposed_actions → single_action mode."""
        request = eps_cascade_request.model_copy(
            update={"proposed_actions": ["shed_nonessential_load"]}
        )
        response = run_oracle(request)
        assert response.mode == "single_action"
        assert len(response.results) == 1
        assert response.results[0].action_name == "shed_nonessential_load"


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: ALL_ACTIONS_UNSAFE response flag behaviour
# ─────────────────────────────────────────────────────────────────────────────


class TestAllActionsUnsafeFlag:
    """
    Verify that best_action is still set when all scores are <= 0, and
    ALL_ACTIONS_UNSAFE is added to response_flags.

    We use a perfectly safe action (switch_redundant_power_bus on a nominal
    state with no fault) to confirm the flag does NOT fire when scores are
    positive, then use a synthetic approach to verify the flag fires.

    Note: Getting all 6 catalog actions to genuinely score <= 0 in the
    real simulator requires an extremely degraded state that no recovery helps.
    We test the flag logic via the internal _build_response helper instead
    of trying to construct an adversarial scenario.
    """

    def test_flag_does_not_fire_when_best_score_is_positive(self, eps_cascade_request):
        """ALL_ACTIONS_UNSAFE must NOT appear when the best action scores > 0."""
        request = eps_cascade_request.model_copy(
            update={"proposed_actions": ["switch_redundant_power_bus"]}
        )
        response = validate_action(request)
        # switch_redundant_power_bus under eps_cascade fault scores high (positive)
        assert "ALL_ACTIONS_UNSAFE" not in response.response_flags

    def test_best_action_always_set_even_if_score_negative(self):
        """
        Even when safety_score <= 0, best_action must point to the top result.
        Tests _build_response via the internal helper indirectly through OracleResponse
        construction in a controlled way.
        """
        from backend.oracle.agent import _build_response
        from backend.oracle.schemas import OracleRequest
        from backend.simulator.schemas import (
            ADCSState, EPSState, OBCState, PropulsionState, SatelliteState,
            TCSState, TTCState, MonteCarloResult,
        )

        # Build a synthetic request (state values don't matter; _build_response
        # doesn't call the simulator)
        state = SatelliteState(
            timestamp=0.0,
            eps=EPSState(battery_soc=0.10, solar_array_current=0.0, bus_voltage=20.0, load_current=6.0),
            tcs=TCSState(panel_temp=-30.0, battery_temp=-20.0, heater_active=False, in_eclipse=True),
            adcs=ADCSState(attitude_error=95.0, reaction_wheel_speed=0.0),
            obc=OBCState(free_memory_mb=5.0, cpu_load=0.98, watchdog_trips=5),
            ttc=TTCState(signal_strength=-118.0, bit_error_rate=0.98, ground_contact_remaining=0.0),
            propulsion=PropulsionState(fuel_remaining=0.5, thruster_temp=180.0),
        )
        request = OracleRequest(current_state=state)

        # Craft ActionResults that all have negative scores
        def _neg_mc(action: str) -> MonteCarloResult:
            return MonteCarloResult(
                proposed_action=action,
                n_runs=10,
                steps=10,
                nominal_recovery_rate=0.0,
                degraded_operation_rate=0.2,
                mission_loss_rate=0.8,
                mean_final_battery_soc=0.03,
                mean_final_attitude_error=100.0,
                std_final_battery_soc=0.01,
                outcome_counts={"nominal_recovery": 0, "degraded_operation": 2, "mission_loss": 8},
            )

        results = [
            ActionResult(
                action_name=name,
                mc_result=_neg_mc(name),
                safety_score=-0.8,
                flags=["HIGH_MISSION_LOSS_RATE", "LOW_NOMINAL_RECOVERY_RATE"],
            )
            for name in ["action_a", "action_b", "action_c"]
        ]

        response = _build_response(results, mode="single_action", request=request)

        # best_action must still be set (not None) even though all scores <= 0
        assert response.best_action is not None
        assert response.best_action == response.results[0].action_name
        # ALL_ACTIONS_UNSAFE flag must be present
        assert "ALL_ACTIONS_UNSAFE" in response.response_flags
