"""Request-scoped OBO Agent Tool using the existing Hosted Toolbox pattern.

The platform call ID carries caller context; bearer tokens never become agent
arguments. Only a status is returned by the agent. The verified name remains
in request-local application state until the procurement controller uses it.
"""
from __future__ import annotations

import json
import os
from contextvars import ContextVar
from dataclasses import dataclass

from agent_framework import Agent, FunctionInvocationContext
from agent_framework_foundry_hosting import FoundryToolbox
from agent_framework_foundry_hosting._responses import consent_url_from_error
from opentelemetry import trace

from .framework import DeterministicChatClient
from .observability import current_request_attributes, sha256


lookup_requested: ContextVar[bool] = ContextVar("obo_lookup_requested", default=False)


@dataclass(frozen=True)
class IdentityResult:
    status: str = "SKIPPED"
    name: str | None = None
    consent: tuple = ()


identity_result: ContextVar[IdentityResult] = ContextVar("obo_result", default=IdentityResult())


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


async def invoke_identity(tool) -> IdentityResult:
    identity_result.set(IdentityResult())
    if not lookup_requested.get():
        return identity_result.get()
    # The operation has no user-controlled arguments and no procurement history.
    arguments = {"task": "lookup"}
    await tool.invoke(arguments=arguments,
                      context=FunctionInvocationContext(function=tool, arguments=arguments), skip_parsing=True)
    return identity_result.get()
