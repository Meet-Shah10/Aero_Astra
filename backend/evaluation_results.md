# Aero-Astra Evaluation Results

This document summarizes the quantitative and qualitative performance of the AERO-ASTRA pipeline across its distinct multi-engine components and evaluations.

## 1. SENTINEL (Anomaly Detection Engine)

SENTINEL's hybrid architecture has been rigorously tested against real ESA OPSSAT-AD telemetry containing live anomalies. Evaluation enforces a strict `Precision >= 0.50` floor to ensure no "predict-all" artifacts make it to production.

### Engine A: XGBoost + Persistence (Slow-Onset Flatlines)
* **Target Faults:** Hardware degradation, stuck sensors, and sustained telemetry flatlines.
* **Architecture:** Gradient-Boosted Trees filtering on `flatline_duration` and `log_inv_std`, wrapped in a 35-step persistence filter to eliminate transient operational noise.
* **Metrics (Conservative Early-Mission CV):** F1 Score = `0.4958`, PR-AUC = `0.5479`.
* **Metrics (Best-Case Late-Mission Test):** F1 Score = `0.6465`, PR-AUC = `0.6927`.
* **Note:** The discrepancy in performance represents natural chronological mission drift. Early telemetry contains higher noise volumes (bringing F1 to ~0.50), while later hardware faults present as longer, cleaner flatlines (yielding ~0.65 F1).

### Engine B: Physics Spike & Triad Isolation (Impulsive Anomalies)
* **Target Faults:** Impulsive momentum anomalies (e.g., sudden reaction wheel strikes) specifically affecting the Magnetometer triad.
* **Architecture:** Deterministic physics-based gate. Checks for a massive input jump rate (`dx_in > 4*MAD`), immediate impulse reversal violating inertia (`dx_in * dx_out < 0`), and enforces single-channel isolation (flags anomaly *only* if exactly 1 out of 3 axes faults, effectively decoupling hardware failures from valid rigid-body multi-axis maneuvers).
* **Metrics:** Reduced False Positive (FP) rate from ~550 per day (legacy CUSUM implementation) down to `< 5 FP/day` on real OPSSAT-AD data. True Positive latency is effectively `0 seconds` upon impact.

## 2. SHERLOCK (Root-Cause Diagnosis Agent)

SHERLOCK evaluates anomalies surfaced by SENTINEL, identifying the underlying physical root cause using a constrained LLM graph-search approach.

* **Phase 1 Validation:** 100% deterministic constraint. The LLM's final diagnosis is checked against the physical `SatelliteGraph`. If Claude hallucinates an impossible physical state, the output is rejected and reprompted automatically.
* **Time-to-Diagnosis:** Typically completes in `< 5 seconds` per event, compared to 15-60 minutes for manual operational review.

## 3. Combined Pipeline (Live Stream Integration)

In the integrated streaming bridge (`backend/api.py`), the pipeline runs fully end-to-end:
* **Latency:** From simulator emission -> SENTINEL Detection -> SHERLOCK Diagnosis -> GUARDIAN Safing Gate -> ORACLE Monte Carlo mitigation, the full loop evaluates in under `10 seconds`.
* **GUARDIAN Tri-Tier Safing Validation:** Effectively prevents catastrophic LLM interventions by implementing rigid thresholds (e.g., auto-safing immediately if Time-to-Critical is `< 5 mins`, or triggering Manual Interlock for `HIGH`/`CRITICAL` states, overriding ORACLE entirely).
