"""Real HTTP fixture: SDK + HTTPX instrumentation, not a mocked header injector."""
import base64
import hashlib
import importlib.util
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from azure.core.credentials import AccessToken
from fastapi.testclient import TestClient
from opentelemetry import propagate
from opentelemetry.baggage.propagation import W3CBaggagePropagator
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator


def _principal(oid="synthetic-object"):
    return base64.b64encode(json.dumps({"claims": [
        {"typ": "tid", "val": "synthetic-tenant"}, {"typ": "oid", "val": oid},
        {"typ": "name", "val": "架空 利用者"}]}).encode()).decode()


@pytest.fixture
def web(monkeypatch):
    spec = importlib.util.spec_from_file_location("procurement_web_test", Path(__file__).parents[2] /
        "src/webapp-foundry-oauth/backend/procurement.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls, conversations = [], {}
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    old_propagator = propagate.get_global_textmap()
    propagate.set_global_textmap(CompositePropagator([TraceContextTextMapPropagator(), W3CBaggagePropagator()]))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            self.handle_api()

        def do_POST(self):
            self.handle_api()

        def handle_api(self):
            body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or "{}")
            path = self.path.split("?", 1)[0]
            calls.append({"path": path, "body": body, "headers": dict(self.headers)})
            if path.endswith("/responses"):
                result = {"technical_status": "SUCCESS", "business_status": "SUCCESS", "status": {
                    "mcp_status": "SUCCESS", "search_status": "SUCCESS", "parse_status": "SUCCESS"},
                    "trace": {"secret": "MUST-NOT-DISPLAY", "correlation": {"framework_session_id_hash": "f" * 64}},
                    "draft": None, "response_text": "Hosted Agentの公開応答です。"}
                value = {"id": "resp_fixture", "object": "response", "created_at": 1, "model": "fixture", "status": "completed",
                    "output": [{"id": "msg_1", "type": "message", "role": "assistant", "status": "completed",
                                "content": [{"type": "output_text", "text": json.dumps(result), "annotations": []}]}]}
                if body.get('stream'):
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/event-stream')
                    self.end_headers()
                    progress = '{"step":"catalog","state":"started","message":"商品の検索・仕様照合：開始しました"}'
                    delta = '{"progress":[\n' + progress + '\n,' + progress + '\n'
                    events = [
                        {'type': 'response.output_text.delta', 'delta': delta, 'item_id': 'msg_1', 'output_index': 0, 'content_index': 0, 'sequence_number': 1},
                        {'type': 'response.completed', 'response': value, 'sequence_number': 2},
                    ]
                    for event in events:
                        self.wfile.write(('data: ' + json.dumps(event) + '\n\n').encode())
                        self.wfile.flush()
                    self.wfile.write(b'data: [DONE]\n\n')
                    return
            elif path.endswith("/conversations"):
                cid = "conv_" + str(len(conversations) + 1)
                value = {"id": cid, "object": "conversation", "created_at": 1, "metadata": body["metadata"]}
                conversations[cid] = value
            else:
                cid = path.rsplit("/", 1)[1]
                value = conversations[cid]
                if self.command == "POST":
                    value["metadata"] = body["metadata"]
            data = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    class Credential:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            await self.close()

        async def get_token(self, *scopes, **kwargs):
            assert scopes == ("https://ai.azure.com/.default",)
            return AccessToken("synthetic-test-token", int(time.time()) + 3600)

        async def close(self):
            pass

    # Exercise the deployed lifespan/client wiring, replacing only external identity/export.
    monkeypatch.setattr(module, "ManagedIdentityCredential", Credential)
    monkeypatch.setattr(module, "TracerProvider", lambda **_: provider)
    monkeypatch.setenv("PROJECT_ENDPOINT", f"http://127.0.0.1:{server.server_port}/project")
    monkeypatch.setenv("WEBUI_SESSION_SIGNING_KEY", "synthetic-key-for-fixture-only-123456")
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    monkeypatch.setenv("WEB_APP_URL", "https://web.test")
    try:
        with TestClient(module.app, base_url="https://web.test", headers={"x-ms-client-principal": _principal()}) as client:
            csrf = client.get("/api/state").json()["csrf"]
            client.headers.update({"Origin": "https://web.test", "x-csrf-token": csrf})
            yield client, module, calls, exporter, conversations
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        provider.shutdown()
        propagate.set_global_textmap(old_propagator)


def test_real_http_propagation_and_remote_conversation(web):
    client, module, calls, exporter, conversations = web
    attacker_trace = "a" * 32
    first = client.post("/api/chat", json={"message": "Synthetic procurement"}, headers={
        "traceparent": f"00-{attacker_trace}-{'b' * 16}-01", "baggage": "email=forbidden", "tracestate": "forged=value"})
    assert first.status_code == 200, first.text
    result = first.json()
    assert set(result["statuses"].values()) == {"SUCCESS"}
    assert result["traceId"] not in {attacker_trace, "0" * 32}
    assert result["parentSpanId"] is None
    assert result["frameworkSessionIdHash"] == "f" * 64
    spans = exporter.get_finished_spans()
    root = next(s for s in spans if format(s.context.span_id, "016x") == result["spanId"])
    assert root.parent is None
    outgoing = [c for c in calls if c["path"].endswith("/responses")][0]
    headers = {k.lower(): v for k, v in outgoing["headers"].items()}
    assert outgoing["path"].endswith("/agents/procurement-parent-agent/endpoint/protocols/openai/responses")
    assert headers["traceparent"].split("-")[1] == result["traceId"]
    dependency = next(s for s in spans if format(s.context.span_id, "016x") == headers["traceparent"].split("-")[2])
    assert dependency.parent.span_id == root.context.span_id
    assert dependency.attributes["app.propagation.traceparent_present"] is True
    assert dependency.attributes["app.propagation.traceparent_matches_span"] is True
    assert dependency.attributes["app.propagation.baggage_user_id_matches"] is True
    # Verify the real exporter mapping too: http.* custom attributes are dropped.
    from azure.monitor.opentelemetry.exporter.export.trace._exporter import _convert_span_to_envelope
    properties = _convert_span_to_envelope(dependency).data.base_data.properties
    for key in ("traceparent_present", "traceparent_matches_span", "baggage_user_id_matches"):
        assert properties[f"app.propagation.{key}"] == "True"
    user = hashlib.sha256(b"synthetic-tenant:synthetic-object").hexdigest()
    assert headers["baggage"] == "user.id=" + user
    assert "tracestate" not in headers
    assert root.attributes["user.id"] == user
    assert root.attributes["gen_ai.conversation.id"] == result["conversationId"]
    assert root.attributes["gen_ai.response.id"] == result["responseId"]
    assert outgoing["body"]["conversation"] == result["conversationId"]
    assert outgoing["body"]["metadata"]["app.authenticated.display_name"] == "架空 利用者"
    assert "previous_response_id" not in outgoing["body"]
    second = client.post("/api/chat", json={"message": "Continue"}).json()
    assert second["conversationId"] == result["conversationId"]
    assert second["turn"] == 2 and second["traceId"] != result["traceId"]
    assert second["testCaseId"] == result["testCaseId"]
    assert len(conversations) == 1
    assert all(c["path"].startswith("/project/agents/procurement-parent-agent/endpoint/protocols/openai/") for c in calls)
    assert "MUST-NOT-DISPLAY" not in first.text
    exported = str([(dict(s.attributes), s.events) for s in spans])
    for forbidden in ("synthetic-test-token", "synthetic-object", "MUST-NOT-DISPLAY", "forbidden"):
        assert forbidden not in exported


def test_user_cookie_csrf_and_arbitrary_conversation_rejected(web):
    client, module, calls, *_ = web
    assert client.get("/api/state", headers={"x-ms-client-principal": ""}).status_code == 401
    assert client.post("/api/chat", json={"message": "x"}, headers={"Origin": "https://evil.test"}).status_code == 403
    assert client.post("/api/chat", json={"message": "x"}, headers={"x-csrf-token": "wrong"}).status_code == 403
    assert client.post("/api/chat", json={"message": "x", "conversationId": "other"}).status_code == 422
    assert client.get("/api/state", headers={"x-ms-client-principal": _principal("other-user")}).status_code == 403
    cookie = client.cookies.get(module.COOKIE)
    client.cookies.set(module.COOKIE, cookie + "tampered", domain="web.test", path="/")
    assert client.post("/api/chat", json={"message": "x"}).status_code == 403
    assert calls == []


def test_new_conversation_preserves_remote_history(web):
    client, module, calls, exporter, conversations = web
    first = client.post("/api/chat", json={"message": "Synthetic"}).json()
    state = client.post("/api/conversation").json()
    client.headers["x-csrf-token"] = state["csrf"]
    second = client.post("/api/chat", json={"message": "New"}).json()
    assert first["conversationId"] != second["conversationId"]
    assert len(conversations) == 2
    assert second["turn"] == 1
    assert client.get("/static/app.js").status_code == 404
    assert client.get("/").status_code == 200


def test_old_conversation_contract_starts_new_remote_conversation(web):
    client, module, calls, exporter, conversations = web
    first = client.post('/api/chat', json={'message': 'Synthetic'}).json()
    conversations[first['conversationId']]['metadata'].pop('contract')
    second = client.post('/api/chat', json={'message': 'Synthetic after update'}).json()
    assert second['conversationReset'] is True
    assert second['conversationId'] != first['conversationId']
    assert second['turn'] == 1 and len(conversations) == 2
    assert conversations[first['conversationId']]['metadata']['turn'] == '1'
    assert conversations[second['conversationId']]['metadata']['contract'] == module.CONVERSATION_CONTRACT


def test_streaming_http_keeps_cookie_trace_headers_and_progress(web):
    client, module, calls, exporter, conversations = web
    reply = client.post('/api/chat/stream', json={'message': 'ノートPCを購入したい'})
    assert reply.status_code == 200
    assert reply.headers['content-type'].startswith('application/x-ndjson')
    events = [json.loads(line) for line in reply.text.splitlines()]
    assert events[0]['type'] == 'progress'
    assert any(e.get('text') == '商品の検索・仕様照合：開始しました' for e in events)
    assert sum(e.get('text') == '商品の検索・仕様照合：開始しました' for e in events) == 1
    final = events[-1]['value']
    assert events[-1]['type'] == 'result' and final['statuses']['technical'] == 'SUCCESS'
    assert client.get('/api/state').json()['conversationId'] == final['conversationId']
    assert not module.app.state.turn_lock.locked()
    sent = next(c for c in calls if c['path'].endswith('/responses'))
    assert sent['body']['stream'] is True
    headers = {k.lower(): v for k, v in sent['headers'].items()}
    assert headers['traceparent'].split('-')[1] == final['traceId']
    assert headers['baggage'].startswith('user.id=')
    assert 'MUST-NOT-DISPLAY' not in reply.text
    assert module._stream_progress('{"step":"hidden reasoning","state":"completed"}') is None


def test_candidate_projection_and_missing_fields_are_user_facing(web):
    _, module, *_ = web
    result = module._public_result(json.dumps({'business_status': 'WAITING_USER',
        'missing_fields': ['quantity', 'selected_product_code', 'arbitrary-secret'],
        'response_text': '商品を選び、台数を教えてください。',
        'candidates': [{'product_code': 'LAPTOP-DEV-14', 'product_name': '架空ノートPC', 'unit_price': '180000', 'hidden': 'secret'}]}))
    assert result['candidates'] == [{'product_code': 'LAPTOP-DEV-14', 'product_name': '架空ノートPC', 'unit_price': '180000'}]
    assert result['response'] == '商品を選び、台数を教えてください。'
    assert 'secret' not in json.dumps(result)


@pytest.mark.parametrize('business', ['WAITING_USER', 'NOT_FOUND'])
def test_unknown_department_asks_for_department_not_product(web, business):
    _, module, *_ = web
    result = module._public_result(json.dumps({'business_status': business,
        'status': {'reason_code': 'DEPARTMENT_NOT_FOUND'}, 'missing_fields': [],
        'response_text': '所属部署名を確認して教えてください。',
        'candidates': [{'product_code': 'LAPTOP-DEV-14', 'product_name': '架空ノートPC', 'unit_price': '180000'}]}))
    assert result['candidates'] == []
    assert '所属部署名を確認して教えてください' in result['response']
    assert '候補名または型番を教えて' not in result['response']


def test_projection_suppresses_unexpected_content(web):
    _, module, *_ = web
    result = module._public_result(json.dumps({"technical_status": "raw-token", "draft": {
        "lines": [{"product_code": "secret@example.test", "quantity": {"reasoning": "hidden"}}],
        "total": "Bearer hidden", "department_code": "raw oid or name"}, "trace": {"reasoning": "hidden"}}))
    assert result["statuses"]["technical"] == module.MISSING
    assert "hidden" not in json.dumps(result)
    assert "Hosted Agentの公開応答を確認できません" in result["response"]


def test_web_relays_hosted_natural_language_without_reconstructing_domain_steps(web):
    _, module, *_ = web
    data = {"technical_status": "SUCCESS", "business_status": "SUCCESS", "draft": {
        "lines": [{"product_code": "SYNTH-01", "quantity": 2, "unit_price": "180000", "subtotal": "360000", "account_code": "AC-01"}],
        "total": "360000", "department_code": "DPT-DEV"},
        "response_text": "Hosted Agentで申請案を確定しました。", "trace": {"events": [
            {"name": "step.started", "step_id": "catalog", "attempt": 1},
            {"name": "step.retry_scheduled", "step_id": "catalog", "reason": "hidden"},
            {"name": "step.started", "step_id": "catalog", "attempt": 2},
            *[{"name": "step.completed", "step_id": step} for step in ("catalog", "code", "merge_validate")],
            {"name": "hidden", "step_id": "hidden", "reason": "hidden"}]}}
    reply = module._public_result(json.dumps(data))["response"]
    assert reply == "Hosted Agentで申請案を確定しました。"
    assert "hidden" not in reply and "SYNTH-01" not in reply
    data["business_status"] = "BLOCKED"
    data["trace"]["events"] = [{"name": "plan.blocked", "step_id": "catalog", "reason": "hidden"}]
    data["response_text"] = "処理を停止しました。"
    assert module._public_result(json.dumps(data))["response"] == "処理を停止しました。"


@pytest.mark.parametrize("business,expected", [
    ("WAITING_USER", "商品を選んでください。"),
    ("INVALID_INPUT", "入力内容を確認してください。"),
    ("VALIDATION_FAILED", "申請案は確定していません。"),
])
def test_hosted_failure_text_is_allowlisted_but_not_generated_by_web(web, business, expected):
    _, module, *_ = web
    reply = module._public_result(json.dumps({"business_status": business, "response_text": expected}))["response"]
    assert reply == expected
    assert "元の応答は表示していません" in module._public_result("not-json")["response"]
