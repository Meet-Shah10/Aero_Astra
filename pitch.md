# AERO-ASTRA — Slide-by-Slide Pitch Script

This is the judge-facing presentation script, one section per PPT slide, in deck order. Same honest narrative arc as before (problem → what we first thought → the wall we hit → the pivot → what we built → demo → close → Q&A) — just distributed across the actual slides so you can present straight from this doc. Every technical figure below is verified against the running code (see `pptcontent.md` for the file:line citations) — say these numbers with confidence, they aren't rounded up for effect.

---

## Slide 1 — Title

Quick, doesn't need a script: team name, problem statement ID, one line — "AERO-ASTRA: an autonomous multi-agent AI system for satellite fault response." Move fast to Slide 2, that's where the hook lives.

---

## Slide 2 — Problem Understanding

**Open with the hook, not the bullet points:**

"In 2023, ESA's OPS-SAT — a satellite the size of a shoebox, orbiting 500km above Earth — developed a subtle sensor fault. A magnetometer flatlined. It took the ground team four contact windows, nearly 16 hours, to notice it, work out what was wrong, and upload a fix. For those 16 hours the satellite kept flying, logging telemetry nobody was watching."

**Then generalize it — this is the slide's actual content:**

A satellite in Low Earth Orbit moves at roughly 7.5 km/s, completing an orbit every ~90 minutes. It's only in radio contact with a ground station for 8–12 minutes per pass, a handful of passes a day — meaning for most of every day it is completely on its own, unwatched and uncommandable.

When contact does happen, a human operator has to: scan the telemetry dump for anomalies (20–40 minutes), figure out which subsystem is at fault, pull in a subject-matter expert, debate the root cause, design and validate a fix, and wait for the *next* contact window to upload it. **End to end: 2 to 48 hours from fault to confirmed fix.**

In that window: a thermal runaway can permanently degrade solar panels, a reaction wheel fault can tumble the spacecraft out of control, a power cascade can drain the battery bus in under four hours and kill the mission outright. This is the cascading-subsystem-risk diagram on the slide — EPS, TCS, ADCS, TT&C aren't independent, a fault in one drags the others down with it.

**Close the slide with the line already printed on it:** "Timely, autonomous and reliable fault diagnosis and recovery planning is essential to ensure mission continuity and asset safety for LEO satellite operations." That's the thesis the rest of the deck has to earn.

---

## Slides 3–4 — Literature Survey

Four gaps, four papers, one honest synthesis — don't read the slide, summarize the pattern:

"Every existing approach we found nails one piece and misses the others. ML-based detectors (Cuéllar et al., 2024) work but are black boxes — no explainability, which is a non-starter for a safety-critical system. Telemetry-only models (Petković et al., 2021) ignore orbital context and false-alarm on normal events like solar conjunctions. Purely data-driven diagnostics (Bieber et al., 2023) fail on fault types they weren't trained on — the cold-start problem, which matters a lot when you're a hackathon team without years of a real spacecraft's failure history. And single-channel monitoring (Lai et al., 2025) can't see faults that only show up as two channels disagreeing with each other, not any one channel crossing a threshold."

**Before you present, verify each DOI actually resolves** — don't let a judge catch a dead citation live, that's worse than a shorter lit review.

**The research gap line is the actual thesis statement**, say it verbatim: "There is a need for an integrated, physics-grounded, explainable, and autonomous framework that can diagnose, validate, and recommend safe recovery actions for satellite anomalies in real time." Then: "That's exactly what we built. Here's how."

---

## Slide 5 — Proposed Solution & Innovation

This is where you compress the "what we thought → the wall → the pivot" story into two sentences before moving into the architecture, since the dataset story gets its own full slide later (7):

"Our first instinct was to pull live telemetry from an operational satellite and train directly on its real fault history. That's not possible — no commercial or defense operator publishes live fault telemetry, it's proprietary and often a security concern. The one real exception is ESA's OPS-SAT, launched specifically as an open experimentation platform, with a public labeled anomaly dataset (OPSSAT-AD). That's what we built on — more on that in the Dataset slide."

**Then the pipeline, correctly described:**

An 8-agent pipeline: SENTINEL (anomaly detection) → SHERLOCK (causal root-cause diagnosis) → ORACLE (recovery simulation) → ATHENA (recovery planning) → GUARDIAN (safety gate) → SCRIBE (audit runbook), with VITALS running continuously alongside for proactive health scoring and CHRONICLE logging every event.

**Three pillars, accurately stated:**

1. **Zero Hallucination Architecture** — SHERLOCK's diagnosis is checked against an 18-edge physical causal graph before it's accepted; if the LLM (Gemini 2.5 Flash, called directly via Google's Gemini API) proposes a root cause outside the physically valid candidate set, it's rejected and reprompted. Every safety decision (GUARDIAN) is deterministic code — no LLM call, no randomness, unit-tested — not "formally verified" in a mathematical sense, but fully auditable and reproducible.
2. **Proactive Intelligence** — VITALS scores subsystem health every second, independent of whether SENTINEL has flagged anything, catching gradual degradation before it crosses a hard threshold.
3. **Execution, Not Just Recommendation** — GUARDIAN doesn't just approve a plan, it executes it step-by-step against the digital twin, logging every step to SCRIBE's runbook.

**The number that lands:** "Cuts triage time from 15–60 minutes down to under 10 seconds — measured end-to-end on our own test runs, not a target we're hoping to hit."

---

## Slide 6 — Novelty of Solution

Six items — present these as "here's what nobody else at this hackathon is likely to have," since that's literally what they're asking when they read a novelty slide:

**1. Physics-Constrained LLM (No Hallucination by Design).** SHERLOCK's causal graph-candidate check means the LLM physically cannot output a root cause that isn't reachable in the 18-edge dependency graph. This isn't "LLM plus better prompting" — it's constrained inference with deterministic rejection logic wrapped around the model.

**2. Zero LLM in the Safety-Critical Path.** GUARDIAN, SENTINEL, ORACLE, and VITALS are 100% deterministic code. The safety gate's decision never depends on what any LLM outputs — a rare discipline in agentic AI systems, where the tempting shortcut is to let the model reason about its own safety.

**3. Monte Carlo Validation Over an Actual Physics Twin.** ORACLE doesn't ask an LLM to estimate a success rate — it runs 100 stochastic simulations per candidate recovery action against a real coupled-differential-equation satellite model (orbital mechanics, eclipse cycling, 6 subsystems) and reports the empirical outcome distribution.

**4. Triple-Engine Anomaly Detection.** XGBoost (trained on real ESA OPSSAT-AD data) plus a physics-based spike filter plus a residual-correlation detector together catch failure classes no single engine catches alone — including the correlated cross-channel drift pattern that killed JAXA's Hitomi, which the other two engines structurally can't see.

**5. RAG-Grounded Recovery Planning.** ATHENA doesn't just ask an LLM to "suggest a procedure" — it retrieves relevant sections from a real spacecraft FDIR handbook (ChromaDB vector store, NASA/ESA reference material) and grounds its recovery steps in retrieved doctrine. Measured, not assumed: 100% retrieval hit-rate, 0.786 recall@4, 1.000 MRR across 7 real fault-scenario queries.

**6. Single-Laptop, End-to-End Demo.** The entire pipeline runs locally on one machine, no cloud infrastructure beyond a single LLM API key. Practical, reproducible, demo-ready.

---

## Slide 7 — Dataset Used

**This is where the full dataset story belongs — tell it as a story, not a table:**

"Our first idea was the obvious one: pull live telemetry from an operational satellite and train directly on its real fault history. That idea didn't survive contact with reality. Operational satellites don't publish their telemetry — commercial operators treat live fault logs as proprietary, sometimes as a security concern, because a public feed of exactly how and when your satellite fails is itself a liability. We checked every public dataset we could find. Most academic 'satellite anomaly data' turns out to be synthetic or simulator-labeled, not a real spacecraft's actual failure history.

So we asked a narrower question: is there *any* real satellite, anywhere, that publishes its own telemetry and fault labels openly? There's exactly one good answer — **ESA's OPS-SAT**, launched in 2019 specifically as an open experimentation platform. ESA also published **OPSSAT-AD**, a labeled anomaly dataset from that satellite's real telemetry (Zenodo, DOI: 10.5281/zenodo.10624588). That's what SENTINEL's Engine A is trained on — real sensor behavior from a real satellite, not a curve we made up.

We also pulled in **Mars Express thermal telemetry** (ESA Planetary Science Archive) — used offline, to calibrate our physics model's thermal constants against how a real spacecraft's temperature behaves under real orbital cycling, not to feed the live pipeline. Where neither dataset covered a fault type we needed — thruster faults, power cascades — we built a **physics-based digital twin**: coupled differential equations per subsystem, calibrated against the real data we did have, rather than inventing fault curves from scratch.

That's the honest version of where the data comes from: one real, open satellite's real anomaly history, real thermal telemetry from a second mission for calibration, and a physics model grounded in both — not a live feed from an operational constellation, because no such feed exists publicly, and we don't pretend otherwise anywhere in the product."

**Tech stack** (verified, don't overstate): Python, FastAPI, Google's genai SDK (Gemini 2.5 Flash, called directly — no LLM gateway in front of it), React + Three.js (3D frontend), XGBoost + scikit-learn (SENTINEL), ChromaDB (ATHENA's RAG retrieval).

---

## Slide 8 — Technical Architecture

Walk the diagram left to right, matching what actually executes in `backend/api.py`:

1. **Data Sources** — the physics digital twin simulator, real OPSSAT-AD telemetry, Mars Express thermal data (offline calibration), and event logs.
2. **Watch** — SENTINEL (three-engine anomaly detection), VITALS (continuous health scoring), CHRONICLE (event log analysis).
3. **Diagnose** — SHERLOCK: Phase 1 computes the physically valid candidate set from the 18-edge graph (no LLM, <5ms), Phase 2 the LLM reasons within that set, Phase 3 validates the output and rejects/reprompts if it steps outside the candidate set.
4. **Act & Ensure Safety** — ORACLE runs the 100-run Monte Carlo against the digital twin; ATHENA turns the winning result into a human-readable plan; GUARDIAN is a **deterministic 5-rule engine** (not an SMT solver — say this correctly: time-to-critical, urgency level, irreversibility, and a safety-score floor, first-match-wins ordering) that decides AUTONOMOUS_SAFED / AUTOMATED_GUARDED / MANUAL_INTERLOCK.
5. **Output** — SCRIBE's auditable runbook and the live operator dashboard.

---

## Slide 9 — Implementation / Prototype

"Everything in this pipeline runs end-to-end on a single laptop — no cloud infrastructure beyond one LLM API key."

| Layer | What it is | Status |
|---|---|---|
| Frontend | React 18 + Vite, Three.js/React-Three-Fiber 3D mission control, live WebSocket client | Running |
| Backend | FastAPI + Uvicorn, async WebSocket bridge | Running |
| SENTINEL | XGBoost (OPSSAT-AD trained) + physics spike filter + residual correlation detector | Live |
| SHERLOCK | 18-edge causal graph + Gemini 2.5 Flash, physics-gated | Live |
| ORACLE | 100-run Monte Carlo, 6-subsystem physics twin | Live |
| ATHENA | RAG-grounded (ChromaDB + FDIR handbook) planning + Gemini 2.5 Flash | Live |
| GUARDIAN | Deterministic 5-rule safety gate | Live |
| SCRIBE | Markdown/PDF audit runbook | Live |

"Every component in this table is the same code running in the live demo you're about to see — nothing here is a slide-only claim."

---

## Slide 10 — Feasibility & Impact

**Feasibility, in one line:** "Runs on standard hardware, on-premise, no dependency on cloud infrastructure — this isn't a research prototype that only works on a specific GPU cluster."

**The ground-vs-onboard question — expect this exact question from a technical judge, have the answer ready:**

"Real flight computers use radiation-hardened processors running at a few hundred MHz — they can't run an LLM, and they don't need to. The dangerous window isn't the seconds after a fault starts; most real subsystem failures take 30–90 minutes to become unrecoverable. A ground-based pipeline finishing in under 10 seconds is still enormously faster than that window, and it's how real mission control systems are actually built today — we're making the human analysis step automatic, not replacing hardwired onboard safe-mode logic, which already handles truly instantaneous events like cosmic-ray bit-flips."

**Then the two case studies — these aren't decoration, they're proof:**

"Hitomi (JAXA, 2016) — an inertial sensor disagreed with the star tracker, the control system trusted the wrong one, and the spacecraft spun itself apart correcting a rotation that never happened. That's not a hypothetical for us — it's one of our five live demo scenarios. Our detector is purpose-built to catch exactly that kind of two-channel disagreement.

Mars Global Surveyor (NASA, 2006) — a software update wrote to the wrong memory location due to insufficient validation, leading to power loss and total mission loss after 11 years of operation. A system that catches abnormal power and thermal trends early — which is exactly what VITALS does continuously — could have flagged that degradation before it became unrecoverable."

---

## Slide 11 — Results

Real numbers only — nothing here is invented, all pulled from `backend/evaluation_results.md` and `backend/athena/rag/EVAL_REPORT.md`:

**SENTINEL**, tested against real OPSSAT-AD: Engine A (XGBoost + persistence) scores F1 = 0.4958 / PR-AUC = 0.5479 on early-mission (noisier) data, F1 = 0.6465 / PR-AUC = 0.6927 on late-mission (cleaner) data. Engine B (physics spike + triad isolation) cuts false positives from ~550/day (legacy CUSUM baseline) to under 5/day, with near-zero detection latency on impact.

**SHERLOCK:** 100% of diagnoses physics-validated before acceptance. Under 5 seconds per diagnosis vs. 15–60 minutes manual.

**ATHENA's RAG retrieval:** 100% hit-rate@4, 0.643 precision@4, 0.786 recall@4, 1.000 MRR@4 across 7 real fault-scenario queries against the FDIR handbook. One honest miss worth mentioning yourself before a judge finds it: average retrieval latency 1123ms vs. a 1000ms target — say this out loud, an honest failed metric next to five passing ones is far more credible than pretending everything is perfect.

**Full pipeline:** under 10 seconds end-to-end, measured — detection through GUARDIAN's gate decision. That's the number that directly answers Slide 2's stated problem.

---

## Slide 12 — Screenshots

This slide is your transition into the live demo — don't over-narrate it, use it as a table of contents for what you're about to show live:

1. Landing page — 3D Earth + orbiting satellite (proves it's a real render, not a video)
2. Mission Control dashboard, nominal state
3. Anomaly injected — the callout labels popping on the zoomed component, red emergency overlay
4. SHERLOCK's causal graph — flagged node red, candidate nodes amber, confirmed chain green (this is the strongest single image in the whole deck — it visually proves the Novelty slide's item 1 instead of just asserting it)
5. ORACLE's ranked-actions + outcome distribution
6. GUARDIAN's MANUAL_INTERLOCK gate — the literal human-approval moment
7. The Hitomi historical case-study replay

**Then say:** "Rather than walk through static screenshots, let's just run it live," and go to the actual dashboard.

---

## Slide 13 — Future Enhancements

Keep this honest about scope, don't overpromise:

- **Autonomous learning loop** — GUARDIAN-approved decisions feeding back into SENTINEL/SHERLOCK to refine detection over time.
- **Edge vs. ground reasoning** — onboard hardwired safe-mode for instantaneous events (already true today, not future), AI diagnosis and recovery planning staying ground-based (architectural choice, not a limitation — see Slide 10).
- **GPU batch inference for constellation scale** — Kafka-buffered telemetry evaluated in CUDA-parallel batches, scaling SENTINEL to thousands of satellites.
- **Hot/cold storage tiering** — 14-day live telemetry, older data compressed and archived, for long-duration missions.

If you still want a payload-management agent on this slide, give it a new name and a one-line reason it's coming back — reviving a shelved feature without explanation reads as indecisive to a judge who remembers you cut it.

---

## Slide 14 — Conclusion

"We set out to answer one question: can a system manage a satellite anomaly better than the ground team that exists today?

The honest answer is yes — but only if you're disciplined about where you use AI and where you don't. Real data where real data exists. Physics simulation where it doesn't. Language models for reasoning, never for arithmetic. And a human always able to stop the machine before anything irreversible happens.

AERO-ASTRA takes a satellite anomaly from detection to a physics-validated, human-approvable recovery plan in under 10 seconds — a measured number, not a target. What's not yet done: onboard deployment (ground-based by design) and constellation-scale load testing beyond a single-satellite demo. We're presenting what we built, not what we plan to build.

The OPS-SAT anomaly that took 16 hours to resolve — this pipeline handles the equivalent in under 10 seconds."

---

## Slide 15 — Thank You / Q&A

Q&A bank — have these ready verbatim, judges ask these almost every time:

**Q: Why not train on real, current satellite telemetry?**
A: Because it isn't public. No operator of a live constellation publishes fault history — proprietary, often a security concern. OPS-SAT is the one satellite that publishes real labeled anomaly data openly, so that's what we trained on, and we say so directly rather than implying access we didn't have.

**Q: Which LLM, and why?**
A: Gemini 2.5 Flash, called directly via Google's Gemini API. It's used only where genuine language-level reasoning is needed — causal diagnosis narrative and procedure writing — never for anything that's actually a calculation. Safety scores come from Monte Carlo simulation, not the model.

**Q: What's novel vs. existing FDIR systems?**
A: Traditional FDIR is rule-based lookup tables — no learning, no causal reasoning, no simulated comparison of fix options. We add a detector trained on real satellite data, physics-constrained causal diagnosis, Monte Carlo-validated recovery simulation, retrieval-grounded planning, and a graded human-authority gate. No existing open system combines all five.

**Q: How would this scale to a constellation of 1,000 satellites?**
A: SENTINEL and VITALS are stateless, sub-5ms per satellite — deploy as parallel workers. SHERLOCK/ATHENA are async LLM calls direct to Gemini's API. ORACLE's Monte Carlo runs are embarrassingly parallel across GPU nodes. The real bottleneck is LLM API rate limits — worth being upfront about here, since our own free-tier key caps at 20 requests/day per model — solved at production scale by a paid tier plus priority queuing critical faults first.

**Q: What if there's no internet or API access at the ground station?**
A: The reasoning stages fall back to a precomputed offline response; detection, simulation, and the safety gate don't depend on a live API. You lose the natural-language explanation layer, not the actual fault handling.

**Q: How confident are you the physics model is realistic?**
A: Calibrated against real OPS-SAT and Mars Express telemetry rather than invented constants, with zero false positives across repeated nominal-telemetry test runs. It's a best-effort physics approximation, not certified flight-grade fidelity — we don't blur that distinction.

**Q: What stops the system from executing a bad fix?**
A: Every candidate is simulated before execution; any option with a meaningfully high mission-loss chance is automatically routed to MANUAL_INTERLOCK regardless of urgency. Nothing irreversible happens without a human clicking approve.

---

*— AERO-ASTRA*
