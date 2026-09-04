"""
AERO-ASTRA — GUARDIAN Execution Gate
======================================
Public interface for the GUARDIAN module.

GUARDIAN is the final safety gate before a recovery action is allowed to
execute. It synthesises SHERLOCK's diagnosis, ATHENA's recovery plan, and
ORACLE's validation response into one of three deterministic execution tiers,
with no LLM calls and no external dependencies.

Usage:
    from backend.guardian import evaluate, GuardianDecision, DecisionTier

    decision = evaluate(
        diagnosis=sherlock_diagnosis,       # SherlockDiagnosis from SHERLOCK
        recovery_plan=athena_recovery_plan, # RecoveryPlan from ATHENA
        oracle_response=oracle_resp,        # OracleResponse from ORACLE
    )
    print(decision.model_dump_json(indent=2))
"""

from .engine import evaluate, SAFETY_SCORE_FLOOR, TIME_CRITICAL_THRESHOLD_MINUTES
from .schemas import DecisionTier, GuardianDecision

__all__ = [
    "evaluate",
    "SAFETY_SCORE_FLOOR",
    "TIME_CRITICAL_THRESHOLD_MINUTES",
    "DecisionTier",
    "GuardianDecision",
]
