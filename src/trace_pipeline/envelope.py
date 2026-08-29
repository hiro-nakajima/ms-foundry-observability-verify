"""Normalized nine-field trace evaluation envelope."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class EnvelopeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunIdentity(EnvelopeModel):
    run_id: str
    case_id: str
    logical_pattern: Literal["PA-S", "PA-M", "HA-S", "HA-M"]
    agent_role: str
    agent_definition_id: str
    foundry_resource_id: str | None = None
    implementation_kind: str
    technical_status: Literal["SUCCESS", "ERROR"] = "SUCCESS"


class SessionIdentity(EnvelopeModel):
    session_id_hash: str
    conversation_id_hash: str
    turn_count: int = Field(ge=0)
    resumed: bool


class AgentTrace(EnvelopeModel):
    spans: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    delegations: list[dict[str, Any]] = Field(default_factory=list)
    governance_decisions: list[dict[str, Any]] = Field(default_factory=list)
    validations: list[dict[str, Any]] = Field(default_factory=list)


class TraceEvaluationEnvelope(EnvelopeModel):
    schema_version: Literal["2.0"] = "2.0"
    run: RunIdentity
    session: SessionIdentity
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
    evaluation: dict[str, Any] = Field(default_factory=dict)
