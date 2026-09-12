"""
AERO-ASTRA — Multi-Provider LLM Client
========================================
Provides a fallback chain of OpenAI-compatible providers.
When one provider fails with a quota/credit error (HTTP 402 or 429),
the next provider in the chain is tried automatically.

Provider chain (in priority order):
  1. Ollama (local)  — no key needed     (mistral-nemo:12b, fully offline)
  2. OpenRouter      — OPENROUTER_API_KEY (google/gemini-2.5-flash)
  3. NVIDIA NIM      — NVIDIA_API_KEY    (nvidia/nemotron-3-super-120b-a12b)

Environment variables:
  OLLAMA_BASE_URL   — Ollama server URL (default: http://localhost:11434/v1)
  OLLAMA_MODEL      — Model tag to use  (default: mistral-nemo:12b)
  OPENROUTER_API_KEY — OpenRouter key (optional, used as cloud fallback)
  NVIDIA_API_KEY    — NVIDIA NIM key   (optional, used as final fallback)

Usage:
    from backend.llm_client import build_clients, call_llm_with_fallback

    clients = build_clients()
    raw = call_llm_with_fallback(clients, messages, max_tokens=2048, temperature=0.1)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx
from openai import OpenAI, APIStatusError

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Provider definitions
# ─────────────────────────────────────────────────────────────────────────────

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
) -> list[LLMProvider]:
    """
    Build and return the ordered fallback chain of providers.

    Ollama (local) is always tried first if the Ollama server is reachable.
    Cloud providers are used as fallbacks when Ollama is unavailable.

    Provider priority:
      1. Ollama (local)  — ollama_model arg or OLLAMA_MODEL env var (default: mistral-nemo:12b)
      2. OpenRouter      — OPENROUTER_API_KEY   — google/gemini-2.5-flash
      3. NVIDIA NIM      — NVIDIA_API_KEY       — nemotron-3-super-120b-a12b
      4. NVIDIA NIM      — NVIDIA_API_KEY       — deepseek-v4-flash-0731 (fallback)
    """
    providers: list[LLMProvider] = []

    # ── 1. Ollama (local, offline-first) ─────────────────────────────────────
    # Ollama exposes an OpenAI-compatible API — no real key required.
    # We probe it lazily; if the server isn't running, call_llm_with_fallback
    # will catch the connection error and move to the next provider.
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

    # ── 2. OpenRouter (cloud fallback) ────────────────────────────────────────
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

    # ── 3. NVIDIA NIM (final cloud fallback) ──────────────────────────────────
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

# Hard wall for local Ollama calls (seconds). mistral-nemo:12b generates at
# ~1 tok/s on M-series Apple Silicon, so 768 max_tokens ≈ 13 minutes worst-case.
# Default 180s covers the typical 100-200 token response; set OLLAMA_TIMEOUT
# in env to tune without a code change.
# Cloud providers (OpenRouter, NVIDIA NIM) get a generous 120s instead.
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
        is_local = provider.name.startswith("Ollama")
        total_timeout = _OLLAMA_TOTAL_TIMEOUT if is_local else _CLOUD_TOTAL_TIMEOUT
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
