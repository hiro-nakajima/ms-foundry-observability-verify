"""Deterministic Plan & Execute controller for the single E2E architecture."""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, TypeVar
from uuid import uuid4

from agent_framework import AgentSession
from pydantic import BaseModel, ValidationError

from .models import (
    ApplicationDraft, ApplicationLine, BusinessStatus, CatalogCandidate, CatalogSearchInput,
    CatalogSearchResult, CodeDeterminationInput, CodeDeterminationResult, ConfirmationPreview,
    CorrelationContext, ExecutionPlan, FailureLayer, McpStatus, OperationStatus,
    ParseStatus, ProcurementIntakeRequest, ProcurementRequest, ScenarioResult, SearchStatus, TechnicalStatus,
)
from .observability import TelemetryRecorder
from .plan import PlanExecutor, StructuredPlanBuilder
from .progress import publish
from .session_state import initialize_execution_state, load_execution_state, save_execution_state

T = TypeVar("T", bound=BaseModel)
StructuredInvoker = Callable[[BaseModel], Awaitable[dict[str, Any] | BaseModel]]


class StructuredChildOutputError(ValueError):
    pass


class ChildCorrelationMismatchError(ValueError):
    def __init__(self, message: str, *, child_status: OperationStatus | None = None) -> None:
        super().__init__(message)
        self.child_status = child_status


class ChildInvocationError(RuntimeError):
    def __init__(self, *, status: OperationStatus, exception_type: str) -> None:
        super().__init__(f"child invocation failed: {exception_type}")
        self.status = status


def classify_child_invocation_exception(exc: Exception) -> OperationStatus:
    """Map proxy/transport failures without persisting exception content."""
    if isinstance(exc, TimeoutError):
        return OperationStatus(
            technical_status=TechnicalStatus.ERROR,
            mcp_status=McpStatus.TIMEOUT,
            search_status=SearchStatus.NOT_RUN,
            parse_status=ParseStatus.NOT_RUN,
            business_status=BusinessStatus.BLOCKED,
            failure_layer=FailureLayer.MCP,
            retryable=True,
            reason_code="child_transport_timeout",
        )
    if isinstance(exc, PermissionError):
        return OperationStatus(
            technical_status=TechnicalStatus.ERROR,
            mcp_status=McpStatus.ERROR,
            search_status=SearchStatus.NOT_RUN,
            parse_status=ParseStatus.NOT_RUN,
            business_status=BusinessStatus.BLOCKED,
            failure_layer=FailureLayer.MCP,
            retryable=False,
            reason_code="child_transport_permission_denied",
        )
    return OperationStatus(
        technical_status=TechnicalStatus.ERROR,
        mcp_status=McpStatus.ERROR,
        search_status=SearchStatus.NOT_RUN,
        parse_status=ParseStatus.NOT_RUN,
        business_status=BusinessStatus.BLOCKED,
        failure_layer=FailureLayer.MCP,
        retryable=False,
        reason_code="child_invocation_error",
    )


def child_operation_succeeded(status: OperationStatus) -> bool:
    """Require coherent success across every child operation status layer."""
    return (
        status.technical_status == TechnicalStatus.SUCCESS
        and status.mcp_status == McpStatus.SUCCESS
        and status.search_status == SearchStatus.SUCCESS
        and status.parse_status == ParseStatus.SUCCESS
        and status.business_status == BusinessStatus.SUCCESS
        and status.failure_layer == FailureLayer.NONE
    )


def specification_mismatch_keys(
    requested: dict[str, str], available: dict[str, str],
) -> list[str]:
    normalized_available = {
        str(key).strip().casefold(): str(value).strip().casefold()
        for key, value in available.items()
    }
    return [
        key for key, expected in requested.items()
        if normalized_available.get(str(key).strip().casefold())
        != str(expected).strip().casefold()
    ]


def catalog_result_is_grounded(result: CatalogSearchResult) -> bool:
    if not child_operation_succeeded(result.status) or not result.selected_product_code:
        return False
    return _catalog_candidate_is_grounded(result, result.selected_product_code)


def _catalog_candidate_is_grounded(result: CatalogSearchResult, product_code: str) -> bool:
    selected = next((item for item in result.candidates if item.product_code == product_code), None)
    if not child_operation_succeeded(result.status) or selected is None:
        return False
    evidence = next((evidence for evidence in result.evidence if (
        evidence.evidence_id == selected.evidence_id
        and evidence.index_name == "procurement-catalog-v1"
        and evidence.record_type == "product"
        and evidence.record_key == selected.product_code
    )), None)
    return evidence is not None and (
        evidence.catalog_product_name == selected.product_name
        and evidence.catalog_category == selected.category
        and evidence.catalog_unit_price == selected.unit_price
        and evidence.catalog_currency == selected.currency
        and evidence.catalog_specifications == selected.specifications
    )


def _exact_grounded_catalog_match(
    result: CatalogSearchResult, query: str,
) -> CatalogCandidate | None:
    """Select only one exact Search-grounded code/name match."""
    normalized = "".join(query.split()).casefold()
    for suffix in ("を購入したい", "を買いたい", "が欲しい", "を注文したい"):
        if normalized.endswith(suffix):
            normalized = normalized[:-len(suffix)]
            break
    matches = [
        candidate for candidate in result.candidates
        if _catalog_candidate_is_grounded(result, candidate.product_code)
        and normalized in {
            "".join(candidate.product_code.split()).casefold(),
            "".join(candidate.product_name.split()).casefold(),
            "".join(candidate.product_name.split("（", 1)[0].split()).casefold(),
        }
    ]
    return matches[0] if len(matches) == 1 else None


def catalog_candidate_matches_specifications(
    result: CatalogSearchResult, requested: dict[str, str],
    product_code: str | None = None,
) -> bool:
    selected_product_code = product_code or result.selected_product_code
    if not selected_product_code or not _catalog_candidate_is_grounded(
        result, selected_product_code,
    ):
        return False
    selected = next(
        item for item in result.candidates
        if item.product_code == selected_product_code
    )
    return not specification_mismatch_keys(requested, selected.specifications)


def reject_ungrounded_catalog(result: CatalogSearchResult) -> None:
    if child_operation_succeeded(result.status) and not catalog_result_is_grounded(result):
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


def operation_status_attributes(
    status: OperationStatus, *, outer_technical: TechnicalStatus,
    outer_business: BusinessStatus,
) -> dict[str, Any]:
    return {
        "http.status_code": status.http_status,
        "technical.status": status.technical_status.value,
        "outer.technical.status": outer_technical.value,
        "mcp.status": status.mcp_status.value,
        "search.status": status.search_status.value,
        "parse.status": status.parse_status.value,
        "business.status": outer_business.value,
        "inner.business.status": status.business_status.value,
        "failure.layer": status.failure_layer.value,
        "retryable": status.retryable,
        "reason.code": status.reason_code or "none",
    }


def correlation_attributes(value: CorrelationContext) -> dict[str, Any]:
    return {
        "test.case.id": value.test_case_id,
        "app.session.id": value.framework_session_id,
        "app.turn.number": value.turn_number,
        "plan.id": value.plan_id,
        "plan.version": value.plan_version,
        "plan.step.id": value.step_id,
        "execution.attempt": value.attempt,
        "parent.invocation.id": value.parent_invocation_id,
        "remote.task.id": value.remote_task_id,
    }


def apply_operation_status(
    span: Any, status: OperationStatus, *, outer_technical: TechnicalStatus,
    outer_business: BusinessStatus,
) -> None:
    for key, value in operation_status_attributes(
        status,
        outer_technical=outer_technical,
        outer_business=outer_business,
    ).items():
        span.set_attribute(key, value)


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


def _missing_fields(state: Any, outer_business: BusinessStatus) -> list[str]:
    if not state.intake or state.request is not None or outer_business != BusinessStatus.WAITING_USER:
        return []
    if not state.intake.query:
        return ["query"]
    if not state.selected_product_code:
        return ["selected_product_code"]
    for field in ("quantity", "department_name", "memo"):
        if getattr(state.intake, field) is None:
            return [field]
    return ["confirmation"]


def _confirmation_preview(state: Any) -> ConfirmationPreview | None:
    if not all((
        state.intake, state.selected_product_code,
        state.catalog_result, state.code_result,
    )):
        return None
    if not catalog_result_is_grounded(state.catalog_result):
        return None
    if not child_operation_succeeded(state.code_result.status):
        return None
    selected = next((
        item for item in state.catalog_result.candidates
        if item.product_code == state.selected_product_code
    ), None)
    if selected is None or not all((
        state.intake.quantity, state.intake.memo,
        state.code_result.account_code, state.code_result.account_name,
        state.code_result.department_code, state.code_result.department_name,
    )):
        return None
    subtotal = selected.unit_price * state.intake.quantity
    return ConfirmationPreview(
        applicant_authenticated=bool(state.applicant_name and state.applicant_source in {"easyauth", "graph_obo"}),
        applicant_name=state.applicant_name,
        product_code=selected.product_code,
        product_name=selected.product_name,
        category=selected.category,
        specifications=selected.specifications,
        unit_price=selected.unit_price,
        currency=selected.currency,
        quantity=state.intake.quantity,
        subtotal=subtotal,
        department_code=state.code_result.department_code,
        department_name=state.code_result.department_name,
        account_code=state.code_result.account_code,
        account_name=state.code_result.account_name,
        memo=state.intake.memo,
    )


def _saved_confirmation_context(
    state: Any, request: ProcurementRequest, selected_product_code: str | None,
    session: AgentSession,
) -> tuple[CatalogSearchResult, CodeDeterminationResult, CatalogCandidate] | None:
    if not all((
        state.intake, state.catalog_result, state.code_result,
        selected_product_code,
    )):
        return None
    intake = state.intake
    if (
        request.query != intake.query
        or request.quantity != intake.quantity
        or request.department_name != intake.department_name
        or request.memo != intake.memo
        or request.constraints != intake.constraints
        or request.applicant_name != state.applicant_name
        or selected_product_code != state.selected_product_code
        or state.catalog_result.correlation.framework_session_id != session.session_id
        or state.code_result.correlation.framework_session_id != session.session_id
        or not catalog_result_is_grounded(state.catalog_result)
        or not child_operation_succeeded(state.code_result.status)
    ):
        return None
    selected = next((
        item for item in state.catalog_result.candidates
        if item.product_code == selected_product_code
    ), None)
    if selected is None or not catalog_candidate_matches_specifications(
        state.catalog_result, request.constraints.specifications,
        selected_product_code,
    ):
        return None
    return state.catalog_result, state.code_result, selected


async def invoke_validated(invoker: StructuredInvoker, payload: BaseModel, result_type: type[T]) -> T:
    """Validate both sides of the parent/child boundary before state mutation."""
    validated_input = type(payload).model_validate(payload.model_dump(mode="json"))
    try:
        raw = await invoker(validated_input)
        result = result_type.model_validate(
            raw.model_dump(mode="json") if isinstance(raw, BaseModel) else raw
        )
    except (ValidationError, json.JSONDecodeError) as exc:
        error_count = exc.error_count() if isinstance(exc, ValidationError) else 1
        raise StructuredChildOutputError(
            f"structured child output failed boundary validation: {error_count}"
        ) from exc
    except Exception as exc:
        raise ChildInvocationError(
            status=classify_child_invocation_exception(exc),
            exception_type=type(exc).__name__,
        ) from exc
    input_correlation = getattr(validated_input, "correlation", None)
    result_correlation = getattr(result, "correlation", None)
    if input_correlation is not None and result_correlation != input_correlation:
        raise ChildCorrelationMismatchError(
            "structured child output changed the supplied correlation",
            child_status=getattr(result, "status", None),
        )
    return result


class ProcurementController:
    def __init__(self, catalog_invoker: StructuredInvoker, code_invoker: StructuredInvoker, *, telemetry: TelemetryRecorder | None = None) -> None:
        self.catalog_invoker = catalog_invoker
        self.code_invoker = code_invoker
        self.telemetry = telemetry or TelemetryRecorder()

    def _finish(
        self, *, state: Any, session: AgentSession, test_case_id: str,
        status: OperationStatus, outer_technical: TechnicalStatus,
        outer_business: BusinessStatus, executor: PlanExecutor, scenario_id: str,
        next_action: str | None = None,
    ) -> ScenarioResult:
        set_machine_status(
            state, status,
            outer_technical=outer_technical,
            outer_business=outer_business,
        )
        save_execution_state(session, state)
        attributes = {
            "test.case.id": test_case_id,
            "app.turn.number": state.turn_number,
            "plan.id": state.plan.plan_id if state.plan else "none",
            **operation_status_attributes(
                status,
                outer_technical=outer_technical,
                outer_business=outer_business,
            ),
        }
        with self.telemetry.span("response.generate", attributes) as span:
            self.telemetry.event(span, "response.status", attributes)
        missing_fields = _missing_fields(state, outer_business)
        confirmation_preview = (
            _confirmation_preview(state) if missing_fields == ["confirmation"] else None
        )
        result = ScenarioResult(
            scenario_id=scenario_id, test_case_id=test_case_id,
            technical_status=outer_technical, business_status=outer_business,
            status=status, draft=state.draft, trace={"events": executor.events},
            next_action=next_action,
            confirmation_preview=confirmation_preview,
            candidates=[candidate for candidate in (state.catalog_result.candidates if state.catalog_result else [])
                        if "selected_product_code" in missing_fields
                        and _catalog_candidate_is_grounded(state.catalog_result, candidate.product_code)],
            missing_fields=missing_fields,
        )
        return result

    def _boundary_failure_result(
        self, *, exc: StructuredChildOutputError | ChildCorrelationMismatchError | ChildInvocationError,
        executor: PlanExecutor, state: Any, session: AgentSession,
        test_case_id: str, step_id: str,
    ) -> ScenarioResult:
        refresh_governance_decisions(state, session)
        executor.block(step_id, str(exc))
        if isinstance(exc, ChildInvocationError):
            status = exc.status
            scenario_id = "S2"
            outer_technical = TechnicalStatus.ERROR
            next_action = "子Agent proxyの認証、接続、MCP transportを確認して再実行する"
        elif isinstance(exc, ChildCorrelationMismatchError) and exc.child_status is not None:
            status = exc.child_status.model_copy(update={
                "business_status": BusinessStatus.BLOCKED,
                "failure_layer": FailureLayer.VALIDATION,
                "retryable": False,
                "reason_code": "child_correlation_mismatch",
            })
            scenario_id = "S4"
            outer_technical = TechnicalStatus.SUCCESS
            next_action = "Structured child outputとcorrelationを修正して再実行する"
        else:
            status = OperationStatus(
                technical_status=TechnicalStatus.ERROR,
                parse_status=ParseStatus.SCHEMA_INVALID,
                business_status=BusinessStatus.BLOCKED,
                failure_layer=FailureLayer.PARSE,
                reason_code="child_output_schema_invalid",
            )
            scenario_id = "S4"
            outer_technical = TechnicalStatus.SUCCESS
            next_action = "Structured child outputとcorrelationを修正して再実行する"
        return self._finish(
            state=state, session=session, test_case_id=test_case_id,
            status=status, outer_technical=outer_technical,
            outer_business=BusinessStatus.BLOCKED,
            executor=executor, scenario_id=scenario_id,
            next_action=next_action,
        )

    def invalid_intake_result(
        self, *, session: AgentSession, test_case_id: str,
        technical_status: TechnicalStatus, business_status: BusinessStatus,
        parse_status: ParseStatus, reason_code: str,
    ) -> ScenarioResult:
        """Create a safe terminal result when the parent request boundary fails."""
        state = load_execution_state(session, required=False)
        if state is None:
            state = initialize_execution_state(session, test_case_id=test_case_id)
        state.turn_number += 1
        state.test_case_id = test_case_id
        previous_version = state.plan.version if state.plan else 0
        state.plan = StructuredPlanBuilder().build(None)
        state.plan.version = previous_version + 1
        state.current_step_id = "catalog"
        state.request = None
        state.catalog_result = None
        state.code_result = None
        state.draft = None
        state.evidence_refs = []
        state.child_correlations = []
        executor = PlanExecutor(state.plan, state.completed_step_keys)
        executor.block("catalog", reason_code)
        status = OperationStatus(
            technical_status=technical_status,
            parse_status=parse_status,
            business_status=business_status,
            failure_layer=FailureLayer.PARSE,
            retryable=False,
            reason_code=reason_code,
        )
        return self._finish(
            state=state, session=session, test_case_id=test_case_id,
            status=status, outer_technical=technical_status,
            outer_business=business_status,
            executor=executor, scenario_id="S4",
            next_action="依頼内容を確認し、必須項目を補って再実行する",
        )

    async def _run_catalog_step(
        self, *, request: ProcurementRequest | ProcurementIntakeRequest, state: Any, session: AgentSession,
        executor: PlanExecutor, test_case_id: str, replan: bool,
    ) -> CatalogSearchResult | ScenarioResult:
        """Execute one catalog attempt; retry only changes the plan input and event."""
        step = executor.start(
            "catalog",
            request.model_dump(mode="json") | ({"replan": True} if replan else {}),
        )
        publish("catalog", "started")
        state.current_step_id = step.step_id
        catalog_input = CatalogSearchInput(
            query=request.query, quantity=request.quantity, constraints=request.constraints,
            correlation=correlation(
                state=state, session=session, step_id="catalog", attempt=step.attempt,
            ),
        )
        state.child_correlations.append(catalog_input.correlation)
        save_execution_state(session, state)
        # SDKのTool Spanに加え、業務上の1ステップ（再試行・検証を含む）を観測する。
        with self.telemetry.span("plan.step.execute", {
            **correlation_attributes(catalog_input.correlation),
            "agent.role": "catalog_search",
            "agent.definition.id": "catalog_search_agent",
            "toolbox.name": "catalog-search-toolbox",
            "search.index.name": "procurement-catalog-v1",
        }) as catalog_span:
            self.telemetry.event(catalog_span, "step.started", {
                "plan.step.id": "catalog", "execution.attempt": step.attempt,
            })
            self.telemetry.event(catalog_span, "handoff.payload_validated", {
                "agent.role": "catalog_search",
            })
            try:
                catalog = await invoke_validated(
                    self.catalog_invoker, catalog_input, CatalogSearchResult,
                )
            except (StructuredChildOutputError, ChildCorrelationMismatchError, ChildInvocationError) as exc:
                self.telemetry.event(catalog_span, "handoff.output_rejected", {"reason": str(exc)})
                return self._boundary_failure_result(
                    exc=exc, executor=executor, state=state, session=session,
                    test_case_id=test_case_id, step_id="catalog",
                )
            refresh_governance_decisions(state, session)
            if state.selected_product_code:
                # Re-query the selected key and require fresh Search evidence for it.
                catalog.selected_product_code = state.selected_product_code if any(
                    c.product_code == state.selected_product_code for c in catalog.candidates
                ) and any(e.record_type == 'product' and e.record_key == state.selected_product_code
                          and any(c.product_code == state.selected_product_code and c.evidence_id == e.evidence_id
                                  for c in catalog.candidates) for e in catalog.evidence) else None
            reject_ungrounded_catalog(catalog)
            apply_operation_status(
                catalog_span, catalog.status,
                outer_technical=catalog.status.technical_status,
                outer_business=catalog.status.business_status,
            )
            if catalog_candidate_matches_specifications(catalog, request.constraints.specifications):
                self.telemetry.event(catalog_span, "step.completed", {"plan.step.id": "catalog"})
                publish("catalog", "completed")
            else:
                specification_mismatch = catalog_result_is_grounded(catalog) and bool(request.constraints.specifications)
                self.telemetry.event(catalog_span, "result.rejected", {
                    "business.status": BusinessStatus.VALIDATION_FAILED if specification_mismatch else catalog.status.business_status,
                    "reason.code": "catalog_specification_mismatch" if specification_mismatch else catalog.status.reason_code or "catalog_rejected",
                })
                if replan and catalog.status.business_status == BusinessStatus.NOT_FOUND:
                    self.telemetry.event(catalog_span, "plan.replanned", {"business.status": "WAITING_USER"})
                elif not replan and (catalog.status.business_status == BusinessStatus.NOT_FOUND or catalog.status.retryable):
                    self.telemetry.event(catalog_span, "step.retry_scheduled", {"execution.attempt": step.attempt + 1})
                    publish("catalog", "retry")
                elif replan:
                    self.telemetry.event(catalog_span, "step.failed", {
                        "business.status": catalog.status.business_status,
                        "failure.layer": catalog.status.failure_layer,
                    })
        state.catalog_result = catalog
        return catalog

    async def _run_code_step(
        self, *, selected: CatalogCandidate, department_name: str, state: Any,
        session: AgentSession, executor: PlanExecutor, test_case_id: str,
    ) -> CodeDeterminationResult | ScenarioResult:
        step = executor.start("code", {
            "product_code": selected.product_code,
            "category": selected.category,
            "department_name": department_name,
        })
        publish("code", "started")
        state.current_step_id = step.step_id
        code_input = CodeDeterminationInput(
            selected_product_code=selected.product_code,
            product_category=selected.category,
            department_name=department_name,
            correlation=correlation(
                state=state, session=session, step_id="code", attempt=step.attempt,
            ),
        )
        state.child_correlations.append(code_input.correlation)
        save_execution_state(session, state)
        # SDKのTool Spanに加え、業務上の1ステップ（再試行・検証を含む）を観測する。
        with self.telemetry.span("plan.step.execute", {
            **correlation_attributes(code_input.correlation),
            "agent.role": "code_determination",
            "agent.definition.id": "code_determination_agent",
            "toolbox.name": "code-master-toolbox",
            "search.index.name": "procurement-code-master-v1",
        }) as code_span:
            self.telemetry.event(code_span, "step.started", {
                "plan.step.id": "code", "execution.attempt": step.attempt,
            })
            self.telemetry.event(code_span, "handoff.payload_validated", {
                "agent.role": "code_determination",
            })
            try:
                codes = await invoke_validated(
                    self.code_invoker, code_input, CodeDeterminationResult,
                )
            except (StructuredChildOutputError, ChildCorrelationMismatchError, ChildInvocationError) as exc:
                self.telemetry.event(code_span, "handoff.output_rejected", {"reason": str(exc)})
                return self._boundary_failure_result(
                    exc=exc, executor=executor, state=state, session=session,
                    test_case_id=test_case_id, step_id="code",
                )
            refresh_governance_decisions(state, session)
            apply_operation_status(
                code_span, codes.status,
                outer_technical=codes.status.technical_status,
                outer_business=codes.status.business_status,
            )
            if child_operation_succeeded(codes.status):
                self.telemetry.event(code_span, "step.completed", {"plan.step.id": "code"})
                publish("code", "completed")
            else:
                self.telemetry.event(code_span, "result.rejected", {
                    "business.status": codes.status.business_status,
                })
        state.code_result = codes
        return codes

    def _merge_validated(
        self, *, request: ProcurementRequest, selected: CatalogCandidate,
        catalog: CatalogSearchResult, codes: CodeDeterminationResult,
        state: Any, session: AgentSession, executor: PlanExecutor,
        test_case_id: str,
    ) -> ScenarioResult:
        step = executor.start("merge_validate", {
            "request": request.model_dump(mode="json"),
            "catalog": catalog.model_dump(mode="json"),
            "codes": codes.model_dump(mode="json"),
        })
        publish("merge_validate", "started")
        state.current_step_id = step.step_id
        with self.telemetry.span("merge.validate", {
            "test.case.id": test_case_id,
            "app.turn.number": state.turn_number,
            "plan.id": state.plan.plan_id,
            "plan.step.id": step.step_id,
        }) as merge_span:
            self.telemetry.event(merge_span, "step.started", {
                "plan.step.id": step.step_id,
            })
            subtotal = selected.unit_price * request.quantity
            draft = ApplicationDraft(
                request_id=request.request_id,
                lines=[ApplicationLine(
                    product_code=selected.product_code,
                    product_name=selected.product_name,
                    category=selected.category,
                    quantity=request.quantity,
                    unit_price=selected.unit_price,
                    currency=selected.currency,
                    subtotal=subtotal,
                    account_code=codes.account_code,
                    account_name=codes.account_name,
                )],
                department_code=codes.department_code,
                department_name=codes.department_name,
                memo=request.memo,
                total=subtotal,
                evidence_refs=state.evidence_refs,
                warnings=[*catalog.warnings, *codes.warnings],
            )
            if request.constraints.budget_limit is not None and draft.total > request.constraints.budget_limit:
                executor.block("merge_validate", "budget limit exceeded")
                self.telemetry.event(merge_span, "result.rejected", {
                    "business.status": "VALIDATION_FAILED",
                })
                validation_status = codes.status.model_copy(update={
                    "business_status": BusinessStatus.VALIDATION_FAILED,
                    "failure_layer": FailureLayer.VALIDATION,
                    "reason_code": "budget_limit_exceeded",
                })
                return self._finish(
                    state=state, session=session, test_case_id=test_case_id,
                    status=validation_status, executor=executor,
                    scenario_id="S1", outer_technical=TechnicalStatus.SUCCESS,
                    outer_business=BusinessStatus.VALIDATION_FAILED,
                    next_action="数量または予算上限をユーザーに確認する",
                )
            self.telemetry.event(merge_span, "step.completed", {
                "plan.step.id": step.step_id,
            })
            publish("merge_validate", "completed")
        state.draft = draft
        executor.complete(
            "merge_validate", output_refs=[draft.request_id],
            reason="validated application ready",
        )
        success_status = codes.status.model_copy(update={
            "business_status": BusinessStatus.SUCCESS,
            "failure_layer": FailureLayer.NONE,
            "reason_code": None,
            "retryable": False,
        })
        return self._finish(
            state=state, session=session, test_case_id=test_case_id,
            status=success_status, executor=executor,
            scenario_id="S1", outer_technical=TechnicalStatus.SUCCESS,
            outer_business=BusinessStatus.SUCCESS,
        )

    async def execute(
        self, request: ProcurementRequest | ProcurementIntakeRequest, *, session: AgentSession | None,
        test_case_id: str, raw_plan: ExecutionPlan | dict[str, Any] | str | None = None,
        selected_product_code: str | None = None,
    ) -> ScenarioResult:
        if session is None:
            raise ValueError("Framework AgentSession is required; implicit sessions are forbidden")
        state = load_execution_state(session, required=False)
        if state is None:
            state = initialize_execution_state(session, test_case_id=test_case_id)
        has_saved_confirmation_state = bool(
            isinstance(request, ProcurementRequest)
            and state.intake is not None
        )
        saved_confirmation = (
            _saved_confirmation_context(
                state, request, selected_product_code, session,
            )
            if isinstance(request, ProcurementRequest) else None
        )
        state.turn_number += 1
        state.test_case_id = test_case_id
        state.request = request if isinstance(request, ProcurementRequest) else None
        state.selected_product_code = selected_product_code
        staged_intake = request if isinstance(request, ProcurementIntakeRequest) else None
        failed_catalog_pending = bool(
            staged_intake
            and state.catalog_result is not None
            and not catalog_result_is_grounded(state.catalog_result)
            and state.intake is not None
            and staged_intake.query == state.intake.query
        )
        stage_requires_code_validation = bool(
            staged_intake
            and state.catalog_result is not None
            and all((
                staged_intake.quantity, staged_intake.department_name,
                staged_intake.memo, selected_product_code,
            ))
        )
        if (staged_intake is not None and not stage_requires_code_validation
                and not failed_catalog_pending):
            assert staged_intake is not None
            state.intake = staged_intake
        previous_version = state.plan.version if state.plan else 0
        state.current_step_id = None
        if isinstance(request, ProcurementRequest) and saved_confirmation is None:
            # Direct/core requests have no pre-confirmation session evidence and
            # still execute the full plan. Hosted confirmations reuse validated state.
            state.catalog_result = None
        if saved_confirmation is None:
            state.code_result = None
        state.draft = None
        state.evidence_refs = []
        state.child_correlations = []
        state.last_machine_response = None
        # Planを実際に作る処理を囲む。ヘルパーの定義だけではSpanは発生しない。
        with self.telemetry.span("plan.create", {"test.case.id": test_case_id, "app.session.id": session.session_id, "app.turn.number": state.turn_number}) as span:
            state.plan = StructuredPlanBuilder().build(raw_plan)
            state.plan.version = previous_version + 1
            self.telemetry.event(span, "plan.created", {"plan.id": state.plan.plan_id, "plan.version": state.plan.version})
        executor = PlanExecutor(state.plan, state.completed_step_keys)
        save_execution_state(session, state)

        def finish(
            status: OperationStatus, scenario_id: str, *,
            technical: TechnicalStatus | None = None,
            business: BusinessStatus | None = None,
            next_action: str | None = None,
        ) -> ScenarioResult:
            return self._finish(
                state=state, session=session, test_case_id=test_case_id,
                status=status, executor=executor, scenario_id=scenario_id,
                outer_technical=technical or status.technical_status,
                outer_business=business or status.business_status,
                next_action=next_action,
            )

        if not request.query:
            executor.wait_for_user("catalog", "product query required")
            status = OperationStatus(business_status=BusinessStatus.WAITING_USER, parse_status=ParseStatus.SUCCESS)
            return finish(status, "S3", technical=TechnicalStatus.SUCCESS)

        if isinstance(request, ProcurementRequest) and has_saved_confirmation_state:
            if saved_confirmation is None:
                executor.block("catalog", "saved confirmation state failed validation")
                status = OperationStatus(
                    technical_status=TechnicalStatus.SUCCESS,
                    parse_status=ParseStatus.SUCCESS,
                    business_status=BusinessStatus.VALIDATION_FAILED,
                    failure_layer=FailureLayer.VALIDATION,
                    reason_code="confirmation_state_invalid",
                )
                return finish(
                    status, "S4", business=BusinessStatus.VALIDATION_FAILED,
                    next_action="購買申請を商品選択から再開する",
                )
            catalog, codes, selected = saved_confirmation
            executor.reuse(
                "catalog", inputs={"saved_product_code": selected.product_code},
                output_refs=[item.evidence_id for item in catalog.evidence],
                reason="reuse pre-confirmation Catalog evidence",
            )
            executor.reuse(
                "code", inputs={
                    "saved_account_code": codes.account_code,
                    "saved_department_code": codes.department_code,
                },
                output_refs=[item.evidence_id for item in codes.evidence],
                reason="reuse pre-confirmation Code evidence",
            )
            state.evidence_refs = [
                *(item.evidence_id for item in catalog.evidence),
                *(item.evidence_id for item in codes.evidence),
            ]
            return self._merge_validated(
                request=request, selected=selected, catalog=catalog, codes=codes,
                state=state, session=session, executor=executor,
                test_case_id=test_case_id,
            )

        if selected_product_code:
            request = request.model_copy(update={"query": selected_product_code})

        if failed_catalog_pending:
            executor.wait_for_user("catalog", "previous catalog query was not found; new product input required")
            assert state.catalog_result is not None
            status = state.catalog_result.status.model_copy(update={
                "business_status": BusinessStatus.WAITING_USER,
            })
            return finish(status, "S3", technical=TechnicalStatus.SUCCESS)

        if (isinstance(request, ProcurementIntakeRequest)
                and state.catalog_result is not None
                and catalog_result_is_grounded(state.catalog_result)):
            ready = all((
                request.quantity, request.department_name, request.memo,
                selected_product_code,
            ))
            if not ready:
                executor.wait_for_user("catalog", "reuse grounded candidates from AgentSession")
                status = state.catalog_result.status.model_copy(update={"business_status": BusinessStatus.WAITING_USER})
                return finish(status, "S3", technical=TechnicalStatus.SUCCESS)
            assert selected_product_code is not None and request.department_name is not None
            if not _catalog_candidate_is_grounded(state.catalog_result, selected_product_code):
                executor.block("catalog", "selected candidate is not grounded by saved Search evidence")
                status = state.catalog_result.status.model_copy(update={
                    "business_status": BusinessStatus.VALIDATION_FAILED,
                    "failure_layer": FailureLayer.VALIDATION,
                    "reason_code": "catalog_evidence_missing_or_unrelated",
                })
                return finish(status, "S4", business=BusinessStatus.BLOCKED)
            selected = next(
                item for item in state.catalog_result.candidates
                if item.product_code == selected_product_code
            )
            if not catalog_candidate_matches_specifications(
                state.catalog_result,
                request.constraints.specifications,
                selected_product_code,
            ):
                executor.block("catalog", "selected product does not match requested specifications")
                status = state.catalog_result.status.model_copy(update={
                    "business_status": BusinessStatus.VALIDATION_FAILED,
                    "failure_layer": FailureLayer.VALIDATION,
                    "reason_code": "catalog_specification_mismatch",
                })
                return finish(
                    status, "S4", business=BusinessStatus.VALIDATION_FAILED,
                    next_action="要求仕様に合う商品を選択する",
                )
            executor.reuse(
                "catalog", inputs={"saved_product_code": selected_product_code},
                output_refs=[selected.evidence_id],
                reason="reuse grounded candidate from AgentSession",
            )
            codes = await self._run_code_step(
                selected=selected, department_name=request.department_name,
                state=state, session=session, executor=executor,
                test_case_id=test_case_id,
            )
            if isinstance(codes, ScenarioResult):
                return codes
            if not child_operation_succeeded(codes.status):
                department_not_found = (
                    codes.status.business_status == BusinessStatus.NOT_FOUND
                    or (
                        codes.status.business_status == BusinessStatus.WAITING_USER
                        and (codes.status.reason_code or "").upper() == "DEPARTMENT_NOT_FOUND"
                    )
                )
                if department_not_found:
                    codes.status = codes.status.model_copy(update={
                        "reason_code": "DEPARTMENT_NOT_FOUND",
                    })
                    state.code_result = codes
                    assert staged_intake is not None
                    state.intake = staged_intake.model_copy(update={"department_name": None})
                    executor.wait_for_user("code", "department was not found; user input required")
                    return finish(
                        codes.status, "S3", technical=TechnicalStatus.SUCCESS,
                        business=BusinessStatus.WAITING_USER,
                        next_action="登録済みの所属部署を入力する",
                    )
                executor.block("code", codes.status.reason_code or "code determination failed")
                return finish(
                    codes.status, "S2", business=BusinessStatus.BLOCKED,
                    next_action="Code Toolbox/Search/parse/validation層を確認して再実行する",
                )
            required_codes = [
                codes.account_code, codes.account_name,
                codes.department_code, codes.department_name,
            ]
            if not all(required_codes) or not codes.evidence:
                raise ValueError("code result cannot be accepted without grounded codes and evidence")
            assert staged_intake is not None
            state.intake = staged_intake
            executor.complete(
                "code", output_refs=[item.evidence_id for item in codes.evidence],
                reason="account and department codes grounded before confirmation",
            )
            executor.wait_for_user("merge_validate", "final user confirmation required")
            status = codes.status.model_copy(update={"business_status": BusinessStatus.WAITING_USER})
            return finish(status, "S3", technical=TechnicalStatus.SUCCESS)

        catalog = await self._run_catalog_step(
            request=request, state=state, session=session, executor=executor,
            test_case_id=test_case_id, replan=False,
        )
        if isinstance(catalog, ScenarioResult):
            return catalog
        if isinstance(request, ProcurementIntakeRequest) and catalog_result_is_grounded(catalog):
            exact = _exact_grounded_catalog_match(catalog, request.query)
            if exact is not None:
                state.selected_product_code = exact.product_code
            executor.wait_for_user("catalog", "grounded candidates available; user details or selection required")
            status = catalog.status.model_copy(update={
                "business_status": BusinessStatus.WAITING_USER,
                "reason_code": "SINGLE_EXACT_CATALOG_MATCH" if exact is not None else catalog.status.reason_code,
            })
            return finish(status, "S3", technical=TechnicalStatus.SUCCESS)
        if not catalog_result_is_grounded(catalog):
            should_retry = (
                catalog.status.business_status == BusinessStatus.NOT_FOUND
                or catalog.status.retryable
            )
            if not should_retry:
                executor.block("catalog", catalog.status.reason_code or "catalog result rejected")
                return finish(
                    catalog.status, "S2", business=BusinessStatus.BLOCKED,
                    next_action="Catalog Toolbox/Search/parse/validation層を確認して再実行する",
                )
            executor.retry("catalog", catalog.status.reason_code or "catalog search did not identify a product")
            if state.plan.status.name != "BLOCKED":
                catalog = await self._run_catalog_step(
                    request=request, state=state, session=session, executor=executor,
                    test_case_id=test_case_id, replan=True,
                )
                if isinstance(catalog, ScenarioResult):
                    return catalog
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
                return finish(catalog.status, scenario_id, business=outer_business, next_action=next_action)
        selected = next(item for item in catalog.candidates if item.product_code == catalog.selected_product_code)
        mismatch_keys = specification_mismatch_keys(
            request.constraints.specifications, selected.specifications,
        )
        if mismatch_keys:
            executor.block("catalog", "requested catalog specifications did not match")
            validation_status = catalog.status.model_copy(update={
                "business_status": BusinessStatus.VALIDATION_FAILED,
                "failure_layer": FailureLayer.VALIDATION,
                "retryable": False,
                "reason_code": "catalog_specification_mismatch",
            })
            return finish(
                validation_status, "S1", technical=TechnicalStatus.SUCCESS,
                next_action="要求仕様の項目を確認し、Catalogを再検索する",
            )
        executor.complete("catalog", output_refs=[item.evidence_id for item in catalog.evidence], reason="grounded catalog candidate selected")
        state.evidence_refs.extend(item.evidence_id for item in catalog.evidence)

        codes = await self._run_code_step(
            selected=selected, department_name=request.department_name,
            state=state, session=session, executor=executor,
            test_case_id=test_case_id,
        )
        if isinstance(codes, ScenarioResult):
            return codes
        if not child_operation_succeeded(codes.status):
            executor.block("code", codes.status.reason_code or "code determination failed")
            outer_business = (
                codes.status.business_status
                if codes.status.business_status != BusinessStatus.SUCCESS
                else BusinessStatus.BLOCKED
            )
            return finish(
                codes.status, "S2", business=outer_business,
                next_action="Failure profileを解除し、Code Toolbox/Search/parse/validation層を確認して再実行する",
            )
        required_codes = [codes.account_code, codes.account_name, codes.department_code, codes.department_name]
        if not all(required_codes) or not codes.evidence:
            raise ValueError("code result cannot be accepted without grounded codes and evidence")
        executor.complete("code", output_refs=[item.evidence_id for item in codes.evidence], reason="account and department codes grounded")
        state.evidence_refs.extend(item.evidence_id for item in codes.evidence)

        return self._merge_validated(
            request=request, selected=selected, catalog=catalog, codes=codes,
            state=state, session=session, executor=executor,
            test_case_id=test_case_id,
        )
