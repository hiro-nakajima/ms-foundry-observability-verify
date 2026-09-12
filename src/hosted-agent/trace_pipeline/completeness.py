"""Deterministic completeness check for the nine required trace fields."""

from __future__ import annotations

from .envelope import TraceEvaluationEnvelope


REQUIRED_TRACE_FIELDS = (
    "user_input",
    "response",
    "retrieved_contexts",
    "system_prompt",
    "tool_definitions",
    "tool_calls",
    "tool_output",
    "agent_trace",
    "conversation",
)


def trace_completeness(envelope: TraceEvaluationEnvelope) -> dict[str, object]:
    data = envelope.model_dump(mode="json")
    present: dict[str, bool] = {}
    for field in REQUIRED_TRACE_FIELDS:
        value = data[field]
        if field == "agent_trace":
            present[field] = bool(value.get("spans") or value.get("events"))
        else:
            present[field] = bool(value)
    missing = [field for field, is_present in present.items() if not is_present]
    return {
        "complete": not missing,
        "present": present,
        "missing": missing,
        "score": sum(present.values()) / len(REQUIRED_TRACE_FIELDS),
    }
