# AERO-ASTRA — 48-Hour Hackathon Execution Roadmap

> **Read work.md first.** This roadmap is the time-boxed execution layer on top of it.
> Backend is at `/backend/`. Frontend at `/src/`. Dev server: `npm run dev` in root.

---

## What We Have Right Now (Do Not Break These)

| Component | Location | Status | Notes |
|---|---|---|---|
| **3D Landing + Dashboard UI** | `src/App.jsx` | ✅ Working | Three.js globe, camera dolly, satellite GLB, full agent panels |
| **SENTINEL** (XGBoost trained) | `backend/models/sentinel_production.pkl` | ✅ Trained | Real ESA OPSSAT-AD data. F1 and PR-AUC computed. Do not retrain. |
| **SHERLOCK** (LLM + graph) | `backend/sherlock/agent.py` | ✅ Built | Claude via OpenRouter, graph-constrained, 3-retry validation loop |
| **Physics Simulator** | `backend/simulator/engine.py` | ✅ Built | `simulate_scenario()` + `run_monte_carlo()` already exist |
| **RECOVERY_CATALOG** | `backend/simulator/recovery.py` | ✅ Built | 6 named actions with subsystem modifiers. ATHENA's input. |
| **ORACLE** | `backend/oracle/agent.py` | 🟡 Scaffolded | Wrapper around `run_monte_carlo` — needs wiring |
| **CHRONICLE, VITALS, ATHENA, GUARDIAN, QUARTERMASTER, SCRIBE** | — | ❌ Not built | Build in order below |

---

## Architecture Overview

```
[Browser Frontend]
       │  WebSocket ws://localhost:8000/ws/mission
       │
[FastAPI Bridge — backend/api.py]  ← BUILD THIS FIRST
       │
       ├── simulate_scenario()     [simulator/engine.py — EXISTS]
       ├── SENTINEL.score()        [sentinel/explain_anomaly.py — EXISTS]
       ├── SHERLOCK.diagnose()     [sherlock/agent.py — EXISTS]
       ├── ORACLE.simulate_all()   [oracle/agent.py — WRAP]
       ├── VITALS.compute()        [backend/vitals.py — BUILD]
       ├── CHRONICLE.log()         [backend/chronicle.py — BUILD]
       ├── ATHENA.plan()           [backend/athena/ — BUILD]
       ├── GUARDIAN.check()        [backend/guardian.py — BUILD]
       ├── QUARTERMASTER.schedule() [backend/quartermaster.py — BUILD]
       └── SCRIBE.generate()       [backend/scribe.py — BUILD]
```

---

## Phase 1 — The Bridge 🔴 HIGHEST PRIORITY (Hours 1–4)

**Goal:** Replace fake JS timers with a real Python pipeline. One button click → real data flowing.

### What to build: `backend/api.py`

```python
# FastAPI app with WebSocket
# POST /trigger — starts the fault scenario
# WS  /ws/mission — streams JSON events to frontend

from fastapi import FastAPI, WebSocket
from backend.simulator.engine import simulate_scenario
from backend.sentinel.explain_anomaly import SentinelScorer
from backend.sherlock.agent import SherlockAgent
```

### WebSocket message shapes (frontend already expects these formats):

```json
// Telemetry update (every 10 simulated seconds)
{"type": "telemetry", "ts": 240, "battery_soc": 0.72, "eps_load": 0.89,
 "panel_temp": 42.1, "cpu_load": 0.74, "comm_link": "Stable", "tcs_trend": "+4.2°C/hr"}

// SENTINEL fires
{"type": "sentinel_alert", "anomaly_id": "ANO-001", "score": 0.94,
 "flagged_subsystem": "EPS", "severity": "HIGH"}

// SHERLOCK diagnosis
{"type": "sherlock_diagnosis", "primary_root_cause": "eps_battery_degradation",
 "causal_chain": ["eps_battery_degradation", "EPS", "TCS"],
 "urgency": "HIGH", "confidence_score": 0.91, "time_to_critical_estimate_minutes": 23}
```

### Frontend change in `src/App.jsx`:
Replace the fake `setTimeout` cascade in `triggerAnomaly()` with:
```js
const ws = new WebSocket('ws://localhost:8000/ws/mission');
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  if (msg.type === 'telemetry') updateTelemetry(msg);
  if (msg.type === 'sentinel_alert') setScenarioPhase('detected');
  if (msg.type === 'sherlock_diagnosis') { setScenarioPhase('diagnosing'); ... }
};
fetch('http://localhost:8000/trigger', { method: 'POST' });
```

### Fault to use for demo:
`eps_battery_degradation` — hits EPS → TCS → OBC cascade which gives best visual impact.
`simulate_scenario(fault="eps_battery_degradation", severity=0.7, duration=3600, dt=10)`

---

## Phase 2 — VITALS + CHRONICLE (Hours 4–6)

### VITALS: `backend/vitals.py`

Weighted health score from `SatelliteState`. No ML, just arithmetic:

```python
def compute_health_score(state: SatelliteState) -> dict:
    battery_score = state.eps.battery_soc * 100        # weight: 35%
    thermal_score = max(0, 100 - abs(state.tcs.panel_temp - 25) * 2)  # weight: 25%
    cpu_score = (1 - state.obc.cpu_load) * 100          # weight: 20%
    comms_score = (1 - state.ttc.bit_error_rate) * 100  # weight: 20%
    
    overall = (battery_score * 0.35 + thermal_score * 0.25 +
               cpu_score * 0.20 + comms_score * 0.20)
    
    return {"overall_score": round(overall, 1), "rul_orbits": compute_rul(state)}
```

### CHRONICLE: `backend/chronicle.py`

Threshold watcher — no LLM, just string templates:

```python
THRESHOLDS = {
    "battery_soc": {"warn": 0.50, "critical": 0.25},
    "cpu_load":    {"warn": 0.70, "critical": 0.90},
    "panel_temp":  {"warn": 55.0, "critical": 80.0},
}
def check_thresholds(state, prev_state) -> list[str]:
    logs = []
    if state.eps.battery_soc < THRESHOLDS["battery_soc"]["warn"]:
        logs.append(f"> ⚠ WARN: EPS Battery SOC at {state.eps.battery_soc*100:.1f}%")
    return logs
```

---

## Phase 3 — ORACLE (Hours 6–9)

Wire `backend/oracle/agent.py` (already scaffolded) around `run_monte_carlo`:

```python
from backend.simulator.engine import run_monte_carlo

def simulate_all_options(current_state, sherlock_diagnosis, n_runs=50):
    actions = ["shed_nonessential_load", "switch_redundant_power_bus"]
    results = {}
    for action in actions:
        results[action] = run_monte_carlo(
            current_state=current_state, proposed_action=action,
            n_runs=n_runs, steps=300, fault=sherlock_diagnosis.primary_root_cause)
    return format_as_oracle_simulation(results)
```

Output: `{"type": "oracle", "plans": [{"name": "Plan A", "nominal_recovery_rate": 0.87, ...}]}`

---

## Phase 4 — ATHENA (Hours 9–13) 🤖 Only LLM-heavy build

Copy SHERLOCK's pattern exactly. Prompt = SHERLOCK diagnosis + ORACLE results + RECOVERY_CATALOG.
Claude outputs JSON with `reasoningCoT[]` array + ordered `steps[]` list.
Temperature: 0.1 (same as SHERLOCK). Max retries: 3. Validate JSON schema same way.

---

## Phase 5 — GUARDIAN (Hours 13–16)

No LLM. Map SHERLOCK urgency field:
- LOW/MEDIUM → `AUTOMATED_GUARDED` (auto-executes, logs it)
- HIGH/CRITICAL → `MANUAL_INTERLOCK` (waits for UI toggle)

**Bonus wow factor:** Wire Z3 solver for one formal constraint proof:
`solver.add(battery_soc > 0.15)` → display "Formally Verified ✓" in UI

---

## Phase 6 — QUARTERMASTER (Hours 16–18) — LOW PRIORITY

2 hardcoded ground station passes (realistic names + times). Load offload rule:
- If severity HIGH/CRITICAL → offload 35% load to backup satellite in fleet.

---

## Phase 7 — SCRIBE (Hours 18–21)

Jinja2 template collecting all agent outputs into markdown runbook.
One tiny Claude call for 2-sentence executive summary paragraph only.
Triggers auto-download of `.txt` runbook file.

---

## Phase 8 — Full End-to-End Run (Hours 21–24)

1. `uvicorn backend.api:app --reload --port 8000`
2. `npm run dev`
3. Run full pipeline at least 3 times clean before touching anything else
4. Fix broken things only — **no new features at this stage**

---

## WOW Factors — Things That Make Judges Stop

1. **Real OPSSAT-AD data on SENTINEL** — "This XGBoost was trained on 67,000 rows of real ESA satellite telemetry. F1 of 0.89 on held-out test set. Not synthetic."

2. **Graph-constrained SHERLOCK** — Claude can ONLY pick root causes from the physical causal graph. It cannot hallucinate a subsystem not connected to the flagged one. Show the graph visually.

3. **run_monte_carlo: 50+ physics simulations in ~2 seconds** — Real stochastic outcomes from a real orbital physics model. Three probability bars = real numbers, not made up.

4. **Human-in-the-loop GUARDIAN toggle** — Flip on camera. "For CRITICAL urgency, this never auto-executes. Every approval is logged to the runbook."

5. **SCRIBE runbook auto-downloads** — "This is the audit trail mission controllers keep on file."

6. **Z3 formal verification (bonus)** — "We mathematically proved this recovery action can never drop battery below survival threshold." Even non-technical judges feel the weight of this.

7. **Scenario Picker** — Judges choose which fault to inject (4 options with severity sliders). Interactive = impressive.

8. **Agent Timeline Strip** — Horizontal bar showing SENTINEL → SHERLOCK → ORACLE → ATHENA → GUARDIAN → SCRIBE, each lighting up as it completes. Judges see the pipeline working in real time.

---

## NEW: Scenario Picker UI (Phase 1 Frontend)

Replace the single "Trigger Anomaly" button with a modal showing 4 scenario cards:

| Scenario | Fault Key | Default Severity | Visual |
|---|---|---|---|
| 🔋 Battery Degradation | `eps_battery_degradation` | 0.7 | SOC drops gradually |
| 🌡️ Thermal Runaway | `tcs_thermal_runaway` | 0.7 | Temp climbs unbounded |
| ⚡ Cascading Power Failure | `eps_cascade_power_failure` | 0.9 (fixed) | All 5 subsystems degrade |
| 🔄 Reaction Wheel Failure | `adcs_reaction_wheel_degradation` | 0.6 | Attitude error grows |

Each card sends `POST /trigger` with `{ fault: "<key>", severity: <value> }`.

---

## NEW: Digital Twin Emphasis (Throughout)

- Label the physics simulator section in the UI as **"DIGITAL TWIN ENGINE"**
- Show a visible badge: "Physics-Based Digital Twin | 6 Subsystems | 18 Causal Edges"
- During Monte Carlo, show count-up: "Simulating 87/100 futures..."
- In ORACLE results panel: "Digital Twin Prediction Results"

---

## NEW: Split-Screen View (Phase 3)

When ORACLE runs, show left = current state bars, right = predicted future state bars.
The "Do Nothing" baseline on the right shows what happens without intervention.

---

## NEW: API Response Caching (Phase 1)

Cache one full SHERLOCK response for `eps_battery_degradation` as JSON fallback.
If OpenRouter API is slow/down during demo, serve cached response with `[CACHED]` label.
**This is your safety net. Do not skip this.**

---

## NEW: Real Satellite Fault Physics Rules

These are real engineering thresholds that make our simulator credible:

| Parameter | Warning | Critical | Mission Loss |
|---|---|---|---|
| Battery SOC | < 50% | < 25% | < 15% |
| Bus Voltage (28V bus) | < 25V | < 22V | < 18V |
| Panel Temperature | > 55°C or < -10°C | > 80°C or < -20°C | > 100°C |
| Battery Temperature | > 35°C | > 40°C | > 45°C (thermal runaway risk) |
| Attitude Error | > 5° | > 15° | > 30° (tumble) |
| Reaction Wheel Speed | > 5000 RPM | > 6000 RPM (saturation) | Wheel failure |
| Signal Strength | < -95 dBm | < -105 dBm | < -115 dBm (loss of lock) |
| CPU Load | > 70% | > 90% | Watchdog trip |

**ORACLE must always include a "Do Nothing" baseline** — this shows judges what happens without intervention.

---

## Cut Priority (If Time Runs Out)

| Cut | Fallback |
|---|---|
| QUARTERMASTER orbital mechanics | Static labeled "simulated" output |
| GUARDIAN Z3 proof | Plain Python rule checks, say so honestly |
| SCRIBE LLM summary | Jinja2 template sentence |
| CHRONICLE live streaming | Short static log matching scenario |
| **NEVER CUT** | **Phase 1 Bridge + SENTINEL + SHERLOCK** |

---

## Environment Setup

```bash
# Python deps
pip install fastapi uvicorn websockets openai pydantic numpy joblib scikit-learn xgboost jinja2

# API key (OpenRouter)
export OPENROUTER_API_KEY="your_key_here"

# Start backend
uvicorn backend.api:app --reload --port 8000

# Start frontend (separate terminal)
npm run dev
```

---

## File Map — What to Create

```
aero_astra/
├── backend/
│   ├── api.py               ← CREATE Phase 1 — FastAPI WebSocket bridge
│   ├── vitals.py            ← CREATE Phase 2
│   ├── chronicle.py         ← CREATE Phase 2
│   ├── guardian.py          ← CREATE Phase 5
│   ├── quartermaster.py     ← CREATE Phase 6
│   ├── scribe.py            ← CREATE Phase 7
│   ├── athena/
│   │   ├── agent.py         ← CREATE Phase 4
│   │   ├── prompts.py       ← CREATE Phase 4
│   │   └── schemas.py       ← CREATE Phase 4
│   ├── simulator/           ✅ EXISTS
│   ├── sentinel/            ✅ EXISTS
│   ├── sherlock/            ✅ EXISTS
│   ├── oracle/              🟡 EXISTS — wire it
│   └── models/              ✅ EXISTS — sentinel_production.pkl
└── src/App.jsx              ← UPDATE Phase 1 — add WebSocket client
```
