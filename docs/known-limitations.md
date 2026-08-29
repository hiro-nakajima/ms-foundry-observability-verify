# Known Limitations after the First Codex Task

確認日: 2026-08-29

## Review後へ延期した項目

| 項目 | 理由 | 影響 | 次のAction |
|---|---|---|---|
| PA-S / PA-M Managed Resource definition | ユーザー指定のReview gate | 4 logical pattern比較は未完成 | Review後にA2A/Managed Agent Toolのcurrent availabilityを再確認して実装 |
| Azure infra / deployment | Azure apply禁止、Resource情報未確定 | Azure runtime/Role/session persistenceは未検証 | Subscription、Region、Project、Model、App Insightsを確認後にBicep/azdを作成・検証 |
| 14 Failure Evaluator / E2E profiles | 次のFailure/Evaluation phase | 現在のfixtureはpositive 1、negative 1だけ | 14 case × Stage A/B、INJECTION_MISSED、88-run Matrixを追加 |
| Foundry Evaluator / report | Azure/Judge model未確定 | Local deterministic testのみ | Judge deployment決定後に独自Evaluatorと並列実行 |

## 現在の制約

- DevUIはentrypoint/Factory smokeとFramework Session再接続を自動test済みですが、browserでの手動UI操作は未実施です。
- `ResponsesHostServer`のclass/Factory smokeは成功しています。実ポート起動は、hostが初期化するAzure telemetry/IMDSの外部接続をsandboxで発生させないため未実施です。
- Local Deterministic Chat Clientはmodel-driven function callingを実装しないため、Agent Frameworkがcapability warningを出します。Plan & Execute harnessと実`as_tool()` streaming delegationはtest済みです。
- Agent Governance Toolkit 4.1.0の現行互換import pathからdeprecated warningが出ます。
- Hosted process再起動時の永続性はFramework Session storeに依存します。serialize/restoreはtest済みですが、Foundry-managed storeはAzure未接続です。
- `propagate_session=True`は安全性を証明していないため実装選択肢にしていません。
