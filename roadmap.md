# AERO-ASTRA — Roadmap (40-Hour Window, Frontend-Led)

> **Ownership split, effective now:** Mohit → 100% frontend (`src/`). Backend (`backend/`) is handed off completely — whoever picks it up should read [`backend.md`](backend.md) instead of this file. This file is the frontend-facing plan and the shared contract both sides build against.
>
> **The old framing was "48 hours, build 8 agents."** The new framing: **we have 40 hours, and the thing that actually needs to exist is 2-3 real, working, click-to-trigger demo flows.** Everything else is upside, not requirement. Read the MVP section first — it is the only thing that must exist for this to be a working product. Everything after it is "yes, do this too, we have time" — not a cut list.

---

## The MVP: 3 buttons, real data, two branching outcomes

This is the whole demo. Get this rock-solid before touching anything else.

**Three scenario cards, each a real click that triggers a real backend pipeline run:**

| Card | Fault | Why this one | What it proves |
|---|---|---|---|
| 🌡️ **Thermal Runaway** | `tcs_thermal_runaway` | Verified: panel_temp climbs 38°C→76°C in ~40 min at default settings — cleanest, most dramatic real signal we have | The FDIR/Safe-Mode story (see below) — this is *literally* the "sudden temperature spike" scenario judges ask about |
| 📡 **Signal Dropout** | `ttc_signal_dropout` | Verified: signal_strength crashes to -114.7 dBm (past mission-loss line) within the demo window | Comms-loss cascade, fast onset (30s ramp) |
| 🚀 **Thruster Fault** | `propulsion_thruster_fault` | Verified: thruster_temp redlines to 200°C, fastest onset (15s ramp) of any fault | Mechanical/propulsion failure mode, visually distinct from the other two |

**Why only these 3, not all 6 in `faults.py`:** verified by direct testing (see [`audit_findings.md`](audit_findings.md) §3) that `eps_battery_degradation`, `adcs_reaction_wheel_degradation`, and `eps_cascade_power_failure` don't move their telemetry far enough within a demo-length window (severity 0.7, ~1hr) for *any* detector — real ESA-trained model or physics-threshold engine — to fire cleanly. Rather than gamble on a fault that might not visibly trigger live in front of judges, we lead with the 3 that are proven to work every time. (The other 3 aren't gone — see "Later, once the MVP is solid" below. They just need their `faults.py` magnitudes re-tuned first, which is a backend task, not a frontend blocker.)

### The severity slider is what creates the second demo path

Each scenario card keeps its severity slider (already speced below under "Scenario Picker UI"). The slider isn't just cosmetic — **it's what decides which of the two GUARDIAN outcomes plays out**, and showing both is the actual differentiator:

**Path A — "Easy" / low severity → `AUTOMATED_GUARDED`**
SHERLOCK's `urgency` comes back LOW/MEDIUM. GUARDIAN auto-executes the recovery action with zero human click, logs it, done. This is the fast, boring, "the system just handles it" path. **Build this first** — it's the simplest to wire (no UI interaction state, no approval modal), and it's the one that proves the pipeline is real end-to-end fastest. This is your quick early win.

**Path B — "High-risk" / high severity → `MANUAL_INTERLOCK`**
SHERLOCK's `urgency` comes back HIGH/CRITICAL. GUARDIAN does **not** auto-execute — it surfaces an approval modal and waits for a human click. This is the dramatic, judge-facing moment: *"For high-risk situations, nothing executes without a human. Watch — I have to click approve."* Build this second, once Path A is proven, since it's the same pipeline plus one extra UI state (waiting-for-approval) and one extra backend gate.

**Bonus third tier, if time allows — `AUTONOMOUS_SAFED` (the FDIR answer):**
If `time_to_critical_estimate_minutes` (already a real field SHERLOCK outputs, see `backend/sherlock/schemas.py:166`) drops below a threshold, GUARDIAN doesn't wait for either of the above — it fires the cheapest safe action (`shed_nonessential_load`) immediately, notifies the operator, and queues the full review for after. This is real spacecraft doctrine (FDIR / Safe Mode — the standard NASA/ESA answer to "what if something goes wrong *right now*"), it directly answers the temperature-spike question, and it reuses data + an action you already have. It's a genuinely small addition once Path A and B exist — a third `if` branch in GUARDIAN's decision function, not a new system. Do it if there's time; the demo works with just A and B.

```python
# backend/guardian.py — the whole decision, once ORACLE/SHERLOCK exist
SAFE_MODE_THRESHOLD_MIN = 5

def guardian_decide(diagnosis, oracle_response):
    if diagnosis.time_to_critical_estimate_minutes < SAFE_MODE_THRESHOLD_MIN:
        return {"tier": "AUTONOMOUS_SAFED", "auto_executes": True,
                "requires_human_approval": False, "action": "shed_nonessential_load"}
    if diagnosis.urgency in ("HIGH", "CRITICAL"):
        return {"tier": "MANUAL_INTERLOCK", "auto_executes": False,
                "requires_human_approval": True, "action": oracle_response.best_action}
    return {"tier": "AUTOMATED_GUARDED", "auto_executes": True,
            "requires_human_approval": False, "action": oracle_response.best_action}
```

### "Real" beats "impressive" — say this to yourself when a number looks boring

If a telemetry value on screen reads `1.24, 1.24, 1.24, 1.24` for ten ticks in a row because that's genuinely what the physics simulator is outputting right now — **that is a win, not a bug.** It means the number came from a real WebSocket message, not a fake timer. Do not "fix" real-but-boring data by adding jitter or fallback animations. The entire point of Phase 1 (the bridge) is replacing fake numbers with real ones; a real number that happens to be flat is still real. Judges (and you) can tell the difference between "this is animating because it's scripted" and "this is animating because it's physics" — but only if you don't fake the second one to look more like the first.

---

## What We Have Right Now

| Component | Location | Status | Notes |
|---|---|---|---|
| **3D Landing + Dashboard UI** | `src/App.jsx` | ✅ Working | Three.js globe, camera dolly, satellite GLB, full agent panels — **but still 100% `setTimeout` fakes, zero WebSocket/fetch calls.** This is the actual current blocker. |
| **SENTINEL** (XGBoost) | `backend/models/sentinel_production.pkl` | ✅ Working, regenerated | Was a broken git-lfs pointer stub as of 2026-09-03 — retrained from real local OPSSAT data, now a real 1.38MB model, F1 0.65 row-level. Structurally blind to all 6 simulator faults on its own (flatline-only features) — **must be combined with Engine B**, see below. |
| **Engine B** | `backend/sentinel/engine_b.py` | ✅ Built | Physics-threshold detector, zero training needed. Fires correctly on the 3 MVP faults, zero false positives on nominal. `combined_score(ml_score, state)` = `max(SENTINEL, Engine B)`, degrades gracefully if the `.pkl` fails to load. |
| **SimulatorTelemetryProvider** | `backend/sherlock/simulator_provider.py` | ✅ Built | Bridges `SatelliteState` → SHERLOCK's `TelemetrySnapshot`. Smoke-tested. |
| **SHERLOCK** (LLM + graph) | `backend/sherlock/agent.py` | ✅ Built | Claude via OpenRouter, graph-constrained, 3-retry validation loop. 18-edge causal graph confirmed real. |
| **Physics Simulator** | `backend/simulator/engine.py` | ✅ Built | `simulate_scenario()` + `run_monte_carlo()` exist and work. |
| **RECOVERY_CATALOG** | `backend/simulator/recovery.py` | ✅ Built | 6 named actions with subsystem modifiers. |
| **ORACLE** | `backend/oracle/agent.py` | ✅ Actually fully wired | Confirmed `run_oracle()`, `_evaluate_action()`, fallback ranking mode all work and call `run_monte_carlo` for real. Just needs `backend/api.py` to import and call it. |
| **requirements.txt** | `backend/requirements.txt` | ✅ Built | Didn't exist before. Install this on whichever laptop runs the demo. |
| **ATHENA** | `backend/athena/agent.py` | ✅ Built (harsh-lal, merged 2026-09-03) | Two-Schema Pattern (LLM never outputs `safety_score`/`blended_rank`/`is_irreversible` — those are injected/computed post-validation, so the LLM can't hallucinate a score). Same JSON-parse → schema-validate → anti-hallucination → retry loop as SHERLOCK. 25/25 tests pass. Verified byte-for-byte against `backend/sherlock`, `backend/oracle`, `backend/simulator` on harsh-lal's branch — those three were untouched, so there was nothing to reconcile there. |
| **`backend/api.py`** (the bridge) | — | ❌ **Does not exist — this is the #1 blocker** | Nothing above matters to a judge until this exists and the frontend talks to it. |
| CHRONICLE, VITALS, GUARDIAN, QUARTERMASTER, SCRIBE | — | ❌ Not built | Build in the order below, after the bridge |

---

## Architecture Overview

```
[Browser Frontend — src/App.jsx]
       │  WebSocket ws://localhost:8000/ws/mission
       │
[FastAPI Bridge — backend/api.py]  ← BUILD THIS FIRST, BLOCKS EVERYTHING
       │
       ├── simulate_scenario()         [simulator/engine.py — EXISTS]
       ├── SENTINEL.combined_score()   [sentinel/engine_b.py + sentinel_production.pkl — EXISTS]
       ├── SHERLOCK.diagnose()         [sherlock/agent.py + simulator_provider.py — EXISTS]
       ├── run_oracle()                [oracle/agent.py — EXISTS, fully wired]
       ├── VITALS.compute()            [backend/vitals.py — BUILD, cheap]
       ├── CHRONICLE.log()             [backend/chronicle.py — BUILD, cheap]
       ├── ATHENA.plan()               [backend/athena/ — EXISTS, 25/25 tests passing]
       ├── guardian_decide()           [backend/guardian.py — BUILD, rule-based, see MVP section]
       ├── QUARTERMASTER.schedule()    [backend/quartermaster.py — BUILD, mostly static]
       └── SCRIBE.generate()           [backend/scribe.py — BUILD, templating]
```

---

## Phase 1 — The Bridge 🔴 BLOCKS EVERYTHING (backend)

**Goal:** One button click → real data flowing over a real WebSocket. Nothing else matters until this exists.

```python
# backend/api.py
from fastapi import FastAPI, WebSocket
from backend.simulator.engine import simulate_scenario
from backend.sentinel.engine_b import combined_score
from backend.sherlock.agent import SherlockAgent
from backend.sherlock.simulator_provider import SimulatorTelemetryProvider
from backend.oracle.agent import run_oracle

# POST /trigger  {"fault": "tcs_thermal_runaway", "severity": 0.7}
# WS   /ws/mission — streams JSON events shaped per the contract below
```

**Full WebSocket message contract — see [`backend.md`](backend.md) for every message type** (`telemetry`, `sentinel_alert`, `sherlock_diagnosis`, `oracle`, `guardian`, `athena`, `quartermaster`, `scribe`). The 3 that existed before (`telemetry`, `sentinel_alert`, `sherlock_diagnosis`) are unchanged; the other 5 are newly specified there so frontend and backend don't drift while building in parallel.

### Frontend change in `src/App.jsx` (this is Mohit's first task)

Replace the fake `setTimeout` cascade in `triggerAnomaly()` with:
```js
const ws = new WebSocket('ws://localhost:8000/ws/mission');
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  if (msg.type === 'telemetry') updateTelemetry(msg);
  if (msg.type === 'sentinel_alert') setScenarioPhase('detected');
  if (msg.type === 'sherlock_diagnosis') setScenarioPhase('diagnosing');
  if (msg.type === 'guardian') {
    if (msg.requires_human_approval) setScenarioPhase('awaiting_approval');
    else setScenarioPhase('auto_executed');
  }
};
fetch('http://localhost:8000/trigger', {
  method: 'POST',
  body: JSON.stringify({ fault: selectedFault, severity: sliderValue }),
});
```

**API response caching — do not skip this.** Cache one full real response set (telemetry + sentinel_alert + sherlock_diagnosis + guardian) for each of the 3 MVP faults as static JSON fallback files. If the LLM call is slow/down mid-demo, serve the cached response with a visible `[CACHED]` label rather than the demo hanging. This is the single highest-leverage 20 minutes you can spend before going on stage.

---

## Later, once the MVP is solid (we have the hours — do these too)

Nothing below is a "nice to have we'll probably cut." With 40 hours, the MVP (Phase 1 + the 3-card/2-path demo) should take a fraction of the time budget. Once it's demoed clean at least twice end-to-end, keep building — the fuller pipeline is a straightforwardly better demo, not scope creep.

### Phase 2 — VITALS + CHRONICLE (no LLM, cheap)
```python
def compute_health_score(state) -> dict:
    battery_score = state.eps.battery_soc * 100        # weight: 35%
    thermal_score = max(0, 100 - abs(state.tcs.panel_temp - 25) * 2)  # weight: 25%
    cpu_score = (1 - state.obc.cpu_load) * 100          # weight: 20%
    comms_score = (1 - state.ttc.bit_error_rate) * 100  # weight: 20%
    overall = battery_score*0.35 + thermal_score*0.25 + cpu_score*0.20 + comms_score*0.20
    return {"overall_score": round(overall, 1), "rul_orbits": compute_rul(state)}
```
CHRONICLE: threshold watcher, string templates, no LLM. See `backend.md` for the exact threshold table (recalibrated — the original numbers false-positive on this simulator's nominal thermal cycling, see `audit_findings.md` §3).

### Phase 3 — Re-tune the other 3 faults (backend, ~30-45 min)
Once the MVP's 3 cards are proven, extend the scenario picker to all 6 by fixing `eps_battery_degradation`/`adcs_reaction_wheel_degradation`/`eps_cascade_power_failure`'s modifier magnitudes in `faults.py` so they produce a visible excursion within ~10-20 minutes of sim time instead of needing hours. Re-run `run_monte_carlo` afterward to confirm ORACLE's outcome distributions still make sense — these constants feed both.

### Phase 4 — ATHENA — ✅ DONE (harsh-lal, merged 2026-09-03)
No longer a build item. `AthenaAgent.plan(sherlock_diagnosis, oracle_response)` → `RecoveryPlan` with a `.to_ws_message()` method that already matches this doc's own `athena` WS message shape. Uses the Two-Schema Pattern (LLM produces `AthenaLLMOption` — no score fields; Python injects ORACLE's real `safety_score`, computes `blended_rank`, and looks up `is_irreversible` from a hardcoded frozenset, so the LLM can never hallucinate a safety number). `backend/api.py` just needs to call `AthenaAgent().plan(...)` after ORACLE and forward `to_ws_message()`.

### Phase 5 — QUARTERMASTER (mostly static)
2 hardcoded ground-station passes (realistic names/times). If severity HIGH/CRITICAL, offload 35% load to a backup satellite in the fixture fleet.

### Phase 6 — SCRIBE
Jinja2 template collecting all agent outputs into a markdown runbook. One small Claude call for a 2-sentence executive summary. Triggers a `.txt`/`.md` auto-download.

### Phase 7 — Full end-to-end run
1. `pip install -r backend/requirements.txt` on the actual demo laptop
2. `uvicorn backend.api:app --reload --port 8000`
3. `npm run dev`
4. Run the full pipeline at least 3 times clean, on all demo-ready faults, before touching anything else
5. Fix only what's broken — no new features once this phase starts

---

## WOW Factors — Things That Make Judges Stop

1. **Two GUARDIAN outcomes, live, same pipeline** — the easy auto-executed path and the human-approval path from the *same* 3 real faults, controlled by one severity slider. This is the actual differentiator, not a feature list.
2. **The FDIR/Safe-Mode tier** (if built) — "sudden temperature spike" is a known, standard question in spacecraft ops, and `tcs_thermal_runaway` is that exact scenario. Answering it with real spacecraft doctrine (FDIR, Safe Mode) rather than improvising is a strong Q&A moment.
3. **Real OPSSAT-AD data on SENTINEL** — "trained on real ESA satellite telemetry, F1 0.65 / ROC-AUC 0.79 on held-out test data. Not synthetic." (Verified number — see `audit_findings.md`, do not cite the old 0.89 figure, it never existed in any results file.)
4. **Graph-constrained SHERLOCK** — Claude can only pick root causes from the physical causal graph (18 real edges, confirmed in code). Show the graph visually.
5. **`run_monte_carlo`: 100 physics simulations in ~2 seconds** — real stochastic outcomes, not made-up probability bars.
6. **SCRIBE runbook auto-downloads** (if built) — the audit trail mission controllers keep on file.
7. **Agent Timeline Strip** — horizontal bar showing which agent is active, lighting up as the real pipeline progresses.

---

## Scenario Picker UI (frontend)

3 scenario cards (not 6 — see MVP section for why), each with a severity slider that determines which GUARDIAN path plays out:

| Scenario | Fault Key | Severity range | Low end → | High end → |
|---|---|---|---|---|
| 🌡️ Thermal Runaway | `tcs_thermal_runaway` | 0.3 – 1.0 | AUTOMATED_GUARDED | MANUAL_INTERLOCK |
| 📡 Signal Dropout | `ttc_signal_dropout` | 0.3 – 1.0 | AUTOMATED_GUARDED | MANUAL_INTERLOCK |
| 🚀 Thruster Fault | `propulsion_thruster_fault` | 0.3 – 1.0 | AUTOMATED_GUARDED | MANUAL_INTERLOCK |

Each card sends `POST /trigger` with `{ fault: "<key>", severity: <value> }`. Exact severity→urgency mapping is SHERLOCK's call (LLM-driven), but as a UI hint, treat severity ≥ 0.7 as "likely high-risk path" so the slider itself communicates what's about to happen.

---

## Digital Twin Emphasis (throughout the UI)

- Label the physics simulator section **"DIGITAL TWIN ENGINE"**
- Visible badge: "Physics-Based Digital Twin | 6 Subsystems | 18 Causal Edges"
- During Monte Carlo: count-up "Simulating 87/100 futures..."
- ORACLE results panel: "Digital Twin Prediction Results"

---

## Real Satellite Fault Physics Rules (Engine B thresholds — recalibrated)

| Parameter | Warning | Critical | Mission Loss | Note |
|---|---|---|---|---|
| Battery SOC | < 50% | < 25% | < 15% | unchanged |
| Bus Voltage (28V bus) | < 25V | < 22V | < 18V | unchanged |
| Panel Temperature | > 55°C or < -10°C | > 80°C or < -20°C | > 100°C | unchanged |
| **Battery Temperature** | **> 44°C** | **> 48°C** | **> 52°C** | **recalibrated — original 35/40/45°C false-positives on this simulator's nominal orbital thermal cycling (verified up to 41.4°C with zero fault active)** |
| Attitude Error | > 5° | > 15° | > 30° (tumble) | unchanged |
| Reaction Wheel Speed | > 5000 RPM | > 6000 RPM (saturation) | Wheel failure | unchanged |
| Signal Strength | < -95 dBm | < -105 dBm | < -115 dBm (loss of lock) | unchanged |
| CPU Load | > 70% | > 90% | Watchdog trip | unchanged |

This table is implemented and tested in `backend/sentinel/engine_b.py` — don't hand-copy it elsewhere, import from there.

---

## Environment Setup

```bash
pip install -r backend/requirements.txt   # now exists, wasn't there before
export OPENROUTER_API_KEY="your_key_here"
uvicorn backend.api:app --reload --port 8000   # backend
npm run dev                                     # frontend, separate terminal
```

**Model files are gitignored and git-lfs is not configured in this repo.** Whoever runs the live demo needs `backend/models/*.joblib`/`*.pkl` copied onto that machine directly (zip + AirDrop/USB/Slack, not git). See `backend.md` for full details — this bit anyone who's picked up backend cold tonight.

---

## File Map

```
aero_astra/
├── backend/
│   ├── api.py                    ← BUILD FIRST — FastAPI WebSocket bridge
│   ├── requirements.txt          ✅ EXISTS
│   ├── vitals.py                 ← BUILD Phase 2
│   ├── chronicle.py              ← BUILD Phase 2
│   ├── guardian.py               ← BUILD (MVP — see decision function above)
│   ├── quartermaster.py          ← BUILD Phase 5
│   ├── scribe.py                 ← BUILD Phase 6
│   ├── athena/
│   │   ├── agent.py              ← BUILD Phase 4
│   │   ├── prompts.py            ← BUILD Phase 4
│   │   └── schemas.py            ← BUILD Phase 4
│   ├── simulator/                ✅ EXISTS
│   ├── sentinel/
│   │   ├── engine_b.py           ✅ EXISTS — physics threshold detector
│   │   └── train.py              ✅ FIXED — portable path, retrained model
│   ├── sherlock/
│   │   └── simulator_provider.py ✅ EXISTS — the bridge class
│   ├── oracle/                   ✅ EXISTS — wire it into api.py, don't rebuild
│   └── models/                   ✅ EXISTS locally — must be copied to demo laptop manually
└── src/App.jsx                   ← UPDATE Phase 1 — add WebSocket client, this is Mohit's task
```

---

*See [`audit_findings.md`](audit_findings.md) for the full verification detail behind every claim above, and [`backend.md`](backend.md) for the complete backend handoff brief — API contract, current state, and phase-by-phase backend task list, written for whoever is picking this up without today's context.*
