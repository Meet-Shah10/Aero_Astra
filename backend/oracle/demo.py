"""
AERO-ASTRA -- ORACLE Demo Script
=================================
Three scenarios demonstrating ORACLE's single-action validation and
multi-action ranking modes.

Fault scenarios reuse the same names, severities, and seed values already
established in the simulator and SHERLOCK demo scripts, for narrative
consistency across the full project demo pipeline.

Scenarios:
    A. Single-action validation -- ATHENA path (switch_redundant_power_bus vs
       eps_cascade_power_failure, the same scenario from simulator demo scenario 4)
    B. Full-catalog ranking -- no-ATHENA fallback (same starting state as A,
       all 6 catalog actions ranked)
    C. Propulsion fault ranking -- thruster_isolation expected near the top
       (narrative consistency with SHERLOCK's propulsion fault demo)

Run with:
    python -m backend.oracle.demo
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from backend.simulator import simulate_scenario
from backend.oracle import rank_all_actions, validate_action
from backend.oracle.schemas import ActionResult, OracleRequest, OracleResponse


# -----------------------------------------------------------------------------
# Formatting helpers
# -----------------------------------------------------------------------------


def _hr(title: str) -> None:
    print(f"\n{'=' * 65}")
    print(f"  {title}")
    print(f"{'=' * 65}")


def _section(title: str) -> None:
    print(f"\n  -- {title} --")


def _print_action_result(result: ActionResult, rank: int | None = None) -> None:
    prefix = f"  [{rank}]" if rank is not None else "  [*]"
    flags_str = ", ".join(result.flags) if result.flags else "none"
    mc = result.mc_result
    print(
        f"{prefix} {result.action_name}\n"
        f"       score={result.safety_score:+.3f}  "
        f"nominal={mc.nominal_recovery_rate:.1%}  "
        f"degraded={mc.degraded_operation_rate:.1%}  "
        f"loss={mc.mission_loss_rate:.1%}  "
        f"mean_soc={mc.mean_final_battery_soc:.3f}\n"
        f"       flags: {flags_str}"
    )


def _print_response_summary(response: OracleResponse) -> None:
    print(f"\n  Request ID  : {response.request_id}")
    print(f"  Mode        : {response.mode}")
    print(f"  Fault       : {response.fault_name or 'none'}")
    print(f"  Best action : {response.best_action}")
    if response.response_flags:
        print(f"  !! Response flags: {', '.join(response.response_flags)}")


# -----------------------------------------------------------------------------
# Shared: build degraded EPS state (reused by scenario A and B)
# -----------------------------------------------------------------------------


def _build_eps_cascade_degraded_state():
    """
    10 minutes into eps_cascade_power_failure at severity=0.9 (seed=0).
    Identical to simulator demo scenario 4 -- narrative consistency.
    """
    cascade = simulate_scenario(
        fault="eps_cascade_power_failure",
        severity=0.9,
        duration=600.0,
        dt=10.0,
        fault_onset=0.0,
        seed=0,
    )
    return cascade.frames[-1].state


# -----------------------------------------------------------------------------
# Scenario A: Single-action validation -- ATHENA path
# -----------------------------------------------------------------------------


def demo_single_action_validation() -> None:
    _hr("SCENARIO A -- Single-Action Validation (ATHENA Path)")
    print("\n  Context: eps_cascade_power_failure at severity=0.9 (10 min in, seed=0)")
    print("  This is the same degraded state used in simulator demo scenario 4.")
    print("  ATHENA has proposed: switch_redundant_power_bus")
    print("  ORACLE validates it before it reaches GUARDIAN.\n")

    state = _build_eps_cascade_degraded_state()
    print(f"  Starting state: SOC={state.eps.battery_soc:.3f}  "
          f"attitude_err={state.adcs.attitude_error:.2f}deg  "
          f"signal={state.ttc.signal_strength:.1f}dBm")

    request = OracleRequest(
        current_state=state,
        fault_name="eps_cascade_power_failure",
        fault_severity=0.9,
        proposed_actions=["switch_redundant_power_bus"],
        diagnosis_context=(
            "SHERLOCK diagnosed eps_cascade_power_failure: solar array loss "
            "cascading to TCS heater cutoff, ADCS pointing drift, OBC voltage "
            "dip, TT&C signal degradation. Root cause: EPS bus fault."
        ),
        n_runs=100,
        steps=300,
    )

    response = validate_action(request)
    _print_response_summary(response)

    _section("Validation result")
    _print_action_result(response.results[0])

    mc = response.results[0].mc_result
    print(f"\n  Rates sum check: "
          f"{mc.nominal_recovery_rate + mc.degraded_operation_rate + mc.mission_loss_rate:.6f} "
          f"(should be 1.000000)")
    print(f"  Outcome counts: {mc.outcome_counts}")
    print(f"  std(final SOC): {mc.std_final_battery_soc:.4f} "
          f"(>0 confirms runs varied -- not identical)")

    if response.best_action:
        print(f"\n  [ORACLE -> GUARDIAN] Cleared for proposal: {response.best_action}")
    else:
        print("\n  [ORACLE -> GUARDIAN] Action unsafe -- do not propose.")


# -----------------------------------------------------------------------------
# Scenario B: Full-catalog ranking -- no-ATHENA fallback
# -----------------------------------------------------------------------------


def demo_ranking_fallback() -> None:
    _hr("SCENARIO B -- Full-Catalog Ranking (No-ATHENA Fallback)")
    print("\n  Context: same eps_cascade_power_failure state as Scenario A.")
    print("  ATHENA is not available. ORACLE tests all 6 catalog actions")
    print("  and ranks them -- giving GUARDIAN a complete validated menu.\n")

    state = _build_eps_cascade_degraded_state()
    print(f"  Starting state: SOC={state.eps.battery_soc:.3f}  "
          f"attitude_err={state.adcs.attitude_error:.2f}deg  "
          f"signal={state.ttc.signal_strength:.1f}dBm")

    request = OracleRequest(
        current_state=state,
        fault_name="eps_cascade_power_failure",
        fault_severity=0.9,
        proposed_actions=None,  # triggers ranking fallback
        diagnosis_context=(
            "SHERLOCK: eps_cascade_power_failure. ATHENA unavailable -- "
            "ORACLE fallback ranking all catalog actions."
        ),
        n_runs=100,
        steps=300,
    )

    response = rank_all_actions(request)
    _print_response_summary(response)

    _section("Ranked recovery actions")
    print(f"  {'Rank':<5} {'Action':<40} {'Score':>7}  {'Nominal':>8}  {'Loss':>7}  Flags")
    print(f"  {'-'*90}")
    for i, result in enumerate(response.results, 1):
        flags_str = ", ".join(result.flags) if result.flags else "-"
        mc = result.mc_result
        marker = "  <-- BEST" if result.action_name == response.best_action else ""
        print(
            f"  {i:<5} {result.action_name:<40} {result.safety_score:>+7.3f}  "
            f"{mc.nominal_recovery_rate:>8.1%}  {mc.mission_loss_rate:>7.1%}  "
            f"{flags_str}{marker}"
        )

    print(f"\n  [ORACLE -> GUARDIAN] Best validated option: {response.best_action}")
    if response.response_flags:
        print(f"  [ORACLE -> GUARDIAN] Response flags: {', '.join(response.response_flags)}")


# -----------------------------------------------------------------------------
# Scenario C: Propulsion fault ranking
# -----------------------------------------------------------------------------


def demo_propulsion_fault_ranking() -> None:
    _hr("SCENARIO C -- Propulsion Fault: Full-Catalog Ranking")
    print("\n  Context: propulsion_thruster_fault at severity=0.8")
    print("  Thruster fault -> heat runaway + attitude disturbance -> ADCS drift.")
    print("  Narrative consistency: same fault SHERLOCK exercises in its demo.\n")
    print("  ORACLE ranks all 6 actions. thruster_isolation expected near top.\n")

    # Build degraded state: 15 min into thruster fault
    prop_result = simulate_scenario(
        fault="propulsion_thruster_fault",
        severity=0.8,
        duration=900.0,
        dt=10.0,
        fault_onset=0.0,
        seed=7,
    )
    degraded_state = prop_result.frames[-1].state

    print(f"  Starting state: SOC={degraded_state.eps.battery_soc:.3f}  "
          f"thruster_temp={degraded_state.propulsion.thruster_temp:.1f}C  "
          f"attitude_err={degraded_state.adcs.attitude_error:.2f}deg  "
          f"fuel={degraded_state.propulsion.fuel_remaining:.2f}kg")

    request = OracleRequest(
        current_state=degraded_state,
        fault_name="propulsion_thruster_fault",
        fault_severity=0.8,
        proposed_actions=None,
        diagnosis_context=(
            "SHERLOCK: propulsion_thruster_fault. Thruster overheat with "
            "attitude disturbance coupling to ADCS. ORACLE ranking all catalog actions."
        ),
        n_runs=100,
        steps=300,
    )

    response = rank_all_actions(request)
    _print_response_summary(response)

    _section("Ranked recovery actions")
    print(f"  {'Rank':<5} {'Action':<40} {'Score':>7}  {'Nominal':>8}  {'Loss':>7}  Flags")
    print(f"  {'-'*90}")
    for i, result in enumerate(response.results, 1):
        flags_str = ", ".join(result.flags) if result.flags else "-"
        mc = result.mc_result
        marker = "  <-- BEST" if result.action_name == response.best_action else ""
        print(
            f"  {i:<5} {result.action_name:<40} {result.safety_score:>+7.3f}  "
            f"{mc.nominal_recovery_rate:>8.1%}  {mc.mission_loss_rate:>7.1%}  "
            f"{flags_str}{marker}"
        )

    # Find where thruster_isolation landed
    isolation_rank = next(
        (i + 1 for i, r in enumerate(response.results) if r.action_name == "thruster_isolation"),
        None
    )
    print(f"\n  thruster_isolation ranked: #{isolation_rank} of {len(response.results)}")
    print(f"  [ORACLE -> GUARDIAN] Best validated option: {response.best_action}")
    if response.response_flags:
        print(f"  [ORACLE -> GUARDIAN] Response flags: {', '.join(response.response_flags)}")


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------


if __name__ == "__main__":
    print("AERO-ASTRA ORACLE -- Demo")
    print("=" * 40)
    print("Monte Carlo digital-twin validation agent")
    print("No LLM calls -- deterministic/statistical simulator wrapper\n")

    demo_single_action_validation()
    demo_ranking_fallback()
    demo_propulsion_fault_ranking()

    print("\n\n  All ORACLE scenarios complete.\n")
