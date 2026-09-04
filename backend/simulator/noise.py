"""
AERO-ASTRA Physics Simulator — Gaussian Noise Injection

Adds calibrated per-field Gaussian noise to a SatelliteState.

The rng argument is a numpy.random.Generator seeded independently per
simulation run. This is the mechanism that makes repeated Monte Carlo
runs of the same scenario produce varying — but statistically sensible —
outcomes rather than identical results every time.

Noise scales are tuned so nominal telemetry looks like real spacecraft data:
small but visible variation, not flatlines (which SENTINEL is specifically
trained to detect as anomalies).
"""

from __future__ import annotations

import numpy as np

from .schemas import (
    ADCSState,
    EPSState,
    OBCState,
    PropulsionState,
    SatelliteState,
    TCSState,
    TTCState,
)

# ─────────────────────────────────────────────────────────────────────────────
# Per-field noise standard deviations (1σ per time step)
# ─────────────────────────────────────────────────────────────────────────────
# Scaled so that over a dt=10s step the noise is physically plausible.
# Watchdog trips is int — no noise applied (discrete events only).

_EPS_NOISE = {
    "battery_soc": 0.004,  # Increased to create spread in Monte Carlo demo
    "solar_array_current": 0.04,
    "bus_voltage": 0.015,
    "load_current": 0.03,
}

_TCS_NOISE = {
    "panel_temp": 0.15,
    "battery_temp": 0.05,
}

_ADCS_NOISE = {
    "attitude_error": 0.2,  # Increased for demo variation
    "reaction_wheel_speed": 2.0,
}

_OBC_NOISE = {
    "free_memory_mb": 0.05,
    "cpu_load": 0.008,
}

_TTC_NOISE = {
    "signal_strength": 0.4,
}

_PROP_NOISE = {
    "thruster_temp": 0.08,
}


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def apply_noise(state: SatelliteState, rng: np.random.Generator) -> SatelliteState:
    """
    Return a new SatelliteState with small Gaussian noise added to
    continuous-valued fields. Boolean and integer fields are not modified.

    Args:
        state: The deterministic simulator state before noise.
        rng:   A numpy Generator (seeded per-run for MC independence).

    Returns:
        A new SatelliteState with noisy field values, all clamped to
        their valid ranges.
    """
    n = rng.standard_normal

    eps = EPSState(
        battery_soc=_clamp(state.eps.battery_soc + n() * _EPS_NOISE["battery_soc"], 0.0, 1.0),
        solar_array_current=max(0.0, state.eps.solar_array_current + n() * _EPS_NOISE["solar_array_current"]),
        bus_voltage=_clamp(state.eps.bus_voltage + n() * _EPS_NOISE["bus_voltage"], 0.0, 36.0),
        load_current=max(0.0, state.eps.load_current + n() * _EPS_NOISE["load_current"]),
    )

    tcs = TCSState(
        panel_temp=_clamp(state.tcs.panel_temp + n() * _TCS_NOISE["panel_temp"], -50.0, 150.0),
        battery_temp=_clamp(state.tcs.battery_temp + n() * _TCS_NOISE["battery_temp"], -50.0, 100.0),
        heater_active=state.tcs.heater_active,  # boolean — no noise
        in_eclipse=state.tcs.in_eclipse,         # boolean — no noise
    )

    adcs = ADCSState(
        attitude_error=_clamp(state.adcs.attitude_error + abs(n()) * _ADCS_NOISE["attitude_error"], 0.0, 180.0),
        reaction_wheel_speed=_clamp(
            state.adcs.reaction_wheel_speed + n() * _ADCS_NOISE["reaction_wheel_speed"],
            -6000.0, 6000.0,
        ),
    )

    obc = OBCState(
        free_memory_mb=_clamp(state.obc.free_memory_mb + n() * _OBC_NOISE["free_memory_mb"], 0.0, 512.0),
        cpu_load=_clamp(state.obc.cpu_load + n() * _OBC_NOISE["cpu_load"], 0.0, 1.0),
        watchdog_trips=state.obc.watchdog_trips,  # int discrete event — no noise
    )

    ttc = TTCState(
        signal_strength=_clamp(
            state.ttc.signal_strength + n() * _TTC_NOISE["signal_strength"],
            -120.0, -60.0,
        ),
        bit_error_rate=state.ttc.bit_error_rate,        # derived from signal, not noised independently
        ground_contact_remaining=state.ttc.ground_contact_remaining,  # orbit-clock-driven
    )

    prop = PropulsionState(
        fuel_remaining=max(0.0, state.propulsion.fuel_remaining),  # no noise on fuel mass
        thruster_temp=_clamp(
            state.propulsion.thruster_temp + n() * _PROP_NOISE["thruster_temp"],
            -20.0, 200.0,
        ),
    )

    return SatelliteState(
        timestamp=state.timestamp,
        eps=eps,
        tcs=tcs,
        adcs=adcs,
        obc=obc,
        ttc=ttc,
        propulsion=prop,
        active_fault=state.active_fault,
        fault_severity=state.fault_severity,
    )
