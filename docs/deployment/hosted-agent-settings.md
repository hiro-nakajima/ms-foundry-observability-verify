# HostedAgent 設定内容

以下の基盤設定表は2026-09-08の読み戻し記録であり、最新稼働値の再照会ではない。現行コードの説明は2026-09-12の改善に合わせて更新した。最新のv35配備確認は[改善検証記録](../observability-integration/hosted-refactor-validation-20260912.md)を参照。

実設定照会: 2026-09-08。購買親 `procurement-parent-agent` **v33 / active** をFoundry SDKで読み戻した。[共通構成](configuration.md)／[Tool呼出し順](../observability-integration/hosted-agent-as-tool.md)／[source ZIP配備](hosted-agent-source-zip.md)。

## 1. Agent versionと実行定義

| 項目 | 現在値 |
| --- | --- |
| account / project | observability-verify / proj-default |
| Agent name / version | procurement-parent-agent / 33 |
| kind / status | hosted / active |
| protocol / version | responses / 2.0.0 |
| runtime | python_3_13 |
| entry_point | [python, main.py] |
| dependency_resolution | remote_build |
| cpu / memory | 0.5 / 1Gi |
| content_hash | 8978c3512b3a7bce02654b3af46c7daebd6c8ecd5e2228476558fce88f96e1a3 |
| runtime principal_id | 80a1bbc5-c4b4-49da-b78e-b817696fe464 |
| runtime identity status | active |

WebからはAgentのstable endpoint名で呼び、APIMにもversion番号は埋め込まない。この表は確認した配備versionであり、将来の新version追加後もv33を呼び続けることを保証する設定ではない。配備後は実際に解決されたversionと定義を再確認する。

source ZIPのrootにmain.py、requirements.txt、requirements-lock.txtを配置し、procurement_agentのPython modulesとStage B用4ファイルだけを許可する。`identity.py` も配布対象。Web／Functions／秘密値／.local_stateをHosted ZIPへ混在させない。

## 2. 明示的に設定された環境変数

| 設定名 | 現在値 |
| --- | --- |
| `PROCUREMENT_PARENT_MODEL_DEPLOYMENT` | `gpt-5-mini` |
| `PROCUREMENT_CATALOG_AGENT_NAME` | `catalog-search-agent` |
| `PROCUREMENT_CATALOG_AGENT_VERSION` | `4` |
| `PROCUREMENT_CODE_AGENT_NAME` | `code-determination-agent` |
| `PROCUREMENT_CODE_AGENT_VERSION` | `2` |
| `PROCUREMENT_ENABLE_SYNTHETIC_INJECTIONS` | `true` |
| `OTEL_PROPAGATORS` | `tracecontext,baggage` |
| `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` | `false` |
| `PROCUREMENT_IDENTITY_TOOLBOX_ENDPOINT` | `https://observability-verify.services.ai.azure.com/api/projects/proj-default/toolboxes/procurement-identity-toolbox/versions/1/mcp?api-version=v1` |

Foundry project接続先は `FoundryRuntimeSettings.from_env()` が読む **FOUNDRY_PROJECT_ENDPOINT** が必須。このキーはversion定義の明示environment_variablesにはなく、Hosted runtimeからの供給に依存する。配布済みコードでの実行成功は確認済みだが、今回runtimeの全環境変数はdumpしていない。ローカル起動では上記projectの直接endpointをFOUNDRY_PROJECT_ENDPOINTへ明示する。WebのAPIM向けPROJECT_ENDPOINTをHosted内部接続へコピーしない。

`PROCUREMENT_ENABLE_SYNTHETIC_INJECTIONS=true` でも通常会話へ無条件に障害を注入しない。synthetic=true、stage-b-v1 contract、許可profile、AZURE-CORE- case prefixの全条件をコードが要求する。通常Webはこの検証用metadataを転送しない。

Toolbox endpointは同一projectのversion付きURL。`scripts/deploy_foundry.py` が検証済みidentity manifestから設定する。別環境のmanifestをコピーして接続先を推測しない。

## 3. Agent Tool構成

| Tool | Agent実体／接続先 | Session |
| --- | --- | --- |
| obo_identity_agent | Hosted内の専用Agent → procurement-identity-toolbox v1 | Agent.as_tool、propagate_session=false |
| catalog_search_agent | Foundry登録済みcatalog-search-agent v4、model gpt-5-mini | FoundryAgent.as_tool、propagate_session=false |
| code_determination_agent | Foundry登録済みcode-determination-agent v2、model gpt-5-mini | FoundryAgent.as_tool、propagate_session=false |

OBOはLLMを使用しないDeterministicChatClient。購買intakeのPlannerはgpt-5-mini、親の最終応答clientはController結果を返す決定的な処理。Tool登録と実行順を分け、明示的なOBO依頼はHostから独立経路へ分岐し、通常購買のCatalog→Code→mergeはController内で制御する。

Catalog v4はcatalog-search-toolbox v1、Code v2はcode-master-toolbox v1へMCP接続する。各Toolboxの接続定義は[検索MCP設定](toolboxes-and-search-mcp.md)を参照。Portalの見た目だけでTool未設定と判断せず、version定義のToolbox間接参照を読み戻す。

## 4. OBO ToolboxとOAuth connection

| Toolbox設定 | 現在値 |
| --- | --- |
| name / version | procurement-identity-toolbox / 1 |
| MCP server_label | whoami_func |
| server_url | https://func-procurement-obo-nkjm.azurewebsites.net/mcp |
| allowed_tools | [whoami] |
| require_approval | never |
| project connection | procurement-whoami |
| 実際の公開Tool名 | whoami_func___whoami（2026-09-08 tools/list実測） |

`require_approval=never` はMCP操作承認の指定であり、OAuth同意が不要になる設定ではない。Tool一覧のFunctionToolをそのままinvokeし、SDKが保持するremote名／metadataを利用する。

| OAuth connection設定 | 現在値 |
| --- | --- |
| name / category / authType | procurement-whoami / RemoteTool / OAuth2 |
| metadata.type | custom_MCP |
| target | https://func-procurement-obo-nkjm.azurewebsites.net/mcp |
| authorizationUrl | https://login.microsoftonline.com/d21866e6-786d-4625-8dc0-1e11e973489a/oauth2/v2.0/authorize |
| tokenUrl | https://login.microsoftonline.com/d21866e6-786d-4625-8dc0-1e11e973489a/oauth2/v2.0/token |
| scopes | api://f7fa30f4-1600-4a07-a0df-ee8ef405fece/access_as_user |
| 固定redirect URI | https://global.consent.azure-apim.net/redirect/8febc08999364a4e845f8d03cc06aff3 |

ここに記載したのは設定用の固定URLであり、利用者ごとのstateやcodeを含む同意実行URLではない。OAuth credential値や利用者Tokenは記載・出力しない。

既存Entra App C `83acd394-6fe9-4dba-861e-2ff370f989b0` をOAuth clientとして再利用し、上記redirect URIを追加した。MCP API／MSAL OBOのApp Bは `f7fa30f4-1600-4a07-a0df-ee8ef405fece`。既存URIとcredentialは削除していない。App B/Cの採用は配備記録を根拠とし、今回の再照会ではconnectionの非秘密設定を確認した。

Functions側はENTRA_TENANT_ID、ENTRA_CLIENT_ID、ENTRA_CLIENT_SECRET、EXPECTED_TOKEN_AUDIENCES、EXPECTED_TENANT_ID、GRAPH_SCOPESを使用する。今回のOBOはApp Bの **client secret方式**。FIC用client_assertionを用いる実装ではない。user_assertionは受信した利用者委任Tokenで、App B secretとは役割が異なる。

## 5. Hosted実行IDのRBAC

| 主体 | Role | Role definition GUID | Scope |
| --- | --- | --- | --- |
| Hosted runtime identity | Foundry User | 53ca6127-db72-4b80-b1b0-d745d6d5456d | proj-default project |

principalは `80a1bbc5-c4b4-49da-b78e-b817696fe464`。Hosted → Foundry子Agent／Toolboxの呼出しに使う実行IDであり、Graph /meの利用者IDではない。Web用MIと取り違えない。

Foundry project identity `70c395fd-1d99-4849-a283-9344ee8c9cd6` にはSearch Index Data ReaderとReaderがCatalog／Codeの各indexスコープで付与されている。これは検索経路の権限であり、Graph利用者委任の代わりにはならない。

Role名はAzureで読取った現在名を採用した。異なる環境や時期ではrole GUIDと権限を確認する。[Foundry RBAC公式資料](https://learn.microsoft.com/en-us/azure/foundry/concepts/rbac-foundry?view=foundry-classic)

## 6. 現行のOBO・会話の動作

2026-09-12の改善で `app.identity.lookup` と `app.user.id` の独自契約を廃止した。通常の購買依頼ではOBOを呼ばない。「私は誰ですか」等の明示的な依頼をHostが判定し、Plan & Executeとは独立したidentity Toolへ分岐する。取得した名前は応答に使い、購買状態へ保存しない。

OAuth同意が必要な場合はSDKの同意要求をWebへ返し、既存の同意UIで再開する。Toolbox未設定時は名前を取得できない旨を返す。本人照合はFunctionsが委任TokenのoidとGraph /meのidで行う。Webのhashとの照合は行わない。

購買状態はFramework AgentSession.stateで管理する。独立OBOは購買Sessionを作成しないため、OBO後の購買継続には標準のconversationを使う。previous_response_idだけによるOBOから購買への継続は対応しない。

現行のソースと呼出し順は[Hosted README](../../src/hosted-agent/README.md)と[Tool呼出し順](../observability-integration/hosted-agent-as-tool.md)を参照。

## 7. OTel設定

[main](../../src/hosted-agent/procurement_agent/hosted_app.py) から `ProcurementResponsesHostServer(..., configure_observability=configure_host_observability)` を作る。SDKがProvider/exporterを構成し、`TelemetryRecorder.for_hosted_runtime()` とidentity tracerが同じglobal Providerを使う。

| 対象 | 設定／観測 |
| --- | --- |
| アプリSpan | plan.create、plan.step.execute、merge.validate、response.generate |
| OBO | identity.lookup。status、エラー段階／型、公開Tool名を記録 |
| SDK標準 | Agent／Chat／Function／MCP。手動Spanと二重化しない |
| Synthetic専用 | semantic.evaluate。固定gate条件下のみ |
| propagator | tracecontext,baggage |
| GenAI message content | false |
| MCP exception privacy | McpPrivacyProcessorで例外message/stacktrace、status descriptionをexport前除去 |
| 出力先 | SDK構成の共通Application Insights |

App Insights resource IDは `.foundry/agent-metadata.yaml` と配備スクリプトのproject接続設定が正本。APPLICATIONINSIGHTS_CONNECTION_STRINGはversion定義の明示environment_variablesにはなく、Host SDK／プラットフォームの観測設定を利用する。connection stringをHostedのpromptやTool引数へ渡さない。McpPrivacyProcessorはOTel 1.43の内部hookに依存するため、SDK更新時は契約テストを行う。

Managed Prompt側のcontent recordingでは希望したProtected設定が実際はGeneralのままで、本文記録offを保証できない制約を配備記録へ残している。今回の特定OBO成功Traceでは実氏名／OAuth実行URLの記録がないことを確認したが、全管理Span・全会話へ保証を拡張しない。

## 8. 確認と再配備

読み戻す対象はAgent **version定義**、runtime identity、環境変数、Toolbox version、OAuth connection、role assignment。`agents.get_version(agent_name="procurement-parent-agent", agent_version="33")` と `toolboxes.get_version(name="procurement-identity-toolbox", version="1")` がSDKの照会位置である。環境変数を無差別にdumpせず、非秘密の設定だけを抽出する。

新versionの作成は[Hosted source ZIP手順](hosted-agent-source-zip.md)に従う。identity manifestも先に対象projectで確認し、配布後にactive状態と実行identityのrole、OAuth同意／取得／省略を確認する。既存正常versionや同意接続を削除しない。

v33の配布hash、同一会話でGraph名→省略→nullの実測、実Web OBO確認は[検証記録](../report/validation-results-2026-09-08-obo.md)を参照。
