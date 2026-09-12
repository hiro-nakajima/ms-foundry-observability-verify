# Agent as Toolの登録と実行順

現在の購買親Agentに登録するToolは商品検索とコード決定の2つです。OBOは同じHostにある独立検証経路で呼び、購買親Agentのtoolsには登録しません。

| Tool | 組立 | 呼出し元 |
|---|---|---|
| `catalog_search_agent` | hosted.pyのFoundryAgent.as_tool(propagate_session=False) | Controllerのcatalog step |
| `code_determination_agent` | hosted.pyのFoundryAgent.as_tool(propagate_session=False) | Controllerのcode step |
| `obo_identity_agent` | identity.pyの内部Agent.as_tool(propagate_session=False) | hosted_app.pyの明示的本人確認分岐 |

## 購買の順序

[hosted.py](../../src/hosted-agent/procurement_agent/hosted.py)の`ControllerContextProvider.before_run` → `_execute_hosted_components` → [controller.py](../../src/hosted-agent/procurement_agent/controller.py)のController／PlanExecutorが制御します。tools配列への登録順で実行されるのではありません。

- 初回: intake／plan → Catalog → 必要な入力確認。
- 商品・数量・部署等が揃った段階: 保存済みCatalog根拠の再利用／検証 → Code → 確認応答。
- 確定: 保存済みCatalog／Codeの再検証・再利用 → merge.validate。観測のためだけに検索を再実行しない。
- 入力不足やTool失敗: 状態に応じて停止／確認待ち。後続Toolを無条件に実行しない。

`_invoke_remote_tool`はPydantic snapshotをtask JSONへ変換し、`FunctionInvocationContext`を使って`tool.invoke()`を呼びます。子へ親Session全体は共有しません。Framework Session、Foundry Conversation、Response IDは別の識別子です。

## OBOの順序

[hosted_app.py](../../src/hosted-agent/procurement_agent/hosted_app.py)で最新user入力を判定し、本人確認なら[identity.py](../../src/hosted-agent/procurement_agent/identity.py)の`invoke_identity`を呼びます。固定引数lookup → 内部Agent Tool → Toolboxが公開するwhoami FunctionTool → Functions OBO／Graphという順です。

Toolboxのremote名とmetadataを保持するため、SDKが公開したFunctionToolを呼びます。同意が必要ならoauth_consent_requestでWebへ戻し、同意後に同じ質問を再送します。名前は本人確認への応答だけに使い、購買Controllerや購買状態へ渡しません。

移植方法は[OBO移植ガイド](hosted-obo-userid-porting.md)。OTelだけの移植では既存のExecutor・Tool順序を維持し、[最小例](examples/minimal_agent_tool_otel.py)で業務境界を囲めばよく、Bundleの導入は不要です。
