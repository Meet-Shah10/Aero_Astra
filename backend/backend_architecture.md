# Aero-Astra Backend Architecture

This document provides a comprehensive overview of the `backend` folder for the Aero-Astra project. It details the directory structure, the purpose of each module, the data flow, and the underlying models and architectures used.

## 📂 Directory Structure Overview

The backend is modularized into four primary distinct systems, along with a raw data directory:

1. **`sentinel/`**: The Anomaly Detection Pipeline.
2. **`sherlock/`**: The Root-Cause Diagnosis Agent.
3. **`oracle/`**: The Safety & Action Evaluation Agent.
4. **`simulator/`**: The Core Physics and Fault Simulation Engine.
5. **`data/`**: Raw datasets (e.g., OPSSAT, Mars Express) used for evaluation and training.

---

## 🛰️ 1. SENTINEL (Anomaly Detection)

**Purpose:** Monitors incoming satellite telemetry, detects faults, and raises alerts. 

**Models & Architecture:**
- **Hybrid ADCS Engine:** Uses a unified multi-engine approach on OPSSAT data.
  - **Engine A (XGBoost + Persistence):** Supervised model wrapped in a `SentinelPersistenceFilter` that identifies "stuck-sensor" or flatline faults using rolling window statistics (`flatline_duration` and `log_inv_std`). Requires a minimum consecutive trigger threshold (e.g., 35s) to eliminate transient noise. Currently the most performant and operationally viable engine.
  - **Engine B (Physics Spike & Triad Isolation):** Evaluates impulsive physical anomalies (e.g., hardware fault spikes) specifically on the magnetometer triad. Uses an Impulse Reversal logic (`dx_in * dx_out < 0`) coupled with Single-Channel Isolation (flags anomaly only if exactly 1 out of 3 axes faults) to decouple actual hardware spikes from valid rigid-body spacecraft maneuvers.
  - **Engine C (Correlation/Fisher-Z):** Measures cross-channel decoupling (e.g., magnetometer axes). (Currently dormant/parked).
- **EPS/TCS Thermal Model:** A semi-supervised residual-based forecaster (LSTM/Regression). It predicts expected thermal power draw (`NPWD*` channels) based on context and flags anomalies when residuals deviate past a tuned threshold.

**Key Files:**
- `engines.py`: Contains the core scoring logic for the hybrid engines.
- `evaluate_opssat_hybrid.py` & `evaluate_opssat_v2.py`: The evaluation harnesses for scoring precision, recall, and detection latency on held-out OPSSAT telemetry.
- `lstm.py` / `eps_tcs.py`: Forecasting models for the Thermal Control Subsystem.

---

## 🔎 2. SHERLOCK (Root-Cause Diagnosis)

**Purpose:** When Sentinel detects an anomaly, Sherlock takes over to diagnose the root physical cause.

**Models & Architecture:**
- **LLM-Based Agent:** Uses Large Language Models (LLMs) to reason about faults.
- **Dependency Graph (`graph.py`):** Maintains a directed graph of satellite subsystems (e.g., ADCS -> EPS -> Solar Panels). When a fault occurs in one system, Sherlock traverses the graph to check if the root cause originated upstream (e.g., ADCS failed because EPS power was lost).
- **Telemetry Interface (`telemetry_interface.py`):** Fetches localized snapshots of data pre- and post-anomaly to provide context to the LLM.

**Data Flow:**
`Sentinel Alert` ➔ `Sherlock Agent` ➔ `Queries Dependency Graph` ➔ `Requests Telemetry Snapshots` ➔ `Emits Root Cause Diagnosis`.

---

## 🔮 3. ORACLE (Safety & Mitigation Agent)

**Purpose:** Recommends and evaluates recovery actions once Sherlock diagnoses a fault.

**Models & Architecture:**
- **Safety Scoring (`scoring.py`):** Uses heuristic matrices and LLM evaluation to score proposed mitigation actions based on risk, system state, and mission constraints.
- **Action Dispatcher:** Validates if an action is safe to execute. Prevents catastrophic commands (e.g., firing thrusters while power is critical or entering an unrecoverable spin).

**Data Flow:**
`Sherlock Diagnosis` ➔ `Oracle Evaluates Possible Actions` ➔ `Safety Score Computed` ➔ `Action Approved/Rejected`.

---

## ⚙️ 4. SIMULATOR (Physics & Fault Engine)

**Purpose:** A synthetic environment that simulates satellite physics, orbital mechanics, and fault injections. Used when real telemetry is unavailable or to stress-test the pipeline.

**Architecture:**
- **Core Engine (`engine.py`):** Steps through time, updating subsystem states.
- **Orbit Clock (`orbit.py`):** Simulates the eclipse cycle (sunlight vs. shadow), which drives solar power generation and thermal states.
- **State Schemas (`schemas.py`):** Pydantic models representing the exact physical state of ADCS, EPS, TCS, OBC, TTC, and Propulsion at any timestep.
- **Fault Injector (`faults.py`):** Can dynamically inject component degradation (e.g., battery capacity loss), catastrophic failures (e.g., stuck reaction wheels), or signal dropouts.
- **Noise Generator (`noise.py`):** Injects realistic Gaussian noise into sensor readings.
- **Transitions (`transitions.py`):** Defines the physics equations (e.g., power consumption = voltage * current) bridging different subsystems.

---

## 🔄 End-to-End Data Routing

1. **Telemetry Ingestion:** Data originates either from raw CSVs (`data/raw/opssat/`) or is generated dynamically by the `simulator/`.
2. **Detection:** Data streams into `sentinel/`. Sentinel computes rolling features and evaluates them against the XGBoost flatline model and the physics-based spike detector.
3. **Alert Generation:** If Sentinel's combined score crosses the threshold (e.g., `0.5` or `0.8`), an `AnomalyEvent` is triggered.
4. **Diagnosis:** The `AnomalyEvent` is passed to `sherlock/`. Sherlock queries the dependency graph and raw telemetry surrounding the timestamp to deduce the root cause.
5. **Mitigation:** Sherlock passes the diagnosis to `oracle/`. Oracle evaluates recovery actions against the current satellite state, scores them for safety, and approves the best mitigation strategy.
6. **Execution:** In a closed-loop test, Oracle's chosen action is fed back into the `simulator/` (via `recovery.py`) to stabilize the satellite.
