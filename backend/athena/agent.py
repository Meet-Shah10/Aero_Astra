"""
AERO-ASTRA — ATHENA Recovery Planning Agent
=============================================
Agent 5 of AERO-ASTRA | Recovery Plan Synthesis

Orchestrates the three-phase planning pipeline:
  Phase 1 (LLM)         — ATHENA calls Gemini (directly via Google's genai
                           SDK) with SHERLOCK's diagnosis + ORACLE's
                           validated rankings + RECOVERY_CATALOG
                           descriptions. The LLM produces
                           reasoning_cot, overall_reasoning, and 2–3 options
                           using the AthenaLLMOption schema (no safety_score,
                           no blended_rank — Two-Schema Pattern).

  Phase 2 (Validation)  — Deterministic, no LLM.
                           A: JSON parse (strip markdown fences)
                           B: Schema validation (required fields, value ranges)
                           C: Anti-hallucination — every action_name in the
                              response must appear in oracle_response.results.
                              This is the ATHENA-equivalent of SHERLOCK's
                              graph-candidate check.

  Phase 3 (Assembly)    — Deterministic, no LLM.
                           Inject real safety_score from ORACLE for each option.
                           Compute blended_rank via scoring.blended_rank().
                           Set is_irreversible from scoring.IRREVERSIBLE_ACTIONS.
                           Sort options by blended_rank descending.
                           Build RecoveryPlan.

ATHENA never re-runs simulations or invents recovery actions. It reasons only
over the actions ORACLE already validated and passes ORACLE's safety scores
through unchanged.

Usage:
    from backend.athena import AthenaAgent

    agent = AthenaAgent()
    plan = agent.plan(
        sherlock_diagnosis=diagnosis,
        oracle_response=oracle_resp,
        constraints=MissionConstraints(notes="Ground pass in 8 min"),
    )
    print(plan.model_dump_json(indent=2))
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from openai import OpenAI

from backend.oracle.schemas import OracleResponse
from backend.sherlock.schemas import SherlockDiagnosis

from .prompts import (
    SYSTEM_PROMPT,
    build_hallucinated_action_reprompt,
    build_json_parse_reprompt,
    build_schema_validation_reprompt,
    build_user_prompt,
)
from .rag.pipeline import get_pipeline as _get_rag_pipeline
from .schemas import (
    AthenaError,
    MissionConstraints,
    OperatorEffort,
    RecoveryOption,
    RecoveryPlan,
)
from .scoring import blended_rank, is_action_irreversible

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

# Called directly against Google's Gemini API (google-genai SDK) — not
# routed through OpenRouter. Model id is the native Gemini name.
# Env var: GEMINI_API_KEY
DEFAULT_MODEL       = "gemini-2.5-flash"
DEFAULT_TEMPERATURE = 0.15
DEFAULT_MAX_RETRIES = 3

# 0.15: slightly above SHERLOCK's 0.1 — procedure prose benefits from natural
# variation, but this is still safety-relevant; must stay below 0.2.
DEFAULT_TEMPERATURE = 0.15

# Longer than SHERLOCK: 3 options × ~5 steps + reasoning_cot + narratives
DEFAULT_MAX_TOKENS  = 2048
DEFAULT_MAX_RETRIES = 3

# Valid operator effort strings (for schema validation)
_VALID_EFFORTS = {"low", "medium", "high"}


# ─────────────────────────────────────────────────────────────────────────────
# AthenaAgent
# ─────────────────────────────────────────────────────────────────────────────


class AthenaAgent:
    """
    ATHENA: Recovery Planning Agent.

    Instantiate once and call .plan() for each diagnosis+oracle pair.

    Args:
        api_key:     Gemini API key. If None, reads GEMINI_API_KEY env var.
        model:       Native Gemini model id. Defaults to 'gemini-2.5-flash'.
        temperature: LLM sampling temperature (0.0–1.0). Default 0.15.
        max_retries: Maximum LLM call attempts before raising AthenaError.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = 'google/gemini-2.5-flash',
        temperature: float = DEFAULT_TEMPERATURE,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        # Use GEMINI_API_KEY
        resolved_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not resolved_key:
            raise EnvironmentError(
                "API key not found. Set GEMINI_API_KEY in environment "
                "or pass api_key= to AthenaAgent()."
            )

        self._client = OpenAI(api_key=resolved_key, base_url='https://openrouter.ai/api/v1')
        self._model       = model
        self._temperature = temperature
        self._max_retries = max_retries

        # ── RAG pipeline (warm singleton, non-blocking) ────────────────────
        # Initialise the shared pipeline instance and ensure the vectorstore is
        # ready. If the vectorstore is empty, ensure_ready() auto-seeds from the
        # synthetic FDIR knowledge base. The entire init is wrapped so a missing
        # API key or vectorstore never prevents ATHENA from starting.
        try:
            self._rag = _get_rag_pipeline()
            if not self._rag.ensure_ready(auto_seed=True):
                log.warning(
                    "RAG vectorstore unavailable — ATHENA will plan without handbook context."
                )
                self._rag = None
            else:
                log.info(
                    "RAG pipeline ready | docs=%d",
                    self._rag._collection.count() if self._rag._collection else 0,
                )
        except Exception as exc:
            log.warning("RAG initialisation failed (%s) — continuing without RAG.", exc)
            self._rag = None

        log.info(
            "AthenaAgent initialised | model=%s | temp=%.2f | max_retries=%d | rag=%s | via Gemini API (direct)",
            model, temperature, max_retries, "enabled" if self._rag else "disabled",
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def plan(
        self,
        sherlock_diagnosis: SherlockDiagnosis,
        oracle_response: OracleResponse,
        constraints: MissionConstraints | None = None,
    ) -> RecoveryPlan:
        """
        Produce a validated, ranked RecoveryPlan.

        Args:
            sherlock_diagnosis: SHERLOCK's validated root-cause diagnosis.
            oracle_response:    ORACLE's ranked and Monte Carlo-validated results.
            constraints:        Optional operator mission constraints (qualitative).

        Returns:
            RecoveryPlan — validated, anti-hallucination-verified, sorted by
            blended_rank descending.

        Raises:
            AthenaError: If all retries are exhausted without a valid plan.
                         Failure is always loud, never silent.
        """
        log.info(
            "ATHENA planning | fault=%s | oracle_actions=%d | urgency=%s",
            oracle_response.fault_name,
            len(oracle_response.results),
            sherlock_diagnosis.urgency.value,
        )

        # Build ORACLE lookup: action_name → safety_score
        # This is the ground truth used in Phase 3 injection and Phase C check.
        oracle_lookup: dict[str, float] = {
            r.action_name: r.safety_score for r in oracle_response.results
        }
        valid_action_names: set[str] = set(oracle_lookup.keys())

        # ── RAG retrieval: query vectorstore with fault context ───────────────
        # Build a natural-language query from SHERLOCK's diagnosis fields so
        # the embedding search targets the most relevant FDIR handbook passages.
        fdir_context: str = ""
        if self._rag is not None:
            try:
                rag_query = " ".join(filter(None, [
                    sherlock_diagnosis.primary_root_cause,
                    " ".join(sherlock_diagnosis.affected_subsystems),
                    " ".join(sherlock_diagnosis.causal_chain),
                    sherlock_diagnosis.urgency.value,
                ]))
                fdir_context = self._rag.retrieve(rag_query)
                log.info(
                    "RAG retrieved %d chars of FDIR context | query=%r",
                    len(fdir_context),
                    rag_query[:80],
                )
            except Exception as exc:
                log.warning("RAG retrieval failed (%s) — proceeding without context.", exc)
                fdir_context = ""

        # Build initial user prompt (includes RAG context when available)
        user_prompt = build_user_prompt(
            sherlock_diagnosis, oracle_response, constraints, fdir_context=fdir_context
        )

        # ── Phase 1+2+3: LLM call → Validate → Retry loop ─────────────────────
        plan_timestamp = datetime.now(timezone.utc)
        last_error: str = ""
        last_raw: str = ""
        messages: list[dict[str, str]] = [{"role": "user", "content": user_prompt}]

        for attempt in range(1, self._max_retries + 1):
            log.info("ATHENA LLM call attempt %d/%d", attempt, self._max_retries)
            raw = self._call_llm(messages)
            last_raw = raw

            # ── Phase A: JSON parse ──────────────────────────────────────────
            parsed, parse_err = self._try_parse_json(raw)
            if parse_err:
                last_error = f"JSON parse error: {parse_err}"
                log.warning("Attempt %d: %s", attempt, last_error)
                if attempt < self._max_retries:
                    reprompt = build_json_parse_reprompt(raw)
                    messages = self._append_reprompt(messages, raw, reprompt)
                continue

            # ── Phase B: Schema validation ───────────────────────────────────
            validation_err = self._try_validate_schema(parsed)
            if validation_err:
                last_error = f"Schema validation error: {validation_err}"
                log.warning("Attempt %d: %s", attempt, last_error)
                if attempt < self._max_retries:
                    reprompt = build_schema_validation_reprompt(raw, validation_err)
                    messages = self._append_reprompt(messages, raw, reprompt)
                continue

            # ── Phase C: Anti-hallucination — action name check ──────────────
            # The Two-Schema Pattern means the LLM never outputs safety_score,
            # so there is no score to mismatch. The only domain-specific check
            # needed is: every action_name must be in oracle_response.results.
            llm_options: list[dict[str, Any]] = parsed["options"]
            bad_names = [
                opt["action_name"]
                for opt in llm_options
                if opt["action_name"] not in valid_action_names
            ]
            if bad_names:
                last_error = (
                    f"Anti-hallucination check failed: action names not in ORACLE results: "
                    f"{bad_names}. Valid: {sorted(valid_action_names)}"
                )
                log.warning("Attempt %d: %s", attempt, last_error)
                if attempt < self._max_retries:
                    reprompt = build_hallucinated_action_reprompt(
                        raw, bad_names, list(valid_action_names)
                    )
                    messages = self._append_reprompt(messages, raw, reprompt)
                continue

            # ── Phase 3: Schema Assembly — inject real values ─────────────────
            # All checks passed. Now merge AthenaLLMOption with ORACLE data.
            try:
                options: list[RecoveryOption] = []
                for opt in llm_options:
                    real_safety = oracle_lookup[opt["action_name"]]
                    rank = blended_rank(
                        safety_score=real_safety,
                        effectiveness_score=float(opt["effectiveness_score"]),
                        operator_effort=opt["operator_effort"],
                    )
                    options.append(RecoveryOption(
                        action_name=opt["action_name"],
                        procedure_steps=opt["procedure_steps"],
                        safety_score=real_safety,          # from ORACLE — not LLM
                        effectiveness_score=float(opt["effectiveness_score"]),
                        operator_effort=OperatorEffort(opt["operator_effort"]),
                        predicted_outcome=opt["predicted_outcome"],
                        contra_indications=opt.get("contra_indications", []),
                        blended_rank=rank,                 # computed here — not LLM
                        is_irreversible=is_action_irreversible(opt["action_name"]),  # lookup — not LLM
                    ))

                # Sort by blended_rank descending — deterministic, not LLM order
                options.sort(key=lambda o: o.blended_rank, reverse=True)

                recovery_plan = RecoveryPlan(
                    recommended_action=options[0].action_name,
                    options=options,
                    reasoning_cot=parsed.get("reasoning_cot", []),
                    overall_reasoning=parsed.get("overall_reasoning", ""),
                    llm_attempts=attempt,
                    generated_at=plan_timestamp,
                    diagnosis_context=sherlock_diagnosis.reasoning,
                )
            except Exception as e:
                # Shouldn't normally happen after passing Phases A–C, but be safe
                last_error = f"Plan assembly failed: {e}"
                log.warning("Attempt %d: %s", attempt, last_error)
                if attempt < self._max_retries:
                    reprompt = build_schema_validation_reprompt(raw, str(e))
                    messages = self._append_reprompt(messages, raw, reprompt)
                continue

            log.info(
                "ATHENA plan complete | attempt=%d | recommended=%s | options=%d | top_rank=%.4f",
                attempt,
                recovery_plan.recommended_action,
                len(options),
                options[0].blended_rank,
            )
            return recovery_plan

        # ── All retries exhausted — fail loudly ───────────────────────────────
        raise AthenaError(
            f"ATHENA exhausted all {self._max_retries} retry attempts. "
            f"Last error: {last_error}",
            last_raw_response=last_raw,
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _call_llm(self, messages: list[dict[str, str]]) -> str:
        """
        Make one call directly against the Gemini API. Returns raw text.

        System prompt is passed via system_instruction. Subsequent messages
        carry the conversation history across retries so the model sees
        exactly what it returned previously — same pattern as
        SherlockAgent._call_llm ('assistant' maps to Gemini's 'model' role).
        """
        contents = [
            genai_types.Content(
                role="model" if m["role"] == "assistant" else "user",
                parts=[genai_types.Part(text=m["content"])],
            )
            for m in messages
        ]
        response = self._client.models.generate_content(
            model=self._model,
            contents=contents,
            config=genai_types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=self._temperature,
                max_output_tokens=DEFAULT_MAX_TOKENS,
            ),
        )
        raw = (response.text or "").strip()
        # Strip markdown code fences that Gemini often wraps JSON in
        if raw.startswith("```"):
            # Remove opening fence (```json or ```) and closing fence (```)
            raw = raw.split("\n", 1)[-1]         # drop first line (```json)
            if raw.endswith("```"):
                raw = raw[: raw.rfind("```")]    # drop closing ```
            raw = raw.strip()
        log.debug("ATHENA LLM raw response: %s", raw[:400])
        return raw

    def _try_parse_json(
        self, raw: str
    ) -> tuple[dict[str, Any] | None, str | None]:
        """
        Attempt to parse raw string as JSON.
        Returns (parsed_dict, None) on success, (None, error_string) on failure.
        Strips markdown code fences if the LLM wrapped JSON in ```json ... ```.
        """
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            inner = lines[1:] if len(lines) > 1 else lines
            if inner and inner[-1].strip() == "```":
                inner = inner[:-1]
            cleaned = "\n".join(inner).strip()

        try:
            parsed = json.loads(cleaned)
            if not isinstance(parsed, dict):
                return None, f"Expected JSON object, got {type(parsed).__name__}"
            return parsed, None
        except json.JSONDecodeError as e:
            return None, str(e)

    def _try_validate_schema(self, parsed: dict[str, Any]) -> str | None:
        """
        Validate the parsed JSON against the AthenaLLMOption contract.

        Returns None if valid, or an error string describing all failures.
        Does NOT construct full Pydantic models yet — that happens in Phase 3.
        Validates only what the LLM was asked to produce.
        """
        errors: list[str] = []

        # Top-level required fields
        if "reasoning_cot" not in parsed:
            errors.append("Missing required field: 'reasoning_cot'")
        elif not isinstance(parsed["reasoning_cot"], list) or not parsed["reasoning_cot"]:
            errors.append("'reasoning_cot' must be a non-empty array of strings")

        if "overall_reasoning" not in parsed:
            errors.append("Missing required field: 'overall_reasoning'")
        elif not isinstance(parsed.get("overall_reasoning"), str) or not parsed["overall_reasoning"].strip():
            errors.append("'overall_reasoning' must be a non-empty string")

        if "options" not in parsed:
            errors.append("Missing required field: 'options'")
            return "; ".join(errors)  # can't validate options without the key

        if not isinstance(parsed["options"], list) or not parsed["options"]:
            errors.append("'options' must be a non-empty array")
            return "; ".join(errors)

        if len(parsed["options"]) > 3:
            errors.append(f"'options' must have at most 3 items, got {len(parsed['options'])}")

        # Per-option validation
        for i, opt in enumerate(parsed["options"]):
            prefix = f"options[{i}]"

            if not isinstance(opt, dict):
                errors.append(f"{prefix}: must be an object")
                continue

            # action_name
            if "action_name" not in opt:
                errors.append(f"{prefix}: missing 'action_name'")
            elif not isinstance(opt["action_name"], str) or not opt["action_name"].strip():
                errors.append(f"{prefix}.action_name: must be a non-empty string")

            # procedure_steps
            if "procedure_steps" not in opt:
                errors.append(f"{prefix}: missing 'procedure_steps'")
            elif not isinstance(opt["procedure_steps"], list) or not opt["procedure_steps"]:
                errors.append(f"{prefix}.procedure_steps: must be a non-empty array")
            elif len(opt["procedure_steps"]) > 5:
                errors.append(
                    f"{prefix}.procedure_steps: max 5 steps, got {len(opt['procedure_steps'])}"
                )

            # effectiveness_score
            if "effectiveness_score" not in opt:
                errors.append(f"{prefix}: missing 'effectiveness_score'")
            elif not isinstance(opt["effectiveness_score"], (int, float)):
                errors.append(f"{prefix}.effectiveness_score: must be a number")
            elif not (0.0 <= float(opt["effectiveness_score"]) <= 1.0):
                errors.append(f"{prefix}.effectiveness_score: must be in [0, 1]")

            # operator_effort
            if "operator_effort" not in opt:
                errors.append(f"{prefix}: missing 'operator_effort'")
            elif opt.get("operator_effort") not in _VALID_EFFORTS:
                errors.append(
                    f"{prefix}.operator_effort: must be 'low', 'medium', or 'high', "
                    f"got '{opt.get('operator_effort')}'"
                )

            # predicted_outcome
            if "predicted_outcome" not in opt:
                errors.append(f"{prefix}: missing 'predicted_outcome'")
            elif not isinstance(opt.get("predicted_outcome"), str) or len(opt["predicted_outcome"]) < 10:
                errors.append(f"{prefix}.predicted_outcome: must be a string with at least 10 characters")

            # contra_indications (optional, but if present must be a list)
            if "contra_indications" in opt and not isinstance(opt["contra_indications"], list):
                errors.append(f"{prefix}.contra_indications: must be an array")

        return "; ".join(errors) if errors else None

    def _append_reprompt(
        self,
        messages: list[dict[str, str]],
        assistant_response: str,
        reprompt: str,
    ) -> list[dict[str, str]]:
        """
        Extend the conversation with the assistant's (failed) response and
        our corrective reprompt. Maintains context across retries.
        Same pattern as SherlockAgent._append_reprompt.
        """
        return messages + [
            {"role": "assistant", "content": assistant_response},
            {"role": "user",      "content": reprompt},
        ]
