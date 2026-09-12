"""明示的な本人確認で使うOBO検証用Agent Tool。購買の前処理には使わない。"""
from __future__ import annotations

import json
import os
import re
from contextvars import ContextVar
from dataclasses import dataclass
from urllib.parse import urlsplit

from mcp.shared.exceptions import McpError

from agent_framework import Agent, FunctionInvocationContext
from agent_framework_foundry_hosting import FoundryToolbox
from agent_framework_foundry_hosting._responses import ConsentError, consent_url_from_error
from opentelemetry import trace

from .framework import DeterministicChatClient
from .observability import current_request_attributes


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


def is_identity_request(text: str) -> bool:
    """OBO検証への明示的な入口。購買文中の「名前」だけでは起動しない。"""
    normalized = re.sub(r"[\s、。！？!?]+", "", text).casefold()
    return normalized in {
        "私は誰", "私は誰ですか", "わたしは誰", "whoami",
        "私の名前を教えて", "私の名前を教えてください", "私の名前は", "私の名前は何ですか",
        "obo", "oboフローを実行", "oboフローを実行して", "oboフローを実行してください",
        "oboで名前を取得して", "oboで名前を取得してください",
    }


def identity_response_text(result: IdentityResult) -> str:
    if result.status == "SUCCESS":
        return f"Graph OBOで取得したあなたの表示名は「{result.name}」です。"
    if result.status == "UNAVAILABLE":
        return "この環境にはOBO検証用Toolboxが設定されていません。購買支援は利用できます。"
    return "OBOによる名前取得に失敗しました。時間をおいて再試行してください。購買支援は利用できます。"
