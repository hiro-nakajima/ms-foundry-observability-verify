"""Deterministic Plan & Execute controller for the single E2E architecture."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Awaitable, Callable, TypeVar
from uuid import uuid4

from agent_framework import AgentSession
from pydantic import BaseModel, ValidationError

from .models import (
    ApplicationDraft, ApplicationLine, BusinessStatus, CatalogSearchInput,
    CatalogSearchResult, CodeDeterminationInput, CodeDeterminationResult,
    CorrelationContext, ExecutionPlan, OperationStatus, ProcurementRequest,
    ScenarioResult, TechnicalStatus,
)
from .observability import TelemetryRecorder
from .plan import PlanExecutor, StructuredPlanBuilder
from .session_state import initialize_execution_state, load_execution_state, save_execution_state

T = TypeVar("T", bound=BaseModel)
StructuredInvoker = Callable[[BaseModel], Awaitable[dict[str, Any] | BaseModel]]


def correlation(*, state, session: AgentSession, step_id: str, attempt: int) -> CorrelationContext:
    assert state.plan is not None
    return CorrelationContext(
        test_case_id=state.test_case_id,
        framework_session_id=session.session_id,
        turn_number=max(state.turn_number, 1),
        plan_id=state.plan.plan_id,
        plan_version=state.plan.version,
        step_id=step_id,
        attempt=attempt,
        remote_task_id=f"task-{uuid4()}",
        parent_invocation_id=f"parent-{uuid4()}",
    )


async def invoke_validated(invoker: StructuredInvoker, payload: BaseModel, result_type: type[T]) -> T:
    """Validate both sides of the parent/child boundary before state mutation."""
    validated_input = type(payload).model_validate(payload.model_dump(mode="json"))
    raw = await invoker(validated_input)
    try:
        return result_type.model_validate(raw.model_dump(mode="json") if isinstance(raw, BaseModel) else raw)
    except ValidationError as exc:
        raise ValueError(f"structured child output failed boundary validation: {exc.error_count()}") from exc


class ProcurementController:
    def __init__(self, catalog_invoker: StructuredInvoker, code_invoker: StructuredInvoker, *, telemetry: TelemetryRecorder | None = None) -> None:
        self.catalog_invoker = catalog_invoker
        self.code_invoker = code_invoker
        self.telemetry = telemetry or TelemetryRecorder()

    async def execute(
        self, request: ProcurementRequest, *, session: AgentSession | None,
        test_case_id: str, raw_plan: ExecutionPlan | dict[str, Any] | str | None = None,
    ) -> ScenarioResult:
        if session is None:
            raise ValueError("Framework AgentSession is required; implicit sessions are forbidden")
        state = load_execution_state(session, required=False)
        if state is None:
            state = initialize_execution_state(session, test_case_id=test_case_id)
        state.turn_number += 1
        state.test_case_id = test_case_id
        state.request = request
        with self.telemetry.span("plan.create", {"test.case.id": test_case_id, "app.session.id": session.session_id, "app.turn.number": state.turn_number}) as span:
            previous_version = state.plan.version if state.plan else 0
            state.plan = StructuredPlanBuilder().build(raw_plan)
            state.plan.version = previous_version + 1
            self.telemetry.event(span, "plan.created", {"plan.id": state.plan.plan_id, "plan.version": state.plan.version})
        executor = PlanExecutor(state.plan, state.completed_step_keys)
        save_execution_state(session, state)

        step = executor.start("catalog", request.model_dump(mode="json"))
        state.current_step_id = step.step_id
        save_execution_state(session, state)
        catalog_input = CatalogSearchInput(
            query=request.query, quantity=request.quantity, constraints=request.constraints,
            correlation=correlation(state=state, session=session, step_id="catalog", attempt=step.attempt),
        )
        with self.telemetry.span("plan.step.execute", {"test.case.id": test_case_id, "plan.id": state.plan.plan_id, "plan.version": state.plan.version, "plan.step.id": "catalog", "execution.attempt": step.attempt, "agent.role": "catalog_search"}) as catalog_span:
            self.telemetry.event(catalog_span, "step.started", {"plan.step.id": "catalog", "execution.attempt": step.attempt})
            self.telemetry.event(catalog_span, "handoff.payload_validated", {"agent.role": "catalog_search"})
            catalog = await invoke_validated(self.catalog_invoker, catalog_input, CatalogSearchResult)
            if catalog.status.business_status == BusinessStatus.SUCCESS and catalog.selected_product_code:
                self.telemetry.event(catalog_span, "step.completed", {"plan.step.id": "catalog"})
            else:
                self.telemetry.event(catalog_span, "result.rejected", {"business.status": catalog.status.business_status})
                self.telemetry.event(catalog_span, "step.retry_scheduled", {"execution.attempt": step.attempt + 1})
                self.telemetry.event(catalog_span, "plan.replanned", {"business.status": "WAITING_USER"})
        state.catalog_result = catalog
        if catalog.status.business_status != BusinessStatus.SUCCESS or not catalog.selected_product_code:
            executor.retry("catalog", catalog.status.reason_code or "catalog search did not identify a product")
            if state.plan.status.name != "BLOCKED":
                executor.start("catalog", request.model_dump(mode="json") | {"replan": True})
                executor.wait_for_user("catalog", "catalog item not found after retry; user confirmation required")
            save_execution_state(session, state)
            return ScenarioResult(
                scenario_id="S3", test_case_id=test_case_id,
                technical_status=catalog.status.technical_status,
                business_status=BusinessStatus.WAITING_USER,
                status=catalog.status,
                trace={"events": executor.events},
                next_action="候補名または型番をユーザーに確認し、新しいPlan versionで再開する",
            )
        executor.complete("catalog", output_refs=[item.evidence_id for item in catalog.candidates], reason="grounded catalog candidate selected")
        state.evidence_refs.extend(item.evidence_id for item in catalog.evidence)
        selected = next(item for item in catalog.candidates if item.product_code == catalog.selected_product_code)

        step = executor.start("code", {"product_code": selected.product_code, "category": selected.category, "department_name": request.department_name})
        state.current_step_id = step.step_id
        save_execution_state(session, state)
        code_input = CodeDeterminationInput(
            selected_product_code=selected.product_code,
            product_category=selected.category,
            department_name=request.department_name,
            correlation=correlation(state=state, session=session, step_id="code", attempt=step.attempt),
        )
        with self.telemetry.span("plan.step.execute", {"test.case.id": test_case_id, "plan.id": state.plan.plan_id, "plan.version": state.plan.version, "plan.step.id": "code", "execution.attempt": step.attempt, "agent.role": "code_determination"}) as code_span:
            self.telemetry.event(code_span, "step.started", {"plan.step.id": "code", "execution.attempt": step.attempt})
            self.telemetry.event(code_span, "handoff.payload_validated", {"agent.role": "code_determination"})
            codes = await invoke_validated(self.code_invoker, code_input, CodeDeterminationResult)
            if codes.status.business_status == BusinessStatus.SUCCESS:
                self.telemetry.event(code_span, "step.completed", {"plan.step.id": "code"})
            else:
                self.telemetry.event(code_span, "result.rejected", {"business.status": codes.status.business_status})
        state.code_result = codes
        if codes.status.business_status != BusinessStatus.SUCCESS:
            executor.block("code", codes.status.reason_code or "code determination failed")
            save_execution_state(session, state)
            return ScenarioResult(
                scenario_id="S2", test_case_id=test_case_id,
                technical_status=codes.status.technical_status,
                business_status=codes.status.business_status,
                status=codes.status, trace={"events": executor.events},
                next_action="Failure profileを解除し、Code Toolbox/Search/parse/validation層を確認して再実行する",
            )
        required_codes = [codes.account_code, codes.account_name, codes.department_code, codes.department_name]
        if not all(required_codes) or not codes.evidence:
            raise ValueError("code result cannot be accepted without grounded codes and evidence")
        executor.complete("code", output_refs=[item.evidence_id for item in codes.evidence], reason="account and department codes grounded")
        state.evidence_refs.extend(item.evidence_id for item in codes.evidence)

        step = executor.start("merge_validate", {"request": request.model_dump(mode="json"), "catalog": catalog.model_dump(mode="json"), "codes": codes.model_dump(mode="json")})
        state.current_step_id = step.step_id
        with self.telemetry.span("merge.validate", {"test.case.id": test_case_id, "plan.id": state.plan.plan_id, "plan.step.id": step.step_id}) as merge_span:
            self.telemetry.event(merge_span, "step.started", {"plan.step.id": step.step_id})
            subtotal = Decimal(selected.unit_price) * request.quantity
            draft = ApplicationDraft(
                request_id=request.request_id,
                lines=[ApplicationLine(
                    product_code=selected.product_code, product_name=selected.product_name,
                    category=selected.category, quantity=request.quantity,
                    unit_price=selected.unit_price, currency=selected.currency, subtotal=subtotal,
                    account_code=codes.account_code, account_name=codes.account_name,
                )],
                department_code=codes.department_code, department_name=codes.department_name,
                total=subtotal, evidence_refs=state.evidence_refs,
                warnings=[*catalog.warnings, *codes.warnings],
            )
            if request.constraints.budget_limit is not None and draft.total > request.constraints.budget_limit:
                executor.block("merge_validate", "budget limit exceeded")
                self.telemetry.event(merge_span, "result.rejected", {"business.status": "VALIDATION_FAILED"})
                save_execution_state(session, state)
                return ScenarioResult(
                    scenario_id="S1", test_case_id=test_case_id,
                    technical_status=TechnicalStatus.SUCCESS,
                    business_status=BusinessStatus.VALIDATION_FAILED,
                    status=OperationStatus(business_status=BusinessStatus.VALIDATION_FAILED),
                    next_action="数量または予算上限をユーザーに確認する",
                )
            self.telemetry.event(merge_span, "step.completed", {"plan.step.id": step.step_id})
        state.draft = draft
        executor.complete("merge_validate", output_refs=[draft.request_id], reason="validated application ready")
        save_execution_state(session, state)
        with self.telemetry.span("response.generate", {"test.case.id": test_case_id, "plan.id": state.plan.plan_id}):
            return ScenarioResult(
                scenario_id="S1", test_case_id=test_case_id,
                technical_status=TechnicalStatus.SUCCESS,
                business_status=BusinessStatus.SUCCESS, draft=draft,
                status=OperationStatus(business_status=BusinessStatus.SUCCESS),
                trace={"events": executor.events},
            )
