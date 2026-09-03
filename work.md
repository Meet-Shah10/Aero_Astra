# AERO-ASTRA — Execution Order (updated 2026-09-03)

### One document. What's done, what's next, in order. Read `roadmap.md` for the full detailed status table and the *why* behind decisions — this file is the short, ordered checklist for someone about to start typing.

The previous version of this file was written before `backend/api.py` existed and before ATHENA was built. Both are true now. This is a fresh version, not a patch — the old one referenced frontend files (`useIncidentStream.ts`, `types/incident.ts`) that don't exist in the current frontend anymore.

---

## 0. Checkpoint — where we are right now

- [x] Frontend — full dashboard, silver/black palette, 9-agent drill-down console, SHERLOCK causal-graph animation
- [x] SENTINEL — trained model + 2 detection engines (Engine B physics-threshold ours, Engine B spike/reversal Meet's — see `roadmap.md` §2 for the honest comparison, one is noisy)
- [x] SHERLOCK — LLM + causal graph, untouched across all 3 team branches
- [x] Physics simulator — real, untouched across all 3 branches
- [x] ORACLE — fully wired
- [x] ATHENA — done, tested (25/25), merged from harsh-lal's branch
- [x] `backend/api.py` — real FastAPI + WebSocket bridge, merged from Meet's `main` branch, two bugs fixed during merge
- [ ] Frontend connected to real `api.py` — **this is the only thing standing between "impressive code that exists" and "a working demo a judge can click through"**
- [ ] VITALS, CHRONICLE, GUARDIAN (own module), QUARTERMASTER, SCRIBE — not built

**The one sentence version of what's next:** wire the frontend to the real backend — everything real is sitting behind a WebSocket nobody's frontend is listening to yet.

---

## 1. The Plan, In Order

### Phase 1 — Close the loop between frontend and `api.py` (do this first)

`api.py` already exists and already runs SENTINEL → SHERLOCK → ORACLE → GUARDIAN for real. It has two gaps that block a real demo:

1. It hardcodes one fault (`eps_cascade_power_failure` — swap this to `tcs_thermal_runaway` immediately, it's a one-line change and the current hardcoded fault is one of the 3 that barely produces a signal, see `roadmap.md` §1) and runs it once at startup.
2. Nothing reads a fault selection from the frontend — add a `POST /trigger {fault, severity}` endpoint that kicks off `simulate_stream()` for that specific fault instead of the hardcoded one.

On the frontend: replace `src/App.jsx`'s `FAULT_SCENARIOS` mock object with a real `new WebSocket('ws://localhost:8000/ws')`. The message types `api.py` already broadcasts (`telemetry`, `sentinel_alert`, `sherlock_diagnosis`, `guardian_action`, `oracle_simulation`) map closely onto the existing `scenarioPhase` state machine already in `App.jsx` — this is closer to relabeling than rebuilding.

**Why first:** this alone turns the entire dashboard from mocked to real, using code that already exists and is already tested. Every other phase below adds capability; this phase makes the capability that already exists visible.

### Phase 2 — Wire ATHENA into `api.py`

`AthenaAgent().plan(sherlock_diagnosis, oracle_response)` → call it after the ORACLE background task resolves, broadcast `.to_ws_message()`. ATHENA is done and tested — this is pure integration, should take under an hour.

### Phase 3 — VITALS + CHRONICLE (no LLM, cheap, do together)

```python
def compute_health_score(state) -> dict:
    battery_score = state.eps.battery_soc * 100        # weight: 35%
    thermal_score = max(0, 100 - abs(state.tcs.panel_temp - 25) * 2)  # weight: 25%
    cpu_score = (1 - state.obc.cpu_load) * 100          # weight: 20%
    comms_score = (1 - state.ttc.bit_error_rate) * 100  # weight: 20%
    overall = battery_score*0.35 + thermal_score*0.25 + cpu_score*0.20 + comms_score*0.20
    return {"overall_score": round(overall, 1), "rul_orbits": compute_rul(state)}
```
CHRONICLE: watch the same state stream `api.py` already has, print a formatted line whenever a threshold crosses or another agent produces output. String templates, no LLM — more reliable in a live demo than an LLM call would be.

### Phase 4 — Extract GUARDIAN into its own module

The decision logic is already correct and already running, just embedded inline inside `api.py`'s `simulate_stream()`. Pull it into `backend/guardian.py` as a standalone, independently-testable function — almost pure copy-paste, no new logic needed.

### Phase 5 — Fix Engine B's debounce (see `roadmap.md` §2 and §4.3 for the full data)

Not urgent for the demo (Engine A / physics-threshold Engine B already cover the 3 MVP faults reliably), but worth doing once the phases above are solid. A consecutive-steps filter was tried and reverted — it kills real detections along with false ones, because a spike+reversal is a one-shot event, not a sustained state. Try a rolling event-count window instead, and actually measure the false-positive/true-positive rate before shipping it, the same way the current numbers in `roadmap.md` were measured.

### Phase 6 — QUARTERMASTER (mostly static)

2 hardcoded ground-station passes (realistic names/times). If severity is HIGH/CRITICAL, offload 35% load to a backup satellite in a fixture fleet. Lowest judge-value agent — don't over-invest here.

### Phase 7 — SCRIBE (templating, barely any code)

Jinja2 template collecting all agent outputs into a markdown runbook, matching the shape the frontend's `.txt` runbook download already produces on the mocked path. One small LLM call for a 2-3 sentence executive summary if there's time; everything else should be plain templating since it needs to be reliable in front of judges.

### Phase 8 — Re-tune the other 3 faults

Once the 3-fault MVP demos clean, extend to all 6 by fixing `eps_battery_degradation`/`adcs_reaction_wheel_degradation`/`eps_cascade_power_failure`'s modifier magnitudes in `faults.py`. Re-run `run_monte_carlo` afterward — these constants feed ORACLE's outcome distributions too.

### Phase 9 — Full run-through, then stop building

Run the whole pipeline start to finish, at least twice, before touching polish or slides. Fix only what's broken. No new features once this phase starts.

---

## 2. LLM choice — see `roadmap.md` §5 for the full brainstorm

Short version: primary recommendation is Gemini Flash via OpenRouter's free tier (zero code changes, same client, check the current free model ID at `openrouter.ai/models?max_price=0` before switching since these shift over time). Fallback for demo-time rate-limiting: Groq hosting Llama 3.3 70B, fastest inference available, needs a small `base_url` swap. Build and test the fallback toggle before you need it live, not during.

---

## 3. If You're Running Low On Time — What To Cut, In Order

1. QUARTERMASTER real logic → static, clearly-labeled "simulated" output
2. SCRIBE's LLM-written summary → template sentence instead
3. CHRONICLE's live threshold-watching → short static log matching the scenario
4. Engine B's spike-detector fix → ship with just Engine A + our physics-threshold Engine B, they already cover the 3 MVP faults
5. **Never cut:** Phase 1 (the frontend↔backend bridge), SENTINEL, SHERLOCK, ORACLE, ATHENA. Those are real, tested, and already built — protect them above everything else.

---

## 4. Demo Script Checklist

- [ ] Open on the dashboard, calm state, all nominal
- [ ] Click the trigger button on Thermal Runaway — narrate what SENTINEL is doing while it happens, don't wait in silence
- [ ] Let SHERLOCK's diagnosis appear, open its causal-graph page, point at the animated backtrace to the root cause — mention it's constrained to a physically-valid candidate set (18 real edges), a free-roaming agent can't do this
- [ ] Show ORACLE's Monte Carlo comparison
- [ ] Show ATHENA's reasoning, out loud, not just on screen
- [ ] Trigger the same fault at high severity — click the GUARDIAN approval toggle yourself, on camera. This is the two-outcomes-same-pipeline moment, the actual differentiator
- [ ] If asked "what about a sudden temperature spike right now" — you have the real answer: FDIR/Safe Mode, already implemented in `api.py`, and `tcs_thermal_runaway` is that exact scenario
- [ ] Open the SCRIBE runbook at the end and scroll it, if built — the audit-trail proof moment
- [ ] Close with the honest data line: real F1/ROC-AUC on real ESA data for SENTINEL, real Mars Express data for the EPS/ADCS forecasters, clearly-labeled synthetic physics for the rest — judges reward honesty about what's real over inflated claims

---

*This file replaces the previous version — it was written before `backend/api.py` and ATHENA existed and referenced frontend files that no longer exist. `roadmap.md` has the full detailed status table, the `api.py` merge notes, and the LLM brainstorm this file summarizes.*
