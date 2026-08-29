"""Common four-stage governance middleware hooks."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from .governance import GovernanceAdapter
from .models import AgentRole, GovernanceDecision, ToolResponse


T = TypeVar("T")


class GovernanceMiddleware:
    def __init__(self, governance: GovernanceAdapter) -> None:
        self.governance = governance

    def run_pre_input(self, text: str, role: AgentRole) -> GovernanceDecision:
        return self.governance.pre_input(text, agent_role=role)

    def run_pre_tool(
        self, *, role: AgentRole, tool_name: str, pre_tool_kwargs: dict
    ) -> GovernanceDecision:
        return self.governance.pre_tool(
            agent_role=role, tool_name=tool_name, **pre_tool_kwargs
        )

    def run_post_tool(
        self,
        *,
        role: AgentRole,
        tool_name: str,
        response: ToolResponse,
        plan_id: str,
        step_id: str,
    ) -> GovernanceDecision:
        return self.governance.post_tool(
            agent_role=role,
            tool_name=tool_name,
            response=response,
            plan_id=plan_id,
            step_id=step_id,
        )

    def run_pre_output(self, *, role: AgentRole, **kwargs) -> GovernanceDecision:
        return self.governance.pre_output(agent_role=role, **kwargs)

    def governed_tool_call(
        self,
        *,
        role: AgentRole,
        tool_name: str,
        pre_tool_kwargs: dict,
        operation: Callable[[], ToolResponse],
    ) -> tuple[ToolResponse, tuple[GovernanceDecision, GovernanceDecision]]:
        before = self.governance.pre_tool(agent_role=role, tool_name=tool_name, **pre_tool_kwargs)
        response = operation()
        after = self.governance.post_tool(
            agent_role=role,
            tool_name=tool_name,
            response=response,
            plan_id=pre_tool_kwargs["plan_id"],
            step_id=pre_tool_kwargs["step_id"],
        )
        return response, (before, after)
