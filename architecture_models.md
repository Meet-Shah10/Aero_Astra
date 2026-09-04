# AERO-ASTRA Architecture: Models & Agents

This document explains the internal logic, algorithms, and models powering each agent in the AERO-ASTRA system.

---

## 1. The Core Physics Simulator (`backend/simulator/engine.py`)

**What it does:** 
The Simulator is the deterministic physics engine underpinning the entire application. It maintains the physical state of the satellite (power, thermal, attitude, etc.) and evolves it step-by-step using discrete-time integration. 

**How it works:**
- It holds a `SatelliteState` containing subsystems (EPS, TCS, ADCS, OBC, TTC, Propulsion).
- At every timestep (e.g. 1 second), it updates state variables based on physics equations. For example, battery State of Charge (SOC) is integrated using `(solar_current - load_current) * dt`.
- **Fault Injection:** If an active fault is specified (e.g., `tcs_thermal_runaway`), the simulator injects modifiers (like an artificial heat load or current drain) that ramp up based on a `severity` parameter and a `fault_onset` time.
- **Monte Carlo (`run_monte_carlo`):** The simulator can branch out into the future. It can run hundreds of parallel simulations of a future state, applying randomized noise via numpy's RNG to test if a specific recovery action (like shedding load) leads to mission survival or loss.

---

## 2. SENTINEL: The Dual-Engine Anomaly Detector (`backend/sentinel/engines.py`)

Sentinel continuously monitors the streaming telemetry from the simulator using two distinct algorithms (engines) to catch anomalies.

### Engine A: XGBoost Flatline Detector
**How it works:**
- Detects subtle sensor degradation, specifically "flatlining" where a sensor gets stuck or loses dynamic range.
- **Feature Extraction:** It calculates rolling features over a 20-step window—specifically `flatline_duration` (consecutive identical values) and `log_inv_std` (log of the inverse standard deviation).
- **ML Model:** These features are fed into a pre-trained XGBoost classification model (`sentinel_production.pkl` trained on historical ESA OPS-SAT data) which outputs an anomaly probability `[0.0, 1.0]`.
- **Persistence Filter:** To prevent noisy false alarms, the `SentinelPersistenceFilter` requires the XGBoost score to exceed a threshold (e.g., 0.60) for a strict number of *consecutive* frames (e.g., 35 steps) before raising an alert.

### Engine B: Physics Spike Filter
**How it works:**
- Detects sudden, violent physical perturbations (e.g., a thruster misfire or impact).
- **Impulse Reversal Logic:** It looks at a sliding window of the last 3 data points for specific sensors (e.g., magnetometer triad). It calculates the deltas: `dx_in` (change entering the point) and `dx_out` (change leaving). 
- A spike is detected if both deltas exceed a statically-calibrated Median Absolute Deviation (MAD) threshold *and* the deltas multiply to a negative number (`dx_in * dx_out < 0`), meaning the signal violently snapped back (an impulse).
- **Single-Channel Isolation:** To avoid flagging normal physical maneuvers (which affect all axes), it requires *exactly one* sensor channel to spike.

---

## 3. SHERLOCK: The Diagnostic Agent (`backend/sherlock/agent.py`)

**What it does:** 
Once Sentinel detects an anomaly, Sherlock isolates the true root cause from downstream symptoms.

**How it works:**
1. **Causal Graph Pruning:** It loads a pre-defined directed graph (`SatelliteGraph` with nodes like EPS, TCS, ADCS). When Sentinel flags a specific subsystem (e.g., TCS), Sherlock traverses the graph backwards to extract a valid candidate set of upstream root causes.
2. **LLM Reasoning:** It packages the anomaly event, recent telemetry, and the pruned candidate graph into a strict prompt.
3. **Inference:** It calls an LLM (Claude 3.5 Sonnet) via OpenRouter, requiring the LLM to output a JSON payload matching the `SherlockDiagnosis` Pydantic schema. The LLM must select a root cause strictly from the graph candidates and provide a logical causal chain and Time-to-Critical (TTC) estimate.

---

## 4. ORACLE: The Mathematical Forward-Simulator (`backend/oracle/agent.py`)

**What it does:** 
Oracle evaluates recovery actions by running them through physics simulations rather than relying on LLM guesses.

**How it works:**
1. When Oracle is invoked, it looks up all available recovery actions in the `RECOVERY_CATALOG` (e.g., `shed_nonessential_load`, `restart_reaction_wheels`).
2. **Monte Carlo Execution:** For *each* action, it invokes the physics `Simulator` to run 100 parallel trajectories 300 steps into the future, maintaining the active fault identified by Sherlock.
3. **Scoring:** It counts how many runs resulted in nominal operation vs. how many resulted in catastrophic failure (e.g., battery hitting 0%, or temperatures exceeding limits). 
4. **Safety Score:** It calculates `safety_score = nominal_recovery_rate - mission_loss_rate`, outputting an exact mathematical ranking of which action is safest.

---

## 5. ATHENA: The Recovery Planner (`backend/athena/agent.py`)

**What it does:** 
Athena translates the mathematical output from Oracle and the diagnostic context from Sherlock into a human-executable recovery plan.

**How it works:**
- Athena acts as a summarization and justification layer. It receives the `OracleResponse` containing the mathematically ranked actions.
- It prompts the LLM to write out a Chain-of-Thought reasoning explaining *why* the top-ranked mathematical action is the correct choice given the physical context.
- It guarantees that the `recommended_action` it outputs is identically the mathematically best action chosen by Oracle, ensuring the LLM cannot hallucinate an unsafe physical maneuver.

---

## 6. GUARDIAN: The Interlock Policy Engine (`backend/api.py`)

**What it does:** 
Guardian is a deterministic, rule-based gatekeeper that decides whether a human is allowed to review a plan, or if the satellite must act autonomously to save itself.

**How it works:**
- It reads the `time_to_critical_estimate_minutes` and `urgency` from Sherlock's diagnosis.
- If TTC is $< 5$ minutes, the situation is moving too fast for human review: Guardian shifts into **AUTONOMOUS_SAFED** mode and executes the Athena plan automatically.
- If TTC $> 5$ minutes but urgency is HIGH, it shifts into **MANUAL_INTERLOCK** mode, pausing execution until the human operator explicitly clicks "Authorize" in the UI.

---

## 7. VITALS: The Health Engine (`backend/vitals/agent.py`)

**What it does:** 
A continuous, lightweight scoring engine that calculates the top-level 0–100% health gauges for the UI.

**How it works:**
- On every telemetry frame, it evaluates individual variables (like Battery SOC or Panel Temp) against their known safe operating limits.
- It generates a score from `0.0` to `1.0` for each subsystem.
- It aggregates these to find the `worst_health` score and the `system_health` (average). If the system degrades below 85% without Sentinel catching it, Vitals can act as a fallback trigger for the pipeline.
