"""OpenTelemetry helpers for observable execution state, never hidden reasoning."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from enum import Enum
from typing import Any, Iterator

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


REQUIRED_SPAN_BOUNDARIES = {
    "agent.invoke",
    "plan.create",
    "plan.resume",
    "plan.step.execute",
    "agent_as_tool.procurement_specialist",
    "agent_as_tool.drafting_specialist",
    "skill.request_check",
    "script.calculate_request",
    "governance.pre_input",
    "governance.pre_tool",
    "governance.post_tool",
    "governance.pre_output",
    "validation",
    "response.generate",
}

FORBIDDEN_ATTRIBUTE_FRAGMENTS = {
    "raw",
    "user_input",
    "system_prompt",
    "tool_arguments",
    "tool_output",
    "content",
    "secret",
    "password",
}


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_value(value: Any) -> str | bool | int | float | list[str]:
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return [str(item.value if isinstance(item, Enum) else item) for item in value]
    return str(value)


def sanitize_attributes(attributes: dict[str, Any] | None) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in (attributes or {}).items():
        folded = key.casefold()
        if any(fragment in folded for fragment in FORBIDDEN_ATTRIBUTE_FRAGMENTS):
            continue
        safe[key] = _safe_value(value)
    return safe


class TelemetryRecorder:
    """Isolated in-memory OTel provider used locally and by trace tests."""

    def __init__(
        self,
        *,
        service_name: str = "foundry-procurement-agent",
        synthetic_environment: bool = True,
        record_raw_content: bool = False,
    ) -> None:
        if record_raw_content and not synthetic_environment:
            raise ValueError("raw content recording is allowed only in a synthetic environment")
        self.synthetic_environment = synthetic_environment
        self.record_raw_content = record_raw_content
        self.content_store: dict[str, str] = {}
        self.exporter = InMemorySpanExporter()
        self.provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        self.provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.tracer = self.provider.get_tracer("procurement_agent", "0.1.0")

    @contextmanager
    def span(self, name: str, attributes: dict[str, Any] | None = None) -> Iterator[trace.Span]:
        with self.tracer.start_as_current_span(name, attributes=sanitize_attributes(attributes)) as span:
            yield span

    @staticmethod
    def add_event(span: trace.Span, name: str, attributes: dict[str, Any] | None = None) -> None:
        span.add_event(name, sanitize_attributes(attributes))

    @staticmethod
    def current_trace_id() -> str | None:
        current = trace.get_current_span().get_span_context()
        return f"{current.trace_id:032x}" if current.is_valid else None

    def protect_content(self, category: str, value: Any) -> dict[str, Any]:
        serialized = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        digest = _hash(serialized)
        reference = f"protected:{category}:{digest[:16]}"
        if self.record_raw_content:
            self.content_store[reference] = serialized
        return {
            "ref": reference,
            "hash": digest,
            "raw_recorded": self.record_raw_content,
        }

    def finished_spans(self):
        return self.exporter.get_finished_spans()

    def safe_baggage(self, values: dict[str, Any]) -> dict[str, str]:
        safe = sanitize_attributes(values)
        return {key: str(value) for key, value in safe.items()}
