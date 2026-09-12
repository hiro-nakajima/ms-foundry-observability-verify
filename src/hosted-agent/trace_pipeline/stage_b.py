"""Stage B semantic-fault harness and facts derived from executed artifacts."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Awaitable, Callable, Literal

from agent_framework import AgentSession
from pydantic import BaseModel

from procurement_agent.controller import ProcurementController, set_machine_status
from procurement_agent.models import (
    ApplicationDraft, ApplicationLine, BusinessStatus, CatalogSearchInput,
    CodeDeterminationInput, PlanStatus, ProcurementRequest, ScenarioResult,
    TechnicalStatus,
)
from procurement_agent.observability import TelemetryRecorder
from procurement_agent.plan import stable_input_hash
from procurement_agent.session_state import load_execution_state, save_execution_state

from .detectors import TraceFacts


StageBPattern = Literal["TV-02", "TV-03", "SD-03", "SD-05", "MA-04", "MA-05"]
StageBHealthyScenario = Literal["S1", "S5"]
StructuredInvoker = Callable[[BaseModel], Awaitable[dict[str, Any] | BaseModel]]


@dataclass
class StageBArtifact:
    pattern_id: StageBPattern
    case_id: str
    result: ScenarioResult
    session: AgentSession
    sequence: list[dict[str, Any]] = field(default_factory=list)
    user_input: dict[str, Any] = field(default_factory=dict)
    response: dict[str, Any] = field(default_factory=dict)
    retrieved_contexts: list[dict[str, Any]] = field(default_factory=list)
    system_prompt: dict[str, Any] = field(default_factory=dict)
    tool_definitions: list[dict[str, Any]] = field(default_factory=list)
    tool_outputs: list[dict[str, Any]] = field(default_factory=list)
    conversation: list[dict[str, Any]] = field(default_factory=list)
    plan: dict[str, Any] = field(default_factory=dict)
    boundary_missing_fields: list[str] = field(default_factory=list)
    received_code_input: dict[str, Any] | None = None
    used_code_input: dict[str, Any] | None = None
    injection_requested: bool = True
    injection_activated: bool = False


@dataclass(kw_only=True)
class StageBHealthyArtifact(StageBArtifact):
    pattern_id: None = None
    scenario_id: StageBHealthyScenario
    injection_requested: bool = False


class StageBInjectionHarness:
    """Execute the real Controller while optionally activating a semantic fault."""

    def __init__(
        self, pattern_id: StageBPattern | None, *,
        catalog_invoker: StructuredInvoker, code_invoker: StructuredInvoker,
        telemetry: TelemetryRecorder | None = None,
        healthy_scenario: StageBHealthyScenario | None = None,
    ) -> None:
        self.pattern_id = pattern_id
        self.healthy_scenario = healthy_scenario
        self.catalog_invoker = catalog_invoker
        self.code_invoker = code_invoker
        self.telemetry = telemetry
        self.sequence: list[dict[str, Any]] = []
        self.tool_outputs: list[dict[str, Any]] = []
        self.boundary_missing_fields: list[str] = []
        self.received_code_input: dict[str, Any] | None = None
        self.used_code_input: dict[str, Any] | None = None
        self.last_catalog_input: CatalogSearchInput | None = None
        self.injection_activated = False

    def _record_call(self, step_id: str, payload: BaseModel, *, after_terminal: bool = False) -> None:
        correlation = getattr(payload, "correlation")
        self.sequence.append({
            "kind": "child.call",
            "step_id": step_id,
            "plan_version": correlation.plan_version,
            "attempt": correlation.attempt,
            "input_hash": stable_input_hash(payload.model_dump(mode="json")),
            "after_terminal": after_terminal,
        })

    async def _catalog(self, payload: BaseModel) -> dict[str, Any] | BaseModel:
        value = CatalogSearchInput.model_validate(payload)
        self.last_catalog_input = value
        result = await self.catalog_invoker(value)
        self._record_call("catalog", value)
        self.tool_outputs.append(_output_summary("catalog", result))
        if self.pattern_id == "SD-03" and value.correlation.attempt == 1 and not self.injection_activated:
            duplicate = await self.catalog_invoker(value)
            self._record_call("catalog", value)
            self.tool_outputs.append(_output_summary("catalog", duplicate))
            self.injection_activated = True
        return result

    async def _code(self, payload: BaseModel) -> dict[str, Any] | BaseModel:
        value = CodeDeterminationInput.model_validate(payload)
        self.received_code_input = value.model_dump(mode="json")
        if self.pattern_id == "MA-04":
            invalid = value.model_dump(mode="json")
            invalid.pop("product_category")
            self.boundary_missing_fields = ["product_category"]
            self.sequence.append({
                "kind": "handoff.rejected",
                "missing_fields": list(self.boundary_missing_fields),
            })
            self.tool_outputs.append({
                "step_id": "code",
                "outcome": "SCHEMA_REJECTED",
                "missing_fields": list(self.boundary_missing_fields),
            })
            self.injection_activated = True
            return CodeDeterminationInput.model_validate(invalid)

        used = value
        if self.pattern_id == "MA-05":
            used = value.model_copy(update={"department_name": "無視された部名（Stage B）"})
            self.injection_activated = used.department_name != value.department_name
        self.used_code_input = used.model_dump(mode="json")
        result = await self.code_invoker(used)
        self._record_call("code", used)
        self.tool_outputs.append(_output_summary("code", result))
        return result

    async def run(
        self, request: ProcurementRequest, *, session: AgentSession | None = None,
        test_case_id: str,
    ) -> StageBArtifact:
        session = session or AgentSession()
        controller = ProcurementController(
            self._catalog, self._code, telemetry=self.telemetry,
        )
        result = await controller.execute(
            request, session=session, test_case_id=test_case_id,
        )

        if self.pattern_id in {"TV-02", "TV-03"}:
            inner_failure = result.status is not None and result.status.business_status != BusinessStatus.SUCCESS
            if inner_failure:
                state = load_execution_state(session)
                assert state is not None and state.plan is not None and state.catalog_result is not None
                candidate = next(
                    item for item in state.catalog_result.candidates
                    if item.product_code == state.catalog_result.selected_product_code
                )
                subtotal = Decimal(candidate.unit_price) * request.quantity
                invalid_draft = ApplicationDraft(
                    request_id=request.request_id,
                    lines=[ApplicationLine(
                        product_code=candidate.product_code,
                        product_name=candidate.product_name,
                        category=candidate.category,
                        quantity=request.quantity,
                        unit_price=candidate.unit_price,
                        currency=candidate.currency,
                        subtotal=subtotal,
                        account_code="UNVALIDATED-ACCOUNT",
                        account_name="未検証勘定科目（Stage B）",
                    )],
                    department_code="UNVALIDATED-DEPARTMENT",
                    department_name=request.department_name,
                    memo=request.memo,
                    total=subtotal,
                    evidence_refs=[item.evidence_id for item in state.catalog_result.evidence],
                    warnings=["Stage B semantic fault: failed code output was accepted"],
                )
                for step in state.plan.steps:
                    step.status = PlanStatus.COMPLETED
                state.plan.status = PlanStatus.COMPLETED
                state.draft = invalid_draft
                self.sequence.append({"kind": "response.generated"})
                result = ScenarioResult(
                    scenario_id="S2",
                    test_case_id=test_case_id,
                    technical_status=TechnicalStatus.SUCCESS,
                    business_status=BusinessStatus.SUCCESS,
                    draft=invalid_draft,
                    status=result.status,
                    trace=result.trace,
                )
                set_machine_status(
                    state, result.status,
                    outer_technical=TechnicalStatus.SUCCESS,
                    outer_business=BusinessStatus.SUCCESS,
                )
                save_execution_state(session, state)
                self.injection_activated = True

        self.sequence.append({
            "kind": "terminal",
            "business_status": result.business_status.value,
        })
        if self.pattern_id == "SD-05" and self.last_catalog_input is not None:
            post_terminal = await self.catalog_invoker(self.last_catalog_input)
            self._record_call("catalog", self.last_catalog_input, after_terminal=True)
            self.tool_outputs.append(_output_summary("catalog", post_terminal))
            self.injection_activated = True

        persisted = load_execution_state(session)
        assert persisted is not None
        retrieved_contexts = []
        for child_result in (persisted.catalog_result, persisted.code_result):
            if child_result is not None:
                retrieved_contexts.extend(
                    item.model_dump(mode="json") for item in child_result.evidence
                )

        artifact_fields = dict(
            case_id=test_case_id,
            result=result,
            session=session,
            sequence=list(self.sequence),
            user_input=request.model_dump(mode="json"),
            response=result.model_dump(mode="json"),
            retrieved_contexts=retrieved_contexts,
            system_prompt={
                "agent_role": "coordinator",
                "implementation_kind": "controller",
            },
            tool_definitions=[
                {"name": "catalog", "input_schema": "CatalogSearchInput"},
                {"name": "code", "input_schema": "CodeDeterminationInput"},
            ],
            tool_outputs=list(self.tool_outputs),
            conversation=[{"role": "user", "request_id": request.request_id}],
            plan=persisted.plan.model_dump(mode="json") if persisted.plan else {},
            boundary_missing_fields=list(self.boundary_missing_fields),
            received_code_input=self.received_code_input,
            used_code_input=self.used_code_input,
            injection_activated=self.injection_activated,
        )
        if self.pattern_id is not None:
            return StageBArtifact(pattern_id=self.pattern_id, **artifact_fields)
        assert self.healthy_scenario is not None
        return StageBHealthyArtifact(
            scenario_id=self.healthy_scenario, **artifact_fields,
        )


class StageBHealthyControlHarness(StageBInjectionHarness):
    """Execute an S1/S5 control through the same real child-invoker path."""

    def __init__(
        self, scenario_id: StageBHealthyScenario, *,
        catalog_invoker: StructuredInvoker, code_invoker: StructuredInvoker,
        telemetry: TelemetryRecorder | None = None,
    ) -> None:
        super().__init__(
            None,
            catalog_invoker=catalog_invoker,
            code_invoker=code_invoker,
            telemetry=telemetry,
            healthy_scenario=scenario_id,
        )

    async def run(
        self, request: ProcurementRequest, *, session: AgentSession | None = None,
        test_case_id: str,
    ) -> StageBHealthyArtifact:
        artifact = await super().run(
            request, session=session, test_case_id=test_case_id,
        )
        assert isinstance(artifact, StageBHealthyArtifact)
        return artifact


def derive_trace_facts(artifact: StageBArtifact) -> TraceFacts:
    """Derive detector inputs from calls/events produced by the executed run."""
    calls = [item for item in artifact.sequence if item["kind"] == "child.call"]
    keys = [
        (item["plan_version"], item["step_id"], item["attempt"], item["input_hash"])
        for item in calls
    ]
    duplicate_step = any(count > 1 for count in Counter(keys).values())
    actions_after_terminal = sum(bool(item.get("after_terminal")) for item in calls)
    kinds = {item["kind"] for item in artifact.sequence}
    present_fields = []
    if artifact.user_input:
        present_fields.append("user_input")
    if artifact.response:
        present_fields.append("response")
    if artifact.retrieved_contexts:
        present_fields.append("retrieved_contexts")
    if artifact.system_prompt:
        present_fields.append("system_prompt")
    if artifact.tool_definitions:
        present_fields.append("tool_definitions")
    if calls or "handoff.rejected" in kinds:
        present_fields.append("tool_calls")
    if artifact.tool_outputs:
        present_fields.append("tool_output")
    if artifact.sequence:
        present_fields.append("agent_trace")
    if artifact.conversation:
        present_fields.append("conversation")
    if artifact.plan:
        present_fields.append("plan")

    received_values_used = True
    if artifact.received_code_input is not None and artifact.used_code_input is not None:
        received_values_used = all(
            artifact.received_code_input.get(name) == artifact.used_code_input.get(name)
            for name in ("product_category", "department_name")
        )

    failed_tool_output = any(
        item.get("business_status") not in {None, BusinessStatus.SUCCESS.value}
        for item in artifact.tool_outputs
    )
    validated_draft = artifact.response.get("draft") or {}
    plan_completed = artifact.plan.get("status") == PlanStatus.COMPLETED.value
    validation_coverage_complete = not (
        failed_tool_output
        and validated_draft.get("status") == "VALIDATED"
        and plan_completed
    )
    evidence_consistent = _draft_matches_evidence(validated_draft, artifact.retrieved_contexts)

    return TraceFacts(
        case_id=artifact.case_id,
        technical_status=artifact.result.technical_status.value,
        present_fields=present_fields,
        duplicate_step=duplicate_step,
        actions_after_terminal=actions_after_terminal,
        handoff_required_fields_missing=artifact.boundary_missing_fields,
        received_values_used=received_values_used,
        validation_coverage_complete=validation_coverage_complete,
        evidence_consistent=evidence_consistent,
    )


def _output_summary(step_id: str, value: dict[str, Any] | BaseModel) -> dict[str, Any]:
    raw = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    status = raw.get("status", {}) if isinstance(raw, dict) else {}
    return {
        "step_id": step_id,
        "technical_status": status.get("technical_status"),
        "business_status": status.get("business_status"),
        "failure_layer": status.get("failure_layer"),
    }


def _draft_matches_evidence(
    draft: dict[str, Any], retrieved_contexts: list[dict[str, Any]],
) -> bool:
    if not draft:
        return True
    account_keys = {
        item.get("record_key") for item in retrieved_contexts
        if item.get("record_type") == "account_code"
    }
    department_keys = {
        item.get("record_key") for item in retrieved_contexts
        if item.get("record_type") == "department"
    }
    product_keys = {
        item.get("record_key") for item in retrieved_contexts
        if item.get("record_type") == "product"
    }
    lines = draft.get("lines") or []
    return bool(lines) and all(
        line.get("product_code") in product_keys
        and line.get("account_code") in account_keys
        for line in lines
    ) and draft.get("department_code") in department_keys
