from __future__ import annotations

from datetime import date

from procurement_agent.memory import AgentSession, InMemoryContextProvider
from procurement_agent.models import LogicalPattern, ProcurementRequest, RequestConstraints
from procurement_agent.plan import StructuredPlanBuilder


def _request(request_id: str = "REQ-001", quantity: int = 3) -> ProcurementRequest:
    return ProcurementRequest(
        request_id=request_id,
        query="開発用ノートPC",
        quantity=quantity,
        applicant_name="山田太郎",
        purpose="開発",
        constraints=RequestConstraints(requested_by=date(2026, 9, 30)),
    )


def test_session_serializes_and_restores_plan_and_conversation() -> None:
    session = AgentSession()
    request = _request()
    plan = StructuredPlanBuilder().build(request, LogicalPattern.HOSTED_SINGLE)
    session.start_new_plan(request, plan)
    session.begin_turn("開発用PCを3台")
    restored = AgentSession.restore(session.serialize())
    assert restored.session_id == session.session_id
    assert restored.plan == session.plan
    assert restored.request == request
    assert restored.conversation[0].content_hash == session.conversation[0].content_hash


def test_new_plan_clears_residual_execution_state() -> None:
    session = AgentSession()
    first_request = _request()
    first_plan = StructuredPlanBuilder().build(first_request, LogicalPattern.HOSTED_SINGLE)
    session.start_new_plan(first_request, first_plan)
    session.evidence["catalog"] = {"old": True}
    session.completed_step_keys.append("1:S1:hash")

    second_request = _request("REQ-002", quantity=1)
    second_plan = StructuredPlanBuilder().build(second_request, LogicalPattern.HOSTED_SINGLE)
    session.start_new_plan(second_request, second_plan)
    assert session.evidence == {}
    assert session.completed_step_keys == []
    assert session.request.quantity == 1
    assert session.active_plan_id == second_plan.plan_id


def test_context_provider_injects_resume_state_without_raw_ids() -> None:
    session = AgentSession()
    request = _request()
    plan = StructuredPlanBuilder().build(request, LogicalPattern.HOSTED_SINGLE)
    session.start_new_plan(request, plan)
    session.begin_turn("continue")
    context = InMemoryContextProvider().before_invocation(
        session, user_input="continue", resumed=True
    )
    assert context.resumed is True
    assert context.next_step_type == "resolve_missing_fields"
    assert context.session_id_hash != session.session_id
    assert context.request.quantity == 3


def test_request_update_reports_exact_changed_refs() -> None:
    session = AgentSession(request=_request())
    changed = session.apply_request_update(
        {"quantity": 5, "constraints": {"requested_by": date(2026, 10, 15)}}
    )
    assert changed == {"request.quantity", "request.constraints.requested_by"}
    assert session.request.quantity == 5


def test_waiting_session_can_serialize_restore_and_resume() -> None:
    request = ProcurementRequest(request_id="REQ-WAIT", query="開発用PC", purpose="開発")
    plan = StructuredPlanBuilder().build(request, LogicalPattern.HOSTED_SINGLE)
    session = AgentSession()
    session.start_new_plan(request, plan)
    restored = AgentSession.restore(session.serialize())
    changed = restored.apply_request_update(
        {
            "quantity": 3,
            "applicant_name": "山田太郎",
            "constraints": {"requested_by": date(2026, 9, 30)},
        }
    )
    assert changed == {
        "request.quantity",
        "request.applicant_name",
        "request.constraints.requested_by",
    }
    executor = restored.plan_executor()
    waiting = next(step for step in restored.plan.steps if step.step_type == "resolve_missing_fields")
    executor.resume_after_user_input(waiting.step_id)
    assert restored.plan.status.value == "RUNNING"
    assert executor.next_step().step_id == waiting.step_id
