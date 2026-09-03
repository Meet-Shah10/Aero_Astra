# AERO-ASTRA — THE FINAL PLAN
### One document. What's done, what's next, in order. Read this one, not the older two.

I went back into your actual backend code (not just the docs) to write this — including the physics simulator's real functions. Good news up front: **your simulator is more finished than it looks.** Two of the remaining agents (ORACLE and ATHENA) mostly need to be *thin wrappers* around code that already exists, not built from zero. This changes your time budget a lot, in your favor.

---

## 0. Checkpoint — where you are right now

✅ Frontend (orbital-tomb style, 3D GLB model) — **done**
✅ SENTINEL (anomaly detector, trained on real data) — done
✅ SHERLOCK (root cause diagnosis, graph + LLM) — done
✅ Physics simulator (`backend/simulator/`) — done, and richer than expected (see Section 2)
❌ No bridge yet connecting Python to the frontend
❌ CHRONICLE, VITALS, ATHENA, GUARDIAN, QUARTERMASTER, SCRIBE — not built

**The one sentence version of what's next:** build the bridge first so you have *something real* on screen today, then fill the 6 missing agents in order of how cheap they are to build, saving the LLM-heavy one (ATHENA) for when SHERLOCK's pattern is fresh in your head since you'll copy it almost directly.

---

## 1. The Dataset Question — Final Answer, No More Debate

You asked which dataset to work on. Here is the decisive answer:

**You do not need a new dataset. You already have the two you need, and they have two completely different jobs:**

| Dataset | Job | Status |
|---|---|---|
| **OPSSAT-AD** (real ESA data) | Trains and scores SENTINEL only | ✅ Done. Do not touch it again. |
| **Your physics simulator** (`backend/simulator/`) | Feeds *everything else* — VITALS, CHRONICLE, ORACLE, ATHENA, GUARDIAN, QUARTERMASTER | ✅ Already built, already outputs clean multi-subsystem data |

**Why this is the right split, explained simply:** OPSSAT-AD's data is anonymized and only covers one type of sensor (attitude control) — it physically *cannot* tell you a battery voltage or a temperature, because it doesn't have those columns. Your simulator does. That's not a workaround — that's the correct architecture, and it's already what your own `datasets-research.md` file concluded months ago. You made the right call already; you just haven't finished building on top of it.

**Do not spend hackathon time on:** switching to ESA-ADB, adding Telemanom/SMAP-MSL data, or any other dataset. Save those for one throwaway line in your "future work" slide ("we scoped these but prioritized shipping a working pipeline"). Chasing a new dataset now would be the single easiest way to waste your remaining hours.

---

## 2. What I Found In Your Simulator Code (this changes your plan)

I read `backend/simulator/engine.py`, `schemas.py`, and `recovery.py` directly. Three things matter a lot:

1. **`run_monte_carlo(current_state, proposed_action, n_runs, steps)`** already exists and already returns a `MonteCarloResult` with `nominal_recovery_rate`, `degraded_operation_rate`, `mission_loss_rate`, `mean_final_battery_soc`, and more. **This is ORACLE.** You don't need to build a Monte Carlo engine — you need a small function that calls `run_monte_carlo` three times (once per candidate action) and reshapes the three `MonteCarloResult` objects into the `OracleSimulation` JSON shape your frontend already expects.

2. **`RECOVERY_CATALOG`** in `recovery.py` already lists named, described recovery actions (`switch_redundant_power_bus`, `shed_nonessential_load`, `reorient_maximum_solar_exposure`, `enter_safe_low_power_mode`, `activate_backup_heater`, and more), each tagged with which subsystems it touches. The code comment in that file literally says *"ATHENA (once built) will build procedural step sequences on top of these."* **This is your ATHENA build instruction, written by your own teammate months ago.** ATHENA's job is: take SHERLOCK's diagnosis + this catalog, ask Claude to pick 3–4 actions, put them in a sensible order with reasoning, and score each step's safety — reusing the exact same "call LLM → validate JSON → retry on failure" pattern already written and tested in `sherlock/agent.py`.

3. **`SatelliteState`** (the simulator's live snapshot — `battery_soc`, `panel_temp`, `cpu_load`, `bit_error_rate`, `watchdog_trips`, etc.) is exactly the human-readable, multi-subsystem data VITALS and CHRONICLE need. VITALS doesn't need its own data source — it needs a small function that turns the latest `SatelliteState` into a 0–100 health number. CHRONICLE doesn't need an LLM — it needs to watch the same state stream and print a line whenever a value crosses a threshold (a "WARN: Anomaly detected at EPS Bus A"-style line, which is literally what your screenshot already shows).

**Bottom line: 3 of your 6 missing agents (ORACLE-shaped, VITALS, CHRONICLE) are now "write a function that reshapes data I already have," not "build an AI system."** Only ATHENA needs an LLM call, and GUARDIAN/QUARTERMASTER/SCRIBE are mostly rule-based logic and templating.

---

## 3. The Plan, In Order

Do these in this order. Don't skip ahead to a later one before an earlier one works end-to-end — a half-working pipeline demos worse than a short, fully-working one.

### Phase 1 — The Bridge (do this first, before anything else)
Build a small FastAPI server with a WebSocket endpoint. On the "Trigger Fault Scenario" click:
1. Call `simulate_scenario(fault=..., severity=..., duration=..., dt=...)` from your simulator to generate a labeled fault timeline.
2. Feed each row through SENTINEL (already trained) to get real anomaly scores instead of fixture ones.
3. When SENTINEL fires, call SHERLOCK (already built) for the real diagnosis.
4. Push both as JSON over the WebSocket, shaped to match `TelemetryPoint`, `FaultNode`, and `SherlockDiagnosis` in `types/incident.ts`.
5. On the frontend, replace the fake timer in `useIncidentStream.ts` with a WebSocket listener that updates state when messages arrive.

**Why first:** this alone turns 3 of your 9 agent panels from fake to real, using code that already exists. That's your safety net if later phases run out of time.

### Phase 2 — VITALS + CHRONICLE (cheap, no LLM, do these together)
- **VITALS:** a weighted score from the live `SatelliteState` (e.g. battery SoC weighted highest, then temperature, then CPU load). Push a number 0–100 plus a `RUL estimate` (your screenshot shows "12 orbits" — a simple linear extrapolation of degradation rate is enough, it doesn't need to be scientifically rigorous for a demo).
- **CHRONICLE:** watch the same state stream, print a formatted line to a log array whenever a threshold is crossed or SENTINEL/SHERLOCK produce an output. No AI needed — string templates are fine and will be more reliable in a live demo than an LLM call.

### Phase 3 — ORACLE (wrapper, not new build)
Write the function described in Section 2, point 1. Call `run_monte_carlo` for each candidate action (start with 2–3 actions from `RECOVERY_CATALOG`, plus a "do nothing" baseline — your fixture already shows this exact 3-option shape: Plan A / Plan B / Baseline). Reshape into `OracleSimulation`.

### Phase 4 — ATHENA (your one LLM-heavy build)
Copy SHERLOCK's LLM-call-plus-validation pattern. Prompt: give Claude the SHERLOCK diagnosis + the `RECOVERY_CATALOG` entries relevant to the affected subsystems + ORACLE's ranked candidates, and ask for a `reasoningCoT` (chain-of-thought, meaning step-by-step written reasoning) array and an ordered `steps` list matching the `RecoveryStep` shape. Keep temperature low (SHERLOCK already uses 0.1 — reuse that).

### Phase 5 — GUARDIAN (rule-based, no LLM)
Define severity tiers directly from SHERLOCK's `urgency` field (already in its schema): LOW/MEDIUM → `AUTOMATED_GUARDED` (auto-executes, just logs it); HIGH/CRITICAL → `MANUAL_INTERLOCK` (waits for the toggle in your UI, exactly like the screenshot shows). For each `RecoveryStep`, write 3–5 simple numeric checks (battery SoC stays above a floor, temperature stays under a ceiling, reversibility is true) — this is what becomes your `GuardianConstraintCheck` list. If you have time, wire these same checks through Z3 for a real mathematical proof instead of a plain if-statement; if you don't have time, plain Python comparisons are an honest, defensible fallback — just don't claim Z3 verified something it didn't.

### Phase 6 — QUARTERMASTER (mostly static logic)
You don't need real orbital mechanics for the demo. A short hardcoded (but labeled realistic) list of 2–3 ground station passes with times, plus a simple rule like "if EPS severity is high, offload 30–50% of load to the next satellite in the fixture fleet" is enough to match `QuartermasterSchedule`. This is the lowest-value agent for judges — don't over-invest here.

### Phase 7 — SCRIBE (templating, one Jinja2 template, barely any code)
This is not really an AI task. Collect the actual outputs from SENTINEL → CHRONICLE → SHERLOCK → ORACLE → ATHENA → GUARDIAN → QUARTERMASTER as they flow through your pipeline, and drop them into a markdown template shaped exactly like your `scribe.ts` fixture (Executive Summary, Agent Decision Trace table, Approved Recovery Procedure, Constellation Rebalancing). If you want one small LLM touch, use Claude only to write the 2–3 sentence Executive Summary paragraph from the structured data — everything else should be plain templating, since it needs to be reliable in front of judges.

### Phase 8 — Full run-through, then stop building
Run the whole pipeline start to finish, at least twice, before you touch polish or slides. Fix only what's broken. Do not add new features this late.

---

## 4. If You're Running Low On Time — What To Cut, In Order

Cut in this order (last item first, if you must):
1. QUARTERMASTER real logic → replace with a static, clearly-labeled "simulated" output
2. GUARDIAN's Z3 verification → fall back to plain rule checks, say so honestly
3. SCRIBE's LLM-written summary → use a template sentence instead
4. CHRONICLE's live threshold-watching → replace with a short static log that matches the scenario
5. Never cut: the Phase 1 bridge, SENTINEL, SHERLOCK. Those are your working, trained, real core — protect them above everything else.

---

## 5. Demo Script Checklist

- [ ] Open on the 3D dashboard, calm state, all green
- [ ] Click "Trigger Fault Scenario" — narrate what SENTINEL is doing while it happens (don't just wait in silence)
- [ ] Let SHERLOCK's diagnosis appear, point at the causal chain, mention it's constrained to a physically-valid candidate set (your differentiator vs. free-roaming agents)
- [ ] Show ORACLE's Monte Carlo comparison — this is your most visually strong panel
- [ ] Show ATHENA's reasoning steps out loud, not just on screen
- [ ] Click the GUARDIAN approval toggle yourself, on camera — human-in-the-loop is a selling point, don't skip it silently
- [ ] Open the SCRIBE runbook at the end and scroll it — this is your "proof of audit trail" moment
- [ ] Close with the honest data line: real F1/PR-AUC on real ESA data for SENTINEL, clearly-labeled synthetic data for everything else — judges reward this over inflated claims

---

*This file replaces the two earlier documents for "what to do next" purposes. The deep research (papers, citations, prior-art check) from the earlier files is still accurate and still worth keeping for your slides and Q&A prep — nothing in this plan contradicts it, this just turns it into an execution order.*