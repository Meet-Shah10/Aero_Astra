# AERO-ASTRA — Roadmap (40-Hour Window, Frontend-Led)

> **Ownership split, effective now:** Mohit → 100% frontend (`src/`). Backend (`backend/`) is handed off completely — whoever picks it up should read [`backend.md`](backend.md) instead of this file. This file is the frontend-facing plan and the shared contract both sides build against.
>
> **Last full verification pass: 2026-09-03.** Everything marked ✅ below was actually run — tests executed, empirical checks against the real simulator, not just read on the page. Everything marked 🟡 is real code that exists but has a known, measured issue. Everything marked ⬜ genuinely doesn't exist yet.

---

## 0. Status checklist — tick these off as they land

**Backend agents**
- [x] SENTINEL — trained model + Engine B physics-threshold detector (see §2, known limitation on 3/6 faults)
- [x] SHERLOCK — LLM + 18-edge causal graph, untouched and verified identical across all 3 team branches
- [x] Physics Simulator — `simulate_scenario()` + `run_monte_carlo()`, real orbital dynamics
- [x] ORACLE — fully wired, 100-run Monte Carlo, fallback ranking mode
- [x] ATHENA — merged from harsh-lal's branch, 25/25 tests passing, Two-Schema anti-hallucination pattern
- [x] `backend/api.py` — merged from Meet's `main` branch, real FastAPI + WebSocket bridge (see §3 for what's real vs. still needed)
- [ ] VITALS — not built
- [ ] CHRONICLE — not built
- [ ] GUARDIAN — logic exists *inline inside `api.py`*, not yet its own module (see §3)
- [ ] QUARTERMASTER — not built
- [ ] SCRIBE — not built

**Frontend**
- [x] Full dashboard UI, silver/black palette, PillNav, agent console, 9 agent drill-down pages
- [x] SHERLOCK causal-graph animation (SVG + GSAP)
- [x] SENTINEL side-by-side dataset comparison view
- [ ] Connected to the real `backend/api.py` WebSocket — **still 100% mocked data in `FAULT_SCENARIOS`, this is the #1 remaining blocker**

**Known bugs to fix before demo (see §3 for detail)**
- [ ] `api.py` hardcodes a single fault (`eps_cascade_power_failure`) at startup — no way for the frontend's scenario picker to actually pick a fault yet
- [ ] `api.py` doesn't call ATHENA at all — SENTINEL → SHERLOCK → ORACLE → GUARDIAN only
- [ ] Engine B's spike detector (`score_physics_spike`) has an unsolved false-positive/debounce problem — documented, not silently shipped, see §3

---

## 1. The MVP: 3 buttons, real data, two branching outcomes

This is the whole demo. Get this rock-solid before touching anything else.

**Three scenario cards, each a real click that triggers a real backend pipeline run:**

| Card | Fault | Why this one | What it proves |
|---|---|---|---|
| 🌡️ **Thermal Runaway** | `tcs_thermal_runaway` | Verified: panel_temp climbs 38°C→76°C in ~40 min at default settings — cleanest, most dramatic real signal we have | The FDIR/Safe-Mode story — this is *literally* the "sudden temperature spike" scenario judges ask about |
| 📡 **Signal Dropout** | `ttc_signal_dropout` | Verified: signal_strength crashes to -114.7 dBm (past mission-loss line) within the demo window | Comms-loss cascade, fast onset (30s ramp) |
| 🚀 **Thruster Fault** | `propulsion_thruster_fault` | Verified: thruster_temp redlines to 200°C, fastest onset (15s ramp) of any fault | Mechanical/propulsion failure mode, visually distinct from the other two |

**Why only these 3, not all 6 in `faults.py`:** verified by direct testing (see [`audit_findings.md`](audit_findings.md) §3) that `eps_battery_degradation`, `adcs_reaction_wheel_degradation`, and `eps_cascade_power_failure` don't move their telemetry far enough within a demo-length window for *any* detector to fire cleanly. Lead with the 3 that are proven to work every time.

### The severity slider creates the second demo path

**Path A — "Easy" / low severity → `AUTOMATED_GUARDED`.** SHERLOCK's `urgency` comes back LOW/MEDIUM. GUARDIAN auto-executes, logs it, done. Build/verify this first.

**Path B — "High-risk" / high severity → `MANUAL_INTERLOCK`.** SHERLOCK's `urgency` comes back HIGH/CRITICAL. GUARDIAN waits for a human click. The judge-facing moment.

**Third tier — `AUTONOMOUS_SAFED` (the FDIR answer) — ✅ already implemented, in `api.py`, not just planned:**

```python
# backend/api.py — this exact logic is already live
ttc = diagnosis.time_to_critical_estimate_minutes
if ttc is not None and ttc < 5:
    guardian_status = "AUTONOMOUS_SAFED"
    action_taken = "shed_nonessential_load"
elif diagnosis.urgency in (UrgencyLevel.HIGH, UrgencyLevel.CRITICAL):
    guardian_status = "MANUAL_INTERLOCK"
else:
    guardian_status = "AUTOMATED_GUARDED"
```

This is a genuinely good sign of team alignment — this is almost exactly the pseudocode this doc sketched before `api.py` existed. It's currently inline in `api.py`'s `simulate_stream()`; pulling it into its own `backend/guardian.py` module is a cheap, worthwhile cleanup (see §4).

### "Real" beats "impressive" — say this to yourself when a number looks boring

If a telemetry value on screen reads `1.24, 1.24, 1.24, 1.24` for ten ticks in a row because that's genuinely what the physics simulator is outputting right now — **that is a win, not a bug.** Do not "fix" real-but-boring data by adding jitter. A real number that happens to be flat is still real.

---

## 2. What We Have Right Now

| Component | Location | Status | Notes |
|---|---|---|---|
| **3D Dashboard UI** | `src/App.jsx` + `src/components/` | ✅ Working | Silver/black palette, PillNav, 9-agent drill-down console, SHERLOCK causal graph — but **still 100% mocked data**, zero WebSocket calls. This is the actual current blocker. |
| **SENTINEL — flatline/XGBoost (Engine A)** | `backend/models/sentinel_production.pkl` + `backend/sentinel/engines.py` | 🟡 Working, structurally limited | Real model, real predict_proba calls. Confirmed (again) via direct testing: does not fire on the ramping simulator faults on its own — this is inherent to what flatline features can see, not a bug. |
| **SENTINEL — Engine B (physics threshold)** | `backend/sentinel/engine_b.py` | ✅ Built, reliable | Ours. Zero training needed. Fires correctly on all 3 MVP faults, zero false positives on nominal, after battery_temp recalibration. `combined_score(ml_score, state)` degrades gracefully if the `.pkl` fails to load. |
| **SENTINEL — Engine B (spike/reversal)** | `backend/sentinel/engines.py::score_physics_spike` | 🟡 Working, noisy | Meet's. Different approach — MAD-based spike+reversal detection on 3 named channels, "1-of-3 isolation" to avoid correlated-motion false alarms. **Measured directly**: ~2-4% per-timestep false-positive rate on clean nominal data (11-26 false alarms per 600-step run across 5 random seeds). A consecutive-steps debounce (same shape as Engine A's) was tried and reverted — it suppresses ~100% of real detections too, since a spike+reversal is a one-shot transient, not a sustained state. Needs a rolling event-count debounce instead, properly tuned — flagged as open work in §4, not silently shipped broken. |
| **SENTINEL — EPS/ADCS forecasters** | `backend/sentinel/eps_tcs.py`, `adcs.py` | ⬜ Trained offline, not wired into the live pipeline | Meet's work. Trains an XGBoost MultiOutputRegressor forecaster on real Mars Express spacecraft telemetry (`data/raw/mars_express/`) — genuinely the Telemanom-style "forecast, flag large error" approach `audit_findings.md` §4 discussed as a stretch goal. Not called by `api.py` yet. Real training data, real capability, just not plumbed in. |
| **SimulatorTelemetryProvider** | Two copies — see below | 🟡 Duplicated | `backend/sherlock/simulator_provider.py` (ours, standalone module, smoke-tested) and an inline class of the same name inside `backend/api.py` (Meet's, actually running in the live bridge, slightly different parameter naming). Functionally overlapping. Consolidate onto one — low priority, doesn't block anything, see §4. |
| **SHERLOCK** (LLM + graph) | `backend/sherlock/agent.py` | ✅ Built | Claude via OpenRouter, graph-constrained, 3-retry validation loop. 18-edge causal graph. Confirmed byte-identical across mohit-rawat, harsh-lal, and Meet's main — untouched by anyone, which is exactly what you want from a component everyone depends on. |
| **Physics Simulator** | `backend/simulator/engine.py` | ✅ Built | `simulate_scenario()` + `run_monte_carlo()` exist and work. Also confirmed byte-identical across all 3 branches. |
| **RECOVERY_CATALOG** | `backend/simulator/recovery.py` | ✅ Built | 6 named actions with subsystem modifiers. |
| **ORACLE** | `backend/oracle/agent.py` | ✅ Fully wired | `run_oracle()`, `_evaluate_action()`, fallback ranking mode all call `run_monte_carlo` for real. |
| **ATHENA** | `backend/athena/agent.py` | ✅ Built, merged from harsh-lal, 2026-09-03 | Two-Schema Pattern — LLM never outputs `safety_score`/`blended_rank`/`is_irreversible`, those are injected/computed after validation, so the LLM structurally cannot hallucinate a safety number. 25/25 tests pass. **Not yet called by `api.py`** — see §3. |
| **`backend/api.py`** (the bridge) | `backend/api.py` | 🟡 Real and running, not feature-complete | Merged from Meet's `main` branch, 2026-09-03. Real FastAPI app, real `/ws` WebSocket endpoint, real `ConnectionManager` broadcast pattern, real background-task handling for ORACLE. Two bugs found and fixed during merge (see §3). Two gaps remain open: hardcoded single fault, no ATHENA call. |
| **requirements.txt** | `backend/requirements.txt` | ✅ Built | Install this on whichever laptop runs the demo. |

---

## 3. What changed in the `api.py` merge — read this before touching it

Pulled from Meet's `main` branch (which also had a full independent SENTINEL rewrite). Compared file-by-file against our branch before merging — this section is what actually changed, not a changelog dump.

**Two real bugs found by reading + testing, fixed during merge:**

1. **Timestamp bug.** `SimulatorTelemetryProvider.get_subsystem_snapshot()` and the SHERLOCK diagnosis call both did `datetime.fromtimestamp(frame.timestamp, tz=timezone.utc)` — but `frame.timestamp` is *simulation-elapsed seconds* (0.0 → 600.0), not a Unix epoch offset. That produces timestamps near 1970-01-01, not "now." Fixed: both now use `datetime.now(timezone.utc)`, since what actually matters for a live-streaming demo is the real wall-clock time the frame was processed.

2. **Engine B false-positive rate, tried a fix, reverted it.** See the SENTINEL table row above. Documented in `api.py` itself with a comment explaining exactly why a naive fix is wrong, so nobody re-introduces it under time pressure.

**Two known gaps, not fixed yet — deliberately, this needs real design time, not a rushed patch:**

1. **`api.py` hardcodes `fault_scenario = "eps_cascade_power_failure"` at startup** and runs it once. There is no code path that reads a fault selection from the frontend at all — `websocket_endpoint()` receives incoming text and discards it (`data = await websocket.receive_text()`, never parsed). The frontend's scenario picker (3 cards + severity slider) has nothing to actually call yet. **This is the single most important thing to build next** — a `POST /trigger {fault, severity}` endpoint (or a parsed WS message) that starts `simulate_stream()` with the frontend's actual selection, replacing the hardcoded fault. Also: `eps_cascade_power_failure` is one of the 3 *weak-signal* faults from §1 — the current hardcoded demo is running the fault least likely to visibly trigger. Swap the hardcoded default to `tcs_thermal_runaway` immediately, even before the picker is wired.

2. **ATHENA is not called anywhere in `api.py`.** The pipeline currently stops at GUARDIAN. Given ATHENA is done and tested (§2), wiring it in is small: after the ORACLE background task resolves, call `AthenaAgent().plan(sherlock_diagnosis, oracle_response)` and broadcast `.to_ws_message()`. Should take under an hour.

---

## 4. What's next — in priority order

1. **Wire the frontend to the real `api.py`.** This is the actual #1 blocker — everything above this line is real, working backend code that nobody outside a Python REPL can see yet. Concretely:
   - Add a `POST /trigger` endpoint to `api.py` that accepts `{fault, severity}` and starts a `simulate_stream()` run for that specific fault (currently hardcoded).
   - Replace `src/App.jsx`'s `FAULT_SCENARIOS` mock object with a real `WebSocket('ws://localhost:8000/ws')` connection; map incoming `{type: "telemetry"|"sentinel_alert"|"sherlock_diagnosis"|"guardian_action"|"oracle_simulation"}` messages onto the existing `scenarioPhase` state machine — the phase names already line up closely with what `api.py` broadcasts.
   - Swap the hardcoded fault to `tcs_thermal_runaway` as an immediate stopgap even before the picker is wired end-to-end.
2. **Wire ATHENA into `api.py`** (see §3 — small, well-scoped, already tested).
3. **Fix Engine B's debounce properly.** Not a consecutive-steps filter (tried, reverted — kills real signal). Try a rolling event-count window (e.g., "≥2 raw spike flags within any 20-30 step window") and *actually measure it* against all 6 faults + nominal before shipping, the same way every other claim in this doc was verified. Budget real time for this — it's a tuning problem, not a one-line fix.
4. **VITALS + CHRONICLE** — no LLM, cheap, straightforward functions over the same `SatelliteState` stream `api.py` already has:
   ```python
   def compute_health_score(state) -> dict:
       battery_score = state.eps.battery_soc * 100
       thermal_score = max(0, 100 - abs(state.tcs.panel_temp - 25) * 2)
       cpu_score = (1 - state.obc.cpu_load) * 100
       comms_score = (1 - state.ttc.bit_error_rate) * 100
       overall = battery_score*0.35 + thermal_score*0.25 + cpu_score*0.20 + comms_score*0.20
       return {"overall_score": round(overall, 1), "rul_orbits": compute_rul(state)}
   ```
5. **Pull GUARDIAN's inline logic into `backend/guardian.py`** as its own module (it's already correct, just embedded in `simulate_stream()` — extracting it is almost pure copy-paste, and makes it independently testable).
6. **QUARTERMASTER** — mostly static: 2 hardcoded ground-station passes, offload rule on HIGH/CRITICAL severity. Lowest judge-value agent, don't over-invest.
7. **SCRIBE** — Jinja2 template over the full pipeline output → markdown runbook. One small LLM call for a 2-sentence executive summary; everything else plain templating (reliability > cleverness in front of judges).
8. **Consolidate the duplicate `SimulatorTelemetryProvider`** (§2) onto one implementation. Low priority, doesn't block anything.
9. **Wire Meet's EPS/ADCS forecasters (`eps_tcs.py`/`adcs.py`) as a real Engine C**, once Engine B's debounce is solid — this is real, trained, working forecast-residual capability that's currently sitting unused. Worth doing specifically because it's the Telemanom-style approach `audit_findings.md` recommended as the *right* fix for slow-ramp faults, and someone already built the training pipeline for it.
10. **Re-tune the other 3 faults** in `faults.py` (`eps_battery_degradation`, `adcs_reaction_wheel_degradation`, `eps_cascade_power_failure`) so all 6 are demo-viable, not just 3.

---

## 5. Which LLM to use — brainstormed, optimized for free + fast

SHERLOCK and ATHENA both currently call `anthropic/claude-sonnet-4-5` via OpenRouter. That's a paid model — worth knowing the free/cheap options given cost and rate-limit risk during a live demo, especially with two agents both making LLM calls in the same pipeline run.

**What actually matters here, given how SHERLOCK/ATHENA are built:** both already have a 3-retry JSON-schema-validation loop with re-prompting on failure (see `backend/sherlock/agent.py` / `backend/athena/agent.py`). That retry loop is what makes swapping models low-risk — a model that occasionally messes up strict JSON still works fine, it just costs a retry. The two things that actually matter for the swap: (a) genuinely free or near-free, (b) fast enough that 2 sequential LLM calls (SHERLOCK then ATHENA) per triggered fault doesn't make the demo feel laggy.

**Recommended primary: Google Gemini 2.0/2.5 Flash, via OpenRouter's free tier.**
Zero code changes beyond the `model=` string — both agents already use OpenRouter's OpenAI-compatible client (`base_url="https://openrouter.ai/api/v1"`), and OpenRouter has offered free-tier Gemini Flash variants (check the current exact model ID at `https://openrouter.ai/models?max_price=0` right before you switch — these IDs and which ones are free shift over time, don't hardcode from memory). Gemini Flash is built for low-latency structured output and has historically been one of the more reliable free options for strict JSON schemas, which matters a lot given both agents demand exact schema compliance.

**Recommended fallback if the free tier rate-limits mid-demo: Groq, hosting Llama 3.3 70B (or whatever their current fastest Llama/open model is).**
Groq's own API (not OpenRouter) is inference-hardware-optimized for raw speed — routinely the fastest tokens/sec of any widely-available option, with a generous free tier well-suited to hackathon use. Requires a small code change: swap `base_url` to Groq's endpoint (`https://api.groq.com/openai/v1`) and the API key env var, same OpenAI-compatible client shape otherwise. Worth having this as a literal backup code path (an env var toggle between OpenRouter/Gemini and Groq/Llama) so a rate-limit mid-demo is a 5-second switch, not a panic.

**Action item, not yet done:** actually implement the backup toggle (env-var-driven provider switch in `sherlock/agent.py` and `athena/agent.py`) and test both paths once, before relying on it live. A fallback you haven't tested is not a fallback.

---

## 6. WOW Factors — Things That Make Judges Stop

1. **Two GUARDIAN outcomes, live, same pipeline** — the easy auto-executed path and the human-approval path from the *same* 3 real faults, controlled by one severity slider.
2. **The FDIR/Safe-Mode tier** — already implemented in `api.py`, not just planned. "Sudden temperature spike" is a known, standard question in spacecraft ops, and `tcs_thermal_runaway` is that exact scenario.
3. **Real OPSSAT-AD data on SENTINEL** — "trained on real ESA satellite telemetry, F1 0.65 / ROC-AUC 0.79 on held-out test data. Not synthetic." (Verified — see `audit_findings.md`, do not cite the old 0.89 figure, it never existed in any results file.)
4. **Graph-constrained SHERLOCK** — Claude can only pick root causes from the physical causal graph (18 real edges, confirmed in code, confirmed identical across all 3 team branches). Show the graph visually — the frontend already does this with an animated SVG backtrace.
5. **Two independent SENTINEL detection strategies, both measured, honestly reported** — this doc doesn't just claim one engine works, it shows the actual false-positive/false-negative numbers for both approaches tried. That level of rigor is itself a differentiator with technical judges.
6. **ATHENA's Two-Schema anti-hallucination pattern** — same discipline as SHERLOCK's graph constraint, applied to a different failure mode (score hallucination instead of root-cause hallucination). Worth explaining explicitly if asked "how do you stop the LLM from making things up."
7. **`run_monte_carlo`: 100 physics simulations in ~2 seconds** — real stochastic outcomes, not made-up probability bars.

---

## 7. Environment Setup

```bash
pip install -r backend/requirements.txt
export OPENROUTER_API_KEY="your_key_here"
uvicorn backend.api:app --reload --port 8000   # backend
npm run dev                                     # frontend, separate terminal
```

**Model files are gitignored and git-lfs is not configured in this repo.** Whoever runs the live demo needs `backend/models/*.joblib`/`*.pkl` copied onto that machine directly (zip + AirDrop/USB/Slack, not git). See `backend.md` for full details.

---

## 8. File Map

```
aero_astra/
├── backend/
│   ├── api.py                    ✅ EXISTS — real WebSocket bridge, see §3 for open gaps
│   ├── requirements.txt          ✅ EXISTS
│   ├── vitals.py                 ← BUILD §4.4
│   ├── chronicle.py              ← BUILD §4.4
│   ├── guardian.py               ← EXTRACT from api.py, §4.5
│   ├── quartermaster.py          ← BUILD §4.6
│   ├── scribe.py                 ← BUILD §4.7
│   ├── athena/                   ✅ EXISTS — not yet called by api.py, §3
│   ├── simulator/                ✅ EXISTS
│   ├── sentinel/
│   │   ├── engine_b.py           ✅ EXISTS — ours, reliable physics-threshold detector
│   │   ├── engines.py            🟡 EXISTS — Meet's, Engine B needs debounce fix (§4.3)
│   │   ├── eps_tcs.py, adcs.py   ⬜ trained offline, not wired in yet (§4.9)
│   │   └── train.py              ✅ FIXED — portable path, retrained model
│   ├── sherlock/
│   │   └── simulator_provider.py 🟡 duplicated with api.py's inline class, §4.8
│   ├── oracle/                   ✅ EXISTS — wired into api.py
│   └── models/                   ✅ EXISTS locally — must be copied to demo laptop manually
└── src/App.jsx                   ← still 100% mocked, §4.1 is the real blocker
```

---

*See [`audit_findings.md`](audit_findings.md) for the full verification detail behind the original SENTINEL/model claims, and [`backend.md`](backend.md) for the complete backend handoff brief written for whoever is picking this up without today's context.*
