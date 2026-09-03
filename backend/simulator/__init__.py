"""
AERO-ASTRA Physics Simulator
=============================
Agent-shared simulation infrastructure for ORACLE, the live dashboard,
and synthetic training-data generation.

Public interface — exactly two entry points:

    simulate_scenario(fault, severity, duration, dt, ...) -> SimulationResult
        Run a single forward simulation with optional fault injection.
        Returns a full labeled time series.

    run_monte_carlo(current_state, proposed_action, n_runs, steps, ...) -> MonteCarloResult
        Run n independent simulations from a given state with a recovery action applied.
        Returns aggregate outcome statistics for ORACLE to report.

No LLM calls, no API keys, no external orbital-mechanics libraries required.
Only numpy, pydantic, and the Python standard library.
"""

from .engine import run_monte_carlo, simulate_scenario

__all__ = ["simulate_scenario", "run_monte_carlo"]
