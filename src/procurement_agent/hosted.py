"""Hosted Single/Multi local Agent Framework factory and Plan & Execute harness."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent_framework import Agent, BaseChatClient, FunctionTool
from trace_pipeline.envelope import RunIdentity, TraceEvaluationEnvelope
from trace_pipeline.normalize import build_envelope

from .framework import (
    DeterministicChatClient,
    SerializedProcurementContextProvider,
    StructuredPlannerHandler,
    marker_response_handler,
)
from .conversation import natural_missing_required_fields
from .governance import GovernanceAdapter
from .intake import (
    DepartmentCandidateResolver,
    LlmProcurementIntake,
    structured_output_options,
    structured_output_timeout_seconds,
)
from .memory import AgentSession, InMemoryContextProvider
from .middleware import GovernanceMiddleware
from .models import (
    AccountCode,
    AgentPlanResponse,
    AgentRole,
    AgentToolResult,
    AgentToolTask,
    Applicant,
    ApplicationDraft,
    BusinessStatus,
    CalculationResult,
    CatalogItem,
    DeliveryEstimate,
    Department,
    DraftAccount,
    DraftApplicant,
    DraftItem,
    GovernanceDecision,
    GovernanceMode,
    ImplementationKind,
    LogicalPattern,
    PlanStatus,
    ProcurementContextSnapshot,
    ProcurementRequest,
    StrictModel,
    ToolResponse,
    ValidationResult,
)
from .observability import TelemetryRecorder
from .plan import MULTI_TEMPLATE, SINGLE_TEMPLATE, StructuredPlanBuilder
from .skills_runtime import AllowlistedSkillScriptRunner, build_request_check_skills_provider
from .tools import LocalJsonAdapter, default_data_resource


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = Path(__file__).parent / "policies" / "policy.yaml"
SKILLS_ROOT = Path(__file__).parent / "skills"


class HostedRunOutcome(StrictModel):
    response_text: str
    session: AgentSession
    envelope: TraceEvaluationEnvelope
    status_summary: dict[str, Any]
    trace_id: str
    resumed: bool = False


@dataclass
class RunLedger:
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_outputs: list[dict[str, Any]] = field(default_factory=list)
    retrieved_contexts: list[dict[str, Any]] = field(default_factory=list)
    delegations: list[dict[str, Any]] = field(default_factory=list)
    validations: list[dict[str, Any]] = field(default_factory=list)
    governance_decision_offset: int = 0


def _hash_payload(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalized_specifications(value: dict[str, Any]) -> dict[str, str]:
    return {
        str(key).strip().casefold(): str(item).strip().casefold()
        for key, item in value.items()
    }


def _select_catalog_candidate(
    search_response: ToolResponse,
    required_specifications: dict[str, str],
    *,
    step_id: str,
    governance_decisions: list[Any] | None = None,
) -> dict[str, Any]:
    candidates = list(search_response.result.get("candidates", []))
    if not candidates:
        raise ValueError("search_catalog returned no candidates")
    required = _normalized_specifications(required_specifications)
    eligible = candidates
    if required:
        matches = []
        for candidate in candidates:
            actual = _normalized_specifications(
                candidate.get("item", {}).get("specifications", {})
            )
            if all(actual.get(key) == value for key, value in required.items()):
                matches.append(candidate)
        if not matches:
            # The search adapter provides a stable score/product-code ordering.
            # Preserve its strongest grounded item so deterministic draft
            # validation can report the unmet specification constraint.
            return candidates[0]
        eligible = matches
    top_score = eligible[0].get("score")
    top_candidates = [
        candidate for candidate in eligible if candidate.get("score") == top_score
    ]
    if len(top_candidates) > 1:
        raise BusinessOperationFailed(
            tool_name="search_catalog",
            step_id=step_id,
            business_status=BusinessStatus.CLARIFICATION_REQUIRED,
            result={
                "clarification": {
                    "field": "catalog_item",
                    "required_input_refs": [
                        "request.query",
                        "request.constraints.specifications",
                    ],
                    "prompt": "商品を特定できる検索条件または仕様を指定してください。",
                    "options": [
                        {
                            "product_code": candidate["item"]["product_code"],
                            "name": candidate["item"]["name"],
                            "specifications": candidate["item"]["specifications"],
                        }
                        for candidate in top_candidates
                    ],
                }
            },
            evidence_refs=search_response.evidence_refs,
            tool_call_ids=[search_response.call_id],
            governance_decisions=governance_decisions,
        )
    # If no item satisfies all requested specifications, preserve the strongest
    # unique search result so deterministic validation can report the mismatch.
    return top_candidates[0]


class BusinessOperationFailed(RuntimeError):
    """Technically successful operation whose domain result stops the plan."""

    def __init__(
        self,
        *,
        tool_name: str,
        step_id: str,
        business_status: BusinessStatus,
        http_status: int = 200,
        evidence_refs: list[str] | None = None,
        warnings: list[str] | None = None,
        tool_call_ids: list[str] | None = None,
        governance_decisions: list[Any] | None = None,
        delegation_tool_name: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> None:
        self.tool_name = tool_name
        self.step_id = step_id
        self.business_status = business_status
        self.http_status = http_status
        self.evidence_refs = list(evidence_refs or [])
        self.warnings = list(warnings or [])
        self.tool_call_ids = list(tool_call_ids or [])
        self.governance_decisions = list(governance_decisions or [])
        self.delegation_tool_name = delegation_tool_name
        self.result = dict(result or {})
        super().__init__(f"{tool_name} returned {business_status.value}")

    @classmethod
    def from_tool_response(
        cls,
        response: ToolResponse,
        *,
        tool_name: str,
        step_id: str,
        governance_decisions: list[Any] | None = None,
    ) -> "BusinessOperationFailed":
        return cls(
            tool_name=tool_name,
            step_id=step_id,
            business_status=response.business_status,
            http_status=response.http_status,
            evidence_refs=response.evidence_refs,
            warnings=response.warnings,
            tool_call_ids=[response.call_id],
            governance_decisions=governance_decisions,
            result=response.result,
        )


class ExecutionSupport:
    """Governed tool and skill execution shared by Single and specialists."""

    def __init__(
        self,
        adapter: LocalJsonAdapter,
        governance: GovernanceAdapter,
        telemetry: TelemetryRecorder,
        script_runner: AllowlistedSkillScriptRunner,
        ledger: RunLedger,
    ) -> None:
        self.adapter = adapter
        self.governance = governance
        self.middleware = GovernanceMiddleware(governance)
        self.telemetry = telemetry
        self.script_runner = script_runner
        self._ledger_var: ContextVar[RunLedger] = ContextVar(
            f"procurement_run_ledger_{id(self)}", default=ledger
        )

    @property
    def ledger(self) -> RunLedger:
        return self._ledger_var.get()

    def bind_ledger(self, ledger: RunLedger) -> Token[RunLedger]:
        return self._ledger_var.set(ledger)

    def reset_ledger(self, token: Token[RunLedger]) -> None:
        self._ledger_var.reset(token)

    def call_tool(
        self,
        *,
        role: AgentRole,
        tool_name: str,
        plan_id: str,
        step_id: str,
        arguments: dict[str, Any],
        operation,
        decisions: list | None = None,
        agent_tool: bool = False,
    ) -> ToolResponse:
        tool_call_count = len(self.ledger.tool_calls) + 1
        agent_tool_call_count = sum(1 for item in self.ledger.tool_calls if item.get("agent_tool"))
        if agent_tool:
            agent_tool_call_count += 1
        with self.telemetry.span(
            "governance.pre_tool",
            {"poc.agent.role": role, "poc.tool.name": tool_name, "poc.plan.id": plan_id},
        ) as governance_span:
            before = self.middleware.run_pre_tool(
                role=role,
                tool_name=tool_name,
                pre_tool_kwargs={
                    "plan_id": plan_id,
                    "step_id": step_id,
                    "plan_status": PlanStatus.RUNNING,
                    "duplicate_step": False,
                    "missing_required_information": False,
                    "tool_call_count": tool_call_count,
                    "agent_tool_call_count": agent_tool_call_count,
                },
            )
            governance_span.set_attributes(
                {
                    "poc.policy.version": before.policy_version,
                    "poc.policy.rule.id": before.rule_id,
                    "poc.governance.stage": before.stage,
                    "poc.governance.decision": before.outcome.value,
                    "poc.plan.step.id": step_id,
                }
            )
        if decisions is not None:
            decisions.append(before)
        call_record = {
            "call_id": f"logical-{uuid4()}",
            "tool_name": tool_name,
            "agent_role": role.value,
            "parent_agent": role.value,
            "step_id": step_id,
            "order": len(self.ledger.tool_calls) + 1,
            "arguments_hash": _hash_payload(arguments),
            "agent_tool": agent_tool,
        }
        self.ledger.tool_calls.append(call_record)
        with self.telemetry.span(
            f"tool.{tool_name}",
            {
                "poc.agent.role": role,
                "poc.tool.name": tool_name,
                "poc.tool.call.id": call_record["call_id"],
            },
        ):
            response = operation()
        provider_call_id = response.call_id
        response = response.model_copy(update={"call_id": call_record["call_id"]})
        with self.telemetry.span(
            "governance.post_tool",
            {"poc.agent.role": role, "poc.tool.name": tool_name, "poc.plan.id": plan_id},
        ) as governance_span:
            after = self.middleware.run_post_tool(
                role=role,
                tool_name=tool_name,
                response=response,
                plan_id=plan_id,
                step_id=step_id,
            )
            governance_span.set_attributes(
                {
                    "poc.policy.version": after.policy_version,
                    "poc.policy.rule.id": after.rule_id,
                    "poc.governance.stage": after.stage,
                    "poc.governance.decision": after.outcome.value,
                    "poc.plan.step.id": step_id,
                }
            )
        if decisions is not None:
            decisions.append(after)
        output_protected = self.telemetry.protect_content("tool_output", response.result)
        self.ledger.tool_outputs.append(
            {
                "call_id": response.call_id,
                "provider_call_id": provider_call_id,
                "tool_name": tool_name,
                "http_status": response.http_status,
                "technical_status": response.technical_status.value,
                "business_status": response.business_status.value,
                "evidence_refs": response.evidence_refs,
                "result": output_protected,
            }
        )
        for rank, ref in enumerate(response.evidence_refs, start=1):
            self.ledger.retrieved_contexts.append(
                {
                    "source_id": ref,
                    "content_ref": ref,
                    "tool_name": tool_name,
                    "data_version": response.data_version,
                    "score": None,
                    "rank": rank,
                }
            )
        return response

    def calculate_with_skill(self, quantity: int, unit_price: str) -> ToolResponse:
        active_rules = self.adapter.active_tax_rules()
        if len(active_rules) != 1:
            return self.adapter.calculate_request(quantity, unit_price)
        active_rule = active_rules[0]
        with self.telemetry.span("skill.request_check", {"poc.skill.name": "request-check"}):
            with self.telemetry.span(
                "script.calculate_request", {"poc.script.name": "calculate_request.py"}
            ):
                raw = self.script_runner.execute(
                    "calculate_request.py",
                    {
                        "quantity": quantity,
                        "unit_price": unit_price,
                        "tax_rate": active_rule["tax_rate"],
                        "discount_rate": "0",
                        "rounding_mode": active_rule["rounding_mode"],
                        "rounding_unit": active_rule["rounding_unit"],
                    },
                )
        result = CalculationResult.model_validate(raw)
        return self.adapter._response(
            business_status=BusinessStatus.SUCCESS,
            result={"calculation": result.model_dump(mode="json")},
            evidence_refs=[f"tax:{active_rule['rule_id']}:{self.adapter.data_version}"],
        )

    def validate_with_skill(self, draft: ApplicationDraft) -> ToolResponse:
        with self.telemetry.span("skill.request_check", {"poc.skill.name": "request-check"}):
            with self.telemetry.span("validation", {"poc.validation.kind": "deterministic"}):
                raw = self.script_runner.execute(
                    "validate_request.py", draft.model_dump(mode="json")
                )
        validation = ValidationResult.model_validate(raw)
        status = BusinessStatus.SUCCESS if validation.valid else BusinessStatus.VALIDATION_FAILED
        return self.adapter._response(
            business_status=status,
            result={"validation": validation.model_dump(mode="json")},
            evidence_refs=validation.evidence_refs,
            warnings=validation.violations,
        )


class ProcurementSpecialistHandler:
    def __init__(self, support: ExecutionSupport) -> None:
        self.support = support

    def __call__(self, messages, options) -> str:
        task = AgentToolTask.model_validate_json(messages[-1].text)
        try:
            return self._execute(task)
        except BusinessOperationFailed as failure:
            result = AgentToolResult(
                task_id=task.task_id,
                agent_role=AgentRole.PROCUREMENT_SPECIALIST,
                business_status=failure.business_status,
                result={
                    **failure.result,
                    "failed_tool": failure.tool_name,
                    "governance_decisions": [
                        item.model_dump(mode="json")
                        for item in failure.governance_decisions
                    ],
                    "tool_call_ids": failure.tool_call_ids,
                },
                evidence_refs=failure.evidence_refs,
                warnings=failure.warnings,
            )
            return result.model_dump_json()

    def _execute(self, task: AgentToolTask) -> str:
        request = task.context_snapshot.request
        decisions: list = []
        tool_records: list[ToolResponse] = []

        def call(name: str, args: dict[str, Any], operation) -> ToolResponse:
            response = self.support.call_tool(
                role=AgentRole.PROCUREMENT_SPECIALIST,
                tool_name=name,
                plan_id=task.plan_id,
                step_id=task.step_ids[0],
                arguments=args,
                operation=operation,
                decisions=decisions,
            )
            tool_records.append(response)
            if response.business_status != BusinessStatus.SUCCESS:
                raise BusinessOperationFailed.from_tool_response(
                    response,
                    tool_name=name,
                    step_id=task.step_ids[0],
                    governance_decisions=decisions,
                )
            return response

        search = call(
            "search_catalog", {"query": request.query}, lambda: self.support.adapter.search_catalog(request.query)
        )
        product_code = _select_catalog_candidate(
            search,
            request.constraints.specifications,
            step_id=task.step_ids[0],
            governance_decisions=decisions,
        )["item"]["product_code"]
        item_response = call(
            "get_catalog_item",
            {"product_code": product_code},
            lambda: self.support.adapter.get_catalog_item(product_code),
        )
        item = CatalogItem.model_validate(item_response.result["item"])
        applicant_response = call(
            "get_applicant",
            {"identifier": request.applicant_name},
            lambda: self.support.adapter.get_applicant(request.applicant_name or ""),
        )
        applicant = Applicant.model_validate(applicant_response.result["applicant"])
        department_response = call(
            "lookup_department",
            {"identifier": applicant.department_code},
            lambda: self.support.adapter.lookup_department(applicant.department_code),
        )
        department = Department.model_validate(department_response.result["department"])
        if request.department_name:
            requested_department_response = call(
                "lookup_department",
                {"identifier": request.department_name},
                lambda: self.support.adapter.lookup_department(
                    request.department_name or ""
                ),
            )
            requested_department = Department.model_validate(
                requested_department_response.result["department"]
            )
            if requested_department.department_code != department.department_code:
                raise BusinessOperationFailed(
                    tool_name="lookup_department",
                    step_id=task.step_ids[0],
                    business_status=BusinessStatus.VALIDATION_FAILED,
                    evidence_refs=list(
                        dict.fromkeys(
                            ref
                            for response in (
                                department_response,
                                requested_department_response,
                            )
                            for ref in response.evidence_refs
                        )
                    ),
                    warnings=[
                        "request.department_name does not match applicant department"
                    ],
                    tool_call_ids=[record.call_id for record in tool_records],
                    governance_decisions=decisions,
                )
        account_response = call(
            "lookup_account_code",
            {"category": item.category, "purpose": request.purpose},
            lambda: self.support.adapter.lookup_account_code(item.category, request.purpose or ""),
        )
        account = AccountCode.model_validate(account_response.result["account_code"])
        delivery_response = call(
            "estimate_delivery",
            {
                "product_code": item.product_code,
                "quantity": request.quantity,
                "requested_by": request.constraints.requested_by,
            },
            lambda: self.support.adapter.estimate_delivery(
                item.product_code, request.quantity or 0, request.constraints.requested_by
            ),
        )
        delivery = DeliveryEstimate.model_validate(delivery_response.result["delivery"])
        evidence = list(dict.fromkeys(ref for record in tool_records for ref in record.evidence_refs))
        result = AgentToolResult(
            task_id=task.task_id,
            agent_role=AgentRole.PROCUREMENT_SPECIALIST,
            business_status=BusinessStatus.SUCCESS,
            result={
                "item": item.model_dump(mode="json"),
                "applicant": applicant.model_dump(mode="json"),
                "department": department.model_dump(mode="json"),
                "account_code": account.model_dump(mode="json"),
                "delivery_estimate": delivery.model_dump(mode="json"),
                "governance_decisions": [item.model_dump(mode="json") for item in decisions],
                "tool_call_ids": [item.call_id for item in tool_records],
            },
            evidence_refs=evidence,
        )
        return result.model_dump_json()


class DraftingSpecialistHandler:
    def __init__(self, support: ExecutionSupport) -> None:
        self.support = support

    def __call__(self, messages, options) -> str:
        task = AgentToolTask.model_validate_json(messages[-1].text)
        snapshot = task.context_snapshot
        if not all(
            [
                snapshot.selected_item,
                snapshot.applicant,
                snapshot.department,
                snapshot.account_code,
                snapshot.delivery_estimate,
            ]
        ):
            raise ValueError("drafting specialist requires a complete ProcurementContextSnapshot")
        decisions: list = []
        calculation_response = self.support.call_tool(
            role=AgentRole.DRAFTING_SPECIALIST,
            tool_name="calculate_request",
            plan_id=task.plan_id,
            step_id=task.step_ids[0],
            arguments={
                "quantity": snapshot.request.quantity,
                "unit_price": str(snapshot.selected_item.unit_price),
            },
            operation=lambda: self.support.calculate_with_skill(
                snapshot.request.quantity or 0, str(snapshot.selected_item.unit_price)
            ),
            decisions=decisions,
        )
        if calculation_response.business_status != BusinessStatus.SUCCESS:
            result = AgentToolResult(
                task_id=task.task_id,
                agent_role=AgentRole.DRAFTING_SPECIALIST,
                business_status=calculation_response.business_status,
                result={
                    "failed_tool": "calculate_request",
                    "governance_decisions": [
                        item.model_dump(mode="json") for item in decisions
                    ],
                    "tool_call_ids": [calculation_response.call_id],
                },
                evidence_refs=calculation_response.evidence_refs,
                warnings=calculation_response.warnings,
            )
            return result.model_dump_json()
        calculation = CalculationResult.model_validate(calculation_response.result["calculation"])
        draft = ApplicationDraft(
            request_id=snapshot.request.request_id,
            item=DraftItem(
                product_code=snapshot.selected_item.product_code,
                name=snapshot.selected_item.name,
                quantity=snapshot.request.quantity or 0,
                unit_price=snapshot.selected_item.unit_price,
                currency=snapshot.selected_item.currency,
                specifications=snapshot.selected_item.specifications,
            ),
            amount=calculation,
            delivery=snapshot.delivery_estimate,
            applicant=DraftApplicant(
                employee_id=snapshot.applicant.employee_id,
                name=snapshot.applicant.name,
                department_code=snapshot.department.department_code,
            ),
            account=DraftAccount(
                account_code=snapshot.account_code.account_code,
                label=snapshot.account_code.label,
            ),
            request_constraints=snapshot.request.constraints,
            evidence_refs=list(
                dict.fromkeys(snapshot.evidence_refs + calculation_response.evidence_refs)
            ),
            warnings=snapshot.delivery_estimate.warnings,
        )
        result = AgentToolResult(
            task_id=task.task_id,
            agent_role=AgentRole.DRAFTING_SPECIALIST,
            business_status=BusinessStatus.SUCCESS,
            result={
                "application_draft": draft.model_dump(mode="json"),
                "calculation": calculation.model_dump(mode="json"),
                "governance_decisions": [item.model_dump(mode="json") for item in decisions],
                "tool_call_ids": [calculation_response.call_id],
            },
            evidence_refs=draft.evidence_refs,
        )
        return result.model_dump_json()


@dataclass
class HostedAgentBundle:
    pattern: LogicalPattern
    coordinator: Agent
    planner: Agent
    planner_client: BaseChatClient
    context_provider: SerializedProcurementContextProvider
    skills_provider: Any
    script_runner: AllowlistedSkillScriptRunner
    support: ExecutionSupport
    procurement_specialist: Agent | None = None
    drafting_specialist: Agent | None = None
    procurement_tool: FunctionTool | None = None
    drafting_tool: FunctionTool | None = None
    application: Any | None = None


def _agent_properties(role: AgentRole, pattern: LogicalPattern, implementation_kind: str) -> dict[str, Any]:
    return {
        "logical_pattern": pattern.value,
        "agent_role": role.value,
        "agent_definition_id": f"local:{pattern.value}:{role.value}:0.1.0",
        "foundry_resource_id": None,
        "implementation_kind": implementation_kind,
    }


def _planner_instructions(pattern: LogicalPattern) -> str:
    source = MULTI_TEMPLATE if pattern == LogicalPattern.HOSTED_MULTI else SINGLE_TEMPLATE
    template = [
        {
            "step_id": step_id,
            "step_type": step_type,
            "owner": owner.value,
            "input_refs": input_refs,
        }
        for step_id, step_type, owner, input_refs in source
    ]
    return (
        "Return one AgentPlanResponse BaseModel and do not call tools or execute the plan. "
        "Copy the exact approved step IDs, order, owners, and input_refs from this hosted "
        "procurement template: "
        + json.dumps(template, ensure_ascii=False, sort_keys=True)
        + ". "
        "Do not include runtime status, timestamps, attempts, evidence, tool calls, or reasoning."
    )


def build_local_hosted_bundle(
    pattern: LogicalPattern,
    *,
    data_dir: str | Path | None = None,
    governance_mode: GovernanceMode = GovernanceMode.SHADOW,
    record_raw_content: bool = False,
    planner_returns_empty: bool = False,
    intake_client: BaseChatClient | None = None,
) -> HostedAgentBundle:
    if pattern not in {LogicalPattern.HOSTED_SINGLE, LogicalPattern.HOSTED_MULTI}:
        raise ValueError("Hosted factory accepts only HA-S or HA-M")
    adapter = LocalJsonAdapter(data_dir if data_dir is not None else default_data_resource())
    telemetry = TelemetryRecorder(
        synthetic_environment=True, record_raw_content=record_raw_content
    )
    governance = GovernanceAdapter(POLICY_PATH, mode=governance_mode)
    skills_provider, runner = build_request_check_skills_provider(SKILLS_ROOT)
    ledger = RunLedger()
    support = ExecutionSupport(adapter, governance, telemetry, runner, ledger)
    intake = LlmProcurementIntake.from_environment(
        telemetry=telemetry,
        client=intake_client,
    )
    context_provider = SerializedProcurementContextProvider(
        intake=intake,
        department_resolver=DepartmentCandidateResolver(adapter.departments),
    )
    if intake_client is None and intake.client is not None and not planner_returns_empty:
        planner_client: BaseChatClient = intake.client
    else:
        planner_client = DeterministicChatClient(
            StructuredPlannerHandler(pattern, return_empty=planner_returns_empty),
            client_name=f"{pattern.value}-planner",
        )
    planner = Agent(
        client=planner_client,
        name=f"{pattern.value.lower()}-planner",
        description="Produces only the Pydantic ExecutionPlan proposal.",
        instructions=_planner_instructions(pattern),
        tools=[],
        additional_properties=_agent_properties(
            AgentRole.COORDINATOR
            if pattern == LogicalPattern.HOSTED_MULTI
            else AgentRole.PROCUREMENT_ASSISTANT,
            pattern,
            ImplementationKind.LOCAL_DETERMINISTIC.value,
        ),
    )
    root_client = DeterministicChatClient(marker_response_handler, client_name=f"{pattern.value}-root")

    if pattern == LogicalPattern.HOSTED_SINGLE:
        coordinator = Agent(
            client=root_client,
            name="hosted-procurement-single",
            description="Plan & Execute procurement assistant using synthetic structured tools.",
            instructions=(
                "Use only the explicit ExecutionPlan and structured tool evidence. "
                "Never infer product codes, prices, account codes, delivery dates, or totals."
            ),
            tools=[
                adapter.search_catalog,
                adapter.get_catalog_item,
                adapter.lookup_account_code,
                adapter.lookup_department,
                adapter.get_applicant,
                adapter.estimate_delivery,
                adapter.calculate_request,
                adapter.validate_application,
            ],
            context_providers=[context_provider, skills_provider],
            additional_properties=_agent_properties(
                AgentRole.PROCUREMENT_ASSISTANT,
                pattern,
                ImplementationKind.LOCAL_DETERMINISTIC.value,
            ),
        )
        bundle = HostedAgentBundle(
            pattern=pattern,
            coordinator=coordinator,
            planner=planner,
            planner_client=planner_client,
            context_provider=context_provider,
            skills_provider=skills_provider,
            script_runner=runner,
            support=support,
        )
    else:
        procurement_specialist = Agent(
            client=DeterministicChatClient(
                ProcurementSpecialistHandler(support), client_name="procurement-specialist"
            ),
            name="procurement_specialist",
            description="Returns grounded catalog, applicant, department, account, and delivery data.",
            instructions="Accept one AgentToolTask JSON and return one AgentToolResult JSON.",
            tools=[
                adapter.search_catalog,
                adapter.get_catalog_item,
                adapter.lookup_account_code,
                adapter.lookup_department,
                adapter.get_applicant,
                adapter.estimate_delivery,
            ],
            additional_properties=_agent_properties(
                AgentRole.PROCUREMENT_SPECIALIST,
                pattern,
                ImplementationKind.IN_PROCESS_AGENT_AS_TOOL.value,
            ),
        )
        drafting_specialist = Agent(
            client=DeterministicChatClient(
                DraftingSpecialistHandler(support), client_name="drafting-specialist"
            ),
            name="drafting_specialist",
            description="Calculates and builds a grounded procurement draft from a context snapshot.",
            instructions="Accept one AgentToolTask JSON and return one AgentToolResult JSON.",
            tools=[adapter.calculate_request, adapter.validate_application],
            context_providers=[skills_provider],
            additional_properties=_agent_properties(
                AgentRole.DRAFTING_SPECIALIST,
                pattern,
                ImplementationKind.IN_PROCESS_AGENT_AS_TOOL.value,
            ),
        )
        procurement_tool = procurement_specialist.as_tool(
            name="procurement_specialist",
            description="Structured procurement lookup delegation. Input must be AgentToolTask JSON.",
            arg_name="task",
            propagate_session=False,
        )
        drafting_tool = drafting_specialist.as_tool(
            name="drafting_specialist",
            description="Structured drafting delegation. Input must be AgentToolTask JSON.",
            arg_name="task",
            propagate_session=False,
        )
        procurement_tool.additional_properties = dict(procurement_tool.additional_properties or {})
        drafting_tool.additional_properties = dict(drafting_tool.additional_properties or {})
        procurement_tool.additional_properties["propagate_session"] = False
        drafting_tool.additional_properties["propagate_session"] = False
        coordinator = Agent(
            client=root_client,
            name="hosted-procurement-coordinator",
            description="Coordinator whose only tools are the two specialist agents.",
            instructions=(
                "Coordinator Session is authoritative. Pass ProcurementContextSnapshot JSON to "
                "specialists, validate their AgentToolResult, then perform final validation."
            ),
            tools=[procurement_tool, drafting_tool],
            context_providers=[context_provider],
            additional_properties=_agent_properties(
                AgentRole.COORDINATOR,
                pattern,
                ImplementationKind.IN_PROCESS_AGENT_AS_TOOL.value,
            ),
        )
        bundle = HostedAgentBundle(
            pattern=pattern,
            coordinator=coordinator,
            planner=planner,
            planner_client=planner_client,
            context_provider=context_provider,
            skills_provider=skills_provider,
            script_runner=runner,
            support=support,
            procurement_specialist=procurement_specialist,
            drafting_specialist=drafting_specialist,
            procurement_tool=procurement_tool,
            drafting_tool=drafting_tool,
        )
    application = HostedProcurementApplication(bundle)
    context_provider.bind(
        application.run,
        invalid_input_gate=lambda raw: support.middleware.run_pre_input(
            raw, application.role
        ),
    )
    bundle.application = application
    return bundle


class HostedProcurementApplication:
    """Application-owned Plan & Execute loop used by Local and DevUI paths."""

    def __init__(self, bundle: HostedAgentBundle) -> None:
        self.bundle = bundle
        self.support = bundle.support
        self.context = InMemoryContextProvider()
        self.plan_builder = StructuredPlanBuilder()

    @property
    def role(self) -> AgentRole:
        return (
            AgentRole.COORDINATOR
            if self.bundle.pattern == LogicalPattern.HOSTED_MULTI
            else AgentRole.PROCUREMENT_ASSISTANT
        )

    async def _create_plan(
        self,
        request: ProcurementRequest,
        *,
        required_missing_fields: list[str] | None = None,
    ):
        with self.support.telemetry.span(
            "plan.create", {"poc.logical.pattern": self.bundle.pattern.value}
        ):
            async with asyncio.timeout(structured_output_timeout_seconds()):
                response = await self.bundle.planner.run(
                    request.model_dump_json(),
                    options=structured_output_options(AgentPlanResponse),
                )
            raw = response.value
            if raw is None and response.text:
                try:
                    raw = AgentPlanResponse.model_validate_json(response.text)
                except ValueError:
                    raw = {}
            return self.plan_builder.build(
                request,
                self.bundle.pattern,
                raw_response=raw if raw is not None else {},
                required_missing_fields=required_missing_fields,
            )

    async def _step(self, executor, step_id: str, inputs: Any, operation):
        with self.support.telemetry.span(
            "plan.step.execute", {"poc.plan.step.id": step_id, "poc.plan.id": executor.plan.plan_id}
        ) as span:
            executor.start(step_id, inputs)
            self.support.telemetry.add_event(
                span, "step_state_changed", {"poc.plan.step.id": step_id, "poc.plan.step.status": "RUNNING"}
            )
            result = operation()
            if inspect.isawaitable(result):
                result = await result
            value, output_refs, evidence_refs, tool_call_ids = result
            executor.complete(
                step_id,
                output_refs=output_refs,
                evidence_refs=evidence_refs,
                tool_call_ids=tool_call_ids,
                reason="observable step outputs recorded",
            )
            self.support.telemetry.add_event(
                span,
                "step_state_changed",
                {"poc.plan.step.id": step_id, "poc.plan.step.status": "COMPLETED"},
            )
            return value

    @staticmethod
    def _success(response: ToolResponse, tool_name: str, step_id: str) -> ToolResponse:
        if response.business_status != BusinessStatus.SUCCESS:
            raise BusinessOperationFailed.from_tool_response(
                response, tool_name=tool_name, step_id=step_id
            )
        return response

    async def _governed_agent_tool(
        self,
        *,
        tool: FunctionTool,
        role_span: str,
        task: AgentToolTask,
        coordinator_session: AgentSession,
        step_id: str,
    ) -> AgentToolResult:
        tool_call_count = len(self.support.ledger.tool_calls) + 1
        agent_tool_call_count = sum(
            1 for item in self.support.ledger.tool_calls if item.get("agent_tool")
        ) + 1
        with self.support.telemetry.span(
            "governance.pre_tool", {"poc.tool.name": tool.name}
        ) as governance_span:
            before = self.support.middleware.run_pre_tool(
                role=AgentRole.COORDINATOR,
                tool_name=tool.name,
                pre_tool_kwargs={
                    "plan_id": task.plan_id,
                    "step_id": step_id,
                    "plan_status": PlanStatus.RUNNING,
                    "duplicate_step": False,
                    "missing_required_information": False,
                    "tool_call_count": tool_call_count,
                    "agent_tool_call_count": agent_tool_call_count,
                },
            )
            governance_span.set_attributes(
                {
                    "poc.policy.version": before.policy_version,
                    "poc.policy.rule.id": before.rule_id,
                    "poc.governance.stage": before.stage,
                    "poc.governance.decision": before.outcome.value,
                    "poc.plan.step.id": step_id,
                }
            )
        coordinator_session.governance_decisions.append(before)
        call_id = f"logical-{uuid4()}"
        self.support.ledger.tool_calls.append(
            {
                "call_id": call_id,
                "tool_name": tool.name,
                "agent_role": AgentRole.COORDINATOR.value,
                "parent_agent": AgentRole.COORDINATOR.value,
                "step_id": step_id,
                "order": len(self.support.ledger.tool_calls) + 1,
                "arguments_hash": _hash_payload(task.model_dump(mode="json")),
                "agent_tool": True,
            }
        )
        with self.support.telemetry.span(role_span, {"poc.plan.id": task.plan_id}):
            raw = await tool.invoke(arguments={"task": task.model_dump_json()}, skip_parsing=True)
        text = "".join(getattr(item, "text", str(item)) for item in raw) if isinstance(raw, list) else str(raw)
        result = AgentToolResult.model_validate_json(text)
        child_decisions = result.result.pop("governance_decisions", [])
        coordinator_session.governance_decisions.extend(
            self._decision_from_json(item) for item in child_decisions
        )
        wrapper = self.support.adapter._response(
            business_status=result.business_status,
            result={"agent_tool_result": result.model_dump(mode="json")},
            evidence_refs=result.evidence_refs,
            warnings=result.warnings,
        )
        with self.support.telemetry.span(
            "governance.post_tool", {"poc.tool.name": tool.name}
        ) as governance_span:
            after = self.support.middleware.run_post_tool(
                role=AgentRole.COORDINATOR,
                tool_name=tool.name,
                response=wrapper,
                plan_id=task.plan_id,
                step_id=step_id,
            )
            governance_span.set_attributes(
                {
                    "poc.policy.version": after.policy_version,
                    "poc.policy.rule.id": after.rule_id,
                    "poc.governance.stage": after.stage,
                    "poc.governance.decision": after.outcome.value,
                    "poc.plan.step.id": step_id,
                }
            )
        coordinator_session.governance_decisions.append(after)
        self.support.ledger.tool_outputs.append(
            {
                "call_id": call_id,
                "tool_name": tool.name,
                "technical_status": "SUCCESS",
                "business_status": result.business_status.value,
                "evidence_refs": result.evidence_refs,
                "result": self.support.telemetry.protect_content("agent_tool_output", result.result),
            }
        )
        self.support.ledger.delegations.append(
            {
                "task_id": task.task_id,
                "agent_role": result.agent_role.value,
                "tool_name": tool.name,
                "propagate_session": False,
                "business_status": result.business_status.value,
            }
        )
        result.result.setdefault("tool_call_ids", []).append(call_id)
        return result

    @staticmethod
    def _decision_from_json(value: dict[str, Any]):
        from .models import GovernanceDecision

        return GovernanceDecision.model_validate(value)

    async def run(
        self,
        request: ProcurementRequest,
        *,
        session: AgentSession | None = None,
        resume: bool = False,
        raw_user_input: str | None = None,
        pre_input_decision: GovernanceDecision | None = None,
        user_confirmed: bool = False,
    ) -> HostedRunOutcome:
        token = self.support.bind_ledger(RunLedger())
        try:
            return await self._run_bound(
                request,
                session=session,
                resume=resume,
                raw_user_input=raw_user_input,
                pre_input_decision=pre_input_decision,
                user_confirmed=user_confirmed,
            )
        finally:
            self.support.reset_ledger(token)

    async def _run_bound(
        self,
        request: ProcurementRequest,
        *,
        session: AgentSession | None = None,
        resume: bool = False,
        raw_user_input: str | None = None,
        pre_input_decision: GovernanceDecision | None = None,
        user_confirmed: bool = False,
    ) -> HostedRunOutcome:
        session = session or AgentSession()
        user_text = (
            raw_user_input
            if raw_user_input is not None
            else request.model_dump_json()
        )
        run_id = f"run-{uuid4()}"
        resumed = bool(resume and session.plan and session.request)
        natural_mode = raw_user_input is not None
        confirmed_validation: ValidationResult | None = None
        self.support.ledger.governance_decision_offset = (
            len(session.governance_decisions) if resumed else 0
        )
        with self.support.telemetry.span(
            "agent.invoke",
            {"poc.run.id": run_id, "poc.logical.pattern": self.bundle.pattern.value, "poc.agent.role": self.role},
        ) as root_span:
            trace_id = f"{root_span.get_span_context().trace_id:032x}"
            with self.support.telemetry.span(
                "governance.pre_input", {"poc.agent.role": self.role}
            ) as governance_span:
                pre_input = pre_input_decision or self.support.middleware.run_pre_input(
                    user_text, self.role
                )
                governance_span.set_attributes(
                    {
                        "poc.policy.version": pre_input.policy_version,
                        "poc.policy.rule.id": pre_input.rule_id,
                        "poc.governance.stage": pre_input.stage,
                        "poc.governance.decision": pre_input.outcome.value,
                    }
                )
            session.begin_turn(user_text)
            if resumed:
                session.governance_decisions.append(pre_input)
                with self.support.telemetry.span("plan.resume", {"poc.plan.id": session.active_plan_id or ""}):
                    if session.plan.status == PlanStatus.COMPLETED:
                        self.support.telemetry.add_event(
                            root_span,
                            "completed_plan_reused",
                            {"poc.plan.id": session.active_plan_id or ""},
                        )
                        return self._completed_plan_replay(
                            session=session,
                            user_text=user_text,
                            run_id=run_id,
                            trace_id=trace_id,
                            root_span=root_span,
                        )
                    changed = session.apply_request_update(
                        request.model_dump(mode="python", exclude_unset=True)
                    )
                    request = session.request
                    waiting = next(
                        step for step in session.plan.steps if step.status == PlanStatus.WAITING_USER
                    )
                    executor = session.plan_executor()
                    missing = self._missing_required_fields(request, natural_mode)
                    pending_confirmation = session.governance_state.get(
                        "pending_confirmation"
                    )
                    pending_clarification = session.governance_state.get(
                        "pending_clarification"
                    )
                    accumulated_changes = set(
                        session.governance_state.get(
                            "clarification_changed_refs", []
                        )
                    )
                    if pending_clarification:
                        accumulated_changes.update(changed)
                        session.governance_state[
                            "clarification_changed_refs"
                        ] = sorted(accumulated_changes)
                    if pending_confirmation and user_confirmed and not changed:
                        executor.resume_after_user_input(waiting.step_id)
                        confirmed_validation = ValidationResult.model_validate(
                            pending_confirmation["validation"]
                        )
                        session.governance_state.pop("pending_confirmation", None)
                        self.support.telemetry.add_event(
                            root_span,
                            "application_confirmation_received",
                            {"poc.plan.step.id": waiting.step_id},
                        )
                    elif pending_confirmation and changed:
                        executor.resume_after_user_input(waiting.step_id)
                        invalidated = executor.invalidate_by_refs(changed)
                        session.governance_state.pop("pending_confirmation", None)
                        self.support.telemetry.add_event(
                            root_span,
                            "confirmed_draft_invalidated",
                            {
                                "poc.changed.ref.count": len(changed),
                                "poc.invalidated.step.count": len(invalidated),
                            },
                        )
                    elif pending_confirmation:
                        executor.refresh_waiting(
                            waiting.step_id,
                            ["user.confirmation"],
                            reason="explicit application confirmation required",
                        )
                    elif missing:
                        executor.refresh_waiting(waiting.step_id, missing)
                        self.support.telemetry.add_event(
                            root_span,
                            "plan_still_waiting",
                            {
                                "poc.plan.step.id": waiting.step_id,
                                "poc.missing.field.count": len(missing),
                            },
                        )
                    elif pending_clarification:
                        required_refs = set(
                            pending_clarification.get("required_input_refs", [])
                        )
                        if accumulated_changes & required_refs:
                            executor.resume_after_user_input(waiting.step_id)
                            invalidated = executor.invalidate_by_refs(
                                accumulated_changes
                            )
                            session.governance_state.pop(
                                "pending_clarification", None
                            )
                            session.governance_state.pop(
                                "clarification_changed_refs", None
                            )
                            self.support.telemetry.add_event(
                                root_span,
                                "clarification_resolved",
                                {
                                    "poc.plan.step.id": waiting.step_id,
                                    "poc.invalidated.step.count": len(invalidated),
                                },
                            )
                        else:
                            executor.refresh_waiting(
                                waiting.step_id,
                                required_refs,
                                reason=(
                                    "clarification required for: "
                                    + ", ".join(sorted(required_refs))
                                ),
                            )
                    else:
                        executor.resume_after_user_input(waiting.step_id)
                        self.support.telemetry.add_event(
                            root_span,
                            "plan_resumed",
                            {"poc.plan.step.id": waiting.step_id, "poc.changed.ref.count": len(changed)},
                        )
            else:
                missing = self._missing_required_fields(request, natural_mode)
                if natural_mode:
                    plan = await self._create_plan(
                        request,
                        required_missing_fields=missing,
                    )
                else:
                    plan = await self._create_plan(request)
                session.start_new_plan(request, plan)
                if natural_mode:
                    session.governance_state["interaction_mode"] = "natural"
                session.governance_decisions.append(pre_input)
                executor = session.plan_executor()
                self.support.telemetry.add_event(
                    root_span,
                    "plan_created",
                    {
                        "poc.plan.version": plan.plan_version,
                        "poc.plan.generation_source": plan.generation_source,
                    },
                )
            context = self.context.before_invocation(
                session, user_input=user_text, resumed=resumed
            )
            if session.plan.status == PlanStatus.WAITING_USER:
                response_text = self._waiting_user_response(session)
                self.context.after_invocation(session, response_text=response_text)
                return self._outcome(
                    session,
                    response_text,
                    run_id,
                    trace_id,
                    resumed,
                    validation=None,
                    active_span=root_span,
                )

            if confirmed_validation is not None:
                return await self._complete_confirmed_application(
                    session=session,
                    executor=executor,
                    validation=confirmed_validation,
                    run_id=run_id,
                    trace_id=trace_id,
                    resumed=resumed,
                    root_span=root_span,
                    confirmation_mode="NATURAL_LANGUAGE",
                )

            resolve_step = next(
                step for step in session.plan.steps if step.step_id == "S02"
            )
            if resolve_step.status != PlanStatus.COMPLETED:
                await self._step(
                    executor,
                    "S02",
                    {"missing": self._missing_required_fields(request, natural_mode)},
                    lambda: (True, ["request.complete"], [], []),
                )
            try:
                if self.bundle.pattern == LogicalPattern.HOSTED_SINGLE:
                    validation = await self._run_single(session, executor, request)
                else:
                    validation = await self._run_multi(session, executor, request)
            except BusinessOperationFailed as failure:
                if (
                    failure.business_status
                    == BusinessStatus.CLARIFICATION_REQUIRED
                ):
                    return self._clarification_outcome(
                        session=session,
                        executor=executor,
                        failure=failure,
                        run_id=run_id,
                        trace_id=trace_id,
                        resumed=resumed,
                        root_span=root_span,
                    )
                return self._business_failure_outcome(
                    session=session,
                    executor=executor,
                    failure=failure,
                    run_id=run_id,
                    trace_id=trace_id,
                    resumed=resumed,
                    root_span=root_span,
                )
            draft = session.application_draft
            if draft is None:
                raise RuntimeError("validated run did not produce an ApplicationDraft")
            if not validation.valid:
                return self._validation_failure_outcome(
                    session=session,
                    executor=executor,
                    validation=validation,
                    run_id=run_id,
                    trace_id=trace_id,
                    resumed=resumed,
                    root_span=root_span,
                )
            if natural_mode:
                confirmation_step = next(
                    step
                    for step in session.plan.steps
                    if step.step_type == "confirm_application"
                )
                with self.support.telemetry.span(
                    "governance.pre_output", {"poc.agent.role": self.role}
                ) as governance_span:
                    decision = self.support.middleware.run_pre_output(
                        role=self.role,
                        plan_id=session.plan.plan_id,
                        response_text=draft.model_dump_json(),
                        ungrounded_product_or_code=False,
                        missing_calculation_output=draft.amount.calculated_by
                        != "request-check/scripts/calculate_request.py",
                        validation_not_passed=False,
                        plan_not_ready=any(
                            step.status != PlanStatus.COMPLETED
                            for step in session.plan.steps
                            if step.step_type
                            not in {"confirm_application", "present_draft"}
                        ),
                    )
                    governance_span.set_attributes(
                        {
                            "poc.policy.version": decision.policy_version,
                            "poc.policy.rule.id": decision.rule_id,
                            "poc.governance.stage": decision.stage,
                            "poc.governance.decision": decision.outcome.value,
                        }
                    )
                session.governance_decisions.append(decision)
                session.governance_state["pending_confirmation"] = {
                    "validation": validation.model_dump(mode="json")
                }
                executor.wait_for_user(
                    confirmation_step.step_id,
                    ["user.confirmation"],
                    evidence_refs=validation.evidence_refs,
                    reason="explicit application confirmation required",
                )
                self.support.telemetry.add_event(
                    root_span,
                    "application_confirmation_required",
                    {"poc.plan.step.id": confirmation_step.step_id},
                )
                response_text = json.dumps(
                    {
                        "business_status": "WAITING_USER",
                        "confirmation_required": True,
                        "validated": True,
                        "application_draft": draft.model_dump(mode="json"),
                        "plan_id": session.plan.plan_id,
                        "plan_version": session.plan.plan_version,
                        "observability": self._status_summary(
                            session, trace_id, resumed
                        ),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                )
                self.context.after_invocation(session, response_text=response_text)
                return self._outcome(
                    session,
                    response_text,
                    run_id,
                    trace_id,
                    resumed,
                    validation=validation,
                    active_span=root_span,
                )

            return await self._complete_confirmed_application(
                session=session,
                executor=executor,
                validation=validation,
                run_id=run_id,
                trace_id=trace_id,
                resumed=resumed,
                root_span=root_span,
                confirmation_mode="STRUCTURED_API",
            )

    @staticmethod
    def _missing_required_fields(
        request: ProcurementRequest, natural_mode: bool
    ) -> list[str]:
        return (
            natural_missing_required_fields(request)
            if natural_mode
            else request.missing_required_fields()
        )

    async def _complete_confirmed_application(
        self,
        *,
        session: AgentSession,
        executor,
        validation: ValidationResult,
        run_id: str,
        trace_id: str,
        resumed: bool,
        root_span: Any,
        confirmation_mode: str,
    ) -> HostedRunOutcome:
        draft = session.application_draft
        if draft is None:
            raise RuntimeError("confirmed plan has no ApplicationDraft")
        with self.support.telemetry.span(
            "governance.pre_output", {"poc.agent.role": self.role}
        ) as governance_span:
            decision = self.support.middleware.run_pre_output(
                role=self.role,
                plan_id=session.plan.plan_id,
                response_text=draft.model_dump_json(),
                ungrounded_product_or_code=False,
                missing_calculation_output=draft.amount.calculated_by
                != "request-check/scripts/calculate_request.py",
                validation_not_passed=False,
                plan_not_ready=any(
                    step.status != PlanStatus.COMPLETED
                    for step in session.plan.steps
                    if step.step_type not in {"confirm_application", "present_draft"}
                ),
            )
            governance_span.set_attributes(
                {
                    "poc.policy.version": decision.policy_version,
                    "poc.policy.rule.id": decision.rule_id,
                    "poc.governance.stage": decision.stage,
                    "poc.governance.decision": decision.outcome.value,
                }
            )
        session.governance_decisions.append(decision)
        confirmation_step = next(
            step
            for step in session.plan.steps
            if step.step_type == "confirm_application"
        )
        await self._step(
            executor,
            confirmation_step.step_id,
            {"confirmation": True, "mode": confirmation_mode},
            lambda: (
                True,
                ["user.confirmation"],
                validation.evidence_refs,
                [],
            ),
        )
        presentation_step = next(
            step
            for step in session.plan.steps
            if step.step_type == "present_draft"
        )
        await self._step(
            executor,
            presentation_step.step_id,
            {"validation": validation.model_dump(mode="json")},
            lambda: (
                draft,
                ["response.validated_draft"],
                validation.evidence_refs,
                [],
            ),
        )
        with self.support.telemetry.span(
            "response.generate", {"poc.response.validated": True}
        ):
            status = self._status_summary(session, trace_id, resumed)
            response_text = json.dumps(
                {
                    "business_status": "SUCCESS",
                    "validated": True,
                    "confirmed": True,
                    "confirmation_mode": confirmation_mode,
                    "application_draft": draft.model_dump(mode="json"),
                    "observability": status,
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
        self.context.after_invocation(session, response_text=response_text)
        return self._outcome(
            session,
            response_text,
            run_id,
            trace_id,
            resumed,
            validation=validation,
            active_span=root_span,
        )

    def _completed_plan_replay(
        self,
        *,
        session: AgentSession,
        user_text: str,
        run_id: str,
        trace_id: str,
        root_span: Any,
    ) -> HostedRunOutcome:
        draft = session.application_draft
        if draft is None:
            raise RuntimeError("completed plan has no ApplicationDraft")
        self.context.before_invocation(session, user_input=user_text, resumed=True)
        with self.support.telemetry.span(
            "governance.pre_output", {"poc.agent.role": self.role}
        ) as governance_span:
            decision = self.support.middleware.run_pre_output(
                role=self.role,
                plan_id=session.plan.plan_id,
                response_text=draft.model_dump_json(),
                ungrounded_product_or_code=False,
                missing_calculation_output=False,
                validation_not_passed=False,
                plan_not_ready=False,
            )
            governance_span.set_attributes(
                {
                    "poc.policy.version": decision.policy_version,
                    "poc.policy.rule.id": decision.rule_id,
                    "poc.governance.stage": decision.stage,
                    "poc.governance.decision": decision.outcome.value,
                }
            )
        session.governance_decisions.append(decision)
        with self.support.telemetry.span(
            "response.generate", {"poc.response.validated": True, "poc.response.replayed": True}
        ):
            response_text = json.dumps(
                {
                    "business_status": BusinessStatus.SUCCESS.value,
                    "validated": True,
                    "confirmed": True,
                    "application_draft": draft.model_dump(mode="json"),
                    "observability": self._status_summary(session, trace_id, True),
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
        self.context.after_invocation(session, response_text=response_text)
        return self._outcome(
            session,
            response_text,
            run_id,
            trace_id,
            True,
            validation=None,
            active_span=root_span,
        )

    def _waiting_user_response(self, session: AgentSession) -> str:
        natural_mode = session.governance_state.get("interaction_mode") == "natural"
        payload: dict[str, Any] = {
            "business_status": "WAITING_USER",
            "missing_required_fields": self._missing_required_fields(
                session.request, natural_mode
            ),
            "plan_id": session.plan.plan_id,
            "plan_version": session.plan.plan_version,
        }
        clarification = session.governance_state.get("pending_clarification")
        if clarification:
            payload["clarification"] = clarification
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)

    def _clarification_outcome(
        self,
        *,
        session: AgentSession,
        executor,
        failure: BusinessOperationFailed,
        run_id: str,
        trace_id: str,
        resumed: bool,
        root_span: Any,
    ) -> HostedRunOutcome:
        clarification = dict(failure.result.get("clarification", {}))
        required_refs = list(clarification.get("required_input_refs", []))
        if not required_refs:
            raise RuntimeError("clarification failure must declare required_input_refs")
        session.governance_state["pending_clarification"] = clarification
        session.governance_state.setdefault("clarification_changed_refs", [])
        executor.wait_for_user(
            failure.step_id,
            required_refs,
            evidence_refs=failure.evidence_refs,
            tool_call_ids=failure.tool_call_ids,
            reason="clarification required for: " + ", ".join(required_refs),
        )
        self.support.telemetry.add_event(
            root_span,
            "clarification_required",
            {
                "poc.plan.step.id": failure.step_id,
                "poc.clarification.option_count": len(
                    clarification.get("options", [])
                ),
                "poc.clarification.required_ref_count": len(required_refs),
            },
        )
        response_text = self._waiting_user_response(session)
        self.context.after_invocation(session, response_text=response_text)
        return self._outcome(
            session,
            response_text,
            run_id,
            trace_id,
            resumed,
            validation=None,
            active_span=root_span,
        )

    def _business_failure_outcome(
        self,
        *,
        session: AgentSession,
        executor,
        failure: BusinessOperationFailed,
        run_id: str,
        trace_id: str,
        resumed: bool,
        root_span: Any,
    ) -> HostedRunOutcome:
        executor.block(
            failure.step_id,
            f"{failure.tool_name} returned {failure.business_status.value}",
            evidence_refs=failure.evidence_refs,
            tool_call_ids=failure.tool_call_ids,
        )
        self.support.telemetry.add_event(
            root_span,
            "business_operation_failed",
            {
                "poc.plan.step.id": failure.step_id,
                "poc.tool.name": failure.tool_name,
                "poc.business.status": failure.business_status.value,
            },
        )
        response = {
            "business_status": failure.business_status.value,
            "technical_status": "SUCCESS",
            "failed_tool": failure.tool_name,
            "warnings": failure.warnings,
            "evidence_refs": failure.evidence_refs,
        }
        if failure.delegation_tool_name:
            response["delegation_tool"] = failure.delegation_tool_name
        gate_input_text = json.dumps(
            response,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        with self.support.telemetry.span(
            "governance.pre_output", {"poc.agent.role": self.role}
        ) as governance_span:
            decision = self.support.middleware.run_pre_output(
                role=self.role,
                plan_id=session.plan.plan_id,
                response_text=gate_input_text,
                ungrounded_product_or_code=False,
                missing_calculation_output=False,
                validation_not_passed=False,
                plan_not_ready=False,
            )
            governance_span.set_attributes(
                {
                    "poc.policy.version": decision.policy_version,
                    "poc.policy.rule.id": decision.rule_id,
                    "poc.governance.stage": decision.stage,
                    "poc.governance.decision": decision.outcome.value,
                }
            )
        session.governance_decisions.append(decision)
        response["observability"] = self._status_summary(
            session, trace_id, resumed
        )
        response_text = json.dumps(
            response,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        with self.support.telemetry.span(
            "response.generate", {"poc.response.validated": False}
        ):
            pass
        self.context.after_invocation(session, response_text=response_text)
        return self._outcome(
            session,
            response_text,
            run_id,
            trace_id,
            resumed,
            validation=None,
            active_span=root_span,
        )

    def _validation_failure_outcome(
        self,
        *,
        session: AgentSession,
        executor,
        validation: ValidationResult,
        run_id: str,
        trace_id: str,
        resumed: bool,
        root_span: Any,
    ) -> HostedRunOutcome:
        reason = (
            "deterministic validation failed "
            f"({len(validation.violations)} violation(s))"
        )
        executor.block(session.plan.steps[-1].step_id, reason)
        self.support.telemetry.add_event(
            root_span,
            "validation_failed",
            {
                "poc.plan.step.id": session.plan.steps[-1].step_id,
                "poc.validation.violation_count": len(validation.violations),
            },
        )
        response = {
            "business_status": BusinessStatus.VALIDATION_FAILED.value,
            "validated": False,
            "violations": validation.violations,
        }
        gate_input_text = json.dumps(
            response,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        with self.support.telemetry.span(
            "governance.pre_output", {"poc.agent.role": self.role}
        ) as governance_span:
            decision = self.support.middleware.run_pre_output(
                role=self.role,
                plan_id=session.plan.plan_id,
                response_text=gate_input_text,
                ungrounded_product_or_code=False,
                missing_calculation_output=False,
                validation_not_passed=False,
                plan_not_ready=False,
            )
            governance_span.set_attributes(
                {
                    "poc.policy.version": decision.policy_version,
                    "poc.policy.rule.id": decision.rule_id,
                    "poc.governance.stage": decision.stage,
                    "poc.governance.decision": decision.outcome.value,
                }
            )
        session.governance_decisions.append(decision)
        response["observability"] = self._status_summary(
            session, trace_id, resumed
        )
        response_text = json.dumps(
            response,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        with self.support.telemetry.span(
            "response.generate", {"poc.response.validated": False}
        ):
            pass
        self.context.after_invocation(session, response_text=response_text)
        return self._outcome(
            session,
            response_text,
            run_id,
            trace_id,
            resumed,
            validation=validation,
            active_span=root_span,
        )

    async def _run_single(self, session, executor, request) -> ValidationResult:
        decisions = session.governance_decisions
        existing_draft = session.application_draft

        def governed(step, name, arguments, operation, *, require_success=True):
            response = self.support.call_tool(
                role=AgentRole.PROCUREMENT_ASSISTANT,
                tool_name=name,
                plan_id=session.plan.plan_id,
                step_id=step,
                arguments=arguments,
                operation=operation,
                decisions=decisions,
            )
            return self._success(response, name, step) if require_success else response

        item_step = next(step for step in session.plan.steps if step.step_id == "S04")
        if item_step.status == PlanStatus.COMPLETED and session.selected_item:
            item = session.selected_item
            item_evidence = list(item_step.evidence_refs)
        else:
            def search_and_select():
                search = governed(
                    "S03",
                    "search_catalog",
                    {"query": request.query},
                    lambda: self.support.adapter.search_catalog(request.query),
                )
                candidate = _select_catalog_candidate(
                    search,
                    request.constraints.specifications,
                    step_id="S03",
                )
                return (
                    candidate,
                    ["search.candidates"],
                    search.evidence_refs,
                    [search.call_id],
                )

            candidate = await self._step(
                executor,
                "S03",
                {
                    "query": request.query,
                    "specifications": request.constraints.specifications,
                },
                search_and_select,
            )
            product_code = candidate["item"]["product_code"]
            item_response = await self._step(
                executor,
                "S04",
                {"product_code": product_code},
                lambda: self._step_tool_result(
                    governed("S04", "get_catalog_item", {"product_code": product_code}, lambda: self.support.adapter.get_catalog_item(product_code)),
                    "item",
                ),
            )
            item = CatalogItem.model_validate(item_response.result["item"])
            session.selected_item = item
            item_evidence = list(item_response.evidence_refs)
        applicant_step = next(
            step for step in session.plan.steps if step.step_id == "S05"
        )
        if applicant_step.status == PlanStatus.COMPLETED and session.applicant:
            applicant = session.applicant
            applicant_evidence = list(applicant_step.evidence_refs)
        else:
            applicant_response = await self._step(
                executor,
                "S05",
                {"applicant_name": request.applicant_name},
                lambda: self._step_tool_result(
                    governed("S05", "get_applicant", {"identifier": request.applicant_name}, lambda: self.support.adapter.get_applicant(request.applicant_name or "")),
                    "applicant",
                ),
            )
            applicant = Applicant.model_validate(
                applicant_response.result["applicant"]
            )
            session.applicant = applicant
            applicant_evidence = list(applicant_response.evidence_refs)

        department_step = next(
            step for step in session.plan.steps if step.step_id == "S06"
        )
        if department_step.status == PlanStatus.COMPLETED and existing_draft:
            department_code = existing_draft.applicant.department_code
            department_evidence = list(department_step.evidence_refs)
        else:
            def resolve_department():
                department_response = governed(
                    "S06",
                    "lookup_department",
                    {"identifier": applicant.department_code},
                    lambda: self.support.adapter.lookup_department(
                        applicant.department_code
                    ),
                )
                responses = [department_response]
                if request.department_name:
                    requested_department_response = governed(
                        "S06",
                        "lookup_department",
                        {"identifier": request.department_name},
                        lambda: self.support.adapter.lookup_department(
                            request.department_name or ""
                        ),
                    )
                    responses.append(requested_department_response)
                    department = Department.model_validate(
                        department_response.result["department"]
                    )
                    requested_department = Department.model_validate(
                        requested_department_response.result["department"]
                    )
                    if requested_department.department_code != department.department_code:
                        raise BusinessOperationFailed(
                            tool_name="lookup_department",
                            step_id="S06",
                            business_status=BusinessStatus.VALIDATION_FAILED,
                            evidence_refs=list(
                                dict.fromkeys(
                                    ref
                                    for response in responses
                                    for ref in response.evidence_refs
                                )
                            ),
                            warnings=[
                                "request.department_name does not match applicant department"
                            ],
                            tool_call_ids=[response.call_id for response in responses],
                        )
                return (
                    department_response,
                    ["department"],
                    list(
                        dict.fromkeys(
                            ref for response in responses for ref in response.evidence_refs
                        )
                    ),
                    [response.call_id for response in responses],
                )

            department_response = await self._step(
                executor,
                "S06",
                {
                    "department_code": applicant.department_code,
                    "requested_department": request.department_name,
                },
                resolve_department,
            )
            department = Department.model_validate(
                department_response.result["department"]
            )
            department_code = department.department_code
            department_evidence = list(department_response.evidence_refs)

        account_step = next(
            step for step in session.plan.steps if step.step_id == "S07"
        )
        if account_step.status == PlanStatus.COMPLETED and existing_draft:
            draft_account = existing_draft.account
            account_evidence = list(account_step.evidence_refs)
        else:
            account_response = await self._step(
                executor,
                "S07",
                {"category": item.category, "purpose": request.purpose},
                lambda: self._step_tool_result(
                    governed("S07", "lookup_account_code", {"category": item.category, "purpose": request.purpose}, lambda: self.support.adapter.lookup_account_code(item.category, request.purpose or "")),
                    "account",
                ),
            )
            account = AccountCode.model_validate(account_response.result["account_code"])
            draft_account = DraftAccount(
                account_code=account.account_code, label=account.label
            )
            account_evidence = list(account_response.evidence_refs)

        delivery_step = next(
            step for step in session.plan.steps if step.step_id == "S08"
        )
        if delivery_step.status == PlanStatus.COMPLETED and existing_draft:
            delivery = existing_draft.delivery
            delivery_evidence = list(delivery_step.evidence_refs)
        else:
            delivery_response = await self._step(
                executor,
                "S08",
                {"product_code": item.product_code, "quantity": request.quantity, "requested_by": request.constraints.requested_by},
                lambda: self._step_tool_result(
                    governed("S08", "estimate_delivery", {"product_code": item.product_code, "quantity": request.quantity, "requested_by": request.constraints.requested_by}, lambda: self.support.adapter.estimate_delivery(item.product_code, request.quantity or 0, request.constraints.requested_by)),
                    "delivery",
                ),
            )
            delivery = DeliveryEstimate.model_validate(delivery_response.result["delivery"])
            delivery_evidence = list(delivery_response.evidence_refs)

        calculation_step = next(
            step for step in session.plan.steps if step.step_id == "S09"
        )
        if calculation_step.status == PlanStatus.COMPLETED and existing_draft:
            calculation = existing_draft.amount
            calculation_evidence = list(calculation_step.evidence_refs)
        else:
            calculation_response = await self._step(
                executor,
                "S09",
                {"quantity": request.quantity, "unit_price": str(item.unit_price)},
                lambda: self._step_tool_result(
                    governed("S09", "calculate_request", {"quantity": request.quantity, "unit_price": str(item.unit_price)}, lambda: self.support.calculate_with_skill(request.quantity or 0, str(item.unit_price))),
                    "calculation",
                ),
            )
            calculation = CalculationResult.model_validate(calculation_response.result["calculation"])
            calculation_evidence = list(calculation_response.evidence_refs)
        evidence = list(
            dict.fromkeys(
                item_evidence
                + applicant_evidence
                + department_evidence
                + account_evidence
                + delivery_evidence
                + calculation_evidence
            )
        )
        draft = ApplicationDraft(
            request_id=request.request_id,
            item=DraftItem(
                product_code=item.product_code,
                name=item.name,
                quantity=request.quantity or 0,
                unit_price=item.unit_price,
                currency=item.currency,
                specifications=item.specifications,
            ),
            amount=calculation,
            delivery=delivery,
            applicant=DraftApplicant(employee_id=applicant.employee_id, name=applicant.name, department_code=department_code),
            account=draft_account,
            request_constraints=request.constraints,
            evidence_refs=evidence,
            warnings=delivery.warnings,
        )
        session.application_draft = await self._step(
            executor,
            "S10",
            {"evidence_refs": evidence},
            lambda: (draft, ["application_draft"], evidence, []),
        )
        validation_response = await self._step(
            executor,
            "S11",
            {"draft_hash": _hash_payload(draft.model_dump(mode="json"))},
            lambda: self._step_tool_result(
                governed(
                    "S11",
                    "validate_application",
                    {"draft_hash": _hash_payload(draft.model_dump(mode="json"))},
                    lambda: self.support.validate_with_skill(draft),
                    require_success=False,
                ),
                "validation",
            ),
        )
        validation = ValidationResult.model_validate(validation_response.result["validation"])
        self.support.ledger.validations.append(validation.model_dump(mode="json"))
        return validation

    async def _run_multi(self, session, executor, request) -> ValidationResult:
        if not self.bundle.procurement_tool or not self.bundle.drafting_tool:
            raise RuntimeError("HA-M requires both specialist Agent Tools")
        procurement_step = next(
            step for step in session.plan.steps if step.step_id == "S03"
        )
        merge_step = next(
            step for step in session.plan.steps if step.step_id == "S04"
        )
        cached_snapshot = session.procurement_context_snapshot
        reuse_procurement = (
            procurement_step.status == PlanStatus.COMPLETED
            and merge_step.status == PlanStatus.COMPLETED
            and cached_snapshot is not None
            and cached_snapshot.selected_item is not None
            and cached_snapshot.applicant is not None
            and cached_snapshot.department is not None
            and cached_snapshot.account_code is not None
            and cached_snapshot.delivery_estimate is not None
        )
        if reuse_procurement:
            enriched_snapshot = cached_snapshot.model_copy(
                update={
                    "request": request,
                    "plan_version": session.plan.plan_version,
                }
            )
        else:
            initial_snapshot = ProcurementContextSnapshot(
                request=request,
                plan_id=session.plan.plan_id,
                plan_version=session.plan.plan_version,
            )
            procurement_task = AgentToolTask(
                task_id=f"task-{uuid4()}",
                plan_id=session.plan.plan_id,
                step_ids=["S03"],
                context_snapshot=initial_snapshot,
                required_outputs=[
                    "item",
                    "applicant",
                    "department",
                    "account_code",
                    "delivery_estimate",
                ],
            )
            procurement_result = await self._step(
                executor,
                "S03",
                procurement_task.model_dump(mode="json"),
                lambda: self._agent_tool_step(
                    self.bundle.procurement_tool,
                    "agent_as_tool.procurement_specialist",
                    procurement_task,
                    session,
                    "S03",
                ),
            )
            item = CatalogItem.model_validate(procurement_result.result["item"])
            applicant = Applicant.model_validate(
                procurement_result.result["applicant"]
            )
            department = Department.model_validate(
                procurement_result.result["department"]
            )
            account = AccountCode.model_validate(
                procurement_result.result["account_code"]
            )
            delivery = DeliveryEstimate.model_validate(
                procurement_result.result["delivery_estimate"]
            )
            session.selected_item = item
            session.applicant = applicant
            await self._step(
                executor,
                "S04",
                {"task_id": procurement_result.task_id},
                lambda: (
                    True,
                    ["procurement_result", "context_snapshot.procurement"],
                    procurement_result.evidence_refs,
                    [],
                ),
            )
            enriched_snapshot = ProcurementContextSnapshot(
                request=request,
                plan_id=session.plan.plan_id,
                plan_version=session.plan.plan_version,
                selected_item=item,
                applicant=applicant,
                department=department,
                account_code=account,
                delivery_estimate=delivery,
                evidence_refs=procurement_result.evidence_refs,
            )
        session.procurement_context_snapshot = enriched_snapshot
        drafting_task = AgentToolTask(
            task_id=f"task-{uuid4()}",
            plan_id=session.plan.plan_id,
            step_ids=["S05"],
            context_snapshot=enriched_snapshot,
            required_outputs=["application_draft", "calculation"],
        )
        drafting_result = await self._step(
            executor,
            "S05",
            drafting_task.model_dump(mode="json"),
            lambda: self._agent_tool_step(
                self.bundle.drafting_tool,
                "agent_as_tool.drafting_specialist",
                drafting_task,
                session,
                "S05",
            ),
        )
        draft = ApplicationDraft.model_validate(drafting_result.result["application_draft"])
        session.application_draft = draft
        await self._step(
            executor,
            "S06",
            {"task_id": drafting_result.task_id},
            lambda: (draft, ["application_draft", "calculation"], drafting_result.evidence_refs, []),
        )
        validation_response = await self._step(
            executor,
            "S07",
            {"draft_hash": _hash_payload(draft.model_dump(mode="json"))},
            lambda: self._step_tool_result(
                self.support.call_tool(
                    role=AgentRole.COORDINATOR,
                    tool_name="validate_application",
                    plan_id=session.plan.plan_id,
                    step_id="S07",
                    arguments={
                        "draft_hash": _hash_payload(draft.model_dump(mode="json"))
                    },
                    operation=lambda: self.support.validate_with_skill(draft),
                    decisions=session.governance_decisions,
                ),
                "validation",
            ),
        )
        validation = ValidationResult.model_validate(validation_response.result["validation"])
        self.support.ledger.validations.append(validation.model_dump(mode="json"))
        return validation

    async def _agent_tool_step(self, tool, span_name, task, session, step_id):
        result = await self._governed_agent_tool(
            tool=tool,
            role_span=span_name,
            task=task,
            coordinator_session=session,
            step_id=step_id,
        )
        tool_ids = list(result.result.pop("tool_call_ids", []))
        if result.business_status != BusinessStatus.SUCCESS:
            raise BusinessOperationFailed(
                tool_name=str(result.result.get("failed_tool") or tool.name),
                step_id=step_id,
                business_status=result.business_status,
                evidence_refs=result.evidence_refs,
                warnings=result.warnings,
                tool_call_ids=tool_ids,
                delegation_tool_name=tool.name,
                result=result.result,
            )
        output_ref = {
            AgentRole.PROCUREMENT_SPECIALIST: "procurement_result",
            AgentRole.DRAFTING_SPECIALIST: "drafting_result",
        }.get(result.agent_role, f"agent_tool_result.{result.agent_role.value}")
        return result, [output_ref], result.evidence_refs, tool_ids

    @staticmethod
    def _step_tool_result(response: ToolResponse, output_ref: str):
        return response, [output_ref], response.evidence_refs, [response.call_id]

    def _status_summary(self, session: AgentSession, trace_id: str, resumed: bool) -> dict[str, Any]:
        next_step = session.plan_executor().next_step() if session.plan else None
        if next_step is None and session.plan:
            next_step = next(
                (
                    step
                    for step in session.plan.steps
                    if step.status == PlanStatus.WAITING_USER
                ),
                None,
            )
        invocation_decisions = session.governance_decisions[
            self.support.ledger.governance_decision_offset :
        ]
        return {
            "logical_pattern": self.bundle.pattern.value,
            "plan_id": session.active_plan_id,
            "plan_version": session.plan.plan_version if session.plan else None,
            "plan_status": session.plan.status.value if session.plan else None,
            "current_step": next_step.step_id if next_step else None,
            "completed_steps": [
                step.step_id for step in (session.plan.steps if session.plan else []) if step.status == PlanStatus.COMPLETED
            ],
            "delegations": [item["agent_role"] for item in self.support.ledger.delegations],
            "governance_decisions": [
                item.outcome.value for item in invocation_decisions
            ],
            "trace_id": trace_id,
            "warnings": list(session.plan.warnings if session.plan else []),
            "session_resumed": resumed,
        }

    def _outcome(
        self,
        session: AgentSession,
        response_text: str,
        run_id: str,
        trace_id: str,
        resumed: bool,
        validation: ValidationResult | None,
        active_span: Any | None = None,
    ) -> HostedRunOutcome:
        role = self.role
        current_user_input = next(
            (
                message.content
                for message in reversed(session.conversation)
                if message.role == "user"
            ),
            "",
        )
        protected_user = self.support.telemetry.protect_content(
            "user_input", current_user_input
        )
        protected_response = self.support.telemetry.protect_content("response", response_text)
        try:
            response_business_status = json.loads(response_text).get(
                "business_status", session.plan.status.value
            )
        except (TypeError, ValueError):
            response_business_status = session.plan.status.value
        run = RunIdentity(
            run_id=run_id,
            case_id="healthy-local",
            logical_pattern=self.bundle.pattern.value,
            agent_role=role.value,
            agent_definition_id=f"local:{self.bundle.pattern.value}:{role.value}:0.1.0",
            foundry_resource_id=None,
            implementation_kind=(
                ImplementationKind.IN_PROCESS_AGENT_AS_TOOL.value
                if self.bundle.pattern == LogicalPattern.HOSTED_MULTI
                else ImplementationKind.LOCAL_DETERMINISTIC.value
            ),
        )
        envelope = build_envelope(
            run=run,
            session=session,
            telemetry=self.support.telemetry,
            user_input=[{"role": "user", "turn_index": session.turn_index, **protected_user}],
            response={
                "technical_status": "SUCCESS",
                "business_status": response_business_status,
                **protected_response,
            },
            retrieved_contexts=self.support.ledger.retrieved_contexts
            or [{"evidence_ref": "none-yet"}],
            system_prompt={
                "version": "0.1.0",
                "role": role.value,
                **self.support.telemetry.protect_content(
                    "system_prompt", self.bundle.coordinator.default_options.get("instructions", "")
                ),
            },
            tool_definitions=[
                {
                    "name": item.name,
                    "description": item.description,
                    "schema_version": "1.0",
                    **self.support.telemetry.protect_content(
                        "tool_definition", item.parameters()
                    ),
                }
                for item in self.bundle.coordinator.default_options.get("tools", [])
            ],
            tool_calls=self.support.ledger.tool_calls or [{"status": "not-executed"}],
            tool_output=self.support.ledger.tool_outputs or [{"status": "not-executed"}],
            delegations=self.support.ledger.delegations,
            governance_decisions=session.governance_decisions[
                self.support.ledger.governance_decision_offset :
            ],
            validations=[validation.model_dump(mode="json")] if validation else [],
            resumed=resumed,
            trace_id=trace_id,
            active_spans=[active_span] if active_span is not None else None,
        )
        status = self._status_summary(session, trace_id, resumed)
        return HostedRunOutcome(
            response_text=response_text,
            session=session,
            envelope=envelope,
            status_summary=status,
            trace_id=trace_id,
            resumed=resumed,
        )
