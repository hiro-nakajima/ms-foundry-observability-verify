# 最新ソース索引・Span／logging箇所・SHA-256

更新日: **2026-09-08**。branch=`main`、基準HEAD=`e7fd85c4599909e9666ecfcd9e5d20c4e50faf59`。**未コミットの変更と新規ファイルを含む作業ツリー**が対象。HEADのソースと一致するという意味ではない。

[統合ガイド](README.md)／[Azure設定](../deployment/configuration.md)／[機械可読Snapshot](source-snapshot.json)。2026-09-07の行番号・hashを現行値へ置き換えた。SDK欄はローカル.venvの証拠であり、Azureの全installed packageを棚卸ししたものではない。

## 1. 稼働入口とファイルの役割

| 対象 | 稼働入口・主要モジュール | 設定／配布 |
| --- | --- | --- |
| Hosted | [main.py](/home/hnakajima/work/foundry-procurement-agent/main.py) → hosted_app.py、hosted.py、controller.py、identity.py、observability.py | root requirements/lock、deploy_foundry.py、package_hosted.py |
| App Service | [src/webapp-foundry-oauth/startup.sh](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/startup.sh) → server.py、procurement_flow.py、telemetry.py、旧OAuth UI | Web root requirements、package-procurement.py |
| Functions | [src/functions-mcp-selfhosted/mcp_handler/__init__.py](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_handler/__init__.py) → mcp_server.py、mcp_telemetry.py | Functions requirements、Bash/PowerShell ZIP script |
| APIM | [infra/apim-foundry-policy.xml](/home/hnakajima/work/foundry-procurement-agent/infra/apim-foundry-policy.xml) | infra/apim.bicep、deploy_identity.py web |

旧backend/procurement.pyとprocurement.* UIは比較用としてSnapshotに残すが、現Web配布の入口ではない。Functionsは現行OBO経路であり、未計装の参考コードとして扱わない。

## 2. 関数・クラス対応

ASTで抽出した定義開始行。リンクは定義先を指し、最終行は関数全体の範囲確認用。内側のcallbackは親関数／class名を含める。

### Hosted

| ソース | 関数／class | 最終行 |
| --- | --- | --- |
| [hosted_app.py:26](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted_app.py:26) | `_RequestCorrelationMiddleware` | 96 |
| [hosted_app.py:27](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted_app.py:27) | `_RequestCorrelationMiddleware.dispatch` | 96 |
| [hosted_app.py:99](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted_app.py:99) | `ProcurementResponsesHostServer` | 139 |
| [hosted_app.py:107](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted_app.py:107) | `ProcurementResponsesHostServer.__init__` | 109 |
| [hosted_app.py:111](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted_app.py:111) | `ProcurementResponsesHostServer._handle_response` | 139 |
| [hosted_app.py:142](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted_app.py:142) | `build_parser` | 147 |
| [hosted_app.py:150](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted_app.py:150) | `main` | 171 |
| [observability.py:26](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/observability.py:26) | `McpPrivacyProcessor` | 42 |
| [observability.py:34](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/observability.py:34) | `McpPrivacyProcessor._on_ending` | 42 |
| [observability.py:45](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/observability.py:45) | `configure_host_observability` | 51 |
| [observability.py:54](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/observability.py:54) | `current_request_attributes` | 59 |
| [observability.py:70](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/observability.py:70) | `sha256` | 71 |
| [observability.py:74](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/observability.py:74) | `safe_value` | 81 |
| [observability.py:84](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/observability.py:84) | `sanitize_attributes` | 91 |
| [observability.py:94](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/observability.py:94) | `TelemetryRecorder` | 145 |
| [observability.py:95](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/observability.py:95) | `TelemetryRecorder.__init__` | 113 |
| [observability.py:116](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/observability.py:116) | `TelemetryRecorder.for_hosted_runtime` | 118 |
| [observability.py:121](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/observability.py:121) | `TelemetryRecorder.record_raw_content` | 122 |
| [observability.py:125](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/observability.py:125) | `TelemetryRecorder.span` | 129 |
| [observability.py:132](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/observability.py:132) | `TelemetryRecorder.event` | 133 |
| [observability.py:135](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/observability.py:135) | `TelemetryRecorder.protect_content` | 140 |
| [observability.py:142](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/observability.py:142) | `TelemetryRecorder.finished_spans` | 145 |
| [observability.py:148](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/observability.py:148) | `truncate_export` | 156 |
| [identity.py:27](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/identity.py:27) | `IdentityResult` | 30 |
| [identity.py:36](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/identity.py:36) | `parse_whoami_result` | 49 |
| [identity.py:52](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/identity.py:52) | `verified_name` | 68 |
| [identity.py:71](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/identity.py:71) | `_consent` | 80 |
| [identity.py:83](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/identity.py:83) | `build_identity_tool` | 142 |
| [identity.py:84](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/identity.py:84) | `build_identity_tool.lookup` | 136 |
| [identity.py:145](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/identity.py:145) | `invoke_identity` | 153 |
| [hosted.py:83](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:83) | `FoundryRuntimeSettings` | 105 |
| [hosted.py:93](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:93) | `FoundryRuntimeSettings.from_env` | 105 |
| [hosted.py:109](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:109) | `HostedAgentBundle` | 118 |
| [hosted.py:121](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:121) | `ControllerContextProvider` | 197 |
| [hosted.py:129](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:129) | `ControllerContextProvider.__init__` | 137 |
| [hosted.py:140](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:140) | `ControllerContextProvider._latest_user_text` | 145 |
| [hosted.py:147](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:147) | `ControllerContextProvider.before_run` | 197 |
| [hosted.py:200](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:200) | `build_hosted_bundle` | 282 |
| [hosted.py:285](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:285) | `_response_model` | 290 |
| [hosted.py:293](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:293) | `_planner_format` | 297 |
| [hosted.py:300](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:300) | `_with_response_text` | 365 |
| [hosted.py:368](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:368) | `_intent` | 378 |
| [hosted.py:381](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:381) | `_is_explicit_purchase_request` | 385 |
| [hosted.py:388](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:388) | `_conversation_result` | 440 |
| [hosted.py:443](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:443) | `_invoke_remote_tool` | 464 |
| [hosted.py:448](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:448) | `_invoke_remote_tool.invoke` | 451 |
| [hosted.py:467](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:467) | `_execute_hosted_components` | 626 |
| [controller.py:27](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:27) | `StructuredChildOutputError` | 28 |
| [controller.py:31](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:31) | `ChildCorrelationMismatchError` | 34 |
| [controller.py:32](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:32) | `ChildCorrelationMismatchError.__init__` | 34 |
| [controller.py:37](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:37) | `ChildInvocationError` | 40 |
| [controller.py:38](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:38) | `ChildInvocationError.__init__` | 40 |
| [controller.py:43](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:43) | `classify_child_invocation_exception` | 76 |
| [controller.py:79](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:79) | `child_operation_succeeded` | 88 |
| [controller.py:91](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:91) | `specification_mismatch_keys` | 102 |
| [controller.py:105](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:105) | `catalog_result_is_grounded` | 108 |
| [controller.py:111](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:111) | `_catalog_candidate_is_grounded` | 127 |
| [controller.py:130](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:130) | `_exact_grounded_catalog_match` | 148 |
| [controller.py:151](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:151) | `catalog_candidate_matches_specifications` | 164 |
| [controller.py:167](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:167) | `reject_ungrounded_catalog` | 171 |
| [controller.py:174](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:174) | `set_machine_status` | 188 |
| [controller.py:191](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:191) | `operation_status_attributes` | 207 |
| [controller.py:210](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:210) | `correlation_attributes` | 221 |
| [controller.py:224](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:224) | `apply_operation_status` | 233 |
| [controller.py:236](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:236) | `refresh_governance_decisions` | 240 |
| [controller.py:243](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:243) | `correlation` | 255 |
| [controller.py:258](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:258) | `_missing_fields` | 268 |
| [controller.py:271](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:271) | `_confirmation_preview` | 308 |
| [controller.py:311](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:311) | `_saved_confirmation_context` | 344 |
| [controller.py:347](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:347) | `invoke_validated` | 372 |
| [controller.py:375](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:375) | `ProcurementController` | 1040 |
| [controller.py:376](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:376) | `ProcurementController.__init__` | 379 |
| [controller.py:381](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:381) | `ProcurementController._finish` | 420 |
| [controller.py:422](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:422) | `ProcurementController._boundary_failure_result` | 461 |
| [controller.py:463](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:463) | `ProcurementController.invalid_intake_result` | 500 |
| [controller.py:502](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:502) | `ProcurementController._run_catalog_step` | 578 |
| [controller.py:580](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:580) | `ProcurementController._run_code_step` | 638 |
| [controller.py:640](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:640) | `ProcurementController._merge_validated` | 720 |
| [controller.py:722](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:722) | `ProcurementController.execute` | 1040 |
| [controller.py:785](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:785) | `ProcurementController.execute.finish` | 797 |
| [plan.py:17](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/plan.py:17) | `PlanStateError` | 18 |
| [plan.py:21](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/plan.py:21) | `DuplicateStepSuppressed` | 22 |
| [plan.py:32](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/plan.py:32) | `stable_input_hash` | 34 |
| [plan.py:37](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/plan.py:37) | `completed_step_key` | 38 |
| [plan.py:41](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/plan.py:41) | `default_steps` | 42 |
| [plan.py:45](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/plan.py:45) | `StructuredPlanBuilder` | 81 |
| [plan.py:48](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/plan.py:48) | `StructuredPlanBuilder.build` | 81 |
| [plan.py:84](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/plan.py:84) | `PlanExecutor` | 195 |
| [plan.py:85](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/plan.py:85) | `PlanExecutor.__init__` | 89 |
| [plan.py:91](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/plan.py:91) | `PlanExecutor.step` | 95 |
| [plan.py:97](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/plan.py:97) | `PlanExecutor.next_step` | 100 |
| [plan.py:102](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/plan.py:102) | `PlanExecutor.start` | 125 |
| [plan.py:127](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/plan.py:127) | `PlanExecutor.complete` | 143 |
| [plan.py:145](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/plan.py:145) | `PlanExecutor.reuse` | 164 |
| [plan.py:166](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/plan.py:166) | `PlanExecutor.retry` | 177 |
| [plan.py:179](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/plan.py:179) | `PlanExecutor.wait_for_user` | 186 |
| [plan.py:188](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/plan.py:188) | `PlanExecutor.block` | 195 |
| [session_state.py:16](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/session_state.py:16) | `SessionStateError` | 17 |
| [session_state.py:20](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/session_state.py:20) | `SessionRequiredError` | 21 |
| [session_state.py:24](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/session_state.py:24) | `SessionStateMissingError` | 25 |
| [session_state.py:28](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/session_state.py:28) | `SessionStateSchemaError` | 29 |
| [session_state.py:32](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/session_state.py:32) | `ProcurementExecutionState` | 52 |
| [session_state.py:55](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/session_state.py:55) | `save_execution_state` | 56 |
| [session_state.py:59](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/session_state.py:59) | `initialize_execution_state` | 62 |
| [session_state.py:65](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/session_state.py:65) | `load_execution_state` | 76 |
| [session_state.py:79](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/session_state.py:79) | `load_context_state` | 82 |
| [session_state.py:85](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/session_state.py:85) | `restore_framework_session` | 88 |
| [azure_validation.py:42](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/azure_validation.py:42) | `validation_request` | 67 |
| [azure_validation.py:70](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/azure_validation.py:70) | `run_azure_validation` | 219 |

### App Service

| ソース | 関数／class | 最終行 |
| --- | --- | --- |
| [server.py:73](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:73) | `_extract_text_from_response` | 96 |
| [server.py:99](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:99) | `_sse` | 100 |
| [server.py:103](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:103) | `_parse_sse_payload` | 114 |
| [server.py:117](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:117) | `_tool_event_from_item` | 144 |
| [server.py:147](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:147) | `_event_status` | 157 |
| [server.py:160](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:160) | `_public_job` | 174 |
| [server.py:177](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:177) | `_public_conversation_state` | 194 |
| [server.py:213](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:213) | `_reset_conversation_state` | 222 |
| [server.py:228](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:228) | `ChatRequest` | 232 |
| [server.py:235](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:235) | `ContinueRequest` | 240 |
| [server.py:263](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:263) | `authenticated_api` | 274 |
| [server.py:285](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:285) | `_safe_b64decode_json` | 295 |
| [server.py:299](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:299) | `_decode_jwt_payload` | 312 |
| [server.py:315](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:315) | `_sanitize_token_claims` | 326 |
| [server.py:329](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:329) | `_extract_claim` | 342 |
| [server.py:345](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:345) | `_hash_user_key` | 346 |
| [server.py:349](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:349) | `_get_request_user` | 389 |
| [server.py:392](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:392) | `_conversation_state_key` | 393 |
| [server.py:397](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:397) | `_fetch_easyauth_me` | 418 |
| [server.py:421](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:421) | `_refresh_easyauth_tokens` | 434 |
| [server.py:437](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:437) | `_get_easyauth_refresh_token` | 465 |
| [server.py:468](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:468) | `_get_easyauth_access_token` | 491 |
| [server.py:494](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:494) | `_get_foundry_obo_config` | 518 |
| [server.py:522](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:522) | `_acquire_foundry_token_by_refresh_token` | 548 |
| [server.py:551](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:551) | `_acquire_foundry_token_on_behalf_of` | 577 |
| [server.py:580](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:580) | `_get_token` | 587 |
| [server.py:590](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:590) | `_build_outbound_headers` | 635 |
| [server.py:638](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:638) | `_validate_delegated_subject` | 646 |
| [server.py:649](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:649) | `_get_foundry_config` | 666 |
| [server.py:670](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:670) | `serve_index` | 672 |
| [server.py:678](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:678) | `_stream_response` | 1193 |
| [server.py:1200](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1200) | `health` | 1205 |
| [server.py:1209](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1209) | `me` | 1215 |
| [server.py:1219](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1219) | `get_conversation_state` | 1225 |
| [server.py:1229](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1229) | `delete_conversation_state` | 1235 |
| [server.py:1238](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1238) | `_cleanup_old_jobs` | 1247 |
| [server.py:1250](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1250) | `_append_job_event` | 1266 |
| [server.py:1269](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1269) | `_create_response_job` | 1309 |
| [server.py:1313](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1313) | `chat` | 1321 |
| [server.py:1325](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1325) | `continue_after_consent` | 1341 |
| [server.py:1345](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1345) | `get_job` | 1351 |
| [server.py:1355](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1355) | `cancel_job` | 1378 |
| [server.py:1382](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1382) | `stream_job_events` | 1418 |
| [server.py:1383](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1383) | `stream_job_events.event_stream` | 1408 |
| [procurement_flow.py:9](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement_flow.py:9) | `public_event` | 15 |
| [procurement_flow.py:18](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement_flow.py:18) | `_create_conversation` | 26 |
| [procurement_flow.py:29](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement_flow.py:29) | `run` | 95 |
| [telemetry.py:22](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/telemetry.py:22) | `tracer` | 23 |
| [telemetry.py:27](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/telemetry.py:27) | `observe` | 37 |
| [telemetry.py:40](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/telemetry.py:40) | `_request_hook` | 42 |
| [telemetry.py:45](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/telemetry.py:45) | `http_client` | 51 |
| [telemetry.py:55](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/telemetry.py:55) | `lifespan` | 72 |
| [telemetry.py:75](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/telemetry.py:75) | `Instrumentation` | 87 |
| [telemetry.py:76](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/telemetry.py:76) | `Instrumentation.__init__` | 77 |
| [telemetry.py:79](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/telemetry.py:79) | `Instrumentation.__call__` | 87 |
| [telemetry.py:90](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/telemetry.py:90) | `BrowserBoundary` | 104 |
| [telemetry.py:92](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/telemetry.py:92) | `BrowserBoundary.__init__` | 93 |
| [telemetry.py:95](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/telemetry.py:95) | `BrowserBoundary.__call__` | 104 |
| [telemetry.py:108](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/telemetry.py:108) | `job_context` | 116 |

### Functions

| ソース | 関数／class | 最終行 |
| --- | --- | --- |
| [mcp_server.py:42](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:42) | `_get_env_int` | 50 |
| [mcp_server.py:53](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:53) | `_get_env_float` | 61 |
| [mcp_server.py:64](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:64) | `_backoff_delay` | 67 |
| [mcp_server.py:70](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:70) | `_normalize_bearer` | 72 |
| [mcp_server.py:75](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:75) | `_get_authorization_from_headers` | 80 |
| [mcp_server.py:83](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:83) | `extract_bearer_token_from_context` | 112 |
| [mcp_server.py:115](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:115) | `get_token_info` | 119 |
| [mcp_server.py:122](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:122) | `_sanitize_claims_for_log` | 132 |
| [mcp_server.py:135](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:135) | `log_inbound_token_summary` | 141 |
| [mcp_server.py:144](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:144) | `decode_jwt_payload` | 156 |
| [mcp_server.py:159](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:159) | `_split_csv_env` | 161 |
| [mcp_server.py:164](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:164) | `validate_incoming_token` | 208 |
| [mcp_server.py:211](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:211) | `_get_required_env` | 215 |
| [mcp_server.py:218](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:218) | `_get_graph_scopes` | 221 |
| [mcp_server.py:224](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:224) | `_get_confidential_client` | 236 |
| [mcp_server.py:239](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:239) | `acquire_graph_token_via_obo` | 296 |
| [mcp_server.py:299](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:299) | `call_graph_api` | 356 |
| [mcp_server.py:359](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:359) | `build_whoami_response` | 461 |
| [mcp_server.py:464](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:464) | `create_mcp_server` | 500 |
| [mcp_server.py:472](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:472) | `create_mcp_server.whoami` | 494 |
| [mcp_server.py:497](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:497) | `create_mcp_server.greet` | 498 |
| [mcp_server.py:503](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:503) | `app` | 507 |
| [mcp_telemetry.py:21](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_telemetry.py:21) | `step` | 30 |
| [mcp_telemetry.py:33](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_telemetry.py:33) | `carrier_from_mcp` | 39 |
| [mcp_telemetry.py:42](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_telemetry.py:42) | `record_outcome` | 50 |

### 設定・配布

| ソース | 関数／class | 最終行 |
| --- | --- | --- |
| [deploy_identity.py:31](/home/hnakajima/work/foundry-procurement-agent/scripts/deploy_identity.py:31) | `api` | 38 |
| [deploy_identity.py:41](/home/hnakajima/work/foundry-procurement-agent/scripts/deploy_identity.py:41) | `arm` | 43 |
| [deploy_identity.py:46](/home/hnakajima/work/foundry-procurement-agent/scripts/deploy_identity.py:46) | `application` | 47 |
| [deploy_identity.py:50](/home/hnakajima/work/foundry-procurement-agent/scripts/deploy_identity.py:50) | `configure_functions` | 93 |
| [deploy_identity.py:96](/home/hnakajima/work/foundry-procurement-agent/scripts/deploy_identity.py:96) | `configure_web` | 131 |
| [deploy_foundry.py:46](/home/hnakajima/work/foundry-procurement-agent/scripts/deploy_foundry.py:46) | `connection` | 61 |
| [deploy_foundry.py:64](/home/hnakajima/work/foundry-procurement-agent/scripts/deploy_foundry.py:64) | `connections` | 77 |
| [deploy_foundry.py:80](/home/hnakajima/work/foundry-procurement-agent/scripts/deploy_foundry.py:80) | `children` | 132 |
| [deploy_foundry.py:135](/home/hnakajima/work/foundry-procurement-agent/scripts/deploy_foundry.py:135) | `hosted` | 174 |
| [package_hosted.py:14](/home/hnakajima/work/foundry-procurement-agent/scripts/package_hosted.py:14) | `package` | 32 |
| [package-procurement.py:7](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/scripts/package-procurement.py:7) | `main` | 24 |

## 3. Span・event・属性・通常loggerの直接呼び出し

現在のアプリソースから抽出した記録位置。SDK内の自動Agent/Chat/Function/MCP/HTTP Spanはこの一覧に含めない。logger呼び出しは通常loggingであり、OTel LogExporterを構成した証拠ではない。表示するのはソースのテンプレート／属性名であり実行値ではない。

### Hosted

| ソース | 所属関数 | 記録API | 名称／属性／テンプレート |
| --- | --- | --- | --- |
| [observability.py:128](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/observability.py:128) | `TelemetryRecorder.span` | `self.tracer.start_as_current_span` | name |
| [observability.py:133](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/observability.py:133) | `TelemetryRecorder.event` | `span.add_event` | name |
| [identity.py:86](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/identity.py:86) | `build_identity_tool.lookup` | `trace.get_tracer('procurement.identity').start_as_current_span` | identity.lookup |
| [identity.py:100](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/identity.py:100) | `build_identity_tool.lookup` | `span.set_attribute` | app.identity.tool.count |
| [identity.py:101](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/identity.py:101) | `build_identity_tool.lookup` | `span.set_attribute` | app.identity.tool.names |
| [identity.py:109](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/identity.py:109) | `build_identity_tool.lookup` | `span.set_attribute` | app.identity.tool.available |
| [identity.py:123](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/identity.py:123) | `build_identity_tool.lookup` | `span.set_attribute` | error.type |
| [identity.py:124](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/identity.py:124) | `build_identity_tool.lookup` | `span.set_attribute` | app.identity.error.type |
| [identity.py:125](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/identity.py:125) | `build_identity_tool.lookup` | `span.set_attribute` | app.identity.error.stage |
| [identity.py:131](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/identity.py:131) | `build_identity_tool.lookup` | `span.set_attribute` | app.identity.error.rpc_code |
| [identity.py:133](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/identity.py:133) | `build_identity_tool.lookup` | `span.set_status` | trace.StatusCode.ERROR |
| [identity.py:134](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/identity.py:134) | `build_identity_tool.lookup` | `span.set_attribute` | app.identity.lookup.status |
| [hosted.py:157](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:157) | `ControllerContextProvider.before_run` | `trace.get_current_span().set_attributes` | attributes |
| [hosted.py:430](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:430) | `_conversation_result` | `telemetry.span` | response.generate |
| [hosted.py:431](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:431) | `_conversation_result` | `telemetry.event` | span |
| [hosted.py:610](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:610) | `_execute_hosted_components` | `span.set_attribute` | error.type |
| [hosted.py:614](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:614) | `_execute_hosted_components` | `span.set_attribute` | error.http_status |
| [controller.py:233](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:233) | `apply_operation_status` | `span.set_attribute` | key |
| [controller.py:403](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:403) | `ProcurementController._finish` | `self.telemetry.span` | response.generate |
| [controller.py:404](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:404) | `ProcurementController._finish` | `self.telemetry.event` | span |
| [controller.py:521](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:521) | `ProcurementController._run_catalog_step` | `self.telemetry.span` | plan.step.execute |
| [controller.py:528](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:528) | `ProcurementController._run_catalog_step` | `self.telemetry.event` | catalog_span |
| [controller.py:531](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:531) | `ProcurementController._run_catalog_step` | `self.telemetry.event` | catalog_span |
| [controller.py:539](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:539) | `ProcurementController._run_catalog_step` | `self.telemetry.event` | catalog_span |
| [controller.py:559](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:559) | `ProcurementController._run_catalog_step` | `self.telemetry.event` | catalog_span |
| [controller.py:563](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:563) | `ProcurementController._run_catalog_step` | `self.telemetry.event` | catalog_span |
| [controller.py:568](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:568) | `ProcurementController._run_catalog_step` | `self.telemetry.event` | catalog_span |
| [controller.py:570](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:570) | `ProcurementController._run_catalog_step` | `self.telemetry.event` | catalog_span |
| [controller.py:573](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:573) | `ProcurementController._run_catalog_step` | `self.telemetry.event` | catalog_span |
| [controller.py:601](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:601) | `ProcurementController._run_code_step` | `self.telemetry.span` | plan.step.execute |
| [controller.py:608](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:608) | `ProcurementController._run_code_step` | `self.telemetry.event` | code_span |
| [controller.py:611](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:611) | `ProcurementController._run_code_step` | `self.telemetry.event` | code_span |
| [controller.py:619](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:619) | `ProcurementController._run_code_step` | `self.telemetry.event` | code_span |
| [controller.py:631](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:631) | `ProcurementController._run_code_step` | `self.telemetry.event` | code_span |
| [controller.py:634](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:634) | `ProcurementController._run_code_step` | `self.telemetry.event` | code_span |
| [controller.py:653](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:653) | `ProcurementController._merge_validated` | `self.telemetry.span` | merge.validate |
| [controller.py:659](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:659) | `ProcurementController._merge_validated` | `self.telemetry.event` | merge_span |
| [controller.py:685](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:685) | `ProcurementController._merge_validated` | `self.telemetry.event` | merge_span |
| [controller.py:700](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:700) | `ProcurementController._merge_validated` | `self.telemetry.event` | merge_span |
| [controller.py:778](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:778) | `ProcurementController.execute` | `self.telemetry.span` | plan.create |
| [controller.py:781](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py:781) | `ProcurementController.execute` | `self.telemetry.event` | span |
| [azure_validation.py:187](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/azure_validation.py:187) | `run_azure_validation` | `telemetry.span` | semantic.evaluate |
| [azure_validation.py:188](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/azure_validation.py:188) | `run_azure_validation` | `telemetry.event` | evaluation_span |
| [azure_validation.py:196](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/azure_validation.py:196) | `run_azure_validation` | `telemetry.event` | evaluation_span |
| [azure_validation.py:201](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/azure_validation.py:201) | `run_azure_validation` | `telemetry.event` | evaluation_span |

### App Service

| ソース | 所属関数 | 記録API | 名称／属性／テンプレート |
| --- | --- | --- | --- |
| [server.py:217](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:217) | `_reset_conversation_state` | `logger.warning` | Conversation state reset: conversation=%s owner=%s reason=%s |
| [server.py:382](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:382) | `_get_request_user` | `trace.get_current_span().set_attribute` | user.id |
| [server.py:409](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:409) | `_fetch_easyauth_me` | `logger.warning` | /.auth/me returned HTTP %s |
| [server.py:417](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:417) | `_fetch_easyauth_me` | `logger.warning` | Failed to fetch /.auth/me: %s |
| [server.py:432](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:432) | `_refresh_easyauth_tokens` | `logger.info` | /.auth/refresh returned HTTP %s |
| [server.py:434](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:434) | `_refresh_easyauth_tokens` | `logger.warning` | Failed to call /.auth/refresh: %s |
| [server.py:446](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:446) | `_get_easyauth_refresh_token` | `logger.info` | Using EasyAuth refresh token from /.auth/me entry provider=%s |
| [server.py:454](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:454) | `_get_easyauth_refresh_token` | `logger.info` | Using EasyAuth refresh token from /.auth/me after refresh provider=%s |
| [server.py:458](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:458) | `_get_easyauth_refresh_token` | `logger.warning` | EasyAuth refresh token not found. /.auth/me keys=%s |
| [server.py:484](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:484) | `_get_easyauth_access_token` | `logger.error` | EasyAuth principal does not match access token claims: principal=%s token_claims=%s |
| [server.py:490](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:490) | `_get_easyauth_access_token` | `logger.info` | EasyAuth access token claims: %s |
| [server.py:533](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:533) | `_acquire_foundry_token_by_refresh_token` | `logger.info` | Acquired Foundry user delegated token via EasyAuth refresh token: scopes=%s claims=%s |
| [server.py:539](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:539) | `_acquire_foundry_token_by_refresh_token` | `logger.error` | Failed to acquire Foundry token by refresh token: error=%s suberror=%s correlation_id=%s |
| [server.py:562](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:562) | `_acquire_foundry_token_on_behalf_of` | `logger.info` | Acquired Foundry user delegated token via OBO: scopes=%s claims=%s |
| [server.py:568](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:568) | `_acquire_foundry_token_on_behalf_of` | `logger.error` | Failed to acquire Foundry token via OBO: error=%s suberror=%s correlation_id=%s |
| [server.py:623](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:623) | `_build_outbound_headers` | `logger.info` | Forwarding EasyAuth access token to Foundry/APIM: claims=%s |
| [server.py:743](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:743) | `_stream_response` | `logger.info` | Calling Foundry Agent endpoint Responses API url=%s previous_response_id=%s agent=%s |
| [server.py:805](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:805) | `_stream_response` | `logger.debug` | Non-JSON SSE data skipped |
| [server.py:847](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:847) | `_stream_response` | `logger.info` | Tool call started: %s (call_id=%s) |
| [server.py:868](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:868) | `_stream_response` | `logger.info` | OAuth consent detected (output item); draining Foundry stream before UI notification: connection=%s response_id=%s |
| [server.py:890](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:890) | `_stream_response` | `logger.info` | MCP approval detected; draining Foundry stream before UI notification: server=%s tool=%s approval_id=%s response_id=%s |
| [server.py:915](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:915) | `_stream_response` | `logger.info` | MCP approval detected (direct event); draining Foundry stream before UI notification: server=%s tool=%s approval_id=%s response_id=%s |
| [server.py:935](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:935) | `_stream_response` | `logger.info` | Tool call done: %s (call_id=%s) |
| [server.py:993](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:993) | `_stream_response` | `logger.info` | OAuth consent detected; draining Foundry stream before UI notification: connection=%s response_id=%s |
| [server.py:1010](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1010) | `_stream_response` | `logger.info` | OAuth consent detected (embedded); draining Foundry stream before UI notification: connection=%s response_id=%s |
| [server.py:1035](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1035) | `_stream_response` | `logger.info` | Foundry response completed upstream; draining remaining SSE framing: %s |
| [server.py:1043](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1043) | `_stream_response` | `logger.error` | msg |
| [server.py:1051](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1051) | `_stream_response` | `logger.error` | Foundry stream ended before response.completed; response_id=%s deferred_action=%s |
| [server.py:1123](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1123) | `_stream_response` | `logger.info` | MCP approval ready after completed response: response_id=%s approval_ids=%s consent_pending=%s |
| [server.py:1140](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1140) | `_stream_response` | `logger.info` | OAuth consent ready after completed response: response_id=%s connection=%s |
| [server.py:1151](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1151) | `_stream_response` | `logger.info` | Response completed: %s |
| [server.py:1156](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1156) | `_stream_response` | `logger.error` | msg |
| [server.py:1164](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1164) | `_stream_response` | `logger.warning` | Foundry rejected previous_response_id; retrying once without conversation state: conversation=%s rejected_previous_response_id=%s |
| [server.py:1192](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:1192) | `_stream_response` | `logger.error` | msg |
| [procurement_flow.py:34](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement_flow.py:34) | `run` | `telemetry.job_context` | user['storage_key'] |
| [procurement_flow.py:34](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement_flow.py:34) | `run` | `telemetry.observe` | web.chat.job |
| [procurement_flow.py:47](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement_flow.py:47) | `run` | `telemetry.observe` | auth.foundry.token |
| [procurement_flow.py:50](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement_flow.py:50) | `run` | `telemetry.observe` | procurement.agent.invoke |
| [procurement_flow.py:53](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement_flow.py:53) | `run` | `invocation.set_attribute` | gen_ai.conversation.id |
| [procurement_flow.py:69](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement_flow.py:69) | `run` | `invocation.set_attribute` | gen_ai.response.id |
| [procurement_flow.py:76](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement_flow.py:76) | `run` | `invocation.set_status` | StatusCode.ERROR |
| [procurement_flow.py:82](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement_flow.py:82) | `run` | `invocation.set_status` | StatusCode.ERROR |
| [procurement_flow.py:87](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement_flow.py:87) | `run` | `span.set_attribute` | app.cancelled |
| [procurement_flow.py:91](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement_flow.py:91) | `run` | `span.set_attribute` | error.type |
| [procurement_flow.py:92](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement_flow.py:92) | `run` | `span.set_status` | StatusCode.ERROR |
| [telemetry.py:28](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/telemetry.py:28) | `observe` | `tracer().start_as_current_span` | name |
| [telemetry.py:35](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/telemetry.py:35) | `observe` | `span.set_attribute` | error.type |
| [telemetry.py:36](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/telemetry.py:36) | `observe` | `span.set_status` | StatusCode.ERROR |
| [telemetry.py:42](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/telemetry.py:42) | `_request_hook` | `span.set_attributes` | job_attributes.get() |

### Functions

| ソース | 所属関数 | 記録API | 名称／属性／テンプレート |
| --- | --- | --- | --- |
| [mcp_server.py:19](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:19) | `(module)` | `logger.setLevel` | logging.INFO |
| [mcp_server.py:27](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:27) | `(module)` | `logger.info` | Graph scope configuration loaded: GRAPH_SCOPES set=%s default_scopes=%s |
| [mcp_server.py:49](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:49) | `_get_env_int` | `logger.warning` | Invalid integer for %s: %s. Using default %s. |
| [mcp_server.py:60](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:60) | `_get_env_float` | `logger.warning` | Invalid float for %s: %s. Using default %s. |
| [mcp_server.py:110](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:110) | `extract_bearer_token_from_context` | `logger.warning` | Failed to extract Authorization header from context: %s |
| [mcp_server.py:137](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:137) | `log_inbound_token_summary` | `logger.info` | Inbound token summary: received=%s claims=%s |
| [mcp_server.py:220](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:220) | `_get_graph_scopes` | `logger.info` | Graph OBO scopes resolved: %s |
| [mcp_server.py:260](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:260) | `acquire_graph_token_via_obo` | `logger.info` | OBO token exchange succeeded after retry %s/%s. |
| [mcp_server.py:271](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:271) | `acquire_graph_token_via_obo` | `logger.warning` | OBO token exchange attempt %s/%s failed: %s |
| [mcp_server.py:285](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:285) | `acquire_graph_token_via_obo` | `logger.error` | OBO token exchange failed after retries |
| [mcp_server.py:314](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:314) | `call_graph_api` | `logger.warning` | Graph API call attempt %s/%s returned retryable status %s. |
| [mcp_server.py:327](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:327) | `call_graph_api` | `logger.info` | Graph API call succeeded after retry %s/%s. |
| [mcp_server.py:332](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:332) | `call_graph_api` | `logger.warning` | Graph API call attempt %s/%s failed: %s |
| [mcp_server.py:339](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:339) | `call_graph_api` | `logger.error` | Graph API call failed after retries: %s |
| [mcp_server.py:364](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:364) | `build_whoami_response` | `logger.warning` | Inbound token validation failed |
| [mcp_server.py:376](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:376) | `build_whoami_response` | `span.set_attribute` | app.obo.success |
| [mcp_server.py:378](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:378) | `build_whoami_response` | `logger.error` | OBO configuration error: %s |
| [mcp_server.py:386](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:386) | `build_whoami_response` | `logger.error` | OBO exchange failed for inbound claims=%s correlation_id=%s trace_id=%s |
| [mcp_server.py:401](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:401) | `build_whoami_response` | `span.set_attribute` | app.graph.success |
| [mcp_server.py:409](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:409) | `build_whoami_response` | `logger.error` | Security check failed: inbound token oid does not match Graph /me id. inbound_claims=%s graph_user_id_present=%s |
| [mcp_server.py:420](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:420) | `build_whoami_response` | `logger.warning` | Security check skipped because user identifiers are incomplete: inbound_claims=%s graph_user_id_present=%s |
| [mcp_server.py:425](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:425) | `build_whoami_response` | `logger.info` | whoami succeeded: inbound_claims=%s obo_attempts=%s graph_attempts=%s |
| [mcp_server.py:451](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:451) | `build_whoami_response` | `logger.error` | Failed to call Graph API: error=%s status_code=%s inbound_claims=%s |
| [mcp_server.py:485](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:485) | `create_mcp_server.whoami` | `logger.info` | whoami MCP tool called (python runtime, OBO) |
| [mcp_telemetry.py:23](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_telemetry.py:23) | `step` | `tracer.start_as_current_span` | name |
| [mcp_telemetry.py:28](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_telemetry.py:28) | `step` | `span.set_attribute` | error.type |
| [mcp_telemetry.py:29](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_telemetry.py:29) | `step` | `span.set_status` | trace.StatusCode.ERROR |
| [mcp_telemetry.py:44](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_telemetry.py:44) | `record_outcome` | `span.set_attribute` | app.identity.lookup.status |
| [mcp_telemetry.py:48](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_telemetry.py:48) | `record_outcome` | `span.set_attribute` | user.id |
| [mcp_telemetry.py:50](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_telemetry.py:50) | `record_outcome` | `span.set_status` | trace.StatusCode.ERROR |

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
| [.foundry/agent-metadata.yaml](/home/hnakajima/work/foundry-procurement-agent/.foundry/agent-metadata.yaml) | 280 | 変更 | `a46853ef81cec897c54a2ca4a07f4a8c45ae54449823af16163a8bcafe9ecb4b` |
| [.venv/lib/python3.13/site-packages/agent_framework/_agents.py](/home/hnakajima/work/foundry-procurement-agent/.venv/lib/python3.13/site-packages/agent_framework/_agents.py) | 1948 | SDK | `362f9cc98fda41cefc7a900fa7e5900b61f21783f69349a482f8ef26f6a69bec` |
| [.venv/lib/python3.13/site-packages/agent_framework/observability.py](/home/hnakajima/work/foundry-procurement-agent/.venv/lib/python3.13/site-packages/agent_framework/observability.py) | 3703 | SDK | `13123cfcdb300285514d8eaef8a1878f29a37e607192801c71d1582cc16d47ab` |
| [.venv/lib/python3.13/site-packages/agent_framework_foundry_hosting-1.0.0b260827.dist-info/METADATA](/home/hnakajima/work/foundry-procurement-agent/.venv/lib/python3.13/site-packages/agent_framework_foundry_hosting-1.0.0b260827.dist-info/METADATA) | 79 | SDK | `3da86c799e3fe41e8ca44a5ede38f439f99c45c9283ef5ddf97170644020f50e` |
| [.venv/lib/python3.13/site-packages/agent_framework_foundry_hosting/_responses.py](/home/hnakajima/work/foundry-procurement-agent/.venv/lib/python3.13/site-packages/agent_framework_foundry_hosting/_responses.py) | 2076 | SDK | `e944316a94eafd7c31fe90c60667d8d01b24615e2825b04dbe7f4f5e9b0b43f7` |
| [.venv/lib/python3.13/site-packages/azure/ai/agentserver/core/_base.py](/home/hnakajima/work/foundry-procurement-agent/.venv/lib/python3.13/site-packages/azure/ai/agentserver/core/_base.py) | 665 | SDK | `8a1686fc867385a93ababdafa8b111e1bb7945e529f8cfd83b4de399807e31b5` |
| [.venv/lib/python3.13/site-packages/azure/ai/agentserver/core/_tracing.py](/home/hnakajima/work/foundry-procurement-agent/.venv/lib/python3.13/site-packages/azure/ai/agentserver/core/_tracing.py) | 829 | SDK | `7f7ca3c2832b83acaec8619438c7bd0bc43adb536264a269cbb2f339133f0202` |
| [.venv/lib/python3.13/site-packages/azure/monitor/opentelemetry/exporter/export/trace/_exporter.py](/home/hnakajima/work/foundry-procurement-agent/.venv/lib/python3.13/site-packages/azure/monitor/opentelemetry/exporter/export/trace/_exporter.py) | 621 | SDK | `f1d868fa3f2af25c0191504d261aae80bdbfe04cf76702299946ed9ed8daa23f` |
| [.venv/lib/python3.13/site-packages/azure_ai_agentserver_core-2.1.0.dist-info/METADATA](/home/hnakajima/work/foundry-procurement-agent/.venv/lib/python3.13/site-packages/azure_ai_agentserver_core-2.1.0.dist-info/METADATA) | 294 | SDK | `bf38e7ac779851286d48e76dcd76384af0a0e0ed0c6f01530819ea742417b7e3` |
| [.venv/lib/python3.13/site-packages/mcp/server/fastmcp/server.py](/home/hnakajima/work/foundry-procurement-agent/.venv/lib/python3.13/site-packages/mcp/server/fastmcp/server.py) | 1366 | SDK | `f4360eec1cca411afa55762a223d103236e856cc8b52944ef64ff337c8e970c2` |
| [.venv/lib/python3.13/site-packages/mcp/shared/context.py](/home/hnakajima/work/foundry-procurement-agent/.venv/lib/python3.13/site-packages/mcp/shared/context.py) | 32 | SDK | `40c447c1708826cbdfe14def720a9201769a50430a85f8fff5794223e9149271` |
| [.venv/lib/python3.13/site-packages/mcp/types.py](/home/hnakajima/work/foundry-procurement-agent/.venv/lib/python3.13/site-packages/mcp/types.py) | 1999 | SDK | `6824109cd1eabaf43c5dab829a83015b1b88ec9ae149765e6814afaf23f9bde5` |
| [.venv/lib/python3.13/site-packages/microsoft_opentelemetry-1.3.8.dist-info/METADATA](/home/hnakajima/work/foundry-procurement-agent/.venv/lib/python3.13/site-packages/microsoft_opentelemetry-1.3.8.dist-info/METADATA) | 432 | SDK | `77fe095d226c77285d6f6ceb7c68b8cfd809646a0486603cfb589b7bfe137fb1` |
| [.venv/lib/python3.13/site-packages/opentelemetry/sdk/trace/__init__.py](/home/hnakajima/work/foundry-procurement-agent/.venv/lib/python3.13/site-packages/opentelemetry/sdk/trace/__init__.py) | 1476 | SDK | `09386c185c308437ad63d2fc015c80601b3ee648ee6cf93e65d11b823bf529e2` |
| [README.md](/home/hnakajima/work/foundry-procurement-agent/README.md) | 62 | 変更 | `a6890a178a4b8374d1d6d4ed65b3b8c1e487caeb1b9e2ce8af14eb51d18cdcc1` |
| [azure.yaml](/home/hnakajima/work/foundry-procurement-agent/azure.yaml) | 72 | HEAD一致 | `8f37e30e1768676396996e182f16c58422933203be57547999637f8ff9386e85` |
| [docs/azure-observability-validation-2026-09-03.md](/home/hnakajima/work/foundry-procurement-agent/docs/azure-observability-validation-2026-09-03.md) | 219 | HEAD一致 | `c4153dabcf54ea357cf3664b5f0efd3424660bd52242c0a07ec83ae41ec770ed` |
| [docs/report/validation-results-2026-09-06.md](/home/hnakajima/work/foundry-procurement-agent/docs/report/validation-results-2026-09-06.md) | 160 | HEAD一致 | `77d8cc792420c0e34b2a7ef9e3cee6de3dfe273b1f64564c66147e05364bd33c` |
| [docs/report/validation-results-2026-09-08-obo.md](/home/hnakajima/work/foundry-procurement-agent/docs/report/validation-results-2026-09-08-obo.md) | 55 | 新規 | `1b01681a7dfd565a896ba4dc598550fe2ccdf843c9ede86bb29c519f9a48b10e` |
| [infra/apim-foundry-policy.xml](/home/hnakajima/work/foundry-procurement-agent/infra/apim-foundry-policy.xml) | 16 | 新規 | `e42a0b9dacda3b8e31517fc10c39557a91306f3db5b101eb6975bdcfafa07f7d` |
| [infra/apim.bicep](/home/hnakajima/work/foundry-procurement-agent/infra/apim.bicep) | 97 | 変更 | `707c5e12719b0f7e5c0fc2aec590b2dbfb7e43931146639ef6bac23a1563f271` |
| [infra/foundry/agents/catalog-search-agent.yaml](/home/hnakajima/work/foundry-procurement-agent/infra/foundry/agents/catalog-search-agent.yaml) | 10 | HEAD一致 | `b34c7c5b3718e7af73bf55cd1281d93375c9d7b6d5283f1d5d7626e979132265` |
| [infra/foundry/agents/code-determination-agent.yaml](/home/hnakajima/work/foundry-procurement-agent/infra/foundry/agents/code-determination-agent.yaml) | 10 | HEAD一致 | `286d231693ab784a0a53fed9a339d3f1c6d121e44cb5cc4347b0e50fe66d6453` |
| [infra/foundry/toolboxes/catalog-search-toolbox.yaml](/home/hnakajima/work/foundry-procurement-agent/infra/foundry/toolboxes/catalog-search-toolbox.yaml) | 13 | HEAD一致 | `2dbc014dd6e2d2b9094e9e2f70fffe0179ddfde7b5f93eecf5bef2afa9330a3e` |
| [infra/foundry/toolboxes/code-master-toolbox.yaml](/home/hnakajima/work/foundry-procurement-agent/infra/foundry/toolboxes/code-master-toolbox.yaml) | 13 | HEAD一致 | `cbbf03b59d245764a5674e4faa935fc093980cf8714691043b2e838a0790ba96` |
| [infra/identity-functions.bicep](/home/hnakajima/work/foundry-procurement-agent/infra/identity-functions.bicep) | 152 | 新規 | `95237fb573a6dc5a424d247f5e7002ef25831f2de1d268ea42eef3e069436099` |
| [infra/observability/instrumentation-manifest.json](/home/hnakajima/work/foundry-procurement-agent/infra/observability/instrumentation-manifest.json) | 10 | HEAD一致 | `ffa01bfe27c7c361135f0c7be9a91592b21441743e536175351553435510a413` |
| [infra/observability/kql/core-status-correlation.kql](/home/hnakajima/work/foundry-procurement-agent/infra/observability/kql/core-status-correlation.kql) | 15 | HEAD一致 | `0c52b4191cd89dfe2cd15d3278f45f111f4bb2c6935723201d6a5855252cfa2b` |
| [infra/observability/kql/export-exact-operation.kql](/home/hnakajima/work/foundry-procurement-agent/infra/observability/kql/export-exact-operation.kql) | 6 | HEAD一致 | `bb45b2cc73bd07a2c5cf396f362b5d19833901e78160688366bfc3d116a2669c` |
| [infra/webui.bicep](/home/hnakajima/work/foundry-procurement-agent/infra/webui.bicep) | 204 | 変更 | `574bf7b8067be2251f1b5d08ac87c1c5dd4572a94069f3e5a7abb14611c38463` |
| [main.py](/home/hnakajima/work/foundry-procurement-agent/main.py) | 7 | HEAD一致 | `a6248ab8ab406846e4b955307b542d60c15a3e738b52f0c72c381cf11d5d612c` |
| [pyproject.toml](/home/hnakajima/work/foundry-procurement-agent/pyproject.toml) | 39 | HEAD一致 | `7fe06cfdebf43afa77898cfc2b7138f1b226b7e4c1adc34dbbd428ee1d90494b` |
| [requirements-lock.txt](/home/hnakajima/work/foundry-procurement-agent/requirements-lock.txt) | 130 | HEAD一致 | `959820d4364604e4798e2479fdf94e41744fd7e45a04a8fbbfb9e46a72d10065` |
| [requirements.txt](/home/hnakajima/work/foundry-procurement-agent/requirements.txt) | 14 | HEAD一致 | `af9f5bb73e98ef6e87ac73bc4d40439b711ad4208278c874801212ca97f6558d` |
| [scripts/deploy_foundation.py](/home/hnakajima/work/foundry-procurement-agent/scripts/deploy_foundation.py) | 153 | HEAD一致 | `64a6226972c854e28d85a20aea2f6f7dbb3e7260f78a7d49f107dda1e646b3a8` |
| [scripts/deploy_foundry.py](/home/hnakajima/work/foundry-procurement-agent/scripts/deploy_foundry.py) | 198 | 変更 | `ca080c6a1a63b2122b700d32cf7c971474210ec5126da9e662dd4a6e27fb93a1` |
| [scripts/deploy_identity.py](/home/hnakajima/work/foundry-procurement-agent/scripts/deploy_identity.py) | 142 | 新規 | `e9479c75cbd75b3ee5ecd1d522aa298d6b8327e74e8888a0bc5a493e4cc312c6` |
| [scripts/export_trace_evidence.py](/home/hnakajima/work/foundry-procurement-agent/scripts/export_trace_evidence.py) | 127 | HEAD一致 | `910cdc339558ff433fe29887acf2d7292f292c37e1014c2198b285a0041b16d9` |
| [scripts/package_hosted.py](/home/hnakajima/work/foundry-procurement-agent/scripts/package_hosted.py) | 38 | HEAD一致 | `1e1c5f388dce0da6505033d4de234167d4b3615fa924fc0be86026064eef7cb8` |
| [scripts/run_s5_boundary_validation.py](/home/hnakajima/work/foundry-procurement-agent/scripts/run_s5_boundary_validation.py) | 196 | HEAD一致 | `a44e37e91fe855796e3bd836dfd340b43b946909da3688cd7c140a95fc3b5d64` |
| [src/functions-mcp-selfhosted/host.json](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/host.json) | 8 | HEAD一致 | `877b38fa6be86aedecd583f347cea814f1fa6f6c38c98ed36f514426abf84813` |
| [src/functions-mcp-selfhosted/infra/azure/main.bicep](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/infra/azure/main.bicep) | 158 | HEAD一致 | `6e322c272517efb61b63e6896cd34e89913c6370fc7cf26697c808c605573709` |
| [src/functions-mcp-selfhosted/mcp_handler/__init__.py](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_handler/__init__.py) | 6 | HEAD一致 | `a038ab913d2992c6c21c3c396ca0ab48c9460f34190ba3fb1a174f743eac77f5` |
| [src/functions-mcp-selfhosted/mcp_handler/function.json](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_handler/function.json) | 26 | HEAD一致 | `c6952c2b5481d6f074fcba6c379a5a30562ab3fb0c14a274a59ee7fc4bad47aa` |
| [src/functions-mcp-selfhosted/mcp_server.py](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py) | 507 | 変更 | `1d9b7f6b584e58be2c24a414a900c8b94f205fdc58373491c3e450ca6820f45e` |
| [src/functions-mcp-selfhosted/mcp_telemetry.py](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_telemetry.py) | 50 | 新規 | `0551372d861f62692f9450a1b82d9a5fded562815df50ab5be1c4564015de622` |
| [src/functions-mcp-selfhosted/pyproject.toml](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/pyproject.toml) | 13 | HEAD一致 | `3035132d9a1a57db2a531d7e474d0d9bd16866321a2cef9f4cf2a332f292f615` |
| [src/functions-mcp-selfhosted/requirements.txt](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/requirements.txt) | 8 | 変更 | `725c1804ad7579c563af9f2d2f95a15615d5ec174f6589a7e2aa5707ecb37ef3` |
| [src/functions-mcp-selfhosted/scripts/deploy-functions-zip.ps1](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/scripts/deploy-functions-zip.ps1) | 137 | 変更 | `0250ad251cf15719c9e5b2c9d98d2368004ccd77d7a8be316d1ea5bb69b4efed` |
| [src/functions-mcp-selfhosted/scripts/deploy-functions-zip.sh](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/scripts/deploy-functions-zip.sh) | 86 | 変更 | `05e216d4762a6fd3a9a2084d7798e9477afd2a8490788bd4bb9ce825c25921d8` |
| [src/procurement_agent/azure_validation.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/azure_validation.py) | 219 | HEAD一致 | `1c362f6af164e12c1aff3896e5f316147c5c0cffc09529443616531db5b67a87` |
| [src/procurement_agent/controller.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/controller.py) | 1040 | 変更 | `90d115a7732e43d798d094d2c922ea3184cfef0251be210ea49e9f31fd287b3b` |
| [src/procurement_agent/hosted.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py) | 626 | 変更 | `de236b5bfef610d7b899afd721750d32e079c508920718441c009abcecb8fa1d` |
| [src/procurement_agent/hosted_app.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted_app.py) | 175 | 変更 | `d93a8924469f8894b29fb8291174cab205acd6c2473b3ff095754ba90945b182` |
| [src/procurement_agent/identity.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/identity.py) | 153 | 新規 | `c080565fecf1da952d750cf9ca04e9f4e3d53611e44d6f2e4ce945ddcdbefac7` |
| [src/procurement_agent/mcp_contract.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/mcp_contract.py) | 153 | HEAD一致 | `f9870d0c1c522ea71e8dbb024011ba0242661024d31309e8384c8a9c34173cea` |
| [src/procurement_agent/middleware.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/middleware.py) | 50 | HEAD一致 | `71423130b282cf844c631f643bb99bc2834849030a50f0eebd30dfb885cd4c66` |
| [src/procurement_agent/models.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/models.py) | 401 | 変更 | `51f4cc2344a8b33c74363e01e29fdf2bc78d37fc4c8fe29511bee16c6482535f` |
| [src/procurement_agent/observability.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/observability.py) | 156 | 変更 | `325f222532eb8d221a3bf865e24f5a58996ae15e8f75f486267cda53bf5d9dd7` |
| [src/procurement_agent/plan.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/plan.py) | 195 | HEAD一致 | `fc8b2227deb01e1f7c565cc4c62a95e7522ddfb9d3a83f6a8952adcb012647cb` |
| [src/procurement_agent/progress.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/progress.py) | 93 | HEAD一致 | `7a228192166f09e836a093ed09d12fc861a4ab2580b712ce2d51b3e9850e1434` |
| [src/procurement_agent/session_state.py](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/session_state.py) | 88 | 変更 | `758c06f9c178137948cffa80dde3f615502cc98f71ca006050d04deec35adcd3` |
| [src/trace_pipeline/__init__.py](/home/hnakajima/work/foundry-procurement-agent/src/trace_pipeline/__init__.py) | 6 | HEAD一致 | `39e3d650bd2900c6a8acfae99f34accbbb34d92a17f14b692401e5cc9d49ac50` |
| [src/trace_pipeline/detectors.py](/home/hnakajima/work/foundry-procurement-agent/src/trace_pipeline/detectors.py) | 137 | HEAD一致 | `6cb4ba196b914bb96377450250a6e76384c70855038e8756227457fe0a3b6747` |
| [src/trace_pipeline/envelope.py](/home/hnakajima/work/foundry-procurement-agent/src/trace_pipeline/envelope.py) | 67 | HEAD一致 | `c2483ae167526292881558d273f0a3d2f3dea5b2d4084a4ac11fba133fd1ba94` |
| [src/trace_pipeline/normalize.py](/home/hnakajima/work/foundry-procurement-agent/src/trace_pipeline/normalize.py) | 125 | HEAD一致 | `55f88f3d882665b691e007c4a6cc5a91d3ba30a9f548b4238b27ee0aa43645d4` |
| [src/trace_pipeline/stage_b.py](/home/hnakajima/work/foundry-procurement-agent/src/trace_pipeline/stage_b.py) | 375 | HEAD一致 | `a4c57a5a2d303d0a7f253e77073fab48f8e759cc0e37dfd8b166c8e34bd2f132` |
| [src/webapp-foundry-oauth/.env.example](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/.env.example) | 14 | 新規 | `ad1bc0df9d0148b80e4fadab6d983b733bd4eb219a869bc04084575fd4f1944f` |
| [src/webapp-foundry-oauth/backend/procurement.py](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement.py) | 409 | HEAD一致 | `e4bd7e39a23000445f97b543ee878b65a580be9e496136f0b1820c39f47c0343` |
| [src/webapp-foundry-oauth/backend/procurement_flow.py](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement_flow.py) | 95 | 新規 | `1d802bbeebc5f2f553ea3aeb09fe8dd1f4f140bc10c9ace0522c4e93ec2bb3f6` |
| [src/webapp-foundry-oauth/backend/requirements.txt](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/requirements.txt) | 1 | 変更 | `69c65f7998ef21ec2b7edc38a7362e1d41478293410311c4617ab2b4d61d8bf4` |
| [src/webapp-foundry-oauth/backend/server.py](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py) | 1418 | 変更 | `45adfab2c367fc12814b8e722cede252376f5642d139e6593ff1e0a06559b99d` |
| [src/webapp-foundry-oauth/backend/static/app.js](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/static/app.js) | 862 | HEAD一致 | `71704b506cf5482ea6c6a93286d4562e8598dd2c8511963d5899d6a6ce095491` |
| [src/webapp-foundry-oauth/backend/static/index.html](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/static/index.html) | 72 | HEAD一致 | `17081929fede020940fa07c45b74fa25923510df29e10cdd3800cba359405bcb` |
| [src/webapp-foundry-oauth/backend/static/procurement.html](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/static/procurement.html) | 55 | HEAD一致 | `cde6e29f34db809340556fa23694e2016702299b25850f8cae8562f90cd4048e` |
| [src/webapp-foundry-oauth/backend/static/procurement.js](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/static/procurement.js) | 118 | HEAD一致 | `5ef2b55192db870f405042dc245103b5d5905be01af311d89bdc7db948234b4e` |
| [src/webapp-foundry-oauth/backend/static/styles.css](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/static/styles.css) | 482 | HEAD一致 | `a87d33fb7b1c9cb7c99f4f08646a15da0db48d37e127387d889023ab9a5cdb5c` |
| [src/webapp-foundry-oauth/backend/telemetry.py](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/telemetry.py) | 116 | 新規 | `67987e23584893b3bcb342dff225d059d7fe675ab9d4d7f28ce1675d91ee0d97` |
| [src/webapp-foundry-oauth/requirements.txt](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/requirements.txt) | 13 | 変更 | `1aaeb17e9b2151e2a119f68c79a377da718db541f09a0d9ae7b0cd7a025240dc` |
| [src/webapp-foundry-oauth/scripts/package-procurement.py](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/scripts/package-procurement.py) | 28 | 変更 | `0050ff4dab0b77297cc26dc9c85844fff0b10b9234815085e259cc7d28f774f5` |
| [src/webapp-foundry-oauth/startup.sh](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/startup.sh) | 22 | 変更 | `7ed9a120b713e2e461594990455007a6e02a6b0716807c626ce1941c203592d8` |
| [src/webapp-foundry-oauth/tests/test_stream_response.py](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/tests/test_stream_response.py) | 468 | HEAD一致 | `4296723666f554f939f84ba7dc513d042ab96cc4bc9cb8a92ef6ec45d6d5ce6d` |
| [tests/integration/test_azure_validation_v2.py](/home/hnakajima/work/foundry-procurement-agent/tests/integration/test_azure_validation_v2.py) | 144 | HEAD一致 | `b675affd46b4a101ee7bf0530a87b52c0a6bfa00b256c743b5b3f0562591cacf` |
| [tests/integration/test_conversation_intake.py](/home/hnakajima/work/foundry-procurement-agent/tests/integration/test_conversation_intake.py) | 619 | 変更 | `43a4bf01ae3923bc0a903187f421593460c6e2a2fef8e1f2b071301a08269827` |
| [tests/trace/test_envelope_v3.py](/home/hnakajima/work/foundry-procurement-agent/tests/trace/test_envelope_v3.py) | 154 | HEAD一致 | `9b06f4591a9a805aa4e6d779a79fe82be2cd6208732e11f63a959442516c2acc` |
| [tests/unit/test_hosted_factory_v2.py](/home/hnakajima/work/foundry-procurement-agent/tests/unit/test_hosted_factory_v2.py) | 242 | HEAD一致 | `a381bd79c0dc67620fead426daebfff0594613251a0bcd20e409b4f623315b8e` |
| [tests/unit/test_hosted_package_v2.py](/home/hnakajima/work/foundry-procurement-agent/tests/unit/test_hosted_package_v2.py) | 24 | HEAD一致 | `397fbfd30ec9e2ee85e71e3097ef00a0da40d9f018b4c8bd6fa71fdc2cdf6732` |
| [tests/unit/test_hosted_protocol_v2.py](/home/hnakajima/work/foundry-procurement-agent/tests/unit/test_hosted_protocol_v2.py) | 153 | 変更 | `835589b252f11b01e764302ec8060d95eca98c6e50b0683eccd4adbde32d1356` |
| [tests/unit/test_identity_tool.py](/home/hnakajima/work/foundry-procurement-agent/tests/unit/test_identity_tool.py) | 160 | 新規 | `de2133a562b513d635fc01b5cc60ff9d698c96a2e9f00757c353f525e67fe4c6` |
| [tests/unit/test_oauth_procurement.py](/home/hnakajima/work/foundry-procurement-agent/tests/unit/test_oauth_procurement.py) | 215 | 新規 | `c89ddab3e4a536b77b4ef3f7f3389eb3b9b0bebf82b39b89070543c405ceb48a` |
| [tests/unit/test_obo_functions.py](/home/hnakajima/work/foundry-procurement-agent/tests/unit/test_obo_functions.py) | 36 | 新規 | `1e91eee8788c8291f406a97ba9021751fe637996ad2cf8dd38c238475d665286` |
| [tests/unit/test_plan_v2.py](/home/hnakajima/work/foundry-procurement-agent/tests/unit/test_plan_v2.py) | 93 | HEAD一致 | `10232f8de0687980f503e2482f8f3741a52f1a36c67141e91f587d118c9e015d` |
| [tests/unit/test_webui.py](/home/hnakajima/work/foundry-procurement-agent/tests/unit/test_webui.py) | 305 | HEAD一致 | `2b6ed22e6cb3c46f44ec8877285b11f7b1ba325f847c2e2bcacfc40c7899c582` |

## 6. 再照合方法

`source-snapshot.json` の各pathをこのリポジトリrootから解決し、ファイルbytesのSHA-256を比較する。SDKファイルがない場合は依存未導入として区別する。hash一致はソース同一性の確認であり、認証・Azure送信・ユーザー操作の成功判定ではない。

実設定は[設定資料](../deployment/configuration.md)、実Webの同意・Graph名前表示・Trace・null消去は[検証記録](../report/validation-results-2026-09-08-obo.md)を参照する。
