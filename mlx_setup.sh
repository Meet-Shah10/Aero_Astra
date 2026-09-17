#!/usr/bin/env bash
# ============================================================
#  AERO-ASTRA  ·  MLX Model Setup
#  One-time script — converts and caches model pairs for
#  speculative decoding with mlx-lm.
#
#  Usage: bash mlx_setup.sh
# ============================================================
set -e

MODELS_DIR="$(cd "$(dirname "$0")" && pwd)/backend/models"
mkdir -p "$MODELS_DIR"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  AERO-ASTRA  ·  MLX Model Setup"
echo "  Models will be saved to: $MODELS_DIR"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── Find the Python interpreter that has mlx_lm installed ────
MLX_PYTHON=""
for PY in \
  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13 \
  /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
  /usr/local/bin/python3 \
  python3 \
  python; do
  if command -v "$PY" &>/dev/null || [ -f "$PY" ]; then
    if "$PY" -c "import mlx_lm" 2>/dev/null; then
      MLX_PYTHON="$PY"
      echo "✅ Using Python: $(command -v $PY 2>/dev/null || echo $PY)"
      break
    fi
  fi
done

if [ -z "$MLX_PYTHON" ]; then
  echo "❌ Could not find a Python installation with mlx_lm."
  echo "   Run: pip3 install mlx-lm"
  echo "   (Make sure to use the same pip3 as your system Python, not Conda)"
  exit 1
fi

echo ""

# ── Helper function ───────────────────────────────────────────
download_model() {
  local label="$1"
  local hf_path="$2"
  local local_path="$3"

  echo "📥 $label"
  if [ ! -d "$local_path" ]; then
    "$MLX_PYTHON" -m mlx_lm.convert \
      --hf-path "$hf_path" \
      --mlx-path "$local_path"
    echo "  ✅ Saved to $local_path"
  else
    echo "  ⏭  Already exists, skipping."
  fi
}

# ──────────────────────────────────────────────────────────────
#  SHERLOCK pair: Llama 3.2 family (shared tokenizer)
# ──────────────────────────────────────────────────────────────
download_model \
  "[1/4] Sherlock TARGET — Llama 3.2 3B Instruct (4-bit)" \
  "mlx-community/Llama-3.2-3B-Instruct-4bit" \
  "$MODELS_DIR/llama3.2-3b-4bit"

download_model \
  "[2/4] Sherlock DRAFT  — Llama 3.2 1B Instruct (4-bit)" \
  "mlx-community/Llama-3.2-1B-Instruct-4bit" \
  "$MODELS_DIR/llama3.2-1b-4bit"

# ──────────────────────────────────────────────────────────────
#  ATHENA pair: Mistral family (shared tokenizer)
# ──────────────────────────────────────────────────────────────
download_model \
  "[3/4] Athena TARGET — Mistral Nemo 12B Instruct (4-bit)" \
  "mlx-community/Mistral-Nemo-Instruct-2407-4bit" \
  "$MODELS_DIR/mistral-nemo-4bit"

download_model \
  "[4/4] Athena DRAFT  — Mistral 7B Instruct v0.3 (4-bit)" \
  "mlx-community/Mistral-7B-Instruct-v0.3-4bit" \
  "$MODELS_DIR/mistral-7b-4bit"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ All models ready."
echo "  Next: python backend/mlx_servers.py"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
