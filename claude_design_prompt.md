# Prompt for Claude (slide/deck generation) — AERO-ASTRA PPT

## How to use this

1. **Yes, upload the existing PDF** (`SHIH26-TID-202_ppt.pdf`) alongside this prompt. Tell Claude to keep the exact same template — same logos (New Horizon, AICTE, Institution's Innovation Council), same color scheme (navy blue headers, teal-outlined boxes), same slide count and layout structure (title, 4-box grid, 2x2 innovation grid, table + tech-stack-icons layout, architecture flow diagram, etc.) — and to **replace the content of each slide with the corrected version below**, not redesign the deck from scratch. The goal is the same visual deck with accurate content, not a new design.
2. Paste everything below the line as one message.
3. If the tool asks you to go slide-by-slide instead of all at once, feed it one `### Slide N` section per turn, in order.

---

I'm rebuilding the content of a 15-slide hackathon pitch deck (AERO-ASTRA — an autonomous multi-agent AI satellite fault-response system). Keep the exact visual template from the attached PDF (logos, colors, box/grid layouts, slide count) but replace every slide's text content with what I give you below. Every number and technical claim here has been verified directly against the actual running codebase — do not soften, round, or "improve" these numbers, use them exactly as given.

### Slide 1 — Title
No change needed. Keep as-is: event branding, "AERO-ASTRA: An Autonomous Multi-Agent AI for Satellite Operations," team info (Team Serenitians, SH-DST-01, Pimpri Chinchwad College of Engineering).

### Slide 2 — Problem Understanding
No content change needed — this slide is already accurate. Keep: the 4-box grid (Limited Ground Contact / Manual Triage / Delayed Response / Cascading Subsystem Risk), the 10-15 min contact / 22 hour blind spot stat, and the closing thesis line about timely autonomous fault diagnosis being essential.

### Slides 3-4 — Literature Survey
No content change needed structurally. Keep the four gaps (Explainability, Orbital Context/False Positives, Cold Start, Cross-Subsystem Propagation) and their citations exactly as they are — but flag to me if any of the four DOIs (Cuéllar 2024, Petković 2021, Bieber 2023, Lai 2025) don't resolve to real papers when you check, I need to verify these before presenting.

### Slide 5 — Proposed Solution & Innovation
Replace the pipeline strip and stat callouts with:

- Header: "An 8-agent AI system that diagnoses, simulates, and resolves satellite anomalies autonomously — with a deterministic safety gate at every irreversible decision."
- Left callout stats:
  - "Cuts triage time from 15-60 min → under 10 seconds (measured end-to-end, not a target)"
  - "LLM steps are hallucination-constrained: SHERLOCK can't invent impossible causes, ATHENA never generates its own safety score"
  - "Every decision is auditable and deterministic — GUARDIAN's 5-rule safety engine is unit-tested code, not a black box"
- Pipeline strip (6 boxes, left to right): TELEMETRY (Physics digital twin, multi-modal mission data) → SENTINEL (Anomaly detection: XGBoost + Physics Spike Filter + Residual Correlation Detector) → SHERLOCK (Causal root-cause: 18-edge graph, LLM-constrained) → ORACLE (100-run Monte Carlo validation) → ATHENA (RAG-grounded recovery plan) → GUARDIAN (Deterministic rule engine, auto-execute or human authorize)
- 3 Innovation Pillars (keep the layout, update text):
  1. **Zero Hallucination Architecture** — Layer 1: LLM reasoning (SHERLOCK, ATHENA, Gemini 2.5 Flash called directly via Google's genai SDK). Layer 2: Physics validation (ORACLE — 100x Monte Carlo). Layer 3: Rule enforcement (GUARDIAN — not an LLM, deliberately). Layer 4: Human override gate (mandatory for irreversible commands).
  2. **Proactive Intelligence** — VITALS monitors degradation trends continuously, even when no anomaly fires. Catches subsystem degradation before failure threshold. Health scoring runs every second independent of SENTINEL.
  3. **Execution, Not Just Recommendation** — GUARDIAN executes approved plans step-by-step against the digital twin. Each step validated before the next begins. Full execution log in SCRIBE's runbook.

### Slide 6 — Novelty of Solution
Replace all 5 boxes and add a 6th:

**01 — Physics-Constrained LLM (No Hallucination by Design)**
SHERLOCK's causal graph-candidate check means the LLM (Gemini 2.5 Flash, called directly via Google's Gemini API) physically cannot output a root cause that isn't reachable in the 18-edge dependency graph. This isn't "LLM + prompt engineering" — it's constrained inference with deterministic rejection logic built around the model.
*Callout: This isn't "LLM + prompt engineering" — it's constrained inference with deterministic rejection logic built around the model.*

**02 — Zero LLM in the Safety-Critical Path**
GUARDIAN, SENTINEL, ORACLE, and VITALS are 100% deterministic code. The safety gate ignores LLM reasoning entirely — the system's safety guarantees hold regardless of what the LLM outputs.
*Callout: A rare design choice in agentic AI systems.*

**03 — Monte Carlo Validation over an Actual Physics Twin**
ORACLE doesn't heuristically score recovery actions — it runs 100 stochastic simulations against a real coupled-differential-equation satellite model (orbital mechanics, eclipse cycling, 6 subsystems) to produce genuine outcome distributions.
*Callout: Physics-grounded validation, not heuristic scoring.*

**04 — Triple-Engine Anomaly Detection**
XGBoost (trained on real ESA OPS-SAT data) + a physics-based spike filter + a residual-correlation detector together catch anomaly classes that no single engine alone detects reliably — including the correlated cross-channel drift pattern behind JAXA's Hitomi loss.
*Callout: Higher detection coverage through complementary methods.*

**05 — RAG-Grounded Recovery Planning** *(new box)*
ATHENA doesn't just ask an LLM to "suggest a procedure" — it retrieves relevant sections from a real spacecraft FDIR handbook (ChromaDB vector store, NASA/ESA reference material) and grounds its recovery steps in retrieved doctrine. Measured: 100% retrieval hit-rate, 0.786 recall@4, 1.000 MRR across 7 real fault-scenario queries.
*Callout: Evaluated like a real IR system, not eyeballed for plausibility.*

**06 — Single-Laptop, End-to-End Demo**
The entire pipeline — simulator → SENTINEL → SHERLOCK → ORACLE → ATHENA → GUARDIAN — runs locally on one machine with no cloud infrastructure beyond a single LLM API key.
*Callout: Practical, reproducible, and demo-ready.*

### Slide 7 — Dataset Used
Replace the dataset table's source column and add a caveat:

| Dataset | Description | Source |
|---|---|---|
| OPS-SAT (On-board Processing Satellite) | Real satellite telemetry from ESA's OPS-SAT mission; multi-sensor time series (attitude, power, thermal); used for training and benchmarking anomaly detection | ESA OPS-SAT Open Dataset (ops-sat.esa.int) |
| Mars Express | Real satellite telemetry (thermal data); used **offline** to calibrate physics model constants against real orbital thermal behavior — not streamed into the live pipeline | ESA Planetary Science Archive (PSA) |
| Synthetic Fault Scenarios (Physics-Based) | Generated using our 6-subsystem satellite digital twin; includes injected faults (sensor noise, drift, bias, complete failure); used for rare fault cases and recovery validation | Generated using in-house simulator |

Tech Stack row — replace the icon set with: Python, FastAPI, Google Gemini API (genai SDK — direct, no gateway), React, Three.js, ChromaDB, scikit-learn. Remove NVIDIA NeMo and Chart.js entirely — neither is actually used anywhere in the codebase.

### Slide 8 — Technical Architecture
Keep the 5-column flow diagram exactly as laid out (DATA SOURCES → WATCH → DIAGNOSE → ACT & ENSURE SAFETY → OUTPUT). One text fix: relabel the GUARDIAN box from "Z3 SMT Prover & Human Interlock Gate" to **"Deterministic Rule Engine & Human Interlock Gate."** There is no Z3/SMT solver anywhere in the codebase — GUARDIAN is a plain 5-rule deterministic Python engine (time-to-critical, urgency level, irreversibility, safety-score floor), which is accurate and still a strong claim, just not "formally verified" in the SMT sense.

### Slide 9 — Implementation / Prototype (currently blank — new content)

Header: "AERO-ASTRA runs end-to-end on a single laptop — no cloud infrastructure beyond one LLM API key."

Table:
| Layer | What it is | Status |
|---|---|---|
| Frontend | React 18 + Vite, Three.js/React-Three-Fiber 3D mission control, live WebSocket client | Fully built, running |
| Backend | FastAPI + Uvicorn, async WebSocket bridge | Fully built, running |
| SENTINEL | XGBoost (OPS-SAT trained) + physics spike filter + residual correlation detector | Trained, live |
| SHERLOCK | 18-edge causal graph + Gemini 2.5 Flash (direct API), physics-gated | Live |
| ORACLE | 100-run Monte Carlo, 6-subsystem physics twin | Live |
| ATHENA | RAG-grounded (ChromaDB + FDIR handbook) planning + Gemini 2.5 Flash | Live |
| GUARDIAN | Deterministic 5-rule safety gate | Live |
| SCRIBE | Markdown/PDF audit runbook | Live |

Footer line: "Every component in this table is the same code running in the live demo — nothing here is a slide-only claim."

### Slide 10 — Feasibility & Impact
No content change needed — this slide is accurate. Keep the Feasibility 4-box grid and the Hitomi/Mars Global Surveyor case-study comparison exactly as-is.

### Slide 11 — Results (currently blank — new content)

**SENTINEL** (tested against real OPS-SAT data): Engine A (XGBoost + persistence) — F1 = 0.4958 / PR-AUC = 0.5479 (early-mission), F1 = 0.6465 / PR-AUC = 0.6927 (late-mission). Engine B (physics spike + triad isolation) — false positives cut from ~550/day (legacy baseline) to under 5/day, near-zero detection latency.

**SHERLOCK**: 100% of diagnoses physics-validated before acceptance. Under 5 seconds per diagnosis vs. 15-60 minutes manual.

**ATHENA (RAG retrieval)**: 100% hit-rate@4, 0.643 precision@4, 0.786 recall@4, 1.000 MRR@4 across 7 real fault-scenario queries. One honest miss: avg latency 1123ms vs. 1000ms target — include this, it reads as more credible than pretending everything passed.

**Full pipeline**: under 10 seconds end-to-end (detection → SENTINEL → SHERLOCK → GUARDIAN → ORACLE), measured — directly answers the problem stated on Slide 2.

### Slide 12 — Screenshots (currently blank — insert real screenshots)

Shot list, in order: (1) landing page 3D Earth + satellite, (2) dashboard nominal state with VITALS gauges, (3) anomaly injected — the callout labels popping on the zoomed component, red emergency overlay, (4) SHERLOCK's causal graph (flagged red / candidates amber / confirmed chain green — put this one right next to Novelty item 01, it visually proves the claim), (5) ORACLE's ranked-actions + outcome distribution, (6) GUARDIAN's MANUAL_INTERLOCK human-approval gate, (7) the Hitomi historical case-study replay screen.

### Slide 13 — Future Enhancements
Keep the 6-box grid layout. Two content fixes:
- Remove or rename the "QUARTERMASTER Activation" box — this agent was deliberately removed from the current build; reviving it without explanation on a future-work slide looks inconsistent.
- "Live WebSocket Integration" box describes something **already built and running** (the real backend has a live `ws://` bridge) — remove this box or replace it with something genuinely future, since it's not actually a future item.

Keep as-is: Autonomous Learning Loop, Edge Computing vs. Ground Reasoning, Hot/Cold Storage Tiering, GPU Batch Inference for Constellation Scale.

### Slide 14 — Conclusion (currently blank — new content)

"AERO-ASTRA takes a satellite anomaly from detection to a physics-validated, human-approvable recovery plan in under 10 seconds — a documented, measured number, not a target.

It's built on real data (ESA OPS-SAT), real physics (a 6-subsystem coupled digital twin, Monte Carlo validated), and a hard architectural rule: language models reason, they never compute a safety number themselves.

What's not yet done: onboard deployment (ground-based by design — see Feasibility slide), and constellation-scale load testing beyond a single-satellite demo. We're presenting what we built, not what we plan to build."

### Slide 15 — Thank You
No change needed. Keep as-is.

---

## One more thing to tell Claude if it asks

If the design tool asks "should the Novelty slide have 5 or 6 boxes" — say 6, and it's fine if the layout shifts from a 2-3-2 grid to a 2x3 grid to fit the new RAG item. Visual balance matters less than not omitting your strongest, most concretely evidenced novelty claim.
