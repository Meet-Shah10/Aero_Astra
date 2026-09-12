"""
AERO-ASTRA — Replay Playlist Generator
========================================
Pre-generates a physics-simulated telemetry playlist that streams nominally,
then develops a fault autonomously (no user trigger), then recovers and loops.

The playlist rotates through 3 fault types so longer demo sessions show variety:
  Loop 1: tcs_thermal_runaway
  Loop 2: propulsion_thruster_fault
  Loop 3: eps_cascade_power_failure

Each loop is structured as 4 acts:
  Act 1 — NOMINAL      (60s)  : Clean baseline, SENTINEL sees nothing
  Act 2 — FAULT ONSET  (600s) : Fault ramps from onset=120s, builds naturally
  Act 3 — POST-DETECT  (30s)  : Nominal batch, pipeline outputs still streaming
  Act 4 — RECOVERY     (30s)  : Return to clean baseline

Total per loop: ~720s = 720 frames at dt=1.0s
At 10fps streaming: ~72s wall-clock per loop.

Outputs:
  backend/replay/playlist.json   (~3-4MB, pre-serialised frame data)

Usage:
  python backend/replay/generate.py          # regenerate playlist
  python backend/replay/generate.py --fast   # shorter acts for rapid testing
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # project root
sys.path.insert(0, str(ROOT))

from backend.simulator.engine import simulate_scenario

OUT = Path(__file__).resolve().parent / "playlist.json"

# ─────────────────────────────────────────────────────────────────────────────
# Playlist structure
# ─────────────────────────────────────────────────────────────────────────────
#
# Each loop entry defines one full streaming cycle.
# fault_onset is set to 120s inside a 600s run — that gives 2 minutes of
# pre-fault baseline within the fault act, then the fault ramps over its
# ramp_time_s (15–120s depending on fault type), crosses VITALS thresholds,
# and SENTINEL fires autonomously.

LOOPS = [
    {
        "loop_id": 1,
        "fault": "tcs_thermal_runaway",
        "severity": 0.85,
        "label": "TCS Thermal Runaway",
        "subsystem": "TCS",
    },
    {
        "loop_id": 2,
        "fault": "propulsion_thruster_fault",
        "severity": 0.85,
        "label": "Propulsion Thruster Fault",
        "subsystem": "Propulsion",
    },
    {
        "loop_id": 3,
        "fault": "eps_cascade_power_failure",
        "severity": 0.85,
        "label": "EPS Cascade Power Failure",
        "subsystem": "EPS",
    },
]


def _state_to_dict(state) -> dict:
    """Serialise a SatelliteState to a plain dict suitable for JSON."""
    return {
        "eps": {
            "battery_soc": state.eps.battery_soc,
            "solar_array_current": state.eps.solar_array_current,
            "bus_voltage": state.eps.bus_voltage,
            "load_current": state.eps.load_current,
        },
        "tcs": {
            "panel_temp": state.tcs.panel_temp,
            "battery_temp": state.tcs.battery_temp,
            "heater_active": state.tcs.heater_active,
            "in_eclipse": state.tcs.in_eclipse,
        },
        "adcs": {
            "attitude_error": state.adcs.attitude_error,
            "reaction_wheel_speed": state.adcs.reaction_wheel_speed,
        },
        "obc": {
            "free_memory_mb": state.obc.free_memory_mb,
            "cpu_load": state.obc.cpu_load,
            "watchdog_trips": state.obc.watchdog_trips,
        },
        "ttc": {
            "signal_strength": state.ttc.signal_strength,
            "bit_error_rate": state.ttc.bit_error_rate,
            "ground_contact_remaining": state.ttc.ground_contact_remaining,
        },
        "propulsion": {
            "fuel_remaining": state.propulsion.fuel_remaining,
            "thruster_temp": state.propulsion.thruster_temp,
        },
        "active_fault": state.active_fault,
        "fault_severity": state.fault_severity,
    }


def _frame_to_dict(frame, act_name: str, loop_id: int, fault_label: str) -> dict:
    """Serialise a SimulationFrame enriched with act/loop metadata."""
    return {
        "timestamp": frame.timestamp,
        "act": act_name,
        "loop_id": loop_id,
        "fault_label": fault_label,
        "fault_active": frame.fault_active,
        "state": _state_to_dict(frame.state),
    }


def generate(fast: bool = False) -> dict:
    """
    Generate the full playlist and return it as a dict.

    In fast mode (--fast), act durations are halved — useful for quick
    iteration and CI testing.
    """
    scale = 0.5 if fast else 1.0

    nominal_duration  = int(60  * scale)   # Act 1: pre-fault baseline
    fault_duration    = int(600 * scale)   # Act 2: fault develops
    fault_onset       = int(120 * scale)   # fault starts this many seconds into Act 2
    recovery_duration = int(60  * scale)   # Act 3+4: post-detect cool-down

    playlist_loops = []

    for loop_def in LOOPS:
        print(f"\n[Loop {loop_def['loop_id']}] {loop_def['label']}")
        acts = []

        # ── Act 1: Nominal baseline ────────────────────────────────────────────
        print(f"  Generating Act 1 (nominal, {nominal_duration}s)…")
        nom1 = simulate_scenario(
            fault=None,
            duration=float(nominal_duration),
            dt=1.0,
            seed=loop_def["loop_id"] * 100,
        )
        acts.append({
            "name": "nominal",
            "frames": [
                _frame_to_dict(f, "nominal", loop_def["loop_id"], loop_def["label"])
                for f in nom1.frames
            ],
        })
        print(f"    → {len(nom1.frames)} frames")

        # ── Act 2: Fault develops ──────────────────────────────────────────────
        print(f"  Generating Act 2 (fault={loop_def['fault']}, {fault_duration}s, onset={fault_onset}s)…")
        fault_sim = simulate_scenario(
            fault=loop_def["fault"],
            severity=loop_def["severity"],
            duration=float(fault_duration),
            dt=1.0,
            fault_onset=float(fault_onset),
            seed=loop_def["loop_id"] * 100 + 1,
        )
        acts.append({
            "name": "fault_developing",
            "frames": [
                _frame_to_dict(f, "fault_developing", loop_def["loop_id"], loop_def["label"])
                for f in fault_sim.frames
            ],
        })
        print(f"    → {len(fault_sim.frames)} frames  "
              f"(fault active from frame {fault_onset})")

        # ── Act 3: Recovery / cool-down ────────────────────────────────────────
        # Continue from end of fault sim so there's no state discontinuity.
        # Fault is still on, severity fading — simulates the system stabilising
        # after ATHENA's recovery action has been applied.
        print(f"  Generating Act 3 (recovery, {recovery_duration}s)…")
        last_state = fault_sim.frames[-1].state
        recovery_sim = simulate_scenario(
            fault=loop_def["fault"],
            severity=max(0.1, loop_def["severity"] * 0.3),  # severity drops post-recovery
            duration=float(recovery_duration),
            dt=1.0,
            fault_onset=0.0,
            initial_state=last_state,
            seed=loop_def["loop_id"] * 100 + 2,
        )
        acts.append({
            "name": "recovery",
            "frames": [
                _frame_to_dict(f, "recovery", loop_def["loop_id"], loop_def["label"])
                for f in recovery_sim.frames
            ],
        })
        print(f"    → {len(recovery_sim.frames)} frames")

        playlist_loops.append({
            "loop_id":    loop_def["loop_id"],
            "fault":      loop_def["fault"],
            "severity":   loop_def["severity"],
            "label":      loop_def["label"],
            "subsystem":  loop_def["subsystem"],
            "fault_onset_frame": nominal_duration + fault_onset,  # absolute frame idx
            "acts": acts,
        })

    total_frames = sum(
        len(act["frames"])
        for loop in playlist_loops
        for act in loop["acts"]
    )
    print(f"\nTotal frames across all loops: {total_frames}")
    print(f"Wall-clock at 10fps: ~{total_frames / 10 / 60:.1f} minutes per full rotation")

    return {
        "version": 1,
        "generated_by": "backend/replay/generate.py",
        "loops": playlist_loops,
        "total_frames": total_frames,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate AERO-ASTRA replay playlist")
    parser.add_argument("--fast", action="store_true",
                        help="Half-length acts — quick iteration mode")
    parser.add_argument("--out", default=str(OUT),
                        help=f"Output path (default: {OUT})")
    args = parser.parse_args()

    print("AERO-ASTRA — Replay Playlist Generator")
    print("=" * 50)

    playlist = generate(fast=args.fast)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(playlist, f, separators=(",", ":"))   # compact, no indent — smaller file

    size_mb = out_path.stat().st_size / 1_048_576
    print(f"\n✅ Playlist written → {out_path}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
