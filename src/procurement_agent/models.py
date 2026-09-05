"""Observable procurement domain contracts for the revised architecture.

The models contain only user-visible or operational state. Hidden reasoning and
chain-of-thought are intentionally not represented.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ARCHITECTURE_ID = "procurement_application_v2"


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


class StepType(StrEnum):
    CATALOG_SEARCH = "catalog_search"
    CODE_DETERMINATION = "code_determination"
    MERGE_VALIDATE = "merge_validate"


class AgentRole(StrEnum):
    COORDINATOR = "coordinator"
    CATALOG_SEARCH = "catalog_search"
    CODE_DETERMINATION = "code_determination"


class ImplementationKind(StrEnum):
    HOSTED_FRAMEWORK = "hosted_framework"
    PROMPT_MANAGED = "prompt_managed"
    FOUNDRY_AGENT_AS_TOOL_REMOTE_PROXY = "foundry_agent_as_tool_remote_proxy"
    LOCAL_RECORDED_MCP_FIXTURE = "local_recorded_mcp_fixture"


class PlanGenerationSource(StrEnum):
    MODEL_STRUCTURED = "MODEL_STRUCTURED"
    DETERMINISTIC_DEFAULT = "DETERMINISTIC_DEFAULT"
    EMPTY_RESPONSE_FALLBACK = "EMPTY_RESPONSE_FALLBACK"
    PARSE_FAILURE_FALLBACK = "PARSE_FAILURE_FALLBACK"
    REQUIRED_STEP_FALLBACK = "REQUIRED_STEP_FALLBACK"


class TechnicalStatus(StrEnum):
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"


class BusinessStatus(StrEnum):
    SUCCESS = "SUCCESS"
    WAITING_USER = "WAITING_USER"
    NOT_FOUND = "NOT_FOUND"
    INVALID_INPUT = "INVALID_INPUT"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    BLOCKED = "BLOCKED"


class McpStatus(StrEnum):
    NOT_RUN = "NOT_RUN"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"
    PROTOCOL_ERROR = "PROTOCOL_ERROR"


class SearchStatus(StrEnum):
    NOT_RUN = "NOT_RUN"
    SUCCESS = "SUCCESS"
    NOT_FOUND = "NOT_FOUND"
    INDEX_MISSING = "INDEX_MISSING"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    ERROR = "ERROR"


class ParseStatus(StrEnum):
    NOT_RUN = "NOT_RUN"
    SUCCESS = "SUCCESS"
    INVALID_JSON = "INVALID_JSON"
    SCHEMA_INVALID = "SCHEMA_INVALID"


class FailureLayer(StrEnum):
    NONE = "NONE"
    MCP = "MCP"
    SEARCH = "SEARCH"
    PARSE = "PARSE"
    VALIDATION = "VALIDATION"


class FailureProfile(StrEnum):
    NORMAL = "normal"
    NOT_FOUND = "not_found"
    INDEX_MISSING = "index_missing"
    PERMISSION = "permission"
    BUSINESS_INVALID = "business_invalid"
    TIMEOUT = "timeout"
    PROTOCOL_INVALID = "protocol_invalid"


class GovernanceMode(StrEnum):
    SHADOW = "shadow"
    ENFORCE = "enforce"


class GovernanceOutcome(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    WOULD_DENY = "WOULD_DENY"


class RequestConstraints(StrictModel):
    budget_limit: Decimal | None = Field(default=None, ge=0)
    specifications: dict[str, str] = Field(default_factory=dict)


class ProcurementRequest(StrictModel):
    request_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    applicant_name: str = Field(min_length=1)
    department_name: str = Field(min_length=1)
    memo: str = Field(min_length=1)
    constraints: RequestConstraints = Field(default_factory=RequestConstraints)


class PlanStep(StrictModel):
    step_id: str = Field(min_length=1)
    step_type: StepType
    owner: AgentRole
    status: PlanStatus = PlanStatus.PENDING
    attempt: int = Field(default=0, ge=0)
    input_refs: list[str] = Field(default_factory=list)
    output_refs: list[str] = Field(default_factory=list)
    input_hash: str | None = None
    completion_reason: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None


class ExecutionPlan(StrictModel):
    """Pydantic response format and runtime plan for the parent planner."""

    plan_id: str = ""
    version: int = Field(default=1, ge=1)
    steps: list[PlanStep] = Field(default_factory=list)
    completion_condition: Literal["validated_application_ready"] = "validated_application_ready"
    status: PlanStatus = PlanStatus.PENDING
    generation_source: PlanGenerationSource = PlanGenerationSource.DETERMINISTIC_DEFAULT
    fallback_reason: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("steps")
    @classmethod
    def unique_step_ids(cls, steps: list[PlanStep]) -> list[PlanStep]:
        ids = [step.step_id for step in steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step_id must be unique")
        return steps


class ProcurementIntakeRequest(StrictModel):
    """User-supplied fields only; missing information is a normal conversation state."""
    query: str | None = Field(default=None, min_length=1)
    quantity: int | None = Field(default=None, gt=0)
    department_name: str | None = Field(default=None, min_length=1)
    memo: str | None = Field(default=None, min_length=1)
    constraints: RequestConstraints = Field(default_factory=RequestConstraints)


class ProcurementIntake(StrictModel):
    request: ProcurementIntakeRequest
    plan: ExecutionPlan
    selected_product_code: str | None = None


class OperationStatus(StrictModel):
    http_status: int = Field(default=200, ge=100, le=599)
    technical_status: TechnicalStatus = TechnicalStatus.SUCCESS
    mcp_status: McpStatus = McpStatus.NOT_RUN
    search_status: SearchStatus = SearchStatus.NOT_RUN
    parse_status: ParseStatus = ParseStatus.NOT_RUN
    business_status: BusinessStatus
    failure_layer: FailureLayer = FailureLayer.NONE
    retryable: bool = False
    reason_code: str | None = None


class CorrelationContext(StrictModel):
    test_case_id: str = Field(min_length=1)
    framework_session_id: str = Field(min_length=1)
    turn_number: int = Field(ge=1)
    plan_id: str = Field(min_length=1)
    plan_version: int = Field(ge=1)
    step_id: str = Field(min_length=1)
    attempt: int = Field(ge=1)
    remote_task_id: str = Field(min_length=1)
    parent_invocation_id: str = Field(min_length=1)


class Evidence(StrictModel):
    evidence_id: str
    index_name: Literal["procurement-catalog-v1", "procurement-code-master-v1"]
    document_id: str
    source_version: str
    record_type: Literal["product", "account_code", "department"]
    record_key: str = Field(min_length=1)
    rank: int | None = Field(default=None, ge=1)
    score: float | None = None
    content_ref: str | None = None
    catalog_product_name: str | None = None
    catalog_category: str | None = None
    catalog_unit_price: Decimal | None = Field(default=None, ge=0)
    catalog_currency: Literal["JPY"] | None = None
    catalog_specifications: dict[str, str] | None = None


class CatalogCandidate(StrictModel):
    product_code: str
    product_name: str
    category: str
    unit_price: Decimal = Field(ge=0)
    currency: Literal["JPY"] = "JPY"
    specifications: dict[str, str] = Field(default_factory=dict)
    evidence_id: str


class CatalogSearchInput(StrictModel):
    query: str = Field(min_length=1)
    quantity: int | None = Field(default=None, gt=0)  # None means discovery, never an assumed order quantity.
    constraints: RequestConstraints
    correlation: CorrelationContext


class CatalogSearchResult(StrictModel):
    correlation: CorrelationContext
    status: OperationStatus
    candidates: list[CatalogCandidate] = Field(default_factory=list)
    selected_product_code: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def grounded_selection(self) -> "CatalogSearchResult":
        if self.selected_product_code:
            selected = next(
                (item for item in self.candidates if item.product_code == self.selected_product_code),
                None,
            )
            if selected is None:
                raise ValueError("selected_product_code must exist in candidates")
            evidence = next((item for item in self.evidence if (
                item.evidence_id == selected.evidence_id
                and item.index_name == "procurement-catalog-v1"
                and item.record_type == "product"
                and item.record_key == selected.product_code
            )), None)
            if evidence is None:
                raise ValueError("selected catalog candidate must have matching product evidence")
            if (
                evidence.catalog_product_name != selected.product_name
                or evidence.catalog_category != selected.category
                or evidence.catalog_unit_price != selected.unit_price
                or evidence.catalog_currency != selected.currency
                or evidence.catalog_specifications != selected.specifications
            ):
                raise ValueError("selected catalog values must match the product evidence snapshot")
        return self


class CodeDeterminationInput(StrictModel):
    selected_product_code: str = Field(min_length=1)
    product_category: str = Field(min_length=1)
    department_name: str = Field(min_length=1)
    correlation: CorrelationContext


class CodeDeterminationResult(StrictModel):
    correlation: CorrelationContext
    status: OperationStatus
    account_code: str | None = None
    account_name: str | None = None
    department_code: str | None = None
    department_name: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def grounded_codes(self) -> "CodeDeterminationResult":
        if self.status.business_status == BusinessStatus.SUCCESS:
            if not all((self.account_code, self.account_name, self.department_code, self.department_name)):
                raise ValueError("successful code result requires account and department values")
            account_grounded = any(
                item.index_name == "procurement-code-master-v1"
                and item.record_type == "account_code"
                and item.record_key == self.account_code
                for item in self.evidence
            )
            department_grounded = any(
                item.index_name == "procurement-code-master-v1"
                and item.record_type == "department"
                and item.record_key == self.department_code
                for item in self.evidence
            )
            if not account_grounded or not department_grounded:
                raise ValueError("successful code result requires matching account and department evidence")
        return self


class ApplicationLine(StrictModel):
    product_code: str
    product_name: str
    category: str
    quantity: int = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    currency: Literal["JPY"] = "JPY"
    subtotal: Decimal = Field(ge=0)
    account_code: str
    account_name: str


class ApplicationDraft(StrictModel):
    request_id: str
    status: Literal["VALIDATED"] = "VALIDATED"
    lines: list[ApplicationLine] = Field(min_length=1)
    department_code: str
    department_name: str
    memo: str
    total: Decimal = Field(ge=0)
    evidence_refs: list[str] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class ConfirmationPreview(StrictModel):
    applicant_authenticated: Literal[True] = True
    applicant_name: str = Field(min_length=1, max_length=120)
    product_code: str
    product_name: str
    category: str
    specifications: dict[str, str] = Field(default_factory=dict)
    unit_price: Decimal = Field(ge=0)
    currency: Literal["JPY"] = "JPY"
    quantity: int = Field(gt=0)
    subtotal: Decimal = Field(ge=0)
    department_code: str
    department_name: str
    account_code: str
    account_name: str
    memo: str


class GovernanceDecision(StrictModel):
    policy_version: str
    stage: Literal["pre_input", "pre_tool", "post_tool", "pre_output"]
    outcome: GovernanceOutcome
    reason: str
    agent_role: AgentRole
    tool_name: str | None = None
    plan_id: str | None = None
    step_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class ScenarioResult(StrictModel):
    scenario_id: Literal["S1", "S2", "S3", "S4", "S5", "CHAT", "IDENTITY"]
    interaction_type: Literal["procurement", "general", "identity"] = "procurement"
    test_case_id: str
    technical_status: TechnicalStatus
    business_status: BusinessStatus
    draft: ApplicationDraft | None = None
    confirmation_preview: ConfirmationPreview | None = None
    status: OperationStatus | None = None
    trace: dict[str, Any] = Field(default_factory=dict)
    injection_requested: str | None = None
    injection_activated: bool = False
    next_action: str | None = None
    candidates: list[CatalogCandidate] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    progress: list[dict[str, str]] = Field(default_factory=list)
    response_text: str = ""
