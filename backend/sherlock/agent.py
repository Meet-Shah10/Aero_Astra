"""
SHERLOCK — Root-Cause Diagnosis Agent
Agent 3 of AERO-ASTRA | Root-Cause Diagnosis

Orchestrates the three-phase diagnosis pipeline:
  Phase 1 (Graph)       — deterministic, no LLM. Computes physically-valid
                          root cause candidates using the dependency graph.
  Phase 2 (LLM)         — constrained. Gemini (called directly via Google's
                          genai SDK) reasons over the candidate set and
                          observed telemetry to produce a JSON diagnosis.
  Phase 3 (Validation)  — deterministic, no LLM. Validates that the response
                          is (a) valid JSON, (b) passes Pydantic schema, and
                          (c) the claimed root cause is within the graph
                          candidate set. Retries with corrective reprompts on
                          any failure. Fails loudly if all retries exhaust.

Usage:
    from backend.sherlock import SherlockAgent, AnomalyEvent

    agent = SherlockAgent()  # uses GEMINI_API_KEY env var
    diagnosis = agent.diagnose(event)
    print(diagnosis.model_dump_json(indent=2))
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from openai import OpenAI
from pydantic import ValidationError

from .graph import SatelliteGraph, DEFAULT_CANDIDATE_DEPTH
from .prompts import (
    SYSTEM_PROMPT,
    build_user_prompt,
    build_json_parse_reprompt,
    build_schema_validation_reprompt,
    build_graph_validation_reprompt,
)
from .schemas import (
    AnomalyEvent,
    SherlockDiagnosis,
    SherlockDiagnosisError,
    SherlockGraphError,
    UrgencyLevel,
)
from .telemetry_interface import TelemetryProvider, PassthroughTelemetryProvider

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

# Routed through OpenRouter (OpenAI-compatible endpoint) -- base_url below
# points there, so the model id needs the "google/" provider prefix and the
# key needs to be an OpenRouter key (sk-or-v1-...), not a native Google
# AI Studio key. A native GEMINI_API_KEY will 401 against OpenRouter.
# Env var: OPENROUTER_API_KEY (GEMINI_API_KEY only works if it happens to
# also be a valid OpenRouter key, which a native AIzaSy... key is not).
DEFAULT_MODEL        = "google/gemini-2.5-flash"
DEFAULT_TEMPERATURE  = 0.1   # Near-deterministic — safety-relevant agent
DEFAULT_MAX_TOKENS   = 2048              # enough for full SherlockDiagnosis JSON
DEFAULT_MAX_RETRIES  = 3


# ─────────────────────────────────────────────────────────────────────────────
# SherlockAgent
# ─────────────────────────────────────────────────────────────────────────────

class SherlockAgent:
    """
    SHERLOCK: Root-Cause Diagnosis Agent.

    Instantiate once and call .diagnose() for each anomaly event.

    Args:
        api_key: OpenRouter API key. If None, reads OPENROUTER_API_KEY env var
                 (falls back to GEMINI_API_KEY, but that only works if it's
                 also a valid OpenRouter key).
        model: OpenRouter model id. Defaults to 'google/gemini-2.5-flash'.
        temperature: LLM sampling temperature (0.0–1.0). Default 0.1.
        max_retries: Maximum LLM call attempts before raising SherlockDiagnosisError.
        candidate_depth: Predecessor search depth in the dependency graph.
                         Default 1 (direct predecessors only). See graph.py
                         for detailed rationale on why this must stay low.
        telemetry_provider: Optional TelemetryProvider instance. If None,
                            uses PassthroughTelemetryProvider (reads telemetry
                            directly from the AnomalyEvent).
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = 'google/gemini-2.5-flash',
        temperature: float = DEFAULT_TEMPERATURE,
        max_retries: int = DEFAULT_MAX_RETRIES,
        candidate_depth: int = DEFAULT_CANDIDATE_DEPTH,
        telemetry_provider: TelemetryProvider | None = None,
    ) -> None:
        # OPENROUTER_API_KEY first (matches base_url below); GEMINI_API_KEY
        # as a fallback for anyone who's set that instead -- note this only
        # actually authenticates if it happens to be an OpenRouter-issued key.
        resolved_key = (
            api_key
            or os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("GEMINI_API_KEY")
        )
        if not resolved_key:
            raise EnvironmentError(
                "API key not found. Set GEMINI_API_KEY in environment "
                "or pass api_key= to SherlockAgent()."
            )

        self._client = OpenAI(api_key=resolved_key, base_url='https://openrouter.ai/api/v1')
        self._model = model
        self._temperature = temperature
        self._max_retries = max_retries
        self._candidate_depth = candidate_depth
        self._telemetry_provider = telemetry_provider
        self._graph = SatelliteGraph()

        log.info(
            "SherlockAgent initialised | model=%s | temp=%.2f | max_retries=%d | depth=%d | via Gemini API (direct)",
            model, temperature, max_retries, candidate_depth,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def diagnose(
        self,
        event: AnomalyEvent,
        telemetry_provider: TelemetryProvider | None = None,
    ) -> SherlockDiagnosis:
        """
        Diagnose the root cause of an anomaly event.

        Args:
            event: The anomaly event to diagnose (from SENTINEL or equivalent).
            telemetry_provider: Override the instance-level provider for this call.

        Returns:
            SherlockDiagnosis — validated, graph-consistent diagnosis.

        Raises:
            SherlockGraphError: If the flagged subsystem is not in the graph.
            SherlockDiagnosisError: If all retries are exhausted without a
                                    valid diagnosis. Failure is always loud.
        """
        log.info(
            "SHERLOCK diagnosing anomaly_id='%s' | subsystem=%s | severity=%s",
            event.anomaly_id, event.flagged_subsystem, event.severity.value,
        )

        # ── Phase 1: Graph — compute candidates ───────────────────────────────
        try:
            candidate_set = self._graph.get_candidates(
                event.flagged_subsystem, depth=self._candidate_depth
            )
        except ValueError as e:
            raise SherlockGraphError(str(e)) from e

        candidate_descriptions = self._graph.describe_candidates(
            event.flagged_subsystem, depth=self._candidate_depth
        )
        log.info(
            "Graph candidates for %s (depth=%d): %s",
            event.flagged_subsystem, self._candidate_depth, sorted(candidate_set),
        )

        # ── Telemetry context ─────────────────────────────────────────────────
        provider = telemetry_provider or self._telemetry_provider or PassthroughTelemetryProvider(event)
        snapshots = provider.get_snapshots_for_candidates(candidate_set)
        telemetry_context = provider.format_for_prompt(snapshots)

        # ── Build initial user prompt ─────────────────────────────────────────
        user_prompt = build_user_prompt(
            event=event,
            candidate_set=candidate_set,
            candidate_descriptions=candidate_descriptions,
            telemetry_context=telemetry_context,
        )

        # ── Phase 2 + 3: LLM call → Validate → Retry loop ───────────────────
        diagnosis_timestamp = datetime.now(timezone.utc)
        last_error: str = ""
        last_raw: str = ""
        messages: list[dict[str, str]] = [{"role": "user", "content": user_prompt}]

        for attempt in range(1, self._max_retries + 1):
            log.info("LLM call attempt %d/%d", attempt, self._max_retries)
            raw_response = self._call_llm(messages)
            last_raw = raw_response

            # Step A: JSON parse
            parsed_json, parse_error = self._try_parse_json(raw_response)
            if parse_error:
                last_error = f"JSON parse error: {parse_error}"
                log.warning("Attempt %d: %s", attempt, last_error)
                if attempt < self._max_retries:
                    reprompt = build_json_parse_reprompt(raw_response)
                    messages = self._append_reprompt(messages, raw_response, reprompt)
                continue

            # Step B: Pydantic schema validation (core fields only)
            validated, validation_error = self._try_validate_schema(parsed_json)
            if validation_error:
                last_error = f"Schema validation error: {validation_error}"
                log.warning("Attempt %d: %s", attempt, last_error)
                if attempt < self._max_retries:
                    reprompt = build_schema_validation_reprompt(raw_response, validation_error)
                    messages = self._append_reprompt(messages, raw_response, reprompt)
                continue

            # Step C: Graph candidate validation — THE CRITICAL SAFETY CHECK
            claimed_root = validated["primary_root_cause"]
            if claimed_root not in candidate_set:
                last_error = (
                    f"Graph validation failed: claimed root cause '{claimed_root}' "
                    f"not in candidate set {sorted(candidate_set)}"
                )
                log.warning("Attempt %d: %s", attempt, last_error)
                if attempt < self._max_retries:
                    reprompt = build_graph_validation_reprompt(
                        raw_response, claimed_root, candidate_set
                    )
                    messages = self._append_reprompt(messages, raw_response, reprompt)
                continue

            # ── All checks passed — build final SherlockDiagnosis ─────────────
            try:
                diagnosis = SherlockDiagnosis(
                    # Core LLM-filled fields
                    primary_root_cause=validated["primary_root_cause"],
                    causal_chain=validated["causal_chain"],
                    affected_subsystems=validated["affected_subsystems"],
                    confidence_score=validated["confidence_score"],
                    urgency=UrgencyLevel(validated["urgency"]),
                    time_to_critical_estimate_minutes=int(
                        validated["time_to_critical_estimate_minutes"]
                    ),
                    reasoning=validated["reasoning"],
                    # Programmatic audit fields
                    graph_candidate_set=sorted(candidate_set),
                    llm_attempts=attempt,
                    diagnosis_timestamp=diagnosis_timestamp,
                )
            except (ValidationError, ValueError) as e:
                # Shouldn't normally happen after passing Steps A-C, but be safe
                last_error = f"Final Pydantic construction failed: {e}"
                log.warning("Attempt %d: %s", attempt, last_error)
                if attempt < self._max_retries:
                    reprompt = build_schema_validation_reprompt(raw_response, str(e))
                    messages = self._append_reprompt(messages, raw_response, reprompt)
                continue

            log.info(
                "SHERLOCK diagnosis complete | attempt=%d | root_cause=%s | urgency=%s | confidence=%.2f",
                attempt,
                diagnosis.primary_root_cause,
                diagnosis.urgency.value,
                diagnosis.confidence_score,
            )
            return diagnosis

        # ── All retries exhausted — fail loudly ───────────────────────────────
        raise SherlockDiagnosisError(
            f"SHERLOCK exhausted all {self._max_retries} retry attempts for "
            f"anomaly '{event.anomaly_id}'. Last error: {last_error}",
            last_raw_response=last_raw,
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _call_llm(self, messages: list[dict[str, str]]) -> str:
        api_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
        response = self._client.chat.completions.create(
            model=self._model,
            messages=api_messages,
            temperature=self._temperature,
            max_tokens=DEFAULT_MAX_TOKENS,
        )
        raw = (response.choices[0].message.content or "").strip()
        log.debug("LLM raw response: %s", raw[:300])
        return raw

    def _try_parse_json(self, raw: str) -> tuple[dict[str, Any] | None, str | None]:
        """
        Attempt to parse raw string as JSON.
        Returns (parsed_dict, None) on success, (None, error_string) on failure.

        Also strips markdown code fences if the LLM wrapped JSON in ```json ... ```.
        """
        cleaned = raw.strip()
        # Strip ```json ... ``` or ``` ... ``` wrapping
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # Remove first line (```json or ```) and last line (```)
            inner_lines = lines[1:] if len(lines) > 1 else lines
            if inner_lines and inner_lines[-1].strip() == "```":
                inner_lines = inner_lines[:-1]
            cleaned = "\n".join(inner_lines).strip()

        try:
            parsed = json.loads(cleaned)
            if not isinstance(parsed, dict):
                return None, f"Expected JSON object, got {type(parsed).__name__}"
            return parsed, None
        except json.JSONDecodeError as e:
            return None, str(e)

    def _try_validate_schema(
        self, parsed: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str | None]:
        """
        Validate that the parsed JSON contains all required fields with correct types.
        Does NOT do full SherlockDiagnosis construction yet (audit fields not present).
        Returns (parsed, None) on success, (None, error_str) on failure.
        """
        required_fields = [
            "primary_root_cause",
            "causal_chain",
            "affected_subsystems",
            "confidence_score",
            "urgency",
            "time_to_critical_estimate_minutes",
            "reasoning",
        ]

        errors: list[str] = []

        for field_name in required_fields:
            if field_name not in parsed:
                errors.append(f"Missing required field: '{field_name}'")

        if errors:
            return None, "; ".join(errors)

        # Type checks
        if not isinstance(parsed.get("primary_root_cause"), str):
            errors.append("'primary_root_cause' must be a string")
        if not isinstance(parsed.get("causal_chain"), list):
            errors.append("'causal_chain' must be an array")
        elif not parsed["causal_chain"]:
            errors.append("'causal_chain' must be non-empty")
        if not isinstance(parsed.get("affected_subsystems"), list):
            errors.append("'affected_subsystems' must be an array")
        if not isinstance(parsed.get("confidence_score"), (int, float)):
            errors.append("'confidence_score' must be a number")
        elif not (0.0 <= float(parsed["confidence_score"]) <= 1.0):
            errors.append("'confidence_score' must be between 0 and 1")
        if parsed.get("urgency") not in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
            errors.append("'urgency' must be one of: CRITICAL, HIGH, MEDIUM, LOW")
        if not isinstance(parsed.get("time_to_critical_estimate_minutes"), (int, float)):
            errors.append("'time_to_critical_estimate_minutes' must be an integer")
        if not isinstance(parsed.get("reasoning"), str) or not parsed.get("reasoning"):
            errors.append("'reasoning' must be a non-empty string")

        # causal_chain[0] must equal primary_root_cause
        chain = parsed.get("causal_chain", [])
        root = parsed.get("primary_root_cause", "")
        if chain and root and chain[0] != root:
            errors.append(
                f"causal_chain[0] ('{chain[0]}') must equal primary_root_cause ('{root}')"
            )

        if errors:
            return None, "; ".join(errors)

        return parsed, None

    def _append_reprompt(
        self,
        messages: list[dict[str, str]],
        assistant_response: str,
        reprompt: str,
    ) -> list[dict[str, str]]:
        """
        Extend the conversation with the assistant's (failed) response and
        our corrective reprompt. This maintains conversation context across retries.
        """
        return messages + [
            {"role": "assistant", "content": assistant_response},
            {"role": "user", "content": reprompt},
        ]

    # ── Utility / introspection ───────────────────────────────────────────────

    def get_graph_summary(self) -> str:
        """Return a text summary of the satellite dependency graph."""
        return self._graph.summary()

    def get_candidates_for(
        self, flagged_subsystem: str, depth: int | None = None
    ) -> set[str]:
        """
        Convenience: get candidate set without running a full diagnosis.
        Useful for testing and graph inspection.
        """
        return self._graph.get_candidates(
            flagged_subsystem,
            depth=depth if depth is not None else self._candidate_depth,
        )
