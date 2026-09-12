"""OAuth WebのOTel初期化。本文・認証情報を記録せず、処理を相関IDで追跡する。"""

from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
import os
import logging
import re
from urllib.parse import unquote
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

APPLICATION_LOGGERS = ("server", "auth", "foundry_client", "procurement_flow")
provider = None
job_attributes = ContextVar("web_job_attributes", default={})


def tracer():
    return (provider or trace.get_tracer_provider()).get_tracer("procurement.oauth.web")


@contextmanager
def observe(name, **attributes):
    # 例外本文には認証URLなどが含まれ得るため、型とERROR状態だけを記録する。
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
    # 実際に通信するクライアントへ計装する。別の非計装クライアントに置き換えない。
    client = httpx.AsyncClient(**kwargs)
    if provider is not None:
        HTTPXClientInstrumentor.instrument_client(
            client, tracer_provider=provider, request_hook=_request_hook,
        )
    return client


def capture_sent_headers(response, destination):
    """送信済みResponses要求の診断用ヘッダーだけを取り出す。下流到達の証明ではない。"""
    # HTTPXのresponse hookではOTelによる注入後のrequest.headersを参照できる。
    # Authorization/Cookie/任意のbaggageは公開せず、固定した許可項目だけを表示する。
    headers = response.request.headers
    destination.clear()  # 再試行前のヘッダーを直近要求の値として残さない。
    parent = headers.get("traceparent", "")
    if re.fullmatch(r"00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}", parent):
        destination["traceparent"] = parent
    destination["baggage"] = ""
    for entry in headers.get("baggage", "").split(","):
        key, _, value = entry.strip().partition("=")
        if key == "user.id" and re.fullmatch(r"[^\s@,;=]+@[^\s@,;=]+\.[^\s@,;=]+", unquote(value)):
            destination["baggage"] = "user.id=" + value
            destination["userId"] = unquote(value)


class CorrelationFilter(logging.Filter):
    """通常ログへTrace/Span IDとジョブ属性を付ける。本文・生claimsは追加しない。"""

    def filter(self, record):
        span_context = trace.get_current_span().get_span_context()
        record.trace_id = f"{span_context.trace_id:032x}"
        record.span_id = f"{span_context.span_id:016x}"
        for key, value in job_attributes.get().items():
            setattr(record, key, value)
        return True


@asynccontextmanager
async def lifespan(app):
    global provider
    # リクエストごとに作らず、アプリの起動・終了に合わせてProviderを管理する。
    provider = TracerProvider(resource=Resource.create({"service.name": "procurement-webapp"}))
    if os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        provider.add_span_processor(BatchSpanProcessor(AzureMonitorTraceExporter()))
    # アプリのloggerだけを対象にし、Exporter自身のログが再送される循環を防ぐ。
    # LoggingHandlerが現在のTrace/Span IDをAzure Monitorのログにも関連付ける。
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.instrumentation.logging.handler import LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

    log_provider = LoggerProvider(resource=provider.resource)
    if os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        from azure.monitor.opentelemetry.exporter import AzureMonitorLogExporter
        log_provider.add_log_record_processor(BatchLogRecordProcessor(AzureMonitorLogExporter()))
    log_handler = LoggingHandler(logger_provider=log_provider)
    correlation_filter = CorrelationFilter()
    log_handler.addFilter(correlation_filter)
    console_handler = logging.StreamHandler()
    console_handler.addFilter(correlation_filter)
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s trace_id=%(trace_id)s span_id=%(span_id)s %(message)s"
    ))
    previous_log_settings = []
    for name in APPLICATION_LOGGERS:
        logger = logging.getLogger(name)
        previous_log_settings.append((logger, logger.level, logger.propagate))
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.addHandler(log_handler)
        logger.addHandler(console_handler)
    app.state.log_provider = log_provider
    app.state.provider = provider
    # このサンプルはW3C Trace ContextとBaggageを固定使用する。
    # OTEL_PROPAGATORSの設定より、この明示設定が優先される。
    previous_propagator = propagate.get_global_textmap()
    propagate.set_global_textmap(CompositePropagator([
        TraceContextTextMapPropagator(), W3CBaggagePropagator(),
    ]))
    try:
        yield
    finally:
        propagate.set_global_textmap(previous_propagator)
        for logger, level, propagate_logs in previous_log_settings:
            logger.removeHandler(log_handler)
            logger.removeHandler(console_handler)
            logger.setLevel(level)
            logger.propagate = propagate_logs
        log_provider.shutdown()
        log_handler.close()
        console_handler.close()
        provider.shutdown()
        provider = None


class Instrumentation:
    """lifespanで作成したProviderを使い、HTTPサーバーSpanを生成する。"""
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
    """ブラウザーからのTrace/BaggageをサーバーSpan生成前に破棄する。

    外部からuser.idやサンプリング判断を持ち込ませないため、最外側に登録する。
    """
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
def job_context(user_id, case_id, turn, *, email=None):
    # ContextVarで並行ジョブの属性を分離し、終了時は必ず元のContextへ戻す。
    # Baggageはサーバー間伝播用。Span属性とは別に設定する必要がある。
    attributes = {"user.id": user_id, "test.case.id": case_id, "app.turn.number": turn}
    attr_token = job_attributes.set(attributes)
    # 利用者指定の検証用途としてメールを伝播する。下流ログにも残り得る。
    # Spanの匿名化IDとは用途を分け、メール未取得時はbaggageへ設定しない。
    baggage_context = baggage.set_baggage("user.id", email) if email else baggage.remove_baggage("user.id")
    baggage_token = context.attach(baggage_context)
    try:
        yield
    finally:
        context.detach(baggage_token)
        job_attributes.reset(attr_token)
