"""
AERO-ASTRA — ATHENA Blended Ranking & Irreversibility Lookup
=============================================================
Isolated scoring logic — same discipline as oracle/scoring.py.

This module is intentionally small and self-contained so that tuning the
blended formula or the irreversibility list touches exactly one file and
nothing else in ATHENA changes.

BLENDED RANK FORMULA (explicit placeholder — may need refinement):
    rank = (safety_score * 0.50)
         + (effectiveness_score * 0.35)
         + ((1 / operator_effort_numeric) * 0.15)

    where effort_numeric: low=1, medium=2, high=3
    (lower effort scores higher — a fast, simple fix is preferable
    when safety and effectiveness are equal)

INPUT CLAMPING:
    safety_score and effectiveness_score are clamped to [0, 1] before
    computation. ORACLE's safety_score can be negative (range [-1, +1])
    when mission_loss_rate > nominal_recovery_rate. Without clamping,
    a dangerous action with negative safety could still receive a positive
    blended rank due to high effectiveness and low effort. The clamp
    ensures negative-safety actions never score above 0.35 + 0.15 = 0.50
    even under the most favourable effort/effectiveness combination,
    while a genuinely safe action (safety=1.0) scores at least 0.50.

IRREVERSIBLE ACTIONS:
    Hardcoded frozenset. GUARDIAN and ATHENA's RecoveryOption.is_irreversible
    are derived from this lookup — never from LLM output.
"""

from __future__ import annotations

# ─────────────────────────────────────────────────────────────────────────────
# Irreversibility lookup — deterministic, never LLM-decided
# ─────────────────────────────────────────────────────────────────────────────

IRREVERSIBLE_ACTIONS: frozenset[str] = frozenset({
    # Switches hardware path: restoring the original bus requires a further ground command
    "switch_redundant_power_bus",
    # Closes propellant isolation valves: reopening risks propellant surge / attitude kick
    "thruster_isolation",
})


def is_action_irreversible(action_name: str) -> bool:
    """
    Return True if executing action_name cannot be undone without a
    subsequent ground intervention command.

    Used by ATHENA to populate RecoveryOption.is_irreversible and by
    GUARDIAN to gate whether human operator approval is required before
    execution. Never delegated to the LLM.
    """
    return action_name in IRREVERSIBLE_ACTIONS


# ─────────────────────────────────────────────────────────────────────────────
# Blended ranking formula
# ─────────────────────────────────────────────────────────────────────────────

# Maps OperatorEffort string values to numeric denominators.
# Lower numeric → higher contribution to rank (easier = preferred at equal safety).
EFFORT_NUMERIC: dict[str, int] = {
    "low":    1,
    "medium": 2,
    "high":   3,
}


def blended_rank(
    safety_score: float,
    effectiveness_score: float,
    operator_effort: str,
) -> float:
    """
    Compute ATHENA's blended ranking score for one recovery option.

    Formula:
        rank = (safety * 0.50) + (effectiveness * 0.35) + ((1 / effort_n) * 0.15)

    Args:
        safety_score:        ORACLE's safety score for this action. Range [-1, +1].
                             Clamped to [0, 1] before use — see module docstring.
        effectiveness_score: LLM-judged functional recovery quality. Range [0, 1].
                             Clamped defensively.
        operator_effort:     "low" | "medium" | "high". Unknown values default to
                             "medium" (effort_n=2) rather than raising, to avoid
                             retries caused by trivial casing issues.

    Returns:
        float in approximately [0.05, 1.0], rounded to 4 decimal places.
        Higher is better. Negative-safety actions are bounded above by 0.50.
    """
    # Clamp inputs — safety can be negative from ORACLE's [-1,+1] range
    s = max(0.0, min(1.0, safety_score))
    e = max(0.0, min(1.0, effectiveness_score))
    effort_n = EFFORT_NUMERIC.get(operator_effort.lower(), 2)

    return round(
        (s * 0.50) + (e * 0.35) + ((1.0 / effort_n) * 0.15),
        4,
    )
