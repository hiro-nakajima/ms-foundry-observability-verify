"""2026-09-12: 独自identity metadata不要のOBO検証経路。import時にAzureへ接続しない。

既存の親AgentをIdentityResponsesHostServer(parent_agent, identity_tool=...)へ渡す。
通常購買は親へ、明示的な本人確認はOBO Toolへ分岐する。名前は購買へ保存しない。
固定SDK: agent-framework-core 1.16.0 / foundry-hosting 1.0.0b260827 / OTel 1.43.0。
"""
from __future__ import annotations
import inspect
import json
import os
import re
from collections.abc import AsyncIterable, Callable, Mapping, Sequence
from contextvars import ContextVar
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4
from agent_framework import Agent, BaseChatClient, ChatResponse, ChatResponseUpdate, FunctionInvocationContext, Message
from agent_framework_foundry_hosting import FoundryToolbox, ResponsesHostServer
from agent_framework_foundry_hosting._responses import ConsentError, consent_url_from_error
from mcp.shared.exceptions import McpError
from opentelemetry import baggage, trace
from opentelemetry.sdk.trace import Event, SpanProcessor, TracerProvider
from pydantic import BaseModel

# 抜粋元: observability.py:request_correlation
request_correlation: ContextVar[dict[str, Any]] = ContextVar("procurement_request_correlation", default={})


# 抜粋元: observability.py:McpPrivacyProcessor
class McpPrivacyProcessor(SpanProcessor):
    """Remove MCP exception content before every exporter sees an ended span.

    The pinned OTel SDK 1.43 calls _on_ending for all processors before on_end
    (including batch export). MCP error text can contain OAuth URL state even
    when GenAI message-content recording is disabled. Preserve exception types,
    method, IDs, timing and error status, but not messages or stack traces.
    """
    # 固定SDKの終了前hookで、Exporterへ届く前にMCP例外本文を除去する。
    def _on_ending(self, span):
        if not (span.attributes or {}).get("mcp.method.name"):
            return
        span._events = [Event(event.name, {
            key: value for key, value in (event.attributes or {}).items()
            if key not in {"exception.message", "exception.stacktrace"}
        }, event.timestamp) for event in span.events]
        if span.status.description:
            span._status = trace.Status(span.status.status_code)


# 抜粋元: observability.py:configure_host_observability
def configure_host_observability(**kwargs):
    from azure.ai.agentserver.core import configure_observability
    configure_observability(**kwargs)
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider) and not getattr(provider, "_procurement_mcp_privacy", False):
        provider.add_span_processor(McpPrivacyProcessor())
        provider._procurement_mcp_privacy = True


# 抜粋元: observability.py:current_request_attributes
def current_request_attributes() -> dict[str, Any]:
    attributes = dict(request_correlation.get())
    # メールは観測用。認証・認可やGraph本人照合には決して使用しない。
    user = baggage.get_baggage("user.id")
    if "user.id" not in attributes and isinstance(user, str) and re.fullmatch(r"[^\s@,;=]+@[^\s@,;=]+\.[^\s@,;=]+", user):
        attributes["user.id"] = user
    return attributes


# 抜粋元: framework.py:Handler
Handler = Callable[[Sequence[Message], Mapping[str, Any]], Any]


# 抜粋元: framework.py:DeterministicChatClient
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


# 抜粋元: identity.py:IdentityResult
@dataclass(frozen=True)
class IdentityResult:
    status: str = "SKIPPED"
    name: str | None = None
    consent: tuple = ()


# 抜粋元: identity.py:identity_result
identity_result: ContextVar[IdentityResult] = ContextVar("obo_result", default=IdentityResult())


# 抜粋元: identity.py:parse_whoami_result
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


# 抜粋元: identity.py:verified_name
def verified_name(result) -> str:
    """信頼済みwhoamiのOBO結果を検査する。本人照合はFunctions側のtoken oidとGraph /me idで行う。"""
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
    if not isinstance(user, dict):
        raise ValueError("invalid_whoami_user")
    name = user.get("displayName")
    # baggageや任意metadataは認証情報ではないため、本人照合に使用しない。
    if not isinstance(name, str) or not 0 < len(name.strip()) <= 120 or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise ValueError("invalid_display_name")
    return name.strip()


# 抜粋元: identity.py:_consent
def _consent(exc):
    # tools/listはJSON形式、tools/callはURL単体の-32006を返す場合がある。
    # SDKは前者だけを解析するため、後者を先に判定して同じ同意イベントへ変換する。
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        rpc_error = exc if isinstance(exc, McpError) else next(
            (arg for arg in exc.args if isinstance(arg, McpError)), None,
        )
        if rpc_error is not None and rpc_error.error.code == -32006 and "{" not in rpc_error.error.message:
            # エラー本文を一般的なURLとして表示せず、Foundryの同意先に限定する。
            # URLのdata値は認証情報を含み得るため、ログやSpanへ出さない。
            url = rpc_error.error.message.strip()
            try:
                parsed = urlsplit(url)
                valid = (parsed.scheme == "https" and parsed.hostname is not None
                         and parsed.hostname.endswith(".consent.azure-apim.net")
                         and parsed.path == "/login" and parsed.port in (None, 443)
                         and parsed.username is None and parsed.password is None)
            except ValueError:
                valid = False
            if valid:
                return (ConsentError(name="whoami_func", consent_url=url),)
            # SDKへ渡すと未対応形式の本文をwarningに出すので、この形式はここで終える。
        else:
            found = consent_url_from_error(exc)
            if found:
                return tuple(found)
        exc = exc.__cause__ or exc.__context__
    return ()


# 抜粋元: identity.py:build_identity_tool
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
                    name = verified_name(raw)
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


# 抜粋元: identity.py:invoke_identity
async def invoke_identity(tool) -> IdentityResult:
    if tool is None:
        return IdentityResult("UNAVAILABLE")
    # 引数へTokenや利用者入力を渡さず、プラットフォームの呼出しコンテキストを使う。
    arguments = {"task": "lookup"}
    token = identity_result.set(IdentityResult())
    try:
        await tool.invoke(arguments=arguments,
                          context=FunctionInvocationContext(function=tool, arguments=arguments), skip_parsing=True)
        return identity_result.get()
    finally:
        identity_result.reset(token)  # 別の要求や通常購買へ名前を持ち越さない。


# 抜粋元: identity.py:is_identity_request
def is_identity_request(text: str) -> bool:
    """OBO検証への明示的な入口。購買文中の「名前」だけでは起動しない。"""
    normalized = re.sub(r"[\s、。！？!?]+", "", text).casefold()
    return normalized in {
        "私は誰", "私は誰ですか", "わたしは誰", "whoami",
        "私の名前を教えて", "私の名前を教えてください", "私の名前は", "私の名前は何ですか",
        "obo", "oboフローを実行", "oboフローを実行して", "oboフローを実行してください",
        "oboで名前を取得して", "oboで名前を取得してください",
    }


# 抜粋元: identity.py:identity_response_text
def identity_response_text(result: IdentityResult) -> str:
    if result.status == "SUCCESS":
        return f"Graph OBOで取得したあなたの表示名は「{result.name}」です。"
    if result.status == "UNAVAILABLE":
        return "この環境にはOBO検証用Toolboxが設定されていません。購買支援は利用できます。"
    return "OBOによる名前取得に失敗しました。時間をおいて再試行してください。購買支援は利用できます。"


# 抜粋元: hosted_app.py:_latest_input_text
def _latest_input_text(request) -> str:
    """今回の標準Responses入力だけを見る。metadataや会話履歴を起動指示にしない。"""
    value = request.get("input", [])
    if isinstance(value, str):
        return value
    for item in reversed(value or []):
        if item.get("role") == "user":
            content = item.get("content", "")
            if isinstance(content, str):
                return content
            return "".join(part.get("text", "") for part in content if part.get("type") == "input_text")
    return ""


# 抜粋元: hosted_app.py:ProcurementResponsesHostServer
class IdentityResponsesHostServer(ResponsesHostServer):
    """通常購買と明示的OBO検証を分離し、既存Webへ標準同意イベントを返す。"""

    def __init__(self, parent_agent, *, identity_tool=None, **kwargs):
        # OBO Toolを購買親Agentへ登録しないため、購買中には実行されない。
        self.identity_tool = identity_tool
        super().__init__(parent_agent, **kwargs)

    async def _handle_response(self, request, context, cancellation_signal):
        from agent_framework_foundry_hosting._responses import _create_response_event_stream, IdGenerator, _SignalledIterator

        if not is_identity_request(_latest_input_text(request)):
            async for event in super()._handle_response(request, context, cancellation_signal):
                yield event
            return

        # 検証経路は購買Controllerや購買状態へ触れない。同意後はWebが元の質問を再送する。
        stream = _create_response_event_stream(context)
        yield stream.emit_created()
        yield stream.emit_in_progress()
        # SDKと同じ停止シグナルを監視し、遅いGraph呼出し中でもキャンセルできる。
        if cancellation_signal.is_set() or context.shutdown.is_set():
            return
        async def lookup():
            yield await invoke_identity(self.identity_tool)
        result = None
        async with aclosing(_SignalledIterator(lookup(), context.shutdown, cancellation_signal)) as pending:
            async for result in pending:
                pass
        if result is None:
            return
        if result.consent:
            for consent in result.consent:
                item = {"type": "oauth_consent_request", "id": IdGenerator.new_id("oacr"),
                        "response_id": context.response_id, "server_label": consent.name,
                        "consent_link": consent.consent_url}
                builder = stream.add_output_item(item["id"])
                yield builder.emit_added(item)
                yield builder.emit_done(item)
            yield stream.emit_incomplete(reason="OAuth consent required")
            return

        # 氏名は応答本文だけへ出し、Span・ログ・購買セッションには保存しない。
        message = stream.add_output_item_message()
        content = message.add_text_content()
        yield message.emit_added()
        yield content.emit_added()
        text = identity_response_text(result)
        yield content.emit_delta(text)
        yield content.emit_text_done(text)
        yield content.emit_done()
        yield message.emit_done()
        yield stream.emit_completed()
