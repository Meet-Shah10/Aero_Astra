"""
SENTINEL — Engine B: Physics-Threshold / Z-Score Fallback Detector

Why this exists: the production XGBoost model (train.py) and the Isolation
Forest baseline are both trained exclusively on `flatline_duration` /
`log_inv_std` — features that fire when a sensor's short-term variance
COLLAPSES (a stuck sensor). Every fault in backend/simulator/faults.py is a
smooth ramp/drift where variance stays normal or increases, so those models
structurally cannot flag any of the 6 demo faults (verified empirically —
see /home/mohit-rawat/aero_astra memory or the accompanying audit doc).

Engine B needs no training and no model file: it scores each subsystem
reading against the physical engineering thresholds already written down in
roadmap.md ("Real Satellite Fault Physics Rules"). A reading exactly at the
"warn" line scores 0.5; a reading at or past "mission loss" scores 1.0.

Combine with any ML engine via combined_score() — max() is deliberate:
either signal firing is enough to raise an alert.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThresholdRule:
    """One monitored parameter. `direction` is '>' (high=bad) or '<' (low=bad)."""

    param: str
    warn: float
    critical: float
    mission_loss: float
    direction: str  # ">" or "<"


# Values transcribed directly from roadmap.md's "Real Satellite Fault Physics
# Rules" table. Two-sided params (panel_temp has both a high and low failure
# mode) get two rules.
RULES: list[ThresholdRule] = [
    ThresholdRule("battery_soc", warn=0.50, critical=0.25, mission_loss=0.15, direction="<"),
    ThresholdRule("bus_voltage", warn=25.0, critical=22.0, mission_loss=18.0, direction="<"),
    ThresholdRule("panel_temp_hot", warn=55.0, critical=80.0, mission_loss=100.0, direction=">"),
    ThresholdRule("panel_temp_cold", warn=-10.0, critical=-20.0, mission_loss=-30.0, direction="<"),
    # NOTE: roadmap.md's original table (warn=35/critical=40/mission_loss=45) false-
    # positives constantly on this simulator: nominal orbital thermal cycling alone
    # swings battery_temp up to ~41.4C with zero fault active (verified empirically).
    # Recalibrated with headroom above the observed nominal envelope.
    ThresholdRule("battery_temp", warn=44.0, critical=48.0, mission_loss=52.0, direction=">"),
    ThresholdRule("attitude_error", warn=5.0, critical=15.0, mission_loss=30.0, direction=">"),
    ThresholdRule("reaction_wheel_speed", warn=5000.0, critical=6000.0, mission_loss=6000.0, direction=">"),
    ThresholdRule("signal_strength", warn=-95.0, critical=-105.0, mission_loss=-115.0, direction="<"),
    ThresholdRule("cpu_load", warn=0.70, critical=0.90, mission_loss=1.0, direction=">"),
]

# Maps a rule's `param` name to how to pull it out of a SatelliteState.
_EXTRACTORS = {
    "battery_soc": lambda s: s.eps.battery_soc,
    "bus_voltage": lambda s: s.eps.bus_voltage,
    "panel_temp_hot": lambda s: s.tcs.panel_temp,
    "panel_temp_cold": lambda s: s.tcs.panel_temp,
    "battery_temp": lambda s: s.tcs.battery_temp,
    "attitude_error": lambda s: s.adcs.attitude_error,
    "reaction_wheel_speed": lambda s: abs(s.adcs.reaction_wheel_speed),
    "signal_strength": lambda s: s.ttc.signal_strength,
    "cpu_load": lambda s: s.obc.cpu_load,
}


def _score_rule(rule: ThresholdRule, value: float) -> float:
    """
    0.0 at/inside nominal, 0.5 at `warn`, 1.0 at/beyond `mission_loss`.
    Linear interpolation in between; direction-aware.
    """
    warn, crit, loss = rule.warn, rule.critical, rule.mission_loss

    if rule.direction == "<":
        if value >= warn:
            return 0.0
        if value <= loss:
            return 1.0
        if value >= crit:
            # between warn and critical -> [0, 0.5]
            span = warn - crit
            return 0.0 if span == 0 else 0.5 * (warn - value) / span
        # between critical and mission_loss -> [0.5, 1.0]
        span = crit - loss
        return 1.0 if span == 0 else 0.5 + 0.5 * (crit - value) / span
    else:  # ">"
        if value <= warn:
            return 0.0
        if value >= loss:
            return 1.0
        if value <= crit:
            span = crit - warn
            return 0.0 if span == 0 else 0.5 * (value - warn) / span
        span = loss - crit
        return 1.0 if span == 0 else 0.5 + 0.5 * (value - crit) / span


def score_state(state) -> dict:
    """
    Score one SatelliteState against every physics rule.

    Returns {"score": float in [0,1], "breakdown": {param: score, ...},
    "worst_param": str}. `score` is the max across all rules — one crossed
    threshold is enough to flag the state as anomalous.
    """
    breakdown = {}
    for rule in RULES:
        value = _EXTRACTORS[rule.param](state)
        breakdown[rule.param] = round(_score_rule(rule, value), 4)

    worst_param = max(breakdown, key=breakdown.get)
    return {
        "score": breakdown[worst_param],
        "breakdown": breakdown,
        "worst_param": worst_param,
    }


def combined_score(ml_score: float | None, state) -> dict:
    """
    Ensemble entry point: max(ML model score, Engine B score).

    ml_score may be None (e.g. the model file failed to load) — Engine B
    alone still produces a usable anomaly score in that case, which is the
    graceful-degradation path for a teammate without the trained .pkl.
    """
    engine_b = score_state(state)
    ml = 0.0 if ml_score is None else float(ml_score)
    return {
        "score": max(ml, engine_b["score"]),
        "ml_score": ml_score,
        "engine_b_score": engine_b["score"],
        "engine_b_breakdown": engine_b["breakdown"],
        "worst_param": engine_b["worst_param"],
    }
