# Web App / APIM readiness — 2026-09-03

状態: 基盤deployment `procurement-foundation-20260903021112` はSucceeded。Search 2 index、Blob indexer、Prompt子、Hosted親v9、新Developer APIM、App Serviceを配備済み。EasyAuth Browser 5 turnのCore flow成功とTrace照合まで完了。S2〜S4のAzure semantic injection、commit/push、最終Review、mergeは未実施。
本書は改訂Architecture資料の実装状況補足。Stage A全14、Stage B 6、S1/S5 Healthy、S1〜S5、V1〜V21は削減しない。

現行Web deploymentは`efebcca8-3807-410a-b04f-dd9ed6ea8f0d`（ZIP SHA256 `96a5b9f68f16e61ceb45f8a47f701af6e4242e465d54cb0a07383e5dc978b9d5`）。status 4/complete/active、Running、匿名401。UIのManaged境界表示は、実測に基づきTrace Context伝播/user.id非伝播へ更新した。詳細とexact Trace evidenceは[Azure検証記録](../azure-observability-validation-2026-09-03.md)を正とする。

## 現在の実測状況

Foundry Prompt子作成の実APIが`400 invalid_parameters`を返した。Agent名は英数字開始/終了・途中hyphenのみ・63字以内という制約で、指定済み`catalog_search_agent`はunderscoreにより拒否される（request ID `fd88b4a2c9dd305e67196a877fefb52c`）。
ユーザーの名称変更承認を受け、論理role名は維持し、Azure実名を`catalog-search-agent` / `code-determination-agent` / `procurement-parent-agent`にした。
作成成功: Search project-MI connection、AppInsights connection、2 Toolbox version 1、各RemoteTool connection、Prompt子2つ version 1。Hosted親はsource ZIPでversion 1を作成し、3 Agentともactiveを確認した。
最初の直接呼出しは`404 not_found`。Project Conversationをnamed Agent endpointへ渡したことが原因で、同じAgent endpointのConversations APIへ揃えると解消した。case `S1-DIRECT-20260903062750`はHTTP成功、構造化result/Conversation/Framework Session hashを取得したが、`planner_intake_failed`でtechnical ERROR/business BLOCKED。これはS1正常PASSではない。
同じplannerの実モデル呼出しで`400 invalid_json_schema`を再現。任意キーのspecifications dictとstrict schema制約の不一致であり、Pydantic生成schemaをstrict=falseで送り、同じmodelで結果検証する方式は単発実測成功。修正版Hosted version 2はactive。S1直接実行ではplannerを通過したが、Toolbox→SearchのAccess deniedで停止。旧version/ZIPは保持。詳細なCore/V1〜V21の実測状態は[Azure検証記録](../azure-observability-validation-2026-09-03.md)を参照。query identityへの更新権限は追加していない。
Web App packageはビルド成功。最初の起動失敗はhttpx依存欠落を確認し、httpx/aiohttp/openaiを明示固定した。現行ZIPは依存修正とnamed Conversation経路を含み、deployment ID `8e37eae7-e693-4c5b-9912-cae214ea9729`でsite起動成功を確認。ZIP SHA256 `305a8ad00d868ab8dd91b86d185b7accacce896f9d5e2ed470096322dd28154d`。
未認証curlは401、`/.auth/login/aad`はEntraへ302を実測。ARM設定はrequireAuthentication=true / RedirectToLoginPage。その後、実EasyAuth要求がcode + id_tokenなのに専用Entra登録がID-token発行無効という不一致を修正。ユーザーが再ログイン後のチャットUI表示成功を確認。元の黒画面にはエラー番号なし。callback URIは一致し、secretも値を出さず存在/一致確認。OBO/delegated API権限は追加していない。Web/EasyAuth経由の実チャットは別途未検証。
実送信header観測版Web ZIPはdeployment `ffaa00ef-ad28-459e-ba80-333666e1277f`、status 4で成功。SDK自動計装後のtransportでtraceparent/現在span一致・user.id baggage一致のbooleanのみ記録し、raw headerやtokenは記録しない。Local実HTTP検証成功、Azure相関待ち。
実ユーザーのcase `WEB-abc0dbe225a5a8c4`でMI→APIM→FoundryのConversations/ResponsesはHTTP200、Web/HostedのTrace ID・Conversation一致を確認。業務は旧親v2のintake SCHEMA_INVALIDであり、正常S1ではない。Web v4の観測属性が`http.*`としてexporterに除外されることをSDKコードで確認し、`app.propagation.*`へ修正。Local実HTTPとexporter変換後の保持をテストし、Web v5 deployment `73af769f-cdce-4a37-94d1-4ed456655403`はstatus 4。
現行AgentはPrompt子2つv2 / Hosted親v4、全てactive。子status各層の明示指示を追加し、親は依頼抽出と計画生成を区別。両Prompt identityは旧版と同一で再利用、role assignmentの追加なし。旧版/ZIPは保持している。
会話上部・入力下部に戻したWeb v6はdeployment `da70715f-43b7-4601-b515-e224c659585c`、status 4。07:30:40〜41 UTCにsite startup probe成功。実サインイン後の新版レイアウト確認とheader booleanのAzure取得は未実施。
日本語応答版Web v7はdeployment `dfc86b15-6946-4c74-8894-5d579f906eab`、status 4 / complete=true / active=true、07:51:53 UTC完了。07:53:33 UTCにApplication startup completeを確認。ZIP SHA256 `0e802b61287f26faff70abf2850c041ba77be41f3ba418ecb7137f8461ec87c5`。旧ZIP保持、clean=false、設定・identity変更なし。実ログイン済み画面での新版確認はユーザーへ依頼中。
07:34 UTCの実Web Trace `701e47d92179cdfd160e160b4d680166`ではWeb clientの`app.propagation.traceparent_matches_span`と`app.propagation.baggage_user_id_matches`がいずれもTrueとしてInsightsに格納された。Web→Hosted→Catalog Prompt→Toolboxは同一Trace ID。ただし下流のuser.idは記録されず、未取得parentもあるため、全経路の伝播PASSではない。詳細はAzure検証記録に記載。
未使用ACR `acrprocurementobservenkjm` はユーザーの明示承認後、repository/taskが空であることを確認して削除した。対象RGのACR一覧が空になったことを再確認済み。失われたimageなし。削除前までのSKU費用は残る。空registryの再作成は可能だが、削除自体の取消しではない。

## 確認した環境

- WSL Azure CLI: 対象subscription `d96eb8c2-2deb-4ed5-8cf2-f9fb178cb3ee` にread-only呼出し成功。
- 対象RG: `rg-ms-foundry-observability-verify`。Foundry `observability-verify` / project `proj-default`、East US 2。
- 参照APIM: `rg-ms-foundry-mcp/apim-mcp-handson`、East US、Consumption、VNet None、system MIあり。今回はread-only参照のみ。
- 参照Web App: `webapp-mcp-handson-nkjm54`、Python 3.14、startup.sh、1 worker、Always On false、EasyAuth必須、token store true。
- 参照Web Appはrefresh_token認証。購買PoCはMIなのでtoken store/OBO/Graphは不要。
- 参照API `foundry-proj-default` はsubscriptionRequired=false。POST `/openai/v1/responses` とPOST `/agents/{agent}/endpoint/protocols/openai/responses` のみ。
- 参照operation policyはAuthorization header確認・転送とsubscription key削除。新構成はheader存在確認だけでなくEntra token検証とApp Service MI限定を追加。
- provider: Search/Web/APIM/OperationalInsights/ContainerRegistry/Insights/CognitiveServices/ManagedIdentityはRegistered。
- 既存モデル: `gpt-5-mini` v2025-08-07、GlobalStandard 500、eastus2 quota 500/1000。新モデル作成なし。Hosted固有capacityはquota APIで未確認。
- 既存Foundry project connection/capability hostなし。BYO Storage必須条件は検出されていない。

## Search availability

2026-03-01-previewのprovider offerings APIをCLIから読み取り、`centralus` / `westcentralus` / `japaneast` がいずれも `serverless` を返すことを確認した。
公式tier資料は引き続きWest Central US / Switzerland North / Japan Eastのみと記載しており、Central USのavailabilityを確定できない。
前回の2025-05-01 + serverlessのInvalidSkuNameはregion不可の証明ではなかった。
今回はユーザーの「選択肢1」承認に沿い、双方にあるWest Central USを選ぶ。

Serverless DeveloperはPreview・SLAなし。費用はcompute usageとindexed storageが要因。
2026-09-03再確認時はtier/cost資料とも2026-09-13課金開始と記載。無料の継続を前提にしない。

根拠: [tier / region](https://learn.microsoft.com/en-us/azure/search/search-sku-tier)、[cost](https://learn.microsoft.com/en-us/azure/search/search-sku-manage-costs)。

## WebUI採用判断

`src/webapp-foundry-oauth` を配置単位として採用。ただし元実装をそのまま使うだけでは次が不足していた。

| 項目 | 元サンプル | 購買PoC入口 |
|---|---|---|
| 自然言語入力・静的配信 | あり | 既存CSS・startup方式を利用 |
| Foundry認証 | refresh/OBO中心 | system ManagedIdentityCredential |
| 会話 | browser UUID + in-memory previous_response_id | Foundry Conversations API + signed owner-bound cookie |
| 相関 | job/response中心 | root/client trace、span、conversation、case、turn |
| 業務status | 未対応 | technical/business/MCP/Search/parseを別表示 |
| 情報表示 | OAuth consent / Tool arguments | 限定業務projectionのみ。raw Tool/trace/claims非表示 |

Hallmarkは利用不可。最小UIに限定した。旧root `webui/` は削除済みで、復元ZIPはignored `.artifacts/retired-webui-2026-09-03.zip`。
ユーザーの追加指示により、元サンプルの`app-header` / `messages` / `input-bar`配置へ戻した。会話は上部の独立スクロール、composerは画面下部。送信内容と限定されたAgent responseをturn順にtextContentで表示し、最新status/Traceは折りたたみ表示にした。既存CSS・元index/app.jsは上書きしていない。追加frameworkなし。
画面内のメッセージ表示はDOM内のみで、再読み込み時はリセットされることを明示。署名cookieによるFoundry Conversation継続は従来どおりで、localStorageや独自履歴Storageを追加せず、「新しい会話」でも以前のFoundry履歴を削除しない。
ユーザー追加の元server/JS/doc/ZIPは削除しない。旧deploy scriptsは誤配備防止guardを追加した。
新packageは明示allowlistの6ファイルのみ、既存ZIP上書き不可。

追加要望により、画面の生JSON表示を日本語の実行結果表示に変更。内部ScenarioResult JSON/status契約は保持し、Web backendで既知のstep.started/completed/retry_scheduled/plan.blocked/replannedとstep IDだけを表示用文章へ変換する。実行完了後の要約であってリアルタイムの進捗やChain-of-Thoughtではない。記録のない工程は未確認とし、停止後に残ったdraftを成功扱いで表示しない。提出・発注はしないことを明記。未知のevent/reason/next_action、元JSON、実社員情報を表示せず、追加LLM呼出しなし。

## Local検証

Python 3.13でpytestを実行し、134 passed / 1 skipped（Azure外部test）/ 1 warning。ZIP package起動テストを含む。SDK/HTTPXの実HTTP fixtureは以下を確認する。

- incoming browser traceparent/tracestate/baggageの不採用。
- server spanをrootとする同一Traceのclient spanと、実outgoing traceparentのSpan ID一致。
- baggageはuser.idの仮名化hashのみ。raw claim/tokenがexported属性・eventsへ入らない。
- Foundry API形式のconversation作成/取得/metadata更新と2 turn継続。previous_response_id不使用。
- 別ユーザーcookie、改ざんcookie、CSRF、任意conversation bodyの拒否。
- 新しい会話を始めてもリモート履歴は削除しない。
- raw trace/不正な結果値を表示しない。

API fixtureはAzure EasyAuth認証、APIM token validation、Foundry側の実Conversation対応を証明しない。
既存external testは有効化すると明示failするplaceholderであり、認証だけ設定して実Azure Matrixが走る実装ではない。実run harnessの実装が必要。
Browser plugin not available。frontend testing skillのfallbackで同梱Playwrightと既存Edgeを使用し、1280x1000/390x844で入力、status/correlation表示、reload後の会話表示、2turn、新規会話を確認。横はみ出しなし、pageerrorなし。APIはSynthetic fixtureでありAzure E2Eとは区別する。スクリーンショットはRepository外のCodex visualizationsに保存。
下部入力レイアウトも同じ2 viewportで再確認し、composer.bottomとviewport.bottom一致、messages.bottom≦composer.top、2turn/再開/新規会話/詳細開閉成功、console error/warningなし。実画面は`webui-chat-bottom-desktop.png` / `webui-chat-bottom-mobile.png`としてRepository外に保存。Local全体129 passed / 1 skippedを再確認した。
日本語応答版も1280x1000/390x844で再確認。2turn、JSON非表示、reload後の会話継続、新規会話、詳細開閉、下部composer、横はみ出しなし、console error/warningなし。証拠はRepository外の`webui-natural-response-desktop.png` / `webui-natural-response-mobile.png`。API fixtureによるUI検証であり、実ログイン済みのin-app Browser操作はこのタスクに操作用skill/toolsがないため未実施。

## what-ifと予定構成

`infra/webui.bicep` build成功。what-ifは `Succeeded` / `error=null`。
当初dummy what-ifは16件Create。実パラメーターではACRを加え17件Create、既存Foundry account/project 2件Ignore。Delete/Modify/置換なしでapplyしSucceeded。
専用Entra app `procurement-observability-web`を作成。30日期限credential（2026-10-03失効）とsession署名keyはignored `.local_state/deployment`のmode-600ファイルとApp Service settingsで管理し、値は出力しない。参照APIMと同一publisherメールの使用は承認済み。

| Resource | 設定 / 名前 | 費用要因 |
|---|---|---|
| App Service Plan | B1、1 instance、`asp-procurement-observe` | instance時間。Always On falseでもPlan費用は発生 |
| Web App | `web-procurement-observe-nkjm`、Python 3.13、system MI、EasyAuth | Planに収容 |
| APIM | Consumption、East US、`apim-procurement-observe-nkjm` | API operations数 |
| Search | Serverless、West Central US、`srch-procurement-observe-nkjm` | preview後のcompute/storage |
| Log Analytics / App Insights | Web App名 + logs/insights、retention 30日 | ingestion量・保持 |
| Foundry | 既存projectを再利用 | model/token、Hosted compute等はagent部署段階で確認 |
| 未使用ACR（削除済み） | `acrprocurementobservenkjm`、Basic、East US 2 | 指示変更前に作成、承認後に空であることを確認して削除。削除前のSKU費用のみ |

[APIM pricing](https://azure.microsoft.com/en-us/pricing/details/api-management/)、[App Service pricing](https://azure.microsoft.com/en-us/pricing/details/app-service/linux/)。
画面の料金値は動的で未取得。金額見積りやAzure請求実測済みとは扱わない。

Web AppへFoundry Project Runtime User（`142bfaed-a13f-4c2d-bed2-6db62c4a1009`）をproject scopeで付与済み。Conversations APIがこのroleで許可されるかは実測待ち。Hosted endpoint用Foundry Agent Consumer（`eed3b665-ab3a-47b6-8f48-c9382fb1dad6`）を`procurement-parent-agent`のagent scopeに追加済み。
Prompt子それぞれの専用Agent identityへToolbox利用のFoundry Userをproject scopeで付与済み。
runtimeへRG Contributorを付与しない。APIMはBearer転送のため新規MI/RBAC不要。
SearchはCLI配備実行者へservice scopeのSearch Service Contributorと2 index scopeのData Contributor、Toolbox用project MIへ2 index scopeのData Readerを付与。承認後、index定義readのためproject MIへ同じ2 index scopeのReader（`acdd72a7-3385-48ef-bd42-f606fba81ae7`）を追加。catalogで先に成功確認してからcode masterへ適用し、双方の実MCP queryがisError=falseで成功。account MIへのrole追加、query identityのwrite/admin key権限追加はなし。
schema管理とdocument投入は同じ配備callerであり、別principalでの分離は未実施。runtimeと配備callerは分離済み。
Search push実測: catalog 10件、code master 9件をHTTP APIでaccepted。元JSON hashはignored search-manifestに保存。Toolbox query成功と、Prompt/親を含む業務成功は別途検証する。

初期配備ではStorage Accountなし。後続のユーザー承認により、Search取込用Storage `stprocurementobsnkjm`を同じPoC RGに追加し、Blob JSON→Indexerへ変更した（実測はAzure validation report参照）。Conversation metadata/historyは引き続きFoundry保持、UI単一instance。
Hosted配備は追加ユーザー指示により**source ZIP / remote_build**を使用する。ACR定義を今後のBicepから除外済み。ZIPはmain/requirements/lock/procurement_agent Pythonだけで、商品JSON、WebUI、docs、tests、secret、local stateを含めない。
Toolbox、Prompt子2つ、Hosted親、Foundry Insights connectionは基盤とは別の配備スクリプトで作成する。
Private Endpoint/VNet/Private Link/AMPLS/DNS変更/T4なし。

## 継続条件・rollback

以後: Toolbox/Prompt/Hosted ZIP配備 → Web App package配備 → Azure測定 → stable HEAD Review → P0/P1なければSquash Merge。

基盤apply済み。既存リソースを触らず、失敗した新規resourceを記録する。
削除・既存role削除・network変更は別承認。Code rollbackは保管した前packageを同一Web Appへ再配備し、署名keyを保持して会話cookieを失効させない。

S1〜S5/Stage A/BはLocal contractを保持。直接Hosted経路では親/Catalog Prompt/Toolboxの同一Trace IDと一部Session mappingを実測したが、未取得parent spanがあり全E2Eは未証明。Azure Core Matrix、V1〜V21、Web入口のtraceparent/baggageは未完了でありPASSにしない。詳細はAzure検証記録を参照。
controllerは642行（初回Catalog/retryとterminal結果生成の重複集約）、hostedは311行。600行未満の目安よりstatus/Trace contractを優先した。test専用factory telemetry引数と未使用public wrapper `execute_hosted_turn()`を削除し、テストはprivate経路へ移行。未参照build_local_parent_scaffoldは存在しない。
未使用のapplicants/delivery_rules/tax_rules JSONを削除し、Search用3 JSONを維持。削除データはGit HEADから復元可能。旧文書とユーザー作成の元WebAppファイルは保持。最終Review/commit/push/mergeは未開始。
