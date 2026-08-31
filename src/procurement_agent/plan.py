"""Structured Plan generation and deterministic Plan & Execute state machine."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from .models import (
    AgentPlanResponse,
    AgentRole,
    ExecutionPlan,
    LogicalPattern,
    PlanGenerationSource,
    PlanStatus,
    PlanStep,
    PlanStepProposal,
    ProcurementRequest,
)


class PlanStateError(RuntimeError):
    pass


class DuplicateStepSuppressed(PlanStateError):
    pass


def stable_input_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def completed_step_key(plan_version: int, step_id: str, input_hash: str) -> str:
    return f"{plan_version}:{step_id}:{input_hash}"


SINGLE_TEMPLATE = (
    ("S01", "parse_request", AgentRole.PROCUREMENT_ASSISTANT, ["request.raw"]),
    ("S02", "resolve_missing_fields", AgentRole.PROCUREMENT_ASSISTANT, ["request"]),
    (
        "S03",
        "search_catalog",
        AgentRole.PROCUREMENT_ASSISTANT,
        ["request.query", "request.constraints.specifications"],
    ),
    ("S04", "select_catalog_item", AgentRole.PROCUREMENT_ASSISTANT, ["search.candidates"]),
    ("S05", "get_applicant", AgentRole.PROCUREMENT_ASSISTANT, ["request.applicant_name"]),
    (
        "S06",
        "lookup_department",
        AgentRole.PROCUREMENT_ASSISTANT,
        ["applicant.department_code", "request.department_name"],
    ),
    ("S07", "lookup_account_code", AgentRole.PROCUREMENT_ASSISTANT, ["item.category", "request.purpose"]),
    ("S08", "estimate_delivery", AgentRole.PROCUREMENT_ASSISTANT, ["item.product_code", "request.quantity", "request.constraints.requested_by"]),
    ("S09", "calculate_total", AgentRole.PROCUREMENT_ASSISTANT, ["item.unit_price", "request.quantity"]),
    ("S10", "build_draft", AgentRole.PROCUREMENT_ASSISTANT, ["item", "applicant", "department", "account", "delivery", "calculation"]),
    ("S11", "validate_draft", AgentRole.PROCUREMENT_ASSISTANT, ["application_draft", "evidence"]),
    ("S12", "confirm_application", AgentRole.PROCUREMENT_ASSISTANT, ["validation", "application_draft", "user.confirmation"]),
    ("S13", "present_draft", AgentRole.PROCUREMENT_ASSISTANT, ["user.confirmation", "application_draft"]),
)


MULTI_TEMPLATE = (
    ("S01", "parse_request", AgentRole.COORDINATOR, ["request.raw"]),
    ("S02", "resolve_missing_fields", AgentRole.COORDINATOR, ["request"]),
    (
        "S03",
        "procurement_lookup",
        AgentRole.PROCUREMENT_SPECIALIST,
        [
            "request.query",
            "request.quantity",
            "request.applicant_name",
            "request.department_name",
            "request.purpose",
            "request.constraints.requested_by",
            "request.constraints.specifications",
            "context_snapshot",
        ],
    ),
    ("S04", "merge_procurement_result", AgentRole.COORDINATOR, ["procurement_result"]),
    ("S05", "build_draft", AgentRole.DRAFTING_SPECIALIST, ["request", "procurement_result", "context_snapshot"]),
    ("S06", "merge_draft_result", AgentRole.COORDINATOR, ["drafting_result"]),
    ("S07", "validate_draft", AgentRole.COORDINATOR, ["application_draft", "evidence"]),
    ("S08", "confirm_application", AgentRole.COORDINATOR, ["validation", "application_draft", "user.confirmation"]),
    ("S09", "present_draft", AgentRole.COORDINATOR, ["user.confirmation", "application_draft"]),
)


class StructuredPlanBuilder:
    """Normalizes model structured output into an application-owned plan.

    The model may suggest step order through AgentPlanResponse, but it cannot set
    runtime status, attempts, timestamps, evidence, or completion. Unknown or
    incomplete proposals fall back to the approved deterministic template.
    """

    response_format: type[AgentPlanResponse] = AgentPlanResponse

    def build(
        self,
        request: ProcurementRequest,
        pattern: LogicalPattern,
        *,
        raw_response: AgentPlanResponse | dict[str, Any] | None = None,
        plan_id: str | None = None,
        plan_version: int = 1,
        required_missing_fields: list[str] | None = None,
    ) -> ExecutionPlan:
        template = MULTI_TEMPLATE if pattern in {LogicalPattern.PROMPT_MULTI, LogicalPattern.HOSTED_MULTI} else SINGLE_TEMPLATE
        approved = {item[1]: item for item in template}
        warnings: list[str] = []
        source = PlanGenerationSource.DETERMINISTIC_DEFAULT

        parsed: AgentPlanResponse | None = None
        if isinstance(raw_response, AgentPlanResponse):
            parsed = raw_response
        elif isinstance(raw_response, dict):
            try:
                parsed = AgentPlanResponse.model_validate(raw_response)
            except ValidationError as exc:
                warnings.append(f"structured plan rejected: {exc.error_count()} schema errors")

        proposals: list[PlanStepProposal] = []
        if parsed is not None and parsed.steps:
            proposal_types = [proposal.step_type for proposal in parsed.steps]
            expected_types = [item[1] for item in template]
            if proposal_types == expected_types and all(
                proposal.owner == approved[proposal.step_type][2]
                and proposal.step_id == approved[proposal.step_type][0]
                and proposal.input_refs == approved[proposal.step_type][3]
                for proposal in parsed.steps
            ):
                proposals = parsed.steps
                source = PlanGenerationSource.MODEL_STRUCTURED
            else:
                warnings.append(
                    "model plan did not match approved step order/owners/input_refs; "
                    "deterministic template used"
                )
        elif raw_response is not None:
            source = PlanGenerationSource.EMPTY_RESPONSE_FALLBACK
            warnings.append("empty structured plan response; deterministic template used")

        if not proposals:
            proposals = [
                PlanStepProposal(step_id=step_id, step_type=step_type, owner=owner, input_refs=input_refs)
                for step_id, step_type, owner, input_refs in template
            ]

        now = datetime.now(timezone.utc)
        missing = (
            list(required_missing_fields)
            if required_missing_fields is not None
            else request.missing_required_fields()
        )
        steps = [
            PlanStep(
                step_id=proposal.step_id,
                step_type=proposal.step_type,
                owner=proposal.owner,
                input_refs=list(proposal.input_refs),
            )
            for proposal in proposals
        ]
        first = steps[0]
        first.started_at = now
        first.ended_at = now
        first.attempt = 1
        first.completion_reason = "request parsed into ProcurementRequest schema"
        first.status = PlanStatus.COMPLETED
        if missing:
            resolve = next(step for step in steps if step.step_type == "resolve_missing_fields")
            resolve.status = PlanStatus.WAITING_USER
            resolve.completion_reason = f"missing required fields: {', '.join(missing)}"
            plan_status = PlanStatus.WAITING_USER
        else:
            plan_status = PlanStatus.RUNNING

        goal = parsed.goal.strip() if parsed and parsed.goal.strip() else f"Create a validated procurement draft for {request.query}"
        return ExecutionPlan(
            plan_id=plan_id or f"plan-{uuid4()}",
            plan_version=plan_version,
            goal=goal,
            status=plan_status,
            steps=steps,
            generation_source=source,
            warnings=warnings,
        )


ALLOWED_TRANSITIONS: dict[PlanStatus, set[PlanStatus]] = {
    PlanStatus.PENDING: {PlanStatus.RUNNING, PlanStatus.WAITING_USER, PlanStatus.BLOCKED, PlanStatus.INVALIDATED},
    PlanStatus.RUNNING: {PlanStatus.COMPLETED, PlanStatus.FAILED, PlanStatus.BLOCKED, PlanStatus.WAITING_USER, PlanStatus.INVALIDATED},
    PlanStatus.WAITING_USER: {PlanStatus.PENDING, PlanStatus.INVALIDATED, PlanStatus.BLOCKED},
    PlanStatus.COMPLETED: {PlanStatus.INVALIDATED},
    PlanStatus.FAILED: {PlanStatus.PENDING, PlanStatus.BLOCKED, PlanStatus.INVALIDATED},
    PlanStatus.BLOCKED: {PlanStatus.PENDING, PlanStatus.INVALIDATED},
    PlanStatus.INVALIDATED: {PlanStatus.PENDING, PlanStatus.RUNNING},
}


class PlanExecutor:
    def __init__(self, plan: ExecutionPlan, completed_step_keys: list[str] | None = None) -> None:
        self.plan = plan
        self.completed_step_keys = completed_step_keys if completed_step_keys is not None else []
        self.events: list[dict[str, Any]] = []

    def _step(self, step_id: str) -> PlanStep:
        try:
            return next(step for step in self.plan.steps if step.step_id == step_id)
        except StopIteration as exc:
            raise PlanStateError(f"unknown step_id: {step_id}") from exc

    def _transition(self, step: PlanStep, target: PlanStatus, reason: str | None = None) -> None:
        if target not in ALLOWED_TRANSITIONS[step.status]:
            raise PlanStateError(f"invalid transition {step.status} -> {target} for {step.step_id}")
        previous = step.status
        updates: dict[str, Any] = {"status": target}
        if target == PlanStatus.RUNNING:
            updates.update(
                started_at=datetime.now(timezone.utc),
                ended_at=None,
                completion_reason=None,
                attempt=step.attempt + 1,
            )
        elif target in {PlanStatus.COMPLETED, PlanStatus.FAILED, PlanStatus.BLOCKED}:
            updates.update(
                ended_at=datetime.now(timezone.utc),
                completion_reason=reason or target.value.lower(),
            )
        elif target == PlanStatus.WAITING_USER:
            updates["completion_reason"] = reason or "user input required"
        elif target == PlanStatus.INVALIDATED:
            updates.update(
                completion_reason=reason or "input changed",
                output_refs=[],
                evidence_refs=[],
                tool_call_ids=[],
                input_hash=None,
            )
        elif target == PlanStatus.PENDING:
            updates.update(started_at=None, ended_at=None, completion_reason=reason)
        candidate = PlanStep.model_validate({**step.model_dump(mode="python"), **updates})
        for field_name in type(candidate).model_fields:
            object.__setattr__(step, field_name, getattr(candidate, field_name))
        self.plan.updated_at = datetime.now(timezone.utc)
        self.events.append(
            {"event": "step_state_changed", "step_id": step.step_id, "from": previous.value, "to": target.value, "reason": reason}
        )

    def next_step(self) -> PlanStep | None:
        if self.plan.status in {PlanStatus.COMPLETED, PlanStatus.WAITING_USER, PlanStatus.BLOCKED}:
            return None
        return next(
            (
                step
                for step in self.plan.steps
                if step.status in {PlanStatus.PENDING, PlanStatus.INVALIDATED, PlanStatus.FAILED}
            ),
            None,
        )

    def start(self, step_id: str, inputs: Any) -> PlanStep:
        step = self._step(step_id)
        input_hash = stable_input_hash(inputs)
        key = completed_step_key(self.plan.plan_version, step_id, input_hash)
        if key in self.completed_step_keys or (
            step.status == PlanStatus.COMPLETED and step.input_hash == input_hash
        ):
            self.events.append({"event": "duplicate_step_suppressed", "step_id": step_id, "input_hash": input_hash})
            raise DuplicateStepSuppressed(key)
        self._transition(step, PlanStatus.RUNNING)
        step.input_hash = input_hash
        return step

    def complete(
        self,
        step_id: str,
        *,
        output_refs: Iterable[str] = (),
        evidence_refs: Iterable[str] = (),
        tool_call_ids: Iterable[str] = (),
        reason: str = "step completed",
    ) -> PlanStep:
        step = self._step(step_id)
        self._transition(step, PlanStatus.COMPLETED, reason)
        step.output_refs = list(output_refs)
        step.evidence_refs = list(evidence_refs)
        step.tool_call_ids = list(tool_call_ids)
        if step.input_hash is None:
            raise PlanStateError("completed step must have input_hash")
        key = completed_step_key(self.plan.plan_version, step_id, step.input_hash)
        if key not in self.completed_step_keys:
            self.completed_step_keys.append(key)
        if all(item.status == PlanStatus.COMPLETED for item in self.plan.steps):
            self.plan.status = PlanStatus.COMPLETED
        return step

    def wait_for_user(
        self,
        step_id: str,
        missing_fields: Iterable[str],
        *,
        evidence_refs: Iterable[str] = (),
        tool_call_ids: Iterable[str] = (),
        reason: str | None = None,
    ) -> PlanStep:
        step = self._step(step_id)
        fields = list(missing_fields)
        self._transition(
            step,
            PlanStatus.WAITING_USER,
            reason or f"missing: {', '.join(fields)}",
        )
        step.evidence_refs = list(evidence_refs)
        step.tool_call_ids = list(tool_call_ids)
        self.plan.status = PlanStatus.WAITING_USER
        return step

    def block(
        self,
        step_id: str,
        reason: str,
        *,
        evidence_refs: Iterable[str] = (),
        tool_call_ids: Iterable[str] = (),
    ) -> PlanStep:
        """Block the current plan without marking an unpresented draft complete."""

        step = self._step(step_id)
        self._transition(step, PlanStatus.BLOCKED, reason)
        step.evidence_refs = list(evidence_refs)
        step.tool_call_ids = list(tool_call_ids)
        self.plan.status = PlanStatus.BLOCKED
        return step

    def refresh_waiting(
        self,
        step_id: str,
        missing_fields: Iterable[str],
        *,
        reason: str | None = None,
    ) -> PlanStep:
        """Refresh observable WAITING_USER state after a partial request merge."""

        step = self._step(step_id)
        if step.status != PlanStatus.WAITING_USER:
            raise PlanStateError(f"step {step_id} is not waiting for user input")
        step.completion_reason = reason or (
            f"missing required fields: {', '.join(missing_fields)}"
        )
        self.plan.updated_at = datetime.now(timezone.utc)
        self.events.append(
            {
                "event": "waiting_reason_refreshed",
                "step_id": step_id,
                "reason": step.completion_reason,
            }
        )
        return step

    def resume_after_user_input(self, step_id: str) -> PlanStep:
        step = self._step(step_id)
        self._transition(step, PlanStatus.PENDING, "required user input supplied")
        self.plan.status = PlanStatus.RUNNING
        self.events.append({"event": "plan_resumed", "step_id": step_id})
        return step

    def invalidate_by_refs(self, changed_refs: set[str]) -> list[str]:
        """Invalidate only steps whose declared inputs depend on changed refs.

        Output references of invalidated steps are added to the change set so
        downstream consumers are invalidated transitively, while independent
        completed lookups remain reusable.
        """

        affected: list[str] = []
        propagated = set(changed_refs)

        def related(left: str, right: str) -> bool:
            return (
                left == right
                or left.startswith(right + ".")
                or right.startswith(left + ".")
            )

        for step in self.plan.steps:
            if any(
                related(input_ref, changed_ref)
                for input_ref in step.input_refs
                for changed_ref in propagated
            ):
                previous_outputs = list(step.output_refs)
                if step.status != PlanStatus.INVALIDATED:
                    self._transition(step, PlanStatus.INVALIDATED, "upstream input changed")
                affected.append(step.step_id)
                propagated.update(previous_outputs)
                propagated.add(step.step_type)
        if affected:
            self.plan.plan_version += 1
            self.plan.status = PlanStatus.RUNNING
            for step_id in affected:
                self._transition(self._step(step_id), PlanStatus.PENDING, "ready after invalidation")
        return affected

    def execute(
        self,
        step_id: str,
        inputs: Any,
        operation: Callable[[], tuple[list[str], list[str], list[str]]],
    ) -> PlanStep:
        self.start(step_id, inputs)
        output_refs, evidence_refs, tool_call_ids = operation()
        return self.complete(
            step_id,
            output_refs=output_refs,
            evidence_refs=evidence_refs,
            tool_call_ids=tool_call_ids,
        )
