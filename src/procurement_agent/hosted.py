"""Single hosted-parent factory with two remote Foundry Prompt Agent proxies."""

from __future__ import annotations

import os
import json
from dataclasses import dataclass
from typing import Any

from agent_framework import Agent, AgentSession, FunctionInvocationContext, InMemoryHistoryProvider
from agent_framework_foundry import FoundryAgent, FoundryChatClient
from azure.identity import DefaultAzureCredential

from .framework import DeterministicChatClient, local_parent_handler
from .middleware import ContentGovernanceChatMiddleware, SessionGovernanceAgentMiddleware, ToolGovernanceFunctionMiddleware
from .models import ExecutionPlan, ProcurementRequest, ScenarioResult
from .controller import ProcurementController
from .session_state import initialize_execution_state, load_execution_state


PARENT_INSTRUCTIONS = """You are the single Hosted procurement coordinator.
Interpret the user request, produce an ExecutionPlan using the configured Pydantic
response_format, then execute catalog, code, and merge/validate in that order.
Call only catalog_search_agent and code_determination_agent. Each task argument must
be a validated Structured snapshot JSON. Never infer product codes, prices, account
codes, or department codes. Do not output chain-of-thought.
"""


@dataclass(frozen=True)
class FoundryRuntimeSettings:
    project_endpoint: str
    parent_model: str
    catalog_agent_name: str = "catalog_search_agent"
    catalog_agent_version: str = "1"
    code_agent_name: str = "code_determination_agent"
    code_agent_version: str = "1"
    parent_name: str = "procurement_parent_agent"

    @classmethod
    def from_env(cls) -> "FoundryRuntimeSettings":
        endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT", "")
        model = os.getenv("PROCUREMENT_PARENT_MODEL_DEPLOYMENT", "")
        if not endpoint or not model:
            raise ValueError("FOUNDRY_PROJECT_ENDPOINT and PROCUREMENT_PARENT_MODEL_DEPLOYMENT are required")
        return cls(
            project_endpoint=endpoint,
            parent_model=model,
            catalog_agent_name=os.getenv("PROCUREMENT_CATALOG_AGENT_NAME", "catalog_search_agent"),
            catalog_agent_version=os.getenv("PROCUREMENT_CATALOG_AGENT_VERSION", "1"),
            code_agent_name=os.getenv("PROCUREMENT_CODE_AGENT_NAME", "code_determination_agent"),
            code_agent_version=os.getenv("PROCUREMENT_CODE_AGENT_VERSION", "1"),
        )


@dataclass
class HostedAgentBundle:
    parent: Agent
    catalog_proxy: FoundryAgent
    code_proxy: FoundryAgent
    catalog_tool: Any
    code_tool: Any
    history_provider: InMemoryHistoryProvider


def build_hosted_bundle(
    settings: FoundryRuntimeSettings,
    *,
    parent_client: Any | None = None,
    credential: Any | None = None,
) -> HostedAgentBundle:
    credential = credential or DefaultAzureCredential()
    catalog_proxy = FoundryAgent(
        project_endpoint=settings.project_endpoint,
        agent_name=settings.catalog_agent_name,
        agent_version=settings.catalog_agent_version,
        credential=credential,
        name=settings.catalog_agent_name,
        description="Remote registered Prompt Agent for procurement catalog search.",
    )
    code_proxy = FoundryAgent(
        project_endpoint=settings.project_endpoint,
        agent_name=settings.code_agent_name,
        agent_version=settings.code_agent_version,
        credential=credential,
        name=settings.code_agent_name,
        description="Remote registered Prompt Agent for account and department code lookup.",
    )
    catalog_tool = catalog_proxy.as_tool(
        name="catalog_search_agent",
        description="Run the registered catalog Prompt Agent with CatalogSearchInput JSON.",
        propagate_session=False,
    )
    code_tool = code_proxy.as_tool(
        name="code_determination_agent",
        description="Run the registered code Prompt Agent with CodeDeterminationInput JSON.",
        propagate_session=False,
    )
    history = InMemoryHistoryProvider("procurement-history", load_messages=True)
    client = parent_client or FoundryChatClient(
        model=settings.parent_model,
        project_endpoint=settings.project_endpoint,
        credential=credential,
    )
    parent = Agent(
        client,
        id="procurement-parent-v2",
        name=settings.parent_name,
        description="Single Hosted parent for the revised procurement E2E.",
        instructions=PARENT_INSTRUCTIONS,
        tools=[catalog_tool, code_tool],
        context_providers=[history],
        middleware=[
            SessionGovernanceAgentMiddleware(),
            ContentGovernanceChatMiddleware(),
            ToolGovernanceFunctionMiddleware(),
        ],
        additional_properties={
            "architecture_id": "procurement_application_v2",
            "child_implementation_location": "Foundry Agent Service",
            "propagate_child_session": False,
        },
    )
    return HostedAgentBundle(parent, catalog_proxy, code_proxy, catalog_tool, code_tool, history)


def build_local_parent_scaffold() -> Agent:
    """No-network parent only; tests inject fixture tools outside the container package."""
    history = InMemoryHistoryProvider("procurement-history", load_messages=True)
    return Agent(
        DeterministicChatClient(local_parent_handler),
        id="procurement-parent-v2-local",
        name="procurement_parent_agent",
        instructions=PARENT_INSTRUCTIONS,
        context_providers=[history],
        additional_properties={"architecture_id": "procurement_application_v2"},
    )


def _response_model(response: Any, model_type: type[Any]) -> Any:
    value = getattr(response, "value", None)
    if isinstance(value, model_type):
        return value
    text = getattr(response, "text", "")
    return model_type.model_validate_json(text)


async def _invoke_remote_tool(tool: Any, payload: Any, session: AgentSession) -> dict[str, Any]:
    arguments = {"task": payload.model_dump_json()}
    context = FunctionInvocationContext(function=tool, arguments=arguments, session=session)
    raw = await tool.invoke(arguments=arguments, context=context, skip_parsing=True)
    if hasattr(raw, "model_dump"):
        return raw.model_dump(mode="json")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        return json.loads(raw)
    if isinstance(raw, list):
        text = "".join(getattr(item, "text", "") for item in raw)
        return json.loads(text)
    raise ValueError("remote child Agent returned an unsupported result type")


async def execute_hosted_turn(
    bundle: HostedAgentBundle, natural_request: str, *, session: AgentSession | None,
    test_case_id: str,
) -> ScenarioResult:
    """Natural language → two Pydantic response formats → ordered Controller."""
    if session is None:
        raise ValueError("Framework AgentSession is required; implicit sessions are forbidden")
    if load_execution_state(session, required=False) is None:
        initialize_execution_state(session, test_case_id=test_case_id)
    request_response = await bundle.parent.run(
        natural_request, session=session, tools=[],
        options={"response_format": ProcurementRequest, "tool_choice": "none"},
    )
    request = _response_model(request_response, ProcurementRequest)
    plan_response = await bundle.parent.run(
        request.model_dump_json(), session=session, tools=[],
        options={"response_format": ExecutionPlan, "tool_choice": "none"},
    )
    try:
        raw_plan: Any = _response_model(plan_response, ExecutionPlan)
    except Exception:
        raw_plan = getattr(plan_response, "text", None)
    controller = ProcurementController(
        lambda payload: _invoke_remote_tool(bundle.catalog_tool, payload, session),
        lambda payload: _invoke_remote_tool(bundle.code_tool, payload, session),
    )
    return await controller.execute(
        request, session=session, test_case_id=test_case_id, raw_plan=raw_plan,
    )
