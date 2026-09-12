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

# Threshold below which best_action is still returned but response_flags will
# include ALL_ACTIONS_UNSAFE. Calibrated to the new multi-factor formula whose
# max score is ~0.55 — a score ≤ 0.10 means even SOC recovery is very poor.
SAFE_SCORE_THRESHOLD: float = 0.10

# Theoretical min/max of compute_safety_score() with the fault-affinity component.
# Min: soc=0, affinity=-0.3 (conflicting action), all penalties max
#      → -(0.25*0.3 + 0.10 + 0.05 + 0.20) = -(0.075+0.35) ≈ -0.43
# Max: soc=1, affinity=1.0, all penalties=0  → 0.40 + 0.25 = 0.65
SCORE_MIN: float = -0.43
SCORE_MAX: float =  0.65


def safety_score_to_probability(score: float) -> float:
    """
    Normalise a safety_score to a [0, 1] success probability.

    Uses the theoretical min/max of compute_safety_score() so the mapping
    is anchored to the formula's actual range rather than observed data.

    Args:
        score: Output of compute_safety_score().

    Returns:
        float in [0.0, 1.0].
    """
    prob = (score - SCORE_MIN) / (SCORE_MAX - SCORE_MIN)
    return round(max(0.0, min(1.0, prob)), 4)



# ─────────────────────────────────────────────────────────────────────────────
# Safety score calibration constants
# ─────────────────────────────────────────────────────────────────────────────

# SOC scoring: score is 1.0 at this SOC or above, linearly falls to 0.0 at the
# loss threshold (5%). Actions that raise SOC get rewarded proportionally.
_SOC_FULL: float = 0.80       # SOC at which full score is awarded
_SOC_LOSS: float = 0.05       # SOC at which score becomes 0.0

# Variance penalty: high outcome variance = less reliable action.
_STD_SOC_OK: float = 0.05
_STD_SOC_MAX: float = 0.25

# Attitude-error penalty
_ATTITUDE_OK: float = 5.0
_ATTITUDE_SEVERE: float = 45.0

# Weights — must sum to 1.0
_W_SOC: float      = 0.40     # primary: battery health
_W_AFFINITY: float = 0.25     # fault-action relevance (new)
_W_VARIANCE: float = 0.10     # outcome consistency
_W_ATTITUDE: float = 0.05     # pointing quality
_W_LOSS: float     = 0.20     # hard mission-loss penalty


# ─────────────────────────────────────────────────────────────────────────────
# Fault-action affinity table
# ─────────────────────────────────────────────────────────────────────────────
#
# Encodes the domain knowledge: "which action directly addresses which fault?"
# Score is in [0.0, 1.0]:
#   1.0 = action is the primary/dedicated fix for this fault
#   0.7 = action provides significant relief for this fault
#   0.4 = action provides partial/indirect relief
#   0.0 = action is neutral or irrelevant
#  -0.3 = action may conflict with or worsen this fault
#
# Derived from the fault catalog's target_subsystem + cascade_targets
# and the recovery catalog's target_subsystems. Any fault/action pair not
# listed defaults to 0.2 (generic partial relief — all actions buy some time).
#
# Each row is: fault_name → { action_name: affinity_score }
# ─────────────────────────────────────────────────────────────────────────────

_FAULT_ACTION_AFFINITY: dict[str, dict[str, float]] = {
    # ── EPS faults ───────────────────────────────────────────────────────────
    "eps_battery_degradation": {
        "switch_redundant_power_bus":      1.0,   # primary: restores full battery capacity
        "shed_nonessential_load":          0.8,   # strong relief: reduces drain rate
        "enter_safe_low_power_mode":       0.7,   # good: cuts CPU + load
        "reorient_maximum_solar_exposure": 0.6,   # helps: maximises solar input
        "activate_backup_heater":          0.0,   # unrelated to EPS fault
        "thruster_isolation":              0.0,   # unrelated to EPS fault
    },
    "eps_cascade_power_failure": {
        "shed_nonessential_load":          1.0,   # primary: buys critical battery time
        "switch_redundant_power_bus":      0.9,   # close second: restores bus
        "enter_safe_low_power_mode":       0.8,   # very effective: minimal draw
        "reorient_maximum_solar_exposure": 0.6,   # helps if array still partially alive
        "activate_backup_heater":         -0.2,   # bad: adds load during power crisis
        "thruster_isolation":              0.2,   # minor: saves prop valve power
    },
    # ── TCS faults ───────────────────────────────────────────────────────────
    "tcs_thermal_runaway": {
        "activate_backup_heater":          1.0,   # primary: directly counteracts thermal fault
        "shed_nonessential_load":          0.6,   # helpful: reduces heat-generating loads
        "enter_safe_low_power_mode":       0.5,   # helps: reduces CPU/board heat
        "reorient_maximum_solar_exposure": 0.2,   # minor thermal relief from pointing
        "switch_redundant_power_bus":      0.1,   # barely relevant
        "thruster_isolation":              0.3,   # stops propulsion heat contribution
    },
    # ── ADCS faults ──────────────────────────────────────────────────────────
    "adcs_reaction_wheel_degradation": {
        "reorient_maximum_solar_exposure": 1.0,   # primary: directly commands ADCS repoint
        "enter_safe_low_power_mode":       0.5,   # helps OBC stabilise command flow
        "shed_nonessential_load":          0.4,   # minor: buys time via SOC
        "switch_redundant_power_bus":      0.3,   # keeps power to ADCS wheels
        "activate_backup_heater":          0.1,   # unrelated
        "thruster_isolation":              0.2,   # minor disturbance reduction
    },
    "adcs_sensor_fusion_failure": {
        "enter_safe_low_power_mode":       1.0,   # primary: halts OBC processes causing bad commands
        "reorient_maximum_solar_exposure": 0.7,   # repoints to break the bad sensor loop
        "shed_nonessential_load":          0.3,   # minor
        "switch_redundant_power_bus":      0.2,
        "activate_backup_heater":          0.0,
        "thruster_isolation":              0.3,   # stops disturbance torque
    },
    # ── Propulsion faults ────────────────────────────────────────────────────
    "propulsion_thruster_fault": {
        "thruster_isolation":              1.0,   # primary: closes isolation valves immediately
        "enter_safe_low_power_mode":       0.4,   # stabilises OBC for recovery
        "reorient_maximum_solar_exposure": 0.3,   # helps ADCS recover attitude
        "shed_nonessential_load":          0.2,
        "switch_redundant_power_bus":      0.1,
        "activate_backup_heater":          0.2,   # counters prop thermal spike
    },
    # ── TT&C faults ──────────────────────────────────────────────────────────
    "ttc_signal_dropout": {
        "enter_safe_low_power_mode":       0.8,   # OBC autonomy / beacon mode
        "reorient_maximum_solar_exposure": 0.7,   # attitude fix can restore antenna pointing
        "shed_nonessential_load":          0.5,   # reduces RF interference
        "switch_redundant_power_bus":      0.4,
        "activate_backup_heater":          0.1,
        "thruster_isolation":              0.1,
    },
}

# Default affinity for any (fault, action) pair not in the table
_DEFAULT_AFFINITY: float = 0.2


def _fault_action_affinity(fault_name: str | None, action_name: str) -> float:
    """
    Return the affinity score for an (fault, action) pair.

    Returns _DEFAULT_AFFINITY for unknown combinations (0.2 = generic partial relief).
    Returns 0.3 if fault_name is None (no active fault — no targeting bonus awarded).
    """
    if fault_name is None:
        return 0.3   # no fault → moderate generic baseline
    return _FAULT_ACTION_AFFINITY.get(fault_name, {}).get(action_name, _DEFAULT_AFFINITY)


def compute_safety_score(
    mc_result: MonteCarloResult,
    fault_name: str | None = None,
    action_name: str | None = None,
) -> float:
    """
    Compute ORACLE's safety score for one recovery action.

    Multi-factor formula that is fault-aware: actions that directly target the
    failing subsystem receive an affinity bonus, ensuring the ranking reflects
    engineering domain knowledge and not just battery-SOC maximisation.

    Components:
      soc_score        (0–1): Mean final battery SOC (normalised).
      affinity_bonus   (-0.3–1.0): Fault-action relevance from domain table.
      variance_penalty (0–1): Penalises high SOC outcome variance.
      attitude_penalty (0–1): Penalises large mean attitude error.
      loss_penalty     (0–1): Direct penalty for mission_loss_rate.

    Weights: SOC=0.40, Affinity=0.25, Variance=0.10, Attitude=0.05, Loss=0.20

    Range: approximately [-0.50, +0.65] (affinity extends both ends).

    Args:
        mc_result:   MonteCarloResult from the simulator for this action.
        fault_name:  Active fault name (from FAULT_CATALOG). None = no fault.
        action_name: Recovery action name (from RECOVERY_CATALOG).

    Returns:
        float (higher is safer/more appropriate).
    """
    # --- Component 1: SOC score ---
    soc = mc_result.mean_final_battery_soc
    soc_score = max(0.0, min(1.0, (soc - _SOC_LOSS) / (_SOC_FULL - _SOC_LOSS)))

    # --- Component 2: Fault-action affinity ---
    affinity = _fault_action_affinity(fault_name, action_name or "")

    # --- Component 3: Variance penalty ---
    std = mc_result.std_final_battery_soc
    variance_penalty = max(0.0, min(1.0, (std - _STD_SOC_OK) / (_STD_SOC_MAX - _STD_SOC_OK)))

    # --- Component 4: Attitude-error penalty ---
    att_err = mc_result.mean_final_attitude_error
    attitude_penalty = max(0.0, min(1.0,
        (att_err - _ATTITUDE_OK) / (_ATTITUDE_SEVERE - _ATTITUDE_OK)
    ))

    # --- Component 5: Hard mission-loss penalty ---
    loss_penalty = mc_result.mission_loss_rate

    score = (
        _W_SOC      * soc_score
        + _W_AFFINITY * affinity
        - _W_VARIANCE * variance_penalty
        - _W_ATTITUDE * attitude_penalty
        - _W_LOSS     * loss_penalty
    )
    return round(score, 4)


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
