"""
AERO-ASTRA — ATHENA Recovery Planning Agent
=============================================
Public interface for the ATHENA module.

ATHENA synthesises SHERLOCK's root-cause diagnosis and ORACLE's
Monte Carlo-validated recovery rankings into a final, human-readable
recovery plan: ranked options with procedure steps, effectiveness
judgements, operator-effort estimates, and a blended recommendation.

Usage:
    from backend.athena import AthenaAgent, AthenaError, RecoveryPlan

    agent = AthenaAgent()   # reads OPENROUTER_API_KEY from env
    plan = agent.plan(
        sherlock_diagnosis=diagnosis,   # SherlockDiagnosis from SHERLOCK
        oracle_response=oracle_resp,    # OracleResponse from run_oracle()
    )
    print(plan.model_dump_json(indent=2))
"""

from .agent import AthenaAgent
from .schemas import (
    AthenaError,
    MissionConstraints,
    OperatorEffort,
    RecoveryOption,
    RecoveryPlan,
)

__all__ = [
    "AthenaAgent",
    "AthenaError",
    "MissionConstraints",
    "OperatorEffort",
    "RecoveryOption",
    "RecoveryPlan",
]
