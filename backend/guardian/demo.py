"""
AERO-ASTRA — GUARDIAN Demo Script
====================================
Demonstrates all three GUARDIAN decision tiers using the same fault
scenarios already established across every other agent demo.

Fault scenarios reuse the exact same fault names, severities, and seed
values from the simulator, ORACLE, and SHERLOCK demos — narrative
consistency across the full pipeline.

Scenarios:
    A. AUTONOMOUS_SAFED  — eps_cascade_power_failure at severity=0.9,
                           time_to_critical=3 min (same EPS cascade as
                           simulator demo 4 / ORACLE demo A).
                           Rule 1 fires; shed_nonessential_load executes
                           immediately, post-hoc notification raised.

    B. MANUAL_INTERLOCK  — propulsion_thruster_fault at severity=0.8,
                           urgency=HIGH (same fault as ORACLE demo C /
                           SHERLOCK propulsion scenario).
                           Rule 2 fires; human approval required before
                           thruster_isolation can execute.

    C. AUTOMATED_GUARDED — eps_battery_degradation at severity=0.6,
                           urgency=LOW, reversible, clean ORACLE score.
                           (Same single-fault scenario as simulator demo 2.)
                           All checks pass; switch_redundant_power_bus
                           executes automatically.

Run with:
    python -m backend.guardian.demo
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from datetime import datetime, timezone

from backend.sherlock.schemas import SherlockDiagnosis, UrgencyLevel
from backend.athena.schemas import RecoveryPlan, RecoveryOption, OperatorEffort
from backend.oracle.schemas import OracleResponse, ActionResult
from backend.simulator.schemas import MonteCarloResult
from backend.simulator.recovery import RECOVERY_CATALOG
from backend.guardian import evaluate, DecisionTier, SAFETY_SCORE_FLOOR, TIME_CRITICAL_THRESHOLD_MINUTES
from backend.guardian.schemas import GuardianDecision


# -----------------------------------------------------------------------------
# Formatting helpers
# -----------------------------------------------------------------------------

_NOW = datetime.now(tz=timezone.utc)


def _hr(title: str) -> None:
    print(f"\n{'=' * 65}")
    print(f"  {title}")
    print(f"{'=' * 65}")


def _section(title: str) -> None:
    print(f"\n  -- {title} --")


def _print_decision(decision: GuardianDecision) -> None:
    tier_label = {
        DecisionTier.AUTONOMOUS_SAFED:  "??  AUTONOMOUS_SAFED",
        DecisionTier.MANUAL_INTERLOCK:  "?? MANUAL_INTERLOCK",
        DecisionTier.AUTOMATED_GUARDED: "? AUTOMATED_GUARDED",
    }[decision.tier]

    print(f"\n  +- GUARDIAN DECISION {'-' * 43}+")
    print(f"  ¦  Tier              : {tier_label}")
    print(f"  ¦  Action            : {decision.action_name}")
    print(f"  ¦  Auto-executes     : {decision.auto_executes}")
    print(f"  ¦  Human approval    : {decision.requires_human_approval}")
    print(f"  ¦  Post-hoc notify   : {decision.notify_operator_post_hoc}")
    print(f"  ¦  Rationale         : {decision.rationale}")
    print(f"  ¦  -- Audit -----------------------------------------------")
    print(f"  ¦  Time-to-critical  : {decision.time_to_critical_minutes} min")
    print(f"  ¦  Urgency           : {decision.urgency}")
    print(f"  ¦  Safety score      : {decision.safety_score:+.3f}" if decision.safety_score != -999.0
          else f"  ¦  Safety score      : N/A (shed_nonessential_load not in ORACLE results)")
    print(f"  ¦  Decided at        : {decision.decided_at.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    print(f"  +{'-' * 63}+")


# -----------------------------------------------------------------------------
# Shared synthetic-data helpers (mirror the same fault context as other demos)
# -----------------------------------------------------------------------------


def _make_mc(
    action: str,
    nominal: float = 0.70,
    loss: float = 0.10,
) -> MonteCarloResult:
    degraded = round(1.0 - nominal - loss, 9)
    return MonteCarloResult(
        proposed_action=action,
        n_runs=100,
        steps=300,
        nominal_recovery_rate=nominal,
        degraded_operation_rate=degraded,
        mission_loss_rate=loss,
        mean_final_battery_soc=0.60,
        mean_final_attitude_error=4.0,
        std_final_battery_soc=0.06,
        outcome_counts={
            "nominal_recovery": int(nominal * 100),
            "degraded_operation": int(degraded * 100),
            "mission_loss": int(loss * 100),
        },
    )


def _make_option(
    action_name: str,
    safety_score: float,
    is_irreversible: bool = False,
    effort: OperatorEffort = OperatorEffort.LOW,
) -> RecoveryOption:
    return RecoveryOption(
        action_name=action_name,
        procedure_steps=[
            "Confirm fault telemetry and subsystem state.",
            f"Issue command: {action_name}.",
            "Monitor recovery for 5 minutes and verify nominal restoration.",
        ],
        safety_score=safety_score,
        effectiveness_score=0.82,
        operator_effort=effort,
        predicted_outcome=(
            f"Execution of {action_name} is expected to restore nominal "
            "power margins within 10-15 minutes. All cascade effects should "
            "begin reversing within one orbit."
        ),
        contra_indications=[],
        blended_rank=round(safety_score * 0.5 + 0.82 * 0.35 + (1.0 / 1) * 0.15, 4),
        is_irreversible=is_irreversible,
    )


def _make_plan(
    action_name: str,
    safety_score: float,
    is_irreversible: bool = False,
    fault_context: str = "",
) -> RecoveryPlan:
    opt = _make_option(action_name=action_name, safety_score=safety_score, is_irreversible=is_irreversible)
    return RecoveryPlan(
        recommended_action=action_name,
        options=[opt],
        reasoning_cot=[
            "Evaluated ORACLE rankings for this fault scenario.",
            f"Top-ranked action by blended score: {action_name}.",
            "Procedure steps generated based on fault subsystem and catalog entry.",
        ],
        overall_reasoning=(
            f"ATHENA recommends {action_name} as the highest-ranked validated "
            f"recovery option for this fault (safety_score={safety_score:+.3f}). "
            f"{fault_context}"
        ),
        llm_attempts=1,
        generated_at=_NOW,
        diagnosis_context=fault_context,
    )


def _make_oracle(
    action_name: str,
    safety_score: float,
    fault_name: str = "eps_cascade_power_failure",
    response_flags: list[str] | None = None,
) -> OracleResponse:
    result = ActionResult(
        action_name=action_name,
        mc_result=_make_mc(action=action_name),
        safety_score=safety_score,
        flags=[],
    )
    return OracleResponse(
        fault_name=fault_name,
        diagnosis_context=f"SHERLOCK diagnosis for {fault_name}",
        mode="single_action",
        results=[result],
        best_action=action_name,
        response_flags=response_flags or [],
    )


# -----------------------------------------------------------------------------
# Scenario A — AUTONOMOUS_SAFED
# -----------------------------------------------------------------------------


def demo_autonomous_safed() -> None:
    _hr("SCENARIO A — AUTONOMOUS_SAFED (Rule 1: Time-Critical Emergency)")
    print("""
  Fault:   eps_cascade_power_failure  (severity=0.9, same as simulator demo 4 /
           ORACLE demo A / SHERLOCK EPS cascade scenario)
  Context: SOC draining fast — time_to_critical=3 min, below the
           {threshold}-min emergency threshold. Rule 1 fires immediately,
           overriding ALL other reasoning regardless of urgency, reversibility,
           or ORACLE scores. shed_nonessential_load executes right now.
           Post-hoc notification is raised so operators review it afterwards.
""".format(threshold=TIME_CRITICAL_THRESHOLD_MINUTES))

    diagnosis = SherlockDiagnosis(
        primary_root_cause="EPS",
        causal_chain=["EPS", "TCS", "ADCS", "OBC", "TT&C"],
        affected_subsystems=["EPS", "TCS", "ADCS", "OBC", "TT&C"],
        confidence_score=0.93,
        urgency=UrgencyLevel.LOW,        # urgency is LOW — Rule 1 still wins
        time_to_critical_estimate_minutes=3,   # <5 ? triggers Rule 1
        reasoning=(
            "Solar array current collapsed to near-zero. Battery SOC falling at "
            "~0.8%/min. At current drain rate: critical in 3 minutes."
        ),
        graph_candidate_set=["EPS"],
        llm_attempts=1,
        diagnosis_timestamp=_NOW,
    )

    recovery_plan = _make_plan(
        action_name="switch_redundant_power_bus",
        safety_score=0.68,
        fault_context="eps_cascade_power_failure: solar loss cascading to all subsystems.",
    )

    oracle_response = _make_oracle(
        action_name="switch_redundant_power_bus",
        safety_score=0.68,
        fault_name="eps_cascade_power_failure",
    )

    _section("Inputs")
    print(f"  SHERLOCK urgency          : {diagnosis.urgency.value}")
    print(f"  SHERLOCK time_to_critical : {diagnosis.time_to_critical_estimate_minutes} min  "
          f"(<{TIME_CRITICAL_THRESHOLD_MINUTES} ? Rule 1)")
    print(f"  ATHENA recommended action : {recovery_plan.recommended_action}")
    print(f"  ORACLE safety_score       : {oracle_response.results[0].safety_score:+.3f}")
    print(f"  ORACLE response_flags     : {oracle_response.response_flags or 'none'}")

    decision = evaluate(
        diagnosis=diagnosis,
        recovery_plan=recovery_plan,
        oracle_response=oracle_response,
    )

    _print_decision(decision)
    assert decision.tier == DecisionTier.AUTONOMOUS_SAFED
    assert decision.action_name == RECOVERY_CATALOG["shed_nonessential_load"].name
    assert decision.notify_operator_post_hoc is True
    print("\n  [OK] Tier=AUTONOMOUS_SAFED ?  action=shed_nonessential_load ?  "
          "notify_operator_post_hoc=True ?")


# -----------------------------------------------------------------------------
# Scenario B — MANUAL_INTERLOCK
# -----------------------------------------------------------------------------


def demo_manual_interlock() -> None:
    _hr("SCENARIO B — MANUAL_INTERLOCK (Rule 2: High-Urgency Propulsion Fault)")
    print("""
  Fault:   propulsion_thruster_fault  (severity=0.8, seed=7 — same as ORACLE
           demo C and SHERLOCK propulsion scenario)
  Context: Thruster overheat with attitude disturbance coupling to ADCS.
           SHERLOCK assessed urgency=HIGH with 25 min to critical.
           Rule 2 fires: human approval required before thruster_isolation.
""")

    diagnosis = SherlockDiagnosis(
        primary_root_cause="Propulsion",
        causal_chain=["Propulsion", "ADCS"],
        affected_subsystems=["Propulsion", "ADCS"],
        confidence_score=0.88,
        urgency=UrgencyLevel.HIGH,       # HIGH urgency ? Rule 2 fires
        time_to_critical_estimate_minutes=25,
        reasoning=(
            "Thruster temperature exceeding 900°C with active leak. "
            "Attitude disturbance growing. Propellant isolation recommended "
            "before thermal runaway. urgency=HIGH."
        ),
        graph_candidate_set=["Propulsion"],
        llm_attempts=1,
        diagnosis_timestamp=_NOW,
    )

    recovery_plan = _make_plan(
        action_name="thruster_isolation",
        safety_score=0.72,
        is_irreversible=False,
        fault_context="propulsion_thruster_fault: thruster overheat + ADCS coupling.",
    )

    oracle_response = _make_oracle(
        action_name="thruster_isolation",
        safety_score=0.72,
        fault_name="propulsion_thruster_fault",
    )

    _section("Inputs")
    print(f"  SHERLOCK urgency          : {diagnosis.urgency.value}  (HIGH ? Rule 2)")
    print(f"  SHERLOCK time_to_critical : {diagnosis.time_to_critical_estimate_minutes} min")
    print(f"  ATHENA recommended action : {recovery_plan.recommended_action}")
    print(f"  ORACLE safety_score       : {oracle_response.results[0].safety_score:+.3f}")
    print(f"  ORACLE response_flags     : {oracle_response.response_flags or 'none'}")

    decision = evaluate(
        diagnosis=diagnosis,
        recovery_plan=recovery_plan,
        oracle_response=oracle_response,
    )

    _print_decision(decision)
    assert decision.tier == DecisionTier.MANUAL_INTERLOCK
    assert decision.requires_human_approval is True
    assert decision.auto_executes is False
    print("\n  [OK] Tier=MANUAL_INTERLOCK ?  requires_human_approval=True ?  auto_executes=False ?")


# -----------------------------------------------------------------------------
# Scenario C — AUTOMATED_GUARDED
# -----------------------------------------------------------------------------


def demo_automated_guarded() -> None:
    _hr("SCENARIO C — AUTOMATED_GUARDED (Rule 5: Routine Recovery)")
    print("""
  Fault:   eps_battery_degradation  (severity=0.6 — same as simulator demo 2)
  Context: Battery degrading slowly. SHERLOCK assessed urgency=LOW, 90 min
           to critical. ATHENA recommends switch_redundant_power_bus.
           ORACLE scored it {score:+.2f} (above the {floor} floor). Action is
           reversible. All five checks pass ? Rule 5 fires.
""".format(score=0.65, floor=SAFETY_SCORE_FLOOR))

    diagnosis = SherlockDiagnosis(
        primary_root_cause="EPS",
        causal_chain=["EPS"],
        affected_subsystems=["EPS"],
        confidence_score=0.85,
        urgency=UrgencyLevel.LOW,        # LOW urgency, comfortable margin
        time_to_critical_estimate_minutes=90,
        reasoning=(
            "Battery SOC declining at ~0.4%/min due to internal resistance "
            "degradation. No immediate risk; 90 minutes of margin remain."
        ),
        graph_candidate_set=["EPS"],
        llm_attempts=1,
        diagnosis_timestamp=_NOW,
    )

    recovery_plan = _make_plan(
        action_name="switch_redundant_power_bus",
        safety_score=0.65,
        is_irreversible=False,   # reversible — Rule 3 does not fire
        fault_context="eps_battery_degradation: gradual SOC decline, no cascade.",
    )

    oracle_response = _make_oracle(
        action_name="switch_redundant_power_bus",
        safety_score=0.65,
        fault_name="eps_battery_degradation",
        response_flags=[],  # no ALL_ACTIONS_UNSAFE
    )

    _section("Inputs")
    print(f"  SHERLOCK urgency          : {diagnosis.urgency.value}")
    print(f"  SHERLOCK time_to_critical : {diagnosis.time_to_critical_estimate_minutes} min")
    print(f"  ATHENA recommended action : {recovery_plan.recommended_action}")
    print(f"  ATHENA is_irreversible    : {recovery_plan.options[0].is_irreversible}")
    print(f"  ORACLE safety_score       : {oracle_response.results[0].safety_score:+.3f}  "
          f"(>= {SAFETY_SCORE_FLOOR} floor)")
    print(f"  ORACLE response_flags     : {oracle_response.response_flags or 'none'}")

    decision = evaluate(
        diagnosis=diagnosis,
        recovery_plan=recovery_plan,
        oracle_response=oracle_response,
    )

    _print_decision(decision)
    assert decision.tier == DecisionTier.AUTOMATED_GUARDED
    assert decision.auto_executes is True
    assert decision.requires_human_approval is False
    assert decision.notify_operator_post_hoc is False
    print("\n  [OK] Tier=AUTOMATED_GUARDED ?  auto_executes=True ?  notify_operator_post_hoc=False ?")


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------


if __name__ == "__main__":
    print("AERO-ASTRA GUARDIAN — Demo")
    print("=" * 40)
    print("Deterministic 5-step execution gate | No LLM | No API key")
    print(f"Safety floor: {SAFETY_SCORE_FLOOR}  |  Time-critical threshold: {TIME_CRITICAL_THRESHOLD_MINUTES} min\n")

    demo_autonomous_safed()
    demo_manual_interlock()
    demo_automated_guarded()

    print("\n\n  All GUARDIAN scenarios complete.")
    print("  Tiers demonstrated: AUTONOMOUS_SAFED ?  MANUAL_INTERLOCK ?  AUTOMATED_GUARDED ?\n")
