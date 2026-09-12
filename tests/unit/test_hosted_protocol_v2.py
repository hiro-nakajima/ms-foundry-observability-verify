import httpx
import pytest
from agent_framework import AgentSession, Message
from agent_framework_foundry_hosting import ResponsesHostServer
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from procurement_agent.framework import DeterministicChatClient, local_parent_handler
from procurement_agent.hosted import FoundryRuntimeSettings, build_hosted_bundle
from procurement_agent.hosted_app import _RequestCorrelationMiddleware
from procurement_agent.observability import current_request_attributes, request_correlation


@pytest.mark.anyio
async def test_hosted_server_keeps_framework_history_without_double_loading(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTSERVER_STATE_ROOT", str(tmp_path))
    bundle = build_hosted_bundle(
        FoundryRuntimeSettings("https://example.services.ai.azure.com/api/projects/synthetic", "synthetic"),
        parent_client=DeterministicChatClient(local_parent_handler),
    )
    # This is the SDK's actual constructor gate, not a mocked hosting adapter.
    with pytest.raises(RuntimeError, match="load_messages=True"):
        ResponsesHostServer(bundle.parent, configure_observability=None)
    bundle.history_provider.load_messages = False
    server = ResponsesHostServer(bundle.parent, configure_observability=None)
    assert server is not None
    assert sum(bool(p.load_messages) for p in bundle.parent.context_providers if hasattr(p, "load_messages")) == 1
    session = AgentSession()
    first = Message("user", "synthetic first turn", message_id="msg-first")
    second = Message("user", "synthetic second turn", message_id="msg-second")
    provider = bundle.history_provider
    await provider.save_messages(session.session_id, [first], state=session.state)
    await provider.save_messages(session.session_id, [first, second], state=session.state)
    restored = AgentSession.from_dict(session.to_dict())
    history = await provider.get_messages(restored.session_id, state=restored.state)
    assert [m.text for m in history] == [first.text, second.text]


@pytest.mark.anyio
async def test_hosted_request_metadata_is_allowlisted_and_request_scoped():
    async def endpoint(request: Request):
        await request.json()  # Middleware must leave the protocol body readable.
        return JSONResponse({"attributes": current_request_attributes(),
                             "applicant": None})

    app = Starlette(routes=[Route("/responses", endpoint, methods=["POST"])])
    app.add_middleware(_RequestCorrelationMiddleware)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/responses", json={"conversation": {"id": "conv_synthetic"}, "metadata": {
            "test.case.id": "S1-synthetic", "app.turn.number": "2", "email": "must-not-record",
            "app.authenticated.display_name": "架空 利用者", "app.client.contract": "web-json-v1"}})
        result = response.json()
        assert result == {"attributes": {"gen_ai.conversation.id": "conv_synthetic",
            "test.case.id": "S1-synthetic", "app.web.turn.number": 2,
            "app.client.contract": "web-json-v1"}, "applicant": None}
        assert (await client.post("/responses", json={})).json() == {"attributes": {}, "applicant": None}
    assert request_correlation.get() == {}


@pytest.mark.anyio
async def test_identity_metadata_is_ignored():
    async def endpoint(request):
        return JSONResponse(current_request_attributes())
    app = Starlette(routes=[Route("/responses", endpoint, methods=["POST"])])
    app.add_middleware(_RequestCorrelationMiddleware)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://testserver") as client:
        response = await client.post("/responses", json={"metadata": {
            "app.authenticated.display_name": "架空 OBO", "app.identity.source": "graph_obo",
            "app.identity.lookup.status": "SUCCESS", "app.identity.lookup": "true",
            "app.user.id": "c" * 64, "app.web.trace_id": "d" * 32}})
        assert response.json() == {"app.web.trace_id": "d" * 32}
        assert (await client.post("/responses", json={})).json() == {}


@pytest.mark.anyio
async def test_stage_b_metadata_requires_every_synthetic_gate(monkeypatch):
    async def endpoint(_request: Request):
        return JSONResponse(current_request_attributes())

    app = Starlette(routes=[Route("/responses", endpoint, methods=["POST"])])
    app.add_middleware(_RequestCorrelationMiddleware)
    transport = httpx.ASGITransport(app=app)
    metadata = {
        "test.case.id": "AZURE-CORE-S2-TV-02",
        "synthetic": "true",
        "app.validation.contract": "stage-b-v1",
        "app.validation.profile": "TV-02",
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert "app.validation.profile" not in (
            await client.post("/responses", json={"metadata": metadata})
        ).json()
        monkeypatch.setenv("PROCUREMENT_ENABLE_SYNTHETIC_INJECTIONS", "true")
        accepted = (await client.post("/responses", json={"metadata": metadata})).json()
        assert accepted["app.validation.contract"] == "stage-b-v1"
        assert accepted["app.validation.profile"] == "TV-02"
        boundary_metadata = {**metadata, "app.validation.profile": "S5-65536"}
        boundary = (await client.post(
            "/responses", json={"metadata": boundary_metadata},
        )).json()
        assert boundary["app.validation.profile"] == "S5-65536"

        for key, value in (
            ("synthetic", "false"),
            ("app.validation.contract", "other"),
            ("app.validation.profile", "SD-01"),
            ("app.validation.profile", "S5-1234"),
            ("test.case.id", "BROWSER-S2-TV-02"),
        ):
            rejected = {**metadata, key: value}
            actual = (await client.post("/responses", json={"metadata": rejected})).json()
            assert "app.validation.profile" not in actual


@pytest.mark.anyio
async def test_sdk_incoming_baggage_reaches_allowlisted_application_attributes():
    from azure.ai.agentserver.core._tracing import TraceContextMiddleware
    from opentelemetry import propagate
    from opentelemetry.baggage.propagation import W3CBaggagePropagator
    from opentelemetry.propagators.composite import CompositePropagator
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    async def endpoint(request):
        return JSONResponse(current_request_attributes())

    app = Starlette(routes=[Route("/responses", endpoint, methods=["POST"])])
    # Same middleware order as ResponsesHostServer + our correlation middleware.
    app.add_middleware(TraceContextMiddleware)
    app.add_middleware(_RequestCorrelationMiddleware)
    previous = propagate.get_global_textmap()
    propagate.set_global_textmap(CompositePropagator([TraceContextTextMapPropagator(), W3CBaggagePropagator()]))
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            result = (await client.post("/responses", json={}, headers={"baggage": "user.id=tester%40example.invalid,email=withheld"})).json()
            assert result == {"user.id": "tester@example.invalid"}
            assert (await client.post("/responses", json={}, headers={"baggage": "user.id=raw-oid"})).json() == {}
            assert (await client.post("/responses", json={})).json() == {}
    finally:
        propagate.set_global_textmap(previous)


def test_application_span_exception_does_not_export_message():
    from procurement_agent.observability import TelemetryRecorder
    recorder = TelemetryRecorder()
    with pytest.raises(ValueError):
        with recorder.span("plan.create"):
            raise ValueError("SECRET consent-url payload")
    span, = recorder.finished_spans()
    assert span.status.status_code.name == "ERROR"
    assert span.attributes["error.type"] == "ValueError"
    assert "SECRET" not in span.to_json()
    assert not span.events
