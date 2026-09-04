"""Single hosted-parent factory with two remote Foundry Prompt Agent proxies."""

from __future__ import annotations

import os
import json
import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from agent_framework import (
    Agent, AgentSession, ContextProvider, FunctionInvocationContext,
    InMemoryHistoryProvider, SessionContext,
)
from agent_framework_foundry import FoundryAgent, FoundryChatClient
from azure.identity import DefaultAzureCredential
from pydantic import ValidationError

from .framework import (
    CONTROLLER_RESULT_END, CONTROLLER_RESULT_START, DeterministicChatClient,
    controller_result_handler,
)
from .middleware import ContentGovernanceChatMiddleware, SessionGovernanceAgentMiddleware, ToolGovernanceFunctionMiddleware
from .models import (
    BusinessStatus, ExecutionPlan, OperationStatus, ParseStatus, ProcurementIntake,
    ProcurementRequest, ScenarioResult, TechnicalStatus,
)
from .controller import ProcurementController
from .observability import TelemetryRecorder, current_request_attributes, request_correlation, sha256
from .session_state import (
    EXECUTION_STATE_KEY, SessionStateSchemaError, initialize_execution_state,
    load_execution_state, save_execution_state,
)
from .progress import ProgressMiddleware, publish


PARENT_INSTRUCTIONS = """You are the single Hosted procurement coordinator.
Return only the object named by the current Pydantic response_format.
For ProcurementIntake, extract the user's request AND generate the ExecutionPlan in one response.
Use the supplied previous intake to continue the same request. Only change fields
the user supplies; unknown fields MUST remain null. Never invent a quantity,
department, or memo to fill a required field. Applicant identity and request ID
are supplied by trusted application state and are not user input.
selected_product_code is only a product the user explicitly selected from the
supplied candidates (a candidate number refers to that displayed ordering).
Never auto-select a product on the user's behalf during clarification.
Keep query, quantity, department_name, and memo in their named top-level fields;
keep budget_limit in constraints. constraints.specifications
contains only explicitly requested technical product properties, with string
keys and string values. Never put quantity, memo, category, or request metadata
in specifications; never add requirements the user did not state.
For ExecutionPlan, plan catalog, code, and merge/validate in that order.
Call only catalog_search_agent and code_determination_agent. Each task argument must
be a validated Structured snapshot JSON. Never infer product codes, prices, account
codes, or department codes. Do not output chain-of-thought.
Treat the JSON payload supplied by the controller as the source of truth for the
current procurement. When previous_intake is null, do not reuse fields from an
older completed procurement found in conversation history.
"""


# Request-scoped identity supplied by the authenticated App Service boundary.
# It is deliberately not an OpenTelemetry attribute or baggage item.
authenticated_applicant_name: ContextVar[str | None] = ContextVar(
    "procurement_authenticated_applicant_name", default=None,
)


@dataclass(frozen=True)
class FoundryRuntimeSettings:
    project_endpoint: str
    parent_model: str
    catalog_agent_name: str = "catalog-search-agent"
    catalog_agent_version: str = "1"
    code_agent_name: str = "code-determination-agent"
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
            catalog_agent_name=os.getenv("PROCUREMENT_CATALOG_AGENT_NAME", "catalog-search-agent"),
            catalog_agent_version=os.getenv("PROCUREMENT_CATALOG_AGENT_VERSION", "1"),
            code_agent_name=os.getenv("PROCUREMENT_CODE_AGENT_NAME", "code-determination-agent"),
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
        attributes = current_request_attributes()
        test_case_id = attributes.get("test.case.id") or f"HOSTED-{session.session_id}-T{next_turn}"
        attributes.update({"test.case.id": test_case_id, "app.session.id.hash": sha256(session.session_id), "app.turn.number": next_turn})
        from opentelemetry import trace
        trace.get_current_span().set_attributes(attributes)
        token = request_correlation.set(attributes)
        try:
            result = await _execute_hosted_components(
                planner=self.planner, catalog_tool=self.catalog_tool, code_tool=self.code_tool,
                natural_request=self._latest_user_text(context), session=session,
                test_case_id=test_case_id, telemetry=self.telemetry,
                applicant_name=authenticated_applicant_name.get(),
            )
        finally:
            request_correlation.reset(token)
        result.trace["correlation"] = {**attributes, "framework_session_id_hash": sha256(session.session_id)}
        output = (
            result.model_dump_json()
            if attributes.get("app.client.contract") == "web-json-v1"
            else result.response_text
        )
        context.extend_instructions(
            self.source_id, f"{CONTROLLER_RESULT_START}{output}{CONTROLLER_RESULT_END}",
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
            ProgressMiddleware(),
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


def _response_model(response: Any, model_type: type[Any]) -> Any:
    value = getattr(response, "value", None)
    if isinstance(value, model_type):
        return value
    text = getattr(response, "text", "")
    return model_type.model_validate_json(text)


def _planner_format(model_type: type[Any]) -> dict[str, Any]:
    # OpenAI strict schemas reject the arbitrary specification keys. Keep the
    # Pydantic schema on the wire and validate the result with the same model.
    return {"type": "json_schema", "name": model_type.__name__,
            "schema": model_type.model_json_schema(), "strict": False}


def _with_response_text(result: ScenarioResult) -> ScenarioResult:
    labels = {"query": "商品", "quantity": "台数", "department_name": "所属部署",
              "memo": "メモ", "selected_product_code": "商品の選択"}
    missing = result.missing_fields
    if result.business_status == BusinessStatus.WAITING_USER:
        if "authenticated_applicant_name" in missing:
            text = "EasyAuthから申請者名を取得できませんでした。サインイン状態を確認してください。"
        elif missing == ["confirmation"]:
            text = "商品・台数・所属部署・メモを保存しました。内容を確認し、よければ「確定」と入力してください。"
        else:
            requested = "・".join(labels[name] for name in missing if name in labels)
            prefix = "商品候補を確認しました。" if result.candidates else "入力内容をAgentSessionへ保存しました。"
            text = f"{prefix} 次に{requested}を教えてください。"
    elif result.business_status == BusinessStatus.SUCCESS and result.draft:
        line = result.draft.lines[0]
        text = ("購買申請案を確定しました。\n"
                f"商品: {line.product_name}（{line.product_code}）\n台数: {line.quantity}\n"
                f"所属部署: {result.draft.department_name}\n合計: {result.draft.total}円\n"
                "このPoCでは提出・発注は行っていません。")
    else:
        text = {
            BusinessStatus.NOT_FOUND: "条件に合う商品または部署コードを確認できませんでした。入力を確認してください。",
            BusinessStatus.INVALID_INPUT: "入力内容を読み取れませんでした。商品・台数・所属部署・メモを確認してください。",
            BusinessStatus.VALIDATION_FAILED: "申請内容が検証条件を満たさないため、申請案は確定していません。",
            BusinessStatus.BLOCKED: "処理を継続できませんでした。実行情報のTrace IDから確認してください。",
        }.get(result.business_status, "処理結果を確認できませんでした。")
    result.response_text = text
    return result


def _intent(text: str, *, procurement_active: bool) -> str:
    normalized = re.sub(r"[\s、。！？!?]+", "", text).lower()
    if normalized in {"私は誰", "私は誰ですか", "わたしは誰", "whoami"}:
        return "identity"
    if procurement_active:
        return "procurement"
    if any(term in normalized for term in ("購入", "買いたい", "買って", "調達", "申請")):
        return "procurement"
    return "general"


def _conversation_result(
    *, session: AgentSession, state: Any, test_case_id: str,
    interaction_type: str, applicant_name: str | None,
) -> ScenarioResult:
    state.turn_number += 1
    state.test_case_id = test_case_id
    save_execution_state(session, state)
    if interaction_type == "identity":
        if applicant_name:
            text = (
                f"現在このWeb Appにサインインしている方の表示名は「{applicant_name}」です。"
                "この名前はEasyAuthの検証済みclaimから取得しており、Graph OBOは使用していません。"
            )
        else:
            text = (
                "Playgroundのサインイン利用者名はHosted Agentへ直接渡されません。"
                "本人確認にはOAuth Identity Passthrough対応MCPを介したGraph OBO接続が必要です。"
            )
        scenario_id = "IDENTITY"
    else:
        text = "こんにちは。何をお手伝いしましょうか。購入したい商品があれば、その内容を教えてください。"
        scenario_id = "CHAT"
    status = OperationStatus(
        business_status=BusinessStatus.SUCCESS,
        parse_status=ParseStatus.SUCCESS,
    )
    return ScenarioResult(
        scenario_id=scenario_id,
        interaction_type=interaction_type,
        test_case_id=test_case_id,
        technical_status=TechnicalStatus.SUCCESS,
        business_status=BusinessStatus.SUCCESS,
        status=status,
        response_text=text,
    )


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
    applicant_name: str | None = None,
) -> ScenarioResult:
    if session is None:
        raise ValueError("Framework AgentSession is required; implicit sessions are forbidden")
    try:
        state = load_execution_state(session, required=False)
    except SessionStateSchemaError:
        raw = session.state.get(EXECUTION_STATE_KEY)
        previous_turn = raw.get("turn_number", 0) if isinstance(raw, dict) else 0
        state = initialize_execution_state(session, test_case_id=test_case_id)
        state.turn_number = previous_turn if isinstance(previous_turn, int) and previous_turn >= 0 else 0
        state.warnings.append("session_state_reset_after_schema_change")
        save_execution_state(session, state)
    if state is None:
        state = initialize_execution_state(session, test_case_id=test_case_id)
    # A completed procurement remains available as evidence for its response,
    # then its Plan & Execute state is cleared at the start of the next turn.
    if state.plan is not None and state.plan.status.name == "COMPLETED":
        previous_turn = state.turn_number
        previous_applicant = state.applicant_name
        state = initialize_execution_state(session, test_case_id=test_case_id)
        state.turn_number = previous_turn
        state.applicant_name = previous_applicant
        save_execution_state(session, state)
    if applicant_name:
        state.applicant_name = applicant_name
        save_execution_state(session, state)
    interaction_type = _intent(
        natural_request,
        procurement_active=bool(state.intake or state.request or state.catalog_result),
    )
    if interaction_type != "procurement":
        return _conversation_result(
            session=session, state=state, test_case_id=test_case_id,
            interaction_type=interaction_type, applicant_name=applicant_name,
        )
    controller = ProcurementController(
        lambda payload: _invoke_remote_tool(catalog_tool, payload, session),
        lambda payload: _invoke_remote_tool(code_tool, payload, session),
        telemetry=telemetry,
    )
    try:
        publish('intake', 'started')
        state = load_execution_state(session)
        previous = state.intake or state.request
        candidates = state.catalog_result.candidates if state.catalog_result else []
        selected_from_button = next((
            candidate.product_code for candidate in candidates
            if re.fullmatch(
                rf"\s*商品コード\s+{re.escape(candidate.product_code)}\s+を選びます。?\s*",
                natural_request,
            )
        ), None)
        confirming = natural_request.strip() == "確定"
        if (selected_from_button or confirming) and state.intake is not None:
            intake = ProcurementIntake(
                request=state.intake,
                plan=state.plan or ExecutionPlan(),
                selected_product_code=selected_from_button or state.selected_product_code,
            )
        else:
            request_response = await planner.run(
                json.dumps({"user_message": natural_request,
                            "previous_intake": previous.model_dump(mode="json") if previous else None,
                            "candidates": [c.model_dump(mode="json") for c in candidates]}, ensure_ascii=False),
                session=session, tools=[],
                options={"response_format": _planner_format(ProcurementIntake), "tool_choice": "none"},
            )
            intake = _response_model(request_response, ProcurementIntake)
        publish('intake', 'completed')
        selected = intake.selected_product_code or state.selected_product_code
        if selected and selected not in {c.product_code for c in candidates}:
            raise ValueError("selection must come from the previous grounded candidates")
        # A changed search invalidates the previous selection; explicit selection keeps it.
        if previous and intake.request.query != previous.query and not intake.selected_product_code:
            selected = None
            state.catalog_result = None
        state.intake = intake.request
        state.selected_product_code = selected
        save_execution_state(session, state)
        request: ProcurementRequest | ProcurementIntakeRequest = intake.request
        complete = all((
            intake.request.query,
            intake.request.quantity,
            intake.request.department_name,
            intake.request.memo,
            state.applicant_name,
            selected,
        ))
        if confirming and complete:
            request = ProcurementRequest(
                request_id=f"{test_case_id}-T{state.turn_number + 1}",
                query=intake.request.query,
                quantity=intake.request.quantity,
                applicant_name=state.applicant_name,
                department_name=intake.request.department_name,
                memo=intake.request.memo,
                constraints=intake.request.constraints,
            )
    except (ValidationError, json.JSONDecodeError, ValueError):
        return _with_response_text(controller.invalid_intake_result(
            session=session, test_case_id=test_case_id,
            technical_status=TechnicalStatus.SUCCESS,
            business_status=BusinessStatus.INVALID_INPUT,
            parse_status=ParseStatus.SCHEMA_INVALID,
            reason_code="procurement_request_schema_invalid",
        ))
    except Exception as error:
        from opentelemetry import trace
        span = trace.get_current_span()
        span.set_attribute("error.type", type(error).__name__)
        cause = error.__cause__ or error
        status = getattr(cause, "status_code", None)
        if isinstance(status, int):
            span.set_attribute("error.http_status", status)
        return _with_response_text(controller.invalid_intake_result(
            session=session, test_case_id=test_case_id,
            technical_status=TechnicalStatus.ERROR,
            business_status=BusinessStatus.BLOCKED,
            parse_status=ParseStatus.NOT_RUN,
            reason_code="planner_intake_failed",
        ))
    result = await controller.execute(
        request, session=session, test_case_id=test_case_id, raw_plan=intake.plan,
        selected_product_code=selected,
    )
    return _with_response_text(result)
