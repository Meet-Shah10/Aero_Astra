"""
SHERLOCK — LLM Prompt Templates
Agent 3 of AERO-ASTRA | Root-Cause Diagnosis

All prompt strings live here, never in agent.py. This makes prompts
easy to review, iterate, and test in isolation from the API call logic.
"""

from __future__ import annotations

import json

from .schemas import AnomalyEvent, SherlockDiagnosis

# ─────────────────────────────────────────────────────────────────────────────
# JSON Schema for the LLM response
# ─────────────────────────────────────────────────────────────────────────────

# Derived from SherlockDiagnosis — we tell the LLM exactly what fields to fill.
# The audit fields (graph_candidate_set, llm_attempts, diagnosis_timestamp)
# are NOT asked from the LLM; they are filled programmatically after validation.
RESPONSE_JSON_SCHEMA = {
    "type": "object",
    "required": [
        "primary_root_cause",
        "causal_chain",
        "affected_subsystems",
        "confidence_score",
        "urgency",
        "time_to_critical_estimate_minutes",
        "reasoning",
    ],
    "properties": {
        "primary_root_cause": {
            "type": "string",
            "description": (
                "The subsystem identified as the originating fault. "
                "MUST be one of the valid root cause candidates listed above."
            ),
        },
        "causal_chain": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Ordered list from root cause → intermediate effects → observed symptom. "
                "First element MUST equal primary_root_cause. "
                "All elements MUST be from the valid candidate set or the flagged subsystem."
            ),
        },
        "affected_subsystems": {
            "type": "array",
            "items": {"type": "string"},
            "description": "All subsystems impacted, including root cause and downstream victims.",
        },
        "confidence_score": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "Your confidence in this diagnosis (0.0 = uncertain, 1.0 = certain).",
        },
        "urgency": {
            "type": "string",
            "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"],
            "description": "Operational urgency for the response team.",
        },
        "time_to_critical_estimate_minutes": {
            "type": "integer",
            "minimum": 0,
            "description": (
                "Estimated minutes until irreversible failure if no action is taken. "
                "Use 0 if already critical."
            ),
        },
        "reasoning": {
            "type": "string",
            "description": (
                "Concise explanation of your reasoning, suitable for an operator audit trail. "
                "Reference specific telemetry values where available."
            ),
        },
    },
}

RESPONSE_JSON_SCHEMA_STR = json.dumps(RESPONSE_JSON_SCHEMA, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# System Prompt
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are SHERLOCK, an expert spacecraft systems engineer specialising in \
satellite fault isolation and root-cause diagnosis. You have 20+ years of experience across \
LEO satellite missions including Earth observation, communications, and scientific platforms.

Your role: given a telemetry anomaly detected by an upstream anomaly detector, determine the \
root cause and causal chain — i.e., which subsystem originally faulted and how the fault \
propagated to produce the observed symptoms.

CRITICAL CONSTRAINTS — you must follow these without exception:

1. ROOT CAUSE SELECTION: You will be given a pre-computed set of valid root cause candidates \
derived from the satellite's physical dependency graph. You MUST select a primary_root_cause \
from this candidate set only. Do NOT introduce root causes outside this set. The graph \
encodes real physical dependencies; candidates outside it are not physically plausible given \
the observed fault location.

2. CAUSAL CHAIN: Every node in your causal_chain must be a known satellite subsystem. The \
first element must equal your primary_root_cause. The last element should be the observed \
symptom subsystem (or close to it). Intermediate steps should reflect real physical \
propagation paths.

3. CONSISTENCY: Use low reasoning temperature — your job is precise fault isolation, not \
creative speculation. When in doubt between two physically equivalent candidates, prefer the \
one with stronger telemetry evidence.

4. JSON ONLY: Return ONLY a valid JSON object matching the schema provided. No preamble, \
no explanation outside the JSON, no markdown fences. The JSON must be parseable as-is.

5. REASONING FIELD: The reasoning field should be concise (2–5 sentences) and reference \
specific telemetry values when available. It will appear verbatim in an operator runbook."""


# ─────────────────────────────────────────────────────────────────────────────
# User Prompt Builder
# ─────────────────────────────────────────────────────────────────────────────

def build_user_prompt(
    event: AnomalyEvent,
    candidate_set: set[str],
    candidate_descriptions: str,
    telemetry_context: str,
) -> str:
    """
    Build the full user-facing prompt for a diagnosis request.

    Args:
        event: The anomaly event to diagnose.
        candidate_set: Set of valid root cause candidates from the graph.
        candidate_descriptions: Human-readable explanation of why each candidate is valid.
        telemetry_context: Formatted telemetry snapshot string.

    Returns:
        Complete user prompt string.
    """
    chronicle_block = ""
    if event.event_log_context:
        chronicle_block = f"""
EVENT LOG CONTEXT (from CHRONICLE):
{event.event_log_context.strip()}
"""

    telemetry_window_block = ""
    if event.telemetry_window:
        rows_str = json.dumps(event.telemetry_window[:20], indent=2)  # cap at 20 rows
        telemetry_window_block = f"""
TELEMETRY WINDOW (rows around anomaly):
{rows_str}
"""

    candidates_list = ", ".join(sorted(candidate_set))

    return f"""ANOMALY EVENT:
  Anomaly ID       : {event.anomaly_id}
  Flagged Subsystem: {event.flagged_subsystem}
  Flagged Parameter: {event.flagged_parameter}
  Severity         : {event.severity.value}
  SENTINEL Confidence: {event.confidence_score:.2%}
  Timestamp        : {event.timestamp.isoformat()}
{telemetry_window_block}{chronicle_block}
CURRENT SUBSYSTEM TELEMETRY:
{telemetry_context}

GRAPH-VALIDATED ROOT CAUSE CANDIDATES:
The satellite dependency graph has determined that only the following subsystems are \
physically capable of causing a fault in {event.flagged_subsystem}:

{candidate_descriptions}

Valid candidate list: [{candidates_list}]

You MUST select primary_root_cause from this list: [{candidates_list}]
Every node in causal_chain must be a known satellite subsystem \
(EPS, TCS, ADCS, OBC, TT&C, Propulsion).

REQUIRED OUTPUT SCHEMA:
{RESPONSE_JSON_SCHEMA_STR}

Return ONLY the JSON object. No other text."""


# ─────────────────────────────────────────────────────────────────────────────
# Corrective Reprompts
# ─────────────────────────────────────────────────────────────────────────────

def build_json_parse_reprompt(raw_response: str) -> str:
    """Reprompt when the LLM returned something that's not valid JSON."""
    return f"""Your previous response could not be parsed as JSON.

What you returned:
---
{raw_response[:500]}{"..." if len(raw_response) > 500 else ""}
---

Return ONLY a valid JSON object. No markdown, no backticks, no explanation text. \
Start your response with {{ and end with }}."""


def build_schema_validation_reprompt(
    raw_response: str,
    validation_errors: str,
) -> str:
    """Reprompt when the LLM's JSON failed Pydantic schema validation."""
    return f"""Your JSON response failed schema validation.

Validation errors:
{validation_errors}

Your previous response:
---
{raw_response[:500]}{"..." if len(raw_response) > 500 else ""}
---

Fix the errors and return ONLY the corrected JSON object."""


def build_graph_validation_reprompt(
    raw_response: str,
    claimed_root_cause: str,
    candidate_set: set[str],
) -> str:
    """Reprompt when the LLM's root cause is outside the graph candidate set."""
    candidates_list = ", ".join(sorted(candidate_set))
    return f"""Your diagnosis is invalid because the primary_root_cause you chose \
('{claimed_root_cause}') is NOT in the graph-validated candidate set.

Valid root cause candidates: [{candidates_list}]

Physical dependency analysis has ruled out all other subsystems. You must \
choose from the valid candidate set.

Your previous response:
---
{raw_response[:500]}{"..." if len(raw_response) > 500 else ""}
---

Return a corrected JSON object with primary_root_cause from [{candidates_list}]."""
