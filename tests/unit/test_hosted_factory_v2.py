import json

from agent_framework import Agent, AgentSession, FunctionInvocationContext, InMemoryHistoryProvider
import pytest

from procurement_agent.framework import DeterministicChatClient, local_parent_handler
from procurement_agent.hosted import (
    FoundryRuntimeSettings, authenticated_applicant_name, build_hosted_bundle,
    _execute_hosted_components,
)
from procurement_agent.models import (
    BusinessStatus, CatalogCandidate, CatalogSearchInput, CatalogSearchResult,
    CodeDeterminationInput, CodeDeterminationResult, Evidence, ExecutionPlan,
    OperationStatus, ProcurementIntake, ProcurementRequest, ScenarioResult,
)
from procurement_agent.observability import TelemetryRecorder
from procurement_agent.plan import default_steps
from procurement_agent.session_state import initialize_execution_state
from procurement_agent.session_state import load_execution_state


def make_bundle():
    return build_hosted_bundle(
        FoundryRuntimeSettings("https://example.services.ai.azure.com/api/projects/synthetic", "gpt-synthetic"),
        parent_client=DeterministicChatClient(local_parent_handler),
    )


def test_single_hosted_parent_has_two_remote_foundry_proxy_tools():
    bundle = make_bundle()
    assert isinstance(bundle.parent, Agent)
    assert type(bundle.catalog_proxy).__name__ == "FoundryAgent"
    assert type(bundle.code_proxy).__name__ == "FoundryAgent"
    assert {bundle.catalog_tool.name, bundle.code_tool.name} == {"catalog_search_agent", "code_determination_agent"}
    assert isinstance(bundle.history_provider, InMemoryHistoryProvider)
    assert bundle.history_provider.source_id == "procurement-history"
    assert bundle.history_provider.load_messages is True
    assert bundle.parent.additional_properties["child_implementation_location"] == "Foundry Agent Service"
    assert bundle.parent.additional_properties["propagate_child_session"] is False
    assert bundle.telemetry.uses_global_provider is True


@pytest.mark.anyio
async def test_as_tool_does_not_propagate_parent_session():
    bundle = make_bundle()
    calls = []
    class FakeStream:
        async def get_final_response(self):
            return type("Response", (), {"text": "ok", "user_input_requests": []})()
    def fake_run(*args, **kwargs):
        calls.append(kwargs)
        return FakeStream()
    bundle.catalog_proxy.run = fake_run
    parent_session = AgentSession()
    initialize_execution_state(parent_session)
    context = FunctionInvocationContext(
        function=bundle.catalog_tool,
        arguments={"task": '{"query":"synthetic"}'},
        session=parent_session,
    )
    await bundle.catalog_tool.invoke(arguments={"task": '{"query":"synthetic"}'}, context=context)
    assert len(calls) == 1
    assert calls[0].get("session") is None


@pytest.mark.anyio
async def test_hosted_turn_extracts_request_and_plan_in_one_model_call(valid_request):
    def planner(messages, options):
        response_format = options.get("response_format")
        assert response_format["strict"] is False
        if response_format["name"] == "ProcurementIntake":
            assert response_format["schema"] == ProcurementIntake.model_json_schema()
            request = json.loads(messages[-1].text)
            if "詳細" not in request["user_message"]:
                intake = {"query": valid_request.query}
            else:
                intake = {
                    "query": valid_request.query,
                    "quantity": valid_request.quantity,
                    "department_name": valid_request.department_name,
                    "memo": valid_request.memo,
                    "constraints": valid_request.constraints.model_dump(mode="json"),
                }
            return ProcurementIntake(request=intake,
                                     plan=ExecutionPlan(plan_id="model-plan", steps=default_steps()))
        raise AssertionError(response_format)

    client = DeterministicChatClient(planner)
    bundle = build_hosted_bundle(
        FoundryRuntimeSettings("https://example.services.ai.azure.com/api/projects/synthetic", "gpt-synthetic"),
        parent_client=client,
    )
    child_sessions = []
    class FakeStream:
        def __init__(self, text): self.text = text
        async def get_final_response(self):
            return type("Response", (), {"text": self.text, "user_input_requests": []})()

    def catalog_run(task, **kwargs):
        child_sessions.append(kwargs.get("session"))
        payload = CatalogSearchInput.model_validate_json(task)
        result = CatalogSearchResult(
            correlation=payload.correlation,
            status=OperationStatus(business_status=BusinessStatus.SUCCESS, mcp_status="SUCCESS", search_status="SUCCESS", parse_status="SUCCESS"),
            candidates=[CatalogCandidate(product_code="LAPTOP-DEV-14", product_name="開発用ノートPC 14インチ（架空商品）", category="laptop", unit_price="180000", specifications={"memory": "32GB"}, evidence_id="evidence:catalog:LAPTOP-DEV-14")],
            selected_product_code="LAPTOP-DEV-14",
            evidence=[Evidence(evidence_id="evidence:catalog:LAPTOP-DEV-14", index_name="procurement-catalog-v1", document_id="catalog-LAPTOP-DEV-14", source_version="2026-09-01.1", record_type="product", record_key="LAPTOP-DEV-14")],
        )
        return FakeStream(result.model_dump_json())

    def code_run(task, **kwargs):
        child_sessions.append(kwargs.get("session"))
        payload = CodeDeterminationInput.model_validate_json(task)
        result = CodeDeterminationResult(
            correlation=payload.correlation,
            status=OperationStatus(business_status=BusinessStatus.SUCCESS, mcp_status="SUCCESS", search_status="SUCCESS", parse_status="SUCCESS"),
            account_code="7210-EQUIPMENT", account_name="情報機器備品（架空科目）",
            department_code="DPT-DEV", department_name="開発部（架空部署）",
            evidence=[
                Evidence(evidence_id="evidence:account", index_name="procurement-code-master-v1", document_id="account-7210-EQUIPMENT-laptop", source_version="2026-09-01.1", record_type="account_code", record_key="7210-EQUIPMENT"),
                Evidence(evidence_id="evidence:department", index_name="procurement-code-master-v1", document_id="department-DPT-DEV", source_version="2026-09-01.1", record_type="department", record_key="DPT-DEV"),
            ],
        )
        return FakeStream(result.model_dump_json())

    bundle.catalog_proxy.run = catalog_run
    bundle.code_proxy.run = code_run
    session = AgentSession()
    args = dict(planner=bundle.planner, catalog_tool=bundle.catalog_tool, code_tool=bundle.code_tool,
                telemetry=bundle.telemetry, session=session, test_case_id="HOSTED-E2E",
                applicant_name="架空 太郎")
    assert (await _execute_hosted_components(**args, natural_request="開発用ノートPCを申請")).business_status == BusinessStatus.WAITING_USER
    assert (await _execute_hosted_components(**args, natural_request="商品コード LAPTOP-DEV-14 を選びます。")).business_status == BusinessStatus.WAITING_USER
    assert (await _execute_hosted_components(**args, natural_request="詳細を入力")).missing_fields == ["confirmation"]
    result = await _execute_hosted_components(**args, natural_request="確定")
    assert result.business_status == BusinessStatus.SUCCESS
    assert [call["response_format"] for call in client.calls] == ["ProcurementIntake", "ProcurementIntake"]
    assert child_sessions == [None, None, None]

    exposed_session = AgentSession()
    token = authenticated_applicant_name.set("架空 太郎")
    try:
        for message in ("開発用ノートPCを申請", "商品コード LAPTOP-DEV-14 を選びます。", "詳細を入力"):
            response = await bundle.parent.run(message, session=exposed_session)
            assert ScenarioResult.model_validate_json(response.text).business_status == BusinessStatus.WAITING_USER
        response = await bundle.parent.run("確定", session=exposed_session)
    finally:
        authenticated_applicant_name.reset(token)
    exposed_result = ScenarioResult.model_validate_json(response.text)
    assert exposed_result.business_status == BusinessStatus.SUCCESS
    exposed_state = load_execution_state(exposed_session)
    assert exposed_state.plan.status.name == "COMPLETED"
    assert [item.tool_name for item in exposed_state.governance_decisions] == [
        "catalog_search_agent", "catalog_search_agent", "code_determination_agent",
    ]
    assert [call["response_format"] for call in client.calls] == ["ProcurementIntake"] * 4
    assert child_sessions == [None] * 6
    assert load_execution_state(exposed_session).turn_number == 4


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("planner_value", "technical_status", "business_status", "reason_code"),
    [
        ({"query": "missing required fields"}, "SUCCESS", "INVALID_INPUT", "procurement_request_schema_invalid"),
        (RuntimeError("synthetic planner failure"), "ERROR", "BLOCKED", "planner_intake_failed"),
    ],
)
async def test_invalid_planner_intake_returns_terminal_machine_result(
    planner_value, technical_status, business_status, reason_code, monkeypatch,
):
    def planner(_messages, options):
        if options["response_format"]["name"] == "ProcurementIntake":
            if isinstance(planner_value, Exception):
                raise planner_value
            return planner_value
        raise AssertionError("ExecutionPlan must not run after invalid intake")

    monkeypatch.setattr(TelemetryRecorder, "for_hosted_runtime", lambda: TelemetryRecorder())
    bundle = build_hosted_bundle(
        FoundryRuntimeSettings(
            "https://example.services.ai.azure.com/api/projects/synthetic",
            "gpt-synthetic",
        ),
        parent_client=DeterministicChatClient(planner),
    )
    session = AgentSession()
    response = await bundle.parent.run("不完全な依頼", session=session)
    result = ScenarioResult.model_validate_json(response.text)

    assert result.scenario_id == "S4"
    assert result.technical_status == technical_status
    assert result.business_status == business_status
    assert result.status.reason_code == reason_code
    state = load_execution_state(session)
    assert state.plan.status.name == "BLOCKED"
    assert state.plan.steps[0].status.name == "BLOCKED"
    assert state.last_machine_response["reason_code"] == reason_code
    assert state.last_machine_response["outer_business_status"] == business_status
    assert any(
        span.name == "response.generate"
        and span.attributes["reason.code"] == reason_code
        for span in bundle.telemetry.finished_spans()
    )
