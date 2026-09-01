"""Deterministic detectors for the 14 revised Failure Patterns."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


PATTERN_IDS = (
    "SD-01", "SD-02", "SD-03", "SD-04", "SD-05",
    "MA-01", "MA-02", "MA-03", "MA-04", "MA-05", "MA-06",
    "TV-01", "TV-02", "TV-03",
)


class DetectionOutcome(StrEnum):
    DETECTED = "DETECTED"
    NOT_DETECTED = "NOT_DETECTED"
    INJECTION_MISSED = "INJECTION_MISSED"
    UNEVALUABLE_TRACE_INCOMPLETE = "UNEVALUABLE_TRACE_INCOMPLETE"


class TraceFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    case_id: str
    technical_status: Literal["SUCCESS", "ERROR"] = "SUCCESS"
    present_fields: list[str] = Field(default_factory=lambda: [
        "user_input", "response", "retrieved_contexts", "system_prompt",
        "tool_definitions", "tool_calls", "tool_output", "agent_trace",
        "conversation", "plan",
    ])
    constraints_satisfied: bool = True
    role_tool_allowlist_valid: bool = True
    duplicate_step: bool = False
    session_continuity: bool = True
    actions_after_terminal: int = Field(default=0, ge=0)
    snapshot_present: bool = True
    clarification_required: bool = False
    clarification_asked: bool = False
    delegation_relevant: bool = True
    handoff_required_fields_missing: list[str] = Field(default_factory=list)
    received_values_used: bool = True
    claimed_actions_missing: list[str] = Field(default_factory=list)
    required_steps_complete: bool = True
    validation_coverage_complete: bool = True
    evidence_consistent: bool = True


class DetectionResult(BaseModel):
    pattern_id: str
    outcome: DetectionOutcome
    reason: str
    injection_requested: bool = False
    injection_activated: bool = False
    missing_trace_fields: list[str] = Field(default_factory=list)


REQUIRED_FIELDS = {
    "SD-01": {"user_input", "response", "retrieved_contexts"},
    "SD-02": {"system_prompt", "tool_definitions", "tool_calls", "agent_trace"},
    "SD-03": {"tool_calls", "agent_trace", "plan"},
    "SD-04": {"conversation", "agent_trace", "plan"},
    "SD-05": {"conversation", "tool_calls", "agent_trace", "plan"},
    "MA-01": {"conversation", "tool_calls", "agent_trace"},
    "MA-02": {"user_input", "response", "conversation", "plan"},
    "MA-03": {"user_input", "tool_calls", "agent_trace"},
    "MA-04": {"tool_calls", "tool_output", "agent_trace", "conversation"},
    "MA-05": {"tool_calls", "tool_output", "agent_trace", "response"},
    "MA-06": {"response", "tool_calls", "agent_trace", "plan"},
    "TV-01": {"user_input", "response", "conversation", "plan"},
    "TV-02": {"tool_calls", "tool_output", "agent_trace", "plan"},
    "TV-03": {"retrieved_contexts", "tool_output", "agent_trace", "response"},
}


def _violated(pattern_id: str, facts: TraceFacts) -> bool:
    return {
        "SD-01": not facts.constraints_satisfied,
        "SD-02": not facts.role_tool_allowlist_valid,
        "SD-03": facts.duplicate_step,
        "SD-04": not facts.session_continuity,
        "SD-05": facts.actions_after_terminal > 0,
        "MA-01": not facts.snapshot_present,
        "MA-02": facts.clarification_required and not facts.clarification_asked,
        "MA-03": not facts.delegation_relevant,
        "MA-04": bool(facts.handoff_required_fields_missing),
        "MA-05": not facts.received_values_used,
        "MA-06": bool(facts.claimed_actions_missing),
        "TV-01": not facts.required_steps_complete,
        "TV-02": not facts.validation_coverage_complete,
        "TV-03": not facts.evidence_consistent,
    }[pattern_id]


def detect(
    pattern_id: str, facts: TraceFacts | dict[str, Any], *,
    injection_requested: bool = False, injection_activated: bool = False,
) -> DetectionResult:
    if pattern_id not in PATTERN_IDS:
        raise ValueError(f"unknown pattern: {pattern_id}")
    facts = TraceFacts.model_validate(facts)
    if injection_requested and not injection_activated:
        return DetectionResult(
            pattern_id=pattern_id, outcome=DetectionOutcome.INJECTION_MISSED,
            reason="requested semantic injection did not activate",
            injection_requested=True, injection_activated=False,
        )
    missing = sorted(REQUIRED_FIELDS[pattern_id] - set(facts.present_fields))
    if missing:
        return DetectionResult(
            pattern_id=pattern_id, outcome=DetectionOutcome.UNEVALUABLE_TRACE_INCOMPLETE,
            reason="required detector inputs are absent from the trace",
            injection_requested=injection_requested, injection_activated=injection_activated,
            missing_trace_fields=missing,
        )
    outcome = DetectionOutcome.DETECTED if _violated(pattern_id, facts) else DetectionOutcome.NOT_DETECTED
    return DetectionResult(
        pattern_id=pattern_id, outcome=outcome,
        reason="semantic contract violation found" if outcome == DetectionOutcome.DETECTED else "no semantic contract violation found",
        injection_requested=injection_requested, injection_activated=injection_activated,
    )


def evaluate_all(facts: TraceFacts | dict[str, Any]) -> list[DetectionResult]:
    return [detect(pattern_id, facts) for pattern_id in PATTERN_IDS]


def summarize(results: list[DetectionResult]) -> dict[str, Any]:
    semantic = [item for item in results if item.outcome in {DetectionOutcome.DETECTED, DetectionOutcome.NOT_DETECTED}]
    operational = [item for item in results if item.outcome in {DetectionOutcome.INJECTION_MISSED, DetectionOutcome.UNEVALUABLE_TRACE_INCOMPLETE}]
    return {
        "semantic": {outcome.value: sum(item.outcome == outcome for item in semantic) for outcome in (DetectionOutcome.DETECTED, DetectionOutcome.NOT_DETECTED)},
        "operational": {outcome.value: sum(item.outcome == outcome for item in operational) for outcome in (DetectionOutcome.INJECTION_MISSED, DetectionOutcome.UNEVALUABLE_TRACE_INCOMPLETE)},
    }
