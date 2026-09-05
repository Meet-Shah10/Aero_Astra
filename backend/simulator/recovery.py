"""
AERO-ASTRA Physics Simulator — Recovery Action Catalog

Defines the injectable recovery actions and their modifier computation logic.

Each action pushes transition function behavior back toward nominal by providing
positive modifiers that counteract fault modifiers. Actions do NOT teleport
state values — they change rates of recovery. This models the realistic
situation where, e.g., switching to a redundant power bus restores charging
current but the battery SOC still needs time to climb.

These are behavioral stubs. ATHENA (once built) will build procedural step
sequences on top of these — the `steps` field is intentionally absent here.
"""

from __future__ import annotations

from dataclasses import dataclass

# ─────────────────────────────────────────────────────────────────────────────
# RecoveryAction dataclass
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class RecoveryAction:
    """Describes one entry in the recovery action catalog."""

    name: str
    target_subsystems: list[str]  # primary subsystems this action directly affects
    description: str


# ─────────────────────────────────────────────────────────────────────────────
# Recovery action catalog
# ─────────────────────────────────────────────────────────────────────────────

RECOVERY_CATALOG: dict[str, RecoveryAction] = {
    "switch_redundant_power_bus": RecoveryAction(
        name="switch_redundant_power_bus",
        target_subsystems=["EPS"],
        description=(
            "Switches to the redundant power bus configuration, restoring effective "
            "battery capacity and resetting the internal resistance penalty. "
            "Primary counter for eps_battery_degradation and eps_cascade_power_failure."
        ),
    ),
    "shed_nonessential_load": RecoveryAction(
        name="shed_nonessential_load",
        target_subsystems=["EPS"],
        description=(
            "Powers off non-critical payloads and heaters, reducing load_current "
            "by ~30%. Buys time for battery SOC to recover in any EPS fault scenario."
        ),
    ),
    "reorient_maximum_solar_exposure": RecoveryAction(
        name="reorient_maximum_solar_exposure",
        target_subsystems=["ADCS", "EPS"],
        description=(
            "Commands ADCS to slew toward maximum solar panel illumination. "
            "Forces pointing efficiency to 1.0 for one orbit, regardless of any "
            "residual attitude error from the ADCS fault. Directly counters "
            "adcs_reaction_wheel_degradation's EPS impact."
        ),
    ),
    "enter_safe_low_power_mode": RecoveryAction(
        name="enter_safe_low_power_mode",
        target_subsystems=["OBC", "EPS"],
        description=(
            "Puts OBC into safe mode: CPU load capped at 20%, non-critical processes "
            "halted, memory leak stopped. Also reduces total load_current. "
            "Reduces watchdog trip risk in OBC-stressed scenarios."
        ),
    ),
    "activate_backup_heater": RecoveryAction(
        name="activate_backup_heater",
        target_subsystems=["TCS"],
        description=(
            "Activates the backup survival heater, forcing heater_on=True regardless "
            "of panel temperature reading. Counters cold thermal runaway (e.g., after "
            "eps_cascade_power_failure cuts primary heater power)."
        ),
    ),
    "thruster_isolation": RecoveryAction(
        name="thruster_isolation",
        target_subsystems=["Propulsion", "ADCS"],
        description=(
            "Closes propellant isolation valves, setting burn_rate and heat_input "
            "to zero and clearing the attitude disturbance from propulsion_thruster_fault. "
            "Stops propellant leak and allows ADCS to regain control."
        ),
    ),
    "reset_ttc_transmitter": RecoveryAction(
        name="reset_ttc_transmitter",
        target_subsystems=["TT&C"],
        description=(
            "Power-cycles the TT&C transmitter and re-initialises the comms stack. "
            "Directly restores signal strength and BER after ttc_signal_dropout. "
            "No effect on EPS or ADCS subsystems."
        ),
    ),
    "reboot_obc": RecoveryAction(
        name="reboot_obc",
        target_subsystems=["OBC"],
        description=(
            "Soft-reboots the On-Board Computer: clears watchdog trips, flushes "
            "memory leak, and resets CPU load to the cold-start baseline (~30%). "
            "Primary counter for obc_memory_leak and obc_cpu_overload faults."
        ),
    ),
}


def get_recovery_modifiers(action_name: str) -> dict[str, dict[str, float]]:
    """
    Return the modifier dict for the given recovery action.

    Modifiers are constant (not time-ramped) — recovery acts immediately
    on the transition behavior once applied, though state values still need
    time to respond.

    Returns:
        Nested dict { subsystem_key: { modifier_key: value } }.
    """
    if action_name not in RECOVERY_CATALOG:
        raise ValueError(
            f"Unknown recovery action '{action_name}'. "
            f"Valid actions: {sorted(RECOVERY_CATALOG.keys())}"
        )

    mods: dict[str, dict[str, float]] = {
        "eps": {}, "tcs": {}, "adcs": {}, "obc": {}, "ttc": {}, "prop": {},
    }

    if action_name == "switch_redundant_power_bus":
        mods["eps"]["eps_capacity_factor"] = 1.0   # restore full capacity
        mods["eps"]["eps_solar_factor"] = 1.0      # restore solar path
        mods["eps"]["eps_load_delta"] = 0.0        # clear internal resistance penalty

    elif action_name == "shed_nonessential_load":
        mods["eps"]["eps_load_delta"] = -1.5       # reduce load ~30% of nominal 5A

    elif action_name == "reorient_maximum_solar_exposure":
        mods["eps"]["eps_pointing_efficiency"] = 1.0  # force maximum solar input
        mods["adcs"]["adcs_wheel_efficiency"] = 0.5   # partial wheel recovery for slew

    elif action_name == "enter_safe_low_power_mode":
        mods["obc"]["obc_cpu_cap"] = 0.20          # cap CPU at 20%
        mods["obc"]["obc_memory_fix"] = 1.0        # stop memory leak
        mods["obc"]["obc_cpu_delta"] = -0.1        # reduce active process load
        mods["eps"]["eps_load_delta"] = -40.0      # huge load reduction
        mods["tcs"]["tcs_target_temp_delta"] = -350.0 # cancels thermal runaway heating
        mods["adcs"]["adcs_safe_mode"] = 1.0       # forces attitude to 0 (sun-pointing)

    elif action_name == "activate_backup_heater":
        mods["tcs"]["tcs_heater_override"] = 1.0  # force heater on

    elif action_name == "thruster_isolation":
        mods["prop"]["prop_burn_rate"] = -999.0    # cancels all burn rate (engine clamps to 0)
        mods["prop"]["prop_heat_input"] = -999.0   # cancels thruster heat
        mods["adcs"]["adcs_disturbance_torque"] = -999.0  # clears disturbance (engine clamps to 0)
        mods["tcs"]["prop_heat_output"] = -999.0   # stops heat cascading to panel

    elif action_name == "reset_ttc_transmitter":
        mods["ttc"]["ttc_signal_delta"] = 40.0     # restores signal (+40 dBm cancels -40 dropout)
        mods["ttc"]["ttc_ber_reset"] = 1.0         # flag to reset BER to nominal in step_ttc

    elif action_name == "reboot_obc":
        mods["obc"]["obc_cpu_cap"] = 0.30          # reset CPU to cold-start baseline
        mods["obc"]["obc_memory_fix"] = 1.0        # flush memory leak
        mods["obc"]["obc_watchdog_reset"] = 1.0    # clear watchdog trip counter
        mods["obc"]["obc_cpu_delta"] = -0.15       # reduce active process overhead

    return mods
