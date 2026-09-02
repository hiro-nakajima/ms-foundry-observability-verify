# Core Observability validation report

検証日: 2026-09-01

Architecture: `procurement_application_v2`

Azure apply: 未実施
Data: version `2026-09-01.1` Synthetic only

## Local結果

- Python 3.13.13
- `pytest`: 112 passed / 1 skipped（Azure E2Eはapply未承認・Credential未指定のため理由付きSKIP）
- Search asset: catalog 10 documents、code master 9 documents、source version一致
- Deployment asset: Bicep compile PASS、`azd show --no-prompt`で5 split-serviceをparse、Azure environment未作成
- 独自Session/History、nested Session JSON、旧4構成selector: sourceから削除
- Stage A: 14/14 positive `DETECTED`、14/14 negative `NOT_DETECTED`
- Stage B: 実行済みcall/event/state artifactから導出した6/6が`DETECTED`、全注入runのouter technical status `SUCCESS`
- S1/S5 healthy control: 28/28 detector判定が`NOT_DETECTED`
- 特別状態: `INJECTION_MISSED`と`UNEVALUABLE_TRACE_INCOMPLETE`はSemantic集計外

## V1〜V21

| ID | 状態 | 確認内容・不足理由・次Action |
|---|---|---|
| V1 | PARTIAL | 親/子runtime別設定manifestとrunbookは完成。両runtimeの実TraceはAzure apply後に照合する。 |
| V2 | PARTIAL | Local exporter境界は8,192/32,768/65,536近傍を測定。App Insights格納長とPortal表示長は未測定。 |
| V3 | AZURE_PENDING | Prompt instructions version/hashは固定。Managed Traceに実値が記録されるかcontent-onで確認する。非記録なら`NOT_RECORDED_BY_PLATFORM`。 |
| V3b | NOT_RUN_SCOPE | Agent/Toolbox定義exportは存在。未選択Toolを含むManaged Trace比較はT1 triggerなしのため未実施。 |
| V4 | PARTIAL | Framework Session生成、業務turn、serialize/restore、2 Turn連続性はPASS。Platform conversation/Response/Trace対応表はAzure後。 |
| V5 | PARTIAL | `test.case.id`とStructured correlation契約はPASS。子server-side Spanで再設定できるかAzure後。 |
| V6 | PARTIAL | document ID/source version/rank/score fixtureとschemaはPASS。Toolboxが本文/rank/scoreを返す範囲はAzure実測後に確定。 |
| V7 | AZURE_PENDING | `FoundryAgent.as_tool()` proxy構成とcorrelation fallbackは実装済み。同一Trace/ParentSpanId伝播は実Azure必須。 |
| V8 | PARTIAL | 6 profileのMCP/Search/parse/business/status層分離はLocal PASS。4 Managed Toolbox profileはAzure後。timeout/protocol不正はLocal契約で完了。 |
| V9 | LOCAL_PASS | not-foundでattempt 1→2、retry、replan、`WAITING_USER`、終了条件を順序assert。 |
| V10 | NOT_RUN_SCOPE | T4未有効。DNS/routeの実Azure障害は作成・注入していない。 |
| V11 | NOT_RUN_SCOPE | content-off profileと非content detectorは実装。Evaluator別score実測はT1 triggerなし。 |
| V12 | NOT_RUN_SCOPE | T2未有効。continuous evaluation ruleを作成せず、PASS扱いにしない。 |
| V13 | PARTIAL | exact operation ID用KQLと手順は完成。Azure TraceのJSONL export/reloadはapply後。 |
| V14 | NOT_RUN_SCOPE | T2未有効。sampling反復と漏れ率reportは未実施。 |
| V15 | NOT_RUN_SCOPE | pre-record secret/CoT排除はLocal contract化。全境界のmask比較はT1 triggerなし。 |
| V16 | NOT_RUN_SCOPE | T3未有効。DCR transformationを変更していない。 |
| V17 | NOT_RUN_SCOPE | T3未有効。table RBACとPortal連動を変更・検証していない。 |
| V18 | NOT_RUN_SCOPE | T2未有効。単一runを集計検証と誤認せず、usage KQL反復は未実施。 |
| V19 | NOT_RUN_SCOPE | T2未有効。`_BilledSize`、retention、観測期間によるcost実測は未実施。 |
| V20 | NOT_RUN_SCOPE | T4未有効。親のprivate OTLP collectorとManaged子の送信先は変更していない。 |
| V21 | NOT_RUN_SCOPE | T4未有効。AMPLS/Private Link ingestionを変更していない。 |

## S1〜S5

| Scenario | 状態 | Local確認 | 未完了理由と次Action |
|---|---|---|---|
| S1 | LOCAL_PASS / AZURE_PENDING | catalog存在商品、grounded型番/価格/code、merge/validate、Framework Session restore、2 Turn、healthy control | 親/子server Trace、Session/Turn/Trace対応はAzure Core runで取得する。V12/V18はT2が有効になった場合だけ追加する。 |
| S2 | LOCAL_PASS / AZURE_PENDING | 6 failure profileのstatus分離、TV-02/TV-03検知 | Managed Toolboxの4 profileとinstructions/result fieldをAzureで確認する。Platform負結果は負の結論として閉じる。 |
| S3 | LOCAL_PASS | 再検索、attempt上限、replan、ユーザー確認、終了条件、SD-03/SD-05検知 | `test.case.id`付き実TraceをAzureで取得する。sampling反復はT2時だけ。 |
| S4 | LOCAL_PASS / AZURE_PENDING | complete/分類欠落/correlation欠落schema、MA-04/MA-05検知 | proxy/server Span関係とexact operation exportはAzureで実測する。 |
| S5 | LOCAL_PARTIAL / AZURE_PENDING | 10サイズの送信前切詰め位置、healthy control | ingestion/Portalの長さをAzureで測る。billing/cost反復はT2時だけ。 |

## 14 Failure Pattern

| Stage | 状態 |
|---|---|
| A positive/negative | SD-01〜SD-05、MA-01〜MA-06、TV-01〜TV-03の全14 contractがPASS |
| B S2 | TV-02、TV-03を`SUCCESS` runから検知 |
| B S3 | SD-03、SD-05を`SUCCESS` runから検知 |
| B S4 | MA-04、MA-05を`SUCCESS` runから検知 |
| Healthy | S1/S5で全14が`NOT_DETECTED` |

## 次Action

1. ユーザーへAzure変更一覧、3 identity、費用要因、rollback、commandを提示する。
2. 明示承認後だけwhat-if、RBAC、Search、Toolbox、Prompt Agent、Hosted親を順にapplyする。
3. Core MatrixをAzureで実行し、このReportの`AZURE_PENDING`を実測結果へ更新する。
4. T1〜T4はtriggerが明示された場合だけ別途提案・承認する。
