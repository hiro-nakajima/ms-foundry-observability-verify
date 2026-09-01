# 新しいCodex Task用メッセージ

以下の本文を、新しいCodex Taskの最初のUser messageとして使用する。

---

あなたは、このRepositoryでMicrosoft Foundry購買申請AgentのObservability PoCを改訂Architectureへ移行し、実装・検証する担当者です。

最初に次の資料を全文読み、Architecture、責務、検証範囲、Acceptance Criteria、実装順序の正本として扱ってください。

```text
docs/revised-architecture-observability-validation-plan-2026-08-31.md
```

旧資料も背景確認のため読んでよいですが、相反する場合は改訂資料を優先してください。旧HandOffのPrompt/Hosted × Single/Multiの4構成比較と88-run Matrixは今回のDone Definitionから除外します。14 Failure Patternは除外せず、Trace/Evaluator仕様として改訂資料7.1.3の新構成へ読み替えて実装してください。

## 最初に行うこと

1. Repository内の`AGENTS.md`、README、改訂資料、既存設計、既存コード、requirements、lockfile、git status、git branch、remoteを確認する。
2. 未commit変更とユーザー作成fileを特定し、上書きや破棄をしない。
3. 現行実装と改訂Architectureとの差分を、file/class/test単位で一覧化する。
4. Microsoft Agent Framework、Microsoft Foundry Agent Service、Foundry Toolbox、Azure AI Search、Observabilityの採用APIを公式資料とインストール済みVersionのsignatureで確認する。
5. 実装Planを提示してから変更を開始する。

質問は、回答によってArchitecture、Azure Resource構成、費用、権限が大きく変わるBlocking事項だけにしてください。改訂資料にDefaultや方針がある項目はそのまま採用して進めてください。

## 実装するArchitecture

- 購買申請Agentは1つのE2E構成だけとする。
- 親はMicrosoft Agent Frameworkで実装するHosted Agentとする。
  - 自然言語依頼を解釈する。
  - Pydantic `BaseModel`と`response_format`で機械可読な`ExecutionPlan`を生成する。
  - Planを保存し、catalog → code → merge/validateの順序をControllerで保証する。
  - 空、parse不能、必須Step欠落時には安全な既定Planを使用する。
- 子はFoundryのPrompt-based Agent 2つとする。
  - `catalog_search_agent`
  - `code_determination_agent`
- Hosted親には、登録済みPrompt Agentを参照する`FoundryAgent` proxyを置き、`FoundryAgent.as_tool(propagate_session=False)`で呼び出す。
- 子Agent実体をHosted containerへ含めない。
- 親Sessionを子へ共有せず、必要情報だけをPydanticで検証したStructured snapshotとして渡す。

## Microsoft Agent Framework優先

Frameworkに同等機能がある場合は独自実装を作らず、Framework標準機能を使用してください。

- 会話履歴は`InMemoryHistoryProvider("procurement-history", load_messages=True)`を明示登録する。
- Sessionは`agent_framework.AgentSession`だけを正本にする。
- 現行`memory.py`の独自`AgentSession`、`ConversationMessage`、`InMemoryContextProvider`は廃止する。
- 現行`SerializedProcurementContextProvider`によるFramework Session内への独自Session JSON保存も廃止する。
- 業務状態だけをPydantic `ProcurementExecutionState`として`AgentSession.state["procurement.execution.v2"]`へJSON互換dictで保存する。
- Framework `AgentSession.to_dict()` / `from_dict()`で会話履歴と業務状態をserialize/restoreする。
- Function Tool/Middlewareは`FunctionInvocationContext.session`からSessionへアクセスする。
- `ctx.session is None`の場合はSessionを暗黙作成せずfail closedにする。
- MiddlewareはFrameworkの`AgentMiddleware`、`ChatMiddleware`、`FunctionMiddleware`を使用する。
- Agent ToolはFrameworkの`as_tool()`を使用する。
- 標準Agent/Chat/Function Spanをcustom codeで二重生成しない。
- 独自実装を残す場合は、対応するFramework機能がない理由、適用範囲、contract testを資料へ記録する。

## Data Tool

- Data ToolはAzure FunctionsやOpenAPIではなくMCP Toolとする。
- Repository内のVersion付きSynthetic JSONを正本にする。
- Azure AI Searchへ次の2 indexを定義する。
  - `procurement-catalog-v1`: Synthetic商品10件
  - `procurement-code-master-v1`: 勘定科目コードと部課コード
- 次の2 ToolboxをVersion付きで定義する。
  - `catalog-search-toolbox`
  - `code-master-toolbox`
- 各Toolboxは担当するAzure AI Search indexだけを`type: azure_ai_search` Toolとして持ち、MCP-compatible endpointから利用できるようにする。
- 各Prompt Agent定義には担当Toolboxだけを接続する。
- runtime identity、index管理identity、document投入identityのRBACを分離する。
- 型番、価格、勘定科目コード、部課コードはSearch/Toolbox resultに存在する値だけを採用し、LLMが推測してはならない。
- 「部課コード」は部単位とし、`department_code` / `department_name`を使用する。課、チーム、係は扱わない。
- 勘定科目コードは商品分類から照会し、部課コードは申請者情報またはユーザーが確認した部名から照会する。

## Observabilityと検証

- 改訂資料のV1〜V21について、IDだけでなく「依頼時の確認内容」を検証目的の正本として扱う。
- S1は、catalogに存在する商品を依頼し、検証済み申請情報の作成まで正常完了させる。
- S2は、Code Toolbox MCP/Azure AI SearchのFailure profileを有効化し、Tool障害の原因箇所とstatus分離を確認する。
- S3は、catalogに存在しない商品を依頼し、再検索、再計画、ユーザー確認、終了条件の経路を確認する。
- S4は、親から子へ渡すStructured inputを意図的に欠落させ、boundary validationとTrace/correlationを確認する。
- S5は、多数の品目をまとめて依頼し、長い入力、Tool出力、responseを発生させ、切詰め位置を確認する。
- S1〜S5のCore Scenarioを実装し、改訂資料7.1の「不足する確認」を未完了理由と次Actionまで含めてReportする。7.1.1のV-ID別最終判定ルールに従い、Platformの負の結果を無理にPASSへしない。7.1.2の成果物は、Core Matrixに含まれるものを作り、T1〜T4に属するものは対象Trackが有効化された場合だけ作成・実行する。
- 14 Failure Patternは改訂資料7.1.3を正本にし、Stage Aで全14パターンのpositive/negative Trace fixtureを検知する。Stage BではS2のTV-02/TV-03、S3のSD-03/SD-05、S4のMA-04/MA-05だけをE2E注入し、S1/S5はHealthy controlとして誤検知がないことを確認する。
- Stage Bの注入runは外側のAgent technical statusを`SUCCESS`のままにし、意味上の誤りをTraceから判定する。注入未発火は`INJECTION_MISSED`、Trace欠落による判定不能は`UNEVALUABLE_TRACE_INCOMPLETE`としてSemantic PASS/FAILへ混ぜない。
- 現時点のCore実行Matrixは改訂資料7.3に従う。
- T1〜T4は現時点ではDone Definitionに含めず、改訂資料7.2の実施トリガーに該当した場合だけ提案する。Azure変更を伴う場合は事前承認を得る。
- HTTP status、MCP/Search status、parse status、business statusを分離する。
- `test.case.id`、Framework Session ID、turn number、plan/step/attempt、Agent role/definition、Toolbox/index、Trace相関情報をRaw contentなしで検索可能にする。
- Chain-of-Thoughtは保存・出力しない。
- Raw contentはSynthetic content-on profileだけで記録し、production-like content-offも検証可能にする。
- PII、Secret、実社員情報、実価格を使用しない。

## Failure profile

- Azure AI Search/Toolbox経路では`not_found`、`index_missing`、`permission`、`business_invalid`を分離して再現する。
- Managed Toolboxで任意生成できないtimeoutとMCP protocol不正はLocal MCP fixtureで検証する。
- DNS、route、Private Link、private collectorはT4が明示的に有効化された場合だけ実Azureで検証する。
- 技術的statusとbusiness statusを分離し、原因箇所をMCP、Search、parse、validationのどこかへ分類する。

## 実装順序

1. 現行Repositoryの差分調査とFramework重複実装の棚卸し
2. 独自History/SessionのFramework標準機能への移行
3. 単一ArchitectureへのDomain/Factory/Trace schema移行
4. Synthetic JSON、Azure AI Search index schema、document生成・検証script
5. Foundry Toolbox定義とLocal recorded MCP contract fixture
6. Prompt-based子Agent定義
7. Hosted親Agent、Plan & Execute、Structured I/O、Session再開
8. Framework Middlewareを使ったGovernanceとObservability
9. 14 Failure PatternのStage A Detector testと、S2〜S4のStage B 6パターン/Healthy control test
10. S1〜S5 Core test、DevUI smoke、deployment configuration validation
11. Azure apply前の変更一覧、RBAC、費用、rollback、実行command提示

各Phase終了時に、変更file、実行test、結果、未完了項目、次のPhaseを短く報告してください。完了済みPhaseを作り直さず、Repository、test結果、改訂資料を正本として続行してください。

## AzureとGitのGate

- Local実装とtestを先に完成させる。
- Bicep、index schema、Toolbox definition、Agent definition、deployment scriptは作成・静的検証してよい。
- Azure Resource作成、index作成、document投入、Role付与、Toolbox/Agent作成、Application Insights/DCR/Private Link変更、deployment、削除は、実行内容と費用影響を提示し、明示承認を得るまで実行しない。
- Secretやtokenを出力、commitしない。既存`.env.azure.local`の値も表示しない。
- Default branchへ直接pushしない。`codex/`prefixの作業branchを使用する。
- 実装とLocal検証が完了したらcommit、push、Draft PR作成、Ready化、`@codex review`、P0/P1解消、再Reviewを行う。
- ユーザーは最終mergeまで依頼済みなので、Review完了かつ未解決P0/P1がなくなった後にSquash and Mergeする。重要でないPoC向け指摘は、理由をPRへ記録して対応しなくてよい。

## Done Definition

- 改訂資料のArchitectureとAcceptance Criteriaを満たす。
- 独自History/Session classとnested Session serializationが残っていない。
- S1〜S5 Core Scenarioと必要なLocal/contract/trace testがpassする。
- 14 Failure PatternすべてのStage A Detector testがpassし、Stage BでS2/S3/S4へ割り当てた6パターンを検知する。
- S1/S5 Healthy controlを誤検知せず、`INJECTION_MISSED`と`UNEVALUABLE_TRACE_INCOMPLETE`をSemantic PASS/FAILから分離する。
- 外部CredentialやAzure applyが必要なtestは理由付きSKIPとし、Local fixtureで検証できる部分を残す。
- Azure未実施項目、Platform制約、Known limitationを明記する。
- 未実装項目を完了扱いにしない。理由、影響、次のActionを示す。

最終回答では、実装結果、Architecture上の判断、主要変更file、test結果、V1〜V21の状態、S1〜S5の状態、14 Failure PatternのStage A/Stage B検知状態、Framework標準機能への移行結果、Azure apply前の確認、Known limitations、PR/Review/Merge結果を簡潔に報告してください。
