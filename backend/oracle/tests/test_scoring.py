"""
AERO-ASTRA — ORACLE Tests: Safety Scoring
==========================================
Unit tests for compute_safety_score() and compute_flags() in scoring.py.

These tests use synthetic MonteCarloResult objects — no simulator calls needed.
They verify:
  - The safety score formula is arithmetically correct
  - All three flagging rules fire and clear at their boundary values
  - The ranking sort key produces deterministic tiebreak ordering
"""

from __future__ import annotations

import pytest

from backend.simulator.schemas import MonteCarloResult
from backend.oracle.scoring import (
    SAFE_SCORE_THRESHOLD,
    compute_flags,
    compute_safety_score,
    ranking_sort_key,
)
from backend.oracle.schemas import ActionResult


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_mc(
    nominal: float = 0.7,
    degraded: float = 0.2,
    loss: float = 0.1,
    mean_soc: float = 0.6,
    std_soc: float = 0.05,
    mean_att: float = 5.0,
    action: str = "switch_redundant_power_bus",
) -> MonteCarloResult:
    """Create a synthetic MonteCarloResult for testing. Rates must sum to 1.0."""
    assert abs(nominal + degraded + loss - 1.0) < 1e-9, "Rates must sum to 1.0"
    return MonteCarloResult(
        proposed_action=action,
        n_runs=100,
        steps=300,
        nominal_recovery_rate=nominal,
        degraded_operation_rate=degraded,
        mission_loss_rate=loss,
        mean_final_battery_soc=mean_soc,
        mean_final_attitude_error=mean_att,
        std_final_battery_soc=std_soc,
        outcome_counts={
            "nominal_recovery": int(nominal * 100),
            "degraded_operation": int(degraded * 100),
            "mission_loss": int(loss * 100),
        },
    )


def _make_action_result(
    safety_score: float,
    loss: float = 0.1,
    nominal: float = 0.7,
    std_soc: float = 0.05,
) -> ActionResult:
    mc = _make_mc(nominal=nominal, degraded=1.0 - nominal - loss, loss=loss, std_soc=std_soc)
    return ActionResult(
        action_name="test_action",
        mc_result=mc,
        safety_score=safety_score,
        flags=[],
    )


# ─────────────────────────────────────────────────────────────────────────────
# compute_safety_score
# ─────────────────────────────────────────────────────────────────────────────


class TestComputeSafetyScore:
    def test_formula_is_nominal_minus_loss(self):
        """Score must equal nominal_recovery_rate - mission_loss_rate exactly."""
        mc = _make_mc(nominal=0.80, degraded=0.15, loss=0.05)
        assert compute_safety_score(mc) == pytest.approx(0.80 - 0.05)

    def test_perfect_recovery_gives_plus_one(self):
        mc = _make_mc(nominal=1.0, degraded=0.0, loss=0.0)
        assert compute_safety_score(mc) == pytest.approx(1.0)

    def test_total_loss_gives_minus_one(self):
        mc = _make_mc(nominal=0.0, degraded=0.0, loss=1.0)
        assert compute_safety_score(mc) == pytest.approx(-1.0)

    def test_equal_nominal_and_loss_gives_zero(self):
        mc = _make_mc(nominal=0.4, degraded=0.2, loss=0.4)
        assert compute_safety_score(mc) == pytest.approx(0.0)

    def test_score_is_symmetric(self):
        """Swapping nominal and loss should negate the score."""
        mc_good = _make_mc(nominal=0.7, degraded=0.1, loss=0.2)
        mc_bad = _make_mc(nominal=0.2, degraded=0.1, loss=0.7)
        assert compute_safety_score(mc_good) == pytest.approx(-compute_safety_score(mc_bad))

    def test_score_is_independent_of_degraded_operation_rate(self):
        """
        Two MCs with different degraded_operation_rate but the same
        (nominal - loss) produce the same score. degraded = 1 - nominal - loss
        is uniquely determined, so we show this by picking two triples where
        nominal - loss is equal but degraded differs.

        mc_c: nominal=0.70, degraded=0.10, loss=0.20  -> score=0.50
        mc_d: nominal=0.60, degraded=0.30, loss=0.10  -> score=0.50
        degraded is 0.10 vs 0.30, but score is identical.
        """
        mc_c = _make_mc(nominal=0.70, degraded=0.10, loss=0.20)
        mc_d = _make_mc(nominal=0.60, degraded=0.30, loss=0.10)
        assert compute_safety_score(mc_c) == pytest.approx(compute_safety_score(mc_d))
        assert compute_safety_score(mc_c) == pytest.approx(0.50)

    def test_return_type_is_float(self):
        mc = _make_mc()
        result = compute_safety_score(mc)
        assert isinstance(result, float)


# ─────────────────────────────────────────────────────────────────────────────
# compute_flags
# ─────────────────────────────────────────────────────────────────────────────


class TestComputeFlags:
    def test_no_flags_on_clean_result(self):
        mc = _make_mc(nominal=0.80, degraded=0.15, loss=0.05, std_soc=0.05)
        assert compute_flags(mc) == []

    # HIGH_MISSION_LOSS_RATE — threshold 0.25
    def test_high_mission_loss_fires_above_threshold(self):
        mc = _make_mc(nominal=0.4, degraded=0.34, loss=0.26)  # loss=0.26 > 0.25
        flags = compute_flags(mc)
        assert "HIGH_MISSION_LOSS_RATE" in flags

    def test_high_mission_loss_does_not_fire_at_threshold(self):
        mc = _make_mc(nominal=0.5, degraded=0.25, loss=0.25)  # loss=0.25, not > 0.25
        flags = compute_flags(mc)
        assert "HIGH_MISSION_LOSS_RATE" not in flags

    def test_high_mission_loss_does_not_fire_below_threshold(self):
        mc = _make_mc(nominal=0.75, degraded=0.20, loss=0.05)
        assert "HIGH_MISSION_LOSS_RATE" not in compute_flags(mc)

    # LOW_NOMINAL_RECOVERY_RATE — threshold 0.30
    def test_low_nominal_fires_below_threshold(self):
        mc = _make_mc(nominal=0.29, degraded=0.41, loss=0.30)  # nominal=0.29 < 0.30
        flags = compute_flags(mc)
        assert "LOW_NOMINAL_RECOVERY_RATE" in flags

    def test_low_nominal_does_not_fire_at_threshold(self):
        mc = _make_mc(nominal=0.30, degraded=0.50, loss=0.20)  # nominal=0.30, not < 0.30
        flags = compute_flags(mc)
        assert "LOW_NOMINAL_RECOVERY_RATE" not in flags

    def test_low_nominal_does_not_fire_above_threshold(self):
        mc = _make_mc(nominal=0.60, degraded=0.30, loss=0.10)
        assert "LOW_NOMINAL_RECOVERY_RATE" not in compute_flags(mc)

    # HIGH_SOC_VARIANCE — threshold 0.20
    def test_high_soc_variance_fires_above_threshold(self):
        mc = _make_mc(std_soc=0.21)
        flags = compute_flags(mc)
        assert "HIGH_SOC_VARIANCE" in flags

    def test_high_soc_variance_does_not_fire_at_threshold(self):
        mc = _make_mc(std_soc=0.20)
        flags = compute_flags(mc)
        assert "HIGH_SOC_VARIANCE" not in flags

    def test_high_soc_variance_does_not_fire_below_threshold(self):
        mc = _make_mc(std_soc=0.10)
        assert "HIGH_SOC_VARIANCE" not in compute_flags(mc)

    def test_multiple_flags_can_fire_simultaneously(self):
        mc = _make_mc(nominal=0.10, degraded=0.59, loss=0.31, std_soc=0.25)
        flags = compute_flags(mc)
        assert "HIGH_MISSION_LOSS_RATE" in flags
        assert "LOW_NOMINAL_RECOVERY_RATE" in flags
        assert "HIGH_SOC_VARIANCE" in flags


# ─────────────────────────────────────────────────────────────────────────────
# ranking_sort_key
# ─────────────────────────────────────────────────────────────────────────────


class TestRankingSortKey:
    def test_higher_safety_score_sorts_first(self):
        a = _make_action_result(safety_score=0.8, loss=0.1, nominal=0.7)  # degraded=0.2
        b = _make_action_result(safety_score=0.3, loss=0.1, nominal=0.4)  # degraded=0.5
        assert ranking_sort_key(a) < ranking_sort_key(b)  # a should come first

    def test_tiebreak_lower_loss_sorts_first(self):
        """Secondary: when scores tie, lower mission_loss_rate wins."""
        # a: nominal=0.6, loss=0.1, degraded=0.3  -> score=0.5
        # b: nominal=0.7, loss=0.2, degraded=0.1  -> score=0.5  (same score, higher loss)
        a = _make_action_result(safety_score=0.5, loss=0.1, nominal=0.6)  # degraded=0.3
        b = _make_action_result(safety_score=0.5, loss=0.2, nominal=0.7)  # degraded=0.1
        # a has loss=0.1, b has loss=0.2 -> a should sort first
        assert ranking_sort_key(a) < ranking_sort_key(b)

    def test_tiebreak_lower_std_soc_sorts_first_when_score_and_loss_equal(self):
        """
        Tertiary (new): when score and loss tie, lower std_final_battery_soc wins.

        This is the level that matters most in practice: the probe run showed
        that five of six actions can tie on score=1.0 and loss=0.0 simultaneously.
        Without this tiebreak, ranking fell back silently to RECOVERY_CATALOG
        insertion order. Lower SOC variance = more predictable outcome = safer.
        """
        # Both: score=0.4, loss=0.1, nominal=0.5 -- identical on primary and secondary.
        # a has std_soc=0.05 (more predictable), b has std_soc=0.20 (noisier).
        a = _make_action_result(safety_score=0.4, loss=0.1, nominal=0.5, std_soc=0.05)
        b = _make_action_result(safety_score=0.4, loss=0.1, nominal=0.5, std_soc=0.20)
        # a should sort first (lower variance)
        assert ranking_sort_key(a) < ranking_sort_key(b)

    def test_tiebreak_higher_nominal_sorts_first_when_score_loss_and_std_equal(self):
        """Quaternary: when score, loss, and std_soc all tie, higher nominal wins."""
        a = _make_action_result(safety_score=0.4, loss=0.1, nominal=0.5, std_soc=0.05)
        b = _make_action_result(safety_score=0.4, loss=0.1, nominal=0.4, std_soc=0.05)
        # a: nominal=0.5, b: nominal=0.4 -> a should sort first
        assert ranking_sort_key(a) < ranking_sort_key(b)

    def test_sorting_list_by_key_produces_descending_score_order(self):
        items = [
            _make_action_result(safety_score=0.1),
            _make_action_result(safety_score=0.9),
            _make_action_result(safety_score=0.5),
        ]
        sorted_items = sorted(items, key=ranking_sort_key)
        scores = [r.safety_score for r in sorted_items]
        assert scores == sorted(scores, reverse=True)

    def test_sort_key_is_four_tuple(self):
        """Return value must be a 4-tuple -- confirms no silent fallback to 3-tuple."""
        a = _make_action_result(safety_score=0.5)
        key = ranking_sort_key(a)
        assert len(key) == 4
