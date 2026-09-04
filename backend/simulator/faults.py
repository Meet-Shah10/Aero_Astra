"""
AERO-ASTRA Physics Simulator — Fault Catalog

Defines the injectable fault types and their modifier computation logic.

Each fault modifies transition function behavior by returning a dict of
modifier keys per subsystem. Transition functions read these and apply them
at computation time — state is never directly overwritten. This is what
makes fault effects play out realistically over time.

Fault onset uses a linear ramp (0 → target severity over ramp_time_s),
so the telemetry shows a building trend rather than an instantaneous jump.

Cascade consistency with SHERLOCK's dependency graph (graph.py):
    Every cascade effect in this catalog follows EXACTLY one of the 18
    directed edges in SHERLOCK's graph. No modifier is produced for a
    target subsystem unless the graph contains an edge from the fault's
    source subsystem to that target.

    EPS  → TCS, ADCS, OBC, TT&C, Propulsion  (power_supply)
    TCS  → ADCS, OBC, EPS, Propulsion         (thermal_stress / thermal_feedback)
    ADCS → TCS, EPS, TT&C                     (attitude_effect / pointing)
    OBC  → ADCS, TT&C, EPS                    (command_control)
    TT&C → OBC                                (data_link)
    Prop → ADCS, TCS                          (attitude_disturbance / thermal_output)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# ─────────────────────────────────────────────────────────────────────────────
# Fault ramp helper
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_RAMP_S: float = 60.0  # seconds to reach full severity from onset


def _ramp(t: float, t_onset: float, severity: float, ramp_s: float = _DEFAULT_RAMP_S) -> float:
    """
    Linear ramp from 0 → severity over ramp_s seconds after t_onset.
    Returns 0.0 before onset.
    """
    if t < t_onset:
        return 0.0
    elapsed = t - t_onset
    return min(1.0, elapsed / ramp_s) * severity


# ─────────────────────────────────────────────────────────────────────────────
# FaultSpec dataclass
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class FaultSpec:
    """Describes one entry in the fault catalog."""

    name: str
    target_subsystem: str
    description: str
    cascade_targets: list[str]   # downstream subsystems affected (graph edge targets)
    ramp_time_s: float = _DEFAULT_RAMP_S


# ─────────────────────────────────────────────────────────────────────────────
# Fault catalog
# ─────────────────────────────────────────────────────────────────────────────

FAULT_CATALOG: dict[str, FaultSpec] = {
    "eps_battery_degradation": FaultSpec(
        name="eps_battery_degradation",
        target_subsystem="EPS",
        description=(
            "Battery cell degradation reduces effective capacity and increases internal "
            "resistance. Bus voltage sags under load, eventually starving downstream subsystems."
        ),
        cascade_targets=["TCS", "ADCS", "OBC", "TT&C", "Propulsion"],  # all 5 EPS→* edges
        ramp_time_s=120.0,   # slower onset — gradual degradation
    ),
    "tcs_thermal_runaway": FaultSpec(
        name="tcs_thermal_runaway",
        target_subsystem="TCS",
        description=(
            "Heat pipe failure reduces radiative cooling; panel temperature climbs unbounded "
            "toward thermal limits. Overtemperature stresses gyroscopes (ADCS), OBC boards, "
            "battery (EPS), and propellant (Propulsion)."
        ),
        cascade_targets=["ADCS", "OBC", "EPS", "Propulsion"],  # TCS→* edges
        ramp_time_s=90.0,
    ),
    "adcs_reaction_wheel_degradation": FaultSpec(
        name="adcs_reaction_wheel_degradation",
        target_subsystem="ADCS",
        description=(
            "Reaction wheel bearing friction or motor fault reduces available torque. "
            "Attitude error grows, degrading solar pointing (EPS), thermal balance (TCS), "
            "and antenna pointing (TT&C)."
        ),
        cascade_targets=["TCS", "EPS", "TT&C"],  # ADCS→* edges
        ramp_time_s=60.0,
    ),
    "ttc_signal_dropout": FaultSpec(
        name="ttc_signal_dropout",
        target_subsystem="TT&C",
        description=(
            "Antenna or transponder fault drops signal below lock threshold. "
            "Uplink loss means OBC receives no ground commands and operates blind."
        ),
        cascade_targets=["OBC"],  # TT&C→OBC data_link edge
        ramp_time_s=30.0,   # fast onset — hardware failure
    ),
    "propulsion_thruster_fault": FaultSpec(
        name="propulsion_thruster_fault",
        target_subsystem="Propulsion",
        description=(
            "Thruster valve misfire or propellant leak generates uncontrolled torque "
            "and heat. ADCS must compensate or saturates; TCS sees local heating."
        ),
        cascade_targets=["ADCS", "TCS"],  # Propulsion→ADCS, Propulsion→TCS edges
        ramp_time_s=15.0,   # fast onset — mechanical event
    ),
    "eps_cascade_power_failure": FaultSpec(
        name="eps_cascade_power_failure",
        target_subsystem="EPS",
        description=(
            "Complete solar array loss (debris strike or array deployment failure) "
            "drops solar_array_current to zero. Battery drains under full load; "
            "all five EPS→* power_supply edges propagate undervoltage to TCS "
            "(heaters off → thermal runaway), ADCS (wheels lose power → attitude loss), "
            "OBC (undervoltage → watchdog trips), TT&C (transmitter drops → comms loss), "
            "and Propulsion (valve actuators offline)."
        ),
        cascade_targets=["TCS", "ADCS", "OBC", "TT&C", "Propulsion"],
        ramp_time_s=10.0,   # near-instant — catastrophic hardware event
    ),
}


def get_fault_modifiers(
    fault_name: str,
    t: float,
    t_onset: float,
    severity: float,
    current_battery_soc: float,
) -> dict[str, dict[str, float]]:
    """
    Compute the full modifier dict for a given fault at simulation time t.

    Returns a nested dict:
        { subsystem_key: { modifier_key: value, ... }, ... }

    Only keys that are non-zero (i.e., the fault is actually active and has
    started ramping) are populated. The transition functions default missing
    keys to 0/1 as appropriate.

    Args:
        fault_name:          Name from FAULT_CATALOG.
        t:                   Current simulation time in seconds.
        t_onset:             When the fault was injected.
        severity:            Configured fault severity [0, 1].
        current_battery_soc: Used by cascade faults to scale downstream effects.

    Returns:
        Nested modifier dict, or empty dict if t < t_onset.
    """
    # Always return all 6 subsystem keys — engine.py relies on these existing.
    mods: dict[str, dict[str, float]] = {
        "eps": {}, "tcs": {}, "adcs": {}, "obc": {}, "ttc": {}, "prop": {},
    }

    if t < t_onset:
        return mods

    eff = _ramp(t, t_onset, severity, FAULT_CATALOG[fault_name].ramp_time_s)
    if eff == 0.0:
        return mods

    # ── EPS battery degradation ───────────────────────────────────────────────
    if fault_name == "eps_battery_degradation":
        # Primary: reduces effective capacity and adds internal-resistance load
        mods["eps"]["eps_capacity_factor"] = 1.0 - 0.6 * eff
        mods["eps"]["eps_load_delta"] = 1.5 * eff  # internal resistance extra load

        # Cascades via EPS→* power_supply edges, scaled by how depleted the battery is
        undervoltage_factor = eff * (1.0 - current_battery_soc)
        # TCS: heaters lose power → cooling effectiveness drops
        mods["tcs"]["tcs_cooling_factor"] = 1.0 - 0.4 * undervoltage_factor
        # ADCS: wheel torque reduced by power loss
        mods["adcs"]["adcs_wheel_efficiency"] = 1.0 - 0.5 * undervoltage_factor
        # OBC: thermal/power stress → CPU delta
        mods["obc"]["obc_cpu_delta"] = 0.2 * undervoltage_factor
        # TT&C: signal transmitter power reduced
        mods["ttc"]["ttc_signal_delta"] = -10.0 * undervoltage_factor
        # Propulsion: valve actuation pressure reduced
        mods["prop"]["prop_burn_rate"] = 0.0  # actuators offline — no burn capability

    # ── TCS thermal runaway ───────────────────────────────────────────────────
    elif fault_name == "tcs_thermal_runaway":
        # Primary: heat pipe failure — push target temp up, reduce cooling
        # Pushed from 50.0 to 350.0 so the 10-minute thermal time constant 
        # produces a fast enough gradient to trigger the 49°C alarm within ~5s
        mods["tcs"]["tcs_target_temp_delta"] = 350.0 * eff
        mods["tcs"]["tcs_cooling_factor"] = 1.0 - 0.8 * eff

        # Cascades via TCS→* thermal_stress / thermal_feedback edges
        # TCS→ADCS thermal_stress: gyro/star-tracker shutdown above threshold
        mods["adcs"]["adcs_wheel_efficiency"] = 1.0 - 0.4 * eff
        # TCS→OBC thermal_stress: CPU thermal throttle (handled in step_obc via panel_temp,
        #   but we also add a direct CPU delta for fault-on-top-of-threshold)
        mods["obc"]["obc_cpu_delta"] = 0.15 * eff
        # TCS→EPS thermal_feedback: battery temp cap → charge rate derating
        #   (handled in step_eps via battery_temp, nothing extra needed here)
        # TCS→Propulsion thermal_stress: propellant pressure effect
        mods["prop"]["prop_heat_input"] = 0.3 * eff  # residual heat into propulsion compartment

    # ── ADCS reaction wheel degradation ──────────────────────────────────────
    elif fault_name == "adcs_reaction_wheel_degradation":
        # Primary: wheel torque efficiency drops
        mods["adcs"]["adcs_wheel_efficiency"] = 1.0 - 0.9 * eff

        # Cascades via ADCS→* attitude_effect / pointing edges
        # These are handled automatically in the transition functions:
        # - step_tcs reads attitude_error for pointing_factor → thermal input changes
        # - step_eps reads eps_pointing_efficiency for solar reduction
        # - step_ttc reads attitude_error for pointing loss → signal degradation
        # We only need to add the direct modifiers for things NOT already computed:
        mods["eps"]["eps_pointing_efficiency"] = 1.0 - 0.5 * eff

    # ── TT&C signal dropout ───────────────────────────────────────────────────
    elif fault_name == "ttc_signal_dropout":
        # Primary: direct signal drop below lock threshold
        mods["ttc"]["ttc_signal_delta"] = -40.0 * eff  # drives signal to ~-115 dBm

        # Cascade via TT&C→OBC data_link edge: uplink loss → OBC blind
        # The engine reads bit_error_rate > 0.9 to set obc_blind flag.
        # No direct modifier needed; it's derived from the signal state.

    # ── Propulsion thruster fault ─────────────────────────────────────────────
    elif fault_name == "propulsion_thruster_fault":
        # Primary: uncontrolled burn/leak
        mods["prop"]["prop_burn_rate"] = 0.05 * eff   # kg/s uncontrolled leak
        mods["prop"]["prop_heat_input"] = 2.0 * eff   # °C/s thruster heat

        # Cascades via Propulsion→ADCS attitude_disturbance edge
        mods["adcs"]["adcs_disturbance_torque"] = 0.3 * eff  # deg/s uncontrolled torque
        # Cascades via Propulsion→TCS thermal_output edge
        mods["tcs"]["prop_heat_output"] = 1.5 * eff   # °C/s added to panel

    # ── EPS cascade power failure (flagship cascading scenario) ───────────────
    elif fault_name == "eps_cascade_power_failure":
        # Primary: complete solar array loss
        mods["eps"]["eps_solar_factor"] = 1.0 - eff      # drops to 0 at full severity
        mods["eps"]["eps_capacity_factor"] = 1.0 - 0.1 * eff  # slight internal degradation

        # Full cascade via all 5 EPS→* power_supply edges:
        # EPS→TCS: heaters lose power
        mods["tcs"]["tcs_cooling_factor"] = 1.0 - 0.6 * eff
        mods["tcs"]["tcs_target_temp_delta"] = -20.0 * eff  # cold spike — heaters off in eclipse
        # EPS→ADCS: wheels lose power
        mods["adcs"]["adcs_wheel_efficiency"] = 1.0 - 0.8 * eff
        # EPS→OBC: undervoltage causes watchdog accumulation
        mods["obc"]["obc_cpu_delta"] = 0.3 * eff
        # EPS→TT&C: transmitter drops
        mods["ttc"]["ttc_signal_delta"] = -20.0 * eff
        # EPS→Propulsion: valve actuators offline (no active burn possible)
        mods["prop"]["prop_burn_rate"] = 0.0

    return mods
