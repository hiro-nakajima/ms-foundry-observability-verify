# Plan&Execute／Functionsへの組み込みコード例

[ガイド本体](/home/hnakajima/work/foundry-procurement-agent/docs/observability-integration/README.md)の補足。以下は**移植先へ追加する設計例**であり、このリポジトリのアプリコードへ適用した変更ではない。移植先サンプルのAPIやFunctions runtimeでの動作は未検証である。コードブロック内の配置先は新設案、`planner`や`invoke`等は移植先の既存処理を渡す接続点を表す。

現行の`FoundryAgent.as_tool()`を採用する場合の登録・実呼出し・順序・再利用は、[HostedAgent補足資料](/home/hnakajima/work/foundry-procurement-agent/docs/observability-integration/hosted-agent-as-tool.md)を参照。購買Webの公開API／応答契約は[App Service補足資料](/home/hnakajima/work/foundry-procurement-agent/docs/observability-integration/appservice-procurement-changes.md)を参照。以下は移植用の提案例であり、最新ソースの全文ではない。

## 1. ソース内Toolを維持する場合

### 1.1 Hostedの初期化

移植元: [hosted_app.py:84](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted_app.py:84)、[observability.py:66](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/observability.py:66)。同じ `ResponsesHostServer` を利用する場合、共通Recorderをサンプルのpackageへコピーし、既存の起動処理へ次の順で統合する。

```python
import os

from agent_framework_foundry_hosting import ResponsesHostServer
from procurement_agent.observability import TelemetryRecorder


def serve_existing_agent(agent):
    # agentは移植先が構築した既存Agent。
    # 移植先ではプロセス起動の最初から同じ環境変数を設定する。
    os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = "false"
    os.environ.setdefault("OTEL_PROPAGATORS", "tracecontext,baggage")
    server = ResponsesHostServer(agent)
    return server


def make_telemetry():
    # 組み込み先Planner/ExecutorへこのRecorderを渡す。
    return TelemetryRecorder.for_hosted_runtime()
```

例のimport先は現在のpackage名。別packageにコピーした場合は変更する。実際の `server.run()`、既存Agent組み立て、会話state、認証、Responses metadata middlewareはサンプルの入口に接続する。独立`TelemetryRecorder()`に置き換えると、Azureへ送信する経路ではなくローカルメモリー収集になる。

同じSDKの起動処理がすでにある場合はHostをもう1つ作らず、既存のProvider／Exporterを利用する。別Frameworkでは、そのFramework自身の標準Agent／LLM／Tool計装を確認し、OTel共通APIとの接続を実装する。

### 1.2 PlannerとExecutorへのSpan挿入例

ここでは移植先のPlanを `{"id": str, "version": int, "steps": [{"id": str, "invoke": async callable}]}` に対応付ける例とする。callableが返す値は、`technical_status`、`business_status`を持つ辞書である。これは説明用のadapter contractであり、現行リポジトリや移植先にこのPlan型が存在するという意味ではない。

```python
async def execute_observed_plan(
    *, request, planner, merge_validate, telemetry, case_id, turn_number
):
    common = {"test.case.id": case_id, "app.turn.number": turn_number}

    # この例ではPlanner LLM呼出し全体を含む。
    # 現行controller.pyのplan.createは構造化Plan構築だけを含む。
    with telemetry.span("plan.create", common) as span:
        plan = await planner(request)
        telemetry.event(span, "plan.created", {
            "plan.id": plan["id"], "plan.version": plan["version"]
        })

    results = []
    for step in plan["steps"]:
        attrs = {
            **common,
            "plan.id": plan["id"],
            "plan.version": plan["version"],
            "plan.step.id": step["id"],
            "execution.attempt": 1,
            "implementation.kind": "local_function",
            "mcp.status": "NOT_RUN",
        }
        with telemetry.span("plan.step.execute", attrs) as span:
            telemetry.event(span, "step.started", {
                "plan.step.id": step["id"], "execution.attempt": 1
            })
            # invokeは既存Toolへのadapter。生例外を出さず分類結果を返す契約。
            result = await step["invoke"]()
            span.set_attributes({
                "technical.status": result["technical_status"],
                "business.status": result["business_status"],
            })
            if result["business_status"] != "SUCCESS":
                telemetry.event(span, "result.rejected", {
                    "business.status": result["business_status"]
                })
                # ここを移植先の既存の確認待ち／retry／replan処理へ接続する。
                with telemetry.span("response.generate", common) as response_span:
                    telemetry.event(response_span, "response.status", {
                        "technical.status": result["technical_status"],
                        "business.status": result["business_status"],
                    })
                return result
            telemetry.event(span, "step.completed", {"plan.step.id": step["id"]})
            results.append(result)

    with telemetry.span("merge.validate", {**common, "plan.id": plan["id"]}):
        final = await merge_validate(results)
    with telemetry.span("response.generate", common) as span:
        telemetry.event(span, "response.status", {
            "technical.status": final["technical_status"],
            "business.status": final["business_status"],
        })
    return final
```

この例にサンプルの業務制御を置換する意図はない。対応する`with`／eventを既存処理へ差し込む。retryがあるサンプルでは各attemptを別Spanにし、実際に次の呼出しを行う場合だけ`step.retry_scheduled`を記録する。Planner／mergeの例外・入力schema不正もサンプル側の既存例外処理で分類し、最終`response.status`まで記録する。

相関ContextVarを移す場合は、[hosted_app.py:25](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted_app.py:25)の本文検証とfinally resetも含める。`user.id`を残したまま次の利用者の実行に入らない。

### 1.3 Tool自動Spanの有無による違い

| 既存Toolの呼び方 | 追加する計装 |
| --- | --- |
| Agent FrameworkのFunction Toolとして標準計装付きでinvoke | 上位に`plan.step.execute`を置く。Tool内部でcurrent Spanへ件数／結果属性を追加し、同じTool用Spanは重ねない |
| 普通のPython関数を直接呼ぶ | 標準Tool Spanがないことを確認し、ToolラッパーにSpanを1つ追加 |
| 標準計装付きSearch SDKを内部で呼ぶ | Tool SpanとSDK dependencyは異なる処理範囲。同じHTTP呼出し用のmanual dependencyを重ねない |

`TelemetryRecorder.span()`は通常業務4種類とSynthetic評価用`semantic.evaluate`の合計5種類だけを許可するため、`telemetry.span("tool.invoke")`を追加するとValueErrorになる。普通の関数を直接呼ぶ場合のTool SpanはOTelのtracerで作るか、サンプルのFramework標準Toolとして登録する。

以下は**自動Tool Spanがない**async検索関数向けの小さなラッパー。`invoke`は引数なしのasync callableに既存関数と引数を束ねたもの、戻り値はlistという例である。商品と部署のどちらにも適用できる。

```python
from opentelemetry import trace


async def observe_local_search(*, tracer, tool_name, invoke, correlation):
    allowed = {
        "test.case.id", "app.turn.number", "plan.id", "plan.version",
        "plan.step.id", "execution.attempt"
    }
    attrs = {k: v for k, v in correlation.items() if k in allowed}
    attrs.update({
        "gen_ai.operation.name": "execute_tool",
        "gen_ai.tool.name": tool_name,  # アプリが登録した固定Tool名を渡す
        "implementation.kind": "local_function",
        "mcp.status": "NOT_RUN",
    })
    with tracer.start_as_current_span(
        f"execute_tool {tool_name}", attributes=attrs,
        record_exception=False, set_status_on_exception=False,
    ) as span:
        span.add_event("tool.started")
        try:
            rows = await invoke()
            if not isinstance(rows, list):
                span.set_attributes({
                    "technical.status": "SUCCESS",
                    "parse.status": "SCHEMA_INVALID",
                    "business.status": "BLOCKED",
                    "reason.code": "tool_output_schema_invalid",
                })
                span.add_event("tool.output_rejected")
                return {"technical_status": "SUCCESS", "business_status": "BLOCKED"}
        except Exception as exc:
            # モデル入力／token／URLを含み得る例外本文は記録しない。
            span.set_status(trace.StatusCode.ERROR)
            span.set_attributes({
                "error.type": type(exc).__name__,
                "technical.status": "ERROR",
                "business.status": "BLOCKED",
                "reason.code": "tool_execution_failed",
            })
            span.add_event("tool.failed")
            return {"technical_status": "ERROR", "business_status": "BLOCKED"}
        business = "SUCCESS" if rows else "NOT_FOUND"
        span.set_attributes({
            "technical.status": "SUCCESS", "business.status": business,
            "app.tool.result_count": len(rows), "parse.status": "SUCCESS",
        })
        span.add_event("tool.completed")
        return {"technical_status": "SUCCESS", "business_status": business, "rows": rows}
```

Hostedでは `TelemetryRecorder.for_hosted_runtime().tracer` のように同じProviderから得たtracerを渡す。rowsは業務処理へ返すがSpanには保存しない。実際のサンプルに合わせてtimeout、403、index不在の分類を増やし、Toolに存在しないMCP／AI Search statusを付けない。

## 2. App Serviceへ通常ログも追加したい場合

現行WebはTraceExporterのみである。[procurement.py:190](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement.py:190)のlifespanへ以下の初期化を統合すると、選択した業務loggerの記録をOTel Logsへ送る構成を作れる。

これは追加案であり、通常ログが不要なら入れない。同じAzure Monitor ExporterパッケージのLogExporterを使う。OTel LoggingHandler等のAPIは採用バージョンで確認する。[Azure Monitor Python Exporterの公式例](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/monitor/azure-monitor-opentelemetry-exporter/README.md)

```python
import logging

from azure.monitor.opentelemetry.exporter import AzureMonitorLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor


def build_business_logger(resource, connection_string):
    # lifespanで1回呼び出す。request処理から繰り返し呼ばない。
    provider = LoggerProvider(resource=resource)
    provider.add_log_record_processor(BatchLogRecordProcessor(
        AzureMonitorLogExporter(connection_string=connection_string)
    ))
    logger = logging.getLogger("procurement.web.business")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = LoggingHandler(level=logging.INFO, logger_provider=provider)
    logger.addHandler(handler)
    return provider, logger, handler
```

初期化時にはTraceと同じ`Resource`を渡す。activeなWeb Spanの中で例えば次のように記録する。

```python
def log_turn_finished(logger, *, case_id, turn_number, business_status):
    logger.info("procurement.turn.finished", extra={
        "test.case.id": case_id,
        "app.turn.number": turn_number,
        "business.status": business_status,
    })
```

handlerがactive contextからTrace ID／Span IDを取り込む。業務statusは検証済みenum等を渡す。`extra={"result": raw_response}`や`logger.exception(...)`で本文を広く送らない。

終了時は `logger.removeHandler(handler)`、`handler.close()`、`provider.shutdown()` を既存lifespanのfinallyへ配置する。root loggerへhandlerを付けるとSDKや旧OAuthサンプルの診断文字列も対象になるため、この例は新しい業務loggerだけを対象にする。

## 3. Functionsに新しい観測モジュールを作る場合

### 3.1 依存と初期化方式の選択

次の追加依存は、このリポジトリで使用しているOTel系列に合わせた**手動計装案**。Functions独立環境での依存解決・実行確認は未実施である。既存のFunctions requirementsへ統合し、Functions用constraintsを作る場合はそのファイルもZIPへ入れる。

```text
# src/functions-mcp-selfhosted/requirements.txtへの追加案
opentelemetry-api==1.43.0
opentelemetry-sdk==1.43.0
opentelemetry-instrumentation-asgi==0.64b0
azure-monitor-opentelemetry-exporter==1.0.0b56
```

Functions HostとPython Workerの初期化担当を次のように選ぶ。

| 方式 | Worker側の設定 | この節の手動Provider例 |
| --- | --- | --- |
| 手動のアプリ計装 | 独自Provider／Trace・LogExporterとASGIを構成 | 使用する |
| Python Workerの自動Azure Monitor計装 | `azure-monitor-opentelemetry`と`PYTHON_APPLICATIONINSIGHTS_ENABLE_TELEMETRY=true`等、採用runtimeの公式設定 | 使用しない。既存Providerを利用する |

手動方式の例では、Workerが既に自動でProvider／LogExporterを作る設定を有効にしない。通常ログの対象を独立したloggerへ限定し`propagate=False`にすることで、この業務loggerの同一記録を通常root経路にも渡すことを避ける。Host自体の診断ログは別のままである。

HostもOTelで観測する段階では、既存`host.json`の`extensions.http.routePrefix`を残して次を追加する。

```json
{
  "version": "2.0",
  "telemetryMode": "OpenTelemetry",
  "extensions": {"http": {"routePrefix": ""}}
}
```

送信先はFunctions App Settingsの`APPLICATIONINSIGHTS_CONNECTION_STRING`。HostとWorkerのSpanは異なる実行層として存在し得るため、単に2つあることを全て重複としない。同じASGI境界を2つのinstrumentorで囲っていないか、同じloggerを2つの経路で送っていないかを照合する。Host mode・Worker flagの意味は[Functions公式設定](https://learn.microsoft.com/en-us/azure/azure-functions/opentelemetry-howto?pivots=programming-language-python)と移植先runtimeで確認する。

### 3.2 手動方式の新規モジュール例

配置案: Functionsルートの新規 `procurement_observability.py`。Hostedのモジュールとは別processなので別のProviderでよい。ローカルで接続文字列がない場合を黙ってAzure送信成功としないため、この例は環境変数を必須とする。

```python
import atexit
import logging
import os

from azure.monitor.opentelemetry.exporter import (
    AzureMonitorLogExporter, AzureMonitorTraceExporter,
)
from opentelemetry import propagate
from opentelemetry.baggage.propagation import W3CBaggagePropagator
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

# module import時にprocessごとに1回。create_mcp_server()の中には置かない。
connection_string = os.environ["APPLICATIONINSIGHTS_CONNECTION_STRING"]
resource = Resource.create({"service.name": "procurement-functions-mcp"})
provider = TracerProvider(resource=resource)
provider.add_span_processor(BatchSpanProcessor(
    AzureMonitorTraceExporter(connection_string=connection_string)
))
tracer = provider.get_tracer("procurement.functions")
propagate.set_global_textmap(CompositePropagator([
    TraceContextTextMapPropagator(), W3CBaggagePropagator(),
]))

log_provider = LoggerProvider(resource=resource)
log_provider.add_log_record_processor(BatchLogRecordProcessor(
    AzureMonitorLogExporter(connection_string=connection_string)
))
logger = logging.getLogger("procurement.functions.business")
logger.setLevel(logging.INFO)
logger.propagate = False
log_handler = LoggingHandler(level=logging.INFO, logger_provider=log_provider)
logger.addHandler(log_handler)


def shutdown_observability():
    logger.removeHandler(log_handler)
    log_handler.close()
    log_provider.shutdown()
    provider.shutdown()


atexit.register(shutdown_observability)
```

このProviderはglobalへ登録しないため、ASGI、Tool、追加のHTTP clientへ明示的に渡す。Workerの既存Providerを使う方式ではこのモジュールのProvider生成を採用しない。`atexit`は正常終了用であり、Functionsの強制終了時にbufferが必ず送られる保証ではない。cold start／停止時も含め実環境で確認する。

### 3.3 Functions入口への組み込み

変更位置: [mcp_handler/__init__.py:1](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_handler/__init__.py:1)。既存`AsgiMiddleware`に渡すアプリをOTel ASGI wrapperで囲む例。

```python
import azure.functions as func
from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware

from procurement_observability import provider
from mcp_server import app as mcp_asgi_app

instrumented_app = OpenTelemetryMiddleware(
    mcp_asgi_app,
    tracer_provider=provider,
    exclude_spans=["receive", "send"],
)
main = func.AsgiMiddleware(instrumented_app).main
```

HTTP headerにある`traceparent`／`tracestate`／`baggage`を受信contextへ取り込み、Tool Spanの親に利用する。ブラウザ用 `_BrowserBoundary` はここへコピーしない。Functions APIの認証・認可は既存のAPI境界で行い、baggageを本人確認に使わない。

### 3.4 商品検索Tool内部へ記録する例

次の例は、ソース内の既存検索をasync callableとして渡して計装する。`whoami`とは別に追加する購買Tool用であり、検索API／DBの実装は含まない。`@mcp.tool()`関数からこのhelperを呼ぶ。

```python
import re

from opentelemetry import baggage, trace
from procurement_observability import logger, tracer


async def run_search_tool(*, tool_name, search):
    # tool_nameはアプリが定義した固定のcatalog_search/department_search等。
    attrs = {
        "gen_ai.operation.name": "execute_tool",
        "gen_ai.tool.name": tool_name,
        "mcp.method": "tools/call",
    }
    user = baggage.get_baggage("user.id")
    if isinstance(user, str) and re.fullmatch(r"[a-f0-9]{64}", user):
        attrs["user.id"] = user
    with tracer.start_as_current_span(
        f"execute_tool {tool_name}", attributes=attrs,
        record_exception=False, set_status_on_exception=False,
    ) as span:
        span.add_event("tool.started")
        try:
            rows = await search()
            if not isinstance(rows, list):
                span.set_attributes({
                    "technical.status": "SUCCESS", "parse.status": "SCHEMA_INVALID",
                    "business.status": "BLOCKED", "reason.code": "invalid_search_result",
                })
                span.add_event("tool.output_rejected")
                return {"technical_status": "SUCCESS", "business_status": "BLOCKED"}
        except Exception as exc:
            error_type = type(exc).__name__
            span.set_status(trace.StatusCode.ERROR)
            span.set_attributes({
                "error.type": error_type, "technical.status": "ERROR",
                "business.status": "BLOCKED", "reason.code": "search_failed",
            })
            logger.warning("procurement.tool.failed", extra={
                "gen_ai.tool.name": tool_name, "error.type": error_type,
                "reason.code": "search_failed",
            })
            return {"technical_status": "ERROR", "business_status": "BLOCKED"}
        business = "SUCCESS" if rows else "NOT_FOUND"
        span.set_attributes({
            "technical.status": "SUCCESS", "business.status": business,
            "app.tool.result_count": len(rows),
        })
        span.add_event("tool.completed")
        logger.info("procurement.tool.completed", extra={
            "gen_ai.tool.name": tool_name, "business.status": business,
            "app.tool.result_count": len(rows),
        })
        return {"technical_status": "SUCCESS", "business_status": business, "rows": rows}
```

例えば既存のasync商品検索へつなぐ場合は、Tool関数内で `await run_search_tool(tool_name="catalog_search", search=lambda: existing_search(query))` を呼ぶ。同期検索をasync関数内でそのまま実行するとevent loopを塞ぐため、既存の同期Toolを維持するか、サンプルの実行方式に合わせてadapterを作る。

結果JSON内の技術エラーがMCP protocolの `isError=true`へ自動変換されるわけではない。移植先のMCPクライアントが読む契約に合わせて、Tool戻り値／エラー形式を設計する。HTTP requestを受信しただけでMCP成功statusを記録しない。

### 3.5 MCP本文の_metaで伝播する場合

上のHTTP ASGI wrapperだけではJSON-RPCの `params._meta` は読まない。HTTP carrierで親Spanが取得できず、採用MCPクライアントが `_meta.traceparent` を送る構成では、Tool dispatchでそのcarrierを抽出する処理が必要になる。

以下は受信carrierを取り出す接続例。**HTTP contextを優先し、HTTPの親がない場合だけ `_meta` を利用する方式**を示す。両方が異なるTraceを示す場合は、親を二重に設定せず必要に応じてSpan Linkで別相関を保持する。

```python
from opentelemetry import context, propagate, trace


def incoming_tool_context(ctx):
    # HTTP Spanがあればそのcontextを継続。
    # HTTP headerなしでもASGIは新しいSpanを作るため、この条件だけで
    # _meta fallbackは選択しない。実際のHTTP traceparentの有無を確認する。
    request = getattr(ctx.request_context, "request", None)
    headers = getattr(request, "headers", {})
    http_carrier = {
        key: headers[key] for key in ("traceparent", "tracestate") if key in headers
    }
    extracted_http = propagate.extract(http_carrier, context=context.Context())
    if trace.get_current_span(extracted_http).get_span_context().is_valid:
        return context.get_current()

    meta = ctx.request_context.meta
    values = meta.model_dump() if hasattr(meta, "model_dump") else (meta or {})
    carrier = {
        key: values[key] for key in ("traceparent", "tracestate", "baggage")
        if isinstance(values, dict) and isinstance(values.get(key), str)
    }
    parent = propagate.extract(carrier, context=context.Context())
    if trace.get_current_span(parent).get_span_context().is_valid:
        return parent
    return context.get_current()
```

この関数が返したcontextを、Tool helperを呼ぶ前に `context.attach()`し、finallyで`context.detach()`する。HTTPの親がないときに `_meta` を親に採用すると、ASGIが生成したローカルrootとToolのTraceが別になることがある。必要ならそのHTTP spanをLinkで関連付ける。これは不明なTraceを同一Traceとして扱うものではない。

`ctx.request_context.request`／`meta`はローカルのMCP 1.29.1の型で確認した。Functions側requirementsは `mcp>=1.28,<2` の範囲なので、移植時には実際の解決バージョン、HTTP／stdio等のtransport、元の相関形式で照合する。プロバイダー管理MCPが `_meta` を送る保証はない。[Agent Frameworkの伝播範囲](https://learn.microsoft.com/en-us/agent-framework/agents/observability#mcp-trace-propagation)

### 3.6 Search／外部HTTPの計装

新しい検索ToolがHTTPを呼ぶ場合は、実際に使用するclientだけを同じ`provider`で計装する。例えばHTTPXなら `opentelemetry-instrumentation-httpx` を追加して `HTTPXClientInstrumentor.instrument_client(http, tracer_provider=provider)` を使う。requestsなら対応するinstrumentorを採用する。自動dependency Spanを作る場合は同じHTTP通信をmanual CLIENT Spanで重ねない。

検索文、Authorization、返却document本文のキャプチャは必要ない。Tool Spanには件数・検索対象・statusを記録し、HTTP dependencyにはstatus／duration／相関を任せる。Functionsへ移した検索がローカルファイルだけを読むなら、実在しないAI Search dependencyを作らない。

## 4. この例を適用する前後で確認するもの

1. processごとにProvider／Exporterが1つの設計で初期化されること。HostedとFunctionsは別processなので各自のProviderが必要。
2. 自動Tool計装の有無を確認し、manual Tool Spanを重ねていないこと。
3. 使用するHTTP client、ASGI、Toolで同じProviderとactive contextを使うこと。
4. 元サンプルのretry／replan／会話state／認証契約を維持し、観測のために成功条件を変えていないこと。
5. 新規FunctionsモジュールとrequirementsがZIPに入っていること。
6. ローカルExporterでSpanとeventを確認後、Azure上で受信、保存、本文非記録、重複の有無を照合すること。

本資料のPythonコード例9ブロックはcompileによる構文確認を行った。接続文字列を必要とするProvider初期化、Functions Hostの起動、Search／Graph／Foundry呼出し、Azureへの送信は実行していない。
