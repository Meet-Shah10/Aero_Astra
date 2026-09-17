# 🛰️ Aero-Astra — Autonomous Satellite Fault Management System

A real-time, multi-agent AI system for satellite anomaly detection, root-cause diagnosis, and autonomous mitigation planning. Built on a **FastAPI** backend with a **React/Vite** frontend, it orchestrates five specialist AI agents over a live WebSocket telemetry stream.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        React / Vite  (port 5173)                │
│  Dashboard · Agent Console · Oracle 3-D View · Sandbox         │
└────────────────────┬────────────────────────────────────────────┘
                     │  WebSocket  ws://localhost:8000/ws
┌────────────────────▼────────────────────────────────────────────┐
│                   FastAPI Backend  (port 8000)                   │
│                                                                  │
│  SENTINEL  ──►  SHERLOCK  ──►  ORACLE  ──►  ATHENA  ──►  GUARDIAN│
│  (anomaly      (root-cause     (MC sim)    (mitigation  (safety  │
│   detect)       diagnosis)                  planning)    gate)   │
│                                                                  │
│  CHRONICLE (always-on audit log)   SCRIBE (runbook compiler)    │
└──────────┬──────────────────────────────────┬───────────────────┘
           │  OpenAI-compat REST               │  OpenAI-compat REST
  ┌────────▼────────┐                ┌─────────▼─────────┐
  │  MLX-LM :8080   │                │  MLX-LM :8081     │
  │  (SHERLOCK LLM) │                │  (ATHENA LLM)     │
  └─────────────────┘                └───────────────────┘
        Llama 3.2 3B-4bit                Llama 3.1 8B-4bit
      + Llama 3.2 1B draft            (standard inference)
     (speculative decoding)
```

Agents are **manually activated** from the UI — SENTINEL and CHRONICLE run continuously; SHERLOCK, ORACLE, and ATHENA fire only when the operator clicks **▶ Activate** on their respective pages.

---

## Prerequisites

### Hardware
| Requirement | Minimum | Recommended |
|---|---|---|
| CPU | Any modern x86-64 or ARM64 | Apple Silicon (M1/M2/M3/M4) |
| RAM | 8 GB | 16 GB |
| Disk | 20 GB free | 40 GB free |
| GPU | — | Apple Silicon unified memory (for MLX) |

> **Note:** MLX local inference only works on **Apple Silicon Macs**. On other hardware the backend automatically falls back to **Ollama**, **OpenRouter**, or **NVIDIA NIM** (see LLM Providers below).

### Software

| Tool | Version | Install |
|---|---|---|
| Python | 3.11 – 3.13 | [python.org](https://python.org) or `brew install python` |
| Node.js | 18+ | [nodejs.org](https://nodejs.org) or `brew install node` |
| npm | 9+ | Bundled with Node.js |
| git | any | `brew install git` |

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/Meet-Shah10/Aero_Astra.git
cd Aero_Astra
```

### 2. Python environment

```bash
# Create and activate a virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install Python dependencies
pip install -r requirements.txt
```

### 3. Node / Frontend dependencies

```bash
npm install
```

### 4. Environment variables

Create a `.env` file in the project root. Only the providers you actually want to use need keys — the backend tries them in order and falls back automatically.

```env
# ── OpenRouter (cloud LLM fallback) ──────────────────────────────
OPENROUTER_API_KEY=sk-or-...

# ── NVIDIA NIM (optional cloud fallback) ─────────────────────────
NVIDIA_API_KEY=nvapi-...

# ── Ollama (local, no key needed — install from https://ollama.ai) ──
# No key required. Run: ollama pull llama3.2:3b && ollama pull mistral-nemo:12b
```

> At least one provider must be reachable. For a fully **offline** setup, install Ollama and pull the models — no API keys needed.

### 5. LLM Providers (choose one or more)

The backend tries providers in this priority order:

| Priority | Provider | When to use |
|---|---|---|
| 1 | **MLX-LM** (local, Apple Silicon) | Fastest; requires model download (Step 6) |
| 2 | **Ollama** (local, any OS) | Good offline option; no GPU required |
| 3 | **OpenRouter** | Cloud fallback; needs `OPENROUTER_API_KEY` |
| 4 | **NVIDIA NIM** | Cloud fallback; needs `NVIDIA_API_KEY` |

#### Option A — MLX local inference (Apple Silicon only)

Download quantised model weights (~2–5 GB each):

```bash
bash mlx_setup.sh
```

Or manually with the MLX CLI:

```bash
pip install mlx-lm
mlx_lm.convert --hf-path meta-llama/Llama-3.2-3B-Instruct -q --q-bits 4 \
    --mlx-path backend/models/llama3.2-3b-4bit
mlx_lm.convert --hf-path meta-llama/Llama-3.2-1B-Instruct -q --q-bits 4 \
    --mlx-path backend/models/llama3.2-1b-4bit
mlx_lm.convert --hf-path meta-llama/Llama-3.1-8B-Instruct -q --q-bits 4 \
    --mlx-path backend/models/llama3.1-8b-4bit
```

#### Option B — Ollama (any OS)

```bash
# Install Ollama from https://ollama.ai, then:
ollama pull llama3.2:3b        # for SHERLOCK
ollama pull mistral-nemo:12b   # for ATHENA
```

---

## Running the System

Open **three terminal tabs**:

### Tab 1 — MLX inference servers (Apple Silicon only, skip for Ollama/cloud)

```bash
python backend/mlx_servers.py
# Starts SHERLOCK server on :8080 and ATHENA server on :8081
```

### Tab 2 — FastAPI backend

```bash
python backend/api.py
# Runs on http://localhost:8000
# WebSocket: ws://localhost:8000/ws
```

### Tab 3 — React frontend

```bash
npm run dev
# Opens at http://localhost:5173
```

Navigate to **http://localhost:5173** in your browser.

---

## Usage Flow

1. **Launch** — the dashboard loads and the telemetry replay begins streaming.
2. **Wait for SENTINEL** — within ~6 seconds, SENTINEL detects the injected fault. The stream **freezes** at the fault frame and the agent console highlights.
3. **Click SHERLOCK** — navigate to the SHERLOCK agent page and click **▶ Activate SHERLOCK**. The LLM diagnoses the root cause. The stream resumes automatically.
4. **Click ATHENA** — navigate to the ATHENA page and click **▶ Activate ATHENA**. ORACLE runs a Monte-Carlo simulation, then ATHENA generates a mitigation plan.
5. **GUARDIAN** fires automatically after SHERLOCK — it classifies the severity tier (`AUTOMATED_GUARDED`, `MANUAL_INTERLOCK`, or `AUTONOMOUS_SAFED`).
6. **Approve & execute** — on the GUARDIAN page, approve the plan. SCRIBE compiles the audit runbook, which can be downloaded as a `.txt` file.

---

## Project Structure

```
Aero_Astra/
├── backend/
│   ├── api.py                  # FastAPI app — WebSocket, endpoints, replay loop
│   ├── mlx_servers.py          # Launches MLX-LM inference servers
│   ├── llm_client.py           # Multi-provider LLM client with fallback chain
│   ├── sherlock/               # SHERLOCK agent (root-cause diagnosis)
│   │   ├── agent.py
│   │   ├── prompts.py
│   │   └── graph.py            # Satellite dependency graph (6 nodes, 18 edges)
│   ├── athena/                 # ATHENA agent (mitigation planning + RAG)
│   │   ├── agent.py
│   │   └── rag/                # NASA-HDBK-1002 vectorstore
│   ├── sentinel/               # SENTINEL anomaly detectors (Engine A/B/C)
│   ├── oracle/                 # ORACLE Monte-Carlo simulator
│   ├── simulator/              # Physics-based satellite telemetry engine
│   ├── replay/                 # Pre-recorded telemetry playlist (playlist.json)
│   └── models/                 # Sentinel ML models + MLX weights (gitignored)
├── src/
│   ├── App.jsx                 # Root React component, WebSocket state machine
│   ├── components/
│   │   ├── AgentDetailPage.jsx # Per-agent detail views + activation buttons
│   │   ├── oracle/             # 3-D orbital visualiser
│   │   └── sandbox/            # Simulation sandbox (digital twin)
│   └── index.css
├── public/
├── requirements.txt
├── package.json
└── vite.config.js
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Out of diskspace` on `git add` | Free disk space; MLX models can be 5–10 GB each |
| Screen goes black on agent click | Ensure backend is running; check browser console for JS errors |
| SHERLOCK button not appearing | Wait for SENTINEL to fire (~6 s after backend start) |
| `LLM call failed` in backend logs | Check `.env` keys; or start Ollama as a fallback |
| ChromaDB collection empty | Delete `backend/athena/rag/vectorstore/` and restart backend to rebuild |
| Port 8080/8081 already in use | Kill any leftover `mlx_lm.server` processes: `pkill -f mlx_lm` |

---

## License

MIT
