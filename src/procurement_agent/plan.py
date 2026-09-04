"""Deterministic three-step Plan & Execute policy."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from .models import AgentRole, ExecutionPlan, PlanGenerationSource, PlanStatus, PlanStep, StepType
from .progress import publish


class PlanStateError(RuntimeError):
    pass


class DuplicateStepSuppressed(PlanStateError):
    pass


APPROVED_STEPS = (
    ("catalog", StepType.CATALOG_SEARCH, AgentRole.CATALOG_SEARCH, ["request.query", "request.quantity", "request.constraints"]),
    ("code", StepType.CODE_DETERMINATION, AgentRole.CODE_DETERMINATION, ["catalog.selected_product_code", "catalog.product_category", "request.department_name"]),
    ("merge_validate", StepType.MERGE_VALIDATE, AgentRole.COORDINATOR, ["request", "catalog", "codes", "evidence"]),
)


def stable_input_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def completed_step_key(plan_version: int, step_id: str, input_hash: str) -> str:
    return f"{plan_version}:{step_id}:{input_hash}"


def default_steps() -> list[PlanStep]:
    return [PlanStep(step_id=a, step_type=b, owner=c, input_refs=list(d)) for a, b, c, d in APPROVED_STEPS]


class StructuredPlanBuilder:
    response_format: type[ExecutionPlan] = ExecutionPlan

    def build(self, raw_response: ExecutionPlan | dict[str, Any] | str | None) -> ExecutionPlan:
        source = PlanGenerationSource.MODEL_STRUCTURED
        reason: str | None = None
        parsed: ExecutionPlan | None = None
        if raw_response is None:
            source = PlanGenerationSource.EMPTY_RESPONSE_FALLBACK
            reason = "planner returned no response"
        elif isinstance(raw_response, ExecutionPlan):
            parsed = raw_response
        else:
            try:
                parsed = ExecutionPlan.model_validate_json(raw_response) if isinstance(raw_response, str) else ExecutionPlan.model_validate(raw_response)
            except (ValidationError, ValueError, TypeError):
                source = PlanGenerationSource.PARSE_FAILURE_FALLBACK
                reason = "planner response could not be parsed as ExecutionPlan"

        if parsed is not None and not parsed.steps:
            source = PlanGenerationSource.EMPTY_RESPONSE_FALLBACK
            reason = "planner returned an empty step list"
        elif parsed is not None:
            actual = [(s.step_id, s.step_type, s.owner, s.input_refs) for s in parsed.steps]
            expected = [(a, b, c, d) for a, b, c, d in APPROVED_STEPS]
            if actual != expected:
                source = PlanGenerationSource.REQUIRED_STEP_FALLBACK
                reason = "planner omitted or changed an approved step, order, owner, or input_refs"

        return ExecutionPlan(
            plan_id=parsed.plan_id if parsed and parsed.plan_id else f"plan-{uuid4()}",
            version=parsed.version if parsed else 1,
            steps=default_steps(),
            status=PlanStatus.PENDING,
            generation_source=source,
            fallback_reason=reason,
        )


class PlanExecutor:
    def __init__(self, plan: ExecutionPlan, completed_step_keys: list[str], *, max_attempts: int = 2) -> None:
        self.plan = plan
        self.completed_step_keys = completed_step_keys
        self.max_attempts = max_attempts
        self.events: list[dict[str, Any]] = []

    def step(self, step_id: str) -> PlanStep:
        try:
            return next(step for step in self.plan.steps if step.step_id == step_id)
        except StopIteration as exc:
            raise PlanStateError(f"unknown step: {step_id}") from exc

    def next_step(self) -> PlanStep | None:
        if self.plan.status in {PlanStatus.COMPLETED, PlanStatus.BLOCKED, PlanStatus.WAITING_USER}:
            return None
        return next((s for s in self.plan.steps if s.status != PlanStatus.COMPLETED), None)

    def start(self, step_id: str, inputs: Any) -> PlanStep:
        if self.plan.status in {PlanStatus.COMPLETED, PlanStatus.BLOCKED, PlanStatus.WAITING_USER}:
            raise PlanStateError(f"cannot execute after terminal state {self.plan.status}")
        step = self.step(step_id)
        expected = self.next_step()
        if expected is not step:
            raise PlanStateError(f"step order violation: expected {expected.step_id if expected else None}")
        digest = stable_input_hash(inputs)
        key = completed_step_key(self.plan.version, step.step_id, digest)
        if key in self.completed_step_keys:
            self.events.append({"name": "duplicate_step_suppressed", "step_id": step_id})
            raise DuplicateStepSuppressed(key)
        if step.attempt >= self.max_attempts:
            self.block(step_id, "attempt limit reached")
            raise PlanStateError("attempt limit reached")
        step.status = PlanStatus.RUNNING
        step.attempt += 1
        step.input_hash = digest
        step.started_at = datetime.now(timezone.utc)
        self.plan.status = PlanStatus.RUNNING
        self.plan.updated_at = datetime.now(timezone.utc)
        self.events.append({"name": "step.started", "step_id": step_id, "attempt": step.attempt})
        publish(step_id, 'started')
        return step

    def complete(self, step_id: str, *, output_refs: list[str], reason: str) -> PlanStep:
        step = self.step(step_id)
        if step.status != PlanStatus.RUNNING or step.input_hash is None:
            raise PlanStateError("only a running step can complete")
        step.status = PlanStatus.COMPLETED
        step.output_refs = output_refs
        step.completion_reason = reason
        step.ended_at = datetime.now(timezone.utc)
        key = completed_step_key(self.plan.version, step_id, step.input_hash)
        if key not in self.completed_step_keys:
            self.completed_step_keys.append(key)
        if all(candidate.status == PlanStatus.COMPLETED for candidate in self.plan.steps):
            self.plan.status = PlanStatus.COMPLETED
        self.plan.updated_at = datetime.now(timezone.utc)
        self.events.append({"name": "step.completed", "step_id": step_id})
        publish(step_id, 'completed')
        return step

    def retry(self, step_id: str, reason: str) -> None:
        step = self.step(step_id)
        if step.status != PlanStatus.RUNNING:
            raise PlanStateError("retry requires a running step")
        if step.attempt >= self.max_attempts:
            self.block(step_id, f"attempt limit reached: {reason}")
            return
        step.status = PlanStatus.PENDING
        step.completion_reason = reason
        step.ended_at = datetime.now(timezone.utc)
        self.events.append({"name": "step.retry_scheduled", "step_id": step_id, "reason": reason})
        publish(step_id, 'retry')

    def wait_for_user(self, step_id: str, reason: str) -> None:
        step = self.step(step_id)
        step.status = PlanStatus.WAITING_USER
        step.completion_reason = reason
        step.ended_at = datetime.now(timezone.utc)
        self.plan.status = PlanStatus.WAITING_USER
        self.events.append({"name": "plan.replanned", "step_id": step_id, "reason": reason})
        publish(step_id, 'waiting_user')

    def block(self, step_id: str, reason: str) -> None:
        step = self.step(step_id)
        step.status = PlanStatus.BLOCKED
        step.completion_reason = reason
        step.ended_at = datetime.now(timezone.utc)
        self.plan.status = PlanStatus.BLOCKED
        self.events.append({"name": "plan.blocked", "step_id": step_id, "reason": reason})
        publish(step_id, 'blocked')
