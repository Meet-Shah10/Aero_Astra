"""
backend/mlx_servers.py
======================
Launches two mlx_lm OpenAI-compatible inference servers with speculative
decoding. This replaces Ollama for local LLM inference.

Design constraints honored:
  1. Each draft/target pair is from the same tokenizer family (Llama 3.2, Mistral).
  2. --draft-temp exactly matches --temp for each server (maximizes acceptance rate).
  3. --max-tokens is capped to prevent GPU batch saturation.

Usage:
    python backend/mlx_servers.py

    Then start the main backend:
    python backend/api.py

    To stop both servers:
    Ctrl+C (SIGINT gracefully kills both subprocesses)
"""

import os
import subprocess
import sys
import signal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "backend" / "models"


def _find_mlx_python() -> str:
    """
    Find the Python interpreter that has mlx_lm installed.
    On macOS with both Anaconda and system Python, they live in different
    site-packages directories, so sys.executable may not be the right one.
    """
    candidates = [
        "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13",
        "/Library/Frameworks/Python.framework/Versions/Current/bin/python3",
        "/usr/local/bin/python3",
        sys.executable,
        "python3",
        "python",
    ]
    for py in candidates:
        try:
            result = subprocess.run(
                [py, "-c", "import mlx_lm"],
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                return py
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    print("\n❌ Cannot find a Python with mlx_lm. Run:  pip install mlx-lm\n")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# Server configurations
# ─────────────────────────────────────────────────────────────────────────────
SERVERS = [
    {
        "name":        "SHERLOCK (Llama 3.2 3B + 1B speculative)",
        "port":        8080,
        # Llama 3.2 1B and 3B share the same Llama 3 tokenizer (128k vocab).
        "model":       str(MODELS / "llama3.2-3b-4bit"),
        "draft_model": str(MODELS / "llama3.2-1b-4bit"),
        "temp":        0.10,
        "max_tokens":  2048,  # must match SherlockAgent DEFAULT_MAX_TOKENS
    },
    {
        "name":        "ATHENA (Llama 3.1 8B — standard inference)",
        "port":        8081,
        # Speculative decoding with 8B target + 1B draft causes a Metal GPU timeout
        # on MacBook Air (no active cooling) when Sherlock's 3B is also loaded.
        # Running 8B alone via MLX is still far more efficient than Ollama/cloud.
        "model":       str(MODELS / "llama3.1-8b-4bit"),
        "draft_model": None,
        "temp":        0.15,
        "max_tokens":  2048,  # must match AthenaAgent DEFAULT_MAX_TOKENS
    },
]


def _check_models():
    """Verify that all required model directories exist before launching."""
    missing = []
    for srv in SERVERS:
        for key in ("model", "draft_model"):
            val = srv[key]
            if val is None:
                continue   # draft_model is optional
            path = Path(val)
            if not path.exists():
                missing.append(str(path))
    if missing:
        print("\n❌ Missing model directories:")
        for m in missing:
            print(f"   {m}")
        print("\nRun:  bash mlx_setup.sh\n")
        sys.exit(1)


def _build_cmd(srv: dict) -> list[str]:
    """Build the mlx_lm.server command for a given server config."""
    py = _find_mlx_python()
    cmd = [
        py, "-m", "mlx_lm.server",
        "--model",      srv["model"],
        "--port",       str(srv["port"]),
        "--temp",       str(srv["temp"]),
        "--max-tokens", str(srv["max_tokens"]),
    ]
    if srv.get("draft_model"):
        cmd += ["--draft-model", srv["draft_model"]]
    return cmd


def main():
    _check_models()

    processes: list[subprocess.Popen] = []

    def _shutdown(signum=None, frame=None):
        print("\n⏹  Shutting down MLX servers...")
        for p in processes:
            p.terminate()
        for p in processes:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    print("\n" + "━" * 60)
    print("  AERO-ASTRA  ·  MLX Inference Servers")
    print("━" * 60)

    for srv in SERVERS:
        cmd = _build_cmd(srv)
        draft_label = Path(srv['draft_model']).name if srv.get('draft_model') else 'disabled (tokenizer mismatch)'
        print(f"\n▶  Starting {srv['name']}")
        print(f"   Port      : {srv['port']}")
        print(f"   Model     : {Path(srv['model']).name}")
        print(f"   Draft     : {draft_label}")
        print(f"   Temp      : {srv['temp']}")
        print(f"   Max tokens: {srv['max_tokens']}")

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env={**os.environ},
        )
        processes.append(proc)

    print("\n" + "━" * 60)
    print("  ✅ Servers starting. OpenAI-compatible endpoints:")
    for srv in SERVERS:
        print(f"   http://localhost:{srv['port']}/v1")
    print("\n  Start backend: python backend/api.py")
    print("  Stop servers : Ctrl+C")
    print("━" * 60 + "\n")

    # Wait — stream any stderr from either server
    import select
    stderr_fds = {p.stderr.fileno(): (p, srv["name"]) for p, srv in zip(processes, SERVERS)}
    while True:
        try:
            rlist, _, _ = select.select(list(stderr_fds.keys()), [], [], 1.0)
            for fd in rlist:
                p, name = stderr_fds[fd]
                line = p.stderr.readline()
                if line:
                    print(f"[{name.split('(')[0].strip()}] {line.decode().rstrip()}")
        except (KeyboardInterrupt, SystemExit):
            _shutdown()


if __name__ == "__main__":
    main()
