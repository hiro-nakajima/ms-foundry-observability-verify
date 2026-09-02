"""Single hosted-parent factory with two remote Foundry Prompt Agent proxies."""

from __future__ import annotations

import os
import json
from dataclasses import dataclass
from typing import Any

from agent_framework import (
    Agent, AgentSession, ContextProvider, FunctionInvocationContext,
    InMemoryHistoryProvider, SessionContext,
)
from agent_framework_foundry import FoundryAgent, FoundryChatClient
from azure.identity import DefaultAzureCredential

from .framework import (
    CONTROLLER_RESULT_END, CONTROLLER_RESULT_START, DeterministicChatClient,
    controller_result_handler, local_parent_handler,
)
from .middleware import ContentGovernanceChatMiddleware, SessionGovernanceAgentMiddleware, ToolGovernanceFunctionMiddleware
from .models import ExecutionPlan, ProcurementRequest, ScenarioResult
from .controller import ProcurementController
from .observability import TelemetryRecorder
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
    planner: Agent
    catalog_proxy: FoundryAgent
    code_proxy: FoundryAgent
    catalog_tool: Any
    code_tool: Any
    history_provider: InMemoryHistoryProvider
    telemetry: TelemetryRecorder


class ControllerContextProvider(ContextProvider):
    """Route each exposed parent invocation through the ordered domain Controller.

    Framework history remains owned by ``InMemoryHistoryProvider``. This provider
    stores no parallel conversation or session object; it only injects the current
    validated ``ScenarioResult`` before the parent response is generated.
    """

    def __init__(
        self, planner: Agent, catalog_tool: Any, code_tool: Any,
        telemetry: TelemetryRecorder,
    ) -> None:
        super().__init__("procurement-controller-v2")
        self.planner = planner
        self.catalog_tool = catalog_tool
        self.code_tool = code_tool
        self.telemetry = telemetry

    @staticmethod
    def _latest_user_text(context: SessionContext) -> str:
        for message in reversed(context.input_messages):
            role = getattr(message.role, "value", message.role)
            if role == "user" and message.text.strip():
                return message.text.strip()
        raise ValueError("a non-empty user request is required")

    async def before_run(
        self, *, agent: Agent, session: AgentSession,
        context: SessionContext, state: dict[str, Any],
    ) -> None:
        current = load_execution_state(session, required=False)
        next_turn = (current.turn_number if current else 0) + 1
        test_case_id = f"HOSTED-{session.session_id}-T{next_turn}"
        result = await _execute_hosted_components(
            planner=self.planner,
            catalog_tool=self.catalog_tool,
            code_tool=self.code_tool,
            natural_request=self._latest_user_text(context),
            session=session,
            test_case_id=test_case_id,
            telemetry=self.telemetry,
        )
        context.extend_instructions(
            self.source_id,
            f"{CONTROLLER_RESULT_START}{result.model_dump_json()}{CONTROLLER_RESULT_END}",
        )


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
    planner_client = parent_client or FoundryChatClient(
        model=settings.parent_model,
        project_endpoint=settings.project_endpoint,
        credential=credential,
    )
    planner = Agent(
        planner_client,
        id="procurement-parent-planner-v2",
        name="procurement_parent_planner",
        description="Internal structured request and ExecutionPlan generator.",
        instructions=PARENT_INSTRUCTIONS,
        additional_properties={"architecture_id": "procurement_application_v2"},
    )
    telemetry = TelemetryRecorder.for_hosted_runtime()
    controller_provider = ControllerContextProvider(
        planner, catalog_tool, code_tool, telemetry,
    )
    parent = Agent(
        DeterministicChatClient(controller_result_handler, client_name="controller-result"),
        id="procurement-parent-v2",
        name=settings.parent_name,
        description="Single Hosted parent for the revised procurement E2E.",
        instructions=PARENT_INSTRUCTIONS,
        tools=[catalog_tool, code_tool],
        context_providers=[history, controller_provider],
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
    return HostedAgentBundle(
        parent=parent,
        planner=planner,
        catalog_proxy=catalog_proxy,
        code_proxy=code_proxy,
        catalog_tool=catalog_tool,
        code_tool=code_tool,
        history_provider=history,
        telemetry=telemetry,
    )


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
    result: dict[str, Any] = {}

    async def invoke() -> None:
        result["raw"] = await tool.invoke(
            arguments=arguments, context=context, skip_parsing=True,
        )

    await ToolGovernanceFunctionMiddleware().process(context, invoke)
    raw = result["raw"]
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


async def _execute_hosted_components(
    *, planner: Agent, catalog_tool: Any, code_tool: Any, natural_request: str,
    session: AgentSession | None, test_case_id: str, telemetry: TelemetryRecorder,
) -> ScenarioResult:
    if session is None:
        raise ValueError("Framework AgentSession is required; implicit sessions are forbidden")
    if load_execution_state(session, required=False) is None:
        initialize_execution_state(session, test_case_id=test_case_id)
    request_response = await planner.run(
        natural_request, session=session, tools=[],
        options={"response_format": ProcurementRequest, "tool_choice": "none"},
    )
    request = _response_model(request_response, ProcurementRequest)
    plan_response = await planner.run(
        request.model_dump_json(), session=session, tools=[],
        options={"response_format": ExecutionPlan, "tool_choice": "none"},
    )
    try:
        raw_plan: Any = _response_model(plan_response, ExecutionPlan)
    except Exception:
        raw_plan = getattr(plan_response, "text", None)
    controller = ProcurementController(
        lambda payload: _invoke_remote_tool(catalog_tool, payload, session),
        lambda payload: _invoke_remote_tool(code_tool, payload, session),
        telemetry=telemetry,
    )
    return await controller.execute(
        request, session=session, test_case_id=test_case_id, raw_plan=raw_plan,
    )


async def execute_hosted_turn(
    bundle: HostedAgentBundle, natural_request: str, *, session: AgentSession | None,
    test_case_id: str,
) -> ScenarioResult:
    """Contract-test entry point for the same route exposed by Hosted/DevUI."""
    return await _execute_hosted_components(
        planner=bundle.planner,
        catalog_tool=bundle.catalog_tool,
        code_tool=bundle.code_tool,
        natural_request=natural_request,
        session=session,
        test_case_id=test_case_id,
        telemetry=bundle.telemetry,
    )
