# AERO-ASTRA — Verified Audit Findings & What Got Fixed Tonight

Everything below was checked by actually running the code on this machine (Mohit's laptop), not by re-reading the previous audit doc. Where I disagree with that doc or found something it missed, I say so explicitly. Every number here came out of a real Python process — the scripts are gone (scratchpad), but the method is reproducible from the descriptions.

**Environment used:** Python 3.12 venv with `--system-site-packages`, `pip install pydantic xgboost tqdm openai`. `pydantic`, `xgboost` were **not installed** before this — meaning nobody could have run the simulator or retrained SENTINEL on this checkout until now.

---

## 0. FDIR / Safe Mode — the judge's question

Confirmed real and still the right answer: `time_to_critical_estimate_minutes` exists in `backend/sherlock/schemas.py:166` and is enforced in `agent.py`'s validation (lines 234, 359-360). `shed_nonessential_load` is a real, already-implemented action in `backend/simulator/recovery.py:48`. GUARDIAN itself (`backend/guardian.py`) **does not exist yet** — it's Phase 5, still unbuilt — so the three-tier APPROVE/FLAG/BLOCK logic from the previous audit is something to build, not something to fix. No code changes needed here tonight; the plan in the previous doc is sound. Build it when you reach Phase 5, using `SAFE_MODE_ACTION = "shed_nonessential_load"`.

---

## 1. SENTINEL blindness to simulator faults — CONFIRMED, with the real model this time

The previous audit inferred this from hand-copied feature formulas because it couldn't load the trained model (it's a broken file — see §2). I fixed that and got a real answer.

**What I did:** retrained `sentinel_production.pkl` from the actual local OPSSAT data (`backend/data/raw/opssat/`, which *is* present and real — 18MB of genuine ESA telemetry), then ran the real `XGBClassifier.predict_proba()` against all 6 simulator faults at the exact settings `roadmap.md` recommends for the demo (`severity=0.7, duration=3600, dt=10`):

| Fault | Real model max probability | Fires at threshold 0.53? |
|---|---:|:---:|
| eps_battery_degradation | 0.511 | **No** |
| tcs_thermal_runaway | 0.372 | **No** |
| adcs_reaction_wheel_degradation | 0.507 | **No** |
| ttc_signal_dropout | 0.372 | **No** |
| propulsion_thruster_fault | 0.418 | **No** |
| eps_cascade_power_failure | 0.511 | **No** |
| *(control) genuine stuck-sensor flatline* | 0.644 | **Yes, correctly** |

Zero for six. The model works exactly as designed — it just wasn't designed to see any of these faults. Root cause confirmed: `flatline_duration` (the dominant feature, 73% importance) is 0 across every single frame of every fault, because none of them ever produce a rolling-window standard deviation below the 0.001 flatline threshold — they're all smooth ramps, exactly as the previous audit said. This is no longer a hypothesis; it's measured against the production classifier.

---

## 2. The model files were worse than "missing" — they're broken git-lfs pointer stubs, even locally

The previous audit said the `.pkl`/`.pt` files simply weren't in the git checkout. That's true but understates it. I found something more specific and more urgent:

`backend/models/` **does exist** on this machine, with 9 files in it — but 4 of them (`sentinel_production.pkl`, `sentinel_supervised.pkl`, `sentinel_if.pkl`, `sentinel_lstm.pt`) are not model files at all. They're plain-text **git-lfs pointer stubs** (`version https://git-lfs.github.com/spec/v1 ... oid sha256:...`) — leftovers from a git-lfs workflow that was never actually configured in this repo (there's no `.gitattributes`, `git lfs` isn't even installed here). Any code that tries `joblib.load("sentinel_production.pkl")` on this exact checkout would **crash immediately** with a pickle/unpickling error, not silently misbehave — this would have been caught the instant someone ran `backend/api.py`, but tonight, before that file exists, nobody had hit it yet.

The good news buried in this: **4 other files are genuinely real, loadable binaries** — `sentinel_if.joblib` (IsolationForest), `sentinel_scaler.joblib` (RobustScaler), `sentinel_lstm_scaler.joblib` (MinMaxScaler), `sentinel_ocsvm.joblib` (OneClassSVM). These load cleanly (with a harmless sklearn 1.7.2→1.8.0 version warning). They're a *different* model lineage — a Phase-1 baseline trained on 18 general statistical features (mean, variance, skew, kurtosis, peak-count, etc. — see `backend/models/sentinel_ensemble.json`) computed by the original OPSSAT-AD benchmark, not on `flatline_duration`/`log_inv_std`. This baseline is more likely to generalize to distribution-shift-style faults than the flatline-only production model, but it operates on whole-segment batch statistics, not a live per-timestep stream — turning it into a real-time detector is a design task, not a bug fix. Worth investigating if Engine B (below) turns out to need a second opinion, but not tonight's priority.

**Fixed tonight:** I retrained `sentinel_production.pkl` for real, using the actual local data (`python backend/sentinel/train.py`, after fixing its hardcoded path — see below). It's now a genuine 1.38MB XGBoost binary, evaluated at F1=0.651 row-level / 0.494 segment-level (close to what the eval JSON already showed — the previous training run wasn't lost, it was just this specific `.pkl` copy that got corrupted). **This machine can now load a real SENTINEL model.** Whether Meet's laptop has a good copy is still unknown and still worth checking — but this laptop is no longer blocked.

**Also fixed:** `backend/sentinel/train.py` line 30 had Meet's hardcoded macOS path (`/Users/meetshah1004/Desktop/...`). Changed to `Path(__file__).resolve().parents[1]` — now runs on any machine.

---

## 3. NEW, more important finding the previous audit missed entirely: 3 of 6 faults are nearly invisible to *any* detector within the demo window

This is the one I'd fix first. I built the physics-threshold detector the previous audit recommended ("Engine B") using `roadmap.md`'s own thresholds table, and tested it — not as a proxy, as actual working code (`backend/sentinel/engine_b.py`) — against all 6 faults at `severity=0.7, duration=3600s` (roadmap's own recommended demo command). Engine B does not depend on any ML model or training, so if a fault beats *this* detector too, it's not a SENTINEL problem anymore — it's a simulator-physics-tuning problem.

| Fault | Engine B max score | Fires? | What's actually happening physically |
|---|---:|:---:|---|
| **tcs_thermal_runaway** | 1.000 | ✅ Yes | panel_temp climbs 38°C → 76°C in ~40min — clean, dramatic, real signal |
| **ttc_signal_dropout** | 1.000 | ✅ Yes | signal_strength crashes to -114.7 dBm (past mission-loss) — clean |
| **propulsion_thruster_fault** | 1.000 | ✅ Yes | thruster_temp redlines to 200°C (its hard clamp) — clean |
| eps_battery_degradation | 0.000 | ❌ No | bus_voltage barely moves (28.80V → 29.87V, *up*, not down); SOC actually *rises* to 0.98 within 1hr. Needed 4 hours to see SOC drop meaningfully. |
| adcs_reaction_wheel_degradation | 0.000 | ❌ No | attitude_error moves from 0.50° to 0.83° — nowhere near the 5° warning line |
| eps_cascade_power_failure | 0.000 | ❌ No | described as "complete solar array loss" but bus_voltage only reaches 28.08V after 1hr (warning line is 25V); needed 4 hours to approach 25V at all |

(One false positive had to be fixed to get this table: `roadmap.md`'s own threshold table lists `battery_temp` warn at 35°C, but this simulator's **normal, no-fault orbital thermal cycling alone swings battery_temp up to 41.4°C** — so a literal copy-paste of that table into a detector would have false-alarmed on every single nominal frame. I recalibrated Engine B's battery_temp thresholds to 44/48/52°C against the measured nominal envelope; verified zero false positives on a clean nominal run afterward.)

**What this means concretely:** no anomaly detector — not the current SENTINEL, not Engine B, not a hypothetical Telemanom/LSTM forecaster (see §4) — can flag `eps_battery_degradation`, `adcs_reaction_wheel_degradation`, or `eps_cascade_power_failure` within a 1-hour demo window at severity 0.7, **because the underlying physics genuinely doesn't move the telemetry far enough yet.** This is upstream of every ML decision in the previous audit. Detection algorithm choice cannot fix a signal that isn't there.

**Two ways to fix, pick one tonight:**
1. **Don't demo those 3 faults.** Lead with `tcs_thermal_runaway` (bonus: this is *literally* the judge's temperature-spike question from §0 — same fault, same story) and `ttc_signal_dropout`/`propulsion_thruster_fault` as backups. This is the zero-risk option and costs nothing.
2. **If you want all 6 in the scenario picker anyway:** the fix is in `backend/simulator/faults.py` — the EPS/ADCS modifier magnitudes (e.g. `eps_capacity_factor`, `eps_solar_factor`, `adcs_wheel_efficiency` deltas) are too small relative to how fast `transitions.py` lets the battery/attitude state respond. I did not touch this tonight — it's core physics tuning with downstream effects on ORACLE's Monte Carlo outcomes and VITALS' health scores, and needs its own testing pass, not a rushed 11pm edit. Budget 30-45 min if you want it.

---

## 4. Telemanom / LSTM-forecast-residual — honest verdict: not tonight's fix, and here's the data showing why

You specifically asked whether the Telemanom approach (predict next value, flag large forecast error) solves the SENTINEL problem. I tested this idea directly rather than taking the "most useful of the five" recommendation on faith.

Using a naive short-horizon forecaster (predict next value from a rolling window mean — a stand-in for what the existing `explain_anomaly.py` LSTM would learn if trained only on non-drifting nominal segments, which is all it's ever been trained on), the 1-step-ahead residual during `eps_battery_degradation`'s and `tcs_thermal_runaway`'s ramps was **barely distinguishable from nominal noise** — a 20-step rolling mean of the residual only grew 1.2-1.4x above the nominal baseline, nowhere near a clean detection margin. The reason: these are *slow, smooth* ramps (`ramp_time_s` of 60-120s = 6-12 steps at dt=10s) — the per-step change is small relative to the sensor noise, so a short-horizon forecaster tracks the ramp almost as well as it tracks noise. A real Telemanom implementation uses smoothed/EWMA error against a rolling historical error distribution rather than raw 1-step error, which would do somewhat better, but it inherits the exact same hard limit as everything else in §3: **for the 3 faults where the physical signal itself barely moves, no forecast-residual technique can manufacture a signal that isn't in the data.**

Where the LSTM/Telemanom idea *would* help: distinguishing "close to a threshold but plausibly normal" from "genuinely drifting toward a threshold" — i.e., a smarter early-warning layer stacked *on top of* Engine B, once the physics-magnitude problem in §3 is fixed. It also needs real training time: the `.pt` file is also a broken LFS pointer (see §2), and the saved `sentinel_lstm_scaler.joblib` is real but the network weights aren't, so it would need retraining (data is present locally — `backend/data/raw/opssat/segments.csv`, likely 5-10 min on CPU given `explain_anomaly.py`'s existing config).

**Recommendation:** build Engine B first (already done tonight, see §5) and fix the fault magnitudes in §3. Treat the LSTM-residual idea as a stretch goal for *after* those two are solid — it adds real training time and, on tonight's evidence, would not have caught anything Engine B doesn't already catch, once the physics is fixed.

---

## 5. What's now actually wired (new/changed files)

| File | Status | What it does |
|---|---|---|
| [`backend/sentinel/engine_b.py`](backend/sentinel/engine_b.py) | **New** | Physics-threshold/z-score detector using `roadmap.md`'s own table (battery_temp recalibrated per §3). `score_state(state)` scores one frame; `combined_score(ml_score, state)` does `max(ml, engine_b)` and degrades gracefully to Engine-B-only if `ml_score` is `None` (i.e. if a teammate's SENTINEL `.pkl` fails to load — this directly neutralizes the "teammate has nothing to load" operational trap). Tested against all 6 faults + a nominal control, see §3 table. |
| [`backend/sherlock/simulator_provider.py`](backend/sherlock/simulator_provider.py) | **New** | `SimulatorTelemetryProvider(TelemetryProvider)` — the exact bridge class the extension point in `telemetry_interface.py` was designed for. Wraps a `SatelliteState` into SHERLOCK's `TelemetrySnapshot` format, field-mapped to match `MockTelemetryProvider`'s existing parameter names. Smoke-tested: produces correct prompt-formatted output from a live `tcs_thermal_runaway` simulation frame. Zero changes to `agent.py`, as designed. |
| [`backend/requirements.txt`](backend/requirements.txt) | **New** | Didn't exist before. Pins every package actually imported across `backend/` (found by grepping every `import`/`from` line) plus the not-yet-built Phase 1/SCRIBE deps (`fastapi`, `uvicorn`, `websockets`, `jinja2`) from `roadmap.md`'s inline pip command. |
| [`backend/sentinel/train.py`](backend/sentinel/train.py) | **Fixed** | Line 30: hardcoded `/Users/meetshah1004/...` path → `Path(__file__).resolve().parents[1]`. Runs on any machine now. |
| [`backend/models/sentinel_production.pkl`](backend/models/sentinel_production.pkl) | **Regenerated** | Was a broken LFS-pointer text stub; ran `train.py` against the real local OPSSAT data and it's now a genuine, loadable 1.38MB XGBoost model (F1 0.651 row-level, matches historical eval numbers). Still gitignored (by design — don't commit it; see §6). |
| [`roadmap.md`](roadmap.md) | **Fixed** | Line 201's "F1 of 0.89" claim (doesn't exist anywhere in any results file) → the real number, 0.65/0.79 ROC-AUC, sourced from `backend/results/sentinel_eval.json`. |

Everything above was actually run, not just written — the numbers in §1 and §3 came from executing this exact code.

---

## 6. Deployment logistics — you said mostly one laptop will run the demo

Given `backend/models/` is gitignored (correctly — some of these files are 1-2MB and don't belong in git without LFS actually configured) and git-lfs isn't set up in this repo at all:

1. **Do not rely on `git clone`/`git pull` to get working models onto the demo laptop.** Whichever laptop runs `backend/api.py` during the demo needs `backend/models/*.joblib` and `backend/models/*.pkl` copied onto it directly — zip `backend/models/` (it's ~4MB total once the `.pkl`/`.pt` files are regenerated like I did tonight) and AirDrop/USB/Slack it to the demo machine. Do this **now**, not at hour 40, exactly as the previous audit said — I'm just flagging it's more urgent than "operational trap," it's currently broken even on the machine that's supposed to have it working.
2. **Regenerate the LSTM (`sentinel_lstm.pt`) the same way if you decide to use it** — `python backend/sentinel/explain_anomaly.py` will retrain it from the same local data (few minutes on CPU per its own epoch/patience settings). It's currently also a broken pointer.
3. `pip install -r backend/requirements.txt` on the actual demo laptop *before* the demo, not during — `xgboost`, `pydantic`, `fastapi`, `uvicorn`, `websockets`, `openai`, and `torch` were **not installed** in the environment I found on this machine. If Meet's laptop is in the same state, the very first `uvicorn backend.api:app` will fail on missing imports.
4. Since only one laptop realistically runs the live demo, put the golden, tested copy of `backend/models/` **on that laptop specifically**, confirm `python -c "import joblib; joblib.load('backend/models/sentinel_production.pkl')"` succeeds there, and don't touch it again before going on stage.

---

## 7. Everything else from the previous audit, re-verified directly against the code

| Claim | Verdict | Where I checked |
|---|:---:|---|
| "18 directed edges" causal graph | ✅ True | `backend/sherlock/graph.py:61` comment + edge list, counted |
| ORACLE `n_runs=100, steps=300, dt=10` → 50 min horizon | ✅ True | `backend/oracle/schemas.py:81-90` field defaults |
| ORACLE fully wired (`run_oracle`, `_evaluate_action`, fallback ranking) | ✅ True | `backend/oracle/agent.py` — `run_oracle`, `validate_action`, `rank_all_actions`, `_evaluate_action` all present and call `run_monte_carlo` |
| SHERLOCK `TelemetryProvider` extension point exists and is unused by a simulator bridge | ✅ True (now fixed, §5) | `backend/sherlock/telemetry_interface.py` — `PassthroughTelemetryProvider` and `MockTelemetryProvider` already existed; no simulator-backed implementation did until tonight |
| Hybrid 3-engine SENTINEL (XGBoost + Z-score + covariance) | ❌ Not built | Confirmed — only XGBoost + IsolationForest baseline existed; Z-score engine (§5) built tonight |
| "F1 of 0.89" | ❌ False, now fixed | `backend/results/sentinel_eval.json` — real number is 0.65 row-level; fixed in `roadmap.md` §5 |
| `backend/models/` missing from git | ✅ True, but worse than stated | It's not just missing — 4 of 9 local files are broken LFS-pointer stubs, see §2 |
| `train.py` hardcoded Meet-only path | ✅ True, now fixed | `train.py:30`, fixed §5 |
| `src/App.jsx` is 100% `setTimeout` fakes, no WebSocket/fetch | ✅ True | grepped for `WebSocket`/`fetch(` — zero matches in 690 lines; `setTimeout` — many |
| No `backend/api.py` yet | ✅ True | Confirmed, still doesn't exist |
| No `requirements.txt` existed | ✅ True, now fixed | §5 |

---

## 8. Corrected priority order for tonight

1. ~~Fix `train.py` path~~ ✅ done
2. ~~Fix "F1 0.89" in `roadmap.md`~~ ✅ done
3. ~~Build Engine B, verify it against all 6 faults~~ ✅ done — 3/6 fire cleanly, 3/6 need simulator retuning (§3)
4. ~~Build `SimulatorTelemetryProvider`~~ ✅ done
5. ~~Write `requirements.txt`~~ ✅ done
6. **Decide now:** either commit to demoing only `tcs_thermal_runaway` / `ttc_signal_dropout` / `propulsion_thruster_fault` (zero further risk), or spend 30-45 min re-tuning `eps_battery_degradation`/`adcs_reaction_wheel_degradation`/`eps_cascade_power_failure` magnitudes in `faults.py` (real risk of breaking ORACLE's Monte Carlo tuning if rushed — test `run_monte_carlo` afterward if you do this)
7. **Get `backend/models/*` onto the actual demo laptop tonight**, not at hour 40 (§6)
8. `pip install -r backend/requirements.txt` on the demo laptop, confirm it actually installs clean
9. Build `backend/api.py` (Phase 1 bridge) — use `SimulatorTelemetryProvider`, call `run_oracle()` directly (it's done), wire SENTINEL's `combined_score()` from `engine_b.py` instead of the raw XGBoost score alone
10. Continue Phase 2 → Phase 8 exactly as `roadmap.md`/`work.md` already lay out — nothing found tonight changes that order
11. LSTM/Telemanom retrain — only if 6-10 spare, after everything above is solid (§4)
