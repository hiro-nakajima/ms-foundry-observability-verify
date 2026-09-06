# Microsoft Foundry 購買申請Agent Observability PoC 検証結果

Snapshot: 2026-09-06 19:29 JST
仕様・Acceptance Criteriaの正本: [改訂Architecture/Observability検証計画](../revised-architecture-observability-validation-plan-2026-08-31.md)

本書は現時点の実測結果を要約する。旧4構成比較と88-run Matrixは復活させない。

## 配備状態

2026-09-06のread-only inventoryで対象subscription `d96eb8c2-2deb-4ed5-8cf2-f9fb178cb3ee`、対象RG `rg-ms-foundry-observability-verify`を再確認した。

| Component | 現行状態 |
| --- | --- |
| Foundry account/project | `observability-verify/proj-default`、East US 2、再利用 |
| Hosted親 | `procurement-parent-agent` v22、`ACTIVE`、source ZIP/remote build、SHA-256 `8bc17940787ef4193c616993657e5843d389010c2ba886dd7ceaf4fb56880562` |
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

今回の全contract testはPython 3.13で`180 passed / 1 skipped / 2 warnings`。追加のOAuth参考Web backend testは`8 passed / 2 subtests passed`。skipはAzure apply/資格情報を必要とするexternal placeholderでありPASSへ変更していない。

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
| S1 | PARTIAL | 直接Hosted、App MI、EasyAuth Browserの正常flowは成功。Healthy detectorのAzure照合は未完了 |
| S2 | PARTIAL | 自然負例でCode `DEPARTMENT_NOT_FOUND`、層別status、draftなしを確認。TV-02/03 injectionは未実施 |
| S3 | PARTIAL | 自然負例でattempt 1/2、retry/replan、WAITING_USER、draftなしを確認。SD-03/05 injectionは未実施 |
| S4 | PARTIAL | Browser成功Traceで完全handoff、v22で選択商品の仕様不一致を入力時に拒否。MA-04/05 injectionは未実施 |
| S5 | PARTIAL | Synthetic 8,192文字を正常完走し保存長を取得。全境界とHealthy detector照合は未完了 |
| Stage A | LOCAL PASS | 14/14 positive/negative contract |
| Stage B | AZURE_PENDING | 6 injection未実施。`INJECTION_MISSED`/trace incompleteをPASSにしない |

## V1～V21

| V-ID | 状態 | 要点 |
| --- | --- | --- |
| V1 | PARTIAL | Hosted/Prompt/Toolboxを同じbackendで収集。全E2E span集合は未完了 |
| V2 | PARTIAL | S5 8,192文字のManaged input/output保存長を取得。他境界未照合 |
| V3/V3b | PARTIAL | Managed Promptのinput/output/content IDを取得。instructions/tool全実値hashは未完了 |
| V4 | PARTIAL | Browserで同一Conversation/Framework Sessionの5turn継続。全ID対応表の最終整理は未完了 |
| V5 | PARTIAL | caseはHostedへ到達。対象Managed Catalog spanにcase/Conversation属性なし |
| V6 | PARTIAL | 実MCPで仕様/source versionを確認。rank/score等の全field照合は未完了 |
| V7 | PARTIAL | Web→Hosted→Catalog/Code→両Toolbox→merge/responseの同一Trace実測。user.idはManaged境界で`NOT_PROPAGATED`、APIM/Search内部spanは`NOT_RECORDED_BY_PLATFORM` |
| V8 | PARTIAL | Azure自然負例でCode business/Search NOT_FOUNDと層別status。指定S2 injection未完了 |
| V9 | PARTIAL | retry/replan/上限停止の自然負例。SD-03/05 injection未完了 |
| V10 | NOT_RUN_SCOPE | T4 private network/DNS/route変更なし |
| V11 | PARTIAL | Local content-off contract。Managed evaluator未測定 |
| V12 | NOT_RUN_SCOPE | T2継続評価ruleなし |
| V13 | PARTIAL | Browser成功Traceを64行allowlist JSONLへexport/reload。S4全variant未実施 |
| V14 | PARTIAL | Local/設定AlwaysOnのみ。実収集漏れの反復評価なし |
| V15 | PARTIAL | Web/Hostedはallowlist/content-off。Managed Prompt子はcontentを保存し得る。Protected applyは未反映 |
| V16 | NOT_RUN_SCOPE | T3 transformation DCRなし |
| V17 | PARTIAL | `AppGenAIContent`はGeneral相当/90日。privileged/non-privileged比較なし |
| V18 | NOT_RUN_SCOPE | T2反復集計なし |
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

## 代表的な会話回帰

- `CHAT-NAMECARD-20260904121318`: 名刺を1商品へ確定し、数量→部署→メモ→確定の5turnを完走
- `CHAT-NAME-V20-20260905005503`: 申請者名付き確認票、保存済みEvidenceによる1.478秒の即時確定
- `CHAT-QUERY-CHANGE-V21-20260905011706`: ノートPCから名刺へのquery変更時に旧Session候補を無効化
- `S4-SELECTED-SPEC-V22-20260905013922`: 32GB要求に16GB商品を選択すると入力時に`catalog_specification_mismatch`で拒否

## Platform制約・未検証

- Managed Promptのcontent保存をHosted側環境変数だけでは無効化できない。`AppGenAIContent` ProtectedのAPI applyは受理されたがread-backはGeneral相当/90日。Synthetic以外を流す前のprivacy blockerである。
- Stage B 6 injection、Azure Healthy detector照合、V-IDの未完了項目は未実測のまま。
- EasyAuth実ユーザー名はUI表示を許可したが、氏名/email/raw oidをcustom telemetryへ保存しない。
- Serverless Developerはpreview/SLAなし。現在の遅延の主因ではないが、scale-to-zeroのcold寄与は専用A/B未測定。
- Functions OBO参考経路とOAuth参考Web backendは本PoC E2E外で、Azure配備・Graph `/me`の再検証は未実施。

詳細evidenceは[Azure Observability検証記録](../azure-observability-validation-2026-09-03.md)と`.foundry/evidence/`を参照する。
