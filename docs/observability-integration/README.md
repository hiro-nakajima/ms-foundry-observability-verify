# オブザーバビリティ統合ガイド

現在の構成はWeb → APIM → Hostedです。Hostedの通常購買はPlan & Executeで商品／コード検索Agent Toolを呼び、明示的な本人確認は独立OBO経路からFunctions／Graphを呼びます。Web独自のidentity metadata、購買前のOBO、OBO名の購買への転記は廃止しました。

## 移植するもの

| 対象 | 最小の組込み箇所・資料 |
|---|---|
| Web全体を再利用 | [Web README](../../src/webapp-foundry-oauth/README.md)。必要な環境変数、EasyAuth、接続先を移植先へ合わせる |
| Functions全体を再利用 | [Functions README](../../src/functions-mcp-selfhosted/README.md)。MCP API／OAuth client／Graph permissionを確認 |
| 異なるPlan & ExecuteへOTelだけ追加 | [最小Python例](examples/minimal_agent_tool_otel.py)。Host初期化＋実際のPlan／各stepをobservedで囲む |
| 商品／コード検索をAgent as Toolへ変更 | [呼出し順と移植単位](hosted-agent-as-tool.md) |
| OBO検証入口を追加 | [OBO・user.id移植](hosted-obo-userid-porting.md)と[独立したPython抜粋](examples/hosted_obo_userid.py) |
| このHosted全体を配布 | [Hosted README](../../src/hosted-agent/README.md) |

## OTelの責務

1. HostのProvider／Exporterは起動時に一度初期化する。Hostedでは`TelemetryRecorder.for_hosted_runtime()`で共有する。
2. SDKが作るAgent／Chat／Function／MCP Spanを重複生成しない。
3. `plan.create`、`plan.step.execute`、`merge.validate`、`response.generate`を実際の処理で囲む。評価機能を使わない場合は`semantic.evaluate`等を移植する必要はない。
4. 別サンプルがexecutorのContextProviderで動いていても、その構成を維持できる。HostedAgentBundleは組立用であり、OTelの要件ではない。
5. 例外本文、Token、生claims、氏名をSpanへ出さない。メールbaggageだけは利用者指定で伝播・表示する。

## user.idと相関

WebはEasyAuthのメールをbaggageへ設定する。OBOは必要ない。Webの所有者判定／SpanとFunctionsのuser.idはハッシュを維持し、Hostedは受信できたメールbaggageを観測属性へ採用する。これらを本人認証に利用しない。

2026-09-12の直接Foundry検証では、メールbaggageはHostedの業務Spanへ記録されなかった。入力を受信するコードと、マネージド境界を越えて到達することは別に確認する。欠落時はTrace／Conversation／Response IDで相関し、独自identity metadataで補完しない。

## 検証資料

[Web変更検証](webapp-refactor-validation-20260912.md)／[Hosted・OBO変更検証](hosted-refactor-validation-20260912.md)。古い契約・ソース行番号／hashは[trash](../trash/README.md)へ移動した。新規移植には上記の現行ガイドを使用する。
