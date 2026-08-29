from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from agent_framework import AgentSession as FrameworkAgentSession

from procurement_agent.hosted import build_local_hosted_bundle
from procurement_agent.models import (
    LogicalPattern,
    PlanGenerationSource,
    PlanStatus,
    ProcurementRequest,
    RequestConstraints,
)
from trace_pipeline.completeness import trace_completeness


ROOT = Path(__file__).resolve().parents[2]


def complete_request(request_id: str = "REQ-INTEGRATION", quantity: int = 3) -> ProcurementRequest:
    return ProcurementRequest(
        request_id=request_id,
        query="開発用ノートPC",
        quantity=quantity,
        applicant_name="山田太郎",
        purpose="開発",
        constraints=RequestConstraints(requested_by=date(2026, 9, 30)),
    )


@pytest.mark.integration
@pytest.mark.parametrize("pattern", [LogicalPattern.HOSTED_SINGLE, LogicalPattern.HOSTED_MULTI])
def test_hosted_local_plan_execute_produces_validated_draft(pattern: LogicalPattern) -> None:
    bundle = build_local_hosted_bundle(pattern)
    outcome = asyncio.run(bundle.application.run(complete_request()))
    assert outcome.session.plan.status == PlanStatus.COMPLETED
    assert outcome.session.application_draft.amount.total == 594000
    assert json.loads(outcome.response_text)["validated"] is True
    assert trace_completeness(outcome.envelope)["complete"] is True
    assert outcome.envelope.system_prompt["version"] == "0.1.0"
    assert outcome.envelope.system_prompt["raw_recorded"] is False
    assert all(item["schema_version"] == "1.0" for item in outcome.envelope.tool_definitions)
    assert [item["order"] for item in outcome.envelope.tool_calls] == list(
        range(1, len(outcome.envelope.tool_calls) + 1)
    )
    span_names = {span["name"] for span in outcome.envelope.agent_trace.spans}
    assert {
        "agent.invoke",
        "plan.create",
        "plan.step.execute",
        "skill.request_check",
        "script.calculate_request",
        "governance.pre_input",
        "governance.pre_tool",
        "governance.post_tool",
        "governance.pre_output",
        "validation",
        "response.generate",
    } <= span_names
    assert any(name.startswith("tool.") for name in span_names)
    governance_spans = [
        span for span in outcome.envelope.agent_trace.spans if span["name"].startswith("governance.")
    ]
    assert all("poc.policy.version" in span["attributes"] for span in governance_spans)


@pytest.mark.integration
def test_hosted_multi_uses_two_real_agent_tools_with_isolated_sessions() -> None:
    bundle = build_local_hosted_bundle(LogicalPattern.HOSTED_MULTI)
    tools = bundle.coordinator.default_options["tools"]
    assert [tool.name for tool in tools] == ["procurement_specialist", "drafting_specialist"]
    assert bundle.procurement_tool.additional_properties["propagate_session"] is False
    assert bundle.drafting_tool.additional_properties["propagate_session"] is False

    outcome = asyncio.run(bundle.application.run(complete_request()))
    assert [item["agent_role"] for item in outcome.envelope.agent_trace.delegations] == [
        "procurement_specialist",
        "drafting_specialist",
    ]
    assert all(item["propagate_session"] is False for item in outcome.envelope.agent_trace.delegations)
    assert bundle.procurement_specialist.client.calls[-1]["stream"] is True
    assert bundle.drafting_specialist.client.calls[-1]["stream"] is True
    span_names = {span["name"] for span in outcome.envelope.agent_trace.spans}
    assert "agent_as_tool.procurement_specialist" in span_names
    assert "agent_as_tool.drafting_specialist" in span_names


@pytest.mark.integration
def test_planner_uses_pydantic_response_format_without_tools_and_empty_fallback() -> None:
    bundle = build_local_hosted_bundle(
        LogicalPattern.HOSTED_SINGLE, planner_returns_empty=True
    )
    outcome = asyncio.run(bundle.application.run(complete_request()))
    planner_call = bundle.planner_client.calls[0]
    assert planner_call == {
        "message_count": 1,
        "response_format": "AgentPlanResponse",
        "tool_choice": "none",
        "tool_count": 0,
        "stream": False,
    }
    assert outcome.session.plan.generation_source == PlanGenerationSource.EMPTY_RESPONSE_FALLBACK
    assert "empty structured plan response" in outcome.session.plan.warnings[0]


@pytest.mark.integration
def test_framework_session_round_trip_resumes_waiting_plan() -> None:
    first_bundle = build_local_hosted_bundle(LogicalPattern.HOSTED_SINGLE)
    framework_session = FrameworkAgentSession()
    incomplete = ProcurementRequest(
        request_id="REQ-RESUME",
        query="開発用ノートPC",
        purpose="開発",
    )
    first = asyncio.run(
        first_bundle.coordinator.run(incomplete.model_dump_json(), session=framework_session)
    )
    assert json.loads(first.text)["business_status"] == "WAITING_USER"

    restored = FrameworkAgentSession.from_dict(framework_session.to_dict())
    second_bundle = build_local_hosted_bundle(LogicalPattern.HOSTED_SINGLE)
    second = asyncio.run(
        second_bundle.coordinator.run(
            complete_request(request_id="REQ-RESUME").model_dump_json(), session=restored
        )
    )
    response = json.loads(second.text)
    assert response["observability"]["session_resumed"] is True
    assert response["application_draft"]["amount"]["total"] == "594000"


@pytest.mark.integration
def test_devui_style_same_framework_session_continues_next_turn() -> None:
    bundle = build_local_hosted_bundle(LogicalPattern.HOSTED_SINGLE)
    framework_session = FrameworkAgentSession()
    incomplete = ProcurementRequest(
        request_id="REQ-DEVUI-TURN",
        query="開発用ノートPC",
        purpose="開発",
    )
    first = asyncio.run(
        bundle.coordinator.run(incomplete.model_dump_json(), session=framework_session)
    )
    assert json.loads(first.text)["business_status"] == "WAITING_USER"
    second = asyncio.run(
        bundle.coordinator.run(
            complete_request(request_id="REQ-DEVUI-TURN").model_dump_json(),
            session=framework_session,
        )
    )
    response = json.loads(second.text)
    assert response["observability"]["session_resumed"] is True
    serialized = framework_session.state["procurement-execution-context"][
        "serialized_procurement_session"
    ]
    assert json.loads(serialized)["turn_index"] == 2


@pytest.mark.integration
def test_multi_child_skill_state_is_not_propagated_to_coordinator_session() -> None:
    bundle = build_local_hosted_bundle(LogicalPattern.HOSTED_MULTI)
    framework_session = FrameworkAgentSession()
    response = asyncio.run(
        bundle.coordinator.run(complete_request().model_dump_json(), session=framework_session)
    )
    assert json.loads(response.text)["validated"] is True
    assert "procurement-execution-context" in framework_session.state
    assert "procurement-request-check-skills" not in framework_session.state


@pytest.mark.integration
def test_completed_session_new_plan_does_not_reuse_residual_values() -> None:
    bundle = build_local_hosted_bundle(LogicalPattern.HOSTED_SINGLE)
    first = asyncio.run(bundle.application.run(complete_request("REQ-FIRST", 3)))
    first_plan = first.session.active_plan_id
    second = asyncio.run(
        bundle.application.run(complete_request("REQ-SECOND", 1), session=first.session, resume=False)
    )
    assert second.session.active_plan_id != first_plan
    assert second.session.application_draft.amount.total == 198000
    assert second.session.request.request_id == "REQ-SECOND"


@pytest.mark.integration
@pytest.mark.parametrize(
    ("module", "pattern"),
    [
        ("procurement_agent.devui_app", "HA-S"),
        ("procurement_agent.devui_app", "HA-M"),
        ("procurement_agent.hosted_app", "HA-S"),
        ("procurement_agent.hosted_app", "HA-M"),
    ],
)
def test_local_entrypoint_smoke(module: str, pattern: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", module, "--pattern", pattern, "--smoke"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
        timeout=20,
    )
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload["pattern"] == pattern
