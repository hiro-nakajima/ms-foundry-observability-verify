"""Normalize Framework session state and application spans without nested sessions."""

from __future__ import annotations

import hashlib
from typing import Any

from agent_framework import AgentSession

from procurement_agent.observability import TelemetryRecorder
from procurement_agent.session_state import load_execution_state

from .envelope import AgentTrace, RunIdentity, SessionIdentity, TraceEvaluationEnvelope


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _span_to_dict(span) -> dict[str, Any]:
    return {
        "name": span.name,
        "trace_id": f"{span.context.trace_id:032x}",
        "span_id": f"{span.context.span_id:016x}",
        "parent_span_id": f"{span.parent.span_id:016x}" if span.parent else None,
        "attributes": dict(span.attributes or {}),
        "status": span.status.status_code.name,
    }


def build_envelope(
    *, run: RunIdentity, session: AgentSession, telemetry: TelemetryRecorder,
    user_input: list[dict[str, Any]], response: dict[str, Any],
    retrieved_contexts: list[dict[str, Any]], system_prompt: dict[str, Any],
    tool_definitions: list[dict[str, Any]], tool_calls: list[dict[str, Any]],
    tool_output: list[dict[str, Any]], resumed: bool = False,
) -> TraceEvaluationEnvelope:
    state = load_execution_state(session, required=True)
    assert state is not None
    spans = [_span_to_dict(span) for span in telemetry.finished_spans()]
    events = [
        {"span": span.name, "name": event.name, "attributes": dict(event.attributes or {})}
        for span in telemetry.finished_spans() for event in span.events
    ]
    return TraceEvaluationEnvelope(
        run=run,
        session=SessionIdentity(
            framework_session_id_hash=_hash(session.session_id),
            service_session_id_hash=_hash(session.service_session_id) if session.service_session_id else None,
            turn_number=state.turn_number,
            resumed=resumed,
        ),
        content_profile=telemetry.content_profile,
        user_input=user_input,
        response=response,
        retrieved_contexts=retrieved_contexts,
        system_prompt=system_prompt,
        tool_definitions=tool_definitions,
        tool_calls=tool_calls,
        tool_output=tool_output,
        agent_trace=AgentTrace(
            spans=spans, events=events,
            governance_decisions=[item.model_dump(mode="json") for item in state.governance_decisions],
        ),
        conversation=[],
        plan=state.plan.model_dump(mode="json") if state.plan else {},
        statuses=state.last_machine_response or {},
    )
