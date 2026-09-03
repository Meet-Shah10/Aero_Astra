"""
SHERLOCK -- Live Demo Script
Agent 3 of AERO-ASTRA | Root-Cause Diagnosis

Runs 3 realistic anomaly scenarios via OpenRouter (Claude 3.5 Sonnet).
Requires OPENROUTER_API_KEY set in environment or a .env file at project root.

Usage:
    cd c:\\Users\\ASUS\\Desktop\\Harsh\\PROJECTS\\Aero_Astra
    python -m backend.sherlock.tests.demo

Each scenario prints:
  - The graph candidate set (verifiable by hand)
  - The full SherlockDiagnosis as JSON
  - A human-readable summary for operator review

Scenarios:
  1. EPS battery undervoltage (self-fault)
  2. ADCS attitude drift (root cause: TCS thermal stress on gyroscope)
  3. OBC reboot loop (root cause: TCS board overtemperature)
"""

from __future__ import annotations

import json
import logging
import os
import sys

# Force UTF-8 output on Windows (avoids cp1252 UnicodeEncodeError)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is in path when running as script
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load .env file if present (for OPENROUTER_API_KEY)
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass  # python-dotenv not installed; key must be in environment

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("SHERLOCK.demo")

from backend.sherlock import (
    SherlockAgent,
    AnomalyEvent,
    MockTelemetryProvider,
    SeverityLevel,
)


# ─────────────────────────────────────────────────────────────────────────────
# Scenario definitions
# ─────────────────────────────────────────────────────────────────────────────

NOW = datetime.now(timezone.utc)


def scenario_1_eps_battery_undervoltage() -> tuple[AnomalyEvent, MockTelemetryProvider]:
    """
    Scenario 1: Battery Undervoltage — EPS self-fault
    
    SENTINEL has flagged battery_voltage_v dropping to 21.3V (nominal: 28V).
    State of charge is 18% and falling. Solar current is nominal.
    Expected SHERLOCK diagnosis: EPS primary fault (battery cell failure),
    cascade to TCS (heaters losing power) and ADCS (reaction wheels spinning down).
    """
    event = AnomalyEvent(
        anomaly_id="ANO-2026-001",
        flagged_subsystem="EPS",
        flagged_parameter="battery_voltage_v",
        severity=SeverityLevel.CRITICAL,
        confidence_score=0.91,
        timestamp=NOW,
        telemetry_window=[
            {"battery_voltage_v": 27.8, "battery_soc_pct": 85.0, "solar_current_a": 4.2},
            {"battery_voltage_v": 26.1, "battery_soc_pct": 62.0, "solar_current_a": 4.1},
            {"battery_voltage_v": 23.4, "battery_soc_pct": 35.0, "solar_current_a": 4.3},
            {"battery_voltage_v": 21.3, "battery_soc_pct": 18.0, "solar_current_a": 4.2},
        ],
        event_log_context=(
            "T-180s: Solar panels reported nominal current (4.2A).\n"
            "T-90s:  Battery voltage began rapid decline independent of eclipse entry.\n"
            "T-30s:  PCDU raised undervoltage warning flag.\n"
            "T-0s:   SENTINEL flagged anomaly. Charge controller still active."
        ),
    )
    
    provider = MockTelemetryProvider()
    provider.inject_fault("EPS", {
        "battery_voltage_v": 21.3,
        "battery_soc_pct": 18.0,
        "solar_current_a": 4.2,   # solar OK — it's not a generation issue
        "bus_voltage_v": 21.1,
        "charge_current_a": 0.1,  # charge rate collapsed
    })
    provider.inject_fault("TCS", {
        "battery_temp_c": 12.0,   # battery cooling due to low activity
        "panel_temp_c": 42.0,
    })
    
    return event, provider


def scenario_2_adcs_attitude_drift() -> tuple[AnomalyEvent, MockTelemetryProvider]:
    """
    Scenario 2: ADCS Attitude Drift — Root cause is TCS (gyroscope overtemperature)
    
    SENTINEL has flagged pointing_error_deg exceeding 4.7° (nominal: < 0.1°).
    Reaction wheel speeds are nominal; the issue is gyroscope drift.
    Gyroscope housing temperature is 71°C (operating limit: 65°C).
    Expected: TCS → ADCS cascade. Root cause: TCS (thermal stress on gyro).
    """
    event = AnomalyEvent(
        anomaly_id="ANO-2026-002",
        flagged_subsystem="ADCS",
        flagged_parameter="pointing_error_deg",
        severity=SeverityLevel.HIGH,
        confidence_score=0.87,
        timestamp=NOW,
        telemetry_window=[
            {"pointing_error_deg": 0.06, "reaction_wheel_rpm": 1200, "star_tracker_confidence": 0.98},
            {"pointing_error_deg": 0.41, "reaction_wheel_rpm": 1198, "star_tracker_confidence": 0.95},
            {"pointing_error_deg": 1.83, "reaction_wheel_rpm": 1201, "star_tracker_confidence": 0.71},
            {"pointing_error_deg": 4.70, "reaction_wheel_rpm": 1199, "star_tracker_confidence": 0.18},
        ],
        event_log_context=(
            "T-600s: Payload thermal controller reported elevated dissipation.\n"
            "T-300s: Gyroscope housing temp crossed 65°C threshold (high-temp alarm).\n"
            "T-120s: Star tracker confidence degraded from 0.98 → 0.71.\n"
            "T-0s:   Pointing error exceeded 4.5° limit. SENTINEL flagged."
        ),
    )
    
    provider = MockTelemetryProvider()
    provider.inject_fault("TCS", {
        "battery_temp_c": 19.0,
        "panel_temp_c": 48.0,
        "payload_temp_c": 67.0,   # payload running hot
        "radiator_temp_c": 71.0,  # radiator saturated
        "obc_board_temp_c": 35.0,
    })
    provider.inject_fault("ADCS", {
        "pointing_error_deg": 4.70,
        "reaction_wheel_rpm": 1199.0,
        "magnetorquer_current_a": 0.4,
        "star_tracker_confidence": 0.18,  # gyro drift → star tracker lost
        "angular_rate_deg_s": 0.02,
    })
    
    return event, provider


def scenario_3_obc_reboot_loop() -> tuple[AnomalyEvent, MockTelemetryProvider]:
    """
    Scenario 3: OBC Reboot Loop — Root cause is TCS (board overtemperature)
    
    OBC has rebooted 7 times in the last hour. Watchdog trips are persistent.
    CPU temperature is 81°C (thermal throttle threshold: 75°C, shutdown: 85°C).
    Software integrity checks pass — this is a thermal issue, not a software bug.
    Expected: TCS → OBC cascade. Root cause: TCS.
    """
    event = AnomalyEvent(
        anomaly_id="ANO-2026-003",
        flagged_subsystem="OBC",
        flagged_parameter="reboot_count_1h",
        severity=SeverityLevel.CRITICAL,
        confidence_score=0.94,
        timestamp=NOW,
        telemetry_window=[
            {"reboot_count_1h": 0, "cpu_load_pct": 44, "watchdog_trips_1h": 0},
            {"reboot_count_1h": 1, "cpu_load_pct": 43, "watchdog_trips_1h": 1},
            {"reboot_count_1h": 4, "cpu_load_pct": 41, "watchdog_trips_1h": 4},
            {"reboot_count_1h": 7, "cpu_load_pct": 38, "watchdog_trips_1h": 7},
        ],
        event_log_context=(
            "T-3600s: Payload imaging campaign started (high CPU + GPU load).\n"
            "T-1800s: OBC board temperature crossed 75°C thermal throttle threshold.\n"
            "T-900s:  First watchdog trip and reboot detected.\n"
            "T-0s:    7 reboots in 1 hour. Software integrity: PASS. SENTINEL flagged.\n"
            "Note: Software image checksum verified nominal after each reboot."
        ),
    )
    
    provider = MockTelemetryProvider()
    provider.inject_fault("TCS", {
        "battery_temp_c": 21.0,
        "panel_temp_c": 50.0,
        "payload_temp_c": 74.0,
        "radiator_temp_c": 68.0,
        "obc_board_temp_c": 81.0,  # primary indicator: OBC board overtemp
    })
    provider.inject_fault("OBC", {
        "cpu_load_pct": 38.0,     # throttled
        "ram_usage_pct": 59.0,
        "reboot_count_1h": 7.0,
        "uptime_hours": 0.1,      # recently rebooted
        "watchdog_trips_1h": 7.0,
    })
    
    return event, provider


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

SEPARATOR = "=" * 70

def print_diagnosis(scenario_name: str, diagnosis) -> None:
    print(f"\n{SEPARATOR}")
    print(f"  RESULT: {scenario_name}")
    print(SEPARATOR)
    print(f"  Root Cause    : {diagnosis.primary_root_cause}")
    print(f"  Causal Chain  : {' → '.join(diagnosis.causal_chain)}")
    print(f"  Urgency       : {diagnosis.urgency.value}")
    print(f"  Time to Crit  : {diagnosis.time_to_critical_estimate_minutes} minutes")
    print(f"  Confidence    : {diagnosis.confidence_score:.0%}")
    print(f"  LLM Attempts  : {diagnosis.llm_attempts}")
    print(f"  Candidates    : {sorted(diagnosis.graph_candidate_set)}")
    print(f"\n  Reasoning:\n    {diagnosis.reasoning}")
    print(f"\n  Full JSON:\n{diagnosis.model_dump_json(indent=4)}")


def run_scenario(
    agent: SherlockAgent,
    name: str,
    event: AnomalyEvent,
    provider: MockTelemetryProvider,
) -> bool:
    print(f"\n{SEPARATOR}")
    print(f"  SCENARIO: {name}")
    print(f"  Flagged: {event.flagged_subsystem}.{event.flagged_parameter} "
          f"| Severity: {event.severity.value} | Confidence: {event.confidence_score:.0%}")
    print(SEPARATOR)

    # Print candidate set BEFORE LLM call (verifiable by hand)
    candidates = agent.get_candidates_for(event.flagged_subsystem)
    print(f"\n  Graph candidate set (depth=1): {sorted(candidates)}")
    print(f"  (These are the ONLY valid root cause options for the LLM)")

    try:
        diagnosis = agent.diagnose(event, telemetry_provider=provider)
        print_diagnosis(name, diagnosis)
        return True
    except Exception as e:
        print(f"\n  ❌ SHERLOCK failed: {type(e).__name__}: {e}")
        return False


def main() -> None:
    print(f"\n{'#' * 70}")
    print("  SHERLOCK — Live Demo | AERO-ASTRA Agent 3")
    print(f"{'#' * 70}")
    print("\nRunning 3 anomaly diagnosis scenarios via OpenRouter (Claude 3.5 Sonnet)...")
    print("(Requires OPENROUTER_API_KEY in environment or .env file)\n")

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY not set.")
        print("  Set it via: export OPENROUTER_API_KEY=sk-or-v1-...")
        print("  Or create a .env file at project root with: OPENROUTER_API_KEY=sk-or-v1-...")
        sys.exit(1)

    agent = SherlockAgent(api_key=api_key)
    
    print("\n" + SEPARATOR)
    print("  SATELLITE DEPENDENCY GRAPH SUMMARY")
    print(SEPARATOR)
    print(agent.get_graph_summary())

    scenarios = [
        ("Scenario 1: EPS Battery Undervoltage (Self-Fault)",
         *scenario_1_eps_battery_undervoltage()),
        ("Scenario 2: ADCS Attitude Drift (TCS Thermal Root Cause)",
         *scenario_2_adcs_attitude_drift()),
        ("Scenario 3: OBC Reboot Loop (TCS Overtemperature Root Cause)",
         *scenario_3_obc_reboot_loop()),
    ]

    results = []
    for name, event, provider in scenarios:
        success = run_scenario(agent, name, event, provider)
        results.append((name, success))

    print(f"\n\n{'#' * 70}")
    print("  DEMO COMPLETE — Summary")
    print(f"{'#' * 70}")
    for name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"  {status}  {name}")

    all_pass = all(s for _, s in results)
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
