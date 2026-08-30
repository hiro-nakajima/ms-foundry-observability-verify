from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from agent_framework import AgentSession as FrameworkAgentSession

from procurement_agent.governance import GovernanceDenied
from procurement_agent.hosted import build_local_hosted_bundle
from procurement_agent.memory import AgentSession
from procurement_agent.models import (
    GovernanceMode,
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
    call_ids = {item["call_id"] for item in outcome.envelope.tool_calls}
    output_ids = {item["call_id"] for item in outcome.envelope.tool_output}
    step_call_ids = {
        call_id
        for step in outcome.session.plan.steps
        for call_id in step.tool_call_ids
    }
    assert call_ids == output_ids
    assert step_call_ids <= call_ids
    assert all(
        item["provider_call_id"].startswith("tool-")
        for item in outcome.envelope.tool_output
        if "provider_call_id" in item
    )


@pytest.mark.integration
def test_default_trace_envelope_protects_conversation_content() -> None:
    bundle = build_local_hosted_bundle(LogicalPattern.HOSTED_SINGLE)
    outcome = asyncio.run(bundle.application.run(complete_request()))
    serialized = outcome.envelope.model_dump_json()
    assert "山田太郎" not in serialized
    assert "開発用ノートPC" not in serialized
    assert all("content" not in item for item in outcome.envelope.conversation)
    assert all(item["raw_recorded"] is False for item in outcome.envelope.conversation)
    assert all(item["ref"].startswith("protected:conversation:") for item in outcome.envelope.conversation)


@pytest.mark.integration
def test_enforce_pre_input_denial_does_not_mutate_session() -> None:
    bundle = build_local_hosted_bundle(
        LogicalPattern.HOSTED_SINGLE,
        governance_mode=GovernanceMode.ENFORCE,
    )
    session = AgentSession()
    request = complete_request(request_id="REQ-REJECTED-INPUT").model_copy(
        update={"query": "password=synthetic-test-value"}
    )
    with pytest.raises(GovernanceDenied):
        asyncio.run(bundle.application.run(request, session=session))
    assert session.turn_index == 0
    assert session.conversation == []
    assert "synthetic-test-value" not in session.serialize()


@pytest.mark.integration
def test_failed_validation_details_are_protected_in_trace_envelope() -> None:
    bundle = build_local_hosted_bundle(LogicalPattern.HOSTED_SINGLE)
    constraints = RequestConstraints(
        requested_by=date(2026, 9, 30),
        budget_limit="100000",
        specifications={"memory": "64GB"},
    )
    outcome = asyncio.run(
        bundle.application.run(
            complete_request().model_copy(update={"constraints": constraints})
        )
    )
    serialized = outcome.envelope.model_dump_json()
    assert "100000" not in serialized
    assert "64GB" not in serialized
    validation = outcome.envelope.agent_trace.validations[0]
    assert validation["valid"] is False
    assert validation["violation_count"] == 2
    assert "violations" not in validation
    assert validation["raw_recorded"] is False
    assert validation["ref"].startswith("protected:validation:")


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
    assert "tool.validate_application" in span_names
    validation_calls = [
        item for item in outcome.envelope.tool_calls if item["tool_name"] == "validate_application"
    ]
    assert len(validation_calls) == 1
    assert validation_calls[0]["agent_role"] == "coordinator"
    assert any(
        item.tool_name == "validate_application" and item.agent_role.value == "coordinator"
        for item in outcome.session.governance_decisions
    )
    decisions = outcome.envelope.agent_trace.governance_decisions
    outer_pre = next(
        index
        for index, decision in enumerate(decisions)
        if decision["stage"] == "pre_tool"
        and decision["agent_role"] == "coordinator"
        and decision["tool_name"] == "procurement_specialist"
    )
    child_pre = next(
        index
        for index, decision in enumerate(decisions)
        if decision["stage"] == "pre_tool"
        and decision["agent_role"] == "procurement_specialist"
        and decision["tool_name"] == "search_catalog"
    )
    outer_post = next(
        index
        for index, decision in enumerate(decisions)
        if decision["stage"] == "post_tool"
        and decision["agent_role"] == "coordinator"
        and decision["tool_name"] == "procurement_specialist"
    )
    assert outer_pre < child_pre < outer_post


@pytest.mark.integration
def test_hosted_multi_propagates_missing_tax_rule_as_business_failure() -> None:
    bundle = build_local_hosted_bundle(LogicalPattern.HOSTED_MULTI)
    bundle.support.adapter.tax_rules[0]["valid_to"] = "2026-01-01"
    outcome = asyncio.run(
        bundle.application.run(complete_request(request_id="REQ-NO-TAX-RULE"))
    )
    response = json.loads(outcome.response_text)
    assert response["technical_status"] == "SUCCESS"
    assert response["business_status"] == "NOT_FOUND"
    assert response["failed_tool"] == "calculate_request"
    assert response["delegation_tool"] == "drafting_specialist"
    assert outcome.session.plan.status == PlanStatus.BLOCKED
    assert response["observability"]["governance_decisions"] == [
        decision["outcome"]
        for decision in outcome.envelope.agent_trace.governance_decisions
    ]


@pytest.mark.integration
@pytest.mark.parametrize("pattern", [LogicalPattern.HOSTED_SINGLE, LogicalPattern.HOSTED_MULTI])
def test_requested_specification_selects_matching_catalog_item(pattern: LogicalPattern) -> None:
    bundle = build_local_hosted_bundle(pattern)
    request = complete_request(quantity=1).model_copy(
        update={
            "query": "ノートPC",
            "constraints": RequestConstraints(
                requested_by=date(2026, 9, 30),
                budget_limit="150000",
                specifications={"memory": "16GB"},
            ),
        }
    )
    outcome = asyncio.run(bundle.application.run(request))
    response = json.loads(outcome.response_text)
    assert response["business_status"] == "SUCCESS"
    assert response["application_draft"]["item"]["product_code"] == "LAPTOP-OFFICE-13"
    assert response["application_draft"]["amount"]["total"] == "132000"


@pytest.mark.integration
@pytest.mark.parametrize("pattern", [LogicalPattern.HOSTED_SINGLE, LogicalPattern.HOSTED_MULTI])
def test_ambiguous_catalog_waits_then_resumes_with_specification(
    pattern: LogicalPattern,
) -> None:
    bundle = build_local_hosted_bundle(pattern)
    initial = complete_request(request_id="REQ-CATALOG-CLARIFY", quantity=1).model_copy(
        update={
            "query": "ノートPC",
            "constraints": RequestConstraints(requested_by=date(2026, 9, 30)),
        }
    )
    first = asyncio.run(bundle.application.run(initial))
    response = json.loads(first.response_text)
    assert response["business_status"] == "WAITING_USER"
    assert response["missing_required_fields"] == []
    assert response["clarification"]["field"] == "catalog_item"
    assert {
        option["product_code"] for option in response["clarification"]["options"]
    } == {"LAPTOP-DEV-14", "LAPTOP-OFFICE-13"}
    waiting_step = next(
        step for step in first.session.plan.steps if step.status == PlanStatus.WAITING_USER
    )
    assert waiting_step.step_id == "S03"
    assert waiting_step.tool_call_ids
    plan_id = first.session.active_plan_id

    clarified = initial.model_copy(
        update={
            "constraints": RequestConstraints(
                requested_by=date(2026, 9, 30),
                specifications={"memory": "16GB"},
            )
        }
    )
    second = asyncio.run(
        bundle.application.run(clarified, session=first.session, resume=True)
    )
    final = json.loads(second.response_text)
    assert final["business_status"] == "SUCCESS"
    assert final["application_draft"]["item"]["product_code"] == "LAPTOP-OFFICE-13"
    assert second.session.active_plan_id == plan_id
    assert second.session.plan.plan_version == 2


@pytest.mark.integration
def test_irrelevant_follow_up_does_not_resume_catalog_clarification() -> None:
    bundle = build_local_hosted_bundle(LogicalPattern.HOSTED_SINGLE)
    initial = complete_request(request_id="REQ-CLARIFY-STILL-WAITING", quantity=1).model_copy(
        update={"query": "ノートPC"}
    )
    first = asyncio.run(bundle.application.run(initial))
    follow_up = initial.model_copy(update={"purpose": "検証環境"})
    second = asyncio.run(
        bundle.application.run(follow_up, session=first.session, resume=True)
    )
    response = json.loads(second.response_text)
    assert response["business_status"] == "WAITING_USER"
    assert response["clarification"]["field"] == "catalog_item"
    assert second.session.plan.plan_version == 1
    assert second.session.plan.status == PlanStatus.WAITING_USER
    assert second.envelope.tool_calls == [{"status": "not-executed"}]
    decisions = second.envelope.agent_trace.governance_decisions
    assert len(decisions) == 1
    assert decisions[0]["stage"] == "pre_input"


@pytest.mark.integration
def test_completed_plan_replay_records_only_current_invocation_governance() -> None:
    bundle = build_local_hosted_bundle(LogicalPattern.HOSTED_SINGLE)
    request = complete_request(request_id="REQ-REPLAY-TRACE")
    first = asyncio.run(bundle.application.run(request))
    second = asyncio.run(
        bundle.application.run(request, session=first.session, resume=True)
    )
    decisions = second.envelope.agent_trace.governance_decisions
    assert [decision["stage"] for decision in decisions] == [
        "pre_input",
        "pre_output",
    ]
    assert second.envelope.tool_calls == [{"status": "not-executed"}]


@pytest.mark.integration
@pytest.mark.parametrize("pattern", [LogicalPattern.HOSTED_SINGLE, LogicalPattern.HOSTED_MULTI])
def test_catalog_clarification_accepts_exact_product_code(
    pattern: LogicalPattern,
) -> None:
    bundle = build_local_hosted_bundle(pattern)
    initial = complete_request(request_id="REQ-CLARIFY-BY-CODE", quantity=1).model_copy(
        update={"query": "ノートPC"}
    )
    first = asyncio.run(bundle.application.run(initial))
    assert json.loads(first.response_text)["business_status"] == "WAITING_USER"

    clarified = initial.model_copy(update={"query": "LAPTOP-DEV-14"})
    second = asyncio.run(
        bundle.application.run(clarified, session=first.session, resume=True)
    )
    response = json.loads(second.response_text)
    assert response["business_status"] == "SUCCESS"
    assert response["application_draft"]["item"]["product_code"] == "LAPTOP-DEV-14"


@pytest.mark.integration
@pytest.mark.parametrize("pattern", [LogicalPattern.HOSTED_SINGLE, LogicalPattern.HOSTED_MULTI])
def test_ambiguous_applicant_waits_then_resumes_with_employee_id(
    pattern: LogicalPattern,
) -> None:
    bundle = build_local_hosted_bundle(pattern)
    initial = complete_request(request_id="REQ-APPLICANT-CLARIFY", quantity=1).model_copy(
        update={"applicant_name": "架空"}
    )
    first = asyncio.run(bundle.application.run(initial))
    response = json.loads(first.response_text)
    assert response["business_status"] == "WAITING_USER"
    assert response["clarification"]["field"] == "applicant_name"
    assert {
        option["employee_id"] for option in response["clarification"]["options"]
    } == {"EMP-001", "EMP-002"}
    waiting_step = next(
        step for step in first.session.plan.steps if step.status == PlanStatus.WAITING_USER
    )
    assert waiting_step.tool_call_ids
    plan_id = first.session.active_plan_id

    clarified = initial.model_copy(update={"applicant_name": "EMP-002"})
    second = asyncio.run(
        bundle.application.run(clarified, session=first.session, resume=True)
    )
    final = json.loads(second.response_text)
    assert final["business_status"] == "SUCCESS"
    assert final["application_draft"]["applicant"]["employee_id"] == "EMP-002"
    assert second.session.active_plan_id == plan_id
    assert second.session.plan.plan_version == 2


@pytest.mark.integration
@pytest.mark.parametrize("pattern", [LogicalPattern.HOSTED_SINGLE, LogicalPattern.HOSTED_MULTI])
def test_clarification_accumulates_changes_across_waiting_turns(
    pattern: LogicalPattern,
) -> None:
    bundle = build_local_hosted_bundle(pattern)
    initial = complete_request(request_id="REQ-CLARIFY-ACCUMULATE", quantity=1).model_copy(
        update={"applicant_name": "架空"}
    )
    first = asyncio.run(bundle.application.run(initial))
    assert json.loads(first.response_text)["business_status"] == "WAITING_USER"

    changed_query = initial.model_copy(update={"query": "一般業務用ノートPC"})
    second = asyncio.run(
        bundle.application.run(changed_query, session=first.session, resume=True)
    )
    assert json.loads(second.response_text)["business_status"] == "WAITING_USER"
    assert second.session.governance_state["clarification_changed_refs"] == [
        "request.query"
    ]

    clarified = changed_query.model_copy(update={"applicant_name": "EMP-002"})
    third = asyncio.run(
        bundle.application.run(clarified, session=second.session, resume=True)
    )
    response = json.loads(third.response_text)
    assert response["business_status"] == "SUCCESS"
    assert response["application_draft"]["item"]["product_code"] == "LAPTOP-OFFICE-13"
    assert response["application_draft"]["applicant"]["employee_id"] == "EMP-002"
    assert "clarification_changed_refs" not in third.session.governance_state


@pytest.mark.integration
@pytest.mark.parametrize("pattern", [LogicalPattern.HOSTED_SINGLE, LogicalPattern.HOSTED_MULTI])
def test_explicit_department_must_match_applicant_department(
    pattern: LogicalPattern,
) -> None:
    bundle = build_local_hosted_bundle(pattern)
    request = complete_request(request_id="REQ-DEPARTMENT-MISMATCH").model_copy(
        update={"department_name": "運用一部"}
    )
    outcome = asyncio.run(bundle.application.run(request))
    response = json.loads(outcome.response_text)
    assert response["technical_status"] == "SUCCESS"
    assert response["business_status"] == "VALIDATION_FAILED"
    assert response["failed_tool"] == "lookup_department"
    assert "application_draft" not in response
    assert outcome.session.application_draft is None
    assert outcome.session.plan.status == PlanStatus.BLOCKED
    assert len(response["evidence_refs"]) == 2


@pytest.mark.integration
@pytest.mark.parametrize("pattern", [LogicalPattern.HOSTED_SINGLE, LogicalPattern.HOSTED_MULTI])
def test_matching_explicit_department_is_accepted(pattern: LogicalPattern) -> None:
    bundle = build_local_hosted_bundle(pattern)
    request = complete_request(request_id="REQ-DEPARTMENT-MATCH").model_copy(
        update={"department_name": "開発一部"}
    )
    outcome = asyncio.run(bundle.application.run(request))
    response = json.loads(outcome.response_text)
    assert response["business_status"] == "SUCCESS"
    assert response["application_draft"]["applicant"]["department_code"] == "DPT-DEV-01"


@pytest.mark.integration
@pytest.mark.parametrize("pattern", [LogicalPattern.HOSTED_SINGLE, LogicalPattern.HOSTED_MULTI])
def test_ambiguous_department_waits_then_resumes_without_duplicate_lookup(
    pattern: LogicalPattern,
) -> None:
    bundle = build_local_hosted_bundle(pattern)
    initial = complete_request(request_id="REQ-DEPARTMENT-CLARIFY").model_copy(
        update={"department_name": "一部"}
    )
    first = asyncio.run(bundle.application.run(initial))
    response = json.loads(first.response_text)
    assert response["business_status"] == "WAITING_USER"
    assert response["clarification"]["field"] == "department_name"
    assert len(response["clarification"]["options"]) == 2

    clarified = initial.model_copy(update={"department_name": "開発一部"})
    second = asyncio.run(
        bundle.application.run(clarified, session=first.session, resume=True)
    )
    final = json.loads(second.response_text)
    assert final["business_status"] == "SUCCESS"
    assert final["application_draft"]["applicant"]["department_code"] == "DPT-DEV-01"


@pytest.mark.integration
@pytest.mark.parametrize("pattern", [LogicalPattern.HOSTED_SINGLE, LogicalPattern.HOSTED_MULTI])
@pytest.mark.parametrize(
    "constraints",
    [
        RequestConstraints(requested_by=date(2026, 9, 30), budget_limit="100000"),
        RequestConstraints(
            requested_by=date(2026, 9, 30), specifications={"memory": "64GB"}
        ),
    ],
)
def test_unmet_purchase_constraint_is_business_failure_without_draft_presentation(
    pattern: LogicalPattern, constraints: RequestConstraints
) -> None:
    bundle = build_local_hosted_bundle(pattern)
    request = complete_request().model_copy(update={"constraints": constraints})
    outcome = asyncio.run(bundle.application.run(request))
    response = json.loads(outcome.response_text)
    assert response["business_status"] == "VALIDATION_FAILED"
    assert response["validated"] is False
    assert "application_draft" not in response
    assert outcome.session.plan.status == PlanStatus.BLOCKED
    assert outcome.session.plan.steps[-1].status == PlanStatus.BLOCKED
    assert outcome.envelope.run.technical_status == "SUCCESS"
    assert outcome.envelope.response["business_status"] == "VALIDATION_FAILED"
    assert any("constraint." in violation for violation in response["violations"])
    assert response["observability"]["governance_decisions"] == [
        decision["outcome"]
        for decision in outcome.envelope.agent_trace.governance_decisions
    ]


@pytest.mark.integration
@pytest.mark.parametrize("pattern", [LogicalPattern.HOSTED_SINGLE, LogicalPattern.HOSTED_MULTI])
def test_ambiguous_query_with_zero_spec_matches_is_validation_failure(
    pattern: LogicalPattern,
) -> None:
    bundle = build_local_hosted_bundle(pattern)
    request = complete_request().model_copy(
        update={
            "query": "ノートPC",
            "constraints": RequestConstraints(
                requested_by=date(2026, 9, 30),
                specifications={"memory": "64GB"},
            ),
        }
    )
    outcome = asyncio.run(bundle.application.run(request))
    response = json.loads(outcome.response_text)
    assert response["business_status"] == "VALIDATION_FAILED"
    assert response["validated"] is False
    assert "clarification" not in response
    assert any("constraint.specifications unmet" in item for item in response["violations"])


@pytest.mark.integration
@pytest.mark.parametrize("pattern", [LogicalPattern.HOSTED_SINGLE, LogicalPattern.HOSTED_MULTI])
def test_unmet_requested_delivery_date_is_validation_failure(pattern: LogicalPattern) -> None:
    bundle = build_local_hosted_bundle(pattern)
    constraints = RequestConstraints(requested_by=date(2026, 8, 29))
    outcome = asyncio.run(
        bundle.application.run(
            complete_request().model_copy(update={"constraints": constraints})
        )
    )
    response = json.loads(outcome.response_text)
    assert response["business_status"] == "VALIDATION_FAILED"
    assert response["validated"] is False
    assert "application_draft" not in response
    assert any("constraint.requested_by" in item for item in response["violations"])
    assert "requested delivery date cannot be met" in outcome.session.application_draft.warnings


@pytest.mark.integration
@pytest.mark.parametrize("pattern", [LogicalPattern.HOSTED_SINGLE, LogicalPattern.HOSTED_MULTI])
def test_enforce_mode_returns_structured_validation_failure(pattern: LogicalPattern) -> None:
    bundle = build_local_hosted_bundle(pattern, governance_mode=GovernanceMode.ENFORCE)
    constraints = RequestConstraints(
        requested_by=date(2026, 9, 30),
        budget_limit="100000",
    )
    outcome = asyncio.run(
        bundle.application.run(
            complete_request().model_copy(update={"constraints": constraints})
        )
    )
    response = json.loads(outcome.response_text)
    assert response["business_status"] == "VALIDATION_FAILED"
    assert response["validated"] is False
    assert "application_draft" not in response
    assert outcome.session.plan.status == PlanStatus.BLOCKED
    assert outcome.session.plan.steps[-1].status == PlanStatus.BLOCKED
    assert outcome.envelope.run.technical_status == "SUCCESS"
    pre_output_decisions = [
        decision
        for decision in outcome.session.governance_decisions
        if decision.stage == "pre_output"
    ]
    assert pre_output_decisions
    assert pre_output_decisions[-1].outcome.value == "ALLOW"


@pytest.mark.integration
@pytest.mark.parametrize("pattern", [LogicalPattern.HOSTED_SINGLE, LogicalPattern.HOSTED_MULTI])
@pytest.mark.parametrize(
    ("request_case", "expected_status"),
    [
        (
            ProcurementRequest(
                request_id="REQ-NOT-FOUND",
                query="存在しない商品",
                quantity=1,
                applicant_name="山田太郎",
                purpose="開発",
                constraints=RequestConstraints(requested_by=date(2026, 9, 30)),
            ),
            "NOT_FOUND",
        ),
        (complete_request("REQ-STOCK", 100), "INSUFFICIENT_STOCK"),
    ],
)
def test_structured_tool_business_failure_blocks_plan_without_exception(
    pattern: LogicalPattern,
    request_case: ProcurementRequest,
    expected_status: str,
) -> None:
    bundle = build_local_hosted_bundle(pattern)
    outcome = asyncio.run(bundle.application.run(request_case))
    response = json.loads(outcome.response_text)
    assert response["technical_status"] == "SUCCESS"
    assert response["business_status"] == expected_status
    assert outcome.session.plan.status == PlanStatus.BLOCKED
    assert any(step.status == PlanStatus.BLOCKED for step in outcome.session.plan.steps)
    blocked_step = next(
        step for step in outcome.session.plan.steps if step.status == PlanStatus.BLOCKED
    )
    assert blocked_step.tool_call_ids
    assert set(blocked_step.tool_call_ids) <= {
        item["call_id"] for item in outcome.envelope.tool_calls
    }
    assert outcome.envelope.run.technical_status == "SUCCESS"
    assert outcome.envelope.response["business_status"] == expected_status
    assert any(
        item.get("business_status") == expected_status
        for item in outcome.envelope.tool_output
    )
    if pattern == LogicalPattern.HOSTED_MULTI:
        expected_tool = (
            "search_catalog" if expected_status == "NOT_FOUND" else "estimate_delivery"
        )
        assert response["failed_tool"] == expected_tool
        assert response["delegation_tool"] == "procurement_specialist"


@pytest.mark.integration
@pytest.mark.parametrize("pattern", [LogicalPattern.HOSTED_SINGLE, LogicalPattern.HOSTED_MULTI])
def test_concurrent_runs_keep_invocation_local_ledgers(pattern: LogicalPattern) -> None:
    async def exercise():
        bundle = build_local_hosted_bundle(pattern)
        application = bundle.application
        original_create_plan = application._create_plan
        both_entered = asyncio.Event()
        entered = 0

        async def overlapping_create_plan(request):
            nonlocal entered
            entered += 1
            if entered == 2:
                both_entered.set()
            await asyncio.wait_for(both_entered.wait(), timeout=2)
            return await original_create_plan(request)

        application._create_plan = overlapping_create_plan
        return await asyncio.gather(
            application.run(complete_request("REQ-CONCURRENT-1", 1)),
            application.run(complete_request("REQ-CONCURRENT-2", 2)),
        )

    first, second = asyncio.run(exercise())
    assert first.session.application_draft.amount.total == 198000
    assert second.session.application_draft.amount.total == 396000
    first_ids = {item["call_id"] for item in first.envelope.tool_calls}
    second_ids = {item["call_id"] for item in second.envelope.tool_calls}
    assert first_ids
    assert second_ids
    assert first_ids.isdisjoint(second_ids)
    assert [item["order"] for item in first.envelope.tool_calls] == list(
        range(1, len(first.envelope.tool_calls) + 1)
    )
    assert [item["order"] for item in second.envelope.tool_calls] == list(
        range(1, len(second.envelope.tool_calls) + 1)
    )


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
@pytest.mark.parametrize("pattern", [LogicalPattern.HOSTED_SINGLE, LogicalPattern.HOSTED_MULTI])
def test_framework_session_resumes_catalog_clarification(
    pattern: LogicalPattern,
) -> None:
    bundle = build_local_hosted_bundle(pattern)
    framework_session = FrameworkAgentSession()
    initial = complete_request(request_id="REQ-FRAMEWORK-CLARIFY", quantity=1).model_copy(
        update={"query": "ノートPC"}
    )
    first = asyncio.run(
        bundle.coordinator.run(initial.model_dump_json(), session=framework_session)
    )
    assert json.loads(first.text)["business_status"] == "WAITING_USER"

    clarified = initial.model_copy(
        update={
            "constraints": RequestConstraints(
                requested_by=date(2026, 9, 30),
                specifications={"memory": "32GB"},
            )
        }
    )
    second = asyncio.run(
        bundle.coordinator.run(clarified.model_dump_json(), session=framework_session)
    )
    response = json.loads(second.text)
    assert response["business_status"] == "SUCCESS"
    assert response["application_draft"]["item"]["product_code"] == "LAPTOP-DEV-14"
    assert response["observability"]["session_resumed"] is True


@pytest.mark.integration
def test_partial_follow_up_keeps_plan_waiting_for_remaining_fields() -> None:
    bundle = build_local_hosted_bundle(LogicalPattern.HOSTED_SINGLE)
    initial = ProcurementRequest(
        request_id="REQ-PARTIAL-RESUME",
        query="開発用ノートPC",
        purpose="開発",
    )
    first = asyncio.run(bundle.application.run(initial))
    plan_id = first.session.active_plan_id
    partial = ProcurementRequest(
        request_id="REQ-PARTIAL-RESUME",
        query="開発用ノートPC",
        quantity=3,
    )
    second = asyncio.run(
        bundle.application.run(partial, session=first.session, resume=True)
    )
    response = json.loads(second.response_text)
    assert response["business_status"] == "WAITING_USER"
    assert response["missing_required_fields"] == [
        "applicant_name",
        "constraints.requested_by",
    ]
    assert second.session.active_plan_id == plan_id
    assert second.session.plan.status == PlanStatus.WAITING_USER
    assert second.session.request.purpose == "開発"
    waiting_step = next(
        step for step in second.session.plan.steps if step.status == PlanStatus.WAITING_USER
    )
    assert waiting_step.completion_reason == (
        "missing required fields: applicant_name, constraints.requested_by"
    )
    assert "quantity" not in waiting_step.completion_reason
    assert second.envelope.tool_calls == [{"status": "not-executed"}]


@pytest.mark.integration
def test_unchanged_completed_framework_request_reuses_plan_without_tool_reexecution() -> None:
    bundle = build_local_hosted_bundle(LogicalPattern.HOSTED_SINGLE)
    framework_session = FrameworkAgentSession()
    request = complete_request(request_id="REQ-COMPLETED-RETRY")
    first = asyncio.run(
        bundle.coordinator.run(request.model_dump_json(), session=framework_session)
    )
    first_response = json.loads(first.text)
    first_serialized = framework_session.state["procurement-execution-context"][
        "serialized_procurement_session"
    ]
    first_session = json.loads(first_serialized)
    planner_calls = len(bundle.planner_client.calls)

    second = asyncio.run(
        bundle.coordinator.run(request.model_dump_json(), session=framework_session)
    )
    second_response = json.loads(second.text)
    second_serialized = framework_session.state["procurement-execution-context"][
        "serialized_procurement_session"
    ]
    second_session = json.loads(second_serialized)
    assert first_response["business_status"] == "SUCCESS"
    assert second_response["business_status"] == "SUCCESS"
    assert second_response["observability"]["session_resumed"] is True
    assert second_session["active_plan_id"] == first_session["active_plan_id"]
    assert second_session["completed_step_keys"] == first_session["completed_step_keys"]
    assert len(bundle.planner_client.calls) == planner_calls


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
    assert second.envelope.agent_trace.governance_decisions


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
