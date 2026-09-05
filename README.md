# AERO-ASTRA

Autonomous multi-agent AI system for satellite fault detection, diagnosis, and recovery. Built for Smart Horizon 2026 (Team Serenitians, SH-DST-01).

**🏆 Hackathon Submission Details**
- **Presentation Deck (PPT) & Video Demo:** [Available on Google Drive](https://drive.google.com/drive/u/1/folders/12AR5bKhr_ckBZtmSmssf3yawUtxbmPjN)

Takes a satellite anomaly from detection to a physics-validated, human-approvable recovery plan in **under 10 seconds** (measured, not a target) — versus the 15-minute to 48-hour manual triage that's standard in real satellite operations today.


---

## Architecture

An 8-agent pipeline, each stage owning exactly one part of Detect → Diagnose → Simulate → Plan → Gate → Log:

| Agent | Role | How |
|---|---|---|
| **VITALS** | Continuous health scoring | Deterministic per-subsystem thresholds, runs every second regardless of active faults |
| **SENTINEL** | Anomaly detection | XGBoost (trained on real ESA OPSSAT-AD data) + physics-based spike filter + residual-correlation detector — 3 engines, no single one catches everything alone |
| **SHERLOCK** | Root-cause diagnosis | 18-edge NetworkX causal graph computes the physically valid candidate set (no LLM), Gemini 2.5 Flash reasons within that set, output is rejected/reprompted if it steps outside it |
| **ORACLE** | Recovery simulation | 100-run Monte Carlo per candidate action against a 6-subsystem coupled-ODE physics digital twin — zero LLM |
| **ATHENA** | Recovery planning | Gemini 2.5 Flash + RAG retrieval (ChromaDB, NASA/ESA FDIR handbook) turns ORACLE's winning simulation into a human-readable procedure |
| **GUARDIAN** | Safety gate | Deterministic 5-rule engine (time-to-critical, urgency, irreversibility, safety-score floor) — decides AUTONOMOUS_SAFED / AUTOMATED_GUARDED / MANUAL_INTERLOCK |
| **CHRONICLE** | Event log | Streams every agent decision over WebSocket, timestamped |
| **SCRIBE** | Audit runbook | Aggregates the full decision trail into an auditable record |

The one hard architectural rule: **LLMs reason, they never compute a safety number.** Anything that's actually a calculation (health scores, simulation outcomes, safety thresholds) is deterministic code. Gemini is only in the loop for causal narrative and procedure writing.

---

## Tech stack

- **Backend:** Python, FastAPI + Uvicorn, async WebSocket bridge
- **LLM:** Gemini 2.5 Flash, called directly via Google's `genai` SDK (not routed through a gateway)
- **ML:** XGBoost, scikit-learn — trained on real ESA OPSSAT-AD telemetry
- **Physics:** Custom NumPy-vectorized digital twin, 6 coupled subsystems
- **Retrieval:** ChromaDB — ATHENA's RAG pipeline over a NASA/ESA FDIR handbook
- **Frontend:** React 18 + Vite, Three.js / React-Three-Fiber (3D mission control), Framer Motion

---

## Running it locally

Two processes, both on one machine — no cloud infrastructure beyond the LLM API key.

### 1. Backend

```bash
python3 -m venv .venv
source .venv/bin/activate          # .venv\Scripts\activate on Windows
pip install -r backend/requirements.txt
```

Create `backend/.env`:
```
GEMINI_API_KEY=your-google-ai-studio-key
```
Get a key at [aistudio.google.com](https://aistudio.google.com/apikey). Note: the free tier caps at **20 requests/day per model** — each anomaly run costs at least 2 calls (SHERLOCK + ATHENA). Budget rehearsals accordingly, or upgrade to a paid tier before a live demo.

Run from the repo root (module path matters — `backend.api`, not `api`):
```bash
uvicorn backend.api:app --host 0.0.0.0 --port 8000 --reload
```

### 2. Frontend

```bash
npm install
npm run dev
```

Opens on `http://localhost:5173` (or the next free port) and connects to the backend's `ws://localhost:8000/ws`.

### Verifying it's actually working

The backend logs its own health on startup — look for:
```
SherlockAgent initialised | model=gemini-2.5-flash | ... | via Gemini API (direct)
AthenaAgent initialised | model=gemini-2.5-flash | ... | via Gemini API (direct)
```
If either of those lines is missing (or you see `EnvironmentError`/an auth error instead), the key isn't resolving — check `backend/.env` has `GEMINI_API_KEY` set. When the key is missing, the server still starts and streams telemetry/SENTINEL/VITALS, but SHERLOCK/ATHENA fall back to a clearly-labeled offline stub instead of crashing.

---

## Project structure

```
backend/
  api.py              — FastAPI + WebSocket bridge, orchestrates the full pipeline
  vitals/  sentinel/  sherlock/  oracle/  athena/  guardian/  — one package per agent
  simulator/          — the physics digital twin
  data/               — OPSSAT-AD, Mars Express (offline calibration only)
  evaluation_results.md — real measured metrics, not projections

src/
  App.jsx             — main dashboard, WebSocket client, scenario injection
  components/         — 3D viewer, VITALS gauges, ORACLE panels, agent detail pages

```

---

## Data sources — the honest version

No operational satellite publishes live fault telemetry — it's proprietary, often a security concern. The one real exception is **ESA's OPS-SAT** (launched 2019, an open experimentation platform) and its public **OPSSAT-AD** labeled anomaly dataset (Zenodo, DOI: 10.5281/zenodo.10624588), which SENTINEL's XGBoost engine is trained on. Mars Express thermal telemetry (ESA Planetary Science Archive) is used offline to calibrate the physics digital twin's thermal constants — not streamed live. Where neither dataset covers a fault type (thruster faults, power cascades), the physics twin fills the gap, calibrated against the real data available rather than invented from scratch.

