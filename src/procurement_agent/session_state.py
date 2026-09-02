"""Thin validated access to procurement state in Agent Framework sessions."""

from __future__ import annotations

from typing import Any, Literal

from agent_framework import AgentSession, FunctionInvocationContext
from pydantic import Field, ValidationError

from .models import ARCHITECTURE_ID, ApplicationDraft, CatalogSearchResult, CodeDeterminationResult, CorrelationContext, ExecutionPlan, GovernanceDecision, ProcurementRequest, StrictModel


EXECUTION_STATE_KEY = "procurement.execution.v2"


class SessionStateError(RuntimeError):
    pass


class SessionRequiredError(SessionStateError):
    pass


class SessionStateMissingError(SessionStateError):
    pass


class SessionStateSchemaError(SessionStateError):
    pass


class ProcurementExecutionState(StrictModel):
    schema_version: Literal["2.0"] = "2.0"
    architecture_id: Literal["procurement_application_v2"] = ARCHITECTURE_ID
    turn_number: int = Field(default=0, ge=0)
    test_case_id: str = "unassigned"
    request: ProcurementRequest | None = None
    plan: ExecutionPlan | None = None
    current_step_id: str | None = None
    catalog_result: CatalogSearchResult | None = None
    code_result: CodeDeterminationResult | None = None
    draft: ApplicationDraft | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    child_correlations: list[CorrelationContext] = Field(default_factory=list)
    completed_step_keys: list[str] = Field(default_factory=list)
    governance_decisions: list[GovernanceDecision] = Field(default_factory=list)
    last_machine_response: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)


def save_execution_state(session: AgentSession, state: ProcurementExecutionState) -> None:
    session.state[EXECUTION_STATE_KEY] = state.model_dump(mode="json")


def initialize_execution_state(session: AgentSession, *, test_case_id: str = "unassigned") -> ProcurementExecutionState:
    state = ProcurementExecutionState(test_case_id=test_case_id)
    save_execution_state(session, state)
    return state


def load_execution_state(session: AgentSession | None, *, required: bool = True) -> ProcurementExecutionState | None:
    if session is None:
        raise SessionRequiredError("FunctionInvocationContext.session is required")
    raw = session.state.get(EXECUTION_STATE_KEY)
    if raw is None:
        if required:
            raise SessionStateMissingError(f"missing {EXECUTION_STATE_KEY}")
        return None
    try:
        return ProcurementExecutionState.model_validate(raw)
    except ValidationError as exc:
        raise SessionStateSchemaError(f"invalid {EXECUTION_STATE_KEY}: {exc.error_count()} errors") from exc


def load_context_state(context: FunctionInvocationContext) -> ProcurementExecutionState:
    state = load_execution_state(context.session, required=True)
    assert state is not None
    return state


def restore_framework_session(payload: dict[str, Any]) -> AgentSession:
    session = AgentSession.from_dict(payload)
    load_execution_state(session, required=True)
    return session
