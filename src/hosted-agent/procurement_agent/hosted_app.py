"""Foundry Responses host for the single Hosted parent."""

from __future__ import annotations

import argparse
from contextlib import aclosing
import json
import os
import re
from pathlib import Path

from agent_framework_foundry_hosting import ResponsesHostServer
from starlette.middleware.base import BaseHTTPMiddleware

from .hosted import FoundryRuntimeSettings, build_hosted_bundle
from .observability import request_correlation, configure_host_observability
from .identity import build_identity_tool, invoke_identity, is_identity_request, identity_response_text


_VALIDATION_PROFILES = {
    "TV-02", "TV-03", "SD-03", "SD-05", "MA-04", "MA-05",
    "S1-HEALTHY", "S5-HEALTHY", "S5-SMALL", "S5-32768", "S5-65536",
    "S5-OVER",
}


class _RequestCorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        attributes = {}
        if request.method == "POST" and request.url.path.endswith("/responses"):
            try:
                body = await request.json()
                metadata = body.get("metadata") or {}
                conversation = body.get("conversation")
                if isinstance(conversation, dict):
                    conversation = conversation.get("id")
                if isinstance(conversation, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,200}", conversation):
                    attributes["gen_ai.conversation.id"] = conversation
                case = metadata.get("test.case.id", "")
                if isinstance(case, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", case):
                    attributes["test.case.id"] = case
                for key, target, pattern in (
                    ("app.web.trace_id", "app.web.trace_id", r"[a-f0-9]{32}"),
                ):
                    value = metadata.get(key)
                    if isinstance(value, str) and re.fullmatch(pattern, value):
                        attributes[target] = value
                turn = str(metadata.get("app.turn.number", ""))
                if turn.isascii() and turn.isdigit() and 0 < int(turn) < 1_000_000:
                    attributes["app.web.turn.number"] = int(turn)
                contract = metadata.get("app.client.contract")
                if contract == "web-json-v1":
                    attributes["app.client.contract"] = contract
                validation_contract = metadata.get("app.validation.contract")
                validation_profile = metadata.get("app.validation.profile")
                if (
                    os.getenv("PROCUREMENT_ENABLE_SYNTHETIC_INJECTIONS") == "true"
                    and metadata.get("synthetic") == "true"
                    and validation_contract == "stage-b-v1"
                    and validation_profile in _VALIDATION_PROFILES
                    and isinstance(case, str)
                    and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", case)
                    and case.startswith("AZURE-CORE-")
                ):
                    attributes["app.validation.contract"] = validation_contract
                    attributes["app.validation.profile"] = validation_profile
            except (ValueError, AttributeError, TypeError):
                pass  # Protocol handler owns rejection; never log the raw body.
        token = request_correlation.set(attributes)
        try:
            return await call_next(request)
        finally:
            request_correlation.reset(token)


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


class ProcurementResponsesHostServer(ResponsesHostServer):
    """通常購買と明示的OBO検証を分離し、既存Webへ標準同意イベントを返す。"""

    def __init__(self, bundle, *, identity_tool=None, **kwargs):
        # OBO Toolを購買親Agentへ登録しないため、購買中には実行されない。
        self.identity_tool = identity_tool
        super().__init__(bundle.parent, **kwargs)

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Procurement Agent v2 Responses host")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--smoke", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = "false"
    os.environ.setdefault("OTEL_PROPAGATORS", "tracecontext,baggage")
    os.environ.setdefault("AGENTSERVER_STATE_ROOT", str(Path("/tmp/foundry-procurement-agent-v2") if args.smoke else Path.cwd() / ".local_state/agentserver"))
    if args.smoke:
        print(json.dumps({
            "architecture_id": "procurement_application_v2",
            "agent": "procurement_parent_agent",
            "server": ResponsesHostServer.__name__,
            "protocol": "responses/v1",
            "azure_apply": False,
        }, sort_keys=True))
        return 0
    from azure.identity import DefaultAzureCredential
    credential = DefaultAzureCredential()
    bundle = build_hosted_bundle(FoundryRuntimeSettings.from_env(), credential=credential)
    # 未設定環境でも購買は起動できる。OBO質問には設定不足を明示する。
    identity_tool = build_identity_tool(credential) if os.getenv("PROCUREMENT_IDENTITY_TOOLBOX_ENDPOINT") else None
    # ResponsesHostServer supplies the transcript. Keep Framework history for
    # serialization/inspection, but never inject the same transcript twice.
    bundle.history_provider.load_messages = False
    server = ProcurementResponsesHostServer(bundle, identity_tool=identity_tool, configure_observability=configure_host_observability)
    server.add_middleware(_RequestCorrelationMiddleware)
    server.run(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
