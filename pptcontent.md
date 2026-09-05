# PPT Content — What To Add / Fix in `SHIH26-TID-202_ppt.pdf`

Fact-checked against the actual running code (file:line citations given). Organized as direct per-slide instructions — copy what you need straight into the deck.

---

## ⚠ Demo-day operational risk — not a slide fix, a logistics warning

The Gemini API key in `backend/.env` is on the **free tier: 20 requests/day per model**. Each anomaly run through the live pipeline costs at least 2 calls (SHERLOCK + ATHENA), more on any validation retry. That's roughly **8-10 full demo runs before the quota is exhausted for the day** — including every rehearsal. If it runs out mid-judging, the pipeline doesn't crash (it falls back to a canned offline diagnosis, gracefully), but you'd silently stop showing real LLM output without necessarily noticing live. Before presenting: either upgrade to a paid Gemini API tier, or budget your rehearsals carefully and do a final quota check right before you go on.

---

## Fix these four first — they are currently false as written

A judge catching one fabricated claim stops trusting the rest of the deck. Fix these before anything else.

### 1. Novelty slide (6), item 01 — wrong LLM name
**Currently says:** "SHERLOCK's causal graph-candidate check means **Claude Sonnet 4.5** physically cannot output a root cause..."
**Reality:** `sherlock/agent.py` and `athena/agent.py` now call Gemini directly via Google's genai SDK (`DEFAULT_MODEL = "gemini-2.5-flash"`, `GEMINI_API_KEY`). This was fixed mid-session — the code previously pointed an OpenAI-compatible client at OpenRouter, which the actual `.env` key (a native Google AI Studio key) couldn't authenticate against, so every diagnosis was silently running the offline fallback stub. Verified live post-fix: both agents now genuinely call Gemini.
**Fix:** replace "Claude Sonnet 4.5" with "Gemini 2.5 Flash (called directly via Google's genai SDK)" everywhere it appears in the deck.

### 2. Proposed Solution (5) + Technical Architecture (8) — fabricated Z3 claim
**Currently says:** "Every decision is auditable and **Z3-formally-verified**, not a black box" (slide 5); GUARDIAN box labeled "**Z3 SMT Prover** & Human Interlock Gate" (slide 8).
**Reality:** `grep -rl "z3\|Z3" backend/` → zero files. No SMT solver anywhere in the repo. `guardian/engine.py` (lines 1-25) is a plain deterministic 5-rule Python `if/elif` chain — good, but not formally verified in the SMT sense.
**Fix:** delete "Z3-formally-verified," replace with "every rule is deterministic and unit-tested." Relabel the slide-8 box "Deterministic Rule Engine & Human Interlock Gate."

### 3. Proposed Solution (5) pipeline strip — wrong SENTINEL description
**Currently says:** SENTINEL — "**Isolation Forest + LSTM Autoencoder**"
**Reality:** `sentinel/engines.py` (the code that actually runs live) implements three engines: Engine A = XGBoost flatline+persistence filter, Engine B = physics spike/boundary filter, Engine C = residual-correlation detector (EWMA-based). No Isolation Forest, no LSTM Autoencoder in the live detection path. (An LSTM does exist in `sentinel/root_cause.py`, but that's a separate offline explainability script — not what SENTINEL runs during detection.)
**Fix:** relabel "XGBoost + Physics Spike Filter + Residual Correlation Detector (3 engines)."

### 4. Proposed Solution (5) — wrong Monte Carlo count
**Currently says:** "**1,000-run** Monte Carlo validation"
**Reality:** `oracle/schemas.py:81-83` sets `default=100`; every live call in `oracle/demo.py` (lines 122, 171, 233) passes `n_runs=100`.
**Fix:** change to "100-run Monte Carlo validation."

---

## Two more numeric/factual corrections

### 5. Tech stack (slide 7) — two tools that aren't actually used
**Currently lists:** NVIDIA NeMo, Chart.js
**Reality:** `grep -rli nemo backend/` → 0 hits, nowhere in the codebase. `chart.js` is not in `package.json`. Frontend charts (`OutcomeDistributionCard.jsx`, `SocTrajectoryChart.jsx`) are hand-built inline SVG, not a charting library.
**Fix:** remove both from the tech stack grid. If you want to keep six logos for visual balance, add ChromaDB (real — used by ATHENA's RAG pipeline, see item 8 below) and scikit-learn (real — used throughout SENTINEL training).

### 6. Proposed Solution (5) — weaker number than what you measured
**Currently says:** "Cuts triage time from 15-60 min → **under 90 sec**"
**Reality:** `backend/evaluation_results.md` documents the actual measured end-to-end latency (detection → SENTINEL → SHERLOCK → GUARDIAN → ORACLE) as **under 10 seconds**.
**Fix:** use the real, stronger, already-measured number: "under 10 seconds."

---

## Slide-by-slide notes

**Slide 1 (Title):** No factual claims. Fine as-is.

**Slide 2 (Problem Understanding):** Solid, matches reality — LEO ground contact windows, 90-min orbits, cascading subsystem risk. No changes needed; strongest slide in the deck as-is.

**Slides 3-4 (Literature Survey):** Structurally sound gap→solution framing. Cannot verify the four cited DOIs from here (no web access) — double-check each one resolves to the actual paper before presenting; a judge googling a dead/wrong DOI live is worse than a shorter lit review.

**Slide 5 (Proposed Solution & Innovation):** Apply fixes #1, #3, #4, #6 above. Everything else — the 4-layer "Zero Hallucination Architecture," "Proactive Intelligence" (VITALS RUL tracking), "Execution, Not Just Recommendation" — is directionally accurate to how the pipeline actually runs. Keep the structure.

**Slide 6 (Novelty of Solution):** See the full rewritten version below — apply fix #1, and add the new RAG item (#8).

**Slide 7 (Dataset Used):** Apply fix #5. Everything about OPS-SAT and Mars Express is otherwise accurate — Mars Express thermal data genuinely exists in `backend/data/raw/mars_express/data15.csv` and is used in `sentinel/eps_tcs.py`. Add one clarifying word: that script is an **offline calibration tool**, not something the live pipeline streams from at demo time — say so explicitly so nobody assumes you're ingesting Mars Express telemetry live.

**Slide 8 (Technical Architecture):** Apply fix #2 (GUARDIAN box relabel). Everything else — the DATA SOURCES → WATCH → DIAGNOSE → ACT → OUTPUT flow — matches how `api.py` actually sequences the agents.

**Slide 9 (Implementation/Prototype) — currently blank:** Content below.

**Slide 10 (Feasibility & Impact):** Hitomi and Mars Global Surveyor are real documented incidents; Hitomi is also your live case-study demo scenario, so this slide and the working demo reinforce each other. No issues found — keep as-is.

**Slide 11 (Results) — currently blank:** Content below, pulled directly from `backend/evaluation_results.md` and `backend/athena/rag/EVAL_REPORT.md` — nothing invented.

**Slide 12 (Screenshots) — currently blank:** Shot list below.

**Slide 13 (Future Enhancements):**
- "QUARTERMASTER Activation" box directly contradicts the earlier decision to remove QUARTERMASTER "from everywhere... from actual agent stuff." Framing it as a *future* item is technically consistent (not in the current build), but if a judge remembers you removed it, be ready with a one-line reason, or just cut the box.
- "Live WebSocket Integration — replaces the mock frontend with a real ws pipeline" describes something **already built and running** (`backend/api.py` has a real `ws://.../ws` bridge) — this isn't a future item. Remove it or reword to describe what's actually still mocked, if anything is.

**Slide 14 (Conclusion) — currently blank:** Content below.

**Slide 15 (Thank You):** Fine as-is.

---

## New content for the blank slides

### Slide 9 — Implementation / Prototype

> AERO-ASTRA runs end-to-end on a single laptop — no cloud infrastructure beyond one LLM API key.

| Layer | What it is | Status |
|---|---|---|
| Frontend | React 18 + Vite, Three.js/React-Three-Fiber 3D mission control, live WebSocket client | Fully built, running |
| Backend | FastAPI + Uvicorn, async WebSocket bridge (`backend/api.py`) | Fully built, running |
| SENTINEL | XGBoost (trained on real OPSSAT-AD) + physics spike filter + residual correlation detector | Trained, live |
| SHERLOCK | 18-edge NetworkX causal graph + Gemini 2.5 Flash (called directly via Google's genai SDK), physics-gated | Live |
| ORACLE | 100-run Monte Carlo over a 6-subsystem coupled physics digital twin | Live |
| ATHENA | RAG-grounded (ChromaDB + NASA FDIR handbook) recovery planning + Gemini 2.5 Flash | Live |
| GUARDIAN | Deterministic 5-rule safety gate | Live |
| SCRIBE | Markdown/PDF audit runbook generation | Live |

Close with: "Every component in this table is the same code running in the live demo you're about to see — nothing here is a slide-only claim."

### Slide 11 — Results

**SENTINEL (anomaly detection, tested against real OPSSAT-AD)**
- Engine A (XGBoost + persistence): F1 = 0.4958 / PR-AUC = 0.5479 (early-mission, noisier data); F1 = 0.6465 / PR-AUC = 0.6927 (late-mission, cleaner flatlines)
- Engine B (physics spike + triad isolation): false-positive rate cut from ~550/day (legacy CUSUM baseline) to **<5/day**; true-positive detection latency ~0 seconds on impact

**SHERLOCK (diagnosis)**
- 100% of diagnoses physics-validated against the causal graph before being accepted
- Time-to-diagnosis: <5 seconds per event vs. 15–60 minutes manual

**ATHENA (RAG-grounded planning)**
- Hit-rate@4: 100%, Precision@4: 0.643, Recall@4: 0.786, MRR@4: 1.000 across 7 real fault-scenario queries against ESA/NASA FDIR handbook content
- One honest miss: avg retrieval latency 1123ms vs. a 1000ms target — **include this**. An honest failed metric next to five passing ones reads far more credible than five suspiciously perfect numbers.

**Full pipeline**
- End-to-end latency (detection → SENTINEL → SHERLOCK → GUARDIAN → ORACLE): **under 10 seconds**, measured
- vs. 15–60 min manual triage baseline from slide 2 — draw the direct line from the stated problem to the measured fix.

### Slide 14 — Conclusion

> AERO-ASTRA takes a satellite anomaly from detection to a physics-validated, human-approvable recovery plan in under 10 seconds — a documented, measured number, not a target.
>
> It's built on real data (ESA OPS-SAT), real physics (a 6-subsystem coupled digital twin, Monte Carlo validated), and a hard architectural rule: language models reason, they never compute a safety number themselves.
>
> What's not yet done: onboard deployment (ground-based by design — see Feasibility), and constellation-scale load testing beyond a single-satellite demo. We're presenting what we built, not what we plan to build.

The last paragraph matters: naming your own scope limits reads as more credible than implying the system is finished and flight-ready.

---

## Slide 6 rewrite — Novelty of Solution

Your current 5 items are good raw material. Fix item 01's model name, and add a 6th item — the RAG pipeline is your most concretely evidenced novel claim (real eval numbers, and nobody else at a hackathon table is likely to have a working retrieval-grounded planner with a measured hit-rate) and it's currently absent from the deck entirely.

**01 — Physics-Constrained LLM (No Hallucination by Design)**
SHERLOCK's causal graph-candidate check means the LLM (Gemini 2.5 Flash, called directly via Google's Gemini API) *physically cannot* output a root cause that isn't reachable in the 18-edge dependency graph — Phase 1 computes the valid candidate set before the LLM ever runs, Phase 3 rejects and reprompts if it violates that set. This isn't "LLM + better prompting" — it's constrained inference with deterministic rejection logic wrapped around the model.

**02 — Zero LLM in the Safety-Critical Path**
GUARDIAN, SENTINEL, ORACLE, and VITALS are 100% deterministic code — no API call, no randomness, unit-tested. The safety gate's decision doesn't depend on what any LLM outputs. A rare design choice in agentic AI systems, where the tempting shortcut is to let the model reason about its own safety.

**03 — Monte Carlo Validation Over an Actual Physics Twin**
ORACLE doesn't ask an LLM to estimate a success rate — it runs 100 stochastic simulations per candidate action against a real coupled-differential-equation satellite model (orbital mechanics, eclipse cycling, 6 subsystems) and reports the empirical outcome distribution. Physics-grounded validation, not a guess dressed up as a percentage.

**04 — Triple-Engine Anomaly Detection**
XGBoost (trained on real ESA OPSSAT-AD flatline data) + a physics-based spike/boundary filter + a residual-correlation detector together catch failure classes no single engine reliably catches alone — including the correlated cross-channel drift pattern that killed JAXA's Hitomi, which none of the other two engines are built to see.

**05 — RAG-Grounded Recovery Planning** *(new)*
ATHENA doesn't just ask an LLM to "suggest a procedure" — it retrieves relevant sections from a real spacecraft FDIR handbook (ChromaDB vector store, NASA/ESA reference material) and grounds its recovery steps in retrieved doctrine, not model memory alone. Measured: 100% retrieval hit-rate, 0.786 recall@4, 1.000 MRR across 7 real fault-scenario queries. Evaluated the way a real IR system is evaluated, not eyeballed for "does it sound reasonable."

**06 — Single-Laptop, End-to-End Demo**
The entire pipeline — simulator → SENTINEL → SHERLOCK → ORACLE → ATHENA → GUARDIAN — runs locally on one machine with no cloud infrastructure beyond a single LLM API key. Practical, reproducible, and demo-ready — no "trust us, it works in the cloud we can't show you."

---

## Screenshots slide — shot list

1. Landing page — the 3D Earth + orbiting satellite (proves "not a static video")
2. Mission Control dashboard, nominal state — SYSTEM VITALS gauges + telemetry stream
3. Anomaly injected mid-pipeline — the callout labels (e.g. TCS / TEMP RISING / ANOMALY DETECTED) popping on the zoomed satellite component, red emergency overlay active
4. SHERLOCK's causal graph view — flagged node red, candidate nodes amber, confirmed chain green. **Highest-value screenshot** — put it right next to Novelty item 01, since it visually proves the "physics-constrained" claim rather than just asserting it in text
5. ORACLE's ranked-actions panel with the outcome-distribution chart
6. GUARDIAN's MANUAL_INTERLOCK approval gate — the literal "human must click approve" moment
7. The Hitomi historical case-study replay screen, if it renders distinctly from the synthetic scenarios

---

## Cross-check against `pitch.md`

`pitch.md` is the narrative talking-script; this PPT is the technical judged deck — they don't need to be word-identical, but they can't contradict each other on facts. Status after this pass:

- **Latency:** both now say "under 10 seconds," matching `evaluation_results.md`. Aligned.
- **Dataset:** both correctly frame OPS-SAT as the real trained-on dataset, physics simulation as the fallback where OPS-SAT doesn't cover a fault type. Aligned.
- **LLM model:** `pitch.md` never names a specific model (deliberately generic — "the LLM," "a language model"), so it isn't contradicted by the Gemini finding. Once you apply fix #1 above, the PPT will match. No change needed in pitch.md.
- **Agent count/names:** `pitch.md` deliberately compresses the pipeline into 6 narrative stages instead of naming all 8 agents by code name — intentional simplification for a spoken pitch, not an error. The PPT should keep the full 8-agent technical breakdown; a judged deck is where that detail belongs.
- **Z3 / Isolation Forest / LSTM Autoencoder / NeMo / Chart.js / 1000-run Monte Carlo:** none of these appear in `pitch.md` — they were PPT-only errors, all fixed above.
