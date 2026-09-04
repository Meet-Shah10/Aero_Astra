"""
AERO-ASTRA Physics Simulator — Per-Subsystem Transition Functions

Each step_<subsystem>() function computes the next state for one subsystem
given:
    state        - current SatelliteState
    dt           - time step in seconds
    orbit        - OrbitClock (provides sunlight_factor, ground contact)
    fault_mods   - subsystem-specific modifier dict from the active fault
    recovery_mods - subsystem-specific modifier dict from the active recovery action
    rng          - numpy Generator (unused here; noise is applied in engine after)
    counters     - InternalCounters (mutable; holds watchdog accumulator state)

All transition functions return the new subsystem state object (not the full
SatelliteState — the engine assembles the full state from the 6 pieces).

Design notes:
    - No external physics/orbital-mechanics libraries. Pure arithmetic.
    - Fault and recovery modifiers are applied at computation time, not by
      directly overwriting state. This lets faults play out realistically
      over time rather than jumping instantly.
    - ADCS uses proportional feedback (not constant correction) so nominal
      attitude hovers at a small non-zero equilibrium rather than pinning
      to exactly 0° (which looks like a SENTINEL-flaggable flatline).
    - watchdog_trips is a strict int managed via InternalCounters.watchdog_overload_s
      and a cooldown — never accumulated fractionally. See _step_obc().

Dependency-graph consistency (graph.py):
    Cascade effects from modifiers produced by faults.py follow EXACTLY
    the 18 directed edges in SHERLOCK's graph. No subsystem receives a
    modifier from a source that lacks an edge in the graph.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .orbit import OrbitClock
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
# Physics constants (tunable, not scientifically exact)
# ─────────────────────────────────────────────────────────────────────────────

# EPS
_BATTERY_CAPACITY_AH: float = 20.0   # Ah — nominal total capacity
_NOMINAL_SOLAR_CURRENT: float = 8.0  # A — peak solar array output in full sunlight
_NOMINAL_LOAD_CURRENT: float = 5.0   # A — baseline spacecraft load
_BATTERY_MIN_VOLTAGE: float = 22.0   # V — fully depleted
_BATTERY_MAX_VOLTAGE: float = 30.0   # V — fully charged
# Bus voltage is linearly interpolated: V = 22 + 8*soc
_BUS_V_OFFSET: float = 22.0
_BUS_V_RANGE: float = 8.0
# Battery temperature derate: above 40°C charge efficiency drops
_BATTERY_TEMP_DERATE_THRESHOLD: float = 40.0
_BATTERY_TEMP_DERATE_COEFF: float = 0.02  # efficiency loss per °C above threshold

# TCS
_PANEL_SUNLIGHT_EQUILIBRIUM: float = 45.0    # °C — equilibrium in full sunlight
_PANEL_ECLIPSE_EQUILIBRIUM: float = -15.0    # °C — equilibrium in full eclipse
_PANEL_THERMAL_TIME_CONST: float = 1.0 / 600.0  # 1/s — ~10min time constant
_BATTERY_THERMAL_COUPLING: float = 0.0005   # °C/s per °C difference (panel↔battery)
_HEATER_ON_THRESHOLD: float = -5.0           # °C — heater turns on below this
_HEATER_OFF_THRESHOLD: float = 5.0           # °C — heater turns off above this
_HEATER_POWER_DEG_PER_S: float = 0.5        # °C/s added by heater when on

# ADCS
_DRIFT_RATE: float = 0.01      # deg/s — natural angular drift without control
_WHEEL_GAIN: float = 0.05      # proportional feedback gain (deg/s correction per deg error)
_MAX_WHEEL_TORQUE: float = 0.5 # deg/s maximum correction rate (wheel torque limit)
_WHEEL_SPEED_GAIN: float = 10.0  # RPM per deg/s of error correction
# Equilibrium attitude_error = DRIFT_RATE / WHEEL_GAIN = 0.2°
# With noise this hovers at ~0.2–0.5°, not a suspicious flatline.

# OBC
_NOMINAL_CPU_LOAD: float = 0.35
_MEMORY_LEAK_RATE_MB_S: float = 0.001     # MB/s very slow baseline leak
_CPU_OSCILLATION_PERIOD: float = 300.0    # s — natural CPU load cycle
_CPU_OSCILLATION_AMP: float = 0.05        # fraction amplitude
_WATCHDOG_THRESHOLD: float = 0.90         # cpu_load above this counts as overload
_WATCHDOG_MIN_DURATION_S: float = 30.0   # seconds sustained overload before trip
_WATCHDOG_COOLDOWN_S: float = 120.0      # seconds before next trip can occur
_OBC_THERMAL_TRIP_TEMP: float = 70.0     # °C — board temp that causes throttling
_OBC_THERMAL_CPU_PENALTY: float = 0.25   # added cpu_load when thermally throttling

# TT&C
_NOMINAL_SIGNAL_DBM: float = -75.0       # dBm — nominal received signal
_POINTING_LOSS_COEFF: float = 0.3        # dBm lost per degree of attitude error
_LOCK_THRESHOLD_DBM: float = -90.0       # dBm — below this, BER degrades rapidly
_BER_SIGMOID_K: float = 0.3             # sigmoid steepness for BER model
# BER = sigmoid(-k * (signal - lock_threshold))
# At -75 dBm: margin=+15 → BER≈0.011 (excellent)
# At -90 dBm: margin=0  → BER=0.5 (degraded)
# At -105 dBm: margin=-15 → BER≈0.989 (lost)

# Propulsion
_MAX_FUEL_KG: float = 50.0
_NOMINAL_THRUSTER_TEMP: float = 20.0
_THRUSTER_PASSIVE_COOLING: float = 0.2    # °C/s passive cooling rate


# ─────────────────────────────────────────────────────────────────────────────
# Internal mutable counters (not part of public SatelliteState)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class InternalCounters:
    """
    Mutable state that must persist across time steps but does NOT belong
    in the public SatelliteState schema.

    Kept separate so SatelliteState remains a clean, serialisable data
    contract without hidden float accumulators leaking into agent APIs.
    """

    # OBC watchdog: accumulated time continuously above cpu threshold
    watchdog_overload_s: float = 0.0
    # OBC watchdog: cooldown timer after a trip (blocks re-triggering)
    watchdog_cooldown_remaining_s: float = 0.0
    # TCS heater hysteresis state (avoids rapid toggling at boundary)
    heater_on: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _sigmoid(x: float) -> float:
    """Numerically stable sigmoid."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


# ─────────────────────────────────────────────────────────────────────────────
# EPS transition
# ─────────────────────────────────────────────────────────────────────────────


def step_eps(
    state: SatelliteState,
    dt: float,
    orbit: OrbitClock,
    t: float,
    fault_mods: dict[str, float],
    recovery_mods: dict[str, float],
    battery_temp: float,
) -> EPSState:
    """
    Compute next EPS state.

    Fault modifiers consumed:
        eps_solar_factor    - multiplier on solar array current (0=no solar)
        eps_load_delta      - additional load current in Amps
        eps_capacity_factor - multiplier on effective battery capacity

    Recovery modifiers consumed:
        eps_solar_factor    - may restore solar (e.g., reorient)
        eps_load_delta      - may reduce load (e.g., shed_nonessential_load)
        eps_capacity_factor - may partially restore (e.g., switch_redundant_bus)
    """
    # Modifiers (fault and recovery are additive/multiplicative as specified)
    solar_factor = fault_mods.get("eps_solar_factor", 1.0) * recovery_mods.get("eps_solar_factor", 1.0)
    solar_factor = _clamp(solar_factor, 0.0, 1.0)
    load_delta = fault_mods.get("eps_load_delta", 0.0) + recovery_mods.get("eps_load_delta", 0.0)
    capacity_factor = fault_mods.get("eps_capacity_factor", 1.0) * recovery_mods.get("eps_capacity_factor", 1.0)
    capacity_factor = _clamp(capacity_factor, 0.05, 1.0)

    # Solar charging: proportional to sunlight_factor and pointing efficiency
    solar_efficiency = fault_mods.get("eps_pointing_efficiency", 1.0) * recovery_mods.get("eps_pointing_efficiency", 1.0)
    solar_array_current = _NOMINAL_SOLAR_CURRENT * orbit.sunlight_factor(t) * solar_factor * solar_efficiency
    solar_array_current = max(0.0, solar_array_current)

    # Load current
    load_current = _NOMINAL_LOAD_CURRENT + load_delta
    load_current = max(0.5, load_current)  # minimum parasitic load always present

    # Battery temperature derate on charge efficiency (TCS→EPS thermal_feedback edge)
    charge_efficiency = 1.0
    if battery_temp > _BATTERY_TEMP_DERATE_THRESHOLD:
        excess = battery_temp - _BATTERY_TEMP_DERATE_THRESHOLD
        charge_efficiency = max(0.0, 1.0 - _BATTERY_TEMP_DERATE_COEFF * excess)

    # Battery SOC integration: (charge - discharge) / effective_capacity
    effective_capacity_as = _BATTERY_CAPACITY_AH * capacity_factor * 3600.0  # Amp-seconds
    net_current = solar_array_current * charge_efficiency - load_current
    d_soc = (net_current * dt) / effective_capacity_as
    new_soc = _clamp(state.eps.battery_soc + d_soc, 0.0, 1.0)

    # Bus voltage: linear SOC model, minus any direct sag from rising
    # internal resistance under load (e.g. eps_battery_degradation) — a
    # term the SOC integration alone can't represent.
    voltage_sag = fault_mods.get("eps_voltage_sag", 0.0) + recovery_mods.get("eps_voltage_sag", 0.0)
    new_voltage = _clamp(_BUS_V_OFFSET + _BUS_V_RANGE * new_soc - voltage_sag, 0.0, 36.0)

    return EPSState(
        battery_soc=new_soc,
        solar_array_current=solar_array_current,
        bus_voltage=new_voltage,
        load_current=load_current,
    )


# ─────────────────────────────────────────────────────────────────────────────
# TCS transition
# ─────────────────────────────────────────────────────────────────────────────


def step_tcs(
    state: SatelliteState,
    dt: float,
    orbit: OrbitClock,
    t: float,
    fault_mods: dict[str, float],
    recovery_mods: dict[str, float],
    attitude_error: float,
    counters: InternalCounters,
) -> TCSState:
    """
    Compute next TCS state.

    Fault modifiers consumed:
        tcs_target_temp_delta  - shift on equilibrium temperature (thermal runaway)
        tcs_cooling_factor     - multiplier on cooling effectiveness (< 1 = failed heat pipe)
        prop_heat_output       - thruster heat addition in °C/s (Propulsion→TCS thermal_output)

    Recovery modifiers consumed:
        tcs_heater_override    - force heater ON regardless of threshold
    """
    sun = orbit.sunlight_factor(t)

    # Equilibrium temperature shifts with sunlight and attitude (ADCS→TCS attitude_effect)
    # Off-pointing reduces effective solar input → cooler in sunlight
    pointing_factor = max(0.0, 1.0 - attitude_error / 180.0)
    sunlight_eq = _PANEL_SUNLIGHT_EQUILIBRIUM * pointing_factor
    eclipse_eq = _PANEL_ECLIPSE_EQUILIBRIUM

    target_temp = sun * sunlight_eq + (1.0 - sun) * eclipse_eq
    target_temp += fault_mods.get("tcs_target_temp_delta", 0.0)

    # Cooling: heat pipe fault reduces effectiveness
    cooling_factor = fault_mods.get("tcs_cooling_factor", 1.0) * recovery_mods.get("tcs_cooling_factor", 1.0)
    cooling_factor = _clamp(cooling_factor, 0.0, 1.0)

    # Panel temperature: exponential approach to target (drift model)
    effective_time_const = _PANEL_THERMAL_TIME_CONST * cooling_factor
    panel_temp = state.tcs.panel_temp + dt * effective_time_const * (target_temp - state.tcs.panel_temp)

    # Propulsion heat addition (Propulsion→TCS thermal_output edge)
    panel_temp += dt * fault_mods.get("prop_heat_output", 0.0)

    panel_temp = _clamp(panel_temp, -50.0, 150.0)

    # Battery temperature: slowly tracks panel temperature
    battery_temp = state.tcs.battery_temp + dt * _BATTERY_THERMAL_COUPLING * (panel_temp - state.tcs.battery_temp)
    battery_temp = _clamp(battery_temp, -50.0, 100.0)

    # Heater hysteresis (uses counters to avoid rapid toggling)
    heater_override = recovery_mods.get("tcs_heater_override", 0)
    if heater_override == 1:
        counters.heater_on = True
    elif panel_temp < _HEATER_ON_THRESHOLD:
        counters.heater_on = True
    elif panel_temp > _HEATER_OFF_THRESHOLD:
        counters.heater_on = False

    if counters.heater_on:
        panel_temp = min(panel_temp + _HEATER_POWER_DEG_PER_S * dt, 150.0)

    return TCSState(
        panel_temp=panel_temp,
        battery_temp=battery_temp,
        heater_active=counters.heater_on,
        in_eclipse=orbit.is_in_eclipse(t),
    )


# ─────────────────────────────────────────────────────────────────────────────
# ADCS transition — proportional feedback (not constant correction)
# ─────────────────────────────────────────────────────────────────────────────


def step_adcs(
    state: SatelliteState,
    dt: float,
    fault_mods: dict[str, float],
    recovery_mods: dict[str, float],
    obc_blind: bool,
) -> ADCSState:
    """
    Compute next ADCS state.

    Uses proportional feedback control: control torque = WHEEL_GAIN × attitude_error × efficiency.
    Equilibrium attitude_error = DRIFT_RATE / WHEEL_GAIN = 0.2°.
    Combined with noise, this produces a realistic hover rather than a flatline at 0°.

    Fault modifiers consumed:
        adcs_disturbance_torque  - additional angular disturbance rate in deg/s
                                   (from Propulsion→ADCS attitude_disturbance edge)
        adcs_wheel_efficiency    - multiplier on wheel torque capability (0=dead wheel)

    Recovery modifiers consumed:
        adcs_wheel_efficiency    - may restore wheel efficiency
        adcs_control_override    - if 1: lock attitude_error to current value (safe mode, no maneuver)

    obc_blind: if True, OBC command loop is halted (OBC→ADCS command_control edge);
               control law is suspended, drift accumulates at full rate.
    """
    wheel_efficiency = (
        fault_mods.get("adcs_wheel_efficiency", 1.0)
        * recovery_mods.get("adcs_wheel_efficiency", 1.0)
    )
    wheel_efficiency = _clamp(wheel_efficiency, 0.0, 1.0)

    disturbance = fault_mods.get("adcs_disturbance_torque", 0.0)

    # If OBC is blind, no control commands → attitude drifts at full DRIFT_RATE
    if obc_blind:
        wheel_efficiency = 0.0

    # Proportional feedback: correction torque ∝ attitude_error × wheel efficiency
    error = state.adcs.attitude_error
    control_torque = min(_MAX_WHEEL_TORQUE, _WHEEL_GAIN * error * wheel_efficiency)

    # Net angular rate change
    d_error = _DRIFT_RATE + disturbance - control_torque
    new_error = _clamp(error + dt * d_error, 0.0, 180.0)

    # Reaction wheel speed: spins up in proportion to correction torque being applied
    # When wheel is working hard (correcting large error), speed increases
    wheel_correction_torque_applied = min(_MAX_WHEEL_TORQUE, _WHEEL_GAIN * error * wheel_efficiency)
    d_wheel = _WHEEL_SPEED_GAIN * wheel_correction_torque_applied - 0.01 * state.adcs.reaction_wheel_speed
    new_wheel_speed = _clamp(state.adcs.reaction_wheel_speed + dt * d_wheel, -6000.0, 6000.0)

    return ADCSState(
        attitude_error=new_error,
        reaction_wheel_speed=new_wheel_speed,
    )


# ─────────────────────────────────────────────────────────────────────────────
# OBC transition — discrete watchdog counter (Fix 1)
# ─────────────────────────────────────────────────────────────────────────────


def step_obc(
    state: SatelliteState,
    dt: float,
    t: float,
    fault_mods: dict[str, float],
    recovery_mods: dict[str, float],
    panel_temp: float,
    counters: InternalCounters,
) -> OBCState:
    """
    Compute next OBC state.

    watchdog_trips is a STRICT INTEGER. Never accumulates fractionally.
    The InternalCounters.watchdog_overload_s float accumulator is the
    hidden state; watchdog_trips only increments by exactly 1 when:
        1. cpu_load has been continuously above _WATCHDOG_THRESHOLD for
           >= _WATCHDOG_MIN_DURATION_S seconds, AND
        2. watchdog_cooldown_remaining_s == 0 (not in post-trip cooldown)

    Fault modifiers consumed:
        obc_cpu_delta       - additional CPU load fraction

    Recovery modifiers consumed:
        obc_cpu_cap         - if set, caps cpu_load at this value (safe mode)
        obc_memory_fix      - stops memory leak if == 1

    panel_temp: from TCS state — used for thermal throttle cascade
                (TCS→OBC thermal_stress edge).
    """
    cpu_delta = fault_mods.get("obc_cpu_delta", 0.0) + recovery_mods.get("obc_cpu_delta", 0.0)

    # Natural slow oscillation in CPU load (makes telemetry look real)
    cpu_oscillation = _CPU_OSCILLATION_AMP * math.sin(2.0 * math.pi * t / _CPU_OSCILLATION_PERIOD)

    # Thermal throttle cascade (TCS→OBC thermal_stress edge)
    thermal_penalty = 0.0
    if panel_temp > _OBC_THERMAL_TRIP_TEMP:
        thermal_penalty = _OBC_THERMAL_CPU_PENALTY

    cpu_load = _NOMINAL_CPU_LOAD + cpu_oscillation + cpu_delta + thermal_penalty

    # Recovery: safe mode CPU cap
    cpu_cap = recovery_mods.get("obc_cpu_cap", 1.0)
    cpu_load = _clamp(cpu_load, 0.0, cpu_cap)

    # Memory leak (very slow baseline drain; stops in safe mode)
    memory_fix = recovery_mods.get("obc_memory_fix", 0)
    leak = 0.0 if memory_fix else _MEMORY_LEAK_RATE_MB_S
    new_memory = _clamp(state.obc.free_memory_mb - leak * dt, 0.0, 512.0)

    # ── Watchdog trip logic (discrete integer, Fix 1) ────────────────────────
    new_trips = state.obc.watchdog_trips

    # Count down cooldown
    if counters.watchdog_cooldown_remaining_s > 0:
        counters.watchdog_cooldown_remaining_s = max(
            0.0, counters.watchdog_cooldown_remaining_s - dt
        )

    if cpu_load > _WATCHDOG_THRESHOLD:
        # Accumulate overload time only if NOT in cooldown
        if counters.watchdog_cooldown_remaining_s == 0.0:
            counters.watchdog_overload_s += dt
    else:
        # Overload must be sustained — reset accumulator on any relief
        counters.watchdog_overload_s = 0.0

    # Trip fires if sustained overload threshold reached and cooldown expired
    if (
        counters.watchdog_overload_s >= _WATCHDOG_MIN_DURATION_S
        and counters.watchdog_cooldown_remaining_s == 0.0
    ):
        new_trips += 1  # exactly +1, always an integer
        counters.watchdog_overload_s = 0.0
        counters.watchdog_cooldown_remaining_s = _WATCHDOG_COOLDOWN_S

    return OBCState(
        free_memory_mb=new_memory,
        cpu_load=cpu_load,
        watchdog_trips=new_trips,
    )


# ─────────────────────────────────────────────────────────────────────────────
# TT&C transition — sigmoid BER model (Fix 2)
# ─────────────────────────────────────────────────────────────────────────────


def step_ttc(
    state: SatelliteState,
    dt: float,
    orbit: OrbitClock,
    t: float,
    fault_mods: dict[str, float],
    recovery_mods: dict[str, float],
    attitude_error: float,
) -> TTCState:
    """
    Compute next TT&C state.

    BER uses a sigmoid model relative to the lock threshold (-90 dBm).
    This produces a smooth S-curve degradation across the realistic signal
    range instead of the raw 10^(-signal/10) formula that saturates to 1.0
    almost immediately once signal degrades.

    Fault modifiers consumed:
        ttc_signal_delta    - dBm offset (negative = worse, from ttc_signal_dropout fault)

    Recovery modifiers consumed:
        (none — signal is physically determined by attitude and fault state)

    attitude_error: from ADCS state — drives pointing loss
                    (ADCS→TT&C pointing edge: antenna de-points with attitude error).
    """
    signal_delta = fault_mods.get("ttc_signal_delta", 0.0)

    # Signal: degrades with attitude error (ADCS→TT&C pointing edge)
    pointing_loss = _POINTING_LOSS_COEFF * attitude_error
    new_signal = _NOMINAL_SIGNAL_DBM - pointing_loss + signal_delta
    new_signal = _clamp(new_signal, -120.0, -60.0)

    # BER: sigmoid model — smooth degradation, no step-function saturation (Fix 2)
    # margin > 0 → good link; margin < 0 → degraded link
    margin = new_signal - _LOCK_THRESHOLD_DBM
    bit_error_rate = _sigmoid(-_BER_SIGMOID_K * margin)
    bit_error_rate = _clamp(bit_error_rate, 0.0, 1.0)

    # Ground contact: orbit clock determines window
    contact_remaining = orbit.ground_contact_remaining(t)

    return TTCState(
        signal_strength=new_signal,
        bit_error_rate=bit_error_rate,
        ground_contact_remaining=contact_remaining,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Propulsion transition
# ─────────────────────────────────────────────────────────────────────────────


def step_propulsion(
    state: SatelliteState,
    dt: float,
    fault_mods: dict[str, float],
    recovery_mods: dict[str, float],
) -> PropulsionState:
    """
    Compute next Propulsion state.

    Fault modifiers consumed:
        prop_burn_rate       - kg/s fuel consumption rate (uncontrolled leak or burn)
        prop_heat_input      - °C/s heat generated by thruster fault
        adcs_disturbance_torque - produced BY Propulsion fault, consumed by ADCS transition

    Recovery modifiers consumed:
        prop_burn_rate       - set to 0 by thruster_isolation action (stops leak)
        prop_heat_input      - set to 0 by thruster_isolation action
    """
    burn_rate = fault_mods.get("prop_burn_rate", 0.0) + recovery_mods.get("prop_burn_rate", 0.0)
    burn_rate = max(0.0, burn_rate)
    heat_input = fault_mods.get("prop_heat_input", 0.0) + recovery_mods.get("prop_heat_input", 0.0)

    new_fuel = _clamp(state.propulsion.fuel_remaining - burn_rate * dt, 0.0, _MAX_FUEL_KG)

    # Thermal: rises during burn, cools passively otherwise
    if burn_rate > 0:
        d_temp = heat_input - _THRUSTER_PASSIVE_COOLING
    else:
        d_temp = -_THRUSTER_PASSIVE_COOLING * (state.propulsion.thruster_temp - _NOMINAL_THRUSTER_TEMP)
    new_temp = _clamp(state.propulsion.thruster_temp + dt * d_temp, -20.0, 200.0)

    return PropulsionState(
        fuel_remaining=new_fuel,
        thruster_temp=new_temp,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Expose constants needed by tests
# ─────────────────────────────────────────────────────────────────────────────

NOMINAL_LOAD_CURRENT = _NOMINAL_LOAD_CURRENT
NOMINAL_SOLAR_CURRENT = _NOMINAL_SOLAR_CURRENT
WATCHDOG_THRESHOLD = _WATCHDOG_THRESHOLD
WATCHDOG_MIN_DURATION_S = _WATCHDOG_MIN_DURATION_S
WATCHDOG_COOLDOWN_S = _WATCHDOG_COOLDOWN_S
LOCK_THRESHOLD_DBM = _LOCK_THRESHOLD_DBM
BER_SIGMOID_K = _BER_SIGMOID_K
DRIFT_RATE = _DRIFT_RATE
WHEEL_GAIN = _WHEEL_GAIN

# CPU oscillation (needed by tests)
CPU_OSCILLATION_PERIOD = _CPU_OSCILLATION_PERIOD
CPU_OSCILLATION_AMP = _CPU_OSCILLATION_AMP
NOMINAL_CPU_LOAD = _NOMINAL_CPU_LOAD
