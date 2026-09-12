import asyncio
import json
from types import SimpleNamespace

import pytest
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData
from agent_framework.exceptions import AgentFrameworkException
from agent_framework import FunctionTool
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.ai.agentserver.responses._response_context import ResponseContext
from azure.ai.agentserver.responses.models.runtime import ResponseModeFlags

from procurement_agent.identity import build_identity_tool, invoke_identity, identity_result, parse_whoami_result, verified_name
from procurement_agent.observability import request_correlation, sha256
from procurement_agent.hosted_app import ProcurementResponsesHostServer


@pytest.fixture
def identity(monkeypatch):
    monkeypatch.setenv("PROCUREMENT_IDENTITY_TOOLBOX_ENDPOINT", "https://foundry.test/toolboxes/identity/mcp")
    monkeypatch.setenv("PROCUREMENT_IDENTITY_TENANT_ID", "tenant")
    seen, options = [], {"mode": "success"}
    class Toolbox:
        def __init__(self, *args, **kwargs):
            seen.append("new")
            async def whoami():
                return await self.call_tool("whoami_func___whoami")
            self.functions = [FunctionTool(func=whoami, name="whoami_func___whoami")]
        async def __aenter__(self):
            if options["mode"] == "consent":
                error = McpError(ErrorData(code=-32006, message=json.dumps({"errors": [{"name": "whoami_func", "type": "mcp",
                    "error": {"code": "CONSENT_REQUIRED", "message": "https://consent.test/authorize"}}]})))
                raise AgentFrameworkException("MCP connect", error)
            return self
        async def __aexit__(self, *args): pass
        async def call_tool(self, name):
            seen.append(name)
            await asyncio.sleep(0)
            if options["mode"] == "call_consent":
                error = McpError(ErrorData(code=-32006,
                    message="https://logic-apis-eastus2.consent.azure-apim.net/login?data=SECRET"))
                raise AgentFrameworkException("MCP call", error)
            if options["mode"] == "failure": raise ValueError("SECRET upstream failure")
            return {"tool": "whoami", "auth_mode": "obo", "user": {
                "subjectHash": sha256("tenant:user"), "displayName": "架空 OBO"}}
    correlation = request_correlation.set({"user.id": sha256("tenant:user")})
    result = identity_result.set(identity_result.get().__class__())
    yield build_identity_tool(None, toolbox_factory=Toolbox), seen, options
    request_correlation.reset(correlation)
    identity_result.reset(result)


@pytest.mark.anyio
async def test_identity_agent_tool_uses_verified_graph_and_clears_on_skip(identity):
    tool, seen, _ = identity
    assert tool.name == "obo_identity_agent"
    assert (await invoke_identity(tool)).name == "架空 OBO"
    assert seen == ["new", "whoami_func___whoami"]
    result = await invoke_identity(None)
    assert result.status == "UNAVAILABLE" and result.name is None
    assert len(seen) == 2


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["failure"])
async def test_identity_failure_never_reuses_name(identity, mode):
    tool, _, options = identity
    assert (await invoke_identity(tool)).name
    options["mode"] = mode
    result = await invoke_identity(tool)
    assert result.status == "FAILED" and result.name is None


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["consent", "call_consent"])
async def test_native_consent_pauses_before_controller_and_retries(identity, monkeypatch, mode):
    tool, _, options = identity
    options["mode"] = mode
    parent_calls = []
    async def parent(self, request, context, cancellation):
        parent_calls.append("called")
        yield {"type": "synthetic.parent"}
    monkeypatch.setattr(ResponsesHostServer, "_handle_response", parent)
    # Exercise the real SDK event emitter and our protocol adapter without
    # starting storage/providers or contacting Azure.
    server = object.__new__(ProcurementResponsesHostServer)
    server.identity_tool = tool
    context = ResponseContext(response_id="resp_test", mode_flags=ResponseModeFlags(stream=True, store=False, background=False))
    events = [e async for e in server._handle_response({"input": "私は誰ですか"}, context, asyncio.Event())]
    assert not parent_calls
    assert any(e["type"] == "response.output_item.done" and e["item"]["type"] == "oauth_consent_request" for e in events)
    assert events[-1]["type"] == "response.incomplete"
    options["mode"] = "success"
    events = [e async for e in server._handle_response({"input": "私は誰ですか"}, context, asyncio.Event())]
    assert events[-1]["type"] == "response.completed"
    assert any(e.get("delta") == "Graph OBOで取得したあなたの表示名は「架空 OBO」です。" for e in events)
    assert not parent_calls
    assert identity_result.get().name is None
    # 名前取得後も通常購買はOBOを呼ばず、親へそのまま委譲する。
    count = len(identity[1])
    assert [e async for e in server._handle_response({"input": "ノートPCを購入したい"}, context, asyncio.Event())] == [{"type": "synthetic.parent"}]
    assert parent_calls == ["called"] and len(identity[1]) == count



@pytest.mark.parametrize("wrapped", [False, True])
def test_real_mcp_duplicate_structured_and_text_result(wrapped):
    from mcp.types import CallToolResult, TextContent
    value = {"tool": "whoami", "auth_mode": "obo", "user": {
        "subjectHash": sha256("tenant:user"), "displayName": "架空 OBO"}}
    result = CallToolResult(content=[TextContent(type="text", text=json.dumps(value))],
                            structuredContent={"result": value} if wrapped else value)
    assert verified_name(parse_whoami_result(result)) == "架空 OBO"


@pytest.mark.anyio
@pytest.mark.parametrize("remote_name", ["whoami_func___whoami", "whoami_func.whoami"])
async def test_sdk_discovery_preserves_remote_name_and_call_metadata(identity, remote_name):
    from agent_framework_foundry_hosting import FoundryToolbox
    from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool
    calls = []
    class Session:
        async def list_tools(self, **kwargs):
            return ListToolsResult(tools=[Tool(name=remote_name,
                inputSchema={"type": "object", "properties": {}},
                _meta={"tool_configuration": {"require_approval": "never"}})])
        async def call_tool(self, name, *, arguments, meta):
            calls.append((name, arguments, meta))
            value = {"tool": "whoami", "auth_mode": "obo", "user": {
                "subjectHash": sha256("tenant:user"), "displayName": "架空 OBO"}}
            return CallToolResult(content=[TextContent(type="text", text=json.dumps(value))],
                                  structuredContent=value)
    class Toolbox(FoundryToolbox):
        async def __aenter__(self):
            self.session = Session()
            self._supports_tools = True
            self._ping_available = False
            await self.load_tools()
            return self
        async def __aexit__(self, *args):
            await self._httpx_client.aclose()
    result = await invoke_identity(build_identity_tool(None, toolbox_factory=Toolbox))
    assert result.status == "SUCCESS" and result.name == "架空 OBO"
    assert len(calls) == 1
    assert calls[0][0:2] == (remote_name, {})
    assert calls[0][2]["tool_configuration"] == {"require_approval": "never"}


def test_sdk_mcp_consent_exception_is_redacted_before_export(monkeypatch):
    from agent_framework import observability as framework_otel
    from procurement_agent.observability import McpPrivacyProcessor
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    provider, exporter = TracerProvider(), InMemorySpanExporter()
    # Same order as the hosted runtime: exporter first, privacy hook later.
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    provider.add_span_processor(McpPrivacyProcessor())
    monkeypatch.setattr(framework_otel, "get_tracer", lambda: provider.get_tracer("agent_framework"))
    monkeypatch.setattr(framework_otel, "OBSERVABILITY_SETTINGS", SimpleNamespace(ENABLED=True))
    with pytest.raises(McpError):
        with framework_otel.create_mcp_client_span("tools/list"):
            raise McpError(ErrorData(code=-32006, message="CONSENT_REQUIRED https://consent.test/?state=SECRET"))
    spans = exporter.get_finished_spans()
    assert len(spans) == 1 and spans[0].status.status_code.name == "ERROR"
    assert "SECRET" not in str(spans[0].to_json()) and "consent.test" not in str(spans[0].to_json())
    assert spans[0].events[0].attributes["exception.type"]


@pytest.mark.parametrize("url,accepted", [
    ("https://logic-apis-eastus2.consent.azure-apim.net/login?data=SECRET", True),
    ("http://logic-apis-eastus2.consent.azure-apim.net/login?data=SECRET", False),
    ("https://attacker.example/login?data=SECRET", False),
    ("https://logic-apis-eastus2.consent.azure-apim.net.attacker.example/login?data=SECRET", False),
])
def test_call_consent_url_is_bounded_and_not_logged(caplog, url, accepted):
    from procurement_agent.identity import _consent
    error = McpError(ErrorData(code=-32006, message=url))
    for wrapper in (error, AgentFrameworkException("MCP call", error)):
        result = _consent(wrapper)
        assert bool(result) == accepted
        if accepted:
            assert result[0].consent_url == url and result[0].name == "whoami_func"
    assert "SECRET" not in caplog.text


@pytest.mark.parametrize("value", [
    {"tool": "whoami", "auth_mode": "anonymous", "user": {"displayName": "架空"}},
    {"tool": "whoami", "auth_mode": "obo", "error": "denied"},
    {"tool": "whoami", "auth_mode": "obo", "user": {"displayName": "bad\nname"}},
])
def test_only_successful_obo_name_is_accepted(value):
    with pytest.raises(ValueError):
        verified_name(value)


@pytest.mark.anyio
async def test_identity_observation_does_not_require_or_trust_user_metadata(identity):
    tool, _, _ = identity
    token = request_correlation.set({"user.id": "different@example.invalid"})
    try:
        assert (await invoke_identity(tool)).status == "SUCCESS"
    finally:
        request_correlation.reset(token)


@pytest.mark.parametrize("value,expected", [
    ("私は誰ですか", True), ("OBOフローを実行して", True),
    ([{"role": "user", "content": [{"type": "input_text", "text": "Who am I?"}]}], True),
    ([{"role": "assistant", "content": "私は誰ですか"}], False),
    ([{"role": "user", "content": "私は誰ですか"}, {"role": "user", "content": "ノートPCを購入"}], False),
    ("名前は誰々です。ノートPCを購入", False),
])
def test_obo_route_uses_latest_explicit_input(value, expected):
    from procurement_agent.hosted_app import _latest_input_text
    from procurement_agent.identity import is_identity_request
    assert is_identity_request(_latest_input_text({"input": value, "metadata": {"app.identity.lookup": "true"}})) is expected


@pytest.mark.anyio
async def test_parallel_obo_results_are_request_scoped():
    from procurement_agent.identity import IdentityResult
    async def lookup(task):
        identity_result.set(IdentityResult("SUCCESS", str(asyncio.current_task().get_name())))
        await asyncio.sleep(0)
    tool = FunctionTool(func=lookup, name="test_identity")
    tasks = [asyncio.create_task(invoke_identity(tool), name=name) for name in ("A", "B")]
    assert [result.name for result in await asyncio.gather(*tasks)] == ["A", "B"]
    assert identity_result.get().name is None


@pytest.mark.anyio
async def test_obo_cancellation_stops_pending_tool(monkeypatch):
    entered, stopped, cancel = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def lookup(tool):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    monkeypatch.setattr("procurement_agent.hosted_app.invoke_identity", lookup)
    server = object.__new__(ProcurementResponsesHostServer)
    server.identity_tool = object()
    context = ResponseContext(response_id="resp_cancel", mode_flags=ResponseModeFlags(stream=True, store=False, background=False))
    async def run():
        return [e async for e in server._handle_response({"input": "私は誰ですか"}, context, cancel)]
    task = asyncio.create_task(run())
    await asyncio.wait_for(entered.wait(), 1)
    cancel.set()
    events = await asyncio.wait_for(task, 1)
    assert stopped.is_set()
    assert not any(e["type"] == "response.completed" for e in events)
