# AERO-ASTRA Data Flow & Agent Schemas

This document maps out exactly what data is passed between the various agents in the AERO-ASTRA pipeline, providing the "proof" in the form of Pydantic models and JSON WebSocket messages used at each stage.

## 1. Simulator $\rightarrow$ Sentinel (Anomaly Detection)

**Flow:** The `Simulator` generates frames of telemetry at 1Hz (`SatelliteState`). These frames are passed through Sentinel's models (`XGBoost` and `PhysicsSpikeFilter`).

**Data Form:**
Sentinel operates directly on Pandas DataFrames (for historical windows). Once an anomaly crosses the threshold, it fires a `sentinel_alert` WebSocket message.

**Proof (WebSocket Payload):**
```json
{
  "type": "sentinel_alert",
  "is_anomaly": true,
  "triggered_engine": "Engine B (Physics)",
  "timestamp": 5.0,
  "false_positive": false
}
```

---

## 2. Sentinel $\rightarrow$ Sherlock (Diagnosis)

**Flow:** Once Sentinel trips the alarm, an `AnomalyEvent` is instantiated and handed to `SherlockAgent`. 

**Data Form (Pydantic Input):**
```python
class AnomalyEvent(BaseModel):
    anomaly_id: str             # e.g., "EVT-001"
    timestamp: datetime         # UTC Time
    flagged_subsystem: str      # e.g., "TCS"
    flagged_parameter: str      # e.g., "panel_temp"
    confidence_score: float     # e.g., 0.75
    severity: SeverityLevel     # e.g., SeverityLevel.HIGH
    telemetry_window: list[TelemetrySnapshot] 
```

**Data Form (Pydantic Output - `SherlockDiagnosis`):**
Sherlock uses Claude-3.5-Sonnet to navigate the causal graph and output this validated schema:
```python
class SherlockDiagnosis(BaseModel):
    primary_root_cause: str                 # e.g., "TCS"
    causal_chain: list[str]                 # e.g., ["TCS", "EPS", "Propulsion"]
    affected_subsystems: list[str]
    confidence_score: float                 # Range: 0.0 - 1.0
    urgency: UrgencyLevel                   # e.g., UrgencyLevel.HIGH
    time_to_critical_estimate_minutes: int  # e.g., 20
    reasoning: str                          # Free text rationale
```

**Proof (WebSocket Payload):**
```json
{
  "type": "sherlock_diagnosis",
  "primary_root_cause": "tcs_thermal_runaway",
  "causal_chain": ["tcs_thermal_runaway"],
  "confidence_score": 0.75,
  "urgency": "HIGH",
  "time_to_critical": 20
}
```

---

## 3. Sherlock $\rightarrow$ Oracle (Monte Carlo Simulation)

**Flow:** Sherlock's diagnosis acts as the seed for ORACLE to simulate recovery actions. The core `Simulator` runs thousands of forward trajectories (Monte Carlo) to evaluate outcomes.

**Data Form (Pydantic Input - `OracleRequest`):**
```python
class OracleRequest(BaseModel):
    current_state: SatelliteState
    fault_name: str | None           # e.g., "tcs_thermal_runaway"
    fault_severity: float            # e.g., 0.7
    diagnosis_context: str | None    # Echoed from Sherlock
    proposed_actions: list[str] | None 
    n_runs: int = 100
    steps: int = 300
```

**Data Form (Pydantic Output - `OracleResponse`):**
```python
class ActionResult(BaseModel):
    action_name: str
    mc_result: MonteCarloResult
    safety_score: float              # nominal_recovery_rate - mission_loss_rate
    flags: list[str]

class OracleResponse(BaseModel):
    mode: Literal["single_action", "ranking"]
    results: list[ActionResult]      # Ranked by safety_score
    best_action: str | None
    response_flags: list[str]
```

**Proof (WebSocket Payload):**
```json
{
  "type": "oracle_simulation",
  "best_action": "shed_nonessential_load",
  "top_score": 0.85,
  "mode": "ranking"
}
```

---

## 4. Oracle $\rightarrow$ Athena (Recovery Planning)

**Flow:** Athena takes Sherlock's diagnosis and Oracle's mathematical ranking of actions and synthesizes a human-readable recovery plan.

**Data Form (Pydantic Output - `RecoveryPlan`):**
```python
class RecoveryPlan(BaseModel):
    recommended_action: str
    options: list[RecoveryOption]    # Sorted by blended rank
    reasoning_cot: list[str]         # Chain of thought from LLM
    overall_reasoning: str           # Executive summary
    llm_attempts: int
```

**Proof (WebSocket Payload):**
```json
{
  "type": "athena_plan",
  "recommended_action": "shed_nonessential_load",
  "rationale": "Shedding load improves EPS survivability based on Oracle MC projections (85% safe).",
  "estimated_recovery_time_minutes": 15
}
```

---

## 5. Sherlock $\rightarrow$ Guardian (Safing & Interlocks)

**Flow:** Guardian acts instantly on Sherlock's `urgency` and `time_to_critical_estimate_minutes`. If TTC is extremely low, it bypasses human-in-the-loop and triggers autonomous safing.

**Data Form (Internal Logic in `api.py`):**
```python
ttc = diagnosis.time_to_critical_estimate_minutes
if ttc is not None and ttc < 5:
    guardian_status = "AUTONOMOUS_SAFED"
    action_taken = "shed_nonessential_load"
elif diagnosis.urgency in (UrgencyLevel.HIGH, UrgencyLevel.CRITICAL):
    guardian_status = "MANUAL_INTERLOCK"
```

**Proof (WebSocket Payload):**
```json
{
  "type": "guardian_action",
  "status": "MANUAL_INTERLOCK",
  "action_taken": null
}
```

---

## Appendix: Vitals Engine

Independently, the `Vitals` engine continuously distills telemetry into a 0.0 - 1.0 health score for the front-end gauges. 

**Proof (WebSocket Payload):**
```json
{
  "type": "vitals_update",
  "timestamp": 25.0,
  "payload": {
    "system_health": 0.89,
    "worst_health": 0.72,
    "worst_subsystem": "TCS"
  }
}
```
