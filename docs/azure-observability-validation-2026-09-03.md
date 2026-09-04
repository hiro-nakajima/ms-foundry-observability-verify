# Azure Observability 検証記録（進行中）

仕様・検証目的の正本は[改訂Architecture資料](revised-architecture-observability-validation-plan-2026-08-31.md)。本書は実測状態のみを記録する。旧4構成/88-run Matrixは対象外。

## 現時点の証拠と限界

- Local: Python 3.13、161 passed / 1 skipped / 2 deprecation warnings。Stage A 14 positive/negative、Stage B 6 injection、S1/S5 Healthy、Session/History、MCP fixture、status分離を保持。
- 2026-09-04後続修正: 対話入力を商品・台数・所属部署・メモ＋最終「確定」に限定。Catalog候補、選択、EasyAuth申請者名をFramework AgentSessionへ保存し、選択後の詳細入力turnではCatalogを再実行しない。最終「確定」turnだけCatalog根拠を更新してCode/mergeへ進む。購買ナレーションをWebからHostedの`response_text`へ移した。Local全回帰後、Hosted v8（source ZIP SHA256 `5cf02c55fb0000ab68b3f554a8b3a60234d31e78d8ced9abc6afab4955bf0bd9`）とWeb deployment `6ab3aa24-9fe6-4478-a9b4-605806d3e723`を配置した。Web package SHA256は`fd92c20405c674738d96731dadb32f4496a4e333cf747771f1fd1a3531de4105`。Azure streamで隣接する同一progress deltaを観測したため、Web中継で直前と同じ公開progressだけを抑止した。
- AppGenAIContent保護: subscription preview feature `Microsoft.Insights/protectGenAISensitiveData`は`Registered`。特権閲覧roleは追加していない。公式REST PATCHはHTTP成功したが、2025-02-01/2025-07-01の読み戻しはいずれも`protectionLevel`なし（General相当）で、Protected適用は未確認。成功扱いにせず`API_ACCEPTED_BUT_NOT_APPLIED`とする。Hosted/App Serviceのcontent captureは引き続きoffだが、Managed Prompt側の既存記録制約を解消したとは扱わない。
- Hosted v8 case `CHAT-DIRECT-20260904024741`: 4 turnを同一Conversation `conv_025a60809016ca1a00QvKGAfKwxxRPcDghQEhiBxsWlaviQfXy` / 同一Framework Session hashで完走。初回39.594秒、商品選択1.542秒、項目入力11.716秒、確定49.220秒。turn 2/3にはCatalog `started`がなく保存済みstateを再利用し、turn 4だけCatalogを再検索してCode/merge後にtechnical/businessともSUCCESS、draft生成。直接Foundry合成経路でありBrowser/EasyAuth E2Eではない。
- 同caseのallowlist KQLでは3 turn分のapplication spanにConversation/case/turnを確認し、各turnは別Operation ID。AppDependencies/AppRequests/AppTraces計150件のcustom propertiesと、同Trace群のAppGenAIContent 12件を件数だけ照合し、合成申請者名の値および`app.authenticated.display_name` keyの記録は0件だった。raw contentは取得・報告していない。
- Browser incident `WEB-8169dbf928133fc0` / Trace `03e8c3c370e16fd541f0793ac0de5964`: 同じConversationのturn 8でWeb requestとAPIM/ResponsesはHTTP 200だが、HostedはFramework state取得直後・planner前に`Failed to produce response for agent`となり、Webは中断表示。Conversationはv7から継続され、保存stateに旧`purpose/requested_by`、v8 modelに新`memo`/extra禁止があるため、`procurement.execution.v2`復元時のschema不一致とコード/時系列が一致した。旧業務値を推測移行せず、Conversationのturn番号だけ保持して新intake stateへresetする回帰を追加。Local `154 passed / 1 skipped`後、Hosted v9 source ZIP SHA256 `cd7f44d9510ab735adbf649702e18fa1fee7128875342eb2c255207e96ee8431`を配置しactive。後述の新ConversationによるBrowser 5 turn完走で復旧を確認した。
- v9再現Trace `c69e429d47b4d9baf226c77cc1788ef1`ではagent version 9を確認したが、別の旧Conversation turn 13でもstate/history `batch/retrieve`直後、アプリhandler前に同じRuntimeError。Hosted内resetでは到達不能と判明。Web Conversation metadataへ`contract=procurement-intake-v2`を追加し、versionなし/不一致の旧Conversationは削除せず、新Conversationを作ってcookie handleを切り替える。通常の同contract会話は継続。Local `155 passed / 1 skipped`後、Web deployment `41a84f23-394d-4393-bf40-35d19cfd07a7`（ZIP SHA256 `cd439d6478986969dbb20039255e4f1f67d79a6e03c6e57309f5622483903875`）を配置しRuntimeSuccessful/Running/匿名401。
- Browser recovery case `WEB-bc7c676157a2cf4c`: EasyAuth実ユーザーで新Conversation `conv_064519df493981fc009tvqsQDh4n0hg1vtF0b4xRpaUr4DYo3c`を5 turn継続し、同一Framework Session hashを維持した。turn 1〜5は55.858/3.006/13.699/13.973/52.696秒。選択turn 2ではCatalogを再実行せず、確定turn 5のTrace `c876a5a2b4997bb2f44aaffb76829f7b`はHosted v9、Catalog子v3、Code子v2、両Toolbox v1、merge/responseを含み、technical/business/MCP/Search/parseすべてSUCCESS、例外・失敗telemetry 0。Conversation contractによる旧state回避とBrowser Core flowの復旧をPASSとする。
- WebUI: 同梱Playwright + 既存Edgeの実画面、1280x1000と390x844。fixtureで入力/再開/2turn/新規会話成功、pageerror/横はみ出しなし。Azure E2Eの証拠ではない。
- App Service: EasyAuthの実要求`code id_token`と専用Entra登録のID-token発行無効の不一致を修正し、ユーザーが再サインイン後のチャットUI表示と5 turn完走を確認。元の黒画面にはエラー番号がなく、特定AADSTS原因は未確定。実測済み伝播結果をUIへ反映した現行Web deploymentは`efebcca8-3807-410a-b04f-dd9ed6ea8f0d`（ZIP SHA256 `96a5b9f68f16e61ceb45f8a47f701af6e4242e465d54cb0a07383e5dc978b9d5`）で、status 4/complete/active、App Service Running、匿名401/EasyAuth保護を確認した。
- 現行Webの実送信直前transportでは、5 turn成功Traceでも`app.propagation.traceparent_present=True`、`traceparent_matches_span=True`、`baggage_user_id_matches=True`を確認。手動注入なし。下流Hosted/Prompt/Toolboxには`user.id`属性がなく、Managed境界のuser.id baggageは`NOT_PROPAGATED`とする。欠落した具体的境界はPlatformで受信headerを取得できないため断定しない。
- Search: 2 index schema作成、Synthetic catalog 10件/code master 9件のpush accepted。Toolbox query成功とは区別する。
- Hosted v1: project-created Conversationでは404。同一Agent endpointでConversationを作成すると404解消。plannerのstrict schemaがHTTP400で拒否され、technical ERROR/business BLOCKEDを返した。
- Hosted v2: ZIP SHA256 `5cac56a3b620e3383035d31d4272cabf7f86fd5e6fab768292d0aa16b6765bd9`、active。Pydantic schemaのwire strict=false修正でplanner通過。case `S1-DIRECT-20260903064227`は`child_invocation_error`、technical ERROR/business BLOCKED、MCP ERROR/Search NOT_RUN。
- 同caseのConversationは`conv_0de93d8c949c664500VAR2peQpaJ31kIkokGYg2CDRqh0rnMWt`、Responseは`caresp_0de93d8c949c6645008iwD5zRhRd91Meu7lF7BIlcYZ99iAVh4`。agent sessionはresponseの`agent_session_id`から取得し、Framework Session hashと区別してignored実行manifestへ保存。
- 対象sessionログでは親planner2回・子呼出しのHTTP200の後にMcpProtocolException。CLIから同じ子proxyを単発呼出しするとHTTP400/tool_user_errorを再現。ログの固定ラベル照合でToolbox→SearchのAccess deniedを確認。親→子の401/403ではない。正常S1ではない。
- Search connectionはProjectManagedIdentity。Data Readerにはdocument readのみでindex定義readがないため、承認後にproject MIへ各indexスコープのReaderを追加。Catalogで先に試行して成功を確認後、Code Masterへ適用。両Toolboxの実MCP tools/callはisError=falseで、catalog商品コードおよびdepartment/accountコードの存在を確認。検索本文は出力しない。account MIへのrole追加、query identityへの更新権限・admin key取得権限付与は行っていない。
- 次の直接Hosted case `S1-DIRECT-20260903070125`はtechnical SUCCESS/business INVALID_INPUT、parse SCHEMA_INVALID/MCP・Search NOT_RUN。独立した実planner再現では`constraints.specifications.quantity`が数値でstring型に違反。親指示の抽出/計画の区別を明確化すると、同じ架空依頼でschema適合・memoryのみ抽出・数量2/予算400000を確認。Hosted配備後の正常S1とは区別する。
- 親指示修正版v3のcase `S1-DIRECT-20260903071227`はintakeを通過し、Catalog Search/parse SUCCESSだがMCP NOT_RUNの子statusが返り、親はouter business BLOCKEDで停止。契約を緩めて成功扱いにせず、Prompt指示へ実行済み各層statusを明記。Prompt子v2と、それを参照するHosted ZIP v4を作成した。v4のSHA256は`7fe5d47f65e67e1eed0683c7b2ca4eb6916402a6f1366924c9522f1d164cacd8`。旧Agent versionsとZIPは保持。
- v4はactive。case `S1-DIRECT-20260903072140`はtechnical/MCP/Search/parse SUCCESSだが、子がbusiness VALIDATION_FAILED / reason SPEC_MISMATCHを返し、親がouter BLOCKEDで停止。コード更新後も正常S1は未達。検索結果の仕様fieldと要求仕様の照合を切り分け中であり、validationを無効化して通していない。
- 実MCP出力を照合すると、Catalogはproduct_code/name/category/contentの検索可能textだけを返し、`specifications_json` / `source_version`は含まれなかった。Code Masterもrecord_type/lookup_key/code/display_nameのみで、source_versionがない。retrievable=trueだけでは今回のToolbox本文へ全fieldが出る保証にならない。
- JSONから本文へID/version/採用値/仕様を投影する生成処理とテストを準備した（document_projection_version=2）。Catalogは既存content更新、Code Masterはsearchableな`content: Edm.String`追加。後述のユーザー承認後にAzure適用・文書再投入を完了。両indexのschema preflightが終わるまでdocument更新を行わない。

## 実Trace照合（直接Hosted経路）

ユーザー承認後、`poc-public` / 親Agent / 上記Insights / 直近24時間をKQLで取得。raw contentではなくID・親子関係・status・相関属性のみをprojectionした。
case `S1-DIRECT-20260903064227`には29 spans、Trace ID `b451bc8cfa4d70c304a6fc58b4e8b183`を確認。

| 境界・項目 | 実測 |
|---|---|
| Hosted application → Catalog Prompt → Catalog Toolbox | 同一Trace IDを確認。完全なparent chainとは区別 |
| Hosted親application span | `bf01716daf3a1db4`、parent `2cbaf64b1bc679ca`、Conversation/caseあり |
| Catalog managed span | `12145fa9df44b082`、parent `76002383a9b5398b`、case/Conversation属性なし。response IDあり |
| Catalog Toolbox tools/call | `c2bbba17fdec28ca`、parent `a8a2a2f3bd8d28a2`、result500/json_rpc_error（Reader追加前）。Search成功Traceではない |
| 親子関係 | 取得集合にないparent IDが5件。完全な木は未証明。収集漏れ/未公開境界の原因は未確定 |
| user.id | 直接CLI入力でEasyAuth baggageを設定していない。属性なしをNOT_PROPAGATEDの証拠にしない |
| App Service / APIM / Search / Code子 | この直接呼出しではWeb入口なし、Catalog失敗のため後段未実行。未実測をPASSにしない |

Hosted applicationのConversationとcaseは取得したが、Catalog managed spanには存在しない。
同一Trace IDと子response IDによる代替相関を保持。Webからの実送信header・baggage伝播の判定は別Traceで行う。

## 認証済みWeb実行との照合

ユーザーが送信した架空依頼と画面表示を照合した（07:09 UTC、Hosted v2）。

| 項目 | 画面 / Azure記録 |
|---|---|
| test.case.id / turn | `WEB-abc0dbe225a5a8c4` / 1 |
| Trace ID | `545ee93881d8b33b96643a3a1a0e79e1`。Web server/clientとHostedで同一 |
| App Service server span | `4c5fb2b5b4405abd` |
| Responses HTTP client span | `1f93e2463ea54aa9`、parent `4c5fb2b5b4405abd`、HTTP200 |
| Hosted server span | `82459f2c283b95a6`、parent `50a52b629e92ed06`（取得集合にない） |
| Conversation | `conv_0ebbd0930b9d940c00RNbhDk0pt2Lu6vntufLXTKB3Ebyz0CTe`。Web/Hostedで一致 |
| Response | `caresp_0ebbd0930b9d940c00kLgkE740xl02lOCEi73xsDkhk4f8MqeI` |
| Framework Session hash | `600293ec26f697d2b2596ef08dbc2843687d59ee7957faea4410dd39d3df7966`（画面） |
| 結果 | technical SUCCESS / business INVALID_INPUT / parse SCHEMA_INVALID / MCP・Search NOT_RUN。親指示修正前の失敗 |
| user.id | Web rootにあり、取得したHosted spansにはなし。raw hash値は照合出力へ出していない |
| header観測 | Web v4の`http.outgoing.*`はAzure Monitor exporterが`http.*`を除外するため格納されない。NOT_PROPAGATEDの証拠ではない |

Web runtime MI→APIM→FoundryのConversations作成/更新とResponsesはHTTP200。
同一Trace IDとConversation相関は実測済みだが、APIM spanと完全なparent chainは未取得。
Application Insightsのroot `operation_ParentId`にはTrace ID相当が返されたが、これは16桁Span IDではない。Local OTel root.parent=None / UI parent=nullと区別し、32桁値を親Spanとして接続しない。
観測属性を`app.propagation.*`へ変更し、実HTTP＋Azure Monitor exporter変換後の保持をLocalテストで確認。後述の新版Web TraceとBrowser成功Traceで送信側booleanのAzure格納も確認した。Web root以外に`user.id`が記録されないため、Managed境界のbaggageは`NOT_PROPAGATED`と判定した。

## Core / Failure Pattern

| 対象 | Local | Azure |
|---|---|---|
| S1 | contract成功 | PARTIAL: 直接Hosted正常run、実MI 3turn、EasyAuth Browser 5 turnの候補提示〜確定成功を実測。Azure Healthy detector照合は未完了 |
| S2 | status/MCP/Search/parse fixture成功 | PARTIAL: 自然負例`S2-V7-ISOLATED-20260903125123`でCatalog成功後のCode `DEPARTMENT_NOT_FOUND`、層別status、draftなしを実測。指定failure profile/TV-02/03のAzure注入は未実施 |
| S3 | retry/replan/上限停止成功 | PARTIAL: 自然負例`S3-CONTROL-20260903123933`でattempt 1/2、retry、replan、WAITING_USER、draftなしを実測。SD-03/05のAzure注入は未実施 |
| S4 | handoff完全/欠落/無視成功 | PARTIAL: Browser成功TraceでCatalog/Code完全handoffを実測。必須field欠落/無視のAzure注入は未実施 |
| S5 | 長文/境界contract成功 | PARTIAL: 8,192文字のHosted正常完走とTrace保存長を実測。Portal表示長・全境界・Healthy detector照合は未完了 |
| Stage A | 14/14 positive/negativeを維持 | Local contract。Azure実測と混同しない |
| Stage B | TV-02/03、SD-03/05、MA-04/05を維持 | AZURE_PENDING: INJECTION_MISSEDとTRACE_INCOMPLETEを引き続き分離 |
| Healthy control | S1/S5全14 detectorを維持 | AZURE_PENDING |

## V1〜V21

PARTIALは完了/PASSではない。未測定のManaged境界へNOT_PROPAGATED等を先取りして付けない。

| ID | 現在の状態 | 根拠・未実施範囲 |
|---|---|---|
| V1 | PARTIAL | Hosted/Prompt/Toolboxの同一backend収集を実測。全E2E span集合は未完了 |
| V2 | PARTIAL | S5 8,192文字を正常実行しManaged spanのinput/output保存長を取得。送信値hash・Portal表示・他境界長は未照合 |
| V3 / V3b | PARTIAL | Managed Prompt spanにinput/output/content IDを実測。system instructions/tool定義の実値hash・未選択Tool比較は未完了 |
| V4 | PARTIAL | EasyAuth Browserで同一Conversation/Framework Session hashの5turn継続を実測。Foundry response/conversation/agent session/Framework Session/turn対応表の最終整理は未完了 |
| V5 | PARTIAL | Hosted applicationへcase到達。対象Catalog managed spanのcase/Conversation属性は記録なし |
| V6 | PARTIAL | 本文の仕様/source version欠落を再投入で解消し、実MCP応答で確認。ID/rank/score全fieldと正常E2Eの照合は未完了 |
| V7 | PARTIAL | Browser成功Traceで自動traceparent/baggage送信True、Web→Hosted親→Catalog/Code→両Toolbox→merge/responseは同一Trace。下流user.idはなく`NOT_PROPAGATED`、APIM/Search内部spanは`NOT_RECORDED_BY_PLATFORM`、完全parent chainは未取得 |
| V8 | PARTIAL | Azure自然負例でCode business/Search NOT_FOUNDと層別statusを実測。指定S2 profileのAzure検証は未完了 |
| V9 | PARTIAL | Azure S3 controlでattempt 1/2、retry、replan、WAITING_USER、終了後actionなしを実測。SD-03/05注入は未実施 |
| V10 | NOT_RUN_SCOPE | T4、DNS/route変更は不実施 |
| V11 | PARTIAL | Local content-off契約のみ。Managed evaluator挙動未測定、T1追加実験は対象外 |
| V12 | NOT_RUN_SCOPE | T2継続評価ruleの作成なし |
| V13 | PARTIAL | Browser成功Traceをexact `operation_Id`で64行のallowlist JSONLへexportし再読込。S4のcomplete/missing/ignored各Trace exportとevaluator入力は未実施 |
| V14 | PARTIAL | Local/設定のAlwaysOnのみ。実収集漏れ未照合、T2 sampling反復は対象外 |
| V15 | PARTIAL | UI/Hosted親はallowlist/content-offだがManaged Prompt子がcontentを保存。保護featureはRegisteredだがAppGenAIContent PATCHが反映されずGeneral相当/90日のまま。Synthetic以外を非記録にするPlatform設定は未確認 |
| V16 | NOT_RUN_SCOPE | T3 transformation DCRを作成しない |
| V17 | PARTIAL | Protected table適用を承認後に試行したがAPI読み戻しはGeneral相当。Privileged Monitoring Data Readerは付与せず、Reader/Privileged比較は未実施 |
| V18 | NOT_RUN_SCOPE | T2反復集計なし |
| V19 | NOT_RUN_SCOPE | T2費用実測なし。SKU/retentionなど費用要因のみ報告 |
| V20 / V21 | NOT_RUN_SCOPE | T4 private collector/AMPLS/Private Linkなし |

AzureのWeb/Hosted/Catalog/Code/両Toolbox/merge/response同一Trace IDはBrowser成功Traceで実測済み。App Serviceからのtraceparent / user.id baggage送信も実測した。traceparentは観測対象経路で継続したが、user.idはManaged境界で`NOT_PROPAGATED`。APIM/Search内部spanは`NOT_RECORDED_BY_PLATFORM`と区別する。
未実測項目をPASSにせず、取得後にNOT_PROPAGATED / NOT_RECORDED_BY_PLATFORM / NOT_SUPPORTEDを証拠に応じて区別する。
最終Review・commit/push・Squash Mergeは未実施。

## 続行事項

### Blob Indexerへの取込経路変更（11:54 UTC実測）

ユーザーの後続指示により既存Serverless Developerを継続利用。Free Search `rag-ais-02`は変更・削除なし。既存PoC Search/Index/Toolbox/Agentの削除・置換なし。

- 新規Storage: 対象RG内 `stprocurementobsnkjm`、West Central US、StorageV2/Standard_LRS/Hot。private container `procurement-catalog` / `procurement-code-master`、各 `documents.json`。共有キー/匿名アクセス無効、TLS1.2/HTTPS。Blob/コンテナーsoft delete 7日、稼働JSONの自動削除なし。
- 既存Searchにsystem MI `7df63982-ee5a-496a-b965-4f10b6206a14`を追加。各コンテナーへStorage Blob Data Reader、投入callerへ各コンテナーのStorage Blob Data Contributor（role assignment計4件）。Foundry/Toolboxのquery roleは変更なし。SearchMIへ書込権限なし。
- what-ifはStorage配下8 resourceのCreateのみ。既存resourceのModify/Deleteなし。Storage deployment Succeeded。
- Data source `procurement-catalog-blob-source` / `procurement-code-master-blob-source`、Indexer `procurement-catalog-blob-indexer` / `procurement-code-master-blob-indexer`を新規作成。ResourceIdのMI認証、jsonArray、document_id明示mapping、失敗許容0、scheduleなし。
- API 2026-04-01以前の一覧取得はページング必須400。公式2026-08-01-preview schemaのpageSize指定で200を確認。Indexer未対応ではない。
- 初回はqueryへファイル名を指定し仮想フォルダー扱いとなったため処理0件。PASS扱いせず、今回作成したData sourceだけをETag条件付きでquery解除し再実行。
- Catalog: 11:53:21.379 UTC完了、処理10/失敗0/エラー0/警告0。Code Master: 11:53:21.861 UTC完了、処理9/失敗0/エラー0/警告0。Blob read-back一致、全19 Index文書の全Repository projection一致。Push呼出しによる代用なし。
- 両Toolbox v1の実MCP検索がisError=false。Catalogの仕様/source_version/32GBとCode Masterのsource_version/DPT-DEV/account_codeを確認。親v4・子v2は変更不要だった。
- 追加費用: Blob計14,290 bytes＋操作。2026-09-03公開retail API: West Central US Hot LRS保存$0.0184/GB月、書込$0.05/1万回、読取$0.004/1万回。今回の少量・オンデマンド運用ではStorage分は月$0.01未満の概算（他サービス/税/契約価格除外）。SearchはPreview/SLAなし、公式tier資料の課金開始日は2026-09-13、以後CU/Index storage課金。
- Rollback: Indexer停止後に既存Push経路へ戻す。Storage/Indexの削除は自動実行しない。JSON配列の要素削除をSearchへ自動同期する処理は未実装。

根拠: [Serverless tier](https://learn.microsoft.com/en-us/azure/search/search-sku-tier?tabs=basic)、[Blob Indexer](https://learn.microsoft.com/en-us/azure/search/search-how-to-index-azure-blob-storage)、[Storage managed identity](https://learn.microsoft.com/en-us/azure/search/search-howto-managed-identities-storage)、[最新REST schema](https://github.com/Azure/azure-rest-api-specs/blob/main/specification/search/data-plane/Search/preview/2026-08-01-preview/search.json)。

Blob経路の成功はS1〜S5、V1〜V21、リアルタイムWebチャットの完了を意味しない。会話intake/進捗streamは後述の新APIM/Web v10でAzure配備・backend実測まで進めたが、再配備後Browser/EasyAuth送信は未確認。

### 対話・進捗のHosted直接実測（12:13 UTC開始）

上記未配備記載の後、Catalog Prompt v3とHosted親v5をimmutable versionとして配備しACTIVE確認。Hostedはsource ZIP/Python3.13/remote_build/CPU0.5/1Gi、追加必須envなし。Code子v2、Toolbox v1、モデルは変更なし。ZIP SHA256 `d12ea9a227e88db1c09a50e6fe73b32f833959105792dba264f233fea7ebd280`。

Case `CHAT-DIRECT-20260903121318`、Conversation `conv_0c74ef1238fb55f800tlzDFECvf2DysZZeJViQ7Q1aXCJuSNxK`、Framework Session hash `6479330057b99bcb5424038b201e249091fecb6da15f57ee9cbe0c3ea2d8014a`は両turnで一致。

| Turn | 実測結果 | 到達時間（要求開始から） |
|---|---|---|
| 1「ノートPCを購入したい」 | technical/MCP/Search/parse SUCCESS、business WAITING_USER、LAPTOP-DEV-14 / LAPTOP-OFFICE-13の2候補、draftなし。数量/申請者等を捏造しない | intake開始8.937秒、完了30.128秒、Catalog開始30.129秒、回答待ち50.895秒、終端51.273秒 |
| 2 選択＋架空情報追加 | 全status SUCCESS、draftあり | intake開始2.248秒、完了13.207秒、Catalog完了34.007秒、Code完了83.377秒、merge完了83.378秒、終端83.749秒 |

Response IDはturn1 `caresp_0c74ef1238fb55f800zi8Dr3Wprtq2pGUXue4vHXwzvb7Pn7R2`、turn2 `caresp_0c74ef1238fb55f800MdGHlz5gBDGyaCdm36xWIbZw8Ti5PYDn`。進捗と終端の受信時刻が異なり、事後要約ではない。親LLMは依頼抽出＋Planを1回で生成。ただしturn2のCode区間は49.370秒で、遅延解消/速度PASSとはしない。

Localでは3 turn（候補提示→ボタン選択だけ→不足情報補完）、不明商品選択拒否、必須queryなしの回答待ち、完全指定の成功後再開を検証。Framework History/serialize restore、進捗先行・並行run分離・pending cancelも検証。Hosted SDKのyield間切断は即時中断されない場合があり、180秒上限を設定。切断即時cancelは保証しない。

v5配備後に、完全指定で成功済みの依頼の次turnを不要な商品再選択待ちにしない条件補正をLocalへ追加した。この1行補正はLocal regression通過・Azure未配備。次のHosted配備時に含める。

Web新UIはLocal実装・表示確認まで。Browser plugin不在、Hallmark skill利用不可のため既存Playwright/Edgeで機能検証。1280x1000/390x844、候補選択/NDJSON parser/2 turn/再読込/新規会話、上部会話・下部入力欄、横overflowなし、console/page errorなしを確認。Azure Webへの新版配備は下記判断待ちで行っていない（稼働Webはv7のまま）。

### APIM ConsumptionのSSEサポートと切替

実resourceはConsumption、実policyはforward-request timeout=210、buffer-response=false。設定の見落としではなく、[公式SSE資料](https://learn.microsoft.com/en-us/azure/api-management/how-to-server-sent-events)でConsumptionは長時間接続のサポート対象外。直接Hostedの成功をApp Service→APIM→Hostedの保証に流用しない。

同じ対象RG/East USへSSE対応Developer APIMを追加し、実MI 3turnと配置済みWeb backendのSSEを確認して切り替えた。公開retail APIのDeveloper Unitは$0.0658/時（730時間で$48.03/月、税/契約価格除外）。Developerは非production・SLAなし。旧Consumptionは直近Requests 0、このPoC API 1件だけ、Webの新endpoint参照を確認後にsoft-deleteした。2026-09-06 01:13:20 UTCまで復元可能でpurgeは未実施。詳細は`docs/apim-streaming-cutover-2026-09-03.md`を参照。

同資料にv6のCode子Trace分岐の実測を追記した。親側Traceとmanaged Code側Traceは異なるが、`gen_ai.response.id`で一致する。同一Traceは`NOT_PROPAGATED`、代替相関は実測済み。全経路のTrace継続をPASSにしない。

S1〜S5 Azure Core/全V1〜V21/最終Review/Mergeは未完了。現時点でcommit/push/Review依頼はしていない。

### 新Developer APIM / Web v10実測（2026-09-04）

- `CHAT-WEBMI-20260904004800`: app containerの実MI→新APIM→Hosted。3turnで候補提示→選択のみの追加確認→不足情報補完、同一Conversation/Framework Session、最終draft生成。turn 1/2/3は56.834/33.578/104.414秒で、各turnの進捗は最終結果前に到着。
- Web deployment `bec7a99f-f95c-4d25-a7f9-4479cf5b915a`: v10 ZIP SHA256 `313b12f2998aee79d6de175d84bc882037b76bccec1b33ea03062c502c570359`。実行コンテナのbackend/JavaScript hash一致、uvicorn起動、EasyAuth匿名401を確認。
- 配置済みWeb localhost case `WEB-412fcb3a9ae73c14`: 署名cookie/CSRF/Conversation/SSE/Web MI/新APIMを通し、最初の進捗6.459秒、最終60.552秒、候補2件、technical/MCP/Search/parse SUCCESS、business WAITING_USER。localhostの架空principalであり、実ユーザーBrowser認証の証拠にはしない。
- Trace `0ea6b91c63359331457aa88fe6171281`: Web root `38ad4c5dc3edf162`、Responses client `e6f225af8bf81ce8`（parentはWeb root）、Hosted `a1ddcbacd7f81cf3`、Catalog proxy `1f870f0bc4fa24ea`まで同一Trace。WebのConversations create/update/Responses clientでtraceparent/baggage送信boolean=True。Hosted側user.idなし。
- Catalog managed trace `d44ae8fabc6c9edc4b34ec8f1c69052a`は親Traceと別で、Response ID `resp_07912587212c9163006a9a1aac106c8195aa82268a9d4f9c1e`が一致。同一Traceは`NOT_PROPAGATED`、Response ID相関は実測。APIM内部spanとSearch service内部spanは`NOT_RECORDED_BY_PLATFORM`、別Traceを架空接続しない。

配置済みWeb backendの同一cookie/Conversation 3turn case `WEB-e6b598f4be0f1140`も実行。turn 1/2/3は59.023/89.156/72.191秒、最初の進捗は1.326/0.685/0.639秒。turn 3は全status SUCCESSでCatalog→Code→mergeを完走した。Trace `7496a2d6ca630e3a7085b11099926055`ではApp Service root `cf45bf64f1b9bfaa`、Responses client `1b94c9dd1483b73a`、Hosted `225b6e6f67be3b51`、Catalog/Code managed span、両Toolbox、merge `4bbb358b912cfb73`、response `a37f6e8c79859fd1`を同一Traceで取得。APIM/Search service内部spanは取得されず、Web root以外のuser.idもない。localhostの架空principalでありBrowser/EasyAuth成功とは区別する。

S1 Healthy追加case `S1-DIRECT-20260904012844`はHosted v7で全status SUCCESS・draftあり。Trace `77180a2df691dd800b2cacaa306eac18`は33 spans、失敗0で、Hosted/Catalog/Code/両Toolbox/merge/responseを含む。一方、取得集合外parent参照14件があり、完全な木とはしない。以前の別Trace分岐と今回の同一Traceの両方を保持し、Platform伝播を一律保証しない。

### S5 content保存の実測とT3境界（2026-09-04）

`S5-DIRECT-20260904013919`は8,192文字のSynthetic入力で全status SUCCESS・draftあり。Trace `98622fa4bbc5a8b960f0d31a747d5a85`のManaged Prompt子には`gen_ai.input.messages`/`gen_ai.output.messages`が保存され、例としてCatalog/Code model spanのinput長17,094/20,116文字、output長1,827/2,410文字を値なしで取得した。Hosted定義の`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false`はManaged Prompt server-side tracingへ適用されない。

`protectGenAISensitiveData`はNotRegistered。`AppGenAIContent`は存在するが`protectionLevel=General`、retention 90日。公式資料上、Managed tracingはuser input/model output/tool dataを記録し得る。専用table routingとProtected化はアクセス制限であり非記録化ではないうえ、正本のT3追加scopeに当たるため未適用。Synthetic data以外を流す場合のprivacy blockerとして扱う。[Foundry trace security](https://learn.microsoft.com/en-us/azure/foundry/observability/concepts/trace-agent-concept)、[sensitive content table](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/traces-sensitive-content)、[protected tables](https://learn.microsoft.com/en-us/azure/azure-monitor/logs/protected-tables-configure)を参照。

最終Local回帰はPython 3.13で161 passed / 1 skipped / 2 deprecation warnings。Skipは既存Azure Core placeholderでありPASSへ変更していない。`git diff --check`、deployment/search assets静的検証、APIM/Web/Storage Bicep buildを確認。controller 691行、hosted 422行、進捗Middleware 71行、App Service backend 408行。Controllerはterminal result呼出しをlocal helperへ集約して714行から削減したが、600行未満の目安には未達。Trace/status contractとAgentSession対話stateを別fileへ移して見かけの行数だけを減らす変更は行っていない。

Trace照合・Toolbox→Search認可設定はユーザー承認済み。EasyAuth Browser 5 turnの架空チャット実行とTrace ID照合を完了し、UI表示だけでなく候補提示〜確定のCore flow成功を確認した。

Code Masterへのcontent field追加・文書再投入はユーザーの明示承認後に実施した。ETag条件付きPUTはHTTP 204で成功し、GET read-backで旧field定義がすべて同一・追加fieldがcontentだけであることを確認。204を失敗扱いしたscriptを修正し、再確認時はschema writeなし。Catalog 10件・Code Master 9件の再投入acceptedを確認した。document_projection_versionは2、source_versionは2026-09-01.1のまま。両Toolbox実MCP応答はisError=falseで、Catalogのsource_version/specifications_json/32GB/180000とCode Masterのsource_version/department_code/DPT-DEV/account_codeを確認。既存配備callerのroleを使用し、新resource/RBAC/SKU変更なし。費用差は検索可能本文分のindex storage/処理量（未計測）。非破壊rollbackは本文の利用停止・値のクリアであり、field自体の除去ではない。

再投入後の直接Hosted S1 `S1-DIRECT-20260903074842`（親v4）はtechnical/MCP/Search/parse SUCCESSだが、business VALIDATION_FAILED、reason_code catalog_specification_mismatch、draftなし。Conversation `conv_078b4d10cc5a3bee00ZAnbHmSdrnBxg7YzmmXYwieJFzZA1QCm`、Response `caresp_078b4d10cc5a3bee00WPhkzzEG74VBL9LgSkkXVQqHADO6JB7Z`。要求仕様と選択商品の表現差を調査中。正常S1およびWeb/EasyAuth E2E成功の証拠ではない。
同じ依頼のLocal Controller＋実Azure planner/子Agentではmemory=32GBが双方で一致しSUCCESS。失敗したHosted会話だけのstate read-backを試みたがHTTP500となり、当該失敗の仕様値は未取得。推測でvalidationを変更しない。
同一Hosted v4で再実行した`S1-DIRECT-20260903075323`はtechnical/business/MCP/Search/parseすべてSUCCESS、draftあり。Conversation `conv_06a6404e0a95df9800nomdwODPbuvy2JmMi12KQxv4Hm5wkzBw`、Response `caresp_06a6404e0a95df9800l4arfZXwK4M2KW7HzcGKFhCDRsbKmaFD`、Framework Session hash `f5781e6a263a2d39baf16eebb8007b99df4056a23fb883f03519f39b2b544df8`。直接Hostedでの正常1件であり、先行failureを除外した安定性PASS、S1〜S5 Core完了、Web/EasyAuth E2E成功とはしない。

## 新版Webの実送信header照合

実Web case `WEB-abc0dbe225a5a8c4`、07:34 UTC、Trace `701e47d92179cdfd160e160b4d680166`で38 spansを取得。Web root `5a37f047360ff78a`にuser.idあり。Responses HTTP client `9fbbbfc6c5361041`のparentはWeb rootで、`app.propagation.traceparent_matches_span=True`、`app.propagation.baggage_user_id_matches=True`。Conversation取得・更新の2 clientでも両方True。手動注入なし、raw traceparent/baggage値の重複記録なし。

Hosted plan.create `b253c58cda1d67b6`とresponse.generate `07e8f5af375697db`に同じConversation/caseがある。Catalog Prompt `11c9a6849c448de4`、Toolbox tools/call `004ec2b9b0a55736`も同じTrace ID。子のresponse IDで代替相関可能。Catalogまでの観測であり、Code/merge/Search service内部spanを取得済みとはしない。

一方、Hosted application/Catalog/Toolboxのuser.idは取得したspan属性にない。SDKの実TraceContextMiddlewareとアプリallowlistのLocal組合せではuser.id hashを抽出でき、未知baggageや不正user.idはアプリ属性へ入らない。Web送信は実証できたが、Hosted受信headerそのものは未観測なので、欠落位置をAPIM/Foundry/SDKのいずれかへ断定しない。user.idの全経路伝播はPARTIALでありPASSではない。

取得集合に存在しない16桁parent IDは8個あり、別Traceの結合や架空parent補完は行わない。Framework plannerの一部spanはgen_ai.conversation.idに内部resp_ IDを記録しており、アプリのFoundry Conversation IDと混同しない。Web/applicationのconv_ ID、case、remote response IDを相関の正本にする。

V13の取出し経路として`scripts/export_trace_evidence.py`を追加し、Trace `c876a5a2b4997bb2f44aaffb76829f7b`をexact IDで`.foundry/evidence/WEB-bc7c676157a2cf4c.jsonl`へ64行exportした。出力はspan相関、version、Toolbox/index、status等のallowlistのみで、raw Properties、本文、`user.id`、EasyAuth表示名を含めない。JSONL再読込でTrace ID 1件、case 1件、Conversation 1件、AppRequests/AppDependencies/AppTracesの3 tableを確認した。S4全variantのexportではないためV13全体はPARTIALとする。
根拠: [Search schema update / rebuild](https://learn.microsoft.com/en-us/azure/search/search-howto-reindex)。

根拠: [Hosted Conversations](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/manage-hosted-sessions)、[Search Tool setup](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/ai-search)、[Search RBAC](https://learn.microsoft.com/en-us/azure/search/search-security-rbac)。
