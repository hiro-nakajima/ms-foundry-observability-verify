"""Local normalizer from session and OTel spans to the evaluation envelope."""

from __future__ import annotations

import hashlib
from typing import Any

from procurement_agent.memory import AgentSession
from procurement_agent.observability import TelemetryRecorder

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
    *,
    run: RunIdentity,
    session: AgentSession,
    telemetry: TelemetryRecorder,
    user_input: list[dict[str, Any]],
    response: dict[str, Any],
    retrieved_contexts: list[dict[str, Any]],
    system_prompt: dict[str, Any],
    tool_definitions: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
    tool_output: list[dict[str, Any]],
    delegations: list[dict[str, Any]] | None = None,
    governance_decisions: list[Any] | None = None,
    validations: list[dict[str, Any]] | None = None,
    resumed: bool = False,
    trace_id: str | None = None,
    active_spans: list[Any] | None = None,
) -> TraceEvaluationEnvelope:
    finished = list(telemetry.finished_spans()) + list(active_spans or [])
    if trace_id is not None:
        expected = int(trace_id, 16)
        finished = [span for span in finished if span.context.trace_id == expected]
    unique: dict[int, Any] = {span.context.span_id: span for span in finished}
    finished = list(unique.values())
    spans = [_span_to_dict(span) for span in finished]
    events = [
        {"span": span.name, "name": event.name, "attributes": dict(event.attributes or {})}
        for span in finished
        for event in span.events
    ]
    plan = session.plan.model_dump(mode="json") if session.plan else {}
    if "goal" in plan:
        plan["goal"] = telemetry.protect_content("plan_goal", plan["goal"])
    protected_validations = []
    for validation in validations or []:
        protected_validations.append(
            {
                "valid": bool(validation.get("valid")),
                "violation_count": len(validation.get("violations", [])),
                "checks": dict(validation.get("checks", {})),
                "evidence_refs": list(validation.get("evidence_refs", [])),
                **telemetry.protect_content("validation", validation),
            }
        )
    return TraceEvaluationEnvelope(
        run=run,
        session=SessionIdentity(
            session_id_hash=_hash(session.session_id),
            conversation_id_hash=_hash(session.conversation_id),
            turn_count=session.turn_index,
            resumed=resumed,
        ),
        user_input=user_input,
        response=response,
        retrieved_contexts=retrieved_contexts,
        system_prompt=system_prompt,
        tool_definitions=tool_definitions,
        tool_calls=tool_calls,
        tool_output=tool_output,
        agent_trace=AgentTrace(
            spans=spans,
            events=events,
            delegations=delegations or [],
            governance_decisions=[
                item.model_dump(mode="json")
                for item in (
                    session.governance_decisions
                    if governance_decisions is None
                    else governance_decisions
                )
            ],
            validations=protected_validations,
        ),
        conversation=[
            {
                "role": message.role,
                "turn_index": message.turn_index,
                "content_hash": message.content_hash,
                **telemetry.protect_content("conversation", message.content),
            }
            for message in session.conversation
        ],
        plan=plan,
    )
