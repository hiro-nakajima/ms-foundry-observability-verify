# Codex実装指示Prompt

## Microsoft Foundry 購買支援Agent Observability / Evaluation PoC

このPromptは、次のHandOff資料と一緒にCodexへ渡す。

- codex-handoff-foundry-procurement-observability-evaluation-poc-2026-08-28.md

HandOffファイルをRepositoryのdocs/配下へ配置するか、CodexのPromptへ添付してから実行すること。

---

## Codexへ貼り付けるPrompt

あなたは、このRepositoryでMicrosoft Foundry購買支援AgentのObservability / Evaluation PoCを実装する担当者です。

最初に、次のHandOff資料を全文読み、要求、前提、制約、Acceptance Criteria、Done Definitionを実装の正本として扱ってください。

~~~text
docs/codex-handoff-foundry-procurement-observability-evaluation-poc-2026-08-28.md
~~~

ファイルが別の場所に添付されている場合は、添付された同名ファイルを使用してください。見つからない場合だけ、作業を開始せず場所を質問してください。

### 最終目標

次の4つの論理構成を、同じ購買仕様、Synthetic Data、Tool契約、Failure Case、Evaluatorで比較できるRepositoryを完成させてください。

1. Prompt Agent / Single
2. Prompt Agent / Multi-Agent
3. Hosted Agent / Single
4. Hosted Agent / Multi-Agent

AgentはReAct型ではなく、明示的なPlanを作成・保存・再開するPlan & Execute型とします。

正常系では、社員からの購買依頼を受け、商品カタログ、商品コード、単価、納期、申請者、部門コード、勘定科目コードを照会し、計算Scriptで合計金額を算出して、検証済みの申請ドラフトを提示してください。

### 最初に行うこと

1. Repository内のAGENTS.md、README、既存設計、既存コード、git statusを確認する。
2. HandOffを全文読み、要求を実装Taskへ分解する。
3. 既存変更やユーザー作成ファイルを特定し、無関係な変更を上書きしない。
4. 現在の公式Microsoft Foundry、Microsoft Agent Framework、Agent Governance Toolkitの仕様を確認する。
5. 使用PackageとVersionをlockfileへ固定し、選定理由と確認日を記録する。
6. 実装Planを提示してから作業を開始する。

質問は、回答によってArchitectureまたはAzure Resource構成が大きく変わるBlocking事項だけにしてください。HandOffに推奨Defaultがある事項は、そのDefaultを採用して先へ進み、採用した前提を記録してください。

### 実装原則

- Chain-of-Thoughtを保存・出力しない。
- agent_traceは観測可能なSpan、Event、状態遷移、Tool Call、検証結果だけで構成する。
- 実データ、実社員情報、実価格、実Secretを使用しない。
- LLMが商品コード、単価、勘定科目、納期を推測しない。
- 合計金額をLLMの暗算で確定しない。
- HTTP statusとbusiness statusを分離する。
- 技術的SUCCESSでも業務的に誤るSilent Semantic Failureを再現可能にする。
- Localで完結する実装とTestを先に完成させる。
- Azure Resource作成、Role付与、設定変更、Deployment、削除は、明示的な承認を得るまで実行しない。
- Deployment用Code、Bicep、azd、Scriptは作成・検証してよいが、applyはしない。

### Agent構成

Single:

~~~text
依頼受付
  → Plan作成
  → 不足情報確認
  → カタログ検索
  → 商品・コード・納期照会
  → 計算Skill
  → Draft作成
  → 検証
  → 申請内容提示
~~~

Multi:

~~~text
依頼受付
  → Coordinator
  → 調達担当 Agent Tool
  → 起案担当 Agent Tool
  → Coordinator最終検証
  → 申請内容提示
~~~

Hosted Multiでは、procurement_specialistとdrafting_specialistをAgent Frameworkのagent.as_tool()でCoordinatorへ登録してください。

Prompt Multiでは、Managed Prompt Agentから同一プロセスのagent.as_tool()を呼んだように扱わず、FoundryのA2A Agent Toolまたは利用可能なManaged Agent Toolで論理的に同じ構成を実現してください。

TraceとReportには、少なくとも次を分離して記録してください。

- logical_pattern
- agent_role
- agent_definition_id
- foundry_resource_id
- implementation_kind

### Plan & Execute

ExecutionPlanとPlanStepをSchema化してください。

PlanStepは最低限、次を保持します。

- step_id
- step_type
- owner
- status
- input_refs
- output_refs
- evidence_refs
- tool_call_ids
- attempt
- started_at
- ended_at
- completion_reason

statusは最低限、次を扱います。

- PENDING
- RUNNING
- WAITING_USER
- COMPLETED
- FAILED
- BLOCKED
- INVALIDATED

同一Plan version、Step、input hashの重複実行を抑止してください。Userが条件を変更した場合は、影響を受けるStepだけをINVALIDATEDにして再実行してください。

### Contextと再開

- AgentSessionを会話と実行状態の正本にする。
- InMemoryContextProviderでPlan、次Step、User入力、取得済み根拠を各Invocationへ注入する。
- Sessionをserialize / restoreできるようにする。
- DevUIのTurn継続と、Hosted環境の再接続・再開を分けてTestする。
- Coordinator Sessionを正本にする。
- 子AgentへProcurementContextSnapshotをStructured inputとして渡す。
- 子Agent ResultをCoordinatorが検証してSessionへmergeする。
- propagate_sessionはDefaultでfalseとする。
- propagate_session=trueはCompatibility Testが通った場合だけ選択可能にする。

### DataとTool

Repository内のVersion付きJSONをSynthetic Dataの正本にしてください。

~~~text
data/
  catalog.json
  account_codes.json
  departments.json
  delivery_rules.json
  applicants.json
  tax_rules.json
~~~

次の論理Tool契約を実装してください。

- search_catalog
- get_catalog_item
- lookup_account_code
- lookup_department
- get_applicant
- estimate_delivery
- calculate_request
- validate_application

Local JSON Adapterを必須とし、Azure Functions、Toolbox / MCP、Azure AI Searchへ差し替え可能なPortを定義してください。

Azure AI Searchを使用する場合でも、単価、コード、納期はStructured Toolで最終確定してください。

### Skill

次のSkillを実装してください。

~~~text
src/procurement_agent/skills/request-check/
  SKILL.md
  scripts/
    calculate_request.py
    validate_request.py
  references/
    calculation-rules.md
~~~

calculate_request.pyはDecimalと明示的な丸め規則を使い、subtotal、discount、taxable_amount、tax、totalを決定論的に返してください。

Hosted AgentではSkillsProviderと許可済みScript runnerを使用してください。Prompt Agentでは同じ計算ロジックをcalculate_request Function Toolから呼び出し、必要に応じてFoundry Toolbox Skillで手順を配布してください。

### Governance

Agent Governance Toolkitを組み込み、次の4段階をMiddlewareへ接続してください。

- pre_input
- pre_tool
- post_tool
- pre_output

policy.yamlには最低限、次を定義してください。

- Role別Tool allowlist
- CoordinatorによるData Tool直接呼出しの禁止
- 起案担当による検索Tool呼出しの禁止
- Tool Outputにない商品・価格・コードの使用禁止
- 計算Skill Outputの必須化
- 必須情報不足時のWAITING_USER
- 検証前のDraft提示禁止
- Completed Stepの重複実行禁止
- Agent Tool / Tool Call回数上限
- Synthetic canary / Secret patternの出力禁止

Governanceはshadowとenforceを切り替え可能にしてください。Silent Failure評価ではshadowのwould_denyを記録し、Hard Gate Testは別Suiteにしてください。

### Observability

OpenTelemetryで最低限、次の境界をSpan化してください。

- agent.invoke
- plan.create
- plan.resume
- plan.step.execute
- agent_as_tool.procurement_specialist
- agent_as_tool.drafting_specialist
- tool.*
- skill.request_check
- script.calculate_request
- governance.pre_input
- governance.pre_tool
- governance.post_tool
- governance.pre_output
- validation
- response.generate

状態変化はSpan Event、補助的な診断情報はLogへ記録してください。

次の9 Trace FieldをTrace Evaluation Envelopeへ正規化してください。

1. user_input
2. response
3. retrieved_contexts
4. system_prompt
5. tool_definitions
6. tool_calls
7. tool_output
8. agent_trace
9. conversation

Raw contentはSynthetic評価環境だけで記録可能にし、Production相当TestではOFFにしてください。Custom AttributeとBaggageにはRaw input、Secret、個人情報を入れないでください。

### Failure Injectionと評価

HandOffに定義された14パターンを、技術的StatusはSUCCESSのまま再現してください。

仕様・設計:

- SD-01 タスク仕様の不遵守
- SD-02 役割仕様の不遵守
- SD-03 ステップの繰り返し
- SD-04 会話履歴の喪失
- SD-05 終了条件の未認識

エージェント間:

- MA-01 会話のリセット
- MA-02 確認を求めない
- MA-03 タスクの逸脱
- MA-04 情報の出し惜しみ
- MA-05 他Agent入力の無視
- MA-06 推論と行動の不一致

タスク検証:

- TV-01 早すぎる終了
- TV-02 検証の欠如・不完全
- TV-03 誤った検証

Stage Aとしてpositive / negative Trace fixtureでEvaluatorを検証し、Stage BとしてAgent E2E Failure Profileを実行してください。

Injectionが発火しなかったRunはSemantic PASS / FAILへ混ぜず、INJECTION_MISSEDとして扱ってください。

最小Evaluation Matrixは44 runs × 2 Stage = 88 runsです。Healthy controlと主要Caseのk反復も追加してください。

### Test

最低限、次を作成・実行してください。

- Domain Model Unit Test
- JSON Data validation
- Tool Contract Test
- Calculation Script Test
- Plan transition Test
- Duplicate Step suppression Test
- Session serialize / restore Test
- Conversation continuity Test
- Agent Tool Structured I/O Test
- Role / Tool Governance Test
- Trace completeness Test
- 14 Failure Evaluator Test
- Hosted Single / Multi Local Integration Test
- DevUI smoke test
- Prompt Agent definition validation
- Deployment configuration validation

外部Credentialがなく実行不能なTestはSKIP理由を明記し、Local fixtureで代替可能な部分を残してください。

### DevUI

devui_app.pyからHA-SとHA-Mを選択可能にしてください。

Hosted deploymentと同じAgent Factory、Prompt、Tool、Skill、Policy、Middlewareを使用し、Demo専用の短絡実装を作らないでください。

DevUIでPlan、現在Step、完了Step、Agent Tool委譲、Governance decision、Trace ID、Warning、Session resumeを確認可能にしてください。

### 作業の進め方

次のPhase順で進め、各Phase終了時に短い進捗、変更ファイル、実行Test、残課題を報告してください。

1. Domain / Synthetic Data / Local Tool
2. Plan / Session / Context / Harness
3. Skill / Governance / Observability
4. Hosted Single / Multi / DevUI
5. Prompt Single / Multi definitions
6. Failure Injection / Evaluator / Report
7. Infrastructure / Deployment scripts

途中で会話が長くなっても、完了済みPhaseを作り直さず、Repository、Plan、Test結果を正本として続行してください。

### 完了時の回答

最終回答は、次を簡潔に示してください。

- 実装結果
- Architecture上の重要判断
- 作成・変更ファイル
- 実行したTestと結果
- 9 Trace Fieldの取得状況
- 14 Failure Patternの再現・判定状況
- Prompt / Hosted間の実装差
- Azure apply前に必要な確認
- Known limitations
- 次に実行するCommand

要件を未実装のまま「完了」としないでください。未完了項目は、理由、影響、次のActionを明示してください。

まずRepositoryとHandOffを確認し、実装Planを提示したうえで作業を開始してください。

---

## 推奨する最初の実行範囲

最初のCodex Taskでは、Azure applyを行わず、次までを完了させる。

1. Repository scaffold
2. Domain Model
3. Synthetic JSON
4. Local Tool Adapter
5. Plan / Session / Context
6. request-check Skill
7. Governance Policy
8. OTel Span helper
9. Unit / Contract / Trace fixture Test
10. Hosted AgentのLocal / DevUI scaffold

その結果をReviewした後、Prompt AgentのManaged Resource定義とAzure deploymentへ進む。
