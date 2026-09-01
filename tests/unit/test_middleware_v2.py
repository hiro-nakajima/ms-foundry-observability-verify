from agent_framework import AgentContext, AgentSession, FunctionInvocationContext, FunctionTool
import pytest

from procurement_agent.middleware import SessionGovernanceAgentMiddleware, ToolGovernanceFunctionMiddleware
from procurement_agent.session_state import SessionRequiredError, initialize_execution_state, load_execution_state


@pytest.mark.anyio
async def test_agent_middleware_uses_framework_session_without_owning_business_turn():
    session = AgentSession()
    initialize_execution_state(session)
    context = AgentContext(agent=object(), messages=[], session=session)
    called = False
    async def call_next():
        nonlocal called
        called = True
    await SessionGovernanceAgentMiddleware().process(context, call_next)
    assert called
    assert load_execution_state(session).turn_number == 0


@pytest.mark.anyio
async def test_agent_middleware_fails_closed_without_session():
    context = AgentContext(agent=object(), messages=[], session=None)
    with pytest.raises(SessionRequiredError):
        await SessionGovernanceAgentMiddleware().process(context, lambda: None)


@pytest.mark.anyio
async def test_function_middleware_rejects_non_allowlisted_tool():
    session = AgentSession()
    initialize_execution_state(session)
    tool = FunctionTool(name="direct_search_call", func=lambda: None)
    context = FunctionInvocationContext(function=tool, arguments={}, session=session)
    with pytest.raises(PermissionError):
        await ToolGovernanceFunctionMiddleware().process(context, lambda: None)
    assert load_execution_state(session).governance_decisions[-1].outcome == "DENY"
