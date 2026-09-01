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
