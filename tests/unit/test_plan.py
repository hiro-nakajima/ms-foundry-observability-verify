from __future__ import annotations

from datetime import date

import pytest

from procurement_agent.models import (
    AgentPlanResponse,
    AgentRole,
    ExecutionPlan,
    LogicalPattern,
    PlanGenerationSource,
    PlanStatus,
    PlanStep,
    PlanStepProposal,
    ProcurementRequest,
    RequestConstraints,
)
from procurement_agent.plan import (
    DuplicateStepSuppressed,
    PlanExecutor,
    StructuredPlanBuilder,
)


def complete_request() -> ProcurementRequest:
    return ProcurementRequest(
        request_id="REQ-001",
        query="開発用ノートPC",
        quantity=3,
        applicant_name="山田太郎",
        purpose="開発",
        constraints=RequestConstraints(requested_by=date(2026, 9, 30)),
    )


def test_response_format_is_pydantic_model_and_machine_readable() -> None:
    builder = StructuredPlanBuilder()
    assert builder.response_format is AgentPlanResponse
    schema = builder.response_format.model_json_schema()
    assert schema["properties"]["steps"]["type"] == "array"

    default_plan = builder.build(complete_request(), LogicalPattern.HOSTED_SINGLE)
    proposal = AgentPlanResponse(
        goal="Create draft",
        steps=[
            PlanStepProposal(
                step_id=step.step_id,
                step_type=step.step_type,
                owner=step.owner,
                input_refs=step.input_refs,
            )
            for step in default_plan.steps
        ],
    )
    plan = builder.build(
        complete_request(),
        LogicalPattern.HOSTED_SINGLE,
        raw_response=proposal,
    )
    assert plan.generation_source == PlanGenerationSource.MODEL_STRUCTURED
    assert [step.step_type for step in plan.steps] == [step.step_type for step in default_plan.steps]


@pytest.mark.parametrize("raw", [None, {}, {"goal": "", "steps": []}])
def test_empty_plan_has_explicit_deterministic_default(raw) -> None:
    plan = StructuredPlanBuilder().build(
        complete_request(), LogicalPattern.HOSTED_SINGLE, raw_response=raw
    )
    assert plan.steps
    if raw is None:
        assert plan.generation_source == PlanGenerationSource.DETERMINISTIC_DEFAULT
    else:
        assert plan.generation_source == PlanGenerationSource.EMPTY_RESPONSE_FALLBACK
        assert "empty structured plan response" in plan.warnings[0]


def test_missing_fields_waits_for_user_and_does_not_select_later_step() -> None:
    request = ProcurementRequest(request_id="REQ-002", query="PC")
    plan = StructuredPlanBuilder().build(request, LogicalPattern.HOSTED_SINGLE)
    missing_step = next(step for step in plan.steps if step.step_type == "resolve_missing_fields")
    assert plan.status == PlanStatus.WAITING_USER
    assert missing_step.status == PlanStatus.WAITING_USER
    assert "quantity" in missing_step.completion_reason
    assert PlanExecutor(plan).next_step() is None


def test_duplicate_step_is_suppressed_for_same_version_step_and_input_hash() -> None:
    plan = ExecutionPlan(
        plan_id="plan-test",
        plan_version=1,
        goal="test",
        status=PlanStatus.RUNNING,
        steps=[PlanStep(step_id="S1", step_type="tool", owner=AgentRole.PROCUREMENT_ASSISTANT)],
    )
    completed: list[str] = []
    executor = PlanExecutor(plan, completed)
    executor.start("S1", {"query": "same"})
    executor.complete("S1", tool_call_ids=["tool-1"])
    with pytest.raises(DuplicateStepSuppressed):
        executor.start("S1", {"query": "same"})
    assert [event["event"] for event in executor.events][-1] == "duplicate_step_suppressed"
    assert len(completed) == 1


def test_changed_input_invalidates_only_dependent_steps() -> None:
    plan = ExecutionPlan(
        plan_id="plan-invalidation",
        plan_version=1,
        goal="test invalidation",
        status=PlanStatus.RUNNING,
        steps=[
            PlanStep(step_id="S1", step_type="catalog", owner=AgentRole.PROCUREMENT_ASSISTANT, input_refs=["request.query"]),
            PlanStep(step_id="S2", step_type="item", owner=AgentRole.PROCUREMENT_ASSISTANT, input_refs=["search.candidates"]),
            PlanStep(step_id="S3", step_type="applicant", owner=AgentRole.PROCUREMENT_ASSISTANT, input_refs=["request.applicant_name"]),
        ],
    )
    executor = PlanExecutor(plan)
    executor.start("S1", {"query": "old"})
    executor.complete("S1", output_refs=["search.candidates"])
    executor.start("S2", {"candidate": "one"})
    executor.complete("S2", output_refs=["item"])
    executor.start("S3", {"applicant": "same"})
    executor.complete("S3", output_refs=["applicant"])

    affected = executor.invalidate_by_refs({"request.query"})
    assert affected == ["S1", "S2"]
    assert plan.plan_version == 2
    assert plan.steps[0].status == PlanStatus.PENDING
    assert plan.steps[1].status == PlanStatus.PENDING
    assert plan.steps[2].status == PlanStatus.COMPLETED


def test_block_marks_unpresented_step_and_plan_blocked() -> None:
    plan = ExecutionPlan(
        plan_id="plan-blocked",
        plan_version=1,
        goal="do not present an invalid draft",
        status=PlanStatus.RUNNING,
        steps=[
            PlanStep(
                step_id="S1",
                step_type="present_draft",
                owner=AgentRole.PROCUREMENT_ASSISTANT,
            )
        ],
    )
    step = PlanExecutor(plan).block(
        "S1",
        "deterministic validation failed",
        evidence_refs=["evidence:1"],
        tool_call_ids=["logical-1"],
    )
    assert step.status == PlanStatus.BLOCKED
    assert step.completion_reason == "deterministic validation failed"
    assert step.evidence_refs == ["evidence:1"]
    assert step.tool_call_ids == ["logical-1"]
    assert plan.status == PlanStatus.BLOCKED


def test_refresh_waiting_replaces_stale_missing_field_reason() -> None:
    request = ProcurementRequest(request_id="REQ-WAIT-REFRESH", query="PC")
    plan = StructuredPlanBuilder().build(request, LogicalPattern.HOSTED_SINGLE)
    waiting = next(step for step in plan.steps if step.status == PlanStatus.WAITING_USER)
    refreshed = PlanExecutor(plan).refresh_waiting(
        waiting.step_id, ["applicant_name", "constraints.requested_by"]
    )
    assert refreshed.status == PlanStatus.WAITING_USER
    assert refreshed.completion_reason == (
        "missing required fields: applicant_name, constraints.requested_by"
    )
