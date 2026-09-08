"""Foundry Responses host for the single Hosted parent."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from agent_framework_foundry_hosting import ResponsesHostServer
from starlette.middleware.base import BaseHTTPMiddleware

from .hosted import FoundryRuntimeSettings, authenticated_applicant_name, applicant_lookup_status, build_hosted_bundle
from .observability import request_correlation, configure_host_observability
from .identity import IdentityResult, invoke_identity, lookup_requested, identity_result


_VALIDATION_PROFILES = {
    "TV-02", "TV-03", "SD-03", "SD-05", "MA-04", "MA-05",
    "S1-HEALTHY", "S5-HEALTHY", "S5-SMALL", "S5-32768", "S5-65536",
    "S5-OVER",
}


class _RequestCorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        attributes = {}
        applicant_name = None
        lookup_status = None
        lookup_enabled = False
        if request.method == "POST" and request.url.path.endswith("/responses"):
            try:
                body = await request.json()
                metadata = body.get("metadata") or {}
                lookup_enabled = metadata.get("app.identity.lookup") == "true"
                conversation = body.get("conversation")
                if isinstance(conversation, dict):
                    conversation = conversation.get("id")
                if isinstance(conversation, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,200}", conversation):
                    attributes["gen_ai.conversation.id"] = conversation
                case = metadata.get("test.case.id", "")
                if isinstance(case, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", case):
                    attributes["test.case.id"] = case
                for key, target, pattern in (
                    ("app.user.id", "user.id", r"[a-f0-9]{64}"),
                    ("app.web.trace_id", "app.web.trace_id", r"[a-f0-9]{32}"),
                ):
                    value = metadata.get(key)
                    if isinstance(value, str) and re.fullmatch(pattern, value):
                        attributes[target] = value
                turn = str(metadata.get("app.turn.number", ""))
                if turn.isascii() and turn.isdigit() and 0 < int(turn) < 1_000_000:
                    attributes["app.web.turn.number"] = int(turn)
                supplied_name = metadata.get("app.authenticated.display_name")
                normalized_name = supplied_name.strip() if isinstance(supplied_name, str) else ""
                if (0 < len(normalized_name) <= 120
                        and not any(ord(char) < 32 or ord(char) == 127 for char in normalized_name)):
                    applicant_name = normalized_name
                supplied_status = metadata.get("app.identity.lookup.status")
                if supplied_status in {"SUCCESS", "SKIPPED", "FAILED"}:
                    lookup_status = supplied_status
                    if lookup_status != "SUCCESS":
                        applicant_name = None
                    elif not applicant_name or metadata.get("app.identity.source") != "graph_obo":
                        lookup_status, applicant_name = "FAILED", None
                    attributes["app.identity.lookup.status"] = lookup_status
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
        identity_token = authenticated_applicant_name.set(applicant_name)
        lookup_token = applicant_lookup_status.set(lookup_status)
        requested_token = lookup_requested.set(lookup_enabled)
        try:
            return await call_next(request)
        finally:
            authenticated_applicant_name.reset(identity_token)
            applicant_lookup_status.reset(lookup_token)
            lookup_requested.reset(requested_token)
            request_correlation.reset(token)


class ProcurementResponsesHostServer(ResponsesHostServer):
    """Resolve identity before procurement; emit native OAuth items when paused.

    The pinned hosting SDK only bridges connect-time consent on the parent
    Agent. This small protocol adapter also covers the nested identity Tool.
    A paused request has not mutated procurement state. The Web wrapper resends
    the original message on the same conversation after consent.
    """
    def __init__(self, bundle, **kwargs):
        self.identity_tool = bundle.identity_tool
        super().__init__(bundle.parent, **kwargs)

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
    server = ProcurementResponsesHostServer(bundle, configure_observability=configure_host_observability)
    server.add_middleware(_RequestCorrelationMiddleware)
    server.run(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
