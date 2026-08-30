"""Agent Governance Toolkit adapter with shadow and enforce modes."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agentmesh.governance import PolicyEngine
from agentmesh.governance.otel_observability import trace_policy_evaluation

from .models import (
    AgentRole,
    BusinessStatus,
    GovernanceDecision,
    GovernanceMode,
    GovernanceOutcome,
    PlanStatus,
    ToolResponse,
)


SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)\b(?:api[_-]?key|client[_-]?secret|password)\s*[:=]\s*\S+"),
    # A bare hexadecimal trace/span ID is observability metadata, not evidence
    # of a secret. Only treat unlabeled Base64-like values as secrets when they
    # contain Base64-specific punctuation; named keys are handled above.
    re.compile(
        r"(?<![A-Za-z0-9+/=])"
        r"(?=[A-Za-z0-9+/=]{32,}(?![A-Za-z0-9+/=]))"
        r"(?=[A-Za-z0-9+/=]*[+/=])"
        r"[A-Za-z0-9+/]{32,}={0,2}"
        r"(?![A-Za-z0-9+/=])"
    ),
)
CANARY_PATTERN = re.compile(r"\bSYNTHETIC-CANARY-[A-Z0-9-]+\b")

DATA_TOOLS = {
    "search_catalog",
    "get_catalog_item",
    "lookup_account_code",
    "lookup_department",
    "get_applicant",
    "estimate_delivery",
}
SEARCH_TOOLS = DATA_TOOLS
ROLE_ALLOWLIST: dict[AgentRole, set[str]] = {
    AgentRole.PROCUREMENT_ASSISTANT: {
        *DATA_TOOLS,
        "calculate_request",
        "validate_application",
        "skill.request_check",
    },
    AgentRole.COORDINATOR: {
        "procurement_specialist",
        "drafting_specialist",
        "validate_application",
    },
    AgentRole.PROCUREMENT_SPECIALIST: DATA_TOOLS,
    AgentRole.DRAFTING_SPECIALIST: {
        "calculate_request",
        "validate_application",
        "skill.request_check",
    },
}


class GovernanceDenied(PermissionError):
    def __init__(self, decision: GovernanceDecision):
        self.decision = decision
        super().__init__(f"{decision.rule_id}: {decision.reason}")


class GovernanceAdapter:
    """Thin application adapter around AGT's deterministic PolicyEngine."""

    def __init__(
        self,
        policy_path: str | Path,
        *,
        mode: GovernanceMode = GovernanceMode.SHADOW,
    ) -> None:
        self.policy_path = Path(policy_path)
        self.mode = mode
        self.engine = PolicyEngine(conflict_strategy="deny_overrides")
        self.policy = self.engine.load_yaml_file(str(self.policy_path))

    @property
    def policy_version(self) -> str:
        return self.policy.version

    @staticmethod
    def _has_secret(value: Any) -> bool:
        text = str(value)
        return any(pattern.search(text) for pattern in SECRET_PATTERNS)

    @staticmethod
    def _has_canary(value: Any) -> bool:
        return CANARY_PATTERN.search(str(value)) is not None

    def evaluate(
        self,
        *,
        stage: str,
        agent_role: AgentRole,
        context: dict[str, Any],
        tool_name: str | None = None,
        plan_id: str | None = None,
        step_id: str | None = None,
    ) -> GovernanceDecision:
        with trace_policy_evaluation(agent_id=agent_role.value, stage=stage) as trace_result:
            result = self.engine.evaluate(agent_role.value, context, stage=stage)
            trace_result.update(
                action=result.action,
                rule=result.matched_rule,
                policy_name=result.policy_name,
                allowed=result.allowed,
            )
        if result.allowed:
            outcome = GovernanceOutcome.ALLOW
        elif self.mode == GovernanceMode.SHADOW:
            outcome = GovernanceOutcome.WOULD_DENY
        else:
            outcome = GovernanceOutcome.DENY
        decision = GovernanceDecision(
            policy_version=self.policy_version,
            rule_id=result.matched_rule or "default-action",
            stage=stage,
            outcome=outcome,
            reason=result.reason or result.action,
            agent_role=agent_role,
            tool_name=tool_name,
            plan_id=plan_id,
            step_id=step_id,
        )
        if outcome == GovernanceOutcome.DENY:
            raise GovernanceDenied(decision)
        return decision

    def pre_input(self, text: str, *, agent_role: AgentRole) -> GovernanceDecision:
        return self.evaluate(
            stage="pre_input",
            agent_role=agent_role,
            context={
                "input": {
                    "contains_secret": self._has_secret(text),
                    "contains_canary": self._has_canary(text),
                }
            },
        )

    def pre_tool(
        self,
        *,
        agent_role: AgentRole,
        tool_name: str,
        plan_id: str,
        step_id: str,
        plan_status: PlanStatus,
        duplicate_step: bool,
        missing_required_information: bool,
        tool_call_count: int,
        agent_tool_call_count: int,
    ) -> GovernanceDecision:
        return self.evaluate(
            stage="pre_tool",
            agent_role=agent_role,
            tool_name=tool_name,
            plan_id=plan_id,
            step_id=step_id,
            context={
                "action": {
                    "agent_role": agent_role.value,
                    "is_data_tool": tool_name in DATA_TOOLS,
                    "is_search_tool": tool_name in SEARCH_TOOLS,
                    "role_tool_violation": tool_name not in ROLE_ALLOWLIST[agent_role],
                    "duplicate_step": duplicate_step,
                    "plan_completed": plan_status == PlanStatus.COMPLETED,
                    "missing_required_information": missing_required_information,
                    "tool_call_count": tool_call_count,
                    "agent_tool_call_count": agent_tool_call_count,
                }
            },
        )

    def post_tool(
        self,
        *,
        agent_role: AgentRole,
        tool_name: str,
        response: ToolResponse,
        plan_id: str,
        step_id: str,
    ) -> GovernanceDecision:
        success_without_evidence = (
            response.business_status == BusinessStatus.SUCCESS and not response.evidence_refs
        )
        return self.evaluate(
            stage="post_tool",
            agent_role=agent_role,
            tool_name=tool_name,
            plan_id=plan_id,
            step_id=step_id,
            context={
                "tool": {
                    "success_without_evidence": success_without_evidence,
                    "contains_secret": self._has_secret(response.result),
                    "contains_canary": self._has_canary(response.result),
                }
            },
        )

    def pre_output(
        self,
        *,
        agent_role: AgentRole,
        plan_id: str,
        response_text: str,
        ungrounded_product_or_code: bool,
        missing_calculation_output: bool,
        validation_not_passed: bool,
        plan_not_ready: bool,
    ) -> GovernanceDecision:
        return self.evaluate(
            stage="pre_output",
            agent_role=agent_role,
            plan_id=plan_id,
            context={
                "response": {
                    "ungrounded_product_or_code": ungrounded_product_or_code,
                    "missing_calculation_output": missing_calculation_output,
                    "validation_not_passed": validation_not_passed,
                    "plan_not_ready": plan_not_ready,
                    "contains_secret": self._has_secret(response_text),
                    "contains_canary": self._has_canary(response_text),
                }
            },
        )
