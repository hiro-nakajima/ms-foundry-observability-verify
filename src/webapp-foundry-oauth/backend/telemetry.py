"""Process-wide OTel for the OAuth wrapper; no content or credential logging."""

from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
import os
import httpx

from opentelemetry import baggage, context, propagate, trace
from opentelemetry.baggage.propagation import W3CBaggagePropagator
from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

provider = None
job_attributes = ContextVar("web_job_attributes", default={})


def tracer():
    return (provider or trace.get_tracer_provider()).get_tracer("procurement.oauth.web")


@contextmanager
def observe(name, **attributes):
    with tracer().start_as_current_span(
        name, attributes={**job_attributes.get(), **attributes},
        record_exception=False, set_status_on_exception=False,
    ) as span:
        try:
            yield span
        except Exception as exc:
            span.set_attribute("error.type", type(exc).__name__)
            span.set_status(StatusCode.ERROR)
            raise


async def _request_hook(span, request):
    if span.is_recording():
        span.set_attributes(job_attributes.get())


def http_client(**kwargs):
    client = httpx.AsyncClient(**kwargs)
    if provider is not None:
        HTTPXClientInstrumentor.instrument_client(
            client, tracer_provider=provider, request_hook=_request_hook,
        )
    return client


@asynccontextmanager
async def lifespan(app):
    global provider
    provider = TracerProvider(resource=Resource.create({"service.name": "procurement-webapp"}))
    if os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        provider.add_span_processor(BatchSpanProcessor(AzureMonitorTraceExporter()))
    app.state.provider = provider
    previous_propagator = propagate.get_global_textmap()
    propagate.set_global_textmap(CompositePropagator([
        TraceContextTextMapPropagator(), W3CBaggagePropagator(),
    ]))
    try:
        yield
    finally:
        propagate.set_global_textmap(previous_propagator)
        provider.shutdown()
        provider = None


class Instrumentation:
    def __init__(self, app):
        self.app, self.instrumented = app, None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if self.instrumented is None:
            self.instrumented = OpenTelemetryMiddleware(
                self.app, tracer_provider=scope["app"].state.provider,
                exclude_spans=["receive", "send"],
            )
        await self.instrumented(scope, receive, send)


class BrowserBoundary:
    """Discard browser trace/baggage before the server span is created."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        scope = dict(scope, headers=[(k, v) for k, v in scope["headers"]
            if k.lower() not in {b"traceparent", b"tracestate", b"baggage"}])
        token = context.attach(context.Context())
        try:
            await self.app(scope, receive, send)
        finally:
            context.detach(token)


@contextmanager
def job_context(user_id, case_id, turn):
    attributes = {"user.id": user_id, "test.case.id": case_id, "app.turn.number": turn}
    attr_token = job_attributes.set(attributes)
    baggage_token = context.attach(baggage.set_baggage("user.id", user_id))
    try:
        yield
    finally:
        context.detach(baggage_token)
        job_attributes.reset(attr_token)
