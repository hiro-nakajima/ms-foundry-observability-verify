"""Normalize Framework session state and application spans without nested sessions."""

from __future__ import annotations

import hashlib
from typing import Any

from agent_framework import AgentSession, HistoryProvider

from procurement_agent.observability import TelemetryRecorder
from procurement_agent.session_state import load_execution_state

from .envelope import AgentTrace, CorrelationIdentity, RunIdentity, SessionIdentity, TraceEvaluationEnvelope


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


async def build_envelope(
    *, run: RunIdentity, session: AgentSession, history_provider: HistoryProvider,
    telemetry: TelemetryRecorder,
    user_input: list[dict[str, Any]], response: dict[str, Any],
    retrieved_contexts: list[dict[str, Any]], system_prompt: dict[str, Any],
    tool_definitions: list[dict[str, Any]], tool_calls: list[dict[str, Any]],
    tool_output: list[dict[str, Any]], resumed: bool = False,
) -> TraceEvaluationEnvelope:
    state = load_execution_state(session, required=True)
    assert state is not None
    finished_spans = [
        span for span in telemetry.finished_spans()
        if (span.attributes or {}).get("test.case.id") == run.case_id
    ]
    spans = [_span_to_dict(span) for span in finished_spans]
    events = [
        {"span": span.name, "name": event.name, "attributes": dict(event.attributes or {})}
        for span in finished_spans for event in span.events
    ]
    root_span = next((span for span in finished_spans if span.name == "plan.create"), finished_spans[0] if finished_spans else None)
    child_correlations = list(state.child_correlations)
    if not child_correlations:
        for child_result in (state.catalog_result, state.code_result):
            if child_result is not None and child_result.correlation not in child_correlations:
                child_correlations.append(child_result.correlation)
    child_correlation = child_correlations[-1] if child_correlations else None
    history_messages = await history_provider.get_messages(
        session.session_id, state=session.state,
    )
    conversation = []
    for turn_index, message in enumerate(history_messages, start=1):
        if isinstance(message, dict):
            role = str(message.get("role", "unknown"))
            content = str(message.get("text") or message.get("contents") or "")
        else:
            raw_role = getattr(message, "role", "unknown")
            role = str(getattr(raw_role, "value", raw_role))
            content = str(getattr(message, "text", ""))
        conversation.append({
            "role": role,
            "turn_index": turn_index,
            **telemetry.protect_content("conversation", content),
        })
    return TraceEvaluationEnvelope(
        run=run,
        session=SessionIdentity(
            framework_session_id_hash=_hash(session.session_id),
            service_session_id_hash=_hash(session.service_session_id) if session.service_session_id else None,
            turn_number=state.turn_number,
            resumed=resumed,
        ),
        correlation=CorrelationIdentity(
            trace_id=f"{root_span.context.trace_id:032x}" if root_span else None,
            span_id=f"{root_span.context.span_id:016x}" if root_span else None,
            parent_span_id=f"{root_span.parent.span_id:016x}" if root_span and root_span.parent else None,
            parent_invocation_id=child_correlation.parent_invocation_id if child_correlation else None,
            remote_task_id=child_correlation.remote_task_id if child_correlation else None,
            child_invocations=[{
                "test_case_id": item.test_case_id,
                "framework_session_id_hash": _hash(item.framework_session_id),
                "turn_number": item.turn_number,
                "plan_id": item.plan_id,
                "plan_version": item.plan_version,
                "step_id": item.step_id,
                "attempt": item.attempt,
                "parent_invocation_id": item.parent_invocation_id,
                "remote_task_id": item.remote_task_id,
            } for item in child_correlations],
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
        conversation=conversation,
        plan=state.plan.model_dump(mode="json") if state.plan else {},
        statuses=state.last_machine_response or {},
    )
