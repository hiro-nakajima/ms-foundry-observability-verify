"""OBO/user-id extraction from main 781db92, 2026-09-10.

Copy this module into the destination package, then wire the host and the
existing Executor as described in ../hosted-obo-userid-porting.md.
This is not an executable app and makes no Azure calls on import.

Pinned source SDKs: agent-framework-core 1.16.0,
agent-framework-foundry-hosting 1.0.0b260827, opentelemetry-sdk 1.43.0.
Source functions are retained; imports are consolidated, the middleware only
accepts current Web metadata, and the Host constructor takes parent + tool
instead of HostedAgentBundle. No procurement Controller is included.
"""
from __future__ import annotations

import inspect
import json
import os
import re
from collections.abc import AsyncIterable, Callable, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from agent_framework import (
    Agent, BaseChatClient, ChatResponse, ChatResponseUpdate,
    FunctionInvocationContext, Message,
)
from agent_framework_foundry_hosting import FoundryToolbox, ResponsesHostServer
from agent_framework_foundry_hosting._responses import consent_url_from_error
from opentelemetry import baggage, trace
from opentelemetry.sdk.trace import Event, SpanProcessor, TracerProvider
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware



# Extracted from src/procurement_agent/observability.py: request_correlation
request_correlation: ContextVar[dict[str, Any]] = ContextVar("procurement_request_correlation", default={})


# Extracted from src/procurement_agent/observability.py: current_request_attributes
def current_request_attributes() -> dict[str, Any]:
    attributes = dict(request_correlation.get())
    user = baggage.get_baggage("user.id")
    if "user.id" not in attributes and isinstance(user, str) and re.fullmatch(r"[a-f0-9]{64}", user):
        attributes["user.id"] = user
    return attributes


# Extracted from src/procurement_agent/observability.py: McpPrivacyProcessor
class McpPrivacyProcessor(SpanProcessor):
    """Remove MCP exception content before every exporter sees an ended span.

    The pinned OTel SDK 1.43 calls _on_ending for all processors before on_end
    (including batch export). MCP error text can contain OAuth URL state even
    when GenAI message-content recording is disabled. Preserve exception types,
    method, IDs, timing and error status, but not messages or stack traces.
    """
    def _on_ending(self, span):
        if not (span.attributes or {}).get("mcp.method.name"):
            return
        span._events = [Event(event.name, {
            key: value for key, value in (event.attributes or {}).items()
            if key not in {"exception.message", "exception.stacktrace"}
        }, event.timestamp) for event in span.events]
        if span.status.description:
            span._status = trace.Status(span.status.status_code)


# Extracted from src/procurement_agent/observability.py: configure_host_observability
def configure_host_observability(**kwargs):
    from azure.ai.agentserver.core import configure_observability
    configure_observability(**kwargs)
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider) and not getattr(provider, "_procurement_mcp_privacy", False):
        provider.add_span_processor(McpPrivacyProcessor())
        provider._procurement_mcp_privacy = True


# Extracted from src/procurement_agent/framework.py: Handler
Handler = Callable[[Sequence[Message], Mapping[str, Any]], Any]


# Extracted from src/procurement_agent/framework.py: DeterministicChatClient
class DeterministicChatClient(BaseChatClient):
    """Framework-compatible client; it does not model a child Prompt Agent."""

    OTEL_PROVIDER_NAME = "procurement-local-parent"

    def __init__(self, handler: Handler, *, client_name: str = "local-parent") -> None:
        super().__init__(additional_properties={"client_name": client_name})
        self.handler = handler
        self.calls: list[dict[str, Any]] = []

    async def _resolve(self, messages: Sequence[Message], options: Mapping[str, Any]) -> Any:
        value = self.handler(messages, options)
        return await value if inspect.isawaitable(value) else value

    @staticmethod
    def _text(value: Any) -> tuple[str, BaseModel | None]:
        if isinstance(value, BaseModel):
            return value.model_dump_json(), value
        if isinstance(value, str):
            return value, None
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str), None

    def _inner_get_response(self, *, messages, stream, options, **kwargs):
        response_format = options.get("response_format")
        format_name = response_format.get("name") if isinstance(response_format, Mapping) else getattr(response_format, "__name__", None)
        self.calls.append({"message_count": len(messages), "response_format": format_name, "tool_count": len(options.get("tools") or []), "stream": stream})
        response_id = f"local-response-{uuid4()}"
        if not stream:
            async def response() -> ChatResponse:
                value = await self._resolve(messages, options)
                text, model = self._text(value)
                return ChatResponse(messages=[Message(role="assistant", contents=[text])], response_id=response_id, value=model, response_format=options.get("response_format"), finish_reason="stop")
            return response()

        async def updates() -> AsyncIterable[ChatResponseUpdate]:
            value = await self._resolve(messages, options)
            text, _ = self._text(value)
            yield ChatResponseUpdate(role="assistant", contents=[{"type": "text", "text": text}], response_id=response_id, finish_reason="stop")
        return self._build_response_stream(updates(), response_format=options.get("response_format"))


# Extracted from src/procurement_agent/hosted.py: authenticated_applicant_name
authenticated_applicant_name: ContextVar[str | None] = ContextVar(
    "procurement_authenticated_applicant_name", default=None,
)


# Extracted from src/procurement_agent/hosted.py: applicant_lookup_status
applicant_lookup_status: ContextVar[str | None] = ContextVar(
    "procurement_applicant_lookup_status", default=None,
)


# Extracted from src/procurement_agent/identity.py: lookup_requested
lookup_requested: ContextVar[bool] = ContextVar("obo_lookup_requested", default=False)


# Extracted from src/procurement_agent/identity.py: IdentityResult
@dataclass(frozen=True)
class IdentityResult:
    status: str = "SKIPPED"
    name: str | None = None
    consent: tuple = ()


# Extracted from src/procurement_agent/identity.py: identity_result
identity_result: ContextVar[IdentityResult] = ContextVar("obo_result", default=IdentityResult())


# Extracted from src/procurement_agent/identity.py: parse_whoami_result
def parse_whoami_result(result):
    """Prefer the structured MCP result over its duplicate text representation."""
    if result.isError:
        raise ValueError("whoami_failed")
    value = result.structuredContent
    if value is None:
        texts = [item.text for item in result.content if item.type == "text"]
        if len(texts) != 1:
            raise ValueError("invalid_whoami_result")
        value = json.loads(texts[0])
    # FastMCP may wrap a typing.Dict return value in a result property.
    if isinstance(value, dict) and set(value) == {"result"}:
        value = value["result"]
    return json.dumps(value, ensure_ascii=False)


# Extracted from src/procurement_agent/identity.py: verified_name
def verified_name(result, expected_user_hash: str) -> str:
    if isinstance(result, list):
        texts = [item.text for item in result if item.type == "text"]
        if len(texts) != 1:
            raise ValueError("invalid_whoami_result")
        result = texts[0]
    if isinstance(result, str):
        result = json.loads(result)
    if not isinstance(result, dict) or result.get("tool") != "whoami" or result.get("auth_mode") != "obo" or result.get("error"):
        raise ValueError("invalid_whoami_result")
    user = result.get("user") or {}
    subject_hash, name = user.get("subjectHash"), user.get("displayName")
    if not isinstance(subject_hash, str) or len(subject_hash) != 64 or subject_hash != expected_user_hash:
        raise ValueError("whoami_subject_mismatch")
    if not isinstance(name, str) or not 0 < len(name.strip()) <= 120 or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise ValueError("invalid_display_name")
    return name.strip()


# Extracted from src/procurement_agent/identity.py: _consent
def _consent(exc):
    # MCP failures may be wrapped at several SDK boundaries.
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        found = consent_url_from_error(exc)
        if found:
            return tuple(found)
        exc = exc.__cause__ or exc.__context__
    return ()


# Extracted from src/procurement_agent/identity.py: build_identity_tool
def build_identity_tool(credential, *, toolbox_factory=FoundryToolbox):
    async def lookup(messages, options):
        result = IdentityResult("FAILED")
        with trace.get_tracer("procurement.identity").start_as_current_span(
            "identity.lookup", attributes=current_request_attributes(),
            record_exception=False, set_status_on_exception=False,
        ) as span:
            stage = "connect"
            try:
                # A fresh MCP session per request also isolates consent and the
                # transport lifecycle task's captured platform caller context.
                async with toolbox_factory(
                    credential, url=os.environ["PROCUREMENT_IDENTITY_TOOLBOX_ENDPOINT"],
                    name="procurement-identity-toolbox",
                    parse_tool_results=parse_whoami_result,
                ) as toolbox:
                    stage = "call"
                    span.set_attribute("app.identity.tool.count", len(toolbox.functions))
                    span.set_attribute("app.identity.tool.names", [f.name for f in toolbox.functions])
                    # Use the SDK-discovered FunctionTool so its remote name and
                    # tools/list metadata survive SDK name normalization. Azure
                    # currently exposes whoami_func___whoami; also accept the
                    # dot-separated name documented by the Toolbox service.
                    matches = [f for f in toolbox.functions if f.name in {
                        "whoami_func___whoami", "whoami_func.whoami",
                    }]
                    span.set_attribute("app.identity.tool.available", len(matches) == 1)
                    if len(matches) != 1:
                        raise ValueError("whoami_tool_unavailable")
                    function = matches[0]
                    raw = await function.invoke(arguments={}, context=FunctionInvocationContext(
                        function=function, arguments={}), skip_parsing=True)
                    stage = "verify"
                    name = verified_name(raw, current_request_attributes().get("user.id", ""))
                    result = IdentityResult("SUCCESS", name)
            except Exception as exc:
                consent = _consent(exc)
                if consent:
                    result = IdentityResult("WAITING_USER", consent=consent)
                else:
                    span.set_attribute("error.type", type(exc).__name__)
                    span.set_attribute("app.identity.error.type", type(exc).__name__)
                    span.set_attribute("app.identity.error.stage", stage)
                    cause, seen = exc, set()
                    while cause is not None and id(cause) not in seen:
                        seen.add(id(cause))
                        code = getattr(getattr(cause, "error", None), "code", None)
                        if isinstance(code, int):
                            span.set_attribute("app.identity.error.rpc_code", code)
                        cause = cause.__cause__ or cause.__context__
                    span.set_status(trace.StatusCode.ERROR)
            span.set_attribute("app.identity.lookup.status", result.status)
        identity_result.set(result)
        return json.dumps({"status": result.status})

    agent = Agent(
        DeterministicChatClient(lookup, client_name="graph-obo-identity"),
        name="obo_identity_agent", description="Resolve the signed-in applicant via Graph OBO.",
    )
    return agent.as_tool(name="obo_identity_agent", propagate_session=False)


# Extracted from src/procurement_agent/identity.py: invoke_identity
async def invoke_identity(tool) -> IdentityResult:
    identity_result.set(IdentityResult())
    if not lookup_requested.get():
        return identity_result.get()
    # The operation has no user-controlled arguments and no procurement history.
    arguments = {"task": "lookup"}
    await tool.invoke(arguments=arguments,
                      context=FunctionInvocationContext(function=tool, arguments=arguments), skip_parsing=True)
    return identity_result.get()


class IdentityRequestMiddleware(BaseHTTPMiddleware):
    """Current Web contract only; no browser-supplied display name is accepted."""

    async def dispatch(self, request, call_next):
        attributes, lookup_enabled = {}, False
        if request.method == "POST" and request.url.path.endswith("/responses"):
            try:
                body = await request.json()
                metadata = body.get("metadata") or {}
                lookup_enabled = metadata.get("app.identity.lookup") == "true"
                for key, target, pattern in (
                    ("app.user.id", "user.id", r"[a-f0-9]{64}"),
                    ("app.web.trace_id", "app.web.trace_id", r"[a-f0-9]{32}"),
                    ("test.case.id", "test.case.id", r"[A-Za-z0-9_-]{1,128}"),
                ):
                    value = metadata.get(key)
                    if isinstance(value, str) and re.fullmatch(pattern, value):
                        attributes[target] = value
                conversation = body.get("conversation")
                if isinstance(conversation, dict):
                    conversation = conversation.get("id")
                if isinstance(conversation, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,200}", conversation):
                    attributes["gen_ai.conversation.id"] = conversation
                turn = str(metadata.get("app.turn.number", ""))
                if turn.isascii() and turn.isdigit() and 0 < int(turn) < 1_000_000:
                    attributes["app.web.turn.number"] = int(turn)
            except (ValueError, AttributeError, TypeError):
                pass  # The protocol handler validates the body; never log it.
        correlation_token = request_correlation.set(attributes)
        requested_token = lookup_requested.set(lookup_enabled)
        try:
            return await call_next(request)
        finally:
            lookup_requested.reset(requested_token)
            request_correlation.reset(correlation_token)


# Adapted from hosted_app.py: constructor accepts the existing parent Agent.
class IdentityResponsesHostServer(ResponsesHostServer):
    """Resolve identity before procurement; emit native OAuth items when paused.

    The pinned hosting SDK only bridges connect-time consent on the parent
    Agent. This small protocol adapter also covers the nested identity Tool.
    A paused request has not mutated procurement state. The Web wrapper resends
    the original message on the same conversation after consent.
    """
    def __init__(self, parent_agent, identity_tool, **kwargs):
        self.identity_tool = identity_tool
        super().__init__(parent_agent, **kwargs)

    async def _handle_response(self, request, context, cancellation_signal):
        from agent_framework_foundry_hosting._responses import _create_response_event_stream, IdGenerator

        name_token = authenticated_applicant_name.set(None)
        status_token = applicant_lookup_status.set("SKIPPED")
        result_token = identity_result.set(IdentityResult())
        try:
            result = await invoke_identity(self.identity_tool)
            authenticated_applicant_name.set(result.name)
            applicant_lookup_status.set(result.status)
            if result.consent:
                stream = _create_response_event_stream(context)
                yield stream.emit_created()
                yield stream.emit_in_progress()
                for consent in result.consent:
                    item = {"type": "oauth_consent_request", "id": IdGenerator.new_id("oacr"),
                            "response_id": context.response_id, "server_label": consent.name,
                            "consent_link": consent.consent_url}
                    builder = stream.add_output_item(item["id"])
                    yield builder.emit_added(item)
                    yield builder.emit_done(item)
                yield stream.emit_incomplete(reason="OAuth consent required")
                return
            async for event in super()._handle_response(request, context, cancellation_signal):
                yield event
        finally:
            identity_result.reset(result_token)
            authenticated_applicant_name.reset(name_token)
            applicant_lookup_status.reset(status_token)
