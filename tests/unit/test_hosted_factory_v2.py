from agent_framework import Agent, AgentSession, FunctionInvocationContext, InMemoryHistoryProvider
import pytest

from procurement_agent.framework import DeterministicChatClient, local_parent_handler
from procurement_agent.hosted import FoundryRuntimeSettings, build_hosted_bundle, execute_hosted_turn
from procurement_agent.models import (
    BusinessStatus, CatalogCandidate, CatalogSearchInput, CatalogSearchResult,
    CodeDeterminationInput, CodeDeterminationResult, Evidence, ExecutionPlan,
    OperationStatus, ProcurementRequest,
)
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


@pytest.mark.anyio
async def test_direct_hosted_parent_initializes_new_framework_session_before_chat():
    bundle = make_bundle()
    session = AgentSession()
    response = await bundle.parent.run("synthetic request", session=session, tools=[])
    assert response.text
    assert load_execution_state(session).schema_version == "2.0"


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
async def test_hosted_turn_uses_request_and_execution_plan_response_formats(valid_request):
    def planner(messages, options):
        response_format = options.get("response_format")
        if response_format is ProcurementRequest:
            return valid_request
        if response_format is ExecutionPlan:
            return ExecutionPlan(plan_id="model-plan", steps=default_steps())
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
            candidates=[CatalogCandidate(product_code="LAPTOP-DEV-14", product_name="開発用ノートPC 14インチ（架空商品）", category="laptop", unit_price="180000", evidence_id="evidence:catalog:LAPTOP-DEV-14")],
            selected_product_code="LAPTOP-DEV-14",
            evidence=[Evidence(evidence_id="evidence:catalog:LAPTOP-DEV-14", index_name="procurement-catalog-v1", document_id="catalog-LAPTOP-DEV-14", source_version="2026-09-01.1")],
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
                Evidence(evidence_id="evidence:account", index_name="procurement-code-master-v1", document_id="account-7210-EQUIPMENT-laptop", source_version="2026-09-01.1"),
                Evidence(evidence_id="evidence:department", index_name="procurement-code-master-v1", document_id="department-DPT-DEV", source_version="2026-09-01.1"),
            ],
        )
        return FakeStream(result.model_dump_json())

    bundle.catalog_proxy.run = catalog_run
    bundle.code_proxy.run = code_run
    result = await execute_hosted_turn(bundle, "開発用ノートPCを2台申請", session=AgentSession(), test_case_id="HOSTED-E2E")
    assert result.business_status == BusinessStatus.SUCCESS
    assert [call["response_format"] for call in client.calls] == ["ProcurementRequest", "ExecutionPlan"]
    assert child_sessions == [None, None]
