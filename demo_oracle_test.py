#!/usr/bin/env python3
"""
demo_oracle_test.py — Standalone Oracle backend smoke-test.

Run from the project root:
    .venv/bin/python demo_oracle_test.py

Tests:
1. Build a realistic SatelliteState (matching the full schema)
2. Call rank_all_actions directly
3. Print every field the frontend adapter needs
4. Simulate what api.py broadcasts over WebSocket (the oracle_simulation message)
"""

import json
import sys
import time
sys.path.insert(0, '.')

from backend.oracle.agent import rank_all_actions
from backend.oracle.schemas import OracleRequest
from backend.simulator.schemas import (
    SatelliteState, EPSState, TCSState, ADCSState, OBCState, TTCState, PropulsionState
)

# ── Build a realistic degraded-satellite state ─────────────────────────────
state = SatelliteState(
    timestamp=120.0,
    eps=EPSState(
        battery_soc=0.52,          # 52% — degraded
        solar_array_current=2.1,
        bus_voltage=26.4,
        load_current=3.8,
    ),
    tcs=TCSState(
        panel_temp=72.0,           # elevated
        battery_temp=38.5,
        heater_active=False,
        in_eclipse=False,
    ),
    adcs=ADCSState(
        attitude_error=4.2,        # drifting
        reaction_wheel_speed=3100.0,
    ),
    obc=OBCState(
        free_memory_mb=180.0,
        cpu_load=0.62,
        watchdog_trips=1,
    ),
    ttc=TTCState(
        signal_strength=-82.0,
        bit_error_rate=0.03,
        ground_contact_remaining=480.0,
    ),
    propulsion=PropulsionState(
        fuel_remaining=1.85,
        thruster_temp=34.0,
    ),
    active_fault='tcs_thermal_runaway',
    fault_severity=0.75,
)

req = OracleRequest(
    current_state=state,
    fault_name='tcs_thermal_runaway',
    fault_severity=0.75,
    n_runs=100,
    steps=300,
)

print("=" * 60)
print("ORACLE BACKEND SMOKE TEST")
print("=" * 60)
print(f"Fault: {req.fault_name} (severity={req.fault_severity})")
print(f"Runs per action: {req.n_runs} | Steps per run: {req.steps}")
print("Running Monte Carlo... (this may take 5-15s)")
print()

t0 = time.time()
resp = rank_all_actions(req)
elapsed = time.time() - t0

print(f"✅  rank_all_actions completed in {elapsed:.1f}s")
print(f"    mode       : {resp.mode}")
print(f"    best_action: {resp.best_action}")
print(f"    num results: {len(resp.results)}")
print()

# ── Print per-action results (matches what api.py broadcasts) ─────────────
print("PER-ACTION RESULTS (sorted by safety_score desc):")
print("-" * 60)
for i, r in enumerate(resp.results):
    mc = r.mc_result
    print(f"  [{i+1}] {r.action_name}")
    print(f"       safety_score          : {r.safety_score:.4f}")
    print(f"       nominal_recovery_rate : {mc.nominal_recovery_rate:.3f}  ({round(mc.nominal_recovery_rate*100)}%)")
    print(f"       degraded_operation_rate:{mc.degraded_operation_rate:.3f}  ({round(mc.degraded_operation_rate*100)}%)")
    print(f"       mission_loss_rate     : {mc.mission_loss_rate:.3f}  ({round(mc.mission_loss_rate*100)}%)")
    print(f"       mean_final_battery_soc: {mc.mean_final_battery_soc:.3f}")
    print(f"       std_final_battery_soc : {mc.std_final_battery_soc:.3f}")
    print(f"       mean_final_attitude   : {mc.mean_final_attitude_error:.3f}°")
    print(f"       flags                 : {r.flags}")
    print()

# ── Simulate exactly what api.py oracle_simulation message looks like ──────
oracle_ws_msg = {
    "type": "oracle_simulation",
    "best_action": resp.best_action,
    "top_score": resp.results[0].safety_score if resp.results else 0.0,
    "mode": resp.mode,
    "results": [
        {
            "action_name": r.action_name,
            "safety_score": r.safety_score,
            "nominal_recovery_rate": r.mc_result.nominal_recovery_rate,
            "degraded_operation_rate": r.mc_result.degraded_operation_rate,
            "mission_loss_rate": r.mc_result.mission_loss_rate,
            "std_final_battery_soc": r.mc_result.std_final_battery_soc,
            "mean_final_battery_soc": r.mc_result.mean_final_battery_soc,
            "flags": r.flags,
        }
        for r in resp.results
    ],
}

print("=" * 60)
print("SIMULATED WebSocket `oracle_simulation` MESSAGE:")
print("=" * 60)
print(json.dumps(oracle_ws_msg, indent=2))
print()
print(f"✅  {len(oracle_ws_msg['results'])} actions in WS message")
print(f"    → frontend adapter will animate {len(oracle_ws_msg['results'])} × 100 = {len(oracle_ws_msg['results'])*100} total runs")
