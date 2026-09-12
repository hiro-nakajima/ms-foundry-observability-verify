# Plan&Execute／Functionsへの組み込みコード例

更新日: 2026-09-08。[統合ガイド](../../observability-integration/README.md)の補足。以下のadapterや検索関数は**移植先への挿入例**であり、未提供サンプルのAPIを確認したものではない。現在のWeb／OBO Functionsの実装済み部分と、任意の追加案を分けて記載する。

現行HostedのAgent Tool呼び出しは[順序資料](../../observability-integration/hosted-agent-as-tool.md)、旧OAuth Webの購買向け変更は[App Service資料](appservice-procurement-changes.md)、正確な関数行番号は[ソース索引](source-map.md)を参照。

## 1. ソース内Toolを維持する場合

### 1.1 Hostedの初期化

移植元: [hosted_app.py:150](../../../src/hosted-agent/procurement_agent/hosted_app.py)、[observability.py:94](../../../src/hosted-agent/procurement_agent/observability.py)。同じ `ResponsesHostServer` を利用する場合、共通Recorderをサンプルのpackageへコピーし、既存の起動処理へ次の順で統合する。

```python
import os

from agent_framework_foundry_hosting import ResponsesHostServer
from procurement_agent.observability import TelemetryRecorder, configure_host_observability


def serve_existing_agent(agent):
    # agentは移植先が構築した既存Agent。
    # 移植先ではプロセス起動の最初から同じ環境変数を設定する。
    os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = "false"
    os.environ.setdefault("OTEL_PROPAGATORS", "tracecontext,baggage")
    server = ResponsesHostServer(agent, configure_observability=configure_host_observability)
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

相関ContextVarを移す場合は、[hosted_app.py:26](../../../src/hosted-agent/procurement_agent/hosted_app.py)の本文検証とfinally resetも含める。`user.id`を残したまま次の利用者の実行に入らない。

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

現行WebはTraceExporterのみである。[telemetry.py:55](../../../src/webapp-foundry-oauth/backend/telemetry.py)のlifespanへ以下の初期化を統合すると、選択した業務loggerの記録をOTel Logsへ送る構成を作れる。

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

## 3. 実装済みFunctions観測モジュールを再利用する

### 3.1 現在の初期化と依存

`src/functions-mcp-selfhosted/mcp_telemetry.py` はすでに配布済みで、workerごとにProvider／Azure Monitor TraceExporterを生成する。`requirements.txt` の現行指定は次のとおり。これらを追加するだけで検索Toolが実装されるわけではない。

```text
opentelemetry-sdk==1.43.0
azure-monitor-opentelemetry-exporter==1.0.0b56
```

サービス名はprocurement-obo-functions。送信先はAPPLICATIONINSIGHTS_CONNECTION_STRING。設定がないローカル実行ではAzure exporterが付かないため、Spanを作れたこととAzureへ届いたことを分けて確認する。

現在は `whoami()` のMCP境界に `mcp.whoami`、その内側に `auth.obo.exchange` と `graph.me` を置く。OTel LogExporterや追加ASGI instrumentorをFunctionsへ一律に入れる実装ではない。Functions Host自体の診断とこのPython workerの手動Spanは別の観測層である。

### 3.2 既存whoamiの組み込み方（要点）

次は `mcp_server.py` にある処理の関係を示す抜粋であり、既存の戻り値・Token取得処理の代替ではない。

```python
from mcp_telemetry import carrier_from_mcp, step, record_outcome


def observed_whoami(ctx, build_result):
    # build_resultは既存のToken検証・OBO・Graph処理を束ねたcallable。
    with step("mcp.whoami", carrier=carrier_from_mcp(ctx)) as span:
        result = build_result()
        record_outcome(span, result)
        return result
```

`carrier_from_mcp()` はMCP request metadataのtraceparentを検査し、`step()` が親contextとして抽出する。HTTP headerのtraceparentとは異なるcarrierである。採用SDKが `_meta.traceparent` を送ることを実際のTraceで確認する。HTTP自動計装を別途導入する場合は、HTTP SpanとMCP metadataの親が異なる状況を調べ、二重Spanや誤った親子付けを避ける。

`record_outcome()` はwhoamiのauth_mode／error／subjectHashに依存する。商品検索や部署検索へそのままコピーせず、それぞれの結果contractからstatus・件数等を付与する。

### 3.3 検索ToolをFunctionsへ新設する場合の挿入例

現在のFunctionsには商品／部署検索は存在しない。次は既存同期検索関数を移す際のwrapper案。Tool自動Spanがない場合に使用する。

```python
from opentelemetry.trace import StatusCode
from mcp_telemetry import carrier_from_mcp, step


def run_search(ctx, *, registered_tool_name, search):
    # registered_tool_nameはアプリ側の固定名。利用者入力をSpan名に使わない。
    with step("mcp.search", carrier=carrier_from_mcp(ctx)) as span:
        span.set_attribute("gen_ai.tool.name", registered_tool_name)
        try:
            rows = search()
            if not isinstance(rows, list):
                span.set_attributes({
                    "technical.status": "SUCCESS", "parse.status": "SCHEMA_INVALID",
                    "business.status": "BLOCKED",
                })
                return {"technical_status": "SUCCESS", "business_status": "BLOCKED"}
        except Exception as exc:
            span.set_status(StatusCode.ERROR)
            span.set_attributes({
                "error.type": type(exc).__name__, "technical.status": "ERROR",
                "business.status": "BLOCKED",
            })
            return {"technical_status": "ERROR", "business_status": "BLOCKED"}
        business = "SUCCESS" if rows else "NOT_FOUND"
        span.set_attributes({
            "technical.status": "SUCCESS", "business.status": business,
            "app.tool.result_count": len(rows),
        })
        return {"technical_status": "SUCCESS", "business_status": business, "rows": rows}
```

検索結果のrowsは業務へ返すがSpanに保存しない。既存async Toolへつなぐ場合は元のasync処理方式を維持する。同期検索を無条件にasync関数へ入れない。戻り値のtechnical_statusがMCP protocolのisErrorへ自動変換されるわけではないため、移植先のTool契約へ合わせる。

新しいMCP Toolを追加する場合はserver登録、Toolboxのallowed_tools、Agent側のTool一覧選択、戻り値schema、配布ZIPをまとめて変更する。whoamiだけの現在のToolboxを指したままでは新規検索Toolを呼べない。

外部HTTP/検索SDKを計装するときは実際に使用するclientを同じProviderへ接続する。標準dependencyと同じHTTP通信を手動Spanでも囲まない。ローカルファイル検索にAI Search dependencyを作らない。

## 4. Webへの最小統合単位

旧OAuth Webには `telemetry.py` を組み込み、FastAPI生成で `lifespan=telemetry.lifespan` を指定する。middlewareはBrowserBoundaryがInstrumentationの外側になるよう構成する。`telemetry.http_client()` を会話作成／Responses等の実際のHTTPX client生成に使う。

```python
import telemetry


async def run_existing_job(*, user_hash, case_id, turn, acquire_headers, invoke):
    with telemetry.job_context(user_hash, case_id, turn):
        with telemetry.observe("web.chat.job"):
            with telemetry.observe("auth.foundry.token"):
                headers = await acquire_headers()
            with telemetry.observe("procurement.agent.invoke"):
                return await invoke(headers)
```

これはSpan境界の挿入例。実際には認証・owner検査・Foundry会話管理・metadata・同意再開を `server.py`／`procurement_flow.py` に従って統合する。user_hashはBrowserが自己申告した値ではなく、EasyAuthのtid/oidから作る。氏名をWeb metadataに追加しない。

## 5. 適用前後の確認

1. HostedはSDK Providerを再利用し、Web／Functionsは各processのProviderを一度構成する。
2. SDK標準Tool Spanと手動Tool Span、HTTP dependencyの重複を確認する。
3. retry、replan、入力不足、業務失敗を既存の意味で記録し、計装のために業務順序を変えない。
4. user.id、case、turn、会話／応答IDを検査し、request終了でContextVarを解除する。
5. 新規モジュールと依存が配布ZIPに入り、送信先設定が存在することを確認する。
6. Azureで実際のTrace、本文非記録、本人一致／不一致、同意／省略／null消去を検証する。

本書のPython例は構文確認を行った。移植先サンプルへの適用実行や例のAzure送信は未検証。現リポジトリの配布済み実装・実Web OBOの検証は[検証記録](../../report/validation-results-2026-09-08-obo.md)で扱う。
