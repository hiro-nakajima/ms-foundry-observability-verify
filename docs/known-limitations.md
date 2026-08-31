# Known Limitations after the First Codex Task

確認日: 2026-08-31

## Review後へ延期した項目

| 項目 | 理由 | 影響 | 次のAction |
|---|---|---|---|
| PA-S / PA-M Managed Resource definition | ユーザー指定のReview gate | 4 logical pattern比較は未完成 | Review後にA2A/Managed Agent Toolのcurrent availabilityを再確認して実装 |
| Azure infra / deployment | Foundry Projectとmodelはユーザー作成済みだがAgent deploymentは未承認・未実施 | Azure runtime/Role/session persistenceとApplication Insightsへのexportは未検証 | 既存Resourceを参照するBicep/azdとHosted Agent definitionを作成・validate後、apply承認を得る |
| 14 Failure Evaluator / E2E profiles | 次のFailure/Evaluation phase | 現在のfixtureはpositive 1、negative 1だけ | 14 case × Stage A/B、INJECTION_MISSED、88-run Matrixを追加 |
| Foundry Evaluator / report | Agent用`gpt-5-mini`は利用可能だがEvaluatorとreportは未実装 | Local deterministic fixtureのみ | Judgeの独立性要件を決め、Foundry batch evaluationと独自Evaluatorを実装 |

## 現在の制約

- DevUI entrypoint/Factory smoke、Framework Session再接続、Fake Chat Clientを使うHA-S / HA-Mの自然言語複数Turn、部門候補選択、確定前変更、明示的な`確定`は自動Test済みです。実Azure OpenAIではAPI E2Eを確認しましたが、Edge上のDevUI表示確認は未実施です。
- 自然言語受付と計画生成はAzure OpenAI Chat Clientの`ProcurementTurnExtraction(BaseModel)` / `AgentPlanResponse(BaseModel)` Structured Outputを使用します。`gpt-5-mini` version `2025-08-07`で単発Smoke、同一Planの部門曖昧性解消、Draftから`確定`までを確認済みです。content filterのnegative caseと負荷時latencyは未検証です。
- 実model E2Eでは`reasoning=minimal`で約5秒の単発Smokeでした。各Invocationは90秒でtimeoutしますが、retry/backoffとユーザー向けtimeout応答は次Taskです。
- Local/PoCは`DefaultAzureCredential`を使用します。Azure apply前にHosted用Managed Identityと、`ManagedIdentityCredential`へ限定するProduction認証方針を確定する必要があります。
- `ResponsesHostServer`のclass/Factory smokeは成功しています。実ポート起動は、hostが初期化するAzure telemetry/IMDSの外部接続をsandboxで発生させないため未実施です。
- Local Deterministic Chat Clientはmodel-driven function callingを実装しないため、Agent Frameworkがcapability warningを出します。Plan & Execute harnessと実`as_tool()` streaming delegationはtest済みです。
- Agent Governance Toolkit 4.1.0の現行互換import pathからdeprecated warningが出ます。
- Hosted process再起動時の永続性はFramework Session storeに依存します。serialize/restoreはtest済みですが、Foundry-managed storeはAzure未接続です。
- `propagate_session=True`は安全性を証明していないため実装選択肢にしていません。
