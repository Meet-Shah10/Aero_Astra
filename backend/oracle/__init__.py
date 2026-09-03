"""
AERO-ASTRA — ORACLE
====================
Digital-twin validation agent.

ORACLE is a deterministic/statistical wrapper around the physics simulator's
run_monte_carlo() function. Given the satellite's current state and a proposed
recovery action, it returns real outcome probabilities from the simulator.

No LLM calls, no API keys. Pure statistics over the simulator.

Public API:
    run_oracle(request: OracleRequest) -> OracleResponse
        Dispatches to single-action validation or full-catalog ranking depending
        on whether proposed_actions is provided in the request.

    validate_action(request: OracleRequest) -> OracleResponse
        Validate one or more specific proposed actions (ATHENA path).

    rank_all_actions(request: OracleRequest) -> OracleResponse
        Test every catalog action and rank by safety score (no-ATHENA fallback).
"""

from .agent import rank_all_actions, run_oracle, validate_action
from .schemas import ActionResult, OracleRequest, OracleResponse

__all__ = [
    "run_oracle",
    "validate_action",
    "rank_all_actions",
    "OracleRequest",
    "OracleResponse",
    "ActionResult",
]
