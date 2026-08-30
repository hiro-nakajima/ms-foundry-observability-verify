"""Shared domain, plan, tool, session, governance, and trace schemas.

Only observable state is modeled here. The schemas intentionally contain no
chain-of-thought or hidden model reasoning fields.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class PlanStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_USER = "WAITING_USER"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    INVALIDATED = "INVALIDATED"


class BusinessStatus(StrEnum):
    SUCCESS = "SUCCESS"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    NOT_FOUND = "NOT_FOUND"
    INVALID_INPUT = "INVALID_INPUT"
    INSUFFICIENT_STOCK = "INSUFFICIENT_STOCK"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    BLOCKED = "BLOCKED"


class TechnicalStatus(StrEnum):
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"


class GovernanceMode(StrEnum):
    SHADOW = "shadow"
    ENFORCE = "enforce"


class GovernanceOutcome(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    WOULD_DENY = "WOULD_DENY"


class LogicalPattern(StrEnum):
    PROMPT_SINGLE = "PA-S"
    PROMPT_MULTI = "PA-M"
    HOSTED_SINGLE = "HA-S"
    HOSTED_MULTI = "HA-M"


class AgentRole(StrEnum):
    PROCUREMENT_ASSISTANT = "procurement_assistant"
    COORDINATOR = "coordinator"
    PROCUREMENT_SPECIALIST = "procurement_specialist"
    DRAFTING_SPECIALIST = "drafting_specialist"


class ImplementationKind(StrEnum):
    LOCAL_DETERMINISTIC = "local_deterministic"
    IN_PROCESS_AGENT_AS_TOOL = "in_process_agent_as_tool"
    REMOTE_AGENT_TOOL = "remote_agent_tool"
    A2A_AGENT_TOOL = "a2a_agent_tool"


class PlanGenerationSource(StrEnum):
    MODEL_STRUCTURED = "MODEL_STRUCTURED"
    DETERMINISTIC_DEFAULT = "DETERMINISTIC_DEFAULT"
    EMPTY_RESPONSE_FALLBACK = "EMPTY_RESPONSE_FALLBACK"


class RequestConstraints(StrictModel):
    requested_by: date | None = None
    budget_limit: Decimal | None = Field(default=None, ge=0)
    specifications: dict[str, str] = Field(default_factory=dict)


class ProcurementRequest(StrictModel):
    request_id: str
    query: str = Field(min_length=1)
    quantity: int | None = Field(default=None, gt=0)
    applicant_name: str | None = None
    department_name: str | None = None
    purpose: str | None = None
    constraints: RequestConstraints = Field(default_factory=RequestConstraints)

    def missing_required_fields(self) -> list[str]:
        missing: list[str] = []
        if self.quantity is None:
            missing.append("quantity")
        if not self.applicant_name:
            missing.append("applicant_name")
        if not self.purpose:
            missing.append("purpose")
        if self.constraints.requested_by is None:
            missing.append("constraints.requested_by")
        return missing


class PlanStepProposal(StrictModel):
    """Model-produced plan step. Runtime status is never accepted from the model."""

    step_id: str = Field(min_length=1)
    step_type: str = Field(min_length=1)
    owner: AgentRole
    input_refs: list[str] = Field(default_factory=list)


class AgentPlanResponse(StrictModel):
    """Pydantic response_format used only at the plan-generation boundary.

    Defaults make an empty structured response parseable. PlanBuilder then turns
    an empty step list into an explicit, traced deterministic fallback rather
    than accidentally reusing steps left in a previous session.
    """

    goal: str = ""
    steps: list[PlanStepProposal] = Field(default_factory=list)
    missing_required_fields: list[str] = Field(default_factory=list)


class PlanStep(StrictModel):
    step_id: str = Field(min_length=1)
    step_type: str = Field(min_length=1)
    owner: AgentRole
    status: PlanStatus = PlanStatus.PENDING
    input_refs: list[str] = Field(default_factory=list)
    output_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    tool_call_ids: list[str] = Field(default_factory=list)
    attempt: int = Field(default=0, ge=0)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    completion_reason: str | None = None
    input_hash: str | None = None

    @model_validator(mode="after")
    def validate_timestamps(self) -> "PlanStep":
        if self.status == PlanStatus.RUNNING and self.started_at is None:
            raise ValueError("RUNNING step requires started_at")
        if self.status in {PlanStatus.COMPLETED, PlanStatus.FAILED, PlanStatus.BLOCKED}:
            if self.ended_at is None or not self.completion_reason:
                raise ValueError(f"{self.status} step requires ended_at and completion_reason")
        return self


class ExecutionPlan(StrictModel):
    plan_id: str
    plan_version: int = Field(ge=1)
    goal: str = Field(min_length=1)
    status: PlanStatus = PlanStatus.PENDING
    steps: list[PlanStep]
    generation_source: PlanGenerationSource = PlanGenerationSource.DETERMINISTIC_DEFAULT
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("steps")
    @classmethod
    def unique_step_ids(cls, steps: list[PlanStep]) -> list[PlanStep]:
        ids = [step.step_id for step in steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step_id must be unique within a plan")
        return steps


class CatalogItem(StrictModel):
    product_code: str
    name: str
    category: str
    keywords: list[str]
    specifications: dict[str, str]
    unit_price: Decimal = Field(ge=0)
    currency: Literal["JPY"]
    stock: int = Field(ge=0)
    lead_time_days: int = Field(ge=0)
    valid_from: date
    valid_to: date


class AccountCode(StrictModel):
    account_code: str
    label: str
    categories: list[str]
    purposes: list[str]
    valid_from: date
    valid_to: date


class Department(StrictModel):
    department_code: str
    name: str
    valid_from: date
    valid_to: date


class Applicant(StrictModel):
    employee_id: str
    name: str
    department_code: str
    active: bool
    synthetic: Literal[True] = True


class DeliveryEstimate(StrictModel):
    product_code: str
    quantity: int = Field(gt=0)
    requested_by: date | None = None
    estimated_on: date
    meets_request: bool
    rule_id: str
    warnings: list[str] = Field(default_factory=list)


class CalculationResult(StrictModel):
    currency: Literal["JPY"] = "JPY"
    quantity: int = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    subtotal: Decimal = Field(ge=0)
    discount: Decimal = Field(ge=0)
    taxable_amount: Decimal = Field(ge=0)
    tax: Decimal = Field(ge=0)
    total: Decimal = Field(ge=0)
    tax_rate: Decimal = Field(ge=0)
    discount_rate: Decimal = Field(ge=0)
    rounding_mode: str
    calculated_by: str


class DraftItem(StrictModel):
    product_code: str
    name: str
    quantity: int = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    currency: Literal["JPY"]
    specifications: dict[str, str] = Field(default_factory=dict)


class DraftApplicant(StrictModel):
    employee_id: str
    name: str
    department_code: str


class DraftAccount(StrictModel):
    account_code: str
    label: str


class ApplicationDraft(StrictModel):
    request_id: str
    status: Literal["DRAFT_READY"] = "DRAFT_READY"
    item: DraftItem
    amount: CalculationResult
    delivery: DeliveryEstimate
    applicant: DraftApplicant
    account: DraftAccount
    request_constraints: RequestConstraints = Field(default_factory=RequestConstraints)
    evidence_refs: list[str] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class ValidationResult(StrictModel):
    valid: bool
    violations: list[str] = Field(default_factory=list)
    checks: dict[str, bool] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)


class ToolResponse(StrictModel):
    call_id: str
    http_status: int = Field(default=200, ge=100, le=599)
    technical_status: TechnicalStatus = TechnicalStatus.SUCCESS
    business_status: BusinessStatus
    data_version: str
    result: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ProcurementContextSnapshot(StrictModel):
    snapshot_version: str = "1.0"
    request: ProcurementRequest
    plan_id: str
    plan_version: int
    selected_item: CatalogItem | None = None
    applicant: Applicant | None = None
    department: Department | None = None
    account_code: AccountCode | None = None
    delivery_estimate: DeliveryEstimate | None = None
    calculation: CalculationResult | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class AgentToolTask(StrictModel):
    task_id: str
    plan_id: str
    step_ids: list[str]
    context_snapshot: ProcurementContextSnapshot
    required_outputs: list[str]


class AgentToolResult(StrictModel):
    task_id: str
    agent_role: AgentRole
    business_status: BusinessStatus
    result: dict[str, Any]
    evidence_refs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class GovernanceDecision(StrictModel):
    policy_version: str
    rule_id: str
    stage: Literal["pre_input", "pre_tool", "post_tool", "pre_output"]
    outcome: GovernanceOutcome
    reason: str
    agent_role: AgentRole
    tool_name: str | None = None
    plan_id: str | None = None
    step_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
