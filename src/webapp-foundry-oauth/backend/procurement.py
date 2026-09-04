"""App Service entry point: EasyAuth -> managed identity -> APIM -> Foundry.

The supplied OAuth/Graph demo stays in server.py, but is not mounted by this app.
Foundry owns conversation history; the signed cookie is only an owner-bound handle.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from azure.ai.projects.aio import AIProjectClient
from azure.identity.aio import ManagedIdentityCredential
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.background import BackgroundTask
from opentelemetry import baggage, context, propagate, trace
from opentelemetry.baggage.propagation import W3CBaggagePropagator
from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from pydantic import BaseModel, ConfigDict, Field

STATIC = Path(__file__).parent / "static"
COOKIE = "__Host-procurement"
MISSING = "NOT_RECORDED_BY_PLATFORM"
STATUS_VALUES = {
    "technical": {"SUCCESS", "ERROR"},
    "business": {"SUCCESS", "WAITING_USER", "NOT_FOUND", "INVALID_INPUT", "VALIDATION_FAILED", "BLOCKED"},
    "mcp": {"NOT_RUN", "SUCCESS", "ERROR", "TIMEOUT", "PROTOCOL_ERROR"},
    "search": {"NOT_RUN", "SUCCESS", "NOT_FOUND", "INDEX_MISSING", "PERMISSION_DENIED", "ERROR"},
    "parse": {"NOT_RUN", "SUCCESS", "INVALID_JSON", "SCHEMA_INVALID"},
}
PROGRESS_STEPS = {'intake', 'catalog', 'code', 'merge_validate'}
PROGRESS_STATES = {'started', 'completed', 'retry', 'waiting_user', 'blocked'}
CONVERSATION_CONTRACT = "procurement-intake-v2"
PLATFORM_PROPAGATION = "TRACE_CONTEXT_PROPAGATED_USER_ID_NOT_PROPAGATED"


def _identity(request: Request) -> tuple[str, str]:
    try:
        principal = json.loads(base64.b64decode(request.headers.get("x-ms-client-principal", ""), validate=True))
        claims = {c["typ"]: c["val"] for c in principal["claims"]
                  if isinstance(c, dict) and isinstance(c.get("typ"), str)}
        tenant = claims.get("tid") or claims.get("http://schemas.microsoft.com/identity/claims/tenantid")
        oid = claims.get("oid") or claims.get("http://schemas.microsoft.com/identity/claims/objectidentifier")
        if not isinstance(tenant, str) or not isinstance(oid, str) or not tenant or not oid:
            raise ValueError()
        display_name = claims.get("name") or claims.get(
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name"
        )
        if (not isinstance(display_name, str) or not display_name.strip()
                or len(display_name.strip()) > 120
                or "@" in display_name
                or any(ord(char) < 32 or ord(char) == 127 for char in display_name)):
            display_name = ""
    except (ValueError, KeyError, TypeError):
        raise HTTPException(401, "EasyAuth authentication is required") from None
    return hashlib.sha256(f"{tenant}:{oid}".encode()).hexdigest(), display_name.strip()


def _user(request: Request) -> str:
    return _identity(request)[0]


def _sign(state: dict, key: bytes) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(state, separators=(",", ":")).encode()).decode()
    return payload + "." + hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()


def _state(request: Request, user: str) -> dict:
    cookie = request.cookies.get(COOKIE)
    if not cookie:
        return {"user": user, "csrf": secrets.token_urlsafe(24), "exp": int(time.time()) + 86400}
    try:
        payload, signature = cookie.rsplit(".", 1)
        expected = hmac.new(request.app.state.signing_key, payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        state = json.loads(base64.urlsafe_b64decode(payload))
        if state["user"] != user or state["exp"] < time.time():
            raise ValueError()
        return state
    except (ValueError, KeyError, TypeError):
        raise HTTPException(403, "Invalid or expired conversation cookie; sign in again") from None


def _reply(request: Request, state: dict, value: dict, status_code: int = 200) -> JSONResponse:
    response = JSONResponse(value, status_code=status_code, headers={"Cache-Control": "no-store"})
    response.set_cookie(COOKIE, _sign(state, request.app.state.signing_key), secure=True,
                        httponly=True, samesite="strict", max_age=86400, path="/")
    return response


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=100_000)


class _BrowserBoundary:
    """Outside OTel: browser-controlled trace context never becomes the root."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        scope = dict(scope, headers=[(k, v) for k, v in scope["headers"]
                                   if k.lower() not in {b"traceparent", b"tracestate", b"baggage"}])
        token = context.attach(context.Context())
        try:
            await self.app(scope, receive, send)
        finally:
            context.detach(token)


def _public_result(text: str) -> dict:
    """No raw model/tool trace, reasoning, tokens, or unknown fields in the UI."""
    statuses = {k: MISSING for k in ("technical", "business", "mcp", "search", "parse")}
    try:
        result = json.loads(text)
        if not isinstance(result, dict):
            raise ValueError()
        layer = result.get("status") or {}
        for name in statuses:
            value = result.get(f"{name}_status") if name in {"technical", "business"} else layer.get(f"{name}_status")
            if isinstance(value, str) and value in STATUS_VALUES[name]:
                statuses[name] = value
        # Project business data and known execution event enums, never raw trace text.
        correlation = (result.get("trace") or {}).get("correlation") or {}
        session_hash = correlation.get("framework_session_id_hash", "")
        session_hash = session_hash if isinstance(session_hash, str) and re.fullmatch(r"[a-f0-9]{64}", session_hash) else MISSING
        candidates = []
        needs_selection = 'selected_product_code' in result.get('missing_fields', [])
        for candidate in (result.get('candidates', [])[:5] if statuses['business'] == 'WAITING_USER' and needs_selection else []):
            code = _public_scalar('product_code', candidate.get('product_code'))
            name = candidate.get('product_name')
            price = _public_scalar('unit_price', candidate.get('unit_price'))
            if (code not in (None, 'WITHHELD') and price not in (None, 'WITHHELD')
                and isinstance(name, str) and len(name) <= 120
                and not any(marker in name.lower() for marker in ('@', '\n', '\r', 'bearer ', 'secret', 'token', 'chain_of_thought'))):
                candidates.append({'product_code': code, 'product_name': name, 'unit_price': price})
        response = result.get("response_text")
        if (not isinstance(response, str) or not response or len(response) > 4_000
                or any(marker in response.lower() for marker in ('bearer ', 'secret', 'token', 'chain_of_thought'))):
            response = "Hosted Agentの公開応答を確認できませんでした。実行情報を確認してください。"
        return {"statuses": statuses, "frameworkSessionIdHash": session_hash, 'candidates': candidates,
                "response": response}
    except (ValueError, TypeError, AttributeError, KeyError):
        statuses["parse"] = "SCHEMA_INVALID"
        return {"statuses": statuses, "response": "応答の形式を確認できませんでした。処理の完了は確認できていません。安全のため元の応答は表示していません。"}


def _public_scalar(key: str, value):
    if value is None:
        return None
    pattern = r"[A-Z0-9_-]{1,32}" if key.endswith("_code") or key == "currency" else r"[0-9]{1,16}(\.[0-9]{1,6})?"
    return value if re.fullmatch(pattern, str(value)) else "WITHHELD"


class _ObservedTransport(httpx.AsyncHTTPTransport):
    """Observe SDK/instrumentation-injected headers at the actual HTTP boundary."""
    async def handle_async_request(self, request):
        span = trace.get_current_span()
        current = span.get_span_context()
        parts = request.headers.get("traceparent", "").split("-")
        user = baggage.get_baggage("user.id")
        span.set_attributes({
            # Azure Monitor filters http.* as standard fields, including custom keys.
            "app.propagation.traceparent_present": len(parts) == 4,
            "app.propagation.traceparent_matches_span": len(parts) == 4 and
                parts[1] == f"{current.trace_id:032x}" and parts[2] == f"{current.span_id:016x}",
            "app.propagation.baggage_user_id_matches": bool(user) and request.headers.get("baggage") == f"user.id={user}",
        })
        return await super().handle_async_request(request)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    key = os.environ.get("WEBUI_SESSION_SIGNING_KEY", "").encode()
    if len(key) < 32:
        raise RuntimeError("WEBUI_SESSION_SIGNING_KEY must contain at least 32 bytes")
    if not os.environ.get("WEB_APP_URL", "").startswith("https://"):
        raise RuntimeError("WEB_APP_URL must be the HTTPS App Service origin")
    app.state.signing_key = key
    app.state.turn_lock = asyncio.Lock()  # One PoC instance; serialize turn metadata updates.
    app.state.provider = TracerProvider(resource=Resource.create({"service.name": "procurement-webapp"}))
    if os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        app.state.provider.add_span_processor(BatchSpanProcessor(AzureMonitorTraceExporter()))
    propagate.set_global_textmap(CompositePropagator([TraceContextTextMapPropagator(), W3CBaggagePropagator()]))
    async with ManagedIdentityCredential() as credential, httpx.AsyncClient(transport=_ObservedTransport()) as http:
        HTTPXClientInstrumentor.instrument_client(http, tracer_provider=app.state.provider)
        async with AIProjectClient(endpoint=os.environ["PROJECT_ENDPOINT"], credential=credential, allow_preview=True) as project:
            async with project.get_openai_client(agent_name=os.getenv("AGENT_NAME", "procurement-parent-agent"),
                                                http_client=http, max_retries=0, timeout=210) as agent:
                # Hosted conversations belong to this named endpoint, not project /openai/v1.
                app.state.conversations = agent.conversations
                app.state.responses = agent.responses
                yield
    app.state.provider.shutdown()


app = FastAPI(title="Procurement observability PoC", lifespan=_lifespan, docs_url=None, redoc_url=None, openapi_url=None)


class _Instrumentation:
    # The provider is initialized by lifespan, after FastAPI builds its middleware.
    def __init__(self, app):
        self.app = app
        self.instrumented = None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if self.instrumented is None:
            self.instrumented = OpenTelemetryMiddleware(self.app, tracer_provider=scope["app"].state.provider,
                                                        exclude_spans=["receive", "send"])
        await self.instrumented(scope, receive, send)


app.add_middleware(_Instrumentation)
app.add_middleware(_BrowserBoundary)


@app.get("/")
async def index(request: Request):
    _user(request)
    return FileResponse(STATIC / "procurement.html", headers={"Cache-Control": "no-store"})


@app.get("/static/{name}")
async def asset(name: str):
    if name not in {"procurement.js", "styles.css"}:
        raise HTTPException(404)
    return FileResponse(STATIC / name)


@app.get("/api/state")
async def state(request: Request):
    saved = _state(request, _user(request))
    return _reply(request, saved, {"conversationId": saved.get("conversation"), "csrf": saved["csrf"]})


def _validate_post(request: Request, saved: dict):
    if request.headers.get("origin") != os.environ.get("WEB_APP_URL") or not secrets.compare_digest(
        request.headers.get("x-csrf-token", ""), saved["csrf"]
    ):
        raise HTTPException(403, "Invalid request origin or CSRF token")


@app.post("/api/conversation")
async def new_conversation(request: Request):
    saved = _state(request, _user(request))
    _validate_post(request, saved)
    saved.pop("conversation", None)  # Never deletes the remote conversation.
    saved["csrf"] = secrets.token_urlsafe(24)
    return _reply(request, saved, {"conversationId": None, "csrf": saved["csrf"]})


def _stream_progress(line: str) -> str | None:
    try:
        value = json.loads(line.lstrip(','))
        step, state, message = value.get('step'), value.get('state'), value.get('message')
        if (step in PROGRESS_STEPS and state in PROGRESS_STATES and isinstance(message, str)
                and 0 < len(message) <= 120 and '\n' not in message and '\r' not in message):
            return message
    except (ValueError, AttributeError):
        pass
    return None


def _response_metadata(case: str, number: int, applicant_name: str) -> dict[str, str]:
    value = {'test.case.id': case, 'app.turn.number': str(number)}
    if applicant_name:
        value['app.authenticated.display_name'] = applicant_name
    return value


async def _stream_turn(request, turn, saved, user, applicant_name, span, conversation, number, case, reset, release):
    token = context.attach(baggage.set_baggage('user.id', user))
    def event(kind, **value):
        return json.dumps({'type': kind, **value}, ensure_ascii=False) + '\n'
    try:
        if reset:
            yield event('progress', text='Agent更新に合わせて新しい会話状態を開始しました。')
        yield event('progress', text='依頼をFoundryへ送信しています。')
        stream = await request.app.state.responses.create(conversation=conversation.id, input=turn.message,
            metadata=_response_metadata(case, number, applicant_name), stream=True)
        final, pending, last_progress = None, '', None
        async with stream:
            async for update in stream:
                if update.type == 'response.output_text.delta':
                    pending += update.delta
                    if len(pending) > 1_000_000:
                        raise ValueError('Response exceeds PoC limit')
                    while '\n' in pending:
                        line, pending = pending.split('\n', 1)
                        text = _stream_progress(line)
                        if text and text != last_progress:
                            yield event('progress', text=text)
                            last_progress = text
                elif update.type == 'response.completed':
                    final = update.response
                elif update.type in {'response.failed', 'response.incomplete', 'error'}:
                    raise RuntimeError('Foundry stream failed')
        if final is None or final.status != 'completed':
            raise RuntimeError('Foundry stream did not complete')
        span.set_attribute('gen_ai.response.id', final.id)
        value = _public_result(final.output_text)
        value.update({'conversationId': conversation.id, 'turn': number, 'testCaseId': case,
                      'responseId': final.id, 'traceId': format(span.get_span_context().trace_id, '032x'),
                      'spanId': format(span.get_span_context().span_id, '016x'), 'parentSpanId': None,
                      'platformPropagation': PLATFORM_PROPAGATION, 'conversationReset': reset, 'csrf': saved['csrf']})
        yield event('result', value=value)
    except Exception as exc:
        span.set_status(trace.StatusCode.ERROR)
        span.set_attribute('error.type', type(exc).__name__)
        yield event('result', value={'error': '応答が中断されました。完了は確認できていません。',
                    'traceId': format(span.get_span_context().trace_id, '032x'), 'conversationId': conversation.id,
                    'statuses': {'technical': 'ERROR', **{k: MISSING for k in ('business', 'mcp', 'search', 'parse')}}})
    finally:
        context.detach(token)
        release()


@app.post("/api/chat")
@app.post("/api/chat/stream")
async def chat(turn: Turn, request: Request):
    user, applicant_name = _identity(request)
    saved = _state(request, user)
    _validate_post(request, saved)
    span = trace.get_current_span()
    span.set_attribute("user.id", user)
    token = context.attach(baggage.set_baggage("user.id", user))
    locked, streaming = False, False
    def release():
        nonlocal locked
        if locked:
            locked = False
            request.app.state.turn_lock.release()
    try:
        await request.app.state.turn_lock.acquire()
        locked = True
        if locked:
            api = request.app.state.conversations
            reset = False
            if saved.get("conversation"):
                conversation = await api.retrieve(saved["conversation"])
                if conversation.metadata.get("owner") != user:
                    raise HTTPException(403, "Conversation ownership mismatch")
                if conversation.metadata.get("contract") != CONVERSATION_CONTRACT:
                    conversation = await api.create(metadata={"owner": user, "turn": "0",
                        "case": "WEB-" + secrets.token_hex(8), "contract": CONVERSATION_CONTRACT})
                    saved["conversation"] = conversation.id
                    reset = True
            else:
                conversation = await api.create(metadata={"owner": user, "turn": "0",
                    "case": "WEB-" + secrets.token_hex(8), "contract": CONVERSATION_CONTRACT})
                saved["conversation"] = conversation.id
            number = int(conversation.metadata["turn"]) + 1
            case = conversation.metadata["case"]
            span.set_attributes({"gen_ai.conversation.id": conversation.id, "app.turn.number": number, "test.case.id": case})
            # Reserve the turn before execution. A failed request is still an attempted turn.
            await api.update(conversation.id, metadata={**conversation.metadata, "turn": str(number)})
            if request.url.path.endswith('/stream'):
                response = StreamingResponse(_stream_turn(request, turn, saved, user, applicant_name, span, conversation, number, case, reset, release),
                    media_type='application/x-ndjson', headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'},
                    background=BackgroundTask(release))
                response.set_cookie(COOKIE, _sign(saved, request.app.state.signing_key), secure=True,
                                    httponly=True, samesite='strict', max_age=86400, path='/')
                streaming = True
                return response
            response = await request.app.state.responses.create(conversation=conversation.id, input=turn.message,
                metadata=_response_metadata(case, number, applicant_name))
            span.set_attribute("gen_ai.response.id", response.id)
            value = _public_result(response.output_text)
            value.update({"conversationId": conversation.id, "turn": number, "testCaseId": case,
                "responseId": response.id, "traceId": format(span.get_span_context().trace_id, "032x"),
                "spanId": format(span.get_span_context().span_id, "016x"), "parentSpanId": None,
                "platformPropagation": PLATFORM_PROPAGATION, "conversationReset": reset, "csrf": saved["csrf"]})
            return _reply(request, saved, value)
    except HTTPException:
        raise
    except Exception as exc:
        # No upstream body, token, claims or exception message reaches UI/trace.
        span.set_status(trace.StatusCode.ERROR)
        span.set_attribute("error.type", type(exc).__name__)
        return _reply(request, saved, {"error": "Foundry request failed; use the trace ID for investigation.",
            "traceId": format(span.get_span_context().trace_id, "032x"), "conversationId": saved.get("conversation"),
            "statuses": {"technical": "ERROR", **{k: MISSING for k in ("business", "mcp", "search", "parse")}}}, 502)
    finally:
        context.detach(token)
        if not streaming:
            release()
