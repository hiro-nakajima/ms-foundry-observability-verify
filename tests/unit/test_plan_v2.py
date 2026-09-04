import pytest

from procurement_agent.models import (
    AgentRole,
    ExecutionPlan,
    PlanGenerationSource,
    PlanStatus,
    PlanStep,
    StepType,
)
from procurement_agent.plan import (
    APPROVED_STEPS,
    DuplicateStepSuppressed,
    PlanExecutor,
    PlanStateError,
    StructuredPlanBuilder,
)


def approved_model_plan() -> ExecutionPlan:
    return ExecutionPlan(
        plan_id="model-plan",
        steps=[
            PlanStep(step_id=step_id, step_type=step_type, owner=owner, input_refs=refs)
            for step_id, step_type, owner, refs in APPROVED_STEPS
        ],
    )


def test_execution_plan_is_the_pydantic_response_format() -> None:
    assert StructuredPlanBuilder.response_format is ExecutionPlan
    built = StructuredPlanBuilder().build(approved_model_plan())
    assert built.generation_source == PlanGenerationSource.MODEL_STRUCTURED
    assert [step.step_type for step in built.steps] == [
        StepType.CATALOG_SEARCH,
        StepType.CODE_DETERMINATION,
        StepType.MERGE_VALIDATE,
    ]


@pytest.mark.parametrize(
    ("raw", "source"),
    [
        (None, PlanGenerationSource.EMPTY_RESPONSE_FALLBACK),
        ({}, PlanGenerationSource.EMPTY_RESPONSE_FALLBACK),
        ("not-json", PlanGenerationSource.PARSE_FAILURE_FALLBACK),
    ],
)
def test_empty_and_unparseable_plans_use_safe_default(raw, source) -> None:
    plan = StructuredPlanBuilder().build(raw)
    assert plan.generation_source == source
    assert len(plan.steps) == 3


def test_missing_required_step_uses_safe_default() -> None:
    raw = approved_model_plan().model_copy(update={"steps": approved_model_plan().steps[:2]})
    plan = StructuredPlanBuilder().build(raw)
    assert plan.generation_source == PlanGenerationSource.REQUIRED_STEP_FALLBACK
    assert [step.step_id for step in plan.steps] == ["catalog", "code", "merge_validate"]


def test_controller_enforces_order_duplicate_suppression_and_terminal_state() -> None:
    plan = StructuredPlanBuilder().build(approved_model_plan())
    completed: list[str] = []
    executor = PlanExecutor(plan, completed)
    with pytest.raises(PlanStateError, match="step order"):
        executor.start("code", {"wrong": "order"})

    executor.start("catalog", {"query": "pc"})
    executor.complete("catalog", output_refs=["catalog"], reason="grounded")
    plan.steps[0].status = PlanStatus.PENDING
    with pytest.raises(DuplicateStepSuppressed):
        executor.start("catalog", {"query": "pc"})

    plan.steps[0].status = PlanStatus.COMPLETED
    executor.start("code", {"category": "laptop"})
    executor.complete("code", output_refs=["codes"], reason="grounded")
    executor.start("merge_validate", {"catalog": 1, "codes": 1})
    executor.complete("merge_validate", output_refs=["draft"], reason="validated")
    assert plan.status == PlanStatus.COMPLETED
    with pytest.raises(PlanStateError, match="terminal"):
        executor.start("merge_validate", {})


def test_attempt_limit_blocks_replan_loop() -> None:
    plan = StructuredPlanBuilder().build(approved_model_plan())
    executor = PlanExecutor(plan, [], max_attempts=2)
    executor.start("catalog", {"query": "missing-1"})
    executor.retry("catalog", "not found")
    executor.start("catalog", {"query": "missing-2"})
    executor.retry("catalog", "still not found")
    assert plan.status == PlanStatus.BLOCKED
    assert plan.steps[0].owner == AgentRole.CATALOG_SEARCH
