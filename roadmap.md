# AERO-ASTRA — Roadmap (40-Hour Window, Frontend-Led)

> **Ownership split, effective now:** Mohit → 100% frontend (`src/`). Backend (`backend/`) is handed off completely — whoever picks it up should read [`backend.md`](backend.md) instead of this file. This file is the frontend-facing plan and the shared contract both sides build against.
>
> **Last full verification pass: 2026-09-04.** Everything marked ✅ below was actually run — tests executed, empirical checks against the real simulator, not just read on the page. Everything marked 🟡 is real code that exists but has a known, measured issue. Everything marked ⬜ genuinely doesn't exist yet. Everything marked 🔴 is a confirmed bug that will visibly break the live demo if not fixed first.
>
> **Branch policy, effective now: only push to `mohit-rawat`.** `harsh-lal` and `main` were reset back to `92388a5` (one commit before the GUARDIAN/VITALS merge) at Mohit's explicit request — do not force-push over them again without asking. Model files were checked as part of that reset: `harsh-lal`/`main`'s tracked `sentinel_production.pkl` is still the original 132-byte broken git-lfs pointer stub from the very first audit; ours is the real 1.38MB retrained model. Nothing was lost in the reset.
>
> **✅ Frontend and backend ARE connected now, as of this pass — confirmed live, not just wired.** Someone (not this pass) had already built the actual `WebSocket`/`fetch` integration in `src/App.jsx` — this pass found it, ran a real backend server, opened the real frontend in a browser, and clicked through the real UI. Full detail in the new §3.5 below: 3 real, previously-unknown bugs were found and fixed this way, including one that silently crashed the entire pipeline every single time — no amount of code review would have caught it as fast as actually running it did.

---

## 0. Status checklist — tick these off as they land

**Backend agents**
- [x] SENTINEL — trained model + 2 fallback detection paths (Engine B physics-threshold [ours], VITALS health-score fallback [Meet's]) — **see §2, none of them currently catch the flagship demo fault within the pipeline's actual run length, this is the top priority fix**
- [x] SHERLOCK — LLM + 18-edge causal graph, untouched and verified identical across all 3 team branches
- [x] Physics Simulator — `simulate_scenario()` + `run_monte_carlo()`, real orbital dynamics
- [x] ORACLE — fully wired, 100-run Monte Carlo, fallback ranking mode
- [x] ATHENA — merged from harsh-lal's branch, 25/25 tests passing, Two-Schema anti-hallucination pattern, **now actually called from `api.py`**
- [x] `backend/api.py` — real FastAPI + WebSocket bridge, now has a working `POST /trigger` endpoint and CORS — see §3
- [x] VITALS — `backend/vitals/agent.py`, real function, wired into `api.py`, streams `vitals_update` — **but see §2, one part of it fakes a detection rather than deriving it from telemetry**
- [x] GUARDIAN — `backend/guardian/` is now its own module, 36/36 tests passing, 5-rule decision tree (more thorough than this doc's original 3-tier sketch — includes an irreversibility check and a safety-score floor)
- [ ] CHRONICLE — not built
- [ ] QUARTERMASTER — not built
- [ ] SCRIBE — not built

**Frontend**
- [x] Full dashboard UI, silver/black palette, PillNav, agent console, 9 agent drill-down pages
- [x] SHERLOCK causal-graph animation (SVG + GSAP)
- [x] SENTINEL side-by-side dataset comparison view
- [x] Clicking "Dashboard" in the nav now resets back to the live 3D view instead of staying on whatever agent page was open
- [x] Right sidebar no longer duplicates VITALS/SHERLOCK/ATHENA as detail panels (they were redundant with the AgentNav console) — replaced with MISSION TIMELINE (real-time 6-stage pipeline progress, tied to actual `scenarioPhase`) and GROUND CONTACT (orbit/pass info). SYSTEM RESOURCES kept.
- [x] Connected to the real `backend/api.py` WebSocket — **confirmed live in a real browser, not just wired: fault injected → SENTINEL fired → SHERLOCK diagnosed → GUARDIAN gated → human approved (or auto-executed) → runbook ran → system returned to nominal. Both GUARDIAN tiers exercised. See §3.5.**

**🔴 Confirmed bugs — read before your next demo run-through**
- [x] ~~`tcs_thermal_runaway` not detected within `api.py`'s 600s run~~ **Fixed this pass** — VITALS' panel_temp threshold recalibrated from 85°C to 49°C, verified firing across 7 seeds with zero false positives. See §3.5. **Still slow though — 244-481 real seconds to fire at severity 0.7, see the new note in §1's fault table. Use `propulsion_thruster_fault` (fires in 24-75s) if you need something to detect live in front of judges; don't rely on watching thermal_runaway happen in real time.**
- [x] ~~VITALS' `eps_cascade_power_failure` fallback reads the ground-truth fault label instead of deriving from telemetry~~ **Fixed this pass** — `calculate_vitals()` fully rewritten, the label-check shortcut is gone. Honest consequence: `eps_cascade_power_failure` (along with `eps_battery_degradation` and `adcs_reaction_wheel_degradation`) is now correctly **undetected** rather than fake-detected — these 3 faults are still too weak to cross any real threshold in the demo window. This was already known/documented as out-of-scope for the 3 MVP faults; nothing regressed, a fake positive was just replaced with an honest negative.
- [ ] Engine B's new debounce (`PhysicsSpikeFilter`) reduces the *raw* false-positive count but not the underlying problem — see §2, the numbers are close for nominal vs. post-fault. Not MVP-blocking (VITALS covers all 3 MVP faults independently), still open.
- [x] **New this pass, found and fixed via live testing, not code review:** `AnomalyEvent` was missing two Pydantic-required fields, crashing the *entire* streaming pipeline on every single anomaly, every fault, regardless of API key. Also: `flagged_subsystem` was hardcoded to `"EPS"` regardless of which fault fired. Also: a false-positive alert on the auto-started nominal stream crashed ORACLE with `KeyError: 'unknown'`. Also: the frontend's `AUTOMATED_GUARDED`/`AUTONOMOUS_SAFED` auto-execute path crashed the whole React app (blank page) due to a stale closure. All 4 fixed and re-verified live — full detail in §3.5.

---

## 0.5. How to actually work from here — answers to the questions that keep coming up

**"Is frontend↔backend connection a big task or just not started?"** Genuinely checked, not guessed: **it's not started, and it's not huge, but it's also not trivial.** Concretely, three things stand between here and a working demo:
1. Add a `WebSocket('ws://localhost:8000/ws')` connection and a `fetch('/trigger', {method:'POST', ...})` call to `src/App.jsx` — mechanical, an hour or two.
2. **The real reason nobody's done it yet:** the WebSocket contract documented in `backend.md` §5 was written speculatively before `api.py` existed, then went stale as `api.py` evolved through several real merges. Nobody had an accurate target to build against — the doc said `"type": "oracle"`, the code sends `"type": "oracle_simulation"`; the doc invented fields like `sentinel_alert.score` that don't exist on the wire. **This is now fixed** — `backend.md` §5 is rewritten this pass, transcribed directly from the actual `manager.broadcast()` calls in `api.py`, not reconstructed from schemas.
3. Once wired, the real messages are noticeably thinner than the mocked `FAULT_SCENARIOS` data the frontend currently shows (e.g. `telemetry` only carries ADCS+EPS, not all 6 subsystems; `sherlock_diagnosis` has no reasoning text on the wire even though SHERLOCK generates it). Either the frontend's agent-detail pages gracefully show "not available yet" for missing fields, or `api.py` gets extended to broadcast more of what each agent already computes internally — cheap per-field, but it's real work, not a formality.

**Bottom line: this is a single focused work session (realistically 3-5 hours end to end, including the debugging that always eats more time than the plumbing itself), not a multi-day rebuild.** It's the highest-leverage thing left to build — everything upstream of it is real, tested backend code that currently only a Python REPL can see.

**"What about CHRONICLE, QUARTERMASTER, SCRIBE — how much is left?"** Checked exhaustively, including the branch tips that got reset in §0's branch-policy note (nothing was hiding there): **none of the three exist anywhere, on any branch, in any form.** Not scaffolded, not half-built. All three are genuinely "not started," same as this doc has said since before the last few merges — that status didn't change, it just hadn't been re-confirmed after all the branch activity. Rough sizing if you're deciding where to spend remaining hours:
- **CHRONICLE** — smallest, cheapest. It's a threshold-watcher over data `api.py` already streams (`vitals_update`, `telemetry`). No LLM. Maybe 1-2 hours including frontend wiring.
- **QUARTERMASTER** — small, mostly static data + one conditional. 1-2 hours. Lowest judge-value of the three — don't prioritize it over finishing the frontend connection.
- **SCRIBE** — a Jinja2 template over the full pipeline's already-existing output, plus optionally one small LLM call for a summary paragraph. 2-3 hours, more if the "download a runbook" UX gets polished.

**"One LLM in ATHENA — what's the plan for the whole system?"** See §5 below — this is the section that was actually researched this pass (previous version of this doc recommended Gemini Flash from memory; that turned out to be the wrong call once actually checked). SHERLOCK and ATHENA are the only two agents that call an LLM at all — everything else in this pipeline (SENTINEL, ORACLE, GUARDIAN, the simulator) is deterministic code with zero LLM involvement, which is worth remembering when explaining the architecture: it's not "8 LLM agents," it's 2 LLM calls in an otherwise fully deterministic pipeline.

**If the goal is "get an MVP fully working," in order:**
1. Wire the frontend↔backend connection (above) — without this, nothing else matters to a judge.
2. Swap the LLM provider to Groq (§5) — cheap insurance against a live rate-limit, and free.
3. Fix the flagship-fault timing bug (§2/§4.1) — the demo's headline scenario currently doesn't fire.
4. CHRONICLE, then QUARTERMASTER, then SCRIBE, in that order, if hours remain.

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

Currently GUARDIAN's decision function lives in `backend/guardian/engine.py` as its own module — it is not yet imported by `api.py`, which still has its own simpler inline version. See §4.4.

### "Real" beats "impressive" — say this to yourself when a number looks boring

If a telemetry value on screen reads `1.24, 1.24, 1.24, 1.24` for ten ticks in a row because that's genuinely what the physics simulator is outputting right now — **that is a win, not a bug.** Do not "fix" real-but-boring data by adding jitter. A real number that happens to be flat is still real.

---

## 2. What We Have Right Now

| Component | Location | Status | Notes |
|---|---|---|---|
| **3D Dashboard UI** | `src/App.jsx` + `src/components/` | ✅ Working, confirmed live | Silver/black palette, PillNav, 9-agent drill-down console, SHERLOCK causal graph. **Real WebSocket + fetch connection to `backend/api.py`, confirmed working live in a browser this pass** (see §3.5) — the mocked `FAULT_SCENARIOS` timers now only serve as a fallback when the backend is unreachable. `SentinelPage` and `VitalsPage` show a live-data badge with real numbers straight off the wire when connected; other agent pages still show mocked detail pending backend field parity (see backend.md §5's closing note). |
| **SENTINEL — flatline/XGBoost (Engine A)** | `backend/models/sentinel_production.pkl` + `backend/sentinel/engines.py` | 🟡 Working, structurally limited | Real model, real predict_proba calls. Confirmed via direct testing: does not fire on the ramping simulator faults on its own — inherent to what flatline features can see, not a bug. |
| **SENTINEL — Engine B (physics threshold)** | `backend/sentinel/engine_b.py` | ✅ Built, reliable, **not currently used by `api.py`** | Ours. Zero training needed. Fires correctly on all 3 MVP faults *at a 3600s test duration*. `api.py` doesn't import or call this module at all — it uses the spike/reversal engine below instead. Worth wiring in alongside it, see §4. |
| **SENTINEL — Engine B (spike/reversal + new debounce)** | `backend/sentinel/engines.py::PhysicsSpikeFilter` | 🟡 Improved, still not solved | Meet's. A rolling event-count debounce (`window_size=10, min_spikes_required=2`) was added since the last pass, replacing the old no-debounce version. **Re-measured directly, 5 seeds, at `api.py`'s actual runtime settings (`dt=1.0, duration=600s, fault_onset=5s`):** nominal (no fault) produces an average of **3.2 false incidents per 600-step run**; every one of the 6 faults produces **3.0-3.6 incidents post-onset** — statistically indistinguishable from the nominal false-alarm rate. The first detection often lands on the *exact same step* across different faults run with the same seed, which is the signature of noise-driven timing, not fault-driven detection. The debounce genuinely reduced the raw alarm count (good), but didn't improve fault-vs-nominal separation (the actual thing that matters). Not a wasted change — a real step forward on false-positive rate — just not yet "resolved" the way the code comment claims. |
| **SENTINEL — VITALS-based fallback** | `backend/vitals/agent.py::calculate_vitals`, called from `api.py` | 🟡 Works for 2/6 faults, one entry is fake | `calculate_vitals()` computes real per-subsystem health scores from real telemetry (battery SOC, bus voltage, panel/battery temp, attitude error, wheel speed) — genuinely good, physics-grounded work. **Measured directly against `api.py`'s actual 600s window:** fires correctly and fast for `ttc_signal_dropout` (step 160) and `propulsion_thruster_fault` (step 75). Does **not** fire for `tcs_thermal_runaway` (health stays at 1.000 the entire run — panel_temp only reaches ~57°C in 600s, the function's threshold is 85°C) or `eps_battery_degradation`/`adcs_reaction_wheel_degradation` (both too weak, consistent with earlier findings). **`eps_cascade_power_failure` "fires" at step 6, but only because the function contains `if state.active_fault == "eps_cascade_power_failure": eps_score -= state.fault_severity` — that's reading the ground-truth fault label directly, not deriving anything from telemetry.** Call this out explicitly if it comes up in Q&A; it's the one part of this whole pipeline that doesn't hold up to "we don't fake detection." |
| **SENTINEL — EPS/ADCS forecasters** | `backend/sentinel/eps_tcs.py`, `adcs.py` | ⬜ Trained offline, not wired into the live pipeline | Meet's work. Trains an XGBoost MultiOutputRegressor forecaster on real Mars Express spacecraft telemetry (`data/raw/mars_express/`) — genuinely the Telemanom-style "forecast, flag large error" approach `audit_findings.md` §4 discussed as a stretch goal. Not called by `api.py` yet. |
| **SimulatorTelemetryProvider** | Two copies — see below | 🟡 Duplicated | `backend/sherlock/simulator_provider.py` (ours, standalone, smoke-tested) and an inline class of the same name inside `backend/api.py` (the one actually running, slightly different parameter naming). Consolidate onto one — low priority, doesn't block anything. |
| **SHERLOCK** (LLM + graph) | `backend/sherlock/agent.py` | ✅ Built | Claude via OpenRouter, graph-constrained, 3-retry validation loop. 18-edge causal graph. Confirmed byte-identical across all 3 team branches at every check so far — untouched by anyone. |
| **Physics Simulator** | `backend/simulator/engine.py` | ✅ Built | `simulate_scenario()` + `run_monte_carlo()` exist and work. Also byte-identical across all 3 branches. |
| **RECOVERY_CATALOG** | `backend/simulator/recovery.py` | ✅ Built | 6 named actions with subsystem modifiers. |
| **ORACLE** | `backend/oracle/agent.py` | ✅ Fully wired | `run_oracle()`, `_evaluate_action()`, fallback ranking mode all call `run_monte_carlo` for real. Now called from `api.py`'s background task, which then feeds ATHENA. |
| **ATHENA** | `backend/athena/agent.py` | ✅ Built, merged from harsh-lal, now called from `api.py` | Two-Schema Pattern — LLM never outputs `safety_score`/`blended_rank`/`is_irreversible`, those are injected/computed after validation. 25/25 tests pass. `api.py` calls `athena_agent.plan(diagnosis, oracle_response)` after ORACLE resolves and broadcasts an `athena_plan` message. |
| **GUARDIAN** | `backend/guardian/` (`engine.py`, `schemas.py`, `demo.py`, tests) | ✅ Built, its own module, 36/36 tests passing | 5-rule decision tree: `time_to_critical < 5min → AUTONOMOUS_SAFED`; `urgency HIGH/CRITICAL → MANUAL_INTERLOCK`; `recommended option is_irreversible → MANUAL_INTERLOCK`; `safety_score < 0.2 floor → MANUAL_INTERLOCK`; otherwise `AUTOMATED_GUARDED`. More thorough than this doc's original 3-tier sketch. **Not yet called from `api.py`** — the bridge still has its own simpler inline 3-branch version instead of importing this module. Worth swapping in, see §4. |
| **VITALS** | `backend/vitals/agent.py` | 🟡 Built, wired, one fake entry | See the SENTINEL row above — same module. |
| **`backend/api.py`** (the bridge) | `backend/api.py` | 🟡 Real, running, closer to feature-complete | Now has: `POST /trigger {fault_name, severity}` (cancels the current stream, starts a new one — the frontend's scenario picker finally has something real to call), CORS middleware, ATHENA wired in, VITALS wired in, lazy `SherlockAgent` init with a graceful no-API-key fallback, `fault_onset=5.0` (near-immediate onset instead of 20% into the run — good for demo pacing). Two bugs found and fixed in the previous merge (timestamp, reverted debounce attempt). One new critical finding this pass — see the 🔴 checklist above: the flagship fault isn't detected within this configuration's actual time budget. |
| **requirements.txt** | `backend/requirements.txt` | ✅ Built | Added `python-dotenv` this pass (`api.py` now uses it). Install this on whichever laptop runs the demo. |

---

## 3. Merge history — what changed and when

**2026-09-03, from harsh-lal:** ATHENA (see above). **2026-09-03, from Meet's `main`:** the first version of `api.py`, `engines.py`'s two-engine hybrid, the EPS/ADCS forecasters. Two bugs found and fixed then: a timestamp bug (`datetime.fromtimestamp()` on simulation-elapsed seconds instead of wall-clock time) and a reverted debounce attempt (see the git history in `backend/sentinel/engines.py` if curious about what didn't work).

**2026-09-04, from harsh-lal (now containing Meet's latest `main` merged in too):** `POST /trigger`, ATHENA + VITALS wired into `api.py`, the full GUARDIAN module, and the `PhysicsSpikeFilter` debounce attempt. This is the pass that found the flagship-fault timing bug and the VITALS fake-detection entry — both documented in §2 and the checklist at the top of this file. All three team branches (`mohit-rawat`, `harsh-lal`, `main`) are synced to the same commit as of this pass — `main`'s separate v2 TypeScript frontend (46 files, unrelated architecture) was confirmed abandoned and removed in that sync, by explicit confirmation, not by default.

---

## 4. What's next — in priority order

1. **Fix the flagship-fault timing bug (🔴, top of file).** `tcs_thermal_runaway` is undetected within `api.py`'s real 600s run. Three options, pick one rather than guessing:
   - Cheapest: lower `calculate_vitals()`'s `tcs_score` panel_temp threshold from 85°C to something realistic for a 10-minute demo window — e.g. our `engine_b.py`'s own calibrated 55°C warn line (already measured against this exact simulator, see `audit_findings.md`). Re-measure afterward, same way every other number in this doc was measured — don't just lower the number and assume it works.
   - More correct: increase `tcs_thermal_runaway`'s ramp rate in `faults.py` so panel_temp reaches a real threshold within ~5-8 minutes at severity 0.7-1.0 instead of the ~40 minutes it currently needs. This also fixes it for anyone who later extends `duration` past 600s.
   - Fallback: wire `engine_b.py` into `api.py` as an additional real-time check *alongside* VITALS and the spike filter (currently it isn't imported by `api.py` at all) — belt-and-suspenders, catches it if either of the above isn't done in time.
2. **Fix or remove the fake VITALS entry for `eps_cascade_power_failure`.** Either derive its detection from a real threshold (bus_voltage crossing the roadmap's calibrated line, same table `engine_b.py` already uses) or stop claiming this fault is "detected" in demo narration — currently it's a label lookup dressed up as detection.
3. **Wire the frontend to the real `api.py`.** Still the #1 *visibility* blocker — everything in §2 above the frontend row is real, tested backend code nobody outside a terminal can see yet. `POST /trigger` now exists; replace `src/App.jsx`'s `FAULT_SCENARIOS` mock with a real `WebSocket('ws://localhost:8000/ws')` and a `fetch('/trigger', {method:'POST', body: {fault_name, severity}})` call. Map incoming `{type: "telemetry"|"sentinel_alert"|"sherlock_diagnosis"|"guardian_action"|"oracle_simulation"|"athena_plan"|"vitals_update"}` onto the existing `scenarioPhase` state machine — the phase names already line up closely.
4. **Swap `api.py`'s inline GUARDIAN 3-branch logic for the real `backend/guardian/` module** (36/36 tests, 5 rules, more thorough than the inline version). Small, mechanical change.
5. **Properly fix Engine B's spike-detector debounce.** The rolling event-count window helped (raw alarm count is down) but hasn't solved fault-vs-nominal separation yet (§2). Try widening the window further, or requiring spikes across *multiple different channels* rather than counting repeats on one, and measure against all 6 faults + nominal before calling it done.
6. **CHRONICLE** — no LLM, cheap: watch the same telemetry/vitals stream `api.py` already broadcasts, print a formatted line whenever a threshold crosses or another agent produces output.
7. **QUARTERMASTER** — mostly static: 2 hardcoded ground-station passes, offload rule on HIGH/CRITICAL severity. Lowest judge-value agent, don't over-invest.
8. **SCRIBE** — Jinja2 template over the full pipeline output → markdown runbook. One small LLM call for a 2-sentence executive summary; everything else plain templating (reliability > cleverness in front of judges).
9. **Consolidate the duplicate `SimulatorTelemetryProvider`** (§2) onto one implementation. Low priority, doesn't block anything.
10. **Wire Meet's EPS/ADCS forecasters (`eps_tcs.py`/`adcs.py`) as a real Engine C**, once items 1-2 are solid — real, trained, working forecast-residual capability that's currently sitting unused.
11. **Re-tune the other weak faults** (`eps_battery_degradation`, `adcs_reaction_wheel_degradation`) in `faults.py` so more than 3 are demo-viable.

---

## 5. Which LLM to use — actually researched, not guessed (2026-09-05)

SHERLOCK and ATHENA both currently call `anthropic/claude-sonnet-4-5` via OpenRouter. Paid. An earlier version of this doc recommended Gemini Flash from memory without checking — that recommendation is now corrected below after actually searching current pricing/limits pages, because the memory-based guess turned out to be the weaker option.

**What actually matters here, given how SHERLOCK/ATHENA are built:** both already have a 3-retry JSON-schema-validation loop with re-prompting on failure (see `backend/sherlock/agent.py` / `backend/athena/agent.py`). That's what makes swapping models low-risk — a model that occasionally messes up strict JSON still works, it just costs a retry. What actually matters for the swap: (a) genuinely free with a *stable* quota, (b) fast, since SHERLOCK then ATHENA is two sequential LLM calls per triggered fault and both sit in the critical path of a live demo.

**Recommended primary: Groq, hosting Llama 3.3 70B (or check `groq.com/pricing` for their current fastest large model — this shifts).**
- **Free tier: 30 requests/min, 6,000 tokens/min, 14,400 requests/day, org-wide.** That's ~70x OpenRouter's free-model cap (below) and far more headroom than a hackathon demo needs even with heavy rehearsal.
- **Genuinely the fastest inference available anywhere right now** — 300-1,000 tokens/sec on their custom LPU hardware, vs. typical GPU-hosted inference. This directly shortens the SHERLOCK→ATHENA latency the demo audience actually waits through.
- **Fully OpenAI-SDK-compatible** — same `openai.OpenAI(...)` client SHERLOCK/ATHENA already use. The swap is exactly two lines per agent: `base_url="https://api.groq.com/openai/v1"` and the API key env var (`GROQ_API_KEY` instead of `OPENROUTER_API_KEY`), plus the model name string.
- No credit card required for the free tier.

**Recommended fallback: OpenRouter's `openai/gpt-oss-120b:free`.**
Explicitly built with native tool-calling and structured-output support — a real, deliberate fit for what SHERLOCK/ATHENA need, not a generic chat model pressed into service. Free tier is much tighter than Groq's (~20 requests/min, ~200/day, *shared across every free model on OpenRouter*, not per-model) — treat this as the break-glass option if Groq's org-wide limit gets hit mid-rehearsal, not the primary. Zero code change needed to reach it, since SHERLOCK/ATHENA already point at OpenRouter — just change the `model=` string.

**Explicitly not recommended as primary: Gemini Flash (the previous guess in this doc).** Current search results turned up a live "Gemini has slashed free API limits" story and inconsistent numbers across sources (some say 250 requests/day, others 1,500) — Google appears to be actively tightening this tier. Fine as a third option, not what you want to build a live demo's critical path on.

**Action item, not yet done:** implement an env-var-driven provider switch (`LLM_PROVIDER=groq|openrouter`) in `sherlock/agent.py` and `athena/agent.py` so a rate-limit mid-demo is a restart with one env var changed, not a panic. Test both paths once before relying on either live — an untested fallback isn't a fallback.

Sources checked this pass: [Groq Free Tier 2026](https://www.grizzlypeaksoftware.com/articles/p/groq-api-free-tier-limits-in-2026-what-you-actually-get-uwysd6mb), [Groq API Pricing 2026](https://tokenmix.ai/blog/groq-api-pricing), [OpenRouter Free Models](https://openrouter.ai/collections/free-models), [Gemini free tier cuts](https://www.howtogeek.com/gemini-slashed-free-api-limits-what-to-use-instead/), [Free LLM APIs 2026 comparison](https://openrouter.ai/blog/tutorials/free-llm-apis-compared/).

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
│   ├── vitals/                   ✅ EXISTS — agent.py, wired into api.py (one fake entry, §2)
│   ├── chronicle.py              ← BUILD §4.4
│   ├── guardian/                 ✅ EXISTS — 36/36 tests, not yet imported by api.py (§4.4)
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
