"""OAuth wrapper with real HTTPX/SSE handling against an in-memory upstream."""
import asyncio
import base64
import hashlib
import importlib
import json
from pathlib import Path
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


def principal(oid="synthetic-user"):
    return base64.b64encode(json.dumps({"claims": [
        {"typ": "tid", "val": "synthetic-tenant"}, {"typ": "oid", "val": oid},
    ]}).encode()).decode()


@pytest.fixture
def web(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2] / "src/webapp-foundry-oauth/backend"))
    server = importlib.import_module("server")
    flow = importlib.import_module("procurement_flow")
    telemetry = importlib.import_module("telemetry")
    server._conversations.clear()
    server._jobs.clear()
    server.app.middleware_stack = None
    exporter, provider = InMemorySpanExporter(), TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry, "TracerProvider", lambda **_: provider)
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    for key, value in {
        "PROJECT_ENDPOINT": "https://gateway.test/foundry/proj-default",
        "AGENT_NAME": "procurement-parent-agent", "WEB_APP_URL": "https://web.test",
        "IDENTITY_LOOKUP_ENABLED": "true", "FOUNDRY_USER_AUTH_MODE": "refresh_token",
    }.items():
        monkeypatch.setenv(key, value)
    calls, modes, options = [], [], {"mode": "success", "release": False}

    async def headers(request, auth_mode="managed_identity"):
        modes.append((auth_mode, server._get_request_user(request)["id"]))
        return {"Authorization": "Bearer TEST-" + auth_mode}

    monkeypatch.setattr(server, "_build_outbound_headers", headers)

    async def upstream(request):
        body = json.loads(request.content)
        calls.append({"path": request.url.path, "body": body, "headers": dict(request.headers)})
        if request.url.path.endswith("/conversations"):
            return httpx.Response(200, json={"id": "conv_" + str(len(calls))})
        mode, output = options["mode"], []
        rid = "resp_procurement_" + str(len(calls))
        if mode == "hold" and body["metadata"]["app.identity.lookup"] == "true":
            while not options["release"]:
                await asyncio.sleep(.01)
        if mode == "http_error":
            return httpx.Response(401, text="SECRET upstream error")
        if mode in {"consent", "approval"} and not options.get("consented") and body["metadata"]["app.identity.lookup"] == "true":
            output = ([{"type": "oauth_consent_request", "consent_link": "https://consent.test/login?state=SECRET"}]
                      if mode == "consent" else [{"type": "mcp_approval_request", "id": "approval_1",
                          "server_label": "whoami_func", "name": "whoami", "arguments": "{}"}])
        else:
            output = [{"type": "message", "content": [{"type": "output_text", "text": "購買支援の応答"}]}]
        events = [{"type": "response.created", "response": {"id": rid}}]
        events += [{"type": "response.output_item.done", "item": item} for item in output]
        terminal = "response.incomplete" if output[0]["type"] == "oauth_consent_request" else "response.completed"
        events += [{"type": terminal, "response": {"id": rid, "output": output}}]
        content = "".join("data: " + json.dumps(event) + "\n\n" for event in events) + "data: [DONE]\n\n"
        return httpx.Response(200, content=content, headers={"Content-Type": "text/event-stream"})

    real_client = telemetry.http_client
    with TestClient(server.app, base_url="https://web.test") as client:
        monkeypatch.setattr(telemetry, "http_client", lambda **kw: real_client(transport=httpx.MockTransport(upstream), **kw))
        client.headers["x-ms-client-principal"] = principal()
        yield client, server, flow, calls, modes, exporter, options


def finish(client, response):
    assert response.status_code == 202, response.text
    job_id = response.json()["jobId"]
    for _ in range(200):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"completed", "failed", "cancelled", "consent_required", "approval_required"}:
            return job
        time.sleep(.01)
    raise AssertionError("job did not finish")


def start(client, **kwargs):
    return client.post("/api/chat", json={"conversationId": "web_1", "userMessage": "名刺を購入したい", **kwargs})


def test_single_target_delegated_request_and_safe_telemetry(web):
    client, _, _, calls, modes, exporter, _ = web
    job = finish(client, start(client))
    assert job["status"] == "completed"
    assert modes == [("refresh_token", "synthetic-user")]
    assert len(calls) == 2 and all("/foundry/proj-default/agents/procurement-parent-agent/" in c["path"] for c in calls)
    body = calls[-1]["body"]
    assert body["metadata"]["app.identity.lookup"] == "true"
    assert "app.authenticated.display_name" not in body["metadata"]
    assert "previous_response_id" not in body
    span_data = str([(dict(s.attributes), s.events) for s in exporter.get_finished_spans()])
    for value in ("synthetic-user", "PRIVATE", "Bearer", "SECRET"):
        assert value not in span_data


def test_skip_keeps_same_principal_and_conversation(web):
    client, _, _, calls, modes, _, _ = web
    finish(client, start(client))
    conversation = calls[-1]["body"]["conversation"]
    job = finish(client, start(client, lookupApplicant=False))
    assert job["status"] == "completed" and len(calls) == 3
    assert calls[-1]["body"]["conversation"] == conversation
    assert calls[-1]["body"]["metadata"]["app.identity.lookup"] == "false"
    assert modes[-1][0] == "refresh_token"


@pytest.mark.parametrize("mode", ["consent", "approval"])
def test_continue_replays_original_message_on_same_conversation(web, mode):
    client, _, _, calls, _, _, options = web
    options["mode"] = mode
    pending = finish(client, start(client))
    assert pending["status"] in {"consent_required", "approval_required"}
    assert len(calls) == 2 and start(client).status_code == 409
    options["consented"] = True
    resumed = finish(client, client.post("/api/continue", json={"conversationId": "web_1"}))
    assert resumed["status"] == "completed"
    assert calls[-1]["body"]["conversation"] == calls[1]["body"]["conversation"]
    assert "previous_response_id" not in calls[-1]["body"]
    assert calls[-1]["body"]["input"][-1]["content"][0]["text"] == "名刺を購入したい"
    assert client.post("/api/continue", json={"conversationId": "web_1"}).status_code == 409


def test_pending_lookup_can_be_skipped(web):
    client, _, _, calls, _, _, options = web
    options["mode"] = "consent"
    finish(client, start(client))
    done = finish(client, client.post("/api/continue", json={"conversationId": "web_1", "skipIdentity": True}))
    assert done["status"] == "completed" and len(calls) == 3
    assert calls[-1]["body"]["metadata"]["app.identity.lookup"] == "false"


def test_concurrent_turn_rejected_and_cancel_releases_state(web):
    client, _, _, _, _, _, options = web
    options["mode"] = "hold"
    first = start(client)
    assert first.status_code == 202
    assert start(client).status_code == 409
    assert client.delete("/api/conversations/web_1").status_code == 409
    cancelled = client.post(f"/api/jobs/{first.json()['jobId']}/cancel")
    assert cancelled.json()["status"] == "cancelled"
    assert client.delete("/api/conversations/web_1").status_code == 200
    finish(client, start(client, lookupApplicant=False))


def test_identity_state_is_owner_scoped_and_browser_cannot_supply_name(web):
    client, _, _, _, _, _, _ = web
    first = finish(client, start(client, lookupApplicant=False))
    client.headers["x-ms-client-principal"] = principal("other-user")
    assert client.get(f"/api/jobs/{first['jobId']}").status_code == 404
    assert client.get("/api/conversations/web_1/state").json()["hasPreviousResponse"] is False
    assert start(client, applicantName="forged").status_code == 422
    assert client.post("/api/chat", json={"conversationId": "a", "userMessage": "test"}, headers={"Origin": "https://attacker.test"}).status_code == 403


def test_browser_trace_is_discarded_and_real_httpx_injects_context(web):
    client, _, _, calls, _, exporter, _ = web
    client.headers.update({"traceparent": "00-" + "a" * 32 + "-" + "b" * 16 + "-01", "baggage": "user.id=forged,email=PRIVATE"})
    job = finish(client, start(client, lookupApplicant=False))
    assert job["traceId"] not in {"a" * 32, "0" * 32}
    user_id = hashlib.sha256(b"synthetic-tenant:synthetic-user").hexdigest()
    for call in calls:
        assert call["headers"]["traceparent"].split("-")[1] == job["traceId"]
        assert call["headers"]["baggage"] == "user.id=" + user_id
    job_span = next(s for s in exporter.get_finished_spans() if s.name == "web.chat.job")
    assert job_span.parent is not None and job_span.attributes["user.id"] == user_id


@pytest.mark.parametrize("bad_claim", [None, ("oid", "other-user"), ("tid", "other-tenant"),
                                           ("scp", ""), ("aud", "https://graph.microsoft.com")])
def test_delegated_token_subject_audience_and_user_scope(web, bad_claim):
    from fastapi import HTTPException, Request
    _, server, _, _, _, _, _ = web
    claims = {"aud": "https://ai.azure.com", "scp": "user_impersonation", "oid": "synthetic-user", "tid": "synthetic-tenant"}
    if bad_claim:
        claims[bad_claim[0]] = bad_claim[1]
    token = "header." + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=") + ".signature"
    request = Request({"type": "http", "headers": [(b"x-ms-client-principal", principal().encode())]})
    if bad_claim:
        with pytest.raises(HTTPException):
            server._validate_delegated_subject(token, request)
    else:
        server._validate_delegated_subject(token, request)


def test_token_failure_does_not_change_principal_or_leak_error(web, monkeypatch):
    from fastapi import HTTPException
    client, server, _, calls, _, _, _ = web
    original = server._build_outbound_headers

    async def headers(request, auth_mode):
        if auth_mode != "managed_identity":
            raise HTTPException(401, "PRIVATE token failure")
        return await original(request, auth_mode)

    monkeypatch.setattr(server, "_build_outbound_headers", headers)
    job = finish(client, start(client))
    assert job["status"] == "failed"
    assert calls == [] and "PRIVATE" not in json.dumps(job)
