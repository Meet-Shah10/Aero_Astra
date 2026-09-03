# Aero-Astra Backend Codebase Map

This document serves as an index for the `backend/` directory, detailing exactly which files contain the code for which specific functionalities.

## 1. Core API & Streaming
* **`api.py`**: The main FastAPI application. Contains the WebSocket bridge (`/ws`) and the core `simulate_stream()` event loop that streams simulated telemetry, triggers SENTINEL anomaly detection, dispatches SHERLOCK for root cause diagnosis, filters safe modes through GUARDIAN logic, and requests mitigation strategies from ORACLE.

## 2. SENTINEL (Anomaly Detection Engine)
Located in `backend/sentinel/`.
* **`engines.py`**: The core detection logic. Contains:
  * `SentinelPersistenceFilter`: The 35-step persistence filter for Engine A.
  * `score_xgboost`: Evaluates the flatline XGBoost model on rolling windows.
  * `score_physics_spike`: The Spike & Boundary Detector (Engine B) that evaluates the `dx_in * dx_out < 0` impulse reversal and enforces triad single-channel isolation.
* **`utils.py`**: Helper functions for telemetry manipulation (e.g., computing static Mean Absolute Deviation, filtering, missing data alignment).
* **`adcs.py`**: ADCS subsystem specific logic and constants.
* **`eps_tcs.py`**: EPS and TCS subsystem logic.
* **`lstm.py`**: Contains the (deprecated for live scoring) LSTM architecture used strictly for diagnostic visual forecasting.
* **`sentinel.py`**: General configuration classes and schema definitions for the Sentinel module.
* **`root_cause.py`**: Legacy mapping rules mapping anomalies to root causes (mostly superseded by SHERLOCK).
* **`cli.py`**: Command-line interface logic for running Sentinel offline.

## 3. SHERLOCK (Root-Cause Diagnosis Agent)
Located in `backend/sherlock/`.
* **`agent.py`**: The `SherlockAgent` class. Orchestrates the 3-phase diagnosis pipeline (Deterministic Graph Phase 1 -> Claude LLM Phase 2 -> Deterministic Validation Phase 3) via OpenRouter.
* **`graph.py`**: The `SatelliteGraph` which maps subsystem interdependencies. Enforces physical validation so the LLM cannot hallucinate impossible root causes.
* **`prompts.py`**: Contains `SYSTEM_PROMPT` and helper functions that construct the contextual prompt injected into Claude.
* **`schemas.py`**: Pydantic models mapping expected inputs and structured JSON outputs (`AnomalyEvent`, `SherlockDiagnosis`).
* **`telemetry_interface.py`**: Abstract `TelemetryProvider` for fetching snapshots without hard-coupling the LLM to the live database/simulator.

## 4. ORACLE (Safety & Mitigation Agent)
Located in `backend/oracle/`.
* **`agent.py`**: Contains `run_oracle()`. Dispatches proposed actions into the digital twin for Monte Carlo analysis to produce evaluated `ActionResult` sets.
* **`scoring.py`**: The heuristic logic that parses Monte Carlo outcomes and calculates the aggregate Safety Score (e.g., penalizing actions that drain battery while in eclipse).
* **`schemas.py`**: Pydantic models for Oracle inputs and responses (`OracleRequest`, `OracleResponse`, `ActionResult`).

## 5. SIMULATOR (Digital Twin / Physics Engine)
Located in `backend/simulator/`.
* **`engine.py`**: The core engine loop (`simulate_scenario`, `run_monte_carlo`). Handles discrete time stepping and aggregates subsystem updates.
* **`schemas.py`**: Pydantic state models mapping the exact physical attributes (voltages, temperatures, momentum) of the satellite at any timestep `t`.
* **`faults.py`**: The catalogue of injectable faults (e.g., `eps_cascade_power_failure`, `adcs_reaction_wheel_degradation`) used for evaluation and live demo mock scenarios.
* **`noise.py`**: Applies mathematical gaussian noise envelopes to sensor readings to simulate realistic orbital degradation.
* **`transitions.py`**: The deterministic state transition equations that govern physical interactions across subsystems between `t` and `t+1`.
* **`recovery.py`**: Contains `RECOVERY_CATALOG` procedures, specifying precisely how proposed commands alter the underlying state logic.
