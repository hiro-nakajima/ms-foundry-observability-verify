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
    ScenarioResult, TechnicalStatus, FailureLayer,
)
from .observability import TelemetryRecorder
from .plan import PlanExecutor, StructuredPlanBuilder
from .session_state import initialize_execution_state, load_execution_state, save_execution_state

T = TypeVar("T", bound=BaseModel)
StructuredInvoker = Callable[[BaseModel], Awaitable[dict[str, Any] | BaseModel]]


def catalog_result_is_grounded(result: CatalogSearchResult) -> bool:
    if result.status.business_status != BusinessStatus.SUCCESS or not result.selected_product_code:
        return False
    selected = next(
        (item for item in result.candidates if item.product_code == result.selected_product_code),
        None,
    )
    return selected is not None and any(
        evidence.evidence_id == selected.evidence_id
        and evidence.index_name == "procurement-catalog-v1"
        and evidence.record_type == "product"
        and evidence.record_key == selected.product_code
        for evidence in result.evidence
    )


def reject_ungrounded_catalog(result: CatalogSearchResult) -> None:
    if result.status.business_status == BusinessStatus.SUCCESS and not catalog_result_is_grounded(result):
        result.status.business_status = BusinessStatus.VALIDATION_FAILED
        result.status.failure_layer = FailureLayer.VALIDATION
        result.status.reason_code = "catalog_evidence_missing_or_unrelated"


def set_machine_status(
    state: Any, status: OperationStatus, *,
    outer_technical: TechnicalStatus, outer_business: BusinessStatus,
) -> None:
    step_statuses: dict[str, Any] = {}
    if state.catalog_result is not None:
        step_statuses["catalog"] = state.catalog_result.status.model_dump(mode="json")
    if state.code_result is not None:
        step_statuses["code"] = state.code_result.status.model_dump(mode="json")
    state.last_machine_response = {
        **status.model_dump(mode="json"),
        "outer_technical_status": outer_technical.value,
        "outer_business_status": outer_business.value,
        "step_statuses": step_statuses,
    }


def refresh_governance_decisions(state: Any, session: AgentSession) -> None:
    """Merge FunctionMiddleware mutations before the Controller saves its state copy."""
    persisted = load_execution_state(session, required=True)
    assert persisted is not None
    state.governance_decisions = persisted.governance_decisions


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
        result = result_type.model_validate(
            raw.model_dump(mode="json") if isinstance(raw, BaseModel) else raw
        )
    except ValidationError as exc:
        raise ValueError(f"structured child output failed boundary validation: {exc.error_count()}") from exc
    input_correlation = getattr(validated_input, "correlation", None)
    result_correlation = getattr(result, "correlation", None)
    if input_correlation is not None and result_correlation != input_correlation:
        raise ValueError("structured child output changed the supplied correlation")
    return result


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
        previous_version = state.plan.version if state.plan else 0
        state.current_step_id = None
        state.catalog_result = None
        state.code_result = None
        state.draft = None
        state.evidence_refs = []
        state.last_machine_response = None
        with self.telemetry.span("plan.create", {"test.case.id": test_case_id, "app.session.id": session.session_id, "app.turn.number": state.turn_number}) as span:
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
            refresh_governance_decisions(state, session)
            reject_ungrounded_catalog(catalog)
            if catalog_result_is_grounded(catalog):
                self.telemetry.event(catalog_span, "step.completed", {"plan.step.id": "catalog"})
            else:
                self.telemetry.event(catalog_span, "result.rejected", {"business.status": catalog.status.business_status})
                self.telemetry.event(catalog_span, "step.retry_scheduled", {"execution.attempt": step.attempt + 1})
        state.catalog_result = catalog
        if not catalog_result_is_grounded(catalog):
            should_retry = (
                catalog.status.business_status == BusinessStatus.NOT_FOUND
                or catalog.status.retryable
            )
            if not should_retry:
                executor.block("catalog", catalog.status.reason_code or "catalog result rejected")
                set_machine_status(
                    state, catalog.status,
                    outer_technical=catalog.status.technical_status,
                    outer_business=BusinessStatus.BLOCKED,
                )
                save_execution_state(session, state)
                return ScenarioResult(
                    scenario_id="S2", test_case_id=test_case_id,
                    technical_status=catalog.status.technical_status,
                    business_status=BusinessStatus.BLOCKED,
                    status=catalog.status,
                    trace={"events": executor.events},
                    next_action="Catalog Toolbox/Search/parse/validation層を確認して再実行する",
                )
            executor.retry("catalog", catalog.status.reason_code or "catalog search did not identify a product")
            if state.plan.status.name != "BLOCKED":
                step = executor.start("catalog", request.model_dump(mode="json") | {"replan": True})
                retry_input = CatalogSearchInput(
                    query=request.query,
                    quantity=request.quantity,
                    constraints=request.constraints,
                    correlation=correlation(
                        state=state, session=session, step_id="catalog", attempt=step.attempt
                    ),
                )
                with self.telemetry.span("plan.step.execute", {"test.case.id": test_case_id, "plan.id": state.plan.plan_id, "plan.version": state.plan.version, "plan.step.id": "catalog", "execution.attempt": step.attempt, "agent.role": "catalog_search"}) as retry_span:
                    self.telemetry.event(retry_span, "step.started", {"plan.step.id": "catalog", "execution.attempt": step.attempt})
                    self.telemetry.event(retry_span, "handoff.payload_validated", {"agent.role": "catalog_search"})
                    catalog = await invoke_validated(
                        self.catalog_invoker, retry_input, CatalogSearchResult
                    )
                    refresh_governance_decisions(state, session)
                    reject_ungrounded_catalog(catalog)
                    if catalog_result_is_grounded(catalog):
                        self.telemetry.event(retry_span, "step.completed", {"plan.step.id": "catalog"})
                    else:
                        self.telemetry.event(retry_span, "result.rejected", {"business.status": catalog.status.business_status})
                        if catalog.status.business_status == BusinessStatus.NOT_FOUND:
                            self.telemetry.event(retry_span, "plan.replanned", {"business.status": "WAITING_USER"})
                        else:
                            self.telemetry.event(retry_span, "step.failed", {
                                "business.status": catalog.status.business_status,
                                "failure.layer": catalog.status.failure_layer,
                            })
                state.catalog_result = catalog
            if not catalog_result_is_grounded(catalog):
                if catalog.status.business_status == BusinessStatus.NOT_FOUND:
                    executor.wait_for_user("catalog", "catalog item not found after retry; user confirmation required")
                    outer_business = BusinessStatus.WAITING_USER
                    scenario_id = "S3"
                    next_action = "候補名または型番をユーザーに確認し、新しいPlan versionで再開する"
                else:
                    executor.block("catalog", catalog.status.reason_code or "catalog retry failed")
                    outer_business = BusinessStatus.BLOCKED
                    scenario_id = "S2"
                    next_action = "Catalog Toolbox/Search/parse/validation層を確認して再実行する"
                set_machine_status(
                    state, catalog.status,
                    outer_technical=catalog.status.technical_status,
                    outer_business=outer_business,
                )
                save_execution_state(session, state)
                return ScenarioResult(
                    scenario_id=scenario_id, test_case_id=test_case_id,
                    technical_status=catalog.status.technical_status,
                    business_status=outer_business,
                    status=catalog.status,
                    trace={"events": executor.events},
                    next_action=next_action,
                )
        executor.complete("catalog", output_refs=[item.evidence_id for item in catalog.evidence], reason="grounded catalog candidate selected")
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
            refresh_governance_decisions(state, session)
            if codes.status.business_status == BusinessStatus.SUCCESS:
                self.telemetry.event(code_span, "step.completed", {"plan.step.id": "code"})
            else:
                self.telemetry.event(code_span, "result.rejected", {"business.status": codes.status.business_status})
        state.code_result = codes
        if codes.status.business_status != BusinessStatus.SUCCESS:
            executor.block("code", codes.status.reason_code or "code determination failed")
            set_machine_status(
                state, codes.status,
                outer_technical=codes.status.technical_status,
                outer_business=codes.status.business_status,
            )
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
                validation_status = codes.status.model_copy(update={
                    "business_status": BusinessStatus.VALIDATION_FAILED,
                    "failure_layer": FailureLayer.VALIDATION,
                    "reason_code": "budget_limit_exceeded",
                })
                set_machine_status(
                    state, validation_status,
                    outer_technical=TechnicalStatus.SUCCESS,
                    outer_business=BusinessStatus.VALIDATION_FAILED,
                )
                save_execution_state(session, state)
                return ScenarioResult(
                    scenario_id="S1", test_case_id=test_case_id,
                    technical_status=TechnicalStatus.SUCCESS,
                    business_status=BusinessStatus.VALIDATION_FAILED,
                    status=validation_status,
                    next_action="数量または予算上限をユーザーに確認する",
                )
            self.telemetry.event(merge_span, "step.completed", {"plan.step.id": step.step_id})
        state.draft = draft
        executor.complete("merge_validate", output_refs=[draft.request_id], reason="validated application ready")
        success_status = codes.status.model_copy(update={
            "business_status": BusinessStatus.SUCCESS,
            "failure_layer": FailureLayer.NONE,
            "reason_code": None,
            "retryable": False,
        })
        set_machine_status(
            state, success_status,
            outer_technical=TechnicalStatus.SUCCESS,
            outer_business=BusinessStatus.SUCCESS,
        )
        save_execution_state(session, state)
        with self.telemetry.span("response.generate", {"test.case.id": test_case_id, "plan.id": state.plan.plan_id}):
            return ScenarioResult(
                scenario_id="S1", test_case_id=test_case_id,
                technical_status=TechnicalStatus.SUCCESS,
                business_status=BusinessStatus.SUCCESS, draft=draft,
                status=success_status,
                trace={"events": executor.events},
            )
