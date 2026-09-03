"""
AERO-ASTRA — ORACLE Safety Scoring
=====================================
Isolated safety-score computation and per-result flagging rules.

This module is intentionally small and self-contained. ATHENA will eventually
replace compute_safety_score() with a weighted formula incorporating safety,
effectiveness, and operator-effort dimensions. Keeping the logic here means
that replacement touches exactly one file and nothing else in ORACLE changes.

Flagging rules are also defined here: they are independent of scoring and
produce human-readable warning strings that GUARDIAN and SCRIBE can act on.
"""

from __future__ import annotations

from backend.simulator.schemas import MonteCarloResult


# ─────────────────────────────────────────────────────────────────────────────
# Safety score
# ─────────────────────────────────────────────────────────────────────────────

# Threshold below which best_action is still returned but response_flags will
# include ALL_ACTIONS_UNSAFE. Defined here so it travels with the formula.
SAFE_SCORE_THRESHOLD: float = 0.0


def compute_safety_score(mc_result: MonteCarloResult) -> float:
    """
    Compute ORACLE's safety score for one recovery action.

    Formula (placeholder — ATHENA will replace with weighted formula):
        safety_score = nominal_recovery_rate - mission_loss_rate

    Range: [-1.0, +1.0]. Higher is safer.
        +1.0  → perfect nominal recovery, zero mission loss
         0.0  → nominal recovery equals mission loss probability
        -1.0  → total mission loss, zero nominal recovery

    This formula is deliberately simple: GUARDIAN needs a single scalar to
    threshold against, and nominal_recovery_rate - mission_loss_rate captures
    the core safety signal without requiring any tuning parameters.

    Args:
        mc_result: MonteCarloResult from the simulator for this action.

    Returns:
        float in [-1.0, +1.0].
    """
    return mc_result.nominal_recovery_rate - mc_result.mission_loss_rate


# ─────────────────────────────────────────────────────────────────────────────
# Flagging rules
# ─────────────────────────────────────────────────────────────────────────────

# Each rule is a (condition_callable, flag_string) pair.
# condition_callable receives a MonteCarloResult and returns True if the flag fires.
# Add new rules here without touching agent.py.

_FLAG_RULES: list[tuple[object, str]] = [
    (lambda r: r.mission_loss_rate > 0.25,        "HIGH_MISSION_LOSS_RATE"),
    (lambda r: r.nominal_recovery_rate < 0.30,    "LOW_NOMINAL_RECOVERY_RATE"),
    (lambda r: r.std_final_battery_soc > 0.20,    "HIGH_SOC_VARIANCE"),
]


def compute_flags(mc_result: MonteCarloResult) -> list[str]:
    """
    Evaluate all flagging rules against a MonteCarloResult.

    Returns a list of flag strings for any rules that fired. Empty list
    means no warnings.

    Args:
        mc_result: MonteCarloResult from the simulator for this action.

    Returns:
        List of flag strings (may be empty).
    """
    return [flag for condition, flag in _FLAG_RULES if condition(mc_result)]


# ─────────────────────────────────────────────────────────────────────────────
# Sort key for ranking
# ─────────────────────────────────────────────────────────────────────────────


def ranking_sort_key(action_result: object) -> tuple[float, float, float, float]:
    """
    Sort key for ordering ActionResult objects. Four-level, fully deterministic.

    Primary:    safety_score descending          (higher is better -> negate)
    Secondary:  mission_loss_rate ascending       (lower is better)
    Tertiary:   std_final_battery_soc ascending   (lower variance -> more predictable)
    Quaternary: nominal_recovery_rate descending  (higher is better -> negate)

    Rationale for tertiary being std_final_battery_soc:
    The probe run showed that under many fault scenarios, five of six actions
    tie perfectly on primary (score=1.0), secondary (loss=0.0), and quaternary
    (nominal=1.0). Without a real tertiary, Python's stable sort falls back to
    the original iteration order of RECOVERY_CATALOG — making 'best_action' an
    accident of dictionary ordering rather than a real decision. Preferring
    lower outcome variance is a defensible engineering criterion: a recovery
    action whose results are more predictable is genuinely safer to recommend,
    even if its expected value is the same. Cheap to compute, removes the
    dict-order dependency entirely.

    Args:
        action_result: An ActionResult instance (typed as object to avoid
                       circular import; duck-typing is fine here).

    Returns:
        4-tuple suitable for use as a sort key (ascending sort gives descending
        safety score order with the tiebreaks applied in sequence).
    """
    return (
        -action_result.safety_score,
        action_result.mc_result.mission_loss_rate,
        action_result.mc_result.std_final_battery_soc,   # lower variance preferred
        -action_result.mc_result.nominal_recovery_rate,
    )
