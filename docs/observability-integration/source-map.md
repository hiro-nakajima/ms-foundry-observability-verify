# ソース索引と調査時点のファイル照合

2026-09-06の作業ツリーから生成。移植先サンプルの索引ではない。

本体: [docs/observability-integration/README.md](/home/hnakajima/work/foundry-procurement-agent/docs/observability-integration/README.md:1) / コード例: [docs/observability-integration/integration-examples.md](/home/hnakajima/work/foundry-procurement-agent/docs/observability-integration/integration-examples.md:1)

**行番号はこのsnapshot時点。ファイルを編集した後は関数名で再検索する。** 未追跡ファイルはHEADのGitHubリンクでは参照できないため、本資料はローカル絶対パスを使用する。

## 1. 移植に使う関数・クラス

| コンポーネント／役割 | ファイル・開始行 | 関数／クラス | 対象行 |
| --- | --- | --- | --- |
| Hosted | [src/procurement_agent/observability.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/observability.py:23) | `current_request_attributes` | 23–28 |
| Hosted | [src/procurement_agent/observability.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/observability.py:53) | `sanitize_attributes` | 53–60 |
| Hosted | [src/procurement_agent/observability.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/observability.py:63) | `TelemetryRecorder` | 63–114 |
| Hosted | [src/procurement_agent/hosted_app.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted_app.py:18) | `_RequestCorrelationMiddleware` | 18–53 |
| Hosted | [src/procurement_agent/hosted_app.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted_app.py:64) | `main` | 64–85 |
| Hosted | [src/procurement_agent/hosted.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:115) | `ControllerContextProvider` | 115–170 |
| Hosted | [src/procurement_agent/hosted.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:173) | `build_hosted_bundle` | 173–253 |
| Hosted | [src/procurement_agent/hosted.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:403) | `_invoke_remote_tool` | 403–424 |
| Hosted | [src/procurement_agent/hosted.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:427) | `_execute_hosted_components` | 427–576 |
| Hosted | [src/procurement_agent/controller.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:191) | `operation_status_attributes` | 191–207 |
| Hosted | [src/procurement_agent/controller.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:210) | `correlation_attributes` | 210–221 |
| Hosted | [src/procurement_agent/controller.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:224) | `apply_operation_status` | 224–233 |
| Hosted | [src/procurement_agent/controller.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:243) | `correlation` | 243–255 |
| Hosted | [src/procurement_agent/controller.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:377) | `ProcurementController` | 377–1042 |
| Hosted | [src/procurement_agent/models.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/models.py:198) | `OperationStatus` | 198–207 |
| Hosted | [src/procurement_agent/models.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/models.py:210) | `CorrelationContext` | 210–219 |
| App Service | [src/webapp-foundry-oauth/backend/procurement.py](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement.py:52) | `_identity` | 52–71 |
| App Service | [src/webapp-foundry-oauth/backend/procurement.py](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement.py:83) | `_state` | 83–97 |
| App Service | [src/webapp-foundry-oauth/backend/procurement.py](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement.py:112) | `_BrowserBoundary` | 112–126 |
| App Service | [src/webapp-foundry-oauth/backend/procurement.py](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement.py:129) | `_public_result` | 129–163 |
| App Service | [src/webapp-foundry-oauth/backend/procurement.py](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement.py:173) | `_ObservedTransport` | 173–187 |
| App Service | [src/webapp-foundry-oauth/backend/procurement.py](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement.py:191) | `_lifespan` | 191–214 |
| App Service | [src/webapp-foundry-oauth/backend/procurement.py](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement.py:220) | `_Instrumentation` | 220–232 |
| App Service | [src/webapp-foundry-oauth/backend/procurement.py](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement.py:286) | `_response_metadata` | 286–291 |
| App Service | [src/webapp-foundry-oauth/backend/procurement.py](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement.py:294) | `_stream_turn` | 294–338 |
| App Service | [src/webapp-foundry-oauth/backend/procurement.py](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement.py:343) | `chat` | 343–409 |
| Functions参考ログ／入口 | [src/functions-mcp-selfhosted/mcp_server.py](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:133) | `log_inbound_token_summary` | 133–139 |
| Functions参考ログ／入口 | [src/functions-mcp-selfhosted/mcp_server.py](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:237) | `acquire_graph_token_via_obo` | 237–294 |
| Functions参考ログ／入口 | [src/functions-mcp-selfhosted/mcp_server.py](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:297) | `call_graph_api` | 297–354 |
| Functions参考ログ／入口 | [src/functions-mcp-selfhosted/mcp_server.py](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:357) | `build_whoami_response` | 357–456 |
| Functions参考ログ／入口 | [src/functions-mcp-selfhosted/mcp_server.py](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:459) | `create_mcp_server` | 459–487 |
| Functions参考ログ／入口 | [src/functions-mcp-selfhosted/mcp_server.py](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:490) | `app` | 490–494 |

## 2. Hostedの明示的なSpan／event／属性記録

ASTから抽出した直接呼出し。標準SDK内の自動計装は含めない。通常loggerの文字列はOTelのSpan名ではない。

| 場所 | 所属関数 | 呼出し | Span名／イベント名／属性／ログテンプレート |
| --- | --- | --- | --- |
| [hosted.py:151](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:151) | `ControllerContextProvider.before_run` | `trace.get_current_span().set_attributes` |  |
| [hosted.py:390](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:390) | `_conversation_result` | `telemetry.span` | response.generate |
| [hosted.py:391](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:391) | `_conversation_result` | `telemetry.event` | response.status |
| [hosted.py:560](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:560) | `_execute_hosted_components` | `span.set_attribute` | error.type |
| [hosted.py:564](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:564) | `_execute_hosted_components` | `span.set_attribute` | error.http_status |
| [controller.py:233](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:233) | `apply_operation_status` | `span.set_attribute` |  |
| [controller.py:405](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:405) | `ProcurementController._finish` | `self.telemetry.span` | response.generate |
| [controller.py:406](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:406) | `ProcurementController._finish` | `self.telemetry.event` | response.status |
| [controller.py:523](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:523) | `ProcurementController._run_catalog_step` | `self.telemetry.span` | plan.step.execute |
| [controller.py:530](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:530) | `ProcurementController._run_catalog_step` | `self.telemetry.event` | step.started |
| [controller.py:533](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:533) | `ProcurementController._run_catalog_step` | `self.telemetry.event` | handoff.payload_validated |
| [controller.py:541](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:541) | `ProcurementController._run_catalog_step` | `self.telemetry.event` | handoff.output_rejected |
| [controller.py:561](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:561) | `ProcurementController._run_catalog_step` | `self.telemetry.event` | step.completed |
| [controller.py:565](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:565) | `ProcurementController._run_catalog_step` | `self.telemetry.event` | result.rejected |
| [controller.py:570](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:570) | `ProcurementController._run_catalog_step` | `self.telemetry.event` | plan.replanned |
| [controller.py:572](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:572) | `ProcurementController._run_catalog_step` | `self.telemetry.event` | step.retry_scheduled |
| [controller.py:575](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:575) | `ProcurementController._run_catalog_step` | `self.telemetry.event` | step.failed |
| [controller.py:603](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:603) | `ProcurementController._run_code_step` | `self.telemetry.span` | plan.step.execute |
| [controller.py:610](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:610) | `ProcurementController._run_code_step` | `self.telemetry.event` | step.started |
| [controller.py:613](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:613) | `ProcurementController._run_code_step` | `self.telemetry.event` | handoff.payload_validated |
| [controller.py:621](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:621) | `ProcurementController._run_code_step` | `self.telemetry.event` | handoff.output_rejected |
| [controller.py:633](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:633) | `ProcurementController._run_code_step` | `self.telemetry.event` | step.completed |
| [controller.py:636](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:636) | `ProcurementController._run_code_step` | `self.telemetry.event` | result.rejected |
| [controller.py:655](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:655) | `ProcurementController._merge_validated` | `self.telemetry.span` | merge.validate |
| [controller.py:661](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:661) | `ProcurementController._merge_validated` | `self.telemetry.event` | step.started |
| [controller.py:687](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:687) | `ProcurementController._merge_validated` | `self.telemetry.event` | result.rejected |
| [controller.py:702](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:702) | `ProcurementController._merge_validated` | `self.telemetry.event` | step.completed |
| [controller.py:780](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:780) | `ProcurementController.execute` | `self.telemetry.span` | plan.create |
| [controller.py:783](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:783) | `ProcurementController.execute` | `self.telemetry.event` | plan.created |

## 3. 購買WebのSpan属性／status記録

ASTから抽出した直接呼出し。標準SDK内の自動計装は含めない。通常loggerの文字列はOTelのSpan名ではない。

| 場所 | 所属関数 | 呼出し | Span名／イベント名／属性／ログテンプレート |
| --- | --- | --- | --- |
| [procurement.py:180](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement.py:180) | `_ObservedTransport.handle_async_request` | `span.set_attributes` | app.propagation.traceparent_present, app.propagation.traceparent_matches_span, app.propagation.baggage_user... |
| [procurement.py:323](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement.py:323) | `_stream_turn` | `span.set_attribute` | gen_ai.response.id |
| [procurement.py:331](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement.py:331) | `_stream_turn` | `span.set_status` |  |
| [procurement.py:332](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement.py:332) | `_stream_turn` | `span.set_attribute` | error.type |
| [procurement.py:348](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement.py:348) | `chat` | `span.set_attribute` | user.id |
| [procurement.py:377](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement.py:377) | `chat` | `span.set_attributes` | gen_ai.conversation.id, app.turn.number, test.case.id |
| [procurement.py:390](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement.py:390) | `chat` | `span.set_attribute` | gen_ai.response.id |
| [procurement.py:401](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement.py:401) | `chat` | `span.set_status` |  |
| [procurement.py:402](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement.py:402) | `chat` | `span.set_attribute` | error.type |

## 4. Functions参考経路の通常logger呼出し一覧

ASTから抽出した直接呼出し。標準SDK内の自動計装は含めない。通常loggerの文字列はOTelのSpan名ではない。

| 場所 | 所属関数 | 呼出し | Span名／イベント名／属性／ログテンプレート |
| --- | --- | --- | --- |
| [mcp_server.py:25](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:25) | `(module)` | `logger.info` | Graph scope configuration loaded: GRAPH_SCOPES set=%s default_scopes=%s |
| [mcp_server.py:47](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:47) | `_get_env_int` | `logger.warning` | Invalid integer for %s: %s. Using default %s. |
| [mcp_server.py:58](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:58) | `_get_env_float` | `logger.warning` | Invalid float for %s: %s. Using default %s. |
| [mcp_server.py:108](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:108) | `extract_bearer_token_from_context` | `logger.warning` | Failed to extract Authorization header from context: %s |
| [mcp_server.py:135](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:135) | `log_inbound_token_summary` | `logger.info` | Inbound token summary: received=%s claims=%s |
| [mcp_server.py:218](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:218) | `_get_graph_scopes` | `logger.info` | Graph OBO scopes resolved: %s |
| [mcp_server.py:258](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:258) | `acquire_graph_token_via_obo` | `logger.info` | OBO token exchange succeeded after retry %s/%s. |
| [mcp_server.py:269](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:269) | `acquire_graph_token_via_obo` | `logger.warning` | OBO token exchange attempt %s/%s failed: %s |
| [mcp_server.py:283](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:283) | `acquire_graph_token_via_obo` | `logger.error` | OBO token exchange failed after retries: %s |
| [mcp_server.py:312](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:312) | `call_graph_api` | `logger.warning` | Graph API call attempt %s/%s returned retryable status %s. |
| [mcp_server.py:325](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:325) | `call_graph_api` | `logger.info` | Graph API call succeeded after retry %s/%s. |
| [mcp_server.py:330](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:330) | `call_graph_api` | `logger.warning` | Graph API call attempt %s/%s failed: %s |
| [mcp_server.py:337](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:337) | `call_graph_api` | `logger.error` | Graph API call failed after retries: %s |
| [mcp_server.py:362](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:362) | `build_whoami_response` | `logger.warning` | Inbound token validation failed: error=%s details=%s |
| [mcp_server.py:376](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:376) | `build_whoami_response` | `logger.error` | OBO configuration error: %s |
| [mcp_server.py:384](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:384) | `build_whoami_response` | `logger.error` | OBO exchange failed for inbound claims=%s correlation_id=%s trace_id=%s |
| [mcp_server.py:405](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:405) | `build_whoami_response` | `logger.error` | Security check failed: inbound token oid does not match Graph /me id. inbound_claims=%s graph_user_id=%s |
| [mcp_server.py:416](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:416) | `build_whoami_response` | `logger.warning` | Security check skipped because user identifiers are incomplete: inbound_claims=%s graph_user_id_present=%s |
| [mcp_server.py:421](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:421) | `build_whoami_response` | `logger.info` | whoami succeeded: inbound_claims=%s obo_attempts=%s graph_attempts=%s |
| [mcp_server.py:446](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:446) | `build_whoami_response` | `logger.error` | Failed to call Graph API: error=%s status_code=%s inbound_claims=%s |
| [mcp_server.py:480](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:480) | `create_mcp_server.whoami` | `logger.info` | whoami MCP tool called (python runtime, OBO) |

## 5. 旧OAuth Webの通常logger呼出し一覧

ASTから抽出した直接呼出し。標準SDK内の自動計装は含めない。通常loggerの文字列はOTelのSpan名ではない。

| 場所 | 所属関数 | 呼出し | Span名／イベント名／属性／ログテンプレート |
| --- | --- | --- | --- |
| [server.py:216](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:216) | `_reset_conversation_state` | `logger.warning` | Conversation state reset: conversation=%s owner=%s reason=%s |
| [server.py:381](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:381) | `_fetch_easyauth_me` | `logger.warning` | /.auth/me returned HTTP %s |
| [server.py:389](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:389) | `_fetch_easyauth_me` | `logger.warning` | Failed to fetch /.auth/me: %s |
| [server.py:404](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:404) | `_refresh_easyauth_tokens` | `logger.info` | /.auth/refresh returned HTTP %s |
| [server.py:406](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:406) | `_refresh_easyauth_tokens` | `logger.warning` | Failed to call /.auth/refresh: %s |
| [server.py:418](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:418) | `_get_easyauth_refresh_token` | `logger.info` | Using EasyAuth refresh token from /.auth/me entry provider=%s |
| [server.py:426](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:426) | `_get_easyauth_refresh_token` | `logger.info` | Using EasyAuth refresh token from /.auth/me after refresh provider=%s |
| [server.py:430](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:430) | `_get_easyauth_refresh_token` | `logger.warning` | EasyAuth refresh token not found. /.auth/me keys=%s |
| [server.py:456](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:456) | `_get_easyauth_access_token` | `logger.error` | EasyAuth principal does not match access token claims: principal=%s token_claims=%s |
| [server.py:462](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:462) | `_get_easyauth_access_token` | `logger.info` | EasyAuth access token claims: %s |
| [server.py:504](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:504) | `_acquire_foundry_token_by_refresh_token` | `logger.info` | Acquired Foundry user delegated token via EasyAuth refresh token: scopes=%s claims=%s |
| [server.py:510](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:510) | `_acquire_foundry_token_by_refresh_token` | `logger.error` | Failed to acquire Foundry token by refresh token: error=%s suberror=%s correlation_id=%s |
| [server.py:533](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:533) | `_acquire_foundry_token_on_behalf_of` | `logger.info` | Acquired Foundry user delegated token via OBO: scopes=%s claims=%s |
| [server.py:539](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:539) | `_acquire_foundry_token_on_behalf_of` | `logger.error` | Failed to acquire Foundry token via OBO: error=%s suberror=%s correlation_id=%s |
| [server.py:596](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:596) | `_build_outbound_headers` | `logger.info` | Forwarding EasyAuth access token to Foundry/APIM: claims=%s |
| [server.py:695](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:695) | `_stream_response` | `logger.info` | Calling Foundry Agent endpoint Responses API url=%s previous_response_id=%s agent=%s |
| [server.py:757](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:757) | `_stream_response` | `logger.debug` | Non-JSON SSE data (skipped): %s |
| [server.py:799](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:799) | `_stream_response` | `logger.info` | Tool call started: %s (call_id=%s) |
| [server.py:820](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:820) | `_stream_response` | `logger.info` | OAuth consent detected (output item); draining Foundry stream before UI notification: connection=%s respons... |
| [server.py:842](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:842) | `_stream_response` | `logger.info` | MCP approval detected; draining Foundry stream before UI notification: server=%s tool=%s approval_id=%s res... |
| [server.py:867](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:867) | `_stream_response` | `logger.info` | MCP approval detected (direct event); draining Foundry stream before UI notification: server=%s tool=%s app... |
| [server.py:885](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:885) | `_stream_response` | `logger.info` | Tool call done: %s (call_id=%s) |
| [server.py:943](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:943) | `_stream_response` | `logger.info` | OAuth consent detected; draining Foundry stream before UI notification: connection=%s response_id=%s |
| [server.py:960](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:960) | `_stream_response` | `logger.info` | OAuth consent detected (embedded); draining Foundry stream before UI notification: connection=%s response_i... |
| [server.py:977](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:977) | `_stream_response` | `logger.info` | Foundry response completed upstream; draining remaining SSE framing: %s |
| [server.py:990](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:990) | `_stream_response` | `logger.error` | Foundry error event: %s |
| [server.py:998](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:998) | `_stream_response` | `logger.error` | Foundry stream ended before response.completed; response_id=%s deferred_action=%s |
| [server.py:1070](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1070) | `_stream_response` | `logger.info` | MCP approval ready after completed response: response_id=%s approval_ids=%s consent_pending=%s |
| [server.py:1087](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1087) | `_stream_response` | `logger.info` | OAuth consent ready after completed response: response_id=%s connection=%s |
| [server.py:1098](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1098) | `_stream_response` | `logger.info` | Response completed: %s |
| [server.py:1107](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1107) | `_stream_response` | `logger.error` |  |
| [server.py:1115](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1115) | `_stream_response` | `logger.warning` | Foundry rejected previous_response_id; retrying once without conversation state: conversation=%s rejected_p... |
| [server.py:1140](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1140) | `_stream_response` | `logger.exception` |  |
| [server.py:1255](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1255) | `_run_response_job` | `logger.exception` | Chat job failed: job_id=%s |
| [server.py:1397](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1397) | `continue_after_consent` | `logger.info` | Sending MCP approval response(s): conversation=%s approve=%s count=%d |
| [server.py:1404](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1404) | `continue_after_consent` | `logger.info` | Continuing conversation %s with previous_response_id=%s |

## 6. Hosted SDK内で確認した初期化・Export処理

| SDKファイル | 確認した内容 |
| --- | --- |
| [.venv/lib/python3.13/site-packages/agent_framework_foundry_hosting/_responses.py](/home/hnakajima/work/foundry-procurement-agent/.venv/lib/python3.13/site-packages/agent_framework_foundry_hosting/_responses.py:326) | ResponsesHostServerの継承と基底Host構築 |
| [.venv/lib/python3.13/site-packages/azure/ai/agentserver/core/_base.py](/home/hnakajima/work/foundry-procurement-agent/.venv/lib/python3.13/site-packages/azure/ai/agentserver/core/_base.py:258) | 接続文字列、capture設定、configure_observability呼出し |
| [.venv/lib/python3.13/site-packages/azure/ai/agentserver/core/_tracing.py](/home/hnakajima/work/foundry-procurement-agent/.venv/lib/python3.13/site-packages/azure/ai/agentserver/core/_tracing.py:181) | _configure_tracing／_setup_distro_export、Microsoft distroへの接続 |
| [.venv/lib/python3.13/site-packages/agent_framework/observability.py](/home/hnakajima/work/foundry-procurement-agent/.venv/lib/python3.13/site-packages/agent_framework/observability.py:1064) | このバージョンの計装既定値 |
| [.venv/lib/python3.13/site-packages/azure/monitor/opentelemetry/exporter/export/trace/_exporter.py](/home/hnakajima/work/foundry-procurement-agent/.venv/lib/python3.13/site-packages/azure/monitor/opentelemetry/exporter/export/trace/_exporter.py:535) | 通常Span eventはMessageData、exception eventはExceptionDataへ変換 |

SDKファイルは調査環境の`.venv`の証拠であり、移植先へコピーする対象ではない。別バージョンでは配置・動作が変わり得る。

## 7. Snapshotの同一性

機械可読の全ハッシュ: [docs/observability-integration/source-snapshot.json](/home/hnakajima/work/foundry-procurement-agent/docs/observability-integration/source-snapshot.json:1)

| ファイル | 行数 | 管理状態 | SHA-256 |
| --- | --- | --- | --- |
| [README.md](/home/hnakajima/work/foundry-procurement-agent/README.md:1) | 55 | tracked (作業ツリー) | `b2d425f59aaef840d25a695f42267012974088c30e3ccbeecf29a45a5876ec51` |
| [requirements.txt](/home/hnakajima/work/foundry-procurement-agent/requirements.txt:1) | 14 | tracked (作業ツリー) | `af9f5bb73e98ef6e87ac73bc4d40439b711ad4208278c874801212ca97f6558d` |
| [requirements-lock.txt](/home/hnakajima/work/foundry-procurement-agent/requirements-lock.txt:1) | 130 | tracked (作業ツリー) | `959820d4364604e4798e2479fdf94e41744fd7e45a04a8fbbfb9e46a72d10065` |
| [pyproject.toml](/home/hnakajima/work/foundry-procurement-agent/pyproject.toml:1) | 39 | tracked (作業ツリー) | `7fe06cfdebf43afa77898cfc2b7138f1b226b7e4c1adc34dbbd428ee1d90494b` |
| [main.py](/home/hnakajima/work/foundry-procurement-agent/main.py:1) | 7 | tracked (作業ツリー) | `a6248ab8ab406846e4b955307b542d60c15a3e738b52f0c72c381cf11d5d612c` |
| [azure.yaml](/home/hnakajima/work/foundry-procurement-agent/azure.yaml:1) | 72 | tracked (作業ツリー) | `8f37e30e1768676396996e182f16c58422933203be57547999637f8ff9386e85` |
| [src/procurement_agent/observability.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/observability.py:1) | 125 | tracked (作業ツリー) | `e88583c2fcef749791ea003d567acc33057e919cb25c599e1a59206ee1d4a101` |
| [src/procurement_agent/hosted_app.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted_app.py:1) | 89 | tracked (作業ツリー) | `7a7c594b933e3c69a6f40b19a3384d0a4eae614f673159065a2e8cf9c257e838` |
| [src/procurement_agent/hosted.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:1) | 576 | tracked (作業ツリー) | `4e3f741c294143f8fe97a42a142f2ac3bd0c93b290009b03b9396266389b0e89` |
| [src/procurement_agent/controller.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:1) | 1042 | tracked (作業ツリー) | `0079be5e85cabc0754c930b66c9bdb2e78ad2bc127274609c5ef9a2bcdc6c3ed` |
| [src/procurement_agent/models.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/models.py:1) | 401 | tracked (作業ツリー) | `1336b60b5f36844ec01e709a473af7e4677ab7d0f4a1a1952f2a60e0d9056f2a` |
| [src/procurement_agent/plan.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/plan.py:1) | 195 | tracked (作業ツリー) | `fc8b2227deb01e1f7c565cc4c62a95e7522ddfb9d3a83f6a8952adcb012647cb` |
| [src/procurement_agent/middleware.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/middleware.py:1) | 50 | tracked (作業ツリー) | `71423130b282cf844c631f643bb99bc2834849030a50f0eebd30dfb885cd4c66` |
| [src/procurement_agent/mcp_contract.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/mcp_contract.py:1) | 153 | tracked (作業ツリー) | `f9870d0c1c522ea71e8dbb024011ba0242661024d31309e8384c8a9c34173cea` |
| [src/procurement_agent/session_state.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/session_state.py:1) | 87 | tracked (作業ツリー) | `e41959f7b9f3cad6e7e7f352c37154d415fda4e2575cb59661c8aa25e1811cdc` |
| [src/procurement_agent/progress.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/progress.py:1) | 93 | tracked (作業ツリー) | `7a228192166f09e836a093ed09d12fc861a4ab2580b712ce2d51b3e9850e1434` |
| [src/webapp-foundry-oauth/requirements.txt](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/requirements.txt:1) | 12 | tracked (作業ツリー) | `7967c95730ff75eaafbe6d95c67cff5983cea40c658060a4ccb645857aeba5aa` |
| [src/webapp-foundry-oauth/startup.sh](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/startup.sh:1) | 22 | tracked (作業ツリー) | `317ee35a0438bd5dbc01b62357f80d14ef9f9a852a9fee3798cd9b15bd5fb23f` |
| [src/webapp-foundry-oauth/backend/requirements.txt](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/requirements.txt:1) | 8 | tracked (作業ツリー) | `7ba97fd0d6ceb547beabcc81128d031860a2ba670b5064c72e7106db463c7547` |
| [src/webapp-foundry-oauth/backend/procurement.py](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement.py:1) | 409 | tracked (作業ツリー) | `e4bd7e39a23000445f97b543ee878b65a580be9e496136f0b1820c39f47c0343` |
| [src/webapp-foundry-oauth/backend/server.py](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1) | 1485 | tracked (作業ツリー) | `f9270b1c84a49547781562324817fd779d2c035f1ffd24b6bb94e9aee3866b16` |
| [src/webapp-foundry-oauth/scripts/package-procurement.py](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/scripts/package-procurement.py:1) | 22 | tracked (作業ツリー) | `bf63beb1758eef5eb82053c3c10b451561e95c82dec47eabb4c71ac1a2bb4dff` |
| [src/functions-mcp-selfhosted/requirements.txt](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/requirements.txt:1) | 6 | tracked (作業ツリー) | `f921c63a2090a98d030af563bd73db8b233eefe4fbb643fd8edf23ac3ea44657` |
| [src/functions-mcp-selfhosted/pyproject.toml](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/pyproject.toml:1) | 13 | tracked (作業ツリー) | `3035132d9a1a57db2a531d7e474d0d9bd16866321a2cef9f4cf2a332f292f615` |
| [src/functions-mcp-selfhosted/host.json](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/host.json:1) | 8 | tracked (作業ツリー) | `877b38fa6be86aedecd583f347cea814f1fa6f6c38c98ed36f514426abf84813` |
| [src/functions-mcp-selfhosted/mcp_handler/__init__.py](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_handler/__init__.py:1) | 6 | tracked (作業ツリー) | `a038ab913d2992c6c21c3c396ca0ab48c9460f34190ba3fb1a174f743eac77f5` |
| [src/functions-mcp-selfhosted/mcp_handler/function.json](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_handler/function.json:1) | 26 | tracked (作業ツリー) | `c6952c2b5481d6f074fcba6c379a5a30562ab3fb0c14a274a59ee7fc4bad47aa` |
| [src/functions-mcp-selfhosted/mcp_server.py](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:1) | 494 | tracked (作業ツリー) | `1cba3808c6af6e188711eb77cb053fc2186b246dcfc08defd5b6a3eee6aaca75` |
| [src/functions-mcp-selfhosted/infra/azure/main.bicep](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/infra/azure/main.bicep:1) | 158 | tracked (作業ツリー) | `6e322c272517efb61b63e6896cd34e89913c6370fc7cf26697c808c605573709` |
| [src/functions-mcp-selfhosted/scripts/deploy-functions-zip.sh](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/scripts/deploy-functions-zip.sh:1) | 85 | tracked (作業ツリー) | `76350b4287e9b7d9302691c2e09cdc97539918b1be251f38f8e974cd5dd492a9` |
| [src/functions-mcp-selfhosted/scripts/deploy-functions-zip.ps1](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/scripts/deploy-functions-zip.ps1:1) | 136 | tracked (作業ツリー) | `1b000a4e488bba979b98bc901ab1a84f559b6e355338101147529b049af021fd` |
| [infra/webui.bicep](/home/hnakajima/work/foundry-procurement-agent/infra/webui.bicep:1) | 190 | tracked (作業ツリー) | `d8020fe91ad063e52446a295eb7854ff0b92d3d774322c0d09b4755cdf843ed6` |
| [infra/apim.bicep](/home/hnakajima/work/foundry-procurement-agent/infra/apim.bicep:1) | 110 | tracked (作業ツリー) | `88c3042bb698ac116e6308345564d2a4d9a78b107d7c6fb99cffe14be57c4e3e` |
| [infra/foundry/toolboxes/catalog-search-toolbox.yaml](/home/hnakajima/work/foundry-procurement-agent/infra/foundry/toolboxes/catalog-search-toolbox.yaml:1) | 13 | tracked (作業ツリー) | `2dbc014dd6e2d2b9094e9e2f70fffe0179ddfde7b5f93eecf5bef2afa9330a3e` |
| [infra/foundry/toolboxes/code-master-toolbox.yaml](/home/hnakajima/work/foundry-procurement-agent/infra/foundry/toolboxes/code-master-toolbox.yaml:1) | 13 | tracked (作業ツリー) | `cbbf03b59d245764a5674e4faa935fc093980cf8714691043b2e838a0790ba96` |
| [infra/foundry/agents/catalog-search-agent.yaml](/home/hnakajima/work/foundry-procurement-agent/infra/foundry/agents/catalog-search-agent.yaml:1) | 10 | tracked (作業ツリー) | `b34c7c5b3718e7af73bf55cd1281d93375c9d7b6d5283f1d5d7626e979132265` |
| [infra/foundry/agents/code-determination-agent.yaml](/home/hnakajima/work/foundry-procurement-agent/infra/foundry/agents/code-determination-agent.yaml:1) | 10 | tracked (作業ツリー) | `286d231693ab784a0a53fed9a339d3f1c6d121e44cb5cc4347b0e50fe66d6453` |
| [infra/observability/instrumentation-manifest.json](/home/hnakajima/work/foundry-procurement-agent/infra/observability/instrumentation-manifest.json:1) | 10 | tracked (作業ツリー) | `ffa01bfe27c7c361135f0c7be9a91592b21441743e536175351553435510a413` |
| [infra/observability/kql/core-status-correlation.kql](/home/hnakajima/work/foundry-procurement-agent/infra/observability/kql/core-status-correlation.kql:1) | 15 | tracked (作業ツリー) | `0c52b4191cd89dfe2cd15d3278f45f111f4bb2c6935723201d6a5855252cfa2b` |
| [infra/observability/kql/export-exact-operation.kql](/home/hnakajima/work/foundry-procurement-agent/infra/observability/kql/export-exact-operation.kql:1) | 6 | tracked (作業ツリー) | `bb45b2cc73bd07a2c5cf396f362b5d19833901e78160688366bfc3d116a2669c` |
| [scripts/package_hosted.py](/home/hnakajima/work/foundry-procurement-agent/scripts/package_hosted.py:1) | 31 | tracked (作業ツリー) | `03f6cbc94edad06dde093a79cec42921de6d78103ee1fe36b7a397162139412a` |
| [scripts/deploy_foundry.py](/home/hnakajima/work/foundry-procurement-agent/scripts/deploy_foundry.py:1) | 191 | tracked (作業ツリー) | `63fcd155443635fb8700e3a71702a6213cad3eab9d593ad70192cb4b3354de02` |
| [scripts/export_trace_evidence.py](/home/hnakajima/work/foundry-procurement-agent/scripts/export_trace_evidence.py:1) | 93 | tracked (作業ツリー) | `9b5a6407ea25c1d29c9897a3828b69886d4d4090a16df7f48b51c32c2ecc7474` |
| [src/trace_pipeline/envelope.py](/home/hnakajima/work/foundry-procurement-agent/src/trace_pipeline/envelope.py:1) | 67 | tracked (作業ツリー) | `c2483ae167526292881558d273f0a3d2f3dea5b2d4084a4ac11fba133fd1ba94` |
| [src/trace_pipeline/normalize.py](/home/hnakajima/work/foundry-procurement-agent/src/trace_pipeline/normalize.py:1) | 125 | tracked (作業ツリー) | `55f88f3d882665b691e007c4a6cc5a91d3ba30a9f548b4238b27ee0aa43645d4` |
| [docs/report/validation-results-2026-09-06.md](/home/hnakajima/work/foundry-procurement-agent/docs/report/validation-results-2026-09-06.md:1) | 120 | tracked (作業ツリー) | `236215f013be7a9b899a4dce4930ce1521793ba0f99f6e266561f91078877fba` |
| [docs/azure-observability-validation-2026-09-03.md](/home/hnakajima/work/foundry-procurement-agent/docs/azure-observability-validation-2026-09-03.md:1) | 219 | tracked (作業ツリー) | `c4153dabcf54ea357cf3664b5f0efd3424660bd52242c0a07ec83ae41ec770ed` |
| [tests/unit/test_webui.py](/home/hnakajima/work/foundry-procurement-agent/tests/unit/test_webui.py:1) | 305 | tracked (作業ツリー) | `2b6ed22e6cb3c46f44ec8877285b11f7b1ba325f847c2e2bcacfc40c7899c582` |
| [tests/unit/test_hosted_protocol_v2.py](/home/hnakajima/work/foundry-procurement-agent/tests/unit/test_hosted_protocol_v2.py:1) | 89 | tracked (作業ツリー) | `ee048b624a130096ce0c2db4ff9cd88ea0e71e9be205d38bd9b6a046463f9fb8` |
| [tests/unit/test_hosted_factory_v2.py](/home/hnakajima/work/foundry-procurement-agent/tests/unit/test_hosted_factory_v2.py:1) | 207 | tracked (作業ツリー) | `7540ffee93de32b0a204eb654c9f97a8582fb52aa520fc8f8fe2a6510308ea6a` |
| [tests/trace/test_envelope_v3.py](/home/hnakajima/work/foundry-procurement-agent/tests/trace/test_envelope_v3.py:1) | 154 | tracked (作業ツリー) | `9b06f4591a9a805aa4e6d779a79fe82be2cd6208732e11f63a959442516c2acc` |
| [.venv/lib/python3.13/site-packages/agent_framework_foundry_hosting/_responses.py](/home/hnakajima/work/foundry-procurement-agent/.venv/lib/python3.13/site-packages/agent_framework_foundry_hosting/_responses.py:1) | 2076 | local SDK | `e944316a94eafd7c31fe90c60667d8d01b24615e2825b04dbe7f4f5e9b0b43f7` |
| [.venv/lib/python3.13/site-packages/azure/ai/agentserver/core/_base.py](/home/hnakajima/work/foundry-procurement-agent/.venv/lib/python3.13/site-packages/azure/ai/agentserver/core/_base.py:1) | 665 | local SDK | `8a1686fc867385a93ababdafa8b111e1bb7945e529f8cfd83b4de399807e31b5` |
| [.venv/lib/python3.13/site-packages/azure/ai/agentserver/core/_tracing.py](/home/hnakajima/work/foundry-procurement-agent/.venv/lib/python3.13/site-packages/azure/ai/agentserver/core/_tracing.py:1) | 829 | local SDK | `7f7ca3c2832b83acaec8619438c7bd0bc43adb536264a269cbb2f339133f0202` |
| [.venv/lib/python3.13/site-packages/agent_framework/observability.py](/home/hnakajima/work/foundry-procurement-agent/.venv/lib/python3.13/site-packages/agent_framework/observability.py:1) | 3703 | local SDK | `13123cfcdb300285514d8eaef8a1878f29a37e607192801c71d1582cc16d47ab` |
| [.venv/lib/python3.13/site-packages/azure/monitor/opentelemetry/exporter/export/trace/_exporter.py](/home/hnakajima/work/foundry-procurement-agent/.venv/lib/python3.13/site-packages/azure/monitor/opentelemetry/exporter/export/trace/_exporter.py:1) | 621 | local SDK | `f1d868fa3f2af25c0191504d261aae80bdbfe04cf76702299946ed9ed8daa23f` |
| [.venv/lib/python3.13/site-packages/agent_framework_foundry_hosting-1.0.0b260827.dist-info/METADATA](/home/hnakajima/work/foundry-procurement-agent/.venv/lib/python3.13/site-packages/agent_framework_foundry_hosting-1.0.0b260827.dist-info/METADATA:1) | 79 | local SDK | `3da86c799e3fe41e8ca44a5ede38f439f99c45c9283ef5ddf97170644020f50e` |
| [.venv/lib/python3.13/site-packages/azure_ai_agentserver_core-2.1.0.dist-info/METADATA](/home/hnakajima/work/foundry-procurement-agent/.venv/lib/python3.13/site-packages/azure_ai_agentserver_core-2.1.0.dist-info/METADATA:1) | 294 | local SDK | `bf38e7ac779851286d48e76dcd76384af0a0e0ed0c6f01530819ea742417b7e3` |
| [.venv/lib/python3.13/site-packages/microsoft_opentelemetry-1.3.8.dist-info/METADATA](/home/hnakajima/work/foundry-procurement-agent/.venv/lib/python3.13/site-packages/microsoft_opentelemetry-1.3.8.dist-info/METADATA:1) | 432 | local SDK | `77fe095d226c77285d6f6ceb7c68b8cfd809646a0486603cfb589b7bfe137fb1` |
| [.venv/lib/python3.13/site-packages/mcp/shared/context.py](/home/hnakajima/work/foundry-procurement-agent/.venv/lib/python3.13/site-packages/mcp/shared/context.py:1) | 32 | local SDK | `40c447c1708826cbdfe14def720a9201769a50430a85f8fff5794223e9149271` |
| [.venv/lib/python3.13/site-packages/mcp/types.py](/home/hnakajima/work/foundry-procurement-agent/.venv/lib/python3.13/site-packages/mcp/types.py:1) | 1999 | local SDK | `6824109cd1eabaf43c5dab829a83015b1b88ec9ae149765e6814afaf23f9bde5` |
| [.venv/lib/python3.13/site-packages/mcp/server/fastmcp/server.py](/home/hnakajima/work/foundry-procurement-agent/.venv/lib/python3.13/site-packages/mcp/server/fastmcp/server.py:1) | 1366 | local SDK | `f4360eec1cca411afa55762a223d103236e856cc8b52944ef64ff337c8e970c2` |
