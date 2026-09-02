# 改訂Architecture実装メモ

正本は`revised-architecture-observability-validation-plan-2026-08-31.md`である。現行実装は`procurement_application_v2`の単一構成だけを提供する。

- 親: Microsoft Agent Framework Hosted Agent
- 子: Foundry Agent Serviceへ登録するPrompt Agent 2つ
- 代理呼出し: `FoundryAgent.as_tool(propagate_session=False)`
- Session: Framework `AgentSession`だけ
- 業務state: `procurement.execution.v2`
- Data: Azure AI Searchを使うFoundry Toolbox MCP。Localではrecorded MCP fixture
- Trace: Framework標準Span + 4つの業務custom span
- Evaluator: 新構成の14 Failure Pattern

独自History/Session、子Agent実体のcontainer内実装、旧4構成selector、88-run Matrixは削除した。

## Framework拡張の境界

公開するHosted/DevUI親AgentにはFramework標準の`ContextProvider`を継承した
`ControllerContextProvider`を登録する。Agent Frameworkには購買Domain固有の
catalog → code → merge/validate順序、grounded evidence検証、再試行終了条件を
実行する標準機能がないため、このdispatchだけを独自実装として残す。Providerは
会話履歴やSessionを保持せず、同じFramework `AgentSession`の業務stateをControllerへ
渡し、検証済み`ScenarioResult`を当該Invocationへ注入する範囲に限定する。

contract testは`tests/unit/test_hosted_factory_v2.py`で、Hosted/DevUIが公開する
`bundle.parent.run()`からController、2つの`FoundryAgent.as_tool()` proxy、
`propagate_session=False`まで到達することを検証する。順序・boundary・再試行・
status分離は`tests/integration/test_core_scenarios_v2.py`で固定する。

Hosted/DevUIの業務custom spanはrequestごとのprivate exporterを作らず、hostが構成する
global OpenTelemetry providerへ送る。Local envelope/Detector testだけは独立した
in-memory providerを明示利用する。Stage BのFault Profileは
`trace_pipeline.stage_b.StageBInjectionHarness`に限定し、実際の子呼出し、boundary
reject、terminal後action、誤った受理を発火させる。Detector入力は注入値を直接設定せず、
そのrunのcall/event/state artifactから`derive_trace_facts()`で導出する。
