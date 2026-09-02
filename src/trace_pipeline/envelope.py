"""Normalized trace envelope for the revised single architecture."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class EnvelopeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunIdentity(EnvelopeModel):
    run_id: str
    case_id: str
    architecture_id: Literal["procurement_application_v2"] = "procurement_application_v2"
    agent_role: str
    agent_definition_name: str
    agent_definition_version: str
    implementation_kind: str
    technical_status: Literal["SUCCESS", "ERROR"] = "SUCCESS"


class SessionIdentity(EnvelopeModel):
    framework_session_id_hash: str
    service_session_id_hash: str | None = None
    turn_number: int = Field(ge=0)
    resumed: bool


class CorrelationIdentity(EnvelopeModel):
    trace_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    parent_invocation_id: str | None = None
    remote_task_id: str | None = None
    child_invocations: list[dict[str, Any]] = Field(default_factory=list)


class AgentTrace(EnvelopeModel):
    spans: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    delegations: list[dict[str, Any]] = Field(default_factory=list)
    governance_decisions: list[dict[str, Any]] = Field(default_factory=list)
    validations: list[dict[str, Any]] = Field(default_factory=list)


class TraceEvaluationEnvelope(EnvelopeModel):
    schema_version: Literal["3.0"] = "3.0"
    run: RunIdentity
    session: SessionIdentity
    correlation: CorrelationIdentity = Field(default_factory=CorrelationIdentity)
    content_profile: Literal["synthetic-content-on", "production-like-content-off"]
    user_input: list[dict[str, Any]] = Field(default_factory=list)
    response: dict[str, Any] = Field(default_factory=dict)
    retrieved_contexts: list[dict[str, Any]] = Field(default_factory=list)
    system_prompt: dict[str, Any] = Field(default_factory=dict)
    tool_definitions: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    tool_output: list[dict[str, Any]] = Field(default_factory=list)
    agent_trace: AgentTrace = Field(default_factory=AgentTrace)
    conversation: list[dict[str, Any]] = Field(default_factory=list)
    plan: dict[str, Any] = Field(default_factory=dict)
    statuses: dict[str, Any] = Field(default_factory=dict)
    evaluation: dict[str, Any] = Field(default_factory=dict)
