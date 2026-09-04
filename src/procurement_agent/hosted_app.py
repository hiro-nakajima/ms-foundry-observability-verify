"""Foundry Responses host for the single Hosted parent."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from agent_framework_foundry_hosting import ResponsesHostServer
from starlette.middleware.base import BaseHTTPMiddleware

from .hosted import FoundryRuntimeSettings, authenticated_applicant_name, build_hosted_bundle
from .observability import request_correlation


class _RequestCorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        attributes = {}
        applicant_name = None
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
                turn = str(metadata.get("app.turn.number", ""))
                if turn.isascii() and turn.isdigit() and 0 < int(turn) < 1_000_000:
                    attributes["app.web.turn.number"] = int(turn)
                supplied_name = metadata.get("app.authenticated.display_name")
                normalized_name = supplied_name.strip() if isinstance(supplied_name, str) else ""
                if (0 < len(normalized_name) <= 120
                        and not any(ord(char) < 32 or ord(char) == 127 for char in normalized_name)):
                    applicant_name = normalized_name
                contract = metadata.get("app.client.contract")
                if contract == "web-json-v1":
                    attributes["app.client.contract"] = contract
            except (ValueError, AttributeError, TypeError):
                pass  # Protocol handler owns rejection; never log the raw body.
        token = request_correlation.set(attributes)
        identity_token = authenticated_applicant_name.set(applicant_name)
        try:
            return await call_next(request)
        finally:
            authenticated_applicant_name.reset(identity_token)
            request_correlation.reset(token)


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
    bundle = build_hosted_bundle(FoundryRuntimeSettings.from_env())
    # ResponsesHostServer supplies the transcript. Keep Framework history for
    # serialization/inspection, but never inject the same transcript twice.
    bundle.history_provider.load_messages = False
    server = ResponsesHostServer(bundle.parent)
    server.add_middleware(_RequestCorrelationMiddleware)
    server.run(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
