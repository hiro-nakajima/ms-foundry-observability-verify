"""Application spans and content profiles; Framework owns Agent/Chat/Function spans."""

from __future__ import annotations

import hashlib
import json
import re
from contextvars import ContextVar
from contextlib import contextmanager
from enum import Enum
from typing import Any, Iterator, Literal

from opentelemetry import baggage, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider, SpanProcessor, Event
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

CUSTOM_SPAN_BOUNDARIES = {
    "plan.create", "plan.step.execute", "merge.validate", "semantic.evaluate",
    "response.generate",
}
request_correlation: ContextVar[dict[str, Any]] = ContextVar("procurement_request_correlation", default={})


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


def configure_host_observability(**kwargs):
    from azure.ai.agentserver.core import configure_observability
    configure_observability(**kwargs)
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider) and not getattr(provider, "_procurement_mcp_privacy", False):
        provider.add_span_processor(McpPrivacyProcessor())
        provider._procurement_mcp_privacy = True


def current_request_attributes() -> dict[str, Any]:
    attributes = dict(request_correlation.get())
    user = baggage.get_baggage("user.id")
    if "user.id" not in attributes and isinstance(user, str) and re.fullmatch(r"[a-f0-9]{64}", user):
        attributes["user.id"] = user
    return attributes
FORBIDDEN_STANDARD_DUPLICATES = {"agent.invoke", "chat", "function", "tool.invoke", "agent_as_tool"}
ALWAYS_SEARCHABLE = {
    "test.case.id", "app.session.id", "app.turn.number",
    "plan.id", "plan.version", "plan.step.id", "execution.attempt",
    "agent.role", "agent.definition.id", "agent.definition.version", "implementation.kind",
    "toolbox.name", "search.index.name", "search.index.version",
    "mcp.server.label", "mcp.method", "parent.invocation.id", "remote.task.id",
}


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def safe_value(value: Any) -> str | bool | int | float | list[str]:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return [str(item.value if isinstance(item, Enum) else item) for item in value]
    return str(value)


def sanitize_attributes(attributes: dict[str, Any] | None) -> dict[str, Any]:
    safe = {}
    for key, value in (attributes or {}).items():
        folded = key.casefold()
        if any(token in folded for token in ("secret", "password", "token", "chain_of_thought")):
            continue
        safe[key] = safe_value(value)
    return safe


class TelemetryRecorder:
    def __init__(
        self, *,
        content_profile: Literal["synthetic-content-on", "production-like-content-off"] = "production-like-content-off",
        synthetic_environment: bool = False,
        tracer_provider: trace.TracerProvider | None = None,
    ) -> None:
        if content_profile == "synthetic-content-on" and not synthetic_environment:
            raise ValueError("synthetic-content-on requires an explicitly synthetic environment")
        self.content_profile = content_profile
        self.exporter: InMemorySpanExporter | None
        self.uses_global_provider = tracer_provider is not None
        if tracer_provider is None:
            self.exporter = InMemorySpanExporter()
            self.provider = TracerProvider(resource=Resource.create({"service.name": "foundry-procurement-agent"}))
            self.provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        else:
            self.exporter = None
            self.provider = tracer_provider
        self.tracer = self.provider.get_tracer("procurement.application", "2.0.0")

    @classmethod
    def for_hosted_runtime(cls) -> "TelemetryRecorder":
        """Emit through the host-configured global OTel provider/App Insights exporter."""
        return cls(tracer_provider=trace.get_tracer_provider())

    @property
    def record_raw_content(self) -> bool:
        return self.content_profile == "synthetic-content-on"

    @contextmanager
    def span(self, name: str, attributes: dict[str, Any] | None = None) -> Iterator[trace.Span]:
        if name not in CUSTOM_SPAN_BOUNDARIES:
            raise ValueError(f"custom span would duplicate Framework or is not approved: {name}")
        with self.tracer.start_as_current_span(name, attributes=sanitize_attributes({**current_request_attributes(), **(attributes or {})})) as span:
            yield span

    @staticmethod
    def event(span: trace.Span, name: str, attributes: dict[str, Any] | None = None) -> None:
        span.add_event(name, sanitize_attributes(attributes))

    def protect_content(self, category: str, value: Any) -> dict[str, Any]:
        serialized = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        result: dict[str, Any] = {"category": category, "sha256": sha256(serialized), "length": len(serialized)}
        if self.record_raw_content:
            result["raw"] = serialized
        return result

    def finished_spans(self):
        if self.exporter is None:
            raise RuntimeError("hosted recorder exports through the global provider; query the configured backend")
        return self.exporter.get_finished_spans()


def truncate_export(value: str, limit: int) -> dict[str, Any]:
    if limit < 0:
        raise ValueError("limit must be non-negative")
    truncated = len(value) > limit
    return {
        "original_length": len(value), "stored_length": min(len(value), limit),
        "truncated": truncated, "value": value[:limit],
        "first_truncated_position": limit if truncated else None,
    }
