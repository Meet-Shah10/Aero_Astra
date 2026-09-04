"""
AERO-ASTRA — ATHENA LLM Prompt Templates
==========================================
All prompt strings live here, never in agent.py.
Same discipline as backend/sherlock/prompts.py.

The LLM prompt schema (RESPONSE_JSON_SCHEMA) deliberately excludes
safety_score and blended_rank — these are injected by Python after
validation (Two-Schema Pattern). This eliminates the score-hallucination
failure mode without requiring a special validation check.

reasoning_cot is asked before options so the model commits to its
reasoning chain before producing numerical scores, reducing score
inconsistency across retries.
"""

from __future__ import annotations

import json
from typing import Any

from backend.oracle.schemas import OracleResponse
from backend.sherlock.schemas import SherlockDiagnosis
from backend.simulator.recovery import RECOVERY_CATALOG

from .schemas import MissionConstraints

# ─────────────────────────────────────────────────────────────────────────────
# LLM Response JSON Schema (AthenaLLMOption — no safety_score, no blended_rank)
# ─────────────────────────────────────────────────────────────────────────────

RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["reasoning_cot", "overall_reasoning", "options"],
    "properties": {
        "reasoning_cot": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Step-by-step reasoning chain BEFORE producing options. "
                "List each reasoning step as a separate string. "
                "Minimum 2 steps. Fill this BEFORE writing the options array."
            ),
        },
        "overall_reasoning": {
            "type": "string",
            "description": (
                "Prose summary (2–4 sentences) of your recommendation rationale. "
                "Reference ORACLE's safety scores and the diagnosis urgency."
            ),
        },
        "options": {
            "type": "array",
            "minItems": 1,
            "maxItems": 3,
            "description": "2–3 recovery options based on the actions ORACLE validated.",
            "items": {
                "type": "object",
                "required": [
                    "action_name",
                    "procedure_steps",
                    "effectiveness_score",
                    "operator_effort",
                    "predicted_outcome",
                    "contra_indications",
                ],
                "properties": {
                    "action_name": {
                        "type": "string",
                        "description": (
                            "MUST be one of the action names from the ORACLE results "
                            "listed above. Any other value will be rejected."
                        ),
                    },
                    "procedure_steps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 5,
                        "description": (
                            "3–5 concise, ordered procedure steps for the operator checklist. "
                            "Each step is one imperative sentence. Keep each step under 20 words."
                        ),
                    },
                    "effectiveness_score": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "description": (
                            "Functional recovery quality beyond mere survival (0.0–1.0). "
                            "ORACLE's safety_score already quantifies success probability — "
                            "do NOT repeat that here. Score 1.0 if the action fully restores "
                            "nominal operations; score 0.3 if it merely keeps the satellite "
                            "alive in degraded safe mode."
                        ),
                    },
                    "operator_effort": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                        "description": (
                            "'low' = single autonomous command; "
                            "'medium' = multi-step sequence needing operator attention; "
                            "'high' = complex manual procedure requiring ground team coordination."
                        ),
                    },
                    "predicted_outcome": {
                        "type": "string",
                        "description": (
                            "2–3 sentence narrative: what the satellite state looks like "
                            "after successful execution. Reference specific subsystems."
                        ),
                    },
                    "contra_indications": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Conditions under which this action should NOT be taken. "
                            "Use an empty array [] if there are none."
                        ),
                    },
                },
            },
        },
    },
}

RESPONSE_JSON_SCHEMA_STR = json.dumps(RESPONSE_JSON_SCHEMA, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# System Prompt
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are ATHENA, an expert spacecraft recovery planning engineer for the \
AERO-ASTRA autonomous satellite operations system. You have 20+ years of \
experience designing fault recovery procedures for LEO missions.

Your role: given SHERLOCK's root-cause diagnosis and ORACLE's Monte Carlo-validated \
safety rankings, produce a human-readable recovery plan with 2–3 ranked options. \
Each option must include ordered procedure steps and an effectiveness judgement.

CRITICAL CONSTRAINTS — follow without exception:

1. ACTION NAMES: Every action_name in your response MUST exactly match one of the \
action names listed in the ORACLE VALIDATED RESULTS section. Do not invent, abbreviate, \
or paraphrase action names. They are machine-executable identifiers.

2. SAFETY SCORES: Do NOT include safety_score or blended_rank in your output — \
these are computed by the system from ORACLE's simulation data. Your schema does not \
have these fields. Including them will cause your response to be rejected.

3. EFFECTIVENESS ≠ SAFETY: ORACLE's safety_score already quantifies survival probability \
via Monte Carlo simulation. Your effectiveness_score measures functional recovery quality: \
does the action restore full mission capability, or merely keep the bus alive in safe mode? \
Score independently of ORACLE's numbers.

4. REASONING FIRST: Complete reasoning_cot before writing the options array. Your \
reasoning steps should reference ORACLE's safety scores, the diagnosis urgency, and the \
mission constraints. This prevents score inconsistency.

5. JSON ONLY: Return ONLY a valid JSON object matching the provided schema. \
No preamble, no explanation outside the JSON, no markdown fences. \
Start with {{ and end with }}."""


# ─────────────────────────────────────────────────────────────────────────────
# User Prompt Builder
# ─────────────────────────────────────────────────────────────────────────────


def _format_oracle_results(oracle_response: OracleResponse) -> str:
    """
    Format ORACLE's ranked results for the prompt. Includes safety_score
    (so the LLM can reference it in reasoning) but does NOT ask the LLM
    to reproduce it in output.
    """
    lines: list[str] = []
    for i, result in enumerate(oracle_response.results, 1):
        mc = result.mc_result
        catalog_entry = RECOVERY_CATALOG.get(result.action_name)
        description = catalog_entry.description if catalog_entry else "(no description)"
        target_subs = (
            ", ".join(catalog_entry.target_subsystems)
            if catalog_entry else "unknown"
        )
        flags_str = ", ".join(result.flags) if result.flags else "none"
        lines.append(
            f"  [{i}] {result.action_name}\n"
            f"       safety_score  = {result.safety_score:+.3f}  "
            f"(nominal={mc.nominal_recovery_rate:.1%}, "
            f"degraded={mc.degraded_operation_rate:.1%}, "
            f"loss={mc.mission_loss_rate:.1%})\n"
            f"       flags         = {flags_str}\n"
            f"       targets       = {target_subs}\n"
            f"       description   : {description}"
        )
    return "\n\n".join(lines)


def _format_constraints(constraints: MissionConstraints | None) -> str:
    if constraints is None:
        return "  (no constraints specified — use engineering judgement)"
    parts = [
        f"  min_fuel_reserve : {constraints.min_fuel_reserve_pct:.1f}%",
        f"  max_operator_effort : {constraints.max_operator_effort.value}",
    ]
    if constraints.notes:
        parts.append(f"  operator notes   : {constraints.notes}")
    return "\n".join(parts)



def build_user_prompt(
    sherlock_diagnosis: SherlockDiagnosis,
    oracle_response: OracleResponse,
    constraints: MissionConstraints | None,
    fdir_context: str = "",
) -> str:

    """
    Build the full user-facing prompt for a recovery planning request.

    Args:
        sherlock_diagnosis: The validated SHERLOCK output.
        oracle_response:    ORACLE's ranked and validated action results.
        constraints:        Optional operator mission constraints.
        fdir_context:       Optional RAG-retrieved FDIR passages from NASA-HDBK-1002.
                            When non-empty, injected between SHERLOCK and ORACLE blocks
                            so the LLM grounds its reasoning in authoritative guidance.

    Returns:
        Complete user prompt string.
    """
    valid_names = ", ".join(
        f'"{r.action_name}"' for r in oracle_response.results
    )

    oracle_block = _format_oracle_results(oracle_response)
    constraints_block = _format_constraints(constraints)

    # RAG block: only rendered when the vectorstore returned relevant passages
    fdir_block = (
        f"\n{fdir_context}\n"
        if fdir_context and fdir_context.strip()
        else "  (no FDIR handbook context available)"
    )

    # RAG-aware instruction step: present only when context was retrieved
    rag_instruction = (
        "  0. Ground your reasoning_cot in the NASA FDIR GUIDANCE passages above "
        "where relevant. Quote or paraphrase the handbook guidance when it applies "
        "to the recommended action or its contra-indications.\n"
        if fdir_context and fdir_context.strip()
        else ""
    )

    return f"""SHERLOCK DIAGNOSIS:
  primary_root_cause  : {sherlock_diagnosis.primary_root_cause}
  causal_chain        : {" → ".join(sherlock_diagnosis.causal_chain)}
  affected_subsystems : {", ".join(sherlock_diagnosis.affected_subsystems)}
  urgency             : {sherlock_diagnosis.urgency.value}
  time_to_critical    : {sherlock_diagnosis.time_to_critical_estimate_minutes} minutes
  confidence          : {sherlock_diagnosis.confidence_score:.0%}
  reasoning           : {sherlock_diagnosis.reasoning}

NASA FDIR GUIDANCE (RAG-RETRIEVED from NASA-HDBK-1002):
{fdir_block}
ORACLE VALIDATED RESULTS (already ranked by safety_score — do NOT alter these scores):
{oracle_block}

VALID action_name VALUES (copy exactly — case-sensitive):
  [{valid_names}]

MISSION CONSTRAINTS (qualitative context for your reasoning — not formal limits):
{constraints_block}

INSTRUCTIONS:
{rag_instruction}  1. Complete reasoning_cot (minimum 2 steps) BEFORE writing options.
  2. Select 2–3 options from the ORACLE results above. Prefer options with higher
     safety_score unless mission constraints or effectiveness considerations justify
     a different order.
  3. Limit procedure_steps to 3–5 concise steps per option (max 20 words each).
  4. Do not include safety_score or blended_rank — the system computes these.

REQUIRED OUTPUT SCHEMA:
{RESPONSE_JSON_SCHEMA_STR}

Return ONLY the JSON object. No other text."""


# ─────────────────────────────────────────────────────────────────────────────
# Corrective Reprompts — one per failure mode
# ─────────────────────────────────────────────────────────────────────────────


def build_json_parse_reprompt(raw_response: str) -> str:
    """Reprompt when the LLM returned something that is not valid JSON."""
    return f"""Your previous response could not be parsed as JSON.

What you returned:
---
{raw_response[:500]}{"..." if len(raw_response) > 500 else ""}
---

Return ONLY a valid JSON object matching the schema. No markdown, no backticks, \
no explanation text. Start your response with {{ and end with }}."""


def build_schema_validation_reprompt(
    raw_response: str,
    validation_errors: str,
) -> str:
    """Reprompt when the LLM's JSON failed schema validation."""
    return f"""Your JSON response failed schema validation.

Validation errors:
{validation_errors}

Your previous response:
---
{raw_response[:600]}{"..." if len(raw_response) > 600 else ""}
---

Fix every error listed above and return ONLY the corrected JSON object. \
Ensure reasoning_cot is a non-empty array and each option has all required fields."""


def build_hallucinated_action_reprompt(
    raw_response: str,
    bad_action_names: list[str],
    valid_action_names: list[str],
) -> str:
    """
    Reprompt when the LLM used action names not present in ORACLE's results.
    This is the ATHENA-specific anti-hallucination check.
    """
    bad_str   = ", ".join(f'"{n}"' for n in bad_action_names)
    valid_str = ", ".join(f'"{n}"' for n in sorted(valid_action_names))
    return f"""Your response was rejected because you used action names that \
ORACLE did not validate: [{bad_str}].

Valid action names (copy exactly, case-sensitive): [{valid_str}]

ORACLE ran Monte Carlo simulations for these specific actions only. Using any \
other action name is physically meaningless — the system has no safety data for it.

Your previous response:
---
{raw_response[:600]}{"..." if len(raw_response) > 600 else ""}
---

Return a corrected JSON object using only action names from [{valid_str}]."""
