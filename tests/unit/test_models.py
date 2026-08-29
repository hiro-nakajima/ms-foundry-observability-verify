from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from procurement_agent.models import AgentRole, ExecutionPlan, PlanStatus, PlanStep


def test_plan_step_requires_completion_evidence() -> None:
    with pytest.raises(ValidationError):
        PlanStep(
            step_id="S01",
            step_type="parse_request",
            owner=AgentRole.PROCUREMENT_ASSISTANT,
            status=PlanStatus.COMPLETED,
        )


def test_execution_plan_rejects_duplicate_step_ids() -> None:
    now = datetime.now(timezone.utc)
    step = PlanStep(
        step_id="S01",
        step_type="parse_request",
        owner=AgentRole.PROCUREMENT_ASSISTANT,
        status=PlanStatus.COMPLETED,
        started_at=now,
        ended_at=now,
        completion_reason="request parsed",
    )
    with pytest.raises(ValidationError):
        ExecutionPlan(
            plan_id="plan-1",
            plan_version=1,
            goal="create draft",
            steps=[step, step.model_copy()],
        )


def test_plan_status_has_required_states() -> None:
    assert {status.value for status in PlanStatus} == {
        "PENDING",
        "RUNNING",
        "WAITING_USER",
        "COMPLETED",
        "FAILED",
        "BLOCKED",
        "INVALIDATED",
    }
