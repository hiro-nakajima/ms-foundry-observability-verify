"""Small process-wide Functions trace provider; never export credentials/content."""
from contextlib import contextmanager
import hashlib
import os
import re

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

provider = TracerProvider(resource=Resource.create({"service.name": "procurement-obo-functions"}))
if os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
    provider.add_span_processor(BatchSpanProcessor(AzureMonitorTraceExporter()))
tracer = provider.get_tracer("procurement.obo.functions")


@contextmanager
def step(name, carrier=None):
    context = TraceContextTextMapPropagator().extract(carrier) if carrier else None
    with tracer.start_as_current_span(name, context=context, record_exception=False,
                                     set_status_on_exception=False) as span:
        try:
            yield span
        except Exception as exc:
            span.set_attribute("error.type", type(exc).__name__)
            span.set_status(trace.StatusCode.ERROR)
            raise


def carrier_from_mcp(ctx):
    meta = getattr(getattr(ctx, "request_context", None), "meta", None)
    meta = meta.model_dump() if hasattr(meta, "model_dump") else meta
    if not isinstance(meta, dict):
        return {}
    parent = meta.get("traceparent")
    return {"traceparent": parent} if isinstance(parent, str) and re.fullmatch(r"00-[a-f0-9]{32}-[a-f0-9]{16}-[a-f0-9]{2}", parent) else {}


def record_outcome(span, result):
    success = result.get("auth_mode") == "obo" and not result.get("error")
    span.set_attribute("app.identity.lookup.status", "SUCCESS" if success else "FAILED")
    if success:
        subject_hash = (result.get("user") or {}).get("subjectHash")
        if subject_hash:
            span.set_attribute("user.id", subject_hash)
    else:
        span.set_status(trace.StatusCode.ERROR)
