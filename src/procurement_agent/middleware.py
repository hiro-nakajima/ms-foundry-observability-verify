"""Governance hooks implemented with Agent Framework middleware base classes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from agent_framework import AgentContext, AgentMiddleware, ChatContext, ChatMiddleware, FunctionInvocationContext, FunctionMiddleware

from .models import AgentRole, GovernanceDecision, GovernanceOutcome
from .session_state import load_context_state, load_execution_state, save_execution_state

ROLE_TOOL_ALLOWLIST = {
    AgentRole.COORDINATOR: {"catalog_search_agent", "code_determination_agent"},
    AgentRole.CATALOG_SEARCH: {"catalog_search"},
    AgentRole.CODE_DETERMINATION: {"code_master_search"},
}


class SessionGovernanceAgentMiddleware(AgentMiddleware):
    async def process(self, context: AgentContext, call_next: Callable[[], Awaitable[None]]) -> None:
        load_execution_state(context.session, required=True)
        await call_next()


class ContentGovernanceChatMiddleware(ChatMiddleware):
    async def process(self, context: ChatContext, call_next: Callable[[], Awaitable[None]]) -> None:
        load_execution_state(context.session, required=True)
        await call_next()


class ToolGovernanceFunctionMiddleware(FunctionMiddleware):
    """Fail closed and enforce the coordinator's remote child proxy allowlist."""

    async def process(self, context: FunctionInvocationContext, call_next: Callable[[], Awaitable[None]]) -> None:
        state = load_context_state(context)
        name = context.function.name
        outcome = GovernanceOutcome.ALLOW if name in ROLE_TOOL_ALLOWLIST[AgentRole.COORDINATOR] else GovernanceOutcome.DENY
        state.governance_decisions.append(GovernanceDecision(
            policy_version="procurement-v2.0", stage="pre_tool", outcome=outcome,
            reason="coordinator remote child proxy allowlist", agent_role=AgentRole.COORDINATOR,
            tool_name=name, plan_id=state.plan.plan_id if state.plan else None,
            step_id=state.current_step_id,
        ))
        save_execution_state(context.session, state)  # type: ignore[arg-type]
        if outcome == GovernanceOutcome.DENY:
            raise PermissionError(f"tool is outside coordinator allowlist: {name}")
        await call_next()
