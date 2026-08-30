"""Application-owned session and invocation context provider."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field

from .models import (
    Applicant,
    ApplicationDraft,
    CatalogItem,
    ExecutionPlan,
    GovernanceDecision,
    ProcurementRequest,
    StrictModel,
)
from .plan import PlanExecutor


SESSION_SCHEMA_VERSION = "1.0"
AGENT_DEFINITION_VERSION = "0.1.0"


class SessionCompatibilityError(ValueError):
    pass


class ConversationMessage(StrictModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    turn_index: int = Field(ge=0)
    content_hash: str

    @classmethod
    def create(cls, role: Literal["system", "user", "assistant", "tool"], content: str, turn_index: int):
        return cls(
            role=role,
            content=content,
            turn_index=turn_index,
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )


class AgentSession(StrictModel):
    session_schema_version: str = SESSION_SCHEMA_VERSION
    agent_definition_version: str = AGENT_DEFINITION_VERSION
    session_id: str = Field(default_factory=lambda: f"session-{uuid4()}")
    conversation_id: str = Field(default_factory=lambda: f"conv-{uuid4()}")
    turn_index: int = Field(default=0, ge=0)
    active_plan_id: str | None = None
    plan: ExecutionPlan | None = None
    request: ProcurementRequest | None = None
    selected_item: CatalogItem | None = None
    applicant: Applicant | None = None
    evidence: dict[str, dict[str, Any]] = Field(default_factory=dict)
    application_draft: ApplicationDraft | None = None
    governance_state: dict[str, Any] = Field(default_factory=dict)
    governance_decisions: list[GovernanceDecision] = Field(default_factory=list)
    completed_step_keys: list[str] = Field(default_factory=list)
    conversation: list[ConversationMessage] = Field(default_factory=list)
    last_response_id: str | None = None
    resume_token: str = Field(default_factory=lambda: f"resume-{uuid4()}")

    def serialize(self) -> str:
        return self.model_dump_json(exclude_none=False)

    @classmethod
    def restore(cls, serialized: str) -> "AgentSession":
        session = cls.model_validate_json(serialized)
        if session.session_schema_version != SESSION_SCHEMA_VERSION:
            raise SessionCompatibilityError(
                f"session schema {session.session_schema_version} is not supported"
            )
        if session.agent_definition_version != AGENT_DEFINITION_VERSION:
            raise SessionCompatibilityError(
                f"agent definition {session.agent_definition_version} is not supported"
            )
        return session

    def add_message(self, role: Literal["system", "user", "assistant", "tool"], content: str) -> None:
        self.conversation.append(ConversationMessage.create(role, content, self.turn_index))

    def begin_turn(self, user_input: str) -> None:
        self.turn_index += 1
        self.add_message("user", user_input)

    def start_new_plan(self, request: ProcurementRequest, plan: ExecutionPlan) -> None:
        """Start a fresh plan and remove all plan-derived residual state.

        This is deliberately separate from resume. A new request must never
        inherit selected product, evidence, draft, or idempotency keys from an
        earlier completed plan in the same process.
        """

        self.request = request
        self.plan = plan
        self.active_plan_id = plan.plan_id
        self.selected_item = None
        self.applicant = None
        self.evidence = {}
        self.application_draft = None
        self.governance_state = {}
        self.governance_decisions = []
        self.completed_step_keys = []
        self.last_response_id = None
        self.resume_token = f"resume-{uuid4()}"

    def plan_executor(self) -> PlanExecutor:
        if self.plan is None:
            raise SessionCompatibilityError("session has no active plan")
        return PlanExecutor(self.plan, self.completed_step_keys)

    def apply_request_update(self, update: dict[str, Any]) -> set[str]:
        if self.request is None:
            raise SessionCompatibilityError("session has no request")
        current = self.request.model_dump(mode="python")
        changed_refs: set[str] = set()
        for key, value in update.items():
            if key == "constraints":
                nested = dict(current["constraints"])
                for nested_key, nested_value in value.items():
                    if nested.get(nested_key) != nested_value:
                        changed_refs.add(f"request.constraints.{nested_key}")
                    nested[nested_key] = nested_value
                current["constraints"] = nested
            else:
                if current.get(key) != value:
                    changed_refs.add(f"request.{key}")
                current[key] = value
        self.request = ProcurementRequest.model_validate(current)
        return changed_refs


class InvocationContext(StrictModel):
    session_id_hash: str
    conversation_id_hash: str
    turn_index: int
    user_input: str
    request: ProcurementRequest
    plan: ExecutionPlan
    next_step_id: str | None
    next_step_type: str | None
    selected_item: CatalogItem | None
    evidence: dict[str, dict[str, Any]]
    governance_state: dict[str, Any]
    resumed: bool


class InMemoryContextProvider:
    """Injects only explicit session state before each invocation.

    It is intentionally application-owned even when Agent Framework is used;
    the Framework session can be serialized alongside this state, but does not
    replace the procurement plan source of truth.
    """

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def before_invocation(
        self,
        session: AgentSession,
        *,
        user_input: str,
        resumed: bool,
    ) -> InvocationContext:
        if session.plan is None or session.request is None:
            raise SessionCompatibilityError("plan and request are required before invocation")
        next_step = session.plan_executor().next_step()
        return InvocationContext(
            session_id_hash=self._hash(session.session_id),
            conversation_id_hash=self._hash(session.conversation_id),
            turn_index=session.turn_index,
            user_input=user_input,
            request=session.request,
            plan=session.plan,
            next_step_id=next_step.step_id if next_step else None,
            next_step_type=next_step.step_type if next_step else None,
            selected_item=session.selected_item,
            evidence=dict(session.evidence),
            governance_state=dict(session.governance_state),
            resumed=resumed,
        )

    def after_invocation(
        self,
        session: AgentSession,
        *,
        response_text: str,
        response_id: str | None = None,
    ) -> None:
        session.add_message("assistant", response_text)
        session.last_response_id = response_id
