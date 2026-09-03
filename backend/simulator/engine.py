"""
AERO-ASTRA Physics Simulator — Core Simulation Engine

This module contains the two public entry points and the main simulation loop.
All other modules in this package are internal implementation details.

Public API:
    simulate_scenario(fault, severity, duration, dt, ...) -> SimulationResult
    run_monte_carlo(current_state, proposed_action, n_runs, steps, ...) -> MonteCarloResult

Simulation loop (per step):
    1. Compute fault modifiers for current time t
    2. Compute recovery modifiers (if action is active)
    3. Derive cross-subsystem cascade inputs (e.g. obc_blind from TT&C BER)
    4. Step each of the 6 subsystems in causal order
    5. Apply Gaussian noise
    6. Assemble new SatelliteState
    7. Update InternalCounters
"""

from __future__ import annotations

import copy
from typing import Any

import numpy as np

from .faults import FAULT_CATALOG, get_fault_modifiers
from .noise import apply_noise
from .orbit import OrbitClock
from .recovery import RECOVERY_CATALOG, get_recovery_modifiers
from .schemas import (
    ADCSState,
    EPSState,
    MonteCarloOutcome,
    MonteCarloResult,
    OBCState,
    PropulsionState,
    SatelliteState,
    SimulationFrame,
    SimulationResult,
    TCSState,
    TTCState,
)
from .transitions import (
    InternalCounters,
    step_adcs,
    step_eps,
    step_obc,
    step_propulsion,
    step_tcs,
    step_ttc,
)

# ─────────────────────────────────────────────────────────────────────────────
# Default initial state (nominal, battery ~85%, mid-orbit)
# ─────────────────────────────────────────────────────────────────────────────

_INITIAL_STATE = SatelliteState(
    timestamp=0.0,
    eps=EPSState(
        battery_soc=0.85,
        solar_array_current=7.5,
        bus_voltage=28.8,
        load_current=5.0,
    ),
    tcs=TCSState(
        panel_temp=38.0,
        battery_temp=22.0,
        heater_active=False,
        in_eclipse=False,
    ),
    adcs=ADCSState(
        attitude_error=0.5,      # small non-zero hover from proportional feedback
        reaction_wheel_speed=1200.0,
    ),
    obc=OBCState(
        free_memory_mb=340.0,
        cpu_load=0.36,
        watchdog_trips=0,
    ),
    ttc=TTCState(
        signal_strength=-75.0,
        bit_error_rate=0.011,
        ground_contact_remaining=0.0,
    ),
    propulsion=PropulsionState(
        fuel_remaining=48.5,
        thruster_temp=21.0,
    ),
    active_fault=None,
    fault_severity=0.0,
)

# ─────────────────────────────────────────────────────────────────────────────
# Monte Carlo outcome thresholds
# ─────────────────────────────────────────────────────────────────────────────
# Revisit when ORACLE is calibrated against mission parameters.

_MC_NOMINAL_SOC_MIN: float = 0.40
_MC_NOMINAL_ATTITUDE_MAX: float = 15.0    # degrees
_MC_NOMINAL_WATCHDOG_MAX: int = 2

_MC_LOSS_SOC_MIN: float = 0.05
_MC_LOSS_ATTITUDE_MAX: float = 90.0       # degrees — totally lost pointing
_MC_LOSS_BER_MAX: float = 0.95            # near-total comms loss

# ─────────────────────────────────────────────────────────────────────────────
# Internal: one simulation step
# ─────────────────────────────────────────────────────────────────────────────


def _step(
    state: SatelliteState,
    t: float,
    dt: float,
    orbit: OrbitClock,
    fault_name: str | None,
    fault_onset: float,
    fault_severity: float,
    recovery_mods: dict[str, dict[str, float]],
    counters: InternalCounters,
    rng: np.random.Generator,
) -> SatelliteState:
    """
    Advance state by one dt step.

    Causal step order:
        1. Fault modifiers computed at time t
        2. Propulsion stepped (generates heat/disturbance outputs for TCS/ADCS)
        3. TCS stepped (uses propulsion heat output; generates battery_temp for EPS)
        4. ADCS stepped (uses obc_blind flag; generates attitude_error for EPS/TT&C)
        5. OBC stepped (uses panel_temp from TCS)
        6. TT&C stepped (uses attitude_error from ADCS)
        7. EPS stepped (uses solar factor, battery_temp from TCS, pointing from ADCS)
        8. Noise applied to continuous fields
    """
    # 1. Fault modifiers
    if fault_name and t >= fault_onset:
        all_mods = get_fault_modifiers(
            fault_name, t, fault_onset, fault_severity, state.eps.battery_soc
        )
    else:
        all_mods = {"eps": {}, "tcs": {}, "adcs": {}, "obc": {}, "ttc": {}, "prop": {}}

    fault_eps = all_mods["eps"]
    fault_tcs = all_mods["tcs"]
    fault_adcs = all_mods["adcs"]
    fault_obc = all_mods["obc"]
    fault_ttc = all_mods["ttc"]
    fault_prop = all_mods["prop"]

    rec_eps = recovery_mods.get("eps", {})
    rec_tcs = recovery_mods.get("tcs", {})
    rec_adcs = recovery_mods.get("adcs", {})
    rec_obc = recovery_mods.get("obc", {})
    rec_ttc = recovery_mods.get("ttc", {})
    rec_prop = recovery_mods.get("prop", {})

    # 2. Propulsion
    new_prop = step_propulsion(state, dt, fault_prop, rec_prop)

    # 3. TCS (uses propulsion heat and attitude_error)
    # Merge prop heat output from fault into tcs mods
    tcs_mods_with_prop = dict(fault_tcs)
    prop_heat = fault_prop.get("prop_heat_output", 0.0)  # already in fault_tcs via faults.py
    new_tcs = step_tcs(
        state, dt, orbit, t, tcs_mods_with_prop, rec_tcs,
        attitude_error=state.adcs.attitude_error,
        counters=counters,
    )

    # 4. ADCS
    # OBC blind: if current BER > 0.95 (TT&C→OBC data_link cascade)
    obc_blind = state.ttc.bit_error_rate > 0.95
    new_adcs = step_adcs(state, dt, fault_adcs, rec_adcs, obc_blind=obc_blind)

    # 5. OBC (uses panel_temp from the freshly computed TCS state)
    new_obc = step_obc(
        state, dt, t, fault_obc, rec_obc,
        panel_temp=new_tcs.panel_temp,
        counters=counters,
    )

    # 6. TT&C (uses attitude_error from the freshly computed ADCS state)
    new_ttc = step_ttc(
        state, dt, orbit, t, fault_ttc, rec_ttc,
        attitude_error=new_adcs.attitude_error,
    )

    # 7. EPS (uses battery_temp from TCS, pointing efficiency from attitude)
    new_eps = step_eps(
        state, dt, orbit, t, fault_eps, rec_eps,
        battery_temp=new_tcs.battery_temp,
    )

    # Assemble deterministic state
    det_state = SatelliteState(
        timestamp=t + dt,
        eps=new_eps,
        tcs=new_tcs,
        adcs=new_adcs,
        obc=new_obc,
        ttc=new_ttc,
        propulsion=new_prop,
        active_fault=fault_name if (fault_name and t >= fault_onset) else None,
        fault_severity=fault_severity if (fault_name and t >= fault_onset) else 0.0,
    )

    # 8. Noise
    return apply_noise(det_state, rng)


# ─────────────────────────────────────────────────────────────────────────────
# Monte Carlo outcome classifier
# ─────────────────────────────────────────────────────────────────────────────


def _classify_outcome(state: SatelliteState) -> MonteCarloOutcome:
    """
    Classify the final state of a Monte Carlo run into one of three outcomes.

    Thresholds are placeholder defaults — revisit when ORACLE is calibrated.
    """
    # Mission loss: battery depleted OR total pointing loss AND comms lost
    if state.eps.battery_soc < _MC_LOSS_SOC_MIN:
        return MonteCarloOutcome.MISSION_LOSS
    if (
        state.adcs.attitude_error > _MC_LOSS_ATTITUDE_MAX
        and state.ttc.bit_error_rate > _MC_LOSS_BER_MAX
    ):
        return MonteCarloOutcome.MISSION_LOSS

    # Nominal recovery: battery healthy AND pointing acceptable AND watchdog stable
    if (
        state.eps.battery_soc >= _MC_NOMINAL_SOC_MIN
        and state.adcs.attitude_error <= _MC_NOMINAL_ATTITUDE_MAX
        and state.obc.watchdog_trips <= _MC_NOMINAL_WATCHDOG_MAX
    ):
        return MonteCarloOutcome.NOMINAL_RECOVERY

    return MonteCarloOutcome.DEGRADED_OPERATION


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point 1: simulate_scenario
# ─────────────────────────────────────────────────────────────────────────────


def simulate_scenario(
    fault: str | None = None,
    severity: float = 0.7,
    duration: float = 3600.0,
    dt: float = 10.0,
    fault_onset: float | None = None,
    initial_state: SatelliteState | None = None,
    seed: int | None = None,
) -> SimulationResult:
    """
    Run a single forward simulation with optional fault injection.

    Returns a full labeled time series (one SimulationFrame per dt step).
    Feed directly to a dashboard telemetry stream, or use as labeled
    synthetic training data for SENTINEL/SHERLOCK testing.

    Args:
        fault:         Fault name from the FAULT_CATALOG, or None for a clean run.
        severity:      Fault severity in [0, 1]. Ignored if fault is None.
        duration:      Total simulation duration in seconds.
        dt:            Time step size in seconds (default 10s).
        fault_onset:   When to inject the fault. Defaults to 20% into the run,
                       so there are clean pre-fault baseline frames.
        initial_state: Starting state. Uses the default nominal initial state if None.
        seed:          RNG seed for reproducibility. Unseeded (random) if None.

    Returns:
        SimulationResult containing all frames, fault metadata, and run parameters.

    Raises:
        ValueError: If fault name is not in FAULT_CATALOG.
    """
    if fault is not None and fault not in FAULT_CATALOG:
        raise ValueError(
            f"Unknown fault '{fault}'. Valid faults: {sorted(FAULT_CATALOG.keys())}"
        )

    if fault_onset is None:
        fault_onset = 0.2 * duration  # default: 20% into run

    state = initial_state if initial_state is not None else _INITIAL_STATE.model_copy(deep=True)
    orbit = OrbitClock()
    counters = InternalCounters(heater_on=state.tcs.heater_active)
    rng = np.random.default_rng(seed)

    frames: list[SimulationFrame] = []
    t = 0.0
    steps = int(duration / dt)

    for _ in range(steps):
        frames.append(
            SimulationFrame(
                timestamp=t,
                state=state,
                fault_active=fault if (fault and t >= fault_onset) else None,
                fault_onset_time=fault_onset if fault else None,
            )
        )
        state = _step(
            state=state,
            t=t,
            dt=dt,
            orbit=orbit,
            fault_name=fault,
            fault_onset=fault_onset,
            fault_severity=severity,
            recovery_mods={},
            counters=counters,
            rng=rng,
        )
        t += dt

    # Include final state
    frames.append(
        SimulationFrame(
            timestamp=t,
            state=state,
            fault_active=fault if (fault and t >= fault_onset) else None,
            fault_onset_time=fault_onset if fault else None,
        )
    )

    return SimulationResult(
        fault=fault,
        severity=severity,
        duration=duration,
        dt=dt,
        frames=frames,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point 2: run_monte_carlo
# ─────────────────────────────────────────────────────────────────────────────


def run_monte_carlo(
    current_state: SatelliteState,
    proposed_action: str,
    n_runs: int = 100,
    steps: int = 300,
    dt: float = 10.0,
    fault: str | None = None,
    fault_severity: float = 0.7,
) -> MonteCarloResult:
    """
    Run n_runs independent simulations from current_state with proposed_action applied.

    Each run uses a different RNG seed, producing statistically independent
    outcomes. The spread in results is what ORACLE will use to rank proposed
    recovery actions.

    Args:
        current_state:   Starting state (typically the most recent live telemetry snapshot).
        proposed_action: Name from RECOVERY_CATALOG.
        n_runs:          Number of independent simulation runs (default 100).
        steps:           Time steps per run (default 300 × 10s = 50 minutes).
        dt:              Step size in seconds (default 10s).
        fault:           Active fault to simulate forward (if any). Pass the fault
                         currently diagnosed by SHERLOCK.
        fault_severity:  Severity of the ongoing fault.

    Returns:
        MonteCarloResult with rate distributions and summary statistics.

    Raises:
        ValueError: If proposed_action is not in RECOVERY_CATALOG.
    """
    if proposed_action not in RECOVERY_CATALOG:
        raise ValueError(
            f"Unknown recovery action '{proposed_action}'. "
            f"Valid actions: {sorted(RECOVERY_CATALOG.keys())}"
        )

    recovery_mods = get_recovery_modifiers(proposed_action)

    # Fault is considered already active at t=0 in each MC run
    fault_onset = 0.0

    outcome_counts: dict[str, int] = {o.value: 0 for o in MonteCarloOutcome}
    final_socs: list[float] = []
    final_attitude_errors: list[float] = []

    orbit = OrbitClock()

    for run_idx in range(n_runs):
        # Each run gets its own seeded generator → independent noise sequences
        rng = np.random.default_rng(run_idx)
        state = current_state.model_copy(deep=True)
        counters = InternalCounters(heater_on=state.tcs.heater_active)
        t = 0.0

        for _ in range(steps):
            state = _step(
                state=state,
                t=t,
                dt=dt,
                orbit=orbit,
                fault_name=fault,
                fault_onset=fault_onset,
                fault_severity=fault_severity,
                recovery_mods=recovery_mods,
                counters=counters,
                rng=rng,
            )
            t += dt

        outcome = _classify_outcome(state)
        outcome_counts[outcome.value] += 1
        final_socs.append(state.eps.battery_soc)
        final_attitude_errors.append(state.adcs.attitude_error)

    soc_arr = np.array(final_socs)
    return MonteCarloResult(
        proposed_action=proposed_action,
        n_runs=n_runs,
        steps=steps,
        nominal_recovery_rate=outcome_counts[MonteCarloOutcome.NOMINAL_RECOVERY.value] / n_runs,
        degraded_operation_rate=outcome_counts[MonteCarloOutcome.DEGRADED_OPERATION.value] / n_runs,
        mission_loss_rate=outcome_counts[MonteCarloOutcome.MISSION_LOSS.value] / n_runs,
        mean_final_battery_soc=float(soc_arr.mean()),
        mean_final_attitude_error=float(np.mean(final_attitude_errors)),
        std_final_battery_soc=float(soc_arr.std()),
        outcome_counts=outcome_counts,
    )
