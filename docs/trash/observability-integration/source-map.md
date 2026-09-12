# 最新ソース索引・Span／logging箇所・SHA-256

> 2026-09-12追加: Webの名前取得用metadataを削除し、メールのuser.id baggageと診断UIを追加しました。現行仕様とHostedの実装結果は[整理案](hosted-simplification-proposal-20260912.md)を参照してください。以下の旧OBO有効化契約は過去の記録です。

> 2026-09-12: WebAppの認証・通信を分割し、旧購買専用UIを削除しました。Webの最新のファイル構成・OTel仕様・配布手順は[WebApp README](../../../src/webapp-foundry-oauth/README.md)を参照してください。以下に残る旧Webパス・行番号・過去の検証件数は当時の記録です。

更新日: **2026-09-08**。branch=`main`、基準HEAD=`e7fd85c4599909e9666ecfcd9e5d20c4e50faf59`。**未コミットの変更と新規ファイルを含む作業ツリー**が対象。HEADのソースと一致するという意味ではない。

[統合ガイド](../../observability-integration/README.md)／[Azure設定](../../deployment/configuration.md)／[機械可読Snapshot](source-snapshot.json)。2026-09-07の行番号・hashを現行値へ置き換えた。SDK欄はローカル.venvの証拠であり、Azureの全installed packageを棚卸ししたものではない。

## 1. 稼働入口とファイルの役割

| 対象 | 稼働入口・主要モジュール | 設定／配布 |
| --- | --- | --- |
| Hosted | [main.py](../../../main.py) → hosted_app.py、hosted.py、controller.py、identity.py、observability.py | root requirements/lock、deploy_foundry.py、package_hosted.py |
| App Service | [src/webapp-foundry-oauth/startup.sh](../../../src/webapp-foundry-oauth/startup.sh) → server.py、procurement_flow.py、telemetry.py、旧OAuth UI | Web root requirements、package-procurement.py |
| Functions | [src/functions-mcp-selfhosted/mcp_handler/__init__.py](../../../src/functions-mcp-selfhosted/mcp_handler/__init__.py) → mcp_server.py、mcp_telemetry.py | Functions requirements、Bash/PowerShell ZIP script |
| APIM | [infra/apim-foundry-policy.xml](../../../infra/apim-foundry-policy.xml) | infra/apim.bicep、deploy_identity.py web |

旧backend/procurement.pyとprocurement.* UIは比較用としてSnapshotに残すが、現Web配布の入口ではない。Functionsは現行OBO経路であり、未計装の参考コードとして扱わない。

## 2. 関数・クラス対応

ASTで抽出した定義開始行。リンクは定義先を指し、最終行は関数全体の範囲確認用。内側のcallbackは親関数／class名を含める。

### Hosted

| ソース | 関数／class | 最終行 |
| --- | --- | --- |
| [hosted_app.py:26](../../../src/hosted-agent/procurement_agent/hosted_app.py) | `_RequestCorrelationMiddleware` | 96 |
| [hosted_app.py:27](../../../src/hosted-agent/procurement_agent/hosted_app.py) | `_RequestCorrelationMiddleware.dispatch` | 96 |
| [hosted_app.py:99](../../../src/hosted-agent/procurement_agent/hosted_app.py) | `ProcurementResponsesHostServer` | 139 |
| [hosted_app.py:107](../../../src/hosted-agent/procurement_agent/hosted_app.py) | `ProcurementResponsesHostServer.__init__` | 109 |
| [hosted_app.py:111](../../../src/hosted-agent/procurement_agent/hosted_app.py) | `ProcurementResponsesHostServer._handle_response` | 139 |
| [hosted_app.py:142](../../../src/hosted-agent/procurement_agent/hosted_app.py) | `build_parser` | 147 |
| [hosted_app.py:150](../../../src/hosted-agent/procurement_agent/hosted_app.py) | `main` | 171 |
| [observability.py:26](../../../src/hosted-agent/procurement_agent/observability.py) | `McpPrivacyProcessor` | 42 |
| [observability.py:34](../../../src/hosted-agent/procurement_agent/observability.py) | `McpPrivacyProcessor._on_ending` | 42 |
| [observability.py:45](../../../src/hosted-agent/procurement_agent/observability.py) | `configure_host_observability` | 51 |
| [observability.py:54](../../../src/hosted-agent/procurement_agent/observability.py) | `current_request_attributes` | 59 |
| [observability.py:70](../../../src/hosted-agent/procurement_agent/observability.py) | `sha256` | 71 |
| [observability.py:74](../../../src/hosted-agent/procurement_agent/observability.py) | `safe_value` | 81 |
| [observability.py:84](../../../src/hosted-agent/procurement_agent/observability.py) | `sanitize_attributes` | 91 |
| [observability.py:94](../../../src/hosted-agent/procurement_agent/observability.py) | `TelemetryRecorder` | 145 |
| [observability.py:95](../../../src/hosted-agent/procurement_agent/observability.py) | `TelemetryRecorder.__init__` | 113 |
| [observability.py:116](../../../src/hosted-agent/procurement_agent/observability.py) | `TelemetryRecorder.for_hosted_runtime` | 118 |
| [observability.py:121](../../../src/hosted-agent/procurement_agent/observability.py) | `TelemetryRecorder.record_raw_content` | 122 |
| [observability.py:125](../../../src/hosted-agent/procurement_agent/observability.py) | `TelemetryRecorder.span` | 129 |
| [observability.py:132](../../../src/hosted-agent/procurement_agent/observability.py) | `TelemetryRecorder.event` | 133 |
| [observability.py:135](../../../src/hosted-agent/procurement_agent/observability.py) | `TelemetryRecorder.protect_content` | 140 |
| [observability.py:142](../../../src/hosted-agent/procurement_agent/observability.py) | `TelemetryRecorder.finished_spans` | 145 |
| [observability.py:148](../../../src/hosted-agent/procurement_agent/observability.py) | `truncate_export` | 156 |
| [identity.py:27](../../../src/hosted-agent/procurement_agent/identity.py) | `IdentityResult` | 30 |
| [identity.py:36](../../../src/hosted-agent/procurement_agent/identity.py) | `parse_whoami_result` | 49 |
| [identity.py:52](../../../src/hosted-agent/procurement_agent/identity.py) | `verified_name` | 68 |
| [identity.py:71](../../../src/hosted-agent/procurement_agent/identity.py) | `_consent` | 80 |
| [identity.py:83](../../../src/hosted-agent/procurement_agent/identity.py) | `build_identity_tool` | 142 |
| [identity.py:84](../../../src/hosted-agent/procurement_agent/identity.py) | `build_identity_tool.lookup` | 136 |
| [identity.py:145](../../../src/hosted-agent/procurement_agent/identity.py) | `invoke_identity` | 153 |
| [hosted.py:83](../../../src/hosted-agent/procurement_agent/hosted.py) | `FoundryRuntimeSettings` | 105 |
| [hosted.py:93](../../../src/hosted-agent/procurement_agent/hosted.py) | `FoundryRuntimeSettings.from_env` | 105 |
| [hosted.py:109](../../../src/hosted-agent/procurement_agent/hosted.py) | `HostedAgentBundle` | 118 |
| [hosted.py:121](../../../src/hosted-agent/procurement_agent/hosted.py) | `ControllerContextProvider` | 197 |
| [hosted.py:129](../../../src/hosted-agent/procurement_agent/hosted.py) | `ControllerContextProvider.__init__` | 137 |
| [hosted.py:140](../../../src/hosted-agent/procurement_agent/hosted.py) | `ControllerContextProvider._latest_user_text` | 145 |
| [hosted.py:147](../../../src/hosted-agent/procurement_agent/hosted.py) | `ControllerContextProvider.before_run` | 197 |
| [hosted.py:200](../../../src/hosted-agent/procurement_agent/hosted.py) | `build_hosted_bundle` | 282 |
| [hosted.py:285](../../../src/hosted-agent/procurement_agent/hosted.py) | `_response_model` | 290 |
| [hosted.py:293](../../../src/hosted-agent/procurement_agent/hosted.py) | `_planner_format` | 297 |
| [hosted.py:300](../../../src/hosted-agent/procurement_agent/hosted.py) | `_with_response_text` | 365 |
| [hosted.py:368](../../../src/hosted-agent/procurement_agent/hosted.py) | `_intent` | 378 |
| [hosted.py:381](../../../src/hosted-agent/procurement_agent/hosted.py) | `_is_explicit_purchase_request` | 385 |
| [hosted.py:388](../../../src/hosted-agent/procurement_agent/hosted.py) | `_conversation_result` | 440 |
| [hosted.py:443](../../../src/hosted-agent/procurement_agent/hosted.py) | `_invoke_remote_tool` | 464 |
| [hosted.py:448](../../../src/hosted-agent/procurement_agent/hosted.py) | `_invoke_remote_tool.invoke` | 451 |
| [hosted.py:467](../../../src/hosted-agent/procurement_agent/hosted.py) | `_execute_hosted_components` | 626 |
| [controller.py:27](../../../src/hosted-agent/procurement_agent/controller.py) | `StructuredChildOutputError` | 28 |
| [controller.py:31](../../../src/hosted-agent/procurement_agent/controller.py) | `ChildCorrelationMismatchError` | 34 |
| [controller.py:32](../../../src/hosted-agent/procurement_agent/controller.py) | `ChildCorrelationMismatchError.__init__` | 34 |
| [controller.py:37](../../../src/hosted-agent/procurement_agent/controller.py) | `ChildInvocationError` | 40 |
| [controller.py:38](../../../src/hosted-agent/procurement_agent/controller.py) | `ChildInvocationError.__init__` | 40 |
| [controller.py:43](../../../src/hosted-agent/procurement_agent/controller.py) | `classify_child_invocation_exception` | 76 |
| [controller.py:79](../../../src/hosted-agent/procurement_agent/controller.py) | `child_operation_succeeded` | 88 |
| [controller.py:91](../../../src/hosted-agent/procurement_agent/controller.py) | `specification_mismatch_keys` | 102 |
| [controller.py:105](../../../src/hosted-agent/procurement_agent/controller.py) | `catalog_result_is_grounded` | 108 |
| [controller.py:111](../../../src/hosted-agent/procurement_agent/controller.py) | `_catalog_candidate_is_grounded` | 127 |
| [controller.py:130](../../../src/hosted-agent/procurement_agent/controller.py) | `_exact_grounded_catalog_match` | 148 |
| [controller.py:151](../../../src/hosted-agent/procurement_agent/controller.py) | `catalog_candidate_matches_specifications` | 164 |
| [controller.py:167](../../../src/hosted-agent/procurement_agent/controller.py) | `reject_ungrounded_catalog` | 171 |
| [controller.py:174](../../../src/hosted-agent/procurement_agent/controller.py) | `set_machine_status` | 188 |
| [controller.py:191](../../../src/hosted-agent/procurement_agent/controller.py) | `operation_status_attributes` | 207 |
| [controller.py:210](../../../src/hosted-agent/procurement_agent/controller.py) | `correlation_attributes` | 221 |
| [controller.py:224](../../../src/hosted-agent/procurement_agent/controller.py) | `apply_operation_status` | 233 |
| [controller.py:236](../../../src/hosted-agent/procurement_agent/controller.py) | `refresh_governance_decisions` | 240 |
| [controller.py:243](../../../src/hosted-agent/procurement_agent/controller.py) | `correlation` | 255 |
| [controller.py:258](../../../src/hosted-agent/procurement_agent/controller.py) | `_missing_fields` | 268 |
| [controller.py:271](../../../src/hosted-agent/procurement_agent/controller.py) | `_confirmation_preview` | 308 |
| [controller.py:311](../../../src/hosted-agent/procurement_agent/controller.py) | `_saved_confirmation_context` | 344 |
| [controller.py:347](../../../src/hosted-agent/procurement_agent/controller.py) | `invoke_validated` | 372 |
| [controller.py:375](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController` | 1040 |
| [controller.py:376](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController.__init__` | 379 |
| [controller.py:381](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController._finish` | 420 |
| [controller.py:422](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController._boundary_failure_result` | 461 |
| [controller.py:463](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController.invalid_intake_result` | 500 |
| [controller.py:502](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController._run_catalog_step` | 578 |
| [controller.py:580](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController._run_code_step` | 638 |
| [controller.py:640](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController._merge_validated` | 720 |
| [controller.py:722](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController.execute` | 1040 |
| [controller.py:785](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController.execute.finish` | 797 |
| [plan.py:17](../../../src/hosted-agent/procurement_agent/plan.py) | `PlanStateError` | 18 |
| [plan.py:21](../../../src/hosted-agent/procurement_agent/plan.py) | `DuplicateStepSuppressed` | 22 |
| [plan.py:32](../../../src/hosted-agent/procurement_agent/plan.py) | `stable_input_hash` | 34 |
| [plan.py:37](../../../src/hosted-agent/procurement_agent/plan.py) | `completed_step_key` | 38 |
| [plan.py:41](../../../src/hosted-agent/procurement_agent/plan.py) | `default_steps` | 42 |
| [plan.py:45](../../../src/hosted-agent/procurement_agent/plan.py) | `StructuredPlanBuilder` | 81 |
| [plan.py:48](../../../src/hosted-agent/procurement_agent/plan.py) | `StructuredPlanBuilder.build` | 81 |
| [plan.py:84](../../../src/hosted-agent/procurement_agent/plan.py) | `PlanExecutor` | 195 |
| [plan.py:85](../../../src/hosted-agent/procurement_agent/plan.py) | `PlanExecutor.__init__` | 89 |
| [plan.py:91](../../../src/hosted-agent/procurement_agent/plan.py) | `PlanExecutor.step` | 95 |
| [plan.py:97](../../../src/hosted-agent/procurement_agent/plan.py) | `PlanExecutor.next_step` | 100 |
| [plan.py:102](../../../src/hosted-agent/procurement_agent/plan.py) | `PlanExecutor.start` | 125 |
| [plan.py:127](../../../src/hosted-agent/procurement_agent/plan.py) | `PlanExecutor.complete` | 143 |
| [plan.py:145](../../../src/hosted-agent/procurement_agent/plan.py) | `PlanExecutor.reuse` | 164 |
| [plan.py:166](../../../src/hosted-agent/procurement_agent/plan.py) | `PlanExecutor.retry` | 177 |
| [plan.py:179](../../../src/hosted-agent/procurement_agent/plan.py) | `PlanExecutor.wait_for_user` | 186 |
| [plan.py:188](../../../src/hosted-agent/procurement_agent/plan.py) | `PlanExecutor.block` | 195 |
| [session_state.py:16](../../../src/hosted-agent/procurement_agent/session_state.py) | `SessionStateError` | 17 |
| [session_state.py:20](../../../src/hosted-agent/procurement_agent/session_state.py) | `SessionRequiredError` | 21 |
| [session_state.py:24](../../../src/hosted-agent/procurement_agent/session_state.py) | `SessionStateMissingError` | 25 |
| [session_state.py:28](../../../src/hosted-agent/procurement_agent/session_state.py) | `SessionStateSchemaError` | 29 |
| [session_state.py:32](../../../src/hosted-agent/procurement_agent/session_state.py) | `ProcurementExecutionState` | 52 |
| [session_state.py:55](../../../src/hosted-agent/procurement_agent/session_state.py) | `save_execution_state` | 56 |
| [session_state.py:59](../../../src/hosted-agent/procurement_agent/session_state.py) | `initialize_execution_state` | 62 |
| [session_state.py:65](../../../src/hosted-agent/procurement_agent/session_state.py) | `load_execution_state` | 76 |
| [session_state.py:79](../../../src/hosted-agent/procurement_agent/session_state.py) | `load_context_state` | 82 |
| [session_state.py:85](../../../src/hosted-agent/procurement_agent/session_state.py) | `restore_framework_session` | 88 |
| [azure_validation.py:42](../../../src/hosted-agent/procurement_agent/azure_validation.py) | `validation_request` | 67 |
| [azure_validation.py:70](../../../src/hosted-agent/procurement_agent/azure_validation.py) | `run_azure_validation` | 219 |

### App Service

| ソース | 関数／class | 最終行 |
| --- | --- | --- |
| [server.py:73](../../../src/webapp-foundry-oauth/backend/server.py) | `_extract_text_from_response` | 96 |
| [server.py:99](../../../src/webapp-foundry-oauth/backend/server.py) | `_sse` | 100 |
| [server.py:103](../../../src/webapp-foundry-oauth/backend/server.py) | `_parse_sse_payload` | 114 |
| [server.py:117](../../../src/webapp-foundry-oauth/backend/server.py) | `_tool_event_from_item` | 144 |
| [server.py:147](../../../src/webapp-foundry-oauth/backend/server.py) | `_event_status` | 157 |
| [server.py:160](../../../src/webapp-foundry-oauth/backend/server.py) | `_public_job` | 174 |
| [server.py:177](../../../src/webapp-foundry-oauth/backend/server.py) | `_public_conversation_state` | 194 |
| [server.py:213](../../../src/webapp-foundry-oauth/backend/server.py) | `_reset_conversation_state` | 222 |
| [server.py:228](../../../src/webapp-foundry-oauth/backend/server.py) | `ChatRequest` | 232 |
| [server.py:235](../../../src/webapp-foundry-oauth/backend/server.py) | `ContinueRequest` | 240 |
| [server.py:263](../../../src/webapp-foundry-oauth/backend/server.py) | `authenticated_api` | 274 |
| [server.py:285](../../../src/webapp-foundry-oauth/backend/server.py) | `_safe_b64decode_json` | 295 |
| [server.py:299](../../../src/webapp-foundry-oauth/backend/server.py) | `_decode_jwt_payload` | 312 |
| [server.py:315](../../../src/webapp-foundry-oauth/backend/server.py) | `_sanitize_token_claims` | 326 |
| [server.py:329](../../../src/webapp-foundry-oauth/backend/server.py) | `_extract_claim` | 342 |
| [server.py:345](../../../src/webapp-foundry-oauth/backend/server.py) | `_hash_user_key` | 346 |
| [server.py:349](../../../src/webapp-foundry-oauth/backend/server.py) | `_get_request_user` | 389 |
| [server.py:392](../../../src/webapp-foundry-oauth/backend/server.py) | `_conversation_state_key` | 393 |
| [server.py:397](../../../src/webapp-foundry-oauth/backend/server.py) | `_fetch_easyauth_me` | 418 |
| [server.py:421](../../../src/webapp-foundry-oauth/backend/server.py) | `_refresh_easyauth_tokens` | 434 |
| [server.py:437](../../../src/webapp-foundry-oauth/backend/server.py) | `_get_easyauth_refresh_token` | 465 |
| [server.py:468](../../../src/webapp-foundry-oauth/backend/server.py) | `_get_easyauth_access_token` | 491 |
| [server.py:494](../../../src/webapp-foundry-oauth/backend/server.py) | `_get_foundry_obo_config` | 518 |
| [server.py:522](../../../src/webapp-foundry-oauth/backend/server.py) | `_acquire_foundry_token_by_refresh_token` | 548 |
| [server.py:551](../../../src/webapp-foundry-oauth/backend/server.py) | `_acquire_foundry_token_on_behalf_of` | 577 |
| [server.py:580](../../../src/webapp-foundry-oauth/backend/server.py) | `_get_token` | 587 |
| [server.py:590](../../../src/webapp-foundry-oauth/backend/server.py) | `_build_outbound_headers` | 635 |
| [server.py:638](../../../src/webapp-foundry-oauth/backend/server.py) | `_validate_delegated_subject` | 646 |
| [server.py:649](../../../src/webapp-foundry-oauth/backend/server.py) | `_get_foundry_config` | 666 |
| [server.py:670](../../../src/webapp-foundry-oauth/backend/server.py) | `serve_index` | 672 |
| [server.py:678](../../../src/webapp-foundry-oauth/backend/server.py) | `_stream_response` | 1193 |
| [server.py:1200](../../../src/webapp-foundry-oauth/backend/server.py) | `health` | 1205 |
| [server.py:1209](../../../src/webapp-foundry-oauth/backend/server.py) | `me` | 1215 |
| [server.py:1219](../../../src/webapp-foundry-oauth/backend/server.py) | `get_conversation_state` | 1225 |
| [server.py:1229](../../../src/webapp-foundry-oauth/backend/server.py) | `delete_conversation_state` | 1235 |
| [server.py:1238](../../../src/webapp-foundry-oauth/backend/server.py) | `_cleanup_old_jobs` | 1247 |
| [server.py:1250](../../../src/webapp-foundry-oauth/backend/server.py) | `_append_job_event` | 1266 |
| [server.py:1269](../../../src/webapp-foundry-oauth/backend/server.py) | `_create_response_job` | 1309 |
| [server.py:1313](../../../src/webapp-foundry-oauth/backend/server.py) | `chat` | 1321 |
| [server.py:1325](../../../src/webapp-foundry-oauth/backend/server.py) | `continue_after_consent` | 1341 |
| [server.py:1345](../../../src/webapp-foundry-oauth/backend/server.py) | `get_job` | 1351 |
| [server.py:1355](../../../src/webapp-foundry-oauth/backend/server.py) | `cancel_job` | 1378 |
| [server.py:1382](../../../src/webapp-foundry-oauth/backend/server.py) | `stream_job_events` | 1418 |
| [server.py:1383](../../../src/webapp-foundry-oauth/backend/server.py) | `stream_job_events.event_stream` | 1408 |
| [procurement_flow.py:9](../../../src/webapp-foundry-oauth/backend/procurement_flow.py) | `public_event` | 15 |
| [procurement_flow.py:18](../../../src/webapp-foundry-oauth/backend/procurement_flow.py) | `_create_conversation` | 26 |
| [procurement_flow.py:29](../../../src/webapp-foundry-oauth/backend/procurement_flow.py) | `run` | 95 |
| [telemetry.py:22](../../../src/webapp-foundry-oauth/backend/telemetry.py) | `tracer` | 23 |
| [telemetry.py:27](../../../src/webapp-foundry-oauth/backend/telemetry.py) | `observe` | 37 |
| [telemetry.py:40](../../../src/webapp-foundry-oauth/backend/telemetry.py) | `_request_hook` | 42 |
| [telemetry.py:45](../../../src/webapp-foundry-oauth/backend/telemetry.py) | `http_client` | 51 |
| [telemetry.py:55](../../../src/webapp-foundry-oauth/backend/telemetry.py) | `lifespan` | 72 |
| [telemetry.py:75](../../../src/webapp-foundry-oauth/backend/telemetry.py) | `Instrumentation` | 87 |
| [telemetry.py:76](../../../src/webapp-foundry-oauth/backend/telemetry.py) | `Instrumentation.__init__` | 77 |
| [telemetry.py:79](../../../src/webapp-foundry-oauth/backend/telemetry.py) | `Instrumentation.__call__` | 87 |
| [telemetry.py:90](../../../src/webapp-foundry-oauth/backend/telemetry.py) | `BrowserBoundary` | 104 |
| [telemetry.py:92](../../../src/webapp-foundry-oauth/backend/telemetry.py) | `BrowserBoundary.__init__` | 93 |
| [telemetry.py:95](../../../src/webapp-foundry-oauth/backend/telemetry.py) | `BrowserBoundary.__call__` | 104 |
| [telemetry.py:108](../../../src/webapp-foundry-oauth/backend/telemetry.py) | `job_context` | 116 |

### Functions

| ソース | 関数／class | 最終行 |
| --- | --- | --- |
| [mcp_server.py:42](../../../src/functions-mcp-selfhosted/mcp_server.py) | `_get_env_int` | 50 |
| [mcp_server.py:53](../../../src/functions-mcp-selfhosted/mcp_server.py) | `_get_env_float` | 61 |
| [mcp_server.py:64](../../../src/functions-mcp-selfhosted/mcp_server.py) | `_backoff_delay` | 67 |
| [mcp_server.py:70](../../../src/functions-mcp-selfhosted/mcp_server.py) | `_normalize_bearer` | 72 |
| [mcp_server.py:75](../../../src/functions-mcp-selfhosted/mcp_server.py) | `_get_authorization_from_headers` | 80 |
| [mcp_server.py:83](../../../src/functions-mcp-selfhosted/mcp_server.py) | `extract_bearer_token_from_context` | 112 |
| [mcp_server.py:115](../../../src/functions-mcp-selfhosted/mcp_server.py) | `get_token_info` | 119 |
| [mcp_server.py:122](../../../src/functions-mcp-selfhosted/mcp_server.py) | `_sanitize_claims_for_log` | 132 |
| [mcp_server.py:135](../../../src/functions-mcp-selfhosted/mcp_server.py) | `log_inbound_token_summary` | 141 |
| [mcp_server.py:144](../../../src/functions-mcp-selfhosted/mcp_server.py) | `decode_jwt_payload` | 156 |
| [mcp_server.py:159](../../../src/functions-mcp-selfhosted/mcp_server.py) | `_split_csv_env` | 161 |
| [mcp_server.py:164](../../../src/functions-mcp-selfhosted/mcp_server.py) | `validate_incoming_token` | 208 |
| [mcp_server.py:211](../../../src/functions-mcp-selfhosted/mcp_server.py) | `_get_required_env` | 215 |
| [mcp_server.py:218](../../../src/functions-mcp-selfhosted/mcp_server.py) | `_get_graph_scopes` | 221 |
| [mcp_server.py:224](../../../src/functions-mcp-selfhosted/mcp_server.py) | `_get_confidential_client` | 236 |
| [mcp_server.py:239](../../../src/functions-mcp-selfhosted/mcp_server.py) | `acquire_graph_token_via_obo` | 296 |
| [mcp_server.py:299](../../../src/functions-mcp-selfhosted/mcp_server.py) | `call_graph_api` | 356 |
| [mcp_server.py:359](../../../src/functions-mcp-selfhosted/mcp_server.py) | `build_whoami_response` | 461 |
| [mcp_server.py:464](../../../src/functions-mcp-selfhosted/mcp_server.py) | `create_mcp_server` | 500 |
| [mcp_server.py:472](../../../src/functions-mcp-selfhosted/mcp_server.py) | `create_mcp_server.whoami` | 494 |
| [mcp_server.py:497](../../../src/functions-mcp-selfhosted/mcp_server.py) | `create_mcp_server.greet` | 498 |
| [mcp_server.py:503](../../../src/functions-mcp-selfhosted/mcp_server.py) | `app` | 507 |
| [mcp_telemetry.py:21](../../../src/functions-mcp-selfhosted/mcp_telemetry.py) | `step` | 30 |
| [mcp_telemetry.py:33](../../../src/functions-mcp-selfhosted/mcp_telemetry.py) | `carrier_from_mcp` | 39 |
| [mcp_telemetry.py:42](../../../src/functions-mcp-selfhosted/mcp_telemetry.py) | `record_outcome` | 50 |

### 設定・配布

| ソース | 関数／class | 最終行 |
| --- | --- | --- |
| [deploy_identity.py:31](../../../scripts/deploy_identity.py) | `api` | 38 |
| [deploy_identity.py:41](../../../scripts/deploy_identity.py) | `arm` | 43 |
| [deploy_identity.py:46](../../../scripts/deploy_identity.py) | `application` | 47 |
| [deploy_identity.py:50](../../../scripts/deploy_identity.py) | `configure_functions` | 93 |
| [deploy_identity.py:96](../../../scripts/deploy_identity.py) | `configure_web` | 131 |
| [deploy_foundry.py:46](../../../scripts/deploy_foundry.py) | `connection` | 61 |
| [deploy_foundry.py:64](../../../scripts/deploy_foundry.py) | `connections` | 77 |
| [deploy_foundry.py:80](../../../scripts/deploy_foundry.py) | `children` | 132 |
| [deploy_foundry.py:135](../../../scripts/deploy_foundry.py) | `hosted` | 174 |
| [package_hosted.py:14](../../../scripts/package_hosted.py) | `package` | 32 |
| [package-procurement.py:7](../../../src/webapp-foundry-oauth/scripts/package-procurement.py) | `main` | 24 |

## 3. Span・event・属性・通常loggerの直接呼び出し

現在のアプリソースから抽出した記録位置。SDK内の自動Agent/Chat/Function/MCP/HTTP Spanはこの一覧に含めない。logger呼び出しは通常loggingであり、OTel LogExporterを構成した証拠ではない。表示するのはソースのテンプレート／属性名であり実行値ではない。

### Hosted

| ソース | 所属関数 | 記録API | 名称／属性／テンプレート |
| --- | --- | --- | --- |
| [observability.py:128](../../../src/hosted-agent/procurement_agent/observability.py) | `TelemetryRecorder.span` | `self.tracer.start_as_current_span` | name |
| [observability.py:133](../../../src/hosted-agent/procurement_agent/observability.py) | `TelemetryRecorder.event` | `span.add_event` | name |
| [identity.py:86](../../../src/hosted-agent/procurement_agent/identity.py) | `build_identity_tool.lookup` | `trace.get_tracer('procurement.identity').start_as_current_span` | identity.lookup |
| [identity.py:100](../../../src/hosted-agent/procurement_agent/identity.py) | `build_identity_tool.lookup` | `span.set_attribute` | app.identity.tool.count |
| [identity.py:101](../../../src/hosted-agent/procurement_agent/identity.py) | `build_identity_tool.lookup` | `span.set_attribute` | app.identity.tool.names |
| [identity.py:109](../../../src/hosted-agent/procurement_agent/identity.py) | `build_identity_tool.lookup` | `span.set_attribute` | app.identity.tool.available |
| [identity.py:123](../../../src/hosted-agent/procurement_agent/identity.py) | `build_identity_tool.lookup` | `span.set_attribute` | error.type |
| [identity.py:124](../../../src/hosted-agent/procurement_agent/identity.py) | `build_identity_tool.lookup` | `span.set_attribute` | app.identity.error.type |
| [identity.py:125](../../../src/hosted-agent/procurement_agent/identity.py) | `build_identity_tool.lookup` | `span.set_attribute` | app.identity.error.stage |
| [identity.py:131](../../../src/hosted-agent/procurement_agent/identity.py) | `build_identity_tool.lookup` | `span.set_attribute` | app.identity.error.rpc_code |
| [identity.py:133](../../../src/hosted-agent/procurement_agent/identity.py) | `build_identity_tool.lookup` | `span.set_status` | trace.StatusCode.ERROR |
| [identity.py:134](../../../src/hosted-agent/procurement_agent/identity.py) | `build_identity_tool.lookup` | `span.set_attribute` | app.identity.lookup.status |
| [hosted.py:157](../../../src/hosted-agent/procurement_agent/hosted.py) | `ControllerContextProvider.before_run` | `trace.get_current_span().set_attributes` | attributes |
| [hosted.py:430](../../../src/hosted-agent/procurement_agent/hosted.py) | `_conversation_result` | `telemetry.span` | response.generate |
| [hosted.py:431](../../../src/hosted-agent/procurement_agent/hosted.py) | `_conversation_result` | `telemetry.event` | span |
| [hosted.py:610](../../../src/hosted-agent/procurement_agent/hosted.py) | `_execute_hosted_components` | `span.set_attribute` | error.type |
| [hosted.py:614](../../../src/hosted-agent/procurement_agent/hosted.py) | `_execute_hosted_components` | `span.set_attribute` | error.http_status |
| [controller.py:233](../../../src/hosted-agent/procurement_agent/controller.py) | `apply_operation_status` | `span.set_attribute` | key |
| [controller.py:403](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController._finish` | `self.telemetry.span` | response.generate |
| [controller.py:404](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController._finish` | `self.telemetry.event` | span |
| [controller.py:521](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController._run_catalog_step` | `self.telemetry.span` | plan.step.execute |
| [controller.py:528](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController._run_catalog_step` | `self.telemetry.event` | catalog_span |
| [controller.py:531](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController._run_catalog_step` | `self.telemetry.event` | catalog_span |
| [controller.py:539](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController._run_catalog_step` | `self.telemetry.event` | catalog_span |
| [controller.py:559](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController._run_catalog_step` | `self.telemetry.event` | catalog_span |
| [controller.py:563](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController._run_catalog_step` | `self.telemetry.event` | catalog_span |
| [controller.py:568](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController._run_catalog_step` | `self.telemetry.event` | catalog_span |
| [controller.py:570](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController._run_catalog_step` | `self.telemetry.event` | catalog_span |
| [controller.py:573](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController._run_catalog_step` | `self.telemetry.event` | catalog_span |
| [controller.py:601](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController._run_code_step` | `self.telemetry.span` | plan.step.execute |
| [controller.py:608](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController._run_code_step` | `self.telemetry.event` | code_span |
| [controller.py:611](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController._run_code_step` | `self.telemetry.event` | code_span |
| [controller.py:619](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController._run_code_step` | `self.telemetry.event` | code_span |
| [controller.py:631](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController._run_code_step` | `self.telemetry.event` | code_span |
| [controller.py:634](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController._run_code_step` | `self.telemetry.event` | code_span |
| [controller.py:653](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController._merge_validated` | `self.telemetry.span` | merge.validate |
| [controller.py:659](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController._merge_validated` | `self.telemetry.event` | merge_span |
| [controller.py:685](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController._merge_validated` | `self.telemetry.event` | merge_span |
| [controller.py:700](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController._merge_validated` | `self.telemetry.event` | merge_span |
| [controller.py:778](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController.execute` | `self.telemetry.span` | plan.create |
| [controller.py:781](../../../src/hosted-agent/procurement_agent/controller.py) | `ProcurementController.execute` | `self.telemetry.event` | span |
| [azure_validation.py:187](../../../src/hosted-agent/procurement_agent/azure_validation.py) | `run_azure_validation` | `telemetry.span` | semantic.evaluate |
| [azure_validation.py:188](../../../src/hosted-agent/procurement_agent/azure_validation.py) | `run_azure_validation` | `telemetry.event` | evaluation_span |
| [azure_validation.py:196](../../../src/hosted-agent/procurement_agent/azure_validation.py) | `run_azure_validation` | `telemetry.event` | evaluation_span |
| [azure_validation.py:201](../../../src/hosted-agent/procurement_agent/azure_validation.py) | `run_azure_validation` | `telemetry.event` | evaluation_span |

### App Service

| ソース | 所属関数 | 記録API | 名称／属性／テンプレート |
| --- | --- | --- | --- |
| [server.py:217](../../../src/webapp-foundry-oauth/backend/server.py) | `_reset_conversation_state` | `logger.warning` | Conversation state reset: conversation=%s owner=%s reason=%s |
| [server.py:382](../../../src/webapp-foundry-oauth/backend/server.py) | `_get_request_user` | `trace.get_current_span().set_attribute` | user.id |
| [server.py:409](../../../src/webapp-foundry-oauth/backend/server.py) | `_fetch_easyauth_me` | `logger.warning` | /.auth/me returned HTTP %s |
| [server.py:417](../../../src/webapp-foundry-oauth/backend/server.py) | `_fetch_easyauth_me` | `logger.warning` | Failed to fetch /.auth/me: %s |
| [server.py:432](../../../src/webapp-foundry-oauth/backend/server.py) | `_refresh_easyauth_tokens` | `logger.info` | /.auth/refresh returned HTTP %s |
| [server.py:434](../../../src/webapp-foundry-oauth/backend/server.py) | `_refresh_easyauth_tokens` | `logger.warning` | Failed to call /.auth/refresh: %s |
| [server.py:446](../../../src/webapp-foundry-oauth/backend/server.py) | `_get_easyauth_refresh_token` | `logger.info` | Using EasyAuth refresh token from /.auth/me entry provider=%s |
| [server.py:454](../../../src/webapp-foundry-oauth/backend/server.py) | `_get_easyauth_refresh_token` | `logger.info` | Using EasyAuth refresh token from /.auth/me after refresh provider=%s |
| [server.py:458](../../../src/webapp-foundry-oauth/backend/server.py) | `_get_easyauth_refresh_token` | `logger.warning` | EasyAuth refresh token not found. /.auth/me keys=%s |
| [server.py:484](../../../src/webapp-foundry-oauth/backend/server.py) | `_get_easyauth_access_token` | `logger.error` | EasyAuth principal does not match access token claims: principal=%s token_claims=%s |
| [server.py:490](../../../src/webapp-foundry-oauth/backend/server.py) | `_get_easyauth_access_token` | `logger.info` | EasyAuth access token claims: %s |
| [server.py:533](../../../src/webapp-foundry-oauth/backend/server.py) | `_acquire_foundry_token_by_refresh_token` | `logger.info` | Acquired Foundry user delegated token via EasyAuth refresh token: scopes=%s claims=%s |
| [server.py:539](../../../src/webapp-foundry-oauth/backend/server.py) | `_acquire_foundry_token_by_refresh_token` | `logger.error` | Failed to acquire Foundry token by refresh token: error=%s suberror=%s correlation_id=%s |
| [server.py:562](../../../src/webapp-foundry-oauth/backend/server.py) | `_acquire_foundry_token_on_behalf_of` | `logger.info` | Acquired Foundry user delegated token via OBO: scopes=%s claims=%s |
| [server.py:568](../../../src/webapp-foundry-oauth/backend/server.py) | `_acquire_foundry_token_on_behalf_of` | `logger.error` | Failed to acquire Foundry token via OBO: error=%s suberror=%s correlation_id=%s |
| [server.py:623](../../../src/webapp-foundry-oauth/backend/server.py) | `_build_outbound_headers` | `logger.info` | Forwarding EasyAuth access token to Foundry/APIM: claims=%s |
| [server.py:743](../../../src/webapp-foundry-oauth/backend/server.py) | `_stream_response` | `logger.info` | Calling Foundry Agent endpoint Responses API url=%s previous_response_id=%s agent=%s |
| [server.py:805](../../../src/webapp-foundry-oauth/backend/server.py) | `_stream_response` | `logger.debug` | Non-JSON SSE data skipped |
| [server.py:847](../../../src/webapp-foundry-oauth/backend/server.py) | `_stream_response` | `logger.info` | Tool call started: %s (call_id=%s) |
| [server.py:868](../../../src/webapp-foundry-oauth/backend/server.py) | `_stream_response` | `logger.info` | OAuth consent detected (output item); draining Foundry stream before UI notification: connection=%s response_id=%s |
| [server.py:890](../../../src/webapp-foundry-oauth/backend/server.py) | `_stream_response` | `logger.info` | MCP approval detected; draining Foundry stream before UI notification: server=%s tool=%s approval_id=%s response_id=%s |
| [server.py:915](../../../src/webapp-foundry-oauth/backend/server.py) | `_stream_response` | `logger.info` | MCP approval detected (direct event); draining Foundry stream before UI notification: server=%s tool=%s approval_id=%s response_id=%s |
| [server.py:935](../../../src/webapp-foundry-oauth/backend/server.py) | `_stream_response` | `logger.info` | Tool call done: %s (call_id=%s) |
| [server.py:993](../../../src/webapp-foundry-oauth/backend/server.py) | `_stream_response` | `logger.info` | OAuth consent detected; draining Foundry stream before UI notification: connection=%s response_id=%s |
| [server.py:1010](../../../src/webapp-foundry-oauth/backend/server.py) | `_stream_response` | `logger.info` | OAuth consent detected (embedded); draining Foundry stream before UI notification: connection=%s response_id=%s |
| [server.py:1035](../../../src/webapp-foundry-oauth/backend/server.py) | `_stream_response` | `logger.info` | Foundry response completed upstream; draining remaining SSE framing: %s |
| [server.py:1043](../../../src/webapp-foundry-oauth/backend/server.py) | `_stream_response` | `logger.error` | msg |
| [server.py:1051](../../../src/webapp-foundry-oauth/backend/server.py) | `_stream_response` | `logger.error` | Foundry stream ended before response.completed; response_id=%s deferred_action=%s |
| [server.py:1123](../../../src/webapp-foundry-oauth/backend/server.py) | `_stream_response` | `logger.info` | MCP approval ready after completed response: response_id=%s approval_ids=%s consent_pending=%s |
| [server.py:1140](../../../src/webapp-foundry-oauth/backend/server.py) | `_stream_response` | `logger.info` | OAuth consent ready after completed response: response_id=%s connection=%s |
| [server.py:1151](../../../src/webapp-foundry-oauth/backend/server.py) | `_stream_response` | `logger.info` | Response completed: %s |
| [server.py:1156](../../../src/webapp-foundry-oauth/backend/server.py) | `_stream_response` | `logger.error` | msg |
| [server.py:1164](../../../src/webapp-foundry-oauth/backend/server.py) | `_stream_response` | `logger.warning` | Foundry rejected previous_response_id; retrying once without conversation state: conversation=%s rejected_previous_response_id=%s |
| [server.py:1192](../../../src/webapp-foundry-oauth/backend/server.py) | `_stream_response` | `logger.error` | msg |
| [procurement_flow.py:34](../../../src/webapp-foundry-oauth/backend/procurement_flow.py) | `run` | `telemetry.job_context` | user['storage_key'] |
| [procurement_flow.py:34](../../../src/webapp-foundry-oauth/backend/procurement_flow.py) | `run` | `telemetry.observe` | web.chat.job |
| [procurement_flow.py:47](../../../src/webapp-foundry-oauth/backend/procurement_flow.py) | `run` | `telemetry.observe` | auth.foundry.token |
| [procurement_flow.py:50](../../../src/webapp-foundry-oauth/backend/procurement_flow.py) | `run` | `telemetry.observe` | procurement.agent.invoke |
| [procurement_flow.py:53](../../../src/webapp-foundry-oauth/backend/procurement_flow.py) | `run` | `invocation.set_attribute` | gen_ai.conversation.id |
| [procurement_flow.py:69](../../../src/webapp-foundry-oauth/backend/procurement_flow.py) | `run` | `invocation.set_attribute` | gen_ai.response.id |
| [procurement_flow.py:76](../../../src/webapp-foundry-oauth/backend/procurement_flow.py) | `run` | `invocation.set_status` | StatusCode.ERROR |
| [procurement_flow.py:82](../../../src/webapp-foundry-oauth/backend/procurement_flow.py) | `run` | `invocation.set_status` | StatusCode.ERROR |
| [procurement_flow.py:87](../../../src/webapp-foundry-oauth/backend/procurement_flow.py) | `run` | `span.set_attribute` | app.cancelled |
| [procurement_flow.py:91](../../../src/webapp-foundry-oauth/backend/procurement_flow.py) | `run` | `span.set_attribute` | error.type |
| [procurement_flow.py:92](../../../src/webapp-foundry-oauth/backend/procurement_flow.py) | `run` | `span.set_status` | StatusCode.ERROR |
| [telemetry.py:28](../../../src/webapp-foundry-oauth/backend/telemetry.py) | `observe` | `tracer().start_as_current_span` | name |
| [telemetry.py:35](../../../src/webapp-foundry-oauth/backend/telemetry.py) | `observe` | `span.set_attribute` | error.type |
| [telemetry.py:36](../../../src/webapp-foundry-oauth/backend/telemetry.py) | `observe` | `span.set_status` | StatusCode.ERROR |
| [telemetry.py:42](../../../src/webapp-foundry-oauth/backend/telemetry.py) | `_request_hook` | `span.set_attributes` | job_attributes.get() |

### Functions

| ソース | 所属関数 | 記録API | 名称／属性／テンプレート |
| --- | --- | --- | --- |
| [mcp_server.py:19](../../../src/functions-mcp-selfhosted/mcp_server.py) | `(module)` | `logger.setLevel` | logging.INFO |
| [mcp_server.py:27](../../../src/functions-mcp-selfhosted/mcp_server.py) | `(module)` | `logger.info` | Graph scope configuration loaded: GRAPH_SCOPES set=%s default_scopes=%s |
| [mcp_server.py:49](../../../src/functions-mcp-selfhosted/mcp_server.py) | `_get_env_int` | `logger.warning` | Invalid integer for %s: %s. Using default %s. |
| [mcp_server.py:60](../../../src/functions-mcp-selfhosted/mcp_server.py) | `_get_env_float` | `logger.warning` | Invalid float for %s: %s. Using default %s. |
| [mcp_server.py:110](../../../src/functions-mcp-selfhosted/mcp_server.py) | `extract_bearer_token_from_context` | `logger.warning` | Failed to extract Authorization header from context: %s |
| [mcp_server.py:137](../../../src/functions-mcp-selfhosted/mcp_server.py) | `log_inbound_token_summary` | `logger.info` | Inbound token summary: received=%s claims=%s |
| [mcp_server.py:220](../../../src/functions-mcp-selfhosted/mcp_server.py) | `_get_graph_scopes` | `logger.info` | Graph OBO scopes resolved: %s |
| [mcp_server.py:260](../../../src/functions-mcp-selfhosted/mcp_server.py) | `acquire_graph_token_via_obo` | `logger.info` | OBO token exchange succeeded after retry %s/%s. |
| [mcp_server.py:271](../../../src/functions-mcp-selfhosted/mcp_server.py) | `acquire_graph_token_via_obo` | `logger.warning` | OBO token exchange attempt %s/%s failed: %s |
| [mcp_server.py:285](../../../src/functions-mcp-selfhosted/mcp_server.py) | `acquire_graph_token_via_obo` | `logger.error` | OBO token exchange failed after retries |
| [mcp_server.py:314](../../../src/functions-mcp-selfhosted/mcp_server.py) | `call_graph_api` | `logger.warning` | Graph API call attempt %s/%s returned retryable status %s. |
| [mcp_server.py:327](../../../src/functions-mcp-selfhosted/mcp_server.py) | `call_graph_api` | `logger.info` | Graph API call succeeded after retry %s/%s. |
| [mcp_server.py:332](../../../src/functions-mcp-selfhosted/mcp_server.py) | `call_graph_api` | `logger.warning` | Graph API call attempt %s/%s failed: %s |
| [mcp_server.py:339](../../../src/functions-mcp-selfhosted/mcp_server.py) | `call_graph_api` | `logger.error` | Graph API call failed after retries: %s |
| [mcp_server.py:364](../../../src/functions-mcp-selfhosted/mcp_server.py) | `build_whoami_response` | `logger.warning` | Inbound token validation failed |
| [mcp_server.py:376](../../../src/functions-mcp-selfhosted/mcp_server.py) | `build_whoami_response` | `span.set_attribute` | app.obo.success |
| [mcp_server.py:378](../../../src/functions-mcp-selfhosted/mcp_server.py) | `build_whoami_response` | `logger.error` | OBO configuration error: %s |
| [mcp_server.py:386](../../../src/functions-mcp-selfhosted/mcp_server.py) | `build_whoami_response` | `logger.error` | OBO exchange failed for inbound claims=%s correlation_id=%s trace_id=%s |
| [mcp_server.py:401](../../../src/functions-mcp-selfhosted/mcp_server.py) | `build_whoami_response` | `span.set_attribute` | app.graph.success |
| [mcp_server.py:409](../../../src/functions-mcp-selfhosted/mcp_server.py) | `build_whoami_response` | `logger.error` | Security check failed: inbound token oid does not match Graph /me id. inbound_claims=%s graph_user_id_present=%s |
| [mcp_server.py:420](../../../src/functions-mcp-selfhosted/mcp_server.py) | `build_whoami_response` | `logger.warning` | Security check skipped because user identifiers are incomplete: inbound_claims=%s graph_user_id_present=%s |
| [mcp_server.py:425](../../../src/functions-mcp-selfhosted/mcp_server.py) | `build_whoami_response` | `logger.info` | whoami succeeded: inbound_claims=%s obo_attempts=%s graph_attempts=%s |
| [mcp_server.py:451](../../../src/functions-mcp-selfhosted/mcp_server.py) | `build_whoami_response` | `logger.error` | Failed to call Graph API: error=%s status_code=%s inbound_claims=%s |
| [mcp_server.py:485](../../../src/functions-mcp-selfhosted/mcp_server.py) | `create_mcp_server.whoami` | `logger.info` | whoami MCP tool called (python runtime, OBO) |
| [mcp_telemetry.py:23](../../../src/functions-mcp-selfhosted/mcp_telemetry.py) | `step` | `tracer.start_as_current_span` | name |
| [mcp_telemetry.py:28](../../../src/functions-mcp-selfhosted/mcp_telemetry.py) | `step` | `span.set_attribute` | error.type |
| [mcp_telemetry.py:29](../../../src/functions-mcp-selfhosted/mcp_telemetry.py) | `step` | `span.set_status` | trace.StatusCode.ERROR |
| [mcp_telemetry.py:44](../../../src/functions-mcp-selfhosted/mcp_telemetry.py) | `record_outcome` | `span.set_attribute` | app.identity.lookup.status |
| [mcp_telemetry.py:48](../../../src/functions-mcp-selfhosted/mcp_telemetry.py) | `record_outcome` | `span.set_attribute` | user.id |
| [mcp_telemetry.py:50](../../../src/functions-mcp-selfhosted/mcp_telemetry.py) | `record_outcome` | `span.set_status` | trace.StatusCode.ERROR |

## 4. ローカルSDKバージョン

| Package | root .venvの実値 |
| --- | --- |
| agent-framework-core | 1.16.0 |
| agent-framework-foundry-hosting | 1.0.0b260827 |
| agent-framework-foundry | 1.11.0 |
| azure-ai-projects | 2.3.0 |
| azure-ai-agentserver-core | 2.1.0 |
| microsoft-opentelemetry | 1.3.8 |
| opentelemetry-api | 1.43.0 |
| opentelemetry-sdk | 1.43.0 |
| azure-monitor-opentelemetry-exporter | 1.0.0b56 |
| opentelemetry-instrumentation-asgi | 0.64b0 |
| opentelemetry-instrumentation-httpx | 0.64b0 |
| mcp | 1.29.1 |

McpPrivacyProcessorはOTel SDK 1.43の_on_ending、OAuth bridgeはHosted SDKのResponses内部APIを使用する。SDK更新時はidentity/protocolの契約テストを確認する。Webの依存同梱ZIP・Functionsのremote buildはそれぞれ別環境なので、root .venvだけでその導入実体を保証しない。

## 5. ファイルhash

「変更」は基準HEADとの差、「新規」は未追跡、「SDK」はローカルinstalled fileを意味する。全ファイルの完全なSHA-256を掲載する。資料自身の循環hashは作らない。

| ファイル | 行数 | 状態 | SHA-256 |
| --- | --- | --- | --- |
| [.foundry/agent-metadata.yaml](../../../.foundry/agent-metadata.yaml) | 280 | 変更 | `a46853ef81cec897c54a2ca4a07f4a8c45ae54449823af16163a8bcafe9ecb4b` |
| [.venv/lib/python3.13/site-packages/agent_framework/_agents.py](../../../.venv/lib/python3.13/site-packages/agent_framework/_agents.py) | 1948 | SDK | `362f9cc98fda41cefc7a900fa7e5900b61f21783f69349a482f8ef26f6a69bec` |
| [.venv/lib/python3.13/site-packages/agent_framework/observability.py](../../../.venv/lib/python3.13/site-packages/agent_framework/observability.py) | 3703 | SDK | `13123cfcdb300285514d8eaef8a1878f29a37e607192801c71d1582cc16d47ab` |
| [.venv/lib/python3.13/site-packages/agent_framework_foundry_hosting-1.0.0b260827.dist-info/METADATA](../../../.venv/lib/python3.13/site-packages/agent_framework_foundry_hosting-1.0.0b260827.dist-info/METADATA) | 79 | SDK | `3da86c799e3fe41e8ca44a5ede38f439f99c45c9283ef5ddf97170644020f50e` |
| [.venv/lib/python3.13/site-packages/agent_framework_foundry_hosting/_responses.py](../../../.venv/lib/python3.13/site-packages/agent_framework_foundry_hosting/_responses.py) | 2076 | SDK | `e944316a94eafd7c31fe90c60667d8d01b24615e2825b04dbe7f4f5e9b0b43f7` |
| [.venv/lib/python3.13/site-packages/azure/ai/agentserver/core/_base.py](../../../.venv/lib/python3.13/site-packages/azure/ai/agentserver/core/_base.py) | 665 | SDK | `8a1686fc867385a93ababdafa8b111e1bb7945e529f8cfd83b4de399807e31b5` |
| [.venv/lib/python3.13/site-packages/azure/ai/agentserver/core/_tracing.py](../../../.venv/lib/python3.13/site-packages/azure/ai/agentserver/core/_tracing.py) | 829 | SDK | `7f7ca3c2832b83acaec8619438c7bd0bc43adb536264a269cbb2f339133f0202` |
| [.venv/lib/python3.13/site-packages/azure/monitor/opentelemetry/exporter/export/trace/_exporter.py](../../../.venv/lib/python3.13/site-packages/azure/monitor/opentelemetry/exporter/export/trace/_exporter.py) | 621 | SDK | `f1d868fa3f2af25c0191504d261aae80bdbfe04cf76702299946ed9ed8daa23f` |
| [.venv/lib/python3.13/site-packages/azure_ai_agentserver_core-2.1.0.dist-info/METADATA](../../../.venv/lib/python3.13/site-packages/azure_ai_agentserver_core-2.1.0.dist-info/METADATA) | 294 | SDK | `bf38e7ac779851286d48e76dcd76384af0a0e0ed0c6f01530819ea742417b7e3` |
| [.venv/lib/python3.13/site-packages/mcp/server/fastmcp/server.py](../../../.venv/lib/python3.13/site-packages/mcp/server/fastmcp/server.py) | 1366 | SDK | `f4360eec1cca411afa55762a223d103236e856cc8b52944ef64ff337c8e970c2` |
| [.venv/lib/python3.13/site-packages/mcp/shared/context.py](../../../.venv/lib/python3.13/site-packages/mcp/shared/context.py) | 32 | SDK | `40c447c1708826cbdfe14def720a9201769a50430a85f8fff5794223e9149271` |
| [.venv/lib/python3.13/site-packages/mcp/types.py](../../../.venv/lib/python3.13/site-packages/mcp/types.py) | 1999 | SDK | `6824109cd1eabaf43c5dab829a83015b1b88ec9ae149765e6814afaf23f9bde5` |
| [.venv/lib/python3.13/site-packages/microsoft_opentelemetry-1.3.8.dist-info/METADATA](../../../.venv/lib/python3.13/site-packages/microsoft_opentelemetry-1.3.8.dist-info/METADATA) | 432 | SDK | `77fe095d226c77285d6f6ceb7c68b8cfd809646a0486603cfb589b7bfe137fb1` |
| [.venv/lib/python3.13/site-packages/opentelemetry/sdk/trace/__init__.py](../../../.venv/lib/python3.13/site-packages/opentelemetry/sdk/trace/__init__.py) | 1476 | SDK | `09386c185c308437ad63d2fc015c80601b3ee648ee6cf93e65d11b823bf529e2` |
| [README.md](../../../README.md) | 62 | 変更 | `a6890a178a4b8374d1d6d4ed65b3b8c1e487caeb1b9e2ce8af14eb51d18cdcc1` |
| [azure.yaml](../../../azure.yaml) | 72 | HEAD一致 | `8f37e30e1768676396996e182f16c58422933203be57547999637f8ff9386e85` |
| [docs/azure-observability-validation-2026-09-03.md](../../azure-observability-validation-2026-09-03.md) | 219 | HEAD一致 | `c4153dabcf54ea357cf3664b5f0efd3424660bd52242c0a07ec83ae41ec770ed` |
| [docs/report/validation-results-2026-09-06.md](../../report/validation-results-2026-09-06.md) | 160 | HEAD一致 | `77d8cc792420c0e34b2a7ef9e3cee6de3dfe273b1f64564c66147e05364bd33c` |
| [docs/report/validation-results-2026-09-08-obo.md](../../report/validation-results-2026-09-08-obo.md) | 55 | 新規 | `1b01681a7dfd565a896ba4dc598550fe2ccdf843c9ede86bb29c519f9a48b10e` |
| [infra/apim-foundry-policy.xml](../../../infra/apim-foundry-policy.xml) | 16 | 新規 | `e42a0b9dacda3b8e31517fc10c39557a91306f3db5b101eb6975bdcfafa07f7d` |
| [infra/apim.bicep](../../../infra/apim.bicep) | 97 | 変更 | `707c5e12719b0f7e5c0fc2aec590b2dbfb7e43931146639ef6bac23a1563f271` |
| [infra/foundry/agents/catalog-search-agent.yaml](../../../infra/foundry/agents/catalog-search-agent.yaml) | 10 | HEAD一致 | `b34c7c5b3718e7af73bf55cd1281d93375c9d7b6d5283f1d5d7626e979132265` |
| [infra/foundry/agents/code-determination-agent.yaml](../../../infra/foundry/agents/code-determination-agent.yaml) | 10 | HEAD一致 | `286d231693ab784a0a53fed9a339d3f1c6d121e44cb5cc4347b0e50fe66d6453` |
| [infra/foundry/toolboxes/catalog-search-toolbox.yaml](../../../infra/foundry/toolboxes/catalog-search-toolbox.yaml) | 13 | HEAD一致 | `2dbc014dd6e2d2b9094e9e2f70fffe0179ddfde7b5f93eecf5bef2afa9330a3e` |
| [infra/foundry/toolboxes/code-master-toolbox.yaml](../../../infra/foundry/toolboxes/code-master-toolbox.yaml) | 13 | HEAD一致 | `cbbf03b59d245764a5674e4faa935fc093980cf8714691043b2e838a0790ba96` |
| [infra/identity-functions.bicep](../../../infra/identity-functions.bicep) | 152 | 新規 | `95237fb573a6dc5a424d247f5e7002ef25831f2de1d268ea42eef3e069436099` |
| [infra/observability/instrumentation-manifest.json](../../../infra/observability/instrumentation-manifest.json) | 10 | HEAD一致 | `ffa01bfe27c7c361135f0c7be9a91592b21441743e536175351553435510a413` |
| [infra/observability/kql/core-status-correlation.kql](../../../infra/observability/kql/core-status-correlation.kql) | 15 | HEAD一致 | `0c52b4191cd89dfe2cd15d3278f45f111f4bb2c6935723201d6a5855252cfa2b` |
| [infra/observability/kql/export-exact-operation.kql](../../../infra/observability/kql/export-exact-operation.kql) | 6 | HEAD一致 | `bb45b2cc73bd07a2c5cf396f362b5d19833901e78160688366bfc3d116a2669c` |
| [infra/webui.bicep](../../../infra/webui.bicep) | 204 | 変更 | `574bf7b8067be2251f1b5d08ac87c1c5dd4572a94069f3e5a7abb14611c38463` |
| [main.py](../../../main.py) | 7 | HEAD一致 | `a6248ab8ab406846e4b955307b542d60c15a3e738b52f0c72c381cf11d5d612c` |
| [pyproject.toml](../../../pyproject.toml) | 39 | HEAD一致 | `7fe06cfdebf43afa77898cfc2b7138f1b226b7e4c1adc34dbbd428ee1d90494b` |
| [requirements-lock.txt](../../../requirements-lock.txt) | 130 | HEAD一致 | `959820d4364604e4798e2479fdf94e41744fd7e45a04a8fbbfb9e46a72d10065` |
| [requirements.txt](../../../requirements.txt) | 14 | HEAD一致 | `af9f5bb73e98ef6e87ac73bc4d40439b711ad4208278c874801212ca97f6558d` |
| [scripts/deploy_foundation.py](../../../scripts/deploy_foundation.py) | 153 | HEAD一致 | `64a6226972c854e28d85a20aea2f6f7dbb3e7260f78a7d49f107dda1e646b3a8` |
| [scripts/deploy_foundry.py](../../../scripts/deploy_foundry.py) | 198 | 変更 | `ca080c6a1a63b2122b700d32cf7c971474210ec5126da9e662dd4a6e27fb93a1` |
| [scripts/deploy_identity.py](../../../scripts/deploy_identity.py) | 142 | 新規 | `e9479c75cbd75b3ee5ecd1d522aa298d6b8327e74e8888a0bc5a493e4cc312c6` |
| [scripts/export_trace_evidence.py](../../../scripts/export_trace_evidence.py) | 127 | HEAD一致 | `910cdc339558ff433fe29887acf2d7292f292c37e1014c2198b285a0041b16d9` |
| [scripts/package_hosted.py](../../../scripts/package_hosted.py) | 38 | HEAD一致 | `1e1c5f388dce0da6505033d4de234167d4b3615fa924fc0be86026064eef7cb8` |
| [scripts/run_s5_boundary_validation.py](../../../scripts/run_s5_boundary_validation.py) | 196 | HEAD一致 | `a44e37e91fe855796e3bd836dfd340b43b946909da3688cd7c140a95fc3b5d64` |
| [src/functions-mcp-selfhosted/host.json](../../../src/functions-mcp-selfhosted/host.json) | 8 | HEAD一致 | `877b38fa6be86aedecd583f347cea814f1fa6f6c38c98ed36f514426abf84813` |
| [src/functions-mcp-selfhosted/infra/azure/main.bicep](../../../src/functions-mcp-selfhosted/infra/azure/main.bicep) | 158 | HEAD一致 | `6e322c272517efb61b63e6896cd34e89913c6370fc7cf26697c808c605573709` |
| [src/functions-mcp-selfhosted/mcp_handler/__init__.py](../../../src/functions-mcp-selfhosted/mcp_handler/__init__.py) | 6 | HEAD一致 | `a038ab913d2992c6c21c3c396ca0ab48c9460f34190ba3fb1a174f743eac77f5` |
| [src/functions-mcp-selfhosted/mcp_handler/function.json](../../../src/functions-mcp-selfhosted/mcp_handler/function.json) | 26 | HEAD一致 | `c6952c2b5481d6f074fcba6c379a5a30562ab3fb0c14a274a59ee7fc4bad47aa` |
| [src/functions-mcp-selfhosted/mcp_server.py](../../../src/functions-mcp-selfhosted/mcp_server.py) | 507 | 変更 | `1d9b7f6b584e58be2c24a414a900c8b94f205fdc58373491c3e450ca6820f45e` |
| [src/functions-mcp-selfhosted/mcp_telemetry.py](../../../src/functions-mcp-selfhosted/mcp_telemetry.py) | 50 | 新規 | `0551372d861f62692f9450a1b82d9a5fded562815df50ab5be1c4564015de622` |
| [src/functions-mcp-selfhosted/pyproject.toml](../../../src/functions-mcp-selfhosted/pyproject.toml) | 13 | HEAD一致 | `3035132d9a1a57db2a531d7e474d0d9bd16866321a2cef9f4cf2a332f292f615` |
| [src/functions-mcp-selfhosted/requirements.txt](../../../src/functions-mcp-selfhosted/requirements.txt) | 8 | 変更 | `725c1804ad7579c563af9f2d2f95a15615d5ec174f6589a7e2aa5707ecb37ef3` |
| [src/functions-mcp-selfhosted/scripts/deploy-functions-zip.ps1](../../../src/functions-mcp-selfhosted/scripts/deploy-functions-zip.ps1) | 137 | 変更 | `0250ad251cf15719c9e5b2c9d98d2368004ccd77d7a8be316d1ea5bb69b4efed` |
| [src/functions-mcp-selfhosted/scripts/deploy-functions-zip.sh](../../../src/functions-mcp-selfhosted/scripts/deploy-functions-zip.sh) | 86 | 変更 | `05e216d4762a6fd3a9a2084d7798e9477afd2a8490788bd4bb9ce825c25921d8` |
| [src/procurement_agent/azure_validation.py](../../../src/hosted-agent/procurement_agent/azure_validation.py) | 219 | HEAD一致 | `1c362f6af164e12c1aff3896e5f316147c5c0cffc09529443616531db5b67a87` |
| [src/procurement_agent/controller.py](../../../src/hosted-agent/procurement_agent/controller.py) | 1040 | 変更 | `90d115a7732e43d798d094d2c922ea3184cfef0251be210ea49e9f31fd287b3b` |
| [src/procurement_agent/hosted.py](../../../src/hosted-agent/procurement_agent/hosted.py) | 626 | 変更 | `de236b5bfef610d7b899afd721750d32e079c508920718441c009abcecb8fa1d` |
| [src/procurement_agent/hosted_app.py](../../../src/hosted-agent/procurement_agent/hosted_app.py) | 175 | 変更 | `d93a8924469f8894b29fb8291174cab205acd6c2473b3ff095754ba90945b182` |
| [src/procurement_agent/identity.py](../../../src/hosted-agent/procurement_agent/identity.py) | 153 | 新規 | `c080565fecf1da952d750cf9ca04e9f4e3d53611e44d6f2e4ce945ddcdbefac7` |
| [src/procurement_agent/mcp_contract.py](../../../src/hosted-agent/procurement_agent/mcp_contract.py) | 153 | HEAD一致 | `f9870d0c1c522ea71e8dbb024011ba0242661024d31309e8384c8a9c34173cea` |
| [src/procurement_agent/middleware.py](../../../src/hosted-agent/procurement_agent/middleware.py) | 50 | HEAD一致 | `71423130b282cf844c631f643bb99bc2834849030a50f0eebd30dfb885cd4c66` |
| [src/procurement_agent/models.py](../../../src/hosted-agent/procurement_agent/models.py) | 401 | 変更 | `51f4cc2344a8b33c74363e01e29fdf2bc78d37fc4c8fe29511bee16c6482535f` |
| [src/procurement_agent/observability.py](../../../src/hosted-agent/procurement_agent/observability.py) | 156 | 変更 | `325f222532eb8d221a3bf865e24f5a58996ae15e8f75f486267cda53bf5d9dd7` |
| [src/procurement_agent/plan.py](../../../src/hosted-agent/procurement_agent/plan.py) | 195 | HEAD一致 | `fc8b2227deb01e1f7c565cc4c62a95e7522ddfb9d3a83f6a8952adcb012647cb` |
| [src/procurement_agent/progress.py](../../../src/hosted-agent/procurement_agent/progress.py) | 93 | HEAD一致 | `7a228192166f09e836a093ed09d12fc861a4ab2580b712ce2d51b3e9850e1434` |
| [src/procurement_agent/session_state.py](../../../src/hosted-agent/procurement_agent/session_state.py) | 88 | 変更 | `758c06f9c178137948cffa80dde3f615502cc98f71ca006050d04deec35adcd3` |
| [src/trace_pipeline/__init__.py](../../../src/hosted-agent/trace_pipeline/__init__.py) | 6 | HEAD一致 | `39e3d650bd2900c6a8acfae99f34accbbb34d92a17f14b692401e5cc9d49ac50` |
| [src/trace_pipeline/detectors.py](../../../src/hosted-agent/trace_pipeline/detectors.py) | 137 | HEAD一致 | `6cb4ba196b914bb96377450250a6e76384c70855038e8756227457fe0a3b6747` |
| [src/trace_pipeline/envelope.py](../../../src/hosted-agent/trace_pipeline/envelope.py) | 67 | HEAD一致 | `c2483ae167526292881558d273f0a3d2f3dea5b2d4084a4ac11fba133fd1ba94` |
| [src/trace_pipeline/normalize.py](../../../src/hosted-agent/trace_pipeline/normalize.py) | 125 | HEAD一致 | `55f88f3d882665b691e007c4a6cc5a91d3ba30a9f548b4238b27ee0aa43645d4` |
| [src/trace_pipeline/stage_b.py](../../../src/hosted-agent/trace_pipeline/stage_b.py) | 375 | HEAD一致 | `a4c57a5a2d303d0a7f253e77073fab48f8e759cc0e37dfd8b166c8e34bd2f132` |
| [src/webapp-foundry-oauth/.env.example](../../../src/webapp-foundry-oauth/.env.example) | 14 | 新規 | `ad1bc0df9d0148b80e4fadab6d983b733bd4eb219a869bc04084575fd4f1944f` |
| [src/webapp-foundry-oauth/backend/procurement.py](../../../src/webapp-foundry-oauth/backend/procurement.py) | 409 | HEAD一致 | `e4bd7e39a23000445f97b543ee878b65a580be9e496136f0b1820c39f47c0343` |
| [src/webapp-foundry-oauth/backend/procurement_flow.py](../../../src/webapp-foundry-oauth/backend/procurement_flow.py) | 95 | 新規 | `1d802bbeebc5f2f553ea3aeb09fe8dd1f4f140bc10c9ace0522c4e93ec2bb3f6` |
| [src/webapp-foundry-oauth/backend/requirements.txt](../../../src/webapp-foundry-oauth/backend/requirements.txt) | 1 | 変更 | `69c65f7998ef21ec2b7edc38a7362e1d41478293410311c4617ab2b4d61d8bf4` |
| [src/webapp-foundry-oauth/backend/server.py](../../../src/webapp-foundry-oauth/backend/server.py) | 1418 | 変更 | `45adfab2c367fc12814b8e722cede252376f5642d139e6593ff1e0a06559b99d` |
| [src/webapp-foundry-oauth/backend/static/app.js](../../../src/webapp-foundry-oauth/backend/static/app.js) | 862 | HEAD一致 | `71704b506cf5482ea6c6a93286d4562e8598dd2c8511963d5899d6a6ce095491` |
| [src/webapp-foundry-oauth/backend/static/index.html](../../../src/webapp-foundry-oauth/backend/static/index.html) | 72 | HEAD一致 | `17081929fede020940fa07c45b74fa25923510df29e10cdd3800cba359405bcb` |
| [src/webapp-foundry-oauth/backend/static/procurement.html](../../../src/webapp-foundry-oauth/backend/static/procurement.html) | 55 | HEAD一致 | `cde6e29f34db809340556fa23694e2016702299b25850f8cae8562f90cd4048e` |
| [src/webapp-foundry-oauth/backend/static/procurement.js](../../../src/webapp-foundry-oauth/backend/static/procurement.js) | 118 | HEAD一致 | `5ef2b55192db870f405042dc245103b5d5905be01af311d89bdc7db948234b4e` |
| [src/webapp-foundry-oauth/backend/static/styles.css](../../../src/webapp-foundry-oauth/backend/static/styles.css) | 482 | HEAD一致 | `a87d33fb7b1c9cb7c99f4f08646a15da0db48d37e127387d889023ab9a5cdb5c` |
| [src/webapp-foundry-oauth/backend/telemetry.py](../../../src/webapp-foundry-oauth/backend/telemetry.py) | 116 | 新規 | `67987e23584893b3bcb342dff225d059d7fe675ab9d4d7f28ce1675d91ee0d97` |
| [src/webapp-foundry-oauth/requirements.txt](../../../src/webapp-foundry-oauth/requirements.txt) | 13 | 変更 | `1aaeb17e9b2151e2a119f68c79a377da718db541f09a0d9ae7b0cd7a025240dc` |
| [src/webapp-foundry-oauth/scripts/package-procurement.py](../../../src/webapp-foundry-oauth/scripts/package-procurement.py) | 28 | 変更 | `0050ff4dab0b77297cc26dc9c85844fff0b10b9234815085e259cc7d28f774f5` |
| [src/webapp-foundry-oauth/startup.sh](../../../src/webapp-foundry-oauth/startup.sh) | 22 | 変更 | `7ed9a120b713e2e461594990455007a6e02a6b0716807c626ce1941c203592d8` |
| [src/webapp-foundry-oauth/tests/test_stream_response.py](../../../src/webapp-foundry-oauth/tests/test_stream_response.py) | 468 | HEAD一致 | `4296723666f554f939f84ba7dc513d042ab96cc4bc9cb8a92ef6ec45d6d5ce6d` |
| [tests/integration/test_azure_validation_v2.py](../../../tests/integration/test_azure_validation_v2.py) | 144 | HEAD一致 | `b675affd46b4a101ee7bf0530a87b52c0a6bfa00b256c743b5b3f0562591cacf` |
| [tests/integration/test_conversation_intake.py](../../../tests/integration/test_conversation_intake.py) | 619 | 変更 | `43a4bf01ae3923bc0a903187f421593460c6e2a2fef8e1f2b071301a08269827` |
| [tests/trace/test_envelope_v3.py](../../../tests/trace/test_envelope_v3.py) | 154 | HEAD一致 | `9b06f4591a9a805aa4e6d779a79fe82be2cd6208732e11f63a959442516c2acc` |
| [tests/unit/test_hosted_factory_v2.py](../../../tests/unit/test_hosted_factory_v2.py) | 242 | HEAD一致 | `a381bd79c0dc67620fead426daebfff0594613251a0bcd20e409b4f623315b8e` |
| [tests/unit/test_hosted_package_v2.py](../../../tests/unit/test_hosted_package_v2.py) | 24 | HEAD一致 | `397fbfd30ec9e2ee85e71e3097ef00a0da40d9f018b4c8bd6fa71fdc2cdf6732` |
| [tests/unit/test_hosted_protocol_v2.py](../../../tests/unit/test_hosted_protocol_v2.py) | 153 | 変更 | `835589b252f11b01e764302ec8060d95eca98c6e50b0683eccd4adbde32d1356` |
| [tests/unit/test_identity_tool.py](../../../tests/unit/test_identity_tool.py) | 160 | 新規 | `de2133a562b513d635fc01b5cc60ff9d698c96a2e9f00757c353f525e67fe4c6` |
| [tests/unit/test_oauth_procurement.py](../../../tests/unit/test_oauth_procurement.py) | 215 | 新規 | `c89ddab3e4a536b77b4ef3f7f3389eb3b9b0bebf82b39b89070543c405ceb48a` |
| [tests/unit/test_obo_functions.py](../../../tests/unit/test_obo_functions.py) | 36 | 新規 | `1e91eee8788c8291f406a97ba9021751fe637996ad2cf8dd38c238475d665286` |
| [tests/unit/test_plan_v2.py](../../../tests/unit/test_plan_v2.py) | 93 | HEAD一致 | `10232f8de0687980f503e2482f8f3741a52f1a36c67141e91f587d118c9e015d` |
| [tests/unit/test_webui.py](../../../tests/unit/test_webui.py) | 305 | HEAD一致 | `2b6ed22e6cb3c46f44ec8877285b11f7b1ba325f847c2e2bcacfc40c7899c582` |

## 6. 再照合方法

`source-snapshot.json` の各pathをこのリポジトリrootから解決し、ファイルbytesのSHA-256を比較する。SDKファイルがない場合は依存未導入として区別する。hash一致はソース同一性の確認であり、認証・Azure送信・ユーザー操作の成功判定ではない。

実設定は[設定資料](../../deployment/configuration.md)、実Webの同意・Graph名前表示・Trace・null消去は[検証記録](../../report/validation-results-2026-09-08-obo.md)を参照する。
