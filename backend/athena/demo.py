"""
AERO-ASTRA — ATHENA Demo Script
=================================
Full diagnosis-to-plan pipeline for two fault scenarios.

Runs the complete SHERLOCK → ORACLE → ATHENA pipeline end-to-end using real
LLM calls (SHERLOCK + ATHENA) and real Monte Carlo simulation (ORACLE).
Fault scenarios match those already established across the simulator,
SHERLOCK, and ORACLE demos for narrative consistency.

Scenarios:
    A. TCS thermal runaway — severity=0.7, seed=1
       (established in simulator demo, SHERLOCK demo, and ORACLE demo §7)
    B. Propulsion thruster fault — severity=0.8, seed=7
       (same as ORACLE demo Scenario C)

Requirements:
    OPENROUTER_API_KEY must be set in environment or a .env file at project root.

Run with:
    python -m backend.athena.demo
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Ensure project root is in path when running as script
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load .env file if present (for OPENROUTER_API_KEY)
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

logging.basicConfig(
    level=logging.WARNING,   # suppress INFO noise for clean demo output
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ATHENA.demo")

from backend.simulator import simulate_scenario
from backend.oracle.agent import run_oracle
from backend.oracle.schemas import OracleRequest
from backend.sherlock.agent import SherlockAgent
from backend.sherlock.schemas import AnomalyEvent, SeverityLevel
from backend.sentinel.engine_b import score_state
from backend.athena.agent import AthenaAgent
from backend.athena.schemas import MissionConstraints, RecoveryPlan, RecoveryOption


# ─────────────────────────────────────────────────────────────────────────────
# Display helpers
# ─────────────────────────────────────────────────────────────────────────────

SEP   = "=" * 72
HSEP  = "-" * 72
NOW   = datetime.now(timezone.utc)


def _hr(title: str) -> None:
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)


def _section(title: str) -> None:
    print(f"\n  {HSEP}")
    print(f"  {title}")
    print(f"  {HSEP}")


def _print_oracle_summary(oracle_resp) -> None:
    print(f"\n  ORACLE ranked {len(oracle_resp.results)} actions:")
    print(f"  {'Rank':<5} {'Action':<38} {'Score':>7}  {'Nominal':>8}  {'Loss':>7}  Flags")
    print(f"  {'-' * 70}")
    for i, r in enumerate(oracle_resp.results, 1):
        flags = ", ".join(r.flags) if r.flags else "-"
        marker = "  <-- BEST" if r.action_name == oracle_resp.best_action else ""
        mc = r.mc_result
        print(
            f"  {i:<5} {r.action_name:<38} {r.safety_score:>+7.3f}  "
            f"{mc.nominal_recovery_rate:>8.1%}  {mc.mission_loss_rate:>7.1%}  "
            f"{flags}{marker}"
        )


def _print_plan(plan: RecoveryPlan) -> None:
    print(f"\n  RECOMMENDED ACTION: {plan.recommended_action}")
    print(f"  LLM Attempts: {plan.llm_attempts}")

    print(f"\n  REASONING CHAIN:")
    for i, step in enumerate(plan.reasoning_cot, 1):
        print(f"    [{i}] {step}")

    print(f"\n  OVERALL: {plan.overall_reasoning}")

    for i, opt in enumerate(plan.options, 1):
        irrev_tag = " [IRREVERSIBLE]" if opt.is_irreversible else ""
        print(f"\n  OPTION {i}: {opt.action_name}{irrev_tag}")
        print(f"    blended_rank    : {opt.blended_rank:.4f}")
        print(f"    safety_score    : {opt.safety_score:+.3f}  (from ORACLE)")
        print(f"    effectiveness   : {opt.effectiveness_score:.2f}")
        print(f"    operator_effort : {opt.operator_effort.value}")
        print(f"    predicted_outcome: {opt.predicted_outcome}")
        if opt.contra_indications:
            print(f"    contra_indications:")
            for c in opt.contra_indications:
                print(f"      - {c}")
        print(f"    procedure_steps:")
        for j, step in enumerate(opt.procedure_steps, 1):
            print(f"      {j}. {step}")

    # WebSocket contract preview
    ws = plan.to_ws_message()
    print(f"\n  WS MESSAGE PREVIEW (type='{ws['type']}'):")
    print(f"    primary_action : {ws['primary_action']}")
    print(f"    steps          : {len(ws['steps'])} step(s) for recommended action")


# ─────────────────────────────────────────────────────────────────────────────
# Scenario helpers
# ─────────────────────────────────────────────────────────────────────────────


def _build_anomaly_event_from_sentinel(
    state,
    anomaly_id: str,
    flagged_subsystem: str,
    flagged_parameter: str,
    sentinel_score: dict,
) -> AnomalyEvent:
    """Build an AnomalyEvent using SENTINEL's score output."""
    severity = (
        SeverityLevel.CRITICAL if sentinel_score["score"] > 0.85 else SeverityLevel.HIGH
    )
    return AnomalyEvent(
        anomaly_id=anomaly_id,
        flagged_subsystem=flagged_subsystem,
        flagged_parameter=flagged_parameter,
        severity=severity,
        confidence_score=min(0.99, sentinel_score["score"]),
        timestamp=NOW,
        telemetry_window=[],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Scenario A: TCS thermal runaway
# ─────────────────────────────────────────────────────────────────────────────


def demo_scenario_a(sherlock: SherlockAgent, athena: AthenaAgent) -> bool:
    _hr("SCENARIO A — TCS Thermal Runaway (severity=0.7, seed=1)")
    print("\n  Pipeline: Simulator → SENTINEL → SHERLOCK → ORACLE → ATHENA")
    print("  Narrative: same fault scenario established in simulator and SHERLOCK demos.")

    # ── Step 1: Simulate ────────────────────────────────────────────────────
    print("\n  [1/4] Simulating fault (duration=1800s, dt=10s)...")
    result = simulate_scenario(
        fault="tcs_thermal_runaway",
        severity=0.7,
        duration=1800,
        dt=10,
        seed=1,
    )
    state = result.frames[-1].state
    print(f"       Final panel_temp  = {state.tcs.panel_temp:.1f}°C")
    print(f"       Final battery_soc = {state.eps.battery_soc:.3f}")
    print(f"       Total frames      = {len(result.frames)}")

    # ── Step 2: SENTINEL score ──────────────────────────────────────────────
    sentinel_score = score_state(state)
    print(f"\n  [2/4] SENTINEL score   = {sentinel_score['score']:.3f}  "
          f"worst_param={sentinel_score['worst_param']}")
    if sentinel_score["score"] < 0.5:
        print("       WARNING: SENTINEL score below 0.5 — fault may not have ramped enough.")

    # ── Step 3: SHERLOCK ─────────────────────────────────────────────────────
    event = _build_anomaly_event_from_sentinel(
        state,
        anomaly_id="ANO-A-001",
        flagged_subsystem="TCS",
        flagged_parameter="panel_temp",
        sentinel_score=sentinel_score,
    )
    print("\n  [3/4] Running SHERLOCK diagnosis...")
    try:
        diagnosis = sherlock.diagnose(event)
    except Exception as e:
        print(f"       SHERLOCK FAILED: {e}")
        return False

    print(f"       root_cause    = {diagnosis.primary_root_cause}")
    print(f"       urgency       = {diagnosis.urgency.value}")
    print(f"       time_to_crit  = {diagnosis.time_to_critical_estimate_minutes} min")
    print(f"       causal_chain  = {' → '.join(diagnosis.causal_chain)}")
    print(f"       llm_attempts  = {diagnosis.llm_attempts}")

    # ── Step 4: ORACLE ──────────────────────────────────────────────────────
    oracle_req = OracleRequest(
        current_state=state,
        fault_name="tcs_thermal_runaway",
        fault_severity=0.7,
        proposed_actions=None,  # ranking mode: test all catalog actions
        diagnosis_context=diagnosis.reasoning,
        n_runs=50,
        steps=200,
    )
    print("\n  Running ORACLE Monte Carlo ranking (n=50, steps=200)...")
    oracle_resp = run_oracle(oracle_req)
    _print_oracle_summary(oracle_resp)

    # ── Step 5: ATHENA ──────────────────────────────────────────────────────
    _section("ATHENA RECOVERY PLAN")
    constraints = MissionConstraints(
        min_fuel_reserve_pct=10.0,
        max_operator_effort="high",
        notes="Next ground station pass in approximately 15 minutes.",
    )
    print("\n  Running ATHENA (LLM call)...")
    try:
        plan = athena.plan(diagnosis, oracle_resp, constraints)
    except Exception as e:
        print(f"  ATHENA FAILED: {e}")
        return False

    _print_plan(plan)
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Scenario B: Propulsion thruster fault
# ─────────────────────────────────────────────────────────────────────────────


def demo_scenario_b(sherlock: SherlockAgent, athena: AthenaAgent) -> bool:
    _hr("SCENARIO B — Propulsion Thruster Fault (severity=0.8, seed=7)")
    print("\n  Pipeline: Simulator → SENTINEL → SHERLOCK → ORACLE → ATHENA")
    print("  Narrative: same state as ORACLE demo Scenario C; thruster_isolation expected near top.")

    # ── Step 1: Simulate ────────────────────────────────────────────────────
    print("\n  [1/4] Simulating fault (duration=900s, dt=10s)...")
    result = simulate_scenario(
        fault="propulsion_thruster_fault",
        severity=0.8,
        duration=900,
        dt=10,
        seed=7,
    )
    state = result.frames[-1].state
    print(f"       Final thruster_temp  = {state.propulsion.thruster_temp:.1f}°C")
    print(f"       Final fuel_remaining = {state.propulsion.fuel_remaining:.2f} kg")
    print(f"       Final attitude_error = {state.adcs.attitude_error:.2f}°")

    # ── Step 2: SENTINEL score ──────────────────────────────────────────────
    sentinel_score = score_state(state)
    print(f"\n  [2/4] SENTINEL score   = {sentinel_score['score']:.3f}  "
          f"worst_param={sentinel_score['worst_param']}")

    # ── Step 3: SHERLOCK ─────────────────────────────────────────────────────
    event = _build_anomaly_event_from_sentinel(
        state,
        anomaly_id="ANO-B-001",
        flagged_subsystem="Propulsion",
        flagged_parameter="thruster_temp",
        sentinel_score=sentinel_score,
    )
    print("\n  [3/4] Running SHERLOCK diagnosis...")
    try:
        diagnosis = sherlock.diagnose(event)
    except Exception as e:
        print(f"       SHERLOCK FAILED: {e}")
        return False

    print(f"       root_cause    = {diagnosis.primary_root_cause}")
    print(f"       urgency       = {diagnosis.urgency.value}")
    print(f"       time_to_crit  = {diagnosis.time_to_critical_estimate_minutes} min")
    print(f"       causal_chain  = {' → '.join(diagnosis.causal_chain)}")
    print(f"       llm_attempts  = {diagnosis.llm_attempts}")

    # ── Step 4: ORACLE ──────────────────────────────────────────────────────
    oracle_req = OracleRequest(
        current_state=state,
        fault_name="propulsion_thruster_fault",
        fault_severity=0.8,
        proposed_actions=None,
        diagnosis_context=diagnosis.reasoning,
        n_runs=50,
        steps=200,
    )
    print("\n  Running ORACLE Monte Carlo ranking (n=50, steps=200)...")
    oracle_resp = run_oracle(oracle_req)
    _print_oracle_summary(oracle_resp)

    isolation_rank = next(
        (i + 1 for i, r in enumerate(oracle_resp.results) if r.action_name == "thruster_isolation"),
        None,
    )
    print(f"\n  thruster_isolation ranked #{isolation_rank} by ORACLE safety_score.")

    # ── Step 5: ATHENA ──────────────────────────────────────────────────────
    _section("ATHENA RECOVERY PLAN")
    constraints = MissionConstraints(
        min_fuel_reserve_pct=5.0,
        max_operator_effort="medium",
        notes="Thruster currently redlined at 200°C. Propellant isolation is time-critical.",
    )
    print("\n  Running ATHENA (LLM call)...")
    try:
        plan = athena.plan(diagnosis, oracle_resp, constraints)
    except Exception as e:
        print(f"  ATHENA FAILED: {e}")
        return False

    _print_plan(plan)
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────


def main() -> None:
    print(f"\n{'#' * 72}")
    print("  ATHENA — Recovery Planning Agent Demo | AERO-ASTRA")
    print(f"{'#' * 72}")
    print("\n  Full pipeline: Simulator → SENTINEL → SHERLOCK → ORACLE → ATHENA")
    print("  Requires OPENROUTER_API_KEY in environment or .env file.\n")

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY not set.")
        print("  Set it via: set OPENROUTER_API_KEY=sk-or-v1-...")
        print("  Or create a .env file at project root: OPENROUTER_API_KEY=sk-or-v1-...")
        sys.exit(1)

    sherlock = SherlockAgent(api_key=api_key)
    athena   = AthenaAgent(api_key=api_key)

    results = []

    ok_a = demo_scenario_a(sherlock, athena)
    results.append(("Scenario A: TCS Thermal Runaway", ok_a))

    ok_b = demo_scenario_b(sherlock, athena)
    results.append(("Scenario B: Propulsion Thruster Fault", ok_b))

    print(f"\n\n{'#' * 72}")
    print("  DEMO COMPLETE — Summary")
    print(f"{'#' * 72}")
    for name, ok in results:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}]  {name}")

    sys.exit(0 if all(ok for _, ok in results) else 1)


if __name__ == "__main__":
    main()
