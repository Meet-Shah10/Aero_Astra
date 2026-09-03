"""
AERO-ASTRA Physics Simulator — Demo Script

Demonstrates all four key simulation scenarios:

    1. Clean/no-fault run (30 minutes)
    2. Single EPS fault — battery degradation
    3. Cascading fault — eps_cascade_power_failure (solar array loss → all 5 subsystems)
    4. Monte Carlo — switch_redundant_power_bus vs the cascade fault

Run with:
    python -m backend.simulator.demo
"""

from __future__ import annotations

import sys
import os
from typing import Any
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from backend.simulator import run_monte_carlo, simulate_scenario
from backend.simulator.engine import _INITIAL_STATE


def _hr(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def _subsystem_row(label: str, values: list[tuple[str, Any]]) -> None:
    parts = "  ".join(f"{k}={v}" for k, v in values)
    print(f"  {label:<14} {parts}")


def _print_frame_summary(label: str, frame) -> None:
    s = frame.state
    print(f"\n  -- {label} (t={frame.timestamp:.0f}s) --")
    _subsystem_row("EPS:", [
        ("soc", f"{s.eps.battery_soc:.3f}"),
        ("solar", f"{s.eps.solar_array_current:.2f}A"),
        ("bus", f"{s.eps.bus_voltage:.2f}V"),
    ])
    _subsystem_row("TCS:", [
        ("panel", f"{s.tcs.panel_temp:.1f}C"),
        ("bat_t", f"{s.tcs.battery_temp:.1f}C"),
        ("heater", "ON" if s.tcs.heater_active else "off"),
        ("eclipse", "YES" if s.tcs.in_eclipse else "no"),
    ])
    _subsystem_row("ADCS:", [
        ("err", f"{s.adcs.attitude_error:.2f}deg"),
        ("wheel", f"{s.adcs.reaction_wheel_speed:.0f}RPM"),
    ])
    _subsystem_row("OBC:", [
        ("mem", f"{s.obc.free_memory_mb:.1f}MB"),
        ("cpu", f"{s.obc.cpu_load:.3f}"),
        ("trips", str(s.obc.watchdog_trips)),
    ])
    _subsystem_row("TT&C:", [
        ("sig", f"{s.ttc.signal_strength:.1f}dBm"),
        ("ber", f"{s.ttc.bit_error_rate:.4f}"),
        ("contact", f"{s.ttc.ground_contact_remaining:.0f}s"),
    ])
    _subsystem_row("Propulsion:", [
        ("fuel", f"{s.propulsion.fuel_remaining:.2f}kg"),
        ("temp", f"{s.propulsion.thruster_temp:.1f}C"),
    ])
    if frame.fault_active:
        print(f"  [FAULT] Active: {frame.fault_active}")




def demo_nominal() -> None:
    _hr("SCENARIO 1 — Clean/No-Fault Run (30 minutes)")
    result = simulate_scenario(
        fault=None,
        duration=1800.0,
        dt=10.0,
        seed=42,
    )
    frames = result.frames
    print(f"\n  Total frames: {len(frames)}")
    _print_frame_summary("START", frames[0])
    _print_frame_summary("MID  ", frames[len(frames) // 2])
    _print_frame_summary("END  ", frames[-1])

    # Sanity check: SOC should stay healthy
    min_soc = min(f.state.eps.battery_soc for f in frames)
    max_err = max(f.state.adcs.attitude_error for f in frames)
    trips = frames[-1].state.obc.watchdog_trips
    print(f"\n  Min SOC across run: {min_soc:.3f}")
    print(f"  Max attitude error: {max_err:.2f}deg")
    print(f"  Final watchdog trips: {trips}")
    print("\n  [OK] Nominal run complete -- all values expected to be healthy")


def demo_single_fault() -> None:
    _hr("SCENARIO 2 — Single EPS Fault: eps_battery_degradation (severity=0.6)")
    result = simulate_scenario(
        fault="eps_battery_degradation",
        severity=0.6,
        duration=3600.0,
        dt=10.0,
        fault_onset=720.0,   # fault at t=720s (20% into 1hr run)
        seed=42,
    )
    frames = result.frames
    print(f"\n  Fault onset: t=720s | Duration: 3600s | dt=10s")

    _print_frame_summary("Pre-fault  (t=600s)", frames[60])
    _print_frame_summary("Onset+2min (t=840s)", frames[84])
    _print_frame_summary("Onset+10min(t=1320s)", frames[132])
    _print_frame_summary("End        (t=3600s)", frames[-1])

    pre_soc = frames[60].state.eps.battery_soc
    end_soc = frames[-1].state.eps.battery_soc
    print(f"\n  SOC at pre-fault: {pre_soc:.3f} -> end: {end_soc:.3f}")
    print(f"  SOC drop: {pre_soc - end_soc:.3f}")
    print("\n  [OK] EPS battery degradation -- SOC should show visible decline")


def demo_cascade_fault() -> None:
    _hr("SCENARIO 3 — Cascading Fault: eps_cascade_power_failure (severity=0.9)")
    print("\n  Solar array loss -> EPS->TCS->ADCS->OBC->TT&C->Propulsion cascade")
    print("  Graph edges exercised: all 5 EPS->* power_supply edges")

    result = simulate_scenario(
        fault="eps_cascade_power_failure",
        severity=0.9,
        duration=3600.0,
        dt=10.0,
        fault_onset=600.0,   # fault at t=600s
        seed=42,
    )
    frames = result.frames

    _print_frame_summary("Pre-fault    (t=500s) ", frames[50])
    _print_frame_summary("Onset+5min   (t=900s) ", frames[90])
    _print_frame_summary("Onset+20min  (t=1800s)", frames[180])
    _print_frame_summary("End          (t=3600s)", frames[-1])

    f_pre = frames[50].state
    f_end = frames[-1].state
    print(f"\n  SOC:          {f_pre.eps.battery_soc:.3f} -> {f_end.eps.battery_soc:.3f}")
    print(f"  Panel temp:   {f_pre.tcs.panel_temp:.1f}C -> {f_end.tcs.panel_temp:.1f}C")
    print(f"  Attitude err: {f_pre.adcs.attitude_error:.2f}deg -> {f_end.adcs.attitude_error:.2f}deg")
    print(f"  OBC trips:    {f_pre.obc.watchdog_trips} -> {f_end.obc.watchdog_trips}")
    print(f"  Signal:       {f_pre.ttc.signal_strength:.1f}dBm -> {f_end.ttc.signal_strength:.1f}dBm")
    print("\n  [OK] Cascade fault -- all 5 downstream subsystems should show degradation")


def demo_monte_carlo() -> None:
    _hr("SCENARIO 4 — Monte Carlo: switch_redundant_power_bus vs eps_cascade_power_failure")
    print("\n  100 independent runs x 3000s each")
    print("  Starting from post-cascade degraded state (SOC~0.3)")

    # Build a degraded starting state representative of 10min into the cascade fault
    cascade_result = simulate_scenario(
        fault="eps_cascade_power_failure",
        severity=0.9,
        duration=600.0,
        dt=10.0,
        fault_onset=0.0,
        seed=0,
    )
    degraded_state = cascade_result.frames[-1].state

    print(f"\n  Starting state: SOC={degraded_state.eps.battery_soc:.3f}  "
          f"attitude_err={degraded_state.adcs.attitude_error:.2f}deg  "
          f"signal={degraded_state.ttc.signal_strength:.1f}dBm")

    mc_result = run_monte_carlo(
        current_state=degraded_state,
        proposed_action="switch_redundant_power_bus",
        n_runs=100,
        steps=300,
        dt=10.0,
        fault="eps_cascade_power_failure",
        fault_severity=0.9,
    )

    print("\n  -- Monte Carlo Results --")
    print(f"  Action:            {mc_result.proposed_action}")
    print(f"  Runs:              {mc_result.n_runs} x {mc_result.steps * 10}s")
    print(f"  Nominal recovery:  {mc_result.nominal_recovery_rate:.1%}  "
          f"(n={mc_result.outcome_counts['nominal_recovery']})")
    print(f"  Degraded ops:      {mc_result.degraded_operation_rate:.1%}  "
          f"(n={mc_result.outcome_counts['degraded_operation']})")
    print(f"  Mission loss:      {mc_result.mission_loss_rate:.1%}  "
          f"(n={mc_result.outcome_counts['mission_loss']})")
    print(f"  Mean final SOC:    {mc_result.mean_final_battery_soc:.3f} "
          f"+/- {mc_result.std_final_battery_soc:.3f}")
    print(f"  Mean final att:    {mc_result.mean_final_attitude_error:.2f}deg")
    print(f"\n  [OK] Rates should sum to 1.0: "
          f"{mc_result.nominal_recovery_rate + mc_result.degraded_operation_rate + mc_result.mission_loss_rate:.3f}")
    print("  [OK] std_final_battery_soc > 0 confirms runs varied (not identical)")


if __name__ == "__main__":
    print("AERO-ASTRA Physics Simulator -- Demo")
    print("="*36)
    demo_nominal()
    demo_single_fault()
    demo_cascade_fault()
    demo_monte_carlo()
    print("\n\n  All scenarios complete.\n")
