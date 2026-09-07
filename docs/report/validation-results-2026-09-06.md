# Microsoft Foundry 購買申請Agent Observability PoC 検証結果

Snapshot: 2026-09-07
仕様・Acceptance Criteriaの正本: [改訂Architecture/Observability検証計画](../revised-architecture-observability-validation-plan-2026-08-31.md)

本書は現時点の実測結果を要約する。旧4構成比較と88-run Matrixは復活させない。

## 配備状態

2026-09-06のread-only inventoryで対象subscription `d96eb8c2-2deb-4ed5-8cf2-f9fb178cb3ee`、対象RG `rg-ms-foundry-observability-verify`を再確認した。

| Component | 現行状態 |
| --- | --- |
| Foundry account/project | `observability-verify/proj-default`、East US 2、再利用 |
| Hosted親 | `procurement-parent-agent` v28、`ACTIVE`、source ZIP/remote build、SHA-256 `c9eba9c0456f822666da261db83a3f2dee1955fdd3451317a483d9b50d549b7c` |
| Catalog Prompt子 | `catalog-search-agent` v4、`ACTIVE` |
| Code Prompt子 | `code-determination-agent` v2、`ACTIVE` |
| Toolboxes | `catalog-search-toolbox` v1、`code-master-toolbox` v1 |
| Search | `srch-procurement-observe-nkjm`、Serverless Developer、West Central US |
| Storage | `stprocurementobsnkjm`、Standard_LRS/Hot、West Central US |
| App Service | `web-procurement-observe-nkjm`、B1 plan、Sweden Central、EasyAuth/system MI |
| APIM | `apim-procurement-stream-nkjm`、Developer、East US、SSE経路 |
| Observability | Application Insights + Log Analytics、Sweden Central |
| ACR | 使用なし。Hostedはsource ZIP deployment |

今回取り込む`functions-mcp-selfhosted`とOAuth参考`server.py`は別途検証用sourceであり、上表の購買E2Eには配備していない。

## Local contract

今回の全contract testはPython 3.13で`198 passed / 1 skipped / 2 warnings`。skipは明示的なAzure deployment/credential gateを必要とするexternal E2Eであり、未実行をPASSへ変更していない。Azure runnerは同じcontractをv24/v27へ別途実行し、後述の安全な結果manifestとTrace evidenceを保存した。

- Stage A: 14 Failure Patternのpositive/negative contract 14/14を維持
- Stage B: S2 `TV-02/TV-03`、S3 `SD-03/SD-05`、S4 `MA-04/MA-05`の6 injectionを維持
- S1/S5: Healthy controlを維持
- `INJECTION_MISSED`と`UNEVALUABLE_TRACE_INCOMPLETE`を分離
- Framework AgentSession serialize/restore、HistoryProvider、Prompt子へのsession非共有を維持
- Search grounding、status層分離、content-on/off、Secret/CoT/PII非記録contractを維持

最初のsandbox内実行ではloopback socketが禁止されWeb fixture 13件がsetup errorになった。コード失敗とは扱わず、loopbackを許可した同一commandの再実行で上記結果を確認した。

## Search/Indexer再照合

2026-09-06 10:28:58 UTCにRepository JSONと既存Blob/Indexer/Indexをread-onlyで再照合した。

| Index | Indexer | 処理/失敗 | Index文書数 | Repository projection |
| --- | --- | ---: | ---: | --- |
| `procurement-catalog-v1` | `procurement-catalog-blob-indexer` | 11 / 0 | 11 | MATCH |
| `procurement-code-master-v1` | `procurement-code-master-blob-indexer` | 10 / 0 | 10 | MATCH |

両Indexerはstatus `success`、error 0、warning 0。source versionは`2026-09-04.1`、document projection versionは`2`。

データフローは次の1本である。

`data/*.json` → deterministic document生成 → private Blob JSON array → managed-identity Blob Indexer → 2 Search index → 2 Azure AI Search Toolbox tools → 2 Prompt子 → Hosted親

## Azure Core Matrix

| Scope | 状態 | 実測範囲と未完了 |
| --- | --- | --- |
| S1 | PARTIAL | v24実Prompt/Toolbox/Search経路を正常完走し、全14 detectorが`NOT_DETECTED`。既存EasyAuth Browser正常flowも成功。Core表が指定するcontent-on 2回はPlatform制約により未実施 |
| S2 | PASS | 自然負例の層別statusに加え、TV-02/TV-03を実Prompt/Toolbox/Search経路で注入。両方`injection_activated=true`かつ`DETECTED` |
| S3 | PASS | retry/replan/上限停止controlに加え、SD-03/SD-05を注入。両方`injection_activated=true`かつ`DETECTED` |
| S4 | PASS | 完全handoff/仕様不一致controlに加え、MA-04/MA-05を注入。両方`injection_activated=true`かつ`DETECTED` |
| S5 | PARTIAL | v27で128/8,192/32,768/65,536/65,537文字を各1回正常完走し、各14 detectorが`NOT_DETECTED`。Application Insightsではproperty 8,192文字、message 32,768文字の格納境界と切詰め位置をhash照合済み。Foundry Portal表示長は未確認 |
| Stage A | LOCAL PASS | 14/14 positive/negative contract |
| Stage B | AZURE PASS | v24で6/6 injectionを検知。S1/S5は各14/14 `NOT_DETECTED`。`INJECTION_MISSED`/`UNEVALUABLE_TRACE_INCOMPLETE`との分離を維持 |

Azure run `AZURE-CORE-20260906131540`は8/8成功した。各Evaluator spanは`detector_version=1.0`、`trace_complete=true`を持ち、6 injectionは`DETECTED`、2 Healthy controlは`NOT_DETECTED`としてApplication Insightsへ記録された。各Traceは51〜87行、観測されたend-to-end時間は35.104〜78.420秒だった。8 Traceの`AppRequests`/`AppDependencies`集計ではHTTP失敗0、model span 25、input 204,357 token、output 63,389 token、detector hit 6を取得した。tokenはnested multi-agent callを含むspan合計であり、1 turnの一意課金量とは扱わない。

通常経路の回帰`S1-DIRECT-20260907004109`をsynthetic validation metadataなしでv24へ1回実行した。Trace `77734b98d6b84a8f3fa3508c5979464c`、Conversation `conv_0254ed346813a2f000wgtRVeFJdTcVOsoxkigVn59YrVYSl27Y`で、`technical=SUCCESS`、`business=WAITING_USER`、MCP/Search/parseはいずれも`SUCCESS`だった。同一TraceにCatalog Prompt/Toolboxを取得し、validation profile/injection属性は空、`semantic.evaluate`は0件であり、検証gateが通常会話へ作動していないことを確認した。

S5境界run `AZURE-CORE-S5-BOUNDARY-20260907010100`はv25で5/5のAgent処理とHealthy detector判定に成功した。対象は128、8,192、32,768、65,536、65,537文字で、各Traceは68〜72行、各`semantic.evaluate`は記録済みである。一方、rawをsynthetic `X`に限定した`content.boundary.measure`は5 Traceすべて0件で、test caseと時間範囲を使った別Trace検索でも見つからなかった。格納長を推測で補完せず、V2/S5をPARTIALのままとする。

v26では境界span内に数値eventを追加し、128文字だけをpreflightした。Trace `34375648021e3f367bfca2d1c2998e41`の全48行と`semantic.evaluate`はingestionされたが、境界spanは再び0件だった。またCatalog子の`child_output_schema_invalid`により`retrieved_contexts`が欠落し、Detector結果は`UNEVALUABLE_TRACE_INCOMPLETE`である。残り4件は開始せず停止した。Managed `gen_ai.input.messages`は全サイズで51文字のredacted placeholderであり、境界測定の代替には使用できない。

v27では既にbackendへ記録される`semantic.evaluate`上に、固定Synthetic `X`だけを載せるproperty/messageイベントを追加した。preflightの128文字が両channelで長さ/hash一致した後、残る4サイズを実行した。run `AZURE-CORE-S5-BOUNDARY-20260907012834`と`AZURE-CORE-S5-BOUNDARY-20260907013019`は5/5のAgent処理と各14 detectorを正常完走した。Application Insightsの格納結果は次のとおりである。生payloadはevidenceへ保存していない。

| 送信文字数 | property格納 | message格納 | 判定 |
| ---: | ---: | ---: | --- |
| 128 | 128 | 128 | 両方hash一致、切詰めなし |
| 8,192 | 8,192 | 8,192 | 両方hash一致、切詰めなし |
| 32,768 | 8,192 | 32,768 | propertyは8,192で切詰め、messageはhash一致 |
| 65,536 | 8,192 | 32,768 | property/messageとも各上限で切詰め |
| 65,537 | 8,192 | 32,768 | property/messageとも各上限で切詰め |

切詰め後のhashは固定Xの先頭8,192/32,768文字のhashと一致した。全channelは同じ`semantic.evaluate`のParentId配下で記録され、Evaluator入力の判定fieldは欠落していない。別途backendの主要span/event件数を照合すると、5 TraceすべてでCode、merge、response、Evaluator、両境界eventを取得した一方、Catalogの`plan.step.execute`は4/5 Traceで0件、残る1 Traceで3件だった。Agent resultのSearch evidenceが完全でもbackend span集合は完全とは扱わず、4件を`NOT_RECORDED_BY_PLATFORM`とする。Foundry Portal表示段階も自動確認していないため、V2/S5全体はPARTIALを維持する。

| Scenario/Profile | Trace ID | 判定 | Trace時間 |
| --- | --- | --- | ---: |
| S2 / TV-02 | `2e83ef5b3f1c96764f9a48050dac3873` | DETECTED | 65.665秒 |
| S2 / TV-03 | `97ee70232e7ee7ee8d717e9afd947db6` | DETECTED | 78.420秒 |
| S3 / SD-03 | `87a66d44c89380659bc95e128f81788a` | DETECTED | 67.913秒 |
| S3 / SD-05 | `1750337a5d4fe19dae75575c5946759f` | DETECTED | 35.104秒 |
| S4 / MA-04 | `093922446d0a840224bd7f363d39a622` | DETECTED | 41.651秒 |
| S4 / MA-05 | `da749e366d8856ae42d08d57a5d8932e` | DETECTED | 60.828秒 |
| S1 Healthy | `865bb6c137d0c4f49b6bb49ec13e98a9` | 14/14 NOT_DETECTED | 38.227秒 |
| S5 Healthy | `5cc81459dcbc2cc2ad7ef272e86b1b41` | 14/14 NOT_DETECTED | 49.062秒 |

## V1～V21

| V-ID | 状態 | 要点 |
| --- | --- | --- |
| V1 | PARTIAL | Hosted/Prompt/Toolbox/Evaluatorを同じbackendで収集。runごとに一部managed spanが記録されないため全E2E span集合は未完了 |
| V2 | PARTIAL | v27で5サイズの送信長/hash、App Insights property 8,192文字/message 32,768文字の格納上限と最初の切詰め位置を実測。Foundry Portal表示長が未確認のためFULL PASSにはしない |
| V3/V3b | PARTIAL | Managed Promptのinput/output/content IDに加え、v24 Evaluatorで実system prompt/tool definitionのhash/lengthをcontent-off記録。未選択toolのPlatform記録比較は未完了 |
| V4 | PARTIAL | Browserで同一Conversation/Framework Sessionの5turn継続。全ID対応表の最終整理は未完了 |
| V5 | PARTIAL | caseはHostedへ到達。対象Managed Catalog spanにcase/Conversation属性なし |
| V6 | PARTIAL | 実MCPで仕様/source versionを確認。rank/score等の全field照合は未完了 |
| V7 | PARTIAL | Web→Hosted→Catalog/Code→両Toolbox→merge/responseの同一Trace実測。user.idはManaged境界で`NOT_PROPAGATED`、APIM/Search内部spanは`NOT_RECORDED_BY_PLATFORM` |
| V8 | PASS | Azure自然負例のCode business/Search NOT_FOUNDと層別status、およびTV-02/TV-03の注入・検知を確認 |
| V9 | PASS | retry/replan/上限停止control、およびSD-03/SD-05の注入・検知を確認 |
| V10 | NOT_RUN_SCOPE | T4 private network/DNS/route変更なし |
| V11 | PARTIAL | v24のcontent-off実行で非content属性Evaluatorが6検知/Healthy 28非検知を返した。Foundry標準content依存Evaluatorとの比較は未実施 |
| V12 | NOT_RUN_SCOPE | T2継続評価ruleなし |
| V13 | PARTIAL | Browser成功Traceを64行allowlist JSONLへexport/reload。S4全variant未実施 |
| V14 | PARTIAL | v24の8/8でEvaluator spanを取得したが、個別managed spanの欠落を確認。T2の20回以上のsampling比較は未実施 |
| V15 | PARTIAL | Web/Hostedはallowlist/content-off。Managed Prompt子はcontentを保存し得る。Protected applyは未反映 |
| V16 | NOT_RUN_SCOPE | T3 transformation DCRなし |
| V17 | PARTIAL | `AppGenAIContent`はGeneral相当/90日。privileged/non-privileged比較なし |
| V18 | PARTIAL | 8 runでlatency、HTTP失敗、model span、input/output token、business/technical status、detector hitをKQL集計。Dashboard比較とT2反復は未実施 |
| V19 | NOT_RUN_SCOPE | T2費用実測なし。費用要因のみ記録 |
| V20 | NOT_RUN_SCOPE | T4 private collector/AMPLSなし |
| V21 | NOT_RUN_SCOPE | T4 Private Linkなし |

## Trace/Identity相関

Browser core success `WEB-bc7c676157a2cf4c`、Trace `c876a5a2b4997bb2f44aaffb76829f7b`では、App Service root、Foundry HTTP client、Hosted、Catalog/Code、両Toolbox、merge、responseを同一Traceで取得した。

- App Serviceのoutgoing `traceparent`はHTTP client spanと一致: PASS
- `gen_ai.conversation.id`: Web/Hosted correlationで取得: PARTIAL
- Framework Session ID hash/turn/test.case.id: 取得: PASS（対象case）
- 仮名化`user.id` baggage: App Service送信はPASS、Managed下流は`NOT_PROPAGATED`
- APIM internal span/Search service internal span: `NOT_RECORDED_BY_PLATFORM`
- Managed Promptが別Traceになるcase: response IDで代替相関、同一Traceへ見せかけない

Stage Bはdirect Foundry validationであるためApp Service server/client spanを実行scopeに含めない。8 TraceではHosted application span、実Prompt子、Toolbox MCP、response、`semantic.evaluate`を同一Trace IDで相関し、Conversation IDは各Traceで1件に一意だった。direct caller側rootはApplication Insightsへ送っていないためworkspace内rootは`NOT_RECORDED_BY_PLATFORM`、App Service rootは`NOT_RUN_SCOPE`とする。v27 S5 runではAgent resultのCatalog Search evidenceは取得したが、Catalogの`plan.step.execute` custom spanは4/5 Traceでbackendに記録されず、`NOT_RECORDED_BY_PLATFORM`とした。

## 代表的な会話回帰

- `PLAYGROUND-CANDIDATES-20260907015643`: Playground相当の`web-json-v1`なしで「ノートPCを購入したい」を実行。v28はJSONではなく、Search根拠付き2候補の商品名・商品コード・単価と、WebAppボタンと同じ商品コード選択文を自然言語で返した。同じConversationで表示されたコードを選ぶと候補を再検索せずAgentSessionから数量stepへ進んだ
- `CHAT-NAMECARD-20260904121318`: 名刺を1商品へ確定し、数量→部署→メモ→確定の5turnを完走
- `CHAT-NAME-V20-20260905005503`: 申請者名付き確認票、保存済みEvidenceによる1.478秒の即時確定
- `CHAT-QUERY-CHANGE-V21-20260905011706`: ノートPCから名刺へのquery変更時に旧Session候補を無効化
- `S4-SELECTED-SPEC-V22-20260905013922`: 32GB要求に16GB商品を選択すると入力時に`catalog_specification_mismatch`で拒否

## Platform制約・未検証

- Managed Promptのcontent保存をHosted側環境変数だけでは無効化できない。`AppGenAIContent` ProtectedのAPI applyは受理されたがread-backはGeneral相当/90日。Synthetic以外を流す前のprivacy blockerである。
- Stage B 6 injectionとS1/S5 Healthy detector照合は完了。S1 content-on 2回、S5のFoundry Portal表示境界、T1〜T4に属するV-IDは未実測のまま。
- v27 S5境界はApp Insights格納値を5サイズ・2channelで実測し、property 8,192文字/message 32,768文字の切詰めを確定した。Foundry Portal表示長は未確認。
- v27 S5のbackend収集ではCode/merge/response/Evaluator/境界eventは5/5、Catalog `plan.step.execute`は1/5 Traceだけで記録された。Agent result上のSearch evidenceとbackend span完全性を分け、欠落4件は`NOT_RECORDED_BY_PLATFORM`とする。
- v26のevent付き境界spanも未記録。preflight自体も子schema不正で`UNEVALUABLE_TRACE_INCOMPLETE`となり、追加4runは実行していない。
- v24の通常Hosted直接回帰は完了した。EasyAuthを通るv24 Browser回帰は、Computer Use helperがWSL cwdを受理できず未実行。既存Browser成功Traceをv24の実測として読み替えない。
- EasyAuth実ユーザー名はUI表示を許可したが、氏名/email/raw oidをcustom telemetryへ保存しない。
- Serverless Developerはpreview/SLAなし。現在の遅延の主因ではないが、scale-to-zeroのcold寄与は専用A/B未測定。
- Functions OBO参考経路とOAuth参考Web backendは本PoC E2E外で、Azure配備・Graph `/me`の再検証は未実施。

今回追加したAzure側の固定費resource/RBACはない。Hosted v23/v24/v25/v26/v27/v28のimmutable source ZIP versionと、既存model/Search/Application Insightsを使った29回の検証呼出しが追加費用要因である。v23は評価属性欠落、v25/v26は境界span未記録の診断run、v27はApp Insights境界確定run、v28はPlayground候補表示回帰で、Stage Bの最終証跡はv24である。Storage Account、Search、Toolbox、Prompt Agent、App Service、APIMは既存構成を再利用した。

詳細evidenceは[Azure Observability検証記録](../azure-observability-validation-2026-09-03.md)と`.foundry/evidence/`を参照する。
