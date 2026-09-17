"""
AERO-ASTRA — Multi-Provider LLM Client
========================================
Provides a fallback chain of OpenAI-compatible providers.
When one provider fails with a quota/credit error (HTTP 402 or 429),
the next provider in the chain is tried automatically.

Provider chain (in priority order):
  1. MLX-LM (local, Apple Silicon)  — mlx_servers.py must be running
     ·  Sherlock → port 8080 (Llama 3.2 3B + 1B speculative draft)
     ·  Athena   → port 8081 (Llama 3.1 8B + 1B speculative draft)
  2. Ollama (local)  — no key needed (legacy fallback, always present)
  3. OpenRouter      — OPENROUTER_API_KEY (google/gemini-2.5-flash)
  4. NVIDIA NIM      — NVIDIA_API_KEY    (nvidia/nemotron-3-super-120b-a12b)

Environment variables:
  MLX_SHERLOCK_URL  — MLX Sherlock server (default: http://localhost:8080/v1)
  MLX_ATHENA_URL    — MLX Athena server   (default: http://localhost:8081/v1)
  OLLAMA_BASE_URL   — Ollama server URL   (default: http://localhost:11434/v1)
  OLLAMA_MODEL      — Model tag to use    (default: mistral-nemo:12b)
  OPENROUTER_API_KEY — OpenRouter key (optional, used as cloud fallback)
  NVIDIA_API_KEY    — NVIDIA NIM key   (optional, used as final fallback)

Usage:
    from backend.llm_client import build_clients, call_llm_with_fallback

    # Sherlock (port 8080)
    clients = build_clients(mlx_port=8080, ollama_model="llama3.2:3b")
    raw = call_llm_with_fallback(clients, messages, max_tokens=512, temperature=0.10)
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import httpx
from openai import OpenAI, APIStatusError

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Provider definitions
# ─────────────────────────────────────────────────────────────────────────────

# mlx_lm.server uses the FULL LOCAL PATH of the model directory as the model ID
# in its /v1/models response.  Any other string is treated as a HuggingFace repo
# ID and triggers a live download — so we must send the exact absolute path.
_MODELS_DIR = Path(__file__).resolve().parent / "models"
_PORT_TO_MODEL: dict[int, str] = {
    8080: str(_MODELS_DIR / "llama3.2-3b-4bit"),   # Sherlock TARGET
    8081: str(_MODELS_DIR / "llama3.1-8b-4bit"),   # Athena TARGET
}


@dataclass
class LLMProvider:
    name: str
    client: OpenAI
    model: str


def build_clients(
    ollama_model: str | None = None,
    openrouter_model: str = "google/gemini-2.5-flash",
    nvidia_model: str = "nvidia/nemotron-3-super-120b-a12b",
    nvidia_model_2: str = "deepseek-ai/deepseek-v4-flash-0731",
    mlx_port: int | None = None,
    mlx_model: str | None = None,  # auto-derived from port if None
) -> list[LLMProvider]:
    """
    Build and return the ordered fallback chain of providers.

    MLX-LM (Apple Silicon native + speculative decoding) is tried first when
    mlx_servers.py is running. Ollama is the local fallback. Cloud providers
    are used when both local options are unavailable.

    Provider priority:
      1. MLX-LM (local, speculative)  — mlx_port controls which agent server
      2. Ollama (local)               — ollama_model arg or OLLAMA_MODEL env var
      3. OpenRouter                   — OPENROUTER_API_KEY — google/gemini-2.5-flash
      4. NVIDIA NIM (primary)         — NVIDIA_API_KEY    — nemotron-3-super-120b-a12b
      5. NVIDIA NIM (fallback)        — NVIDIA_API_KEY    — deepseek-v4-flash-0731
    """
    providers: list[LLMProvider] = []

    # ── 1. MLX-LM (Apple Silicon native with speculative decoding) ────────────
    # mlx_lm.server exposes an OpenAI-compatible API on the given port.
    # IMPORTANT: mlx_lm.server uses the full local model path as the model ID.
    # Sending any other string causes the server to attempt a HuggingFace download.
    if mlx_port is not None:
        mlx_base = f"http://localhost:{mlx_port}/v1"
    else:
        mlx_base = os.environ.get("MLX_BASE_URL", "")

    if mlx_base:
        # Resolve model ID: caller-supplied path takes precedence, else derive from port.
        resolved_mlx_model = mlx_model or _PORT_TO_MODEL.get(mlx_port or 0, "")
        providers.append(LLMProvider(
            name=f"MLX-LM (port {mlx_port or 'env'})",
            client=OpenAI(
                base_url=mlx_base,
                api_key="mlx",   # mlx_lm.server ignores the key
            ),
            model=resolved_mlx_model,
        ))
        log.info("LLM provider registered: MLX-LM (port=%s, speculative decoding)", mlx_port)

    # ── 2. Ollama (local fallback) ────────────────────────────────────────────
    ollama_base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    resolved_ollama_model = ollama_model or os.environ.get("OLLAMA_MODEL", "mistral-nemo:12b")
    providers.append(LLMProvider(
        name="Ollama (local)",
        client=OpenAI(
            base_url=ollama_base,
            api_key="ollama",   # Ollama ignores the key but the client requires one
        ),
        model=resolved_ollama_model,
    ))
    log.info("LLM provider registered: Ollama local (model=%s, url=%s)", resolved_ollama_model, ollama_base)

    # ── 3. OpenRouter (cloud fallback) ────────────────────────────────────────
    or_key = os.environ.get("OPENROUTER_API_KEY")
    if or_key:
        providers.append(LLMProvider(
            name="OpenRouter",
            client=OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=or_key,
            ),
            model=openrouter_model,
        ))
        log.info("LLM provider registered: OpenRouter (model=%s)", openrouter_model)

    # ── 4. NVIDIA NIM (final cloud fallback) ──────────────────────────────────
    nv_key = os.environ.get("NVIDIA_API_KEY")
    if nv_key:
        providers.append(LLMProvider(
            name="NVIDIA NIM (nemotron-70b)",
            client=OpenAI(
                base_url="https://integrate.api.nvidia.com/v1",
                api_key=nv_key,
            ),
            model=nvidia_model,
        ))
        log.info("LLM provider registered: NVIDIA NIM primary (model=%s)", nvidia_model)

        providers.append(LLMProvider(
            name="NVIDIA NIM (deepseek-fallback)",
            client=OpenAI(
                base_url="https://integrate.api.nvidia.com/v1",
                api_key=nv_key,
            ),
            model=nvidia_model_2,
        ))
        log.info("LLM provider registered: NVIDIA NIM fallback (model=%s)", nvidia_model_2)

    return providers


# ─────────────────────────────────────────────────────────────────────────────
# Fallback-aware call
# ─────────────────────────────────────────────────────────────────────────────

# HTTP status codes that indicate quota/credit/gone errors — trigger fallback
# Also includes 503 (service unavailable) and 0 for connection errors (Ollama not running)
_FALLBACK_CODES = {402, 410, 429, 503}

# Timeout tuning:
#   MLX-LM: speculative decoding is much faster than Ollama — 60s is generous.
#   Ollama: mistral-nemo:12b at ~1 tok/s means long responses can take minutes.
#   Cloud:  OpenRouter/NVIDIA get 120s (network latency included).
_MLX_TOTAL_TIMEOUT    = int(os.environ.get("MLX_TIMEOUT",    "60"))
_OLLAMA_TOTAL_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "180"))
_CLOUD_TOTAL_TIMEOUT  = 120


def call_llm_with_fallback(
    providers: list[LLMProvider],
    messages: list[dict[str, str]],
    max_tokens: int = 2048,
    temperature: float = 0.1,
) -> str:
    """
    Call the LLM via the first available provider. On quota/credit errors
    (HTTP 402 or 429), fall back to the next provider in the chain.

    Args:
        providers:    Ordered list from build_clients().
        messages:     Full message list (system + user + assistant turns).
        max_tokens:   Maximum tokens to generate.
        temperature:  Sampling temperature.

    Returns:
        Raw text content of the model response (stripped).

    Raises:
        RuntimeError: If all providers fail.
    """
    last_exc: Exception | None = None

    for provider in providers:
        is_mlx   = provider.name.startswith("MLX")
        is_local = provider.name.startswith("Ollama") or is_mlx
        if is_mlx:
            total_timeout = _MLX_TOTAL_TIMEOUT
        elif provider.name.startswith("Ollama"):
            total_timeout = _OLLAMA_TOTAL_TIMEOUT
        else:
            total_timeout = _CLOUD_TOTAL_TIMEOUT
        # httpx.Timeout(total) sets a hard wall on the entire request—including
        # streaming reads—so slow local generation can't hang indefinitely.
        http_timeout = httpx.Timeout(total_timeout, connect=10.0)
        try:
            log.debug(
                "Calling %s (model=%s, timeout=%ds) ...",
                provider.name, provider.model, total_timeout,
            )
            response = provider.client.chat.completions.create(
                model=provider.model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=messages,
                timeout=http_timeout,
            )
            raw = (response.choices[0].message.content or "").strip()
            log.info("LLM call succeeded via %s", provider.name)
            return raw

        except APIStatusError as exc:
            if exc.status_code in _FALLBACK_CODES:
                log.warning(
                    "%s returned HTTP %d — falling back to next provider.",
                    provider.name,
                    exc.status_code,
                )
                last_exc = exc
                continue
            # Non-quota error — re-raise immediately
            raise

        except Exception as exc:
            # Catch connection errors (e.g. Ollama not running) and fall through
            log.warning(
                "%s unavailable (%s: %s) — falling back to next provider.",
                provider.name,
                type(exc).__name__,
                exc,
            )
            last_exc = exc
            continue

    raise RuntimeError(
        f"All LLM providers exhausted. Last error: {last_exc}"
    ) from last_exc
