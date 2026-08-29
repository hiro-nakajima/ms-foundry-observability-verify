# Codex HandOff: Microsoft Foundry 購買支援Agent Observability / Evaluation PoC

## Plan & Execute型 Prompt Agent / Hosted Agent × Single / Multi-Agent

- 改訂日: 2026-08-28
- 実装主体: Codex
- 対象: Microsoft Foundry Agent Service
- 推奨言語: Python
- 比較対象: Prompt Agent / Hosted Agent、Single / Multi-Agent
- 業務シナリオ: 社員からの購買依頼を受け、商品・各種コードを照会し、申請内容を作成・提示する
- 重要: 商品、社員、部署、勘定科目、価格、納期、会話、SecretはすべてSynthetic Test Dataを使用する

---

# 0. この資料の結論

このPoCは、次の4つの論理構成を、同じ購買仕様、同じSynthetic Data、同じTool契約、同じFailure Caseで比較する。

1. Prompt Agent / Single
2. Prompt Agent / Multi-Agent
3. Hosted Agent / Single
4. Hosted Agent / Multi-Agent

AgentはReAct型ではなくPlan & Execute型とする。最初に明示的なExecution Planを作成し、各Stepを実行・検証・保存する。再開時はAgentSessionに保存したPlanから未完了Stepを特定し、完了済みStepを重複実行しない。

正常系のMVP終了点は、購買システムへの実登録ではない。次の項目を含む、根拠付きで検証済みの申請ドラフトをUserへ提示した時点とする。

- 品名、商品コード
- 数量
- 単価
- 小計、税額、合計金額
- 希望納期、回答納期
- 申請者、所属部門
- 勘定科目コード
- 検索・照会根拠
- 警告、未確定項目

評価対象は、例外やHTTPエラーではない。Agent、子Agent、Tool、Skillがすべて技術的には正常終了し、Error Rateが0であるにもかかわらず、業務結果、会話、Plan、Tool経路が誤っているSilent Semantic Failureである。

必須Traceは次の9種類である。

1. user_input
2. response
3. retrieved_contexts
4. system_prompt
5. tool_definitions
6. tool_calls
7. tool_output
8. agent_trace
9. conversation

agent_traceはChain-of-Thoughtではない。保存・評価するのは、Plan作成、Step状態遷移、Agent呼び出し、Model呼び出し、Tool呼び出し、Skill実行、子Agent委譲、Governance判定、検証結果、終了判定など、観測可能な実行軌跡である。

Span化の認識は概ね正しい。ただし「各種手続き間にログを置く」だけでは不十分である。次の境界をSpanとして表現し、判断結果や業務状態をAttributeまたはEventとして記録する。

- Agent invocation
- plan.create、plan.resume
- plan.step.execute
- agent-as-tool invocation
- tool execution
- skill script execution
- governanceのpre_input、pre_tool、post_tool、pre_output
- validation
- response generation

OpenTelemetryでは、Spanが処理区間、Eventが区間内の状態変化、Logが補助的な診断情報である。Trace評価の主軸はSpan treeと正規化Envelopeであり、Logだけに依存しない。

---

# 1. Codexへの最重要指示

次を、Local TestからFoundry上の比較評価まで再現可能な1つのRepositoryとして完成させること。

1. 4つの論理Agent構成
2. Plan & Executeの明示的なPlan SchemaとExecutor
3. InMemoryContextProviderとAgentSessionによる継続・再開
4. Single Agentの購買フロー
5. agent-as-toolを用いるMulti-Agentフロー
6. JSONを正本とするSynthetic Data
7. JSON / Azure Functions / Azure AI Searchを差し替え可能にするTool Port
8. request-check Skillと計算Script
9. Agent Governance ToolkitのPolicy-as-CodeとMiddleware統合
10. 5要素のAgent Harness
11. Hosted AgentのDevUI実行
12. 9種類のTraceを含むTrace Evaluation Envelope
13. 14種類のSilent Semantic Failure Profile
14. Deterministic Evaluator
15. Foundry Built-in Evaluator / Rubric Evaluator連携
16. 非決定論を測る反復実行
17. JSONL / JSON / CSV / Markdown比較Report
18. Unit / Contract / Integration / Trace Test
19. セットアップ、デプロイ、評価、削除手順

Azure Credentialや対象Resourceがない場合も、Repository scaffold、Synthetic Data、Local Tool、Plan Executor、Skill、Governance Policy、Failure Injection、Trace fixture、Normalizer、Deterministic Evaluator、Unit Test、Dry Runまでは完成させる。

既存Azure環境の設定変更、Role付与、Feature登録、Resource作成、削除は、明示的なapply指定なしに行わない。

---

# 2. PoCの目的と非目的

## 2.1 目的

- 技術的Error Rateでは見つからない業務上の失敗をTraceで検出できるか確認する
- Prompt AgentとHosted Agentで取得可能なTraceの差を確認する
- SingleとMulti-Agentで会話、Plan、委譲、Tool経路の失敗率を比較する
- 最終responseだけでなく、Planと実行Trajectoryを評価する
- AgentSessionからの再開が正しく機能するか確認する
- Governanceの判定とAgentの実行が一致するか確認する
- 失敗を仕様へ戻し、Regression Testへ昇格する流れを確認する

## 2.2 非目的

- 実際の購買システムへの登録
- 実在する社員、部署、勘定科目、価格の利用
- Production環境でのRaw prompt / responseの常時記録
- Chain-of-Thoughtの保存
- LLMによる暗算を金額の正本にすること
- すべての失敗をLLM Judgeだけで判定すること
- Prompt AgentとHosted Agentで存在しない同一Spanを捏造すること
- AgentSessionを異なるAgentまたは異なるService Sessionへ無条件に共有すること

---

# 3. 前提と設計判断

## 3.1 論理4構成、Agent役割8、推奨Foundry Resource 6

Multi-AgentはCoordinator、調達担当、起案担当の3役で構成する。Hosted Multiでは3つのAgent Framework Agentを1つのHosted Agent deployment内に置き、子Agentをagent.as_tool()で親へ登録する。

Prompt AgentはManaged Runtimeであり、Pythonオブジェクトのagent.as_tool()を同一プロセスで実行できない。Prompt Multiでは、論理的に同じ「子AgentをToolとして呼ぶ」構成を、FoundryのA2A Agent ToolまたはManaged Agent参照で実現する。厳密にAgent Frameworkのagent.as_tool() APIを4構成すべてで使うことはできない。

| Pattern | Agent役割 | Agent定義数 | 推奨Foundry Resource | 子Agentの物理接続 |
|---|---:|---:|---:|---|
| PA-S | 購買支援 | 1 | Prompt Agent × 1 | なし |
| PA-M | Coordinator、調達担当、起案担当 | 3 | Prompt Agent × 3 | A2A Agent Tool / Managed Agent Tool |
| HA-S | 購買支援 | 1 | Hosted Agent × 1 | なし |
| HA-M | Coordinator、調達担当、起案担当 | 3 | Hosted Agent × 1 | Agent Framework agent.as_tool() |
| 合計 | 4つの比較Pattern | 8 | 6 | 実装方式はPattern別 |

評価Reportでは、logical_pattern、agent_role、agent_definition_id、foundry_resource_idを分離する。単に「4 Agent」または「8 Resource」と数えない。

## 3.2 各Patternの責務

| ID | 構成 | 実行内容 |
|---|---|---|
| PA-S | Prompt Single | 依頼受付 → カタログ検索 → コード照会 → 計算 → 検証 → 申請内容提示 |
| PA-M | Prompt Multi | 依頼受付 → 調達担当Tool → 起案担当Tool → Coordinator検証 → 申請内容提示 |
| HA-S | Hosted Single | PA-Sと同じ業務をPlan & Executeで実装 |
| HA-M | Hosted Multi | 依頼受付 → procurement_specialist agent-as-tool → drafting_specialist agent-as-tool → Coordinator検証 → 申請内容提示 |

## 3.3 Prompt / Hostedの比較公平性

同じにするもの:

- User Case
- System role specification
- Plan step type
- JSON Schema
- Toolの論理名、入力、出力、Business status
- Synthetic DataとVersion
- Calculation logic
- Failure Profile
- Trace Evaluation Envelope
- Evaluatorと合否条件
- Model deployment、可能な限りのModel settings

同じにしないもの:

- Prompt AgentのManaged内部SpanとHosted AgentのCustom Span
- Prompt MultiのRemote Agent ToolとHosted Multiのin-process agent.as_tool()
- Prompt Agent向けTool transportとHosted AgentのPython Function Tool
- Prompt Agent向けSkill deliveryとHosted Agentのlocal SkillsProvider

比較Reportにはimplementation_kindを必ず含める。

---

# 4. 5要素のAgent Harness

| 要素 | 責務 | 主な実装 |
|---|---|---|
| オーケストレーション | Plan作成、Step選択、実行順序、子Agent委譲、終了判定 | agent.py、ExecutionPlan、PlanExecutor |
| コンテキスト管理 | 会話、業務状態、根拠、Plan、再開情報の保存・注入 | memory.py、InMemoryContextProvider、AgentSession |
| ツール連携 | JSON検索、コード照会、納期照会、外部Adapter | tools.py、data providers、Functions / AI Search adapter |
| 検証・統制 | 入出力Schema、業務Rule、権限、承認、重複抑止 | middleware.py、governance.py、policy.yaml、request-check Skill |
| オブザーバビリティ | OTel Span、Event、Log、Trace正規化、相関 | observability.py、Trace middleware、Application Insights |

Hosted Agentでは、利用Versionで安定している場合はAgent Framework Harness Agentを基盤にしてよい。ただし、評価に必要なplan_id、step_id、step_status、evidence_refsを外部から観測できる独自Plan Schemaは残す。Harness内部の非公開Todo表現だけを評価の正本にしない。

---

# 5. Plan & Execute実行契約

## 5.1 Execution Plan

最初のTurnでUser intentを構造化し、次のPlanを作成する。

~~~json
{
  "plan_id": "plan-001",
  "plan_version": 1,
  "goal": "開発用ノートPCを3台、来月までに調達する申請ドラフトを作る",
  "status": "RUNNING",
  "steps": [
    {"id": "S01", "type": "parse_request", "status": "COMPLETED"},
    {"id": "S02", "type": "resolve_missing_fields", "status": "PENDING"},
    {"id": "S03", "type": "search_catalog", "status": "PENDING"},
    {"id": "S04", "type": "select_catalog_item", "status": "PENDING"},
    {"id": "S05", "type": "lookup_account_code", "status": "PENDING"},
    {"id": "S06", "type": "lookup_delivery", "status": "PENDING"},
    {"id": "S07", "type": "calculate_total", "status": "PENDING"},
    {"id": "S08", "type": "build_draft", "status": "PENDING"},
    {"id": "S09", "type": "validate_draft", "status": "PENDING"},
    {"id": "S10", "type": "present_draft", "status": "PENDING"}
  ]
}
~~~

各Stepは最低限、次のFieldを持つ。

| Field | 意味 |
|---|---|
| id | Plan内で不変のStep ID |
| type | 評価可能なStep種別 |
| owner | coordinator / procurement_specialist / drafting_specialist |
| status | PENDING / RUNNING / WAITING_USER / COMPLETED / FAILED / BLOCKED |
| input_refs | Session内入力への参照 |
| output_refs | Session内出力への参照 |
| evidence_refs | Tool Output / Document IDへの参照 |
| tool_call_ids | 実行したTool Call ID |
| attempt | 再試行回数 |
| started_at / ended_at | 実行時刻 |
| completion_reason | 完了・待機・停止理由 |

## 5.2 Executorの規則

1. PlanはUser requestと既知Session Stateから作成する。
2. 必須情報が曖昧ならresolve_missing_fieldsをWAITING_USERにする。
3. 実行するのは原則として最初の未完了Stepだけである。
4. Tool実行前にStepをRUNNINGへ遷移する。
5. Tool Outputと根拠を保存してからCOMPLETEDへ遷移する。
6. 必須Stepの検証に失敗した場合、後続のpresent_draftへ進まない。
7. User inputで前提が変わった場合、影響を受けるStepだけをINVALIDATEDから再実行する。
8. 同一Input hash、同一Plan version、同一Stepの重複Tool Callは抑止する。
9. 全必須Stepが完了したときだけPlanをCOMPLETEDにする。
10. COMPLETED後はUserが明示的に変更を依頼しない限り再実行しない。

## 5.3 終了条件

MVPの正常終了条件:

- 必須項目がすべて存在する
- 商品とコードがTool Outputに存在する
- 数量と単価のprovenanceがある
- 合計金額がrequest-check Skill scriptの出力と一致する
- 納期が希望条件を満たすか、満たさない場合は警告がある
- Governance pre_outputがallow
- ApplicationDraft schema validationがpass
- responseに申請内容と未確定項目が明示される
- plan.statusがCOMPLETED

User確認後の実申請はMVP外とする。確認不足や推論と行動の不一致を試験する場合だけ、Synthetic submit extensionを別Feature Flagで有効にする。

---

# 6. 購買業務モデル

## 6.1 代表入力

~~~text
開発用のノートPCを3台、来月までに購入したいです。
申請者は山田太郎、開発一部です。
~~~

## 6.2 期待出力

~~~json
{
  "request_id": "PR-DRAFT-0001",
  "status": "DRAFT_READY",
  "item": {
    "product_code": "LAPTOP-DEV-14",
    "name": "開発用ノートPC 14インチ",
    "quantity": 3,
    "unit_price": 180000,
    "currency": "JPY"
  },
  "amount": {
    "subtotal": 540000,
    "tax": 54000,
    "total": 594000,
    "calculated_by": "request-check/scripts/calculate_request.py"
  },
  "delivery": {
    "requested_by": "2026-09-30",
    "estimated_on": "2026-09-18",
    "meets_request": true
  },
  "applicant": {
    "employee_id": "EMP-001",
    "name": "山田太郎",
    "department_code": "DPT-DEV-01"
  },
  "account": {
    "account_code": "7210-EQUIPMENT",
    "label": "開発用備品"
  },
  "evidence_refs": [
    "catalog:LAPTOP-DEV-14:v1",
    "account:7210-EQUIPMENT:v1",
    "delivery:LAPTOP-DEV-14:v1"
  ],
  "warnings": []
}
~~~

## 6.3 Domain Model

models.pyに最低限、次を定義する。

- ProcurementRequest
- RequestConstraints
- ExecutionPlan
- PlanStep
- CatalogItem
- AccountCode
- DeliveryEstimate
- Applicant
- ProcurementContextSnapshot
- ApplicationDraft
- ValidationResult
- AgentToolResult
- GovernanceDecision

すべてPydantic等でSchema化し、response、Tool I/O、Session State、Trace Envelopeで同じ定義を再利用する。

---

# 7. Synthetic DataとTool

## 7.1 JSONを正本にする

次をRepository内部のVersion付きJSONとして保持する。

~~~text
data/
  catalog.json
  account_codes.json
  departments.json
  delivery_rules.json
  applicants.json
  tax_rules.json
~~~

catalog.jsonにはproduct_code、name、category、keywords、specifications、unit_price、currency、stock、lead_time_days、valid_from、valid_toを含める。

金額と納期の正本はLLM promptではなくJSON / Tool Outputである。

## 7.2 Tool Port

論理Tool名とSchemaは4構成で統一する。

| Tool | 目的 | 主なOutput |
|---|---|---|
| search_catalog | 要件に合う商品候補を検索 | 候補、score、price、lead time、evidence |
| get_catalog_item | 商品コードの詳細取得 | 商品、単価、在庫、Version |
| lookup_account_code | 用途・カテゴリから勘定科目を照会 | code、label、validity、evidence |
| lookup_department | 申請者の部門コードを照会 | department code、validity |
| get_applicant | 申請者情報を照会 | employee id、name、department |
| estimate_delivery | 数量と希望納期から回答納期を算出 | estimated date、meets request |
| calculate_request | request-check Skill scriptを呼ぶ | subtotal、tax、total、checks |
| validate_application | 申請ドラフトを決定論的に検証 | pass、violations、evidence |

Tool Responseには必ず次を含める。

~~~json
{
  "call_id": "tool-...",
  "business_status": "SUCCESS",
  "data_version": "2026-08-28.1",
  "result": {},
  "evidence_refs": [],
  "warnings": []
}
~~~

HTTP 200やSpan Status OKとbusiness_statusは分ける。Silent Failureでは技術StatusをOKのままにし、内容だけを意図的に誤らせる。

## 7.3 Adapter

| 環境 | 推奨Adapter |
|---|---|
| Unit / Local | In-process JSON repository |
| Hosted Agent PoC | Python Function Tool、または共通Toolbox / MCP |
| Prompt Agent PoC | Foundry Function / Azure Functions / Toolbox |
| 検索拡張 | Azure AI Search |

Azure AI Searchを使う場合も、商品コード、単価、納期、勘定科目の最終確定はStructured Toolで再取得する。検索スコアだけで金額やコードを確定しない。

---

# 8. request-check Skill

## 8.1 構成

~~~text
skills/request-check/
  SKILL.md
  scripts/
    calculate_request.py
    validate_request.py
  references/
    calculation-rules.md
~~~

SKILL.mdには、Skillの適用条件、入力Schema、Script実行方法、丸め規則、出力Schema、禁止事項を記載する。

calculate_request.pyはDecimalを使用し、少なくとも次を決定論的に計算する。

- subtotal = quantity × unit_price
- discount
- taxable_amount
- tax
- total
- rounding mode

LLMが独自に暗算した値を最終金額として採用してはならない。responseの金額はSkill Outputと完全一致させる。

## 8.2 Prompt / Hostedの適用差

- Hosted Agent: Agent FrameworkのSkillsProviderと許可済みScript runnerでSkillを実行する
- Prompt Agent: Foundry Toolbox Skillで指示を配布し、計算Script本体はcalculate_request Function Toolとして公開する

同一Scriptまたは同一Python packageを両経路から呼び出し、計算結果の比較可能性を保つ。Prompt AgentのManaged Runtime内で任意のlocal scriptが直接実行されたように扱わない。

Skill実行Spanには次を記録する。

- skill.name
- skill.version
- script.name
- script.sha256
- input_hash
- rounding_mode
- output subtotal / tax / total
- validation status

---

# 9. AgentSession、Context Provider、再開

## 9.1 Session State

AgentSessionを会話と実行状態の正本とする。

~~~json
{
  "session_schema_version": "1.0",
  "conversation_id": "conv-001",
  "turn_index": 2,
  "active_plan_id": "plan-001",
  "plan": {},
  "request": {},
  "selected_item": {},
  "evidence": {},
  "application_draft": null,
  "governance_state": {},
  "completed_step_keys": [],
  "last_response_id": "resp-...",
  "resume_token": "opaque"
}
~~~

InMemoryContextProviderは各Invocationの前に、現在Plan、次のStep、User入力、選択済み商品、取得済み根拠、Governance状態をModel Contextへ注入し、Invocation後にStructured ResultをAgentSessionへ反映する。

## 9.2 再開規則

1. 同じUser / tenantに紐づくcontinuation IDからAgentSessionを復元する。
2. session_schema_versionとagent_definition_versionを検証する。
3. PlanのCOMPLETED Stepとevidenceを読み込む。
4. RUNNINGで中断したStepはidempotency keyとTool履歴を確認する。
5. WAITING_USERなら不足項目への回答を適用する。
6. 最初のPENDINGまたは再実行が必要なStepから続行する。
7. plan.resume Spanへresume_reasonとresumed_from_stepを記録する。

InMemoryContextProviderはプロセス終了後の永続化を保証しない。DevUI内のTurn継続には使えるが、Hostedでプロセス再起動をまたぐ場合はAgentSessionのserialize / restoreまたはFoundryのsession persistenceと組み合わせる。

## 9.3 子Agent Session

推奨Default:

- CoordinatorのAgentSessionを正本にする
- 子AgentへProcurementContextSnapshotをStructured inputとして明示的に渡す
- 子Agentは独立Sessionで実行する
- 子AgentはAgentToolResultを返し、Coordinatorが正本Sessionへmergeする

agent.as_tool(propagate_session=True)は、利用Versionで親子が同じService Sessionを安全に共有できることをCompatibility Testで証明した場合だけ有効にする。異なるAgent / Providerでservice_session_idを共有すると、remote conversation pointerが衝突する可能性があるため、無条件に有効化しない。

---

# 10. Multi-Agentの実装

## 10.1 Coordinator

- User conversationとAgentSessionのOwner
- Plan作成、再開、次Step選択
- 不足情報の確認
- 子Agent ToolへのStructured task発行
- 子Agent ResultのSchema / provenance検証
- 最終ApplicationDraftの検証と提示
- 完了条件の判定

Multi構成のCoordinatorへcatalog / account / deliveryのData Toolを直接付けない。Coordinatorが検索を迂回して独自に値を作る経路を防ぐ。

## 10.2 調達担当 Agent

論理名: procurement_specialist

入力:

~~~json
{
  "task_id": "task-proc-001",
  "plan_id": "plan-001",
  "step_ids": ["S03", "S04", "S05", "S06"],
  "context_snapshot": {},
  "required_outputs": [
    "catalog_item",
    "account_code",
    "delivery_estimate",
    "evidence_refs"
  ]
}
~~~

責務:

- 商品カタログ検索
- 商品候補の比較
- 商品コード、単価、在庫の確定
- 勘定科目、部門、申請者の照会
- 納期の照会
- 根拠付きStructured Resultの返却

禁止:

- Userへ最終回答する
- 申請ドラフトを完成扱いにする
- Toolにない商品、価格、コードを補完する

## 10.3 起案担当 Agent

論理名: drafting_specialist

責務:

- 調達担当ResultとUser requestからApplicationDraftを組み立てる
- request-check Skillで合計金額を計算する
- validate_applicationで完全性と整合性を検証する
- 根拠と警告を保持したStructured Resultを返す

禁止:

- catalog / account Toolを直接呼ぶ
- 調達担当のevidenceを捨てる
- Skillを使わず金額を作る
- Userへ最終回答する

## 10.4 Hosted Multi

~~~python
procurement_tool = procurement_specialist.as_tool(
    name="procurement_specialist",
    description="商品、価格、コード、納期を根拠付きで照会する",
    arg_name="task"
)

drafting_tool = drafting_specialist.as_tool(
    name="drafting_specialist",
    description="照会結果から検証済み申請ドラフトを作成する",
    arg_name="task"
)
~~~

Coordinatorにはprocurement_toolとdrafting_toolだけを登録する。Plan上の順序はprocurement_specialist → drafting_specialistで固定し、並列実行しない。

## 10.5 Prompt Multi

Prompt Coordinatorへ、調達担当Prompt Agentと起案担当Prompt AgentをA2A Agent ToolまたはFoundryが提供するAgent Toolとして登録する。Tool input / outputはHostedのAgentToolResult Schemaと一致させる。

この接続を「Agent Framework as_tool」と記録してはいけない。Traceのimplementation_kindはremote_agent_toolまたはa2a_agent_toolとする。

---

# 11. Agent Governance Toolkit

## 11.1 組み込み位置

governance.pyでAgent Governance Toolkitを初期化し、middleware.pyから次の4段階を呼ぶ。

| Stage | 実行位置 | 主な判定 |
|---|---|---|
| pre_input | User入力をPlanへ入れる前 | injection、入力Schema、禁止データ |
| pre_tool | Tool / Agent Tool / Skill実行前 | role allowlist、引数、重複、回数、承認 |
| post_tool | Tool OutputをSessionへ入れる前 | Schema、PII、provenance、Business status |
| pre_output | Userへresponseを返す前 | 必須項目、金額一致、根拠、漏えい、終了条件 |

Agent Governance ToolkitはFoundryのControl PlaneやRBACを置き換えない。Application内の実行時Policy、監査、検証レイヤーとして組み込む。

## 11.2 policy.yamlの最低Rule

- CoordinatorはMulti構成でData Toolを直接呼べない
- procurement_specialistだけがcatalog / account / delivery Toolを呼べる
- drafting_specialistはrequest-check Skillとvalidate_applicationだけを呼べる
- calculate_total StepはSkill script由来のOutputを必須とする
- Tool Outputに存在しないproduct_code / account_codeをresponseへ出せない
- 同一Plan version / Step / input_hashの重複Tool Callをdenyまたはflagする
- 必須情報不足時はWAITING_USERを要求する
- validation pass前のpresent_draftをdenyする
- plan COMPLETED後の再実行をdenyする
- Tool Call上限、子Agent委譲回数上限を設定する
- Synthetic canary、Secret pattern、個人情報をpre_outputで検査する

## 11.3 Rollout

1. audit-only
2. shadow / advisory
3. enforce

PoCのFailure評価では、Agentを完走させる必要があるため、Injection CaseによってはGovernanceをshadowにし、would_denyをTraceへ残す。Governanceが実際に阻止するHard Gate Testは別Suiteで実施する。

Governance Span / Eventにはpolicy_version、rule_id、stage、decision、reason、agent_role、tool_name、plan_id、step_idを記録する。

---

# 12. Source構成

ユーザー想定構成を最小骨格として維持し、Data、Test、Prompt Agent deploymentを追加する。

~~~text
src/procurement_agent/
  agent.py
  models.py
  tools.py
  memory.py
  middleware.py
  governance.py
  policies/
    policy.yaml
  skills/
    request-check/
      SKILL.md
      scripts/
        calculate_request.py
        validate_request.py
      references/
        calculation-rules.md
  devui_app.py
  observability.py
~~~

推奨Repository全体:

~~~text
.
├─ pyproject.toml
├─ README.md
├─ azure.yaml
├─ .env.example
├─ src/
│  ├─ procurement_agent/
│  │  ├─ agent.py
│  │  ├─ models.py
│  │  ├─ tools.py
│  │  ├─ memory.py
│  │  ├─ middleware.py
│  │  ├─ governance.py
│  │  ├─ observability.py
│  │  ├─ devui_app.py
│  │  ├─ policies/policy.yaml
│  │  └─ skills/request-check/
│  │     ├─ SKILL.md
│  │     ├─ scripts/calculate_request.py
│  │     ├─ scripts/validate_request.py
│  │     └─ references/calculation-rules.md
│  ├─ prompt_agents/
│  │  ├─ single.yaml
│  │  ├─ multi_coordinator.yaml
│  │  ├─ procurement_specialist.yaml
│  │  └─ drafting_specialist.yaml
│  ├─ trace_pipeline/
│  │  ├─ envelope.py
│  │  ├─ normalize.py
│  │  ├─ completeness.py
│  │  └─ appinsights_reader.py
│  └─ evaluation/
│     ├─ runner.py
│     ├─ deterministic/
│     ├─ foundry.py
│     ├─ rubric.py
│     └─ report.py
├─ data/
│  ├─ catalog.json
│  ├─ account_codes.json
│  ├─ departments.json
│  ├─ delivery_rules.json
│  ├─ applicants.json
│  └─ tax_rules.json
├─ failure_profiles/
│  ├─ healthy.yaml
│  └─ *.yaml
├─ trace_fixtures/
│  ├─ positive/
│  └─ negative/
├─ infra/
├─ scripts/
│  ├─ deploy_prompt_agents.py
│  ├─ deploy_hosted_agents.py
│  ├─ configure_observability.py
│  ├─ run_eval_matrix.py
│  └─ cleanup.py
├─ tests/
│  ├─ unit/
│  ├─ contract/
│  ├─ trace/
│  └─ integration/
└─ artifacts/
   ├─ traces/
   ├─ envelopes/
   ├─ eval-results/
   └─ reports/
~~~

## 12.1 ファイル責務

| File | 責務 |
|---|---|
| agent.py | 4 PatternのFactory、Plan Executor、Coordinator / Specialist定義 |
| models.py | Domain、Plan、Tool、Trace用Schema |
| tools.py | Port、JSON Adapter、Functions / Search Adapter |
| memory.py | Context Provider、AgentSession serialize / restore / merge |
| middleware.py | Tool、Agent Tool、Model、Governanceの共通Middleware |
| governance.py | Agent Governance Toolkit Adapter、Policy load、decision export |
| policy.yaml | Role、Tool、Step、approval、output Rule |
| skills/request-check | 計算・申請検証Skill |
| devui_app.py | HA-S / HA-Mを同じFactoryでDevUIへ公開 |
| observability.py | OTel初期化、Span helper、Attribute sanitize、Exporter |

agent.pyが肥大化した場合だけagents/配下へCoordinatorとSpecialistを分割する。外部Entry pointはagent.pyに維持する。

---

# 13. 正常フロー

## 13.1 Single

1. User requestを受ける
2. Planを作成する
3. 不足情報を確認する
4. search_catalogを呼ぶ
5. get_catalog_itemで商品、単価、在庫を確定する
6. get_applicant / lookup_departmentを呼ぶ
7. lookup_account_codeを呼ぶ
8. estimate_deliveryを呼ぶ
9. request-check Skillで合計を計算する
10. ApplicationDraftを作る
11. validate_applicationとGovernance pre_outputを通す
12. 申請内容を提示する
13. PlanをCOMPLETEDにする

## 13.2 Multi

1. Coordinatorが依頼を受けPlanを作成する
2. 不足情報をUserへ確認する
3. procurement_specialistをAgent Toolとして呼ぶ
4. 調達担当が検索・照会しStructured Resultを返す
5. CoordinatorがSchemaと根拠を検証する
6. drafting_specialistをAgent Toolとして呼ぶ
7. 起案担当がSkill計算、Draft作成、検証を行う
8. Coordinatorが子Agent ResultとPlanを突合する
9. Coordinatorが申請内容を提示する
10. PlanをCOMPLETEDにする

## 13.3 Sequence

~~~mermaid
sequenceDiagram
    participant U as User
    participant C as Coordinator
    participant P as 調達担当
    participant D as 起案担当
    participant T as Tool / Skill
    U->>C: 購買依頼
    C->>C: Plan作成・不足確認
    C->>P: agent-as-tool
    P->>T: カタログ・コード・納期照会
    T-->>P: 根拠付き結果
    P-->>C: ProcurementResult
    C->>D: agent-as-tool
    D->>T: 計算Skill・検証
    T-->>D: 合計・Validation
    D-->>C: ApplicationDraft
    C->>C: 最終検証・終了判定
    C-->>U: 申請内容
~~~

---

# 14. OpenTelemetry設計

## 14.1 Span tree

Hosted Multiの期待例:

~~~text
agent.invoke coordinator
├─ governance.pre_input
├─ plan.create
├─ plan.step.execute resolve_missing_fields
├─ plan.step.execute procurement_lookup
│  ├─ governance.pre_tool
│  ├─ agent_as_tool procurement_specialist
│  │  ├─ tool.search_catalog
│  │  ├─ tool.get_catalog_item
│  │  ├─ tool.lookup_account_code
│  │  └─ tool.estimate_delivery
│  └─ governance.post_tool
├─ plan.step.execute build_draft
│  ├─ agent_as_tool drafting_specialist
│  │  ├─ skill.request_check
│  │  │  └─ script.calculate_request
│  │  └─ tool.validate_application
│  └─ governance.post_tool
├─ governance.pre_output
└─ response.generate
~~~

Prompt AgentではManaged Runtimeが生成するAgent / Model / Tool / A2A Spanを正本にする。作成できない内部Step Spanを存在したように補わない。Client側で観測可能なplan / evaluation Spanと、poc.run.id等のCorrelation Keyで束ねる。

## 14.2 共通Attribute

OpenTelemetry semantic conventionsの標準Fieldを優先し、業務Fieldにはpoc. prefixを付ける。

~~~text
poc.run.id
poc.case.id
poc.pattern
poc.agent.role
poc.agent.definition.id
poc.implementation.kind
poc.session.id_hash
poc.conversation.id_hash
poc.turn.index
poc.plan.id
poc.plan.version
poc.plan.status
poc.step.id
poc.step.type
poc.step.status
poc.step.attempt
poc.resume.reason
poc.tool.logical_name
poc.tool.call_index
poc.tool.input_hash
poc.tool.business_status
poc.skill.name
poc.skill.version
poc.policy.version
poc.policy.rule_id
poc.policy.decision
poc.validation.status
poc.semantic.status
poc.failure.profile
~~~

Raw user input、prompt、tool arguments、tool outputをAttributeへ直接入れない。Synthetic評価環境のProtected Content StoreまたはTrace content recordへ保存し、Custom AttributeはID、hash、enum、countを中心にする。

## 14.3 Event

- plan_created
- plan_resumed
- step_started
- step_waiting_user
- step_completed
- step_invalidated
- duplicate_step_suppressed
- agent_delegated
- agent_result_received
- evidence_attached
- skill_started
- skill_completed
- governance_decided
- validation_completed
- completion_decided
- failure_injected

## 14.4 Log

Logは次に限定する。

- 起動・設定
- Adapter選択
- Policy / Data / Skill Version
- Warning
- Exporter failure
- Correlation fallback
- Redaction実施
- Injection activated / missed

Trace評価に必要な順序と親子関係をLog timestampだけから復元しない。

---

# 15. 必須Trace情報の契約

| 必須Field | 主Source | 正規化内容 |
|---|---|---|
| user_input | User message / request event | turn、textまたはprotected ref、制約、hash |
| response | Agent output | text、structured draft、status、warnings |
| retrieved_contexts | Search / lookup output | source_id、content/ref、score、version、rank |
| system_prompt | Agent definition / content record | role、raw/ref、version、hash |
| tool_definitions | Agent definition / toolbox | name、description、schema、version、hash |
| tool_calls | Tool / Agent Tool / Skill Span | call_id、name、args/ref、order、parent、status |
| tool_output | Tool Result | business status、structured output/ref、evidence |
| agent_trace | Span tree / Plan events | agent、plan、step、delegation、validation、completion |
| conversation | Session + turn join | conversation id、turn index、messages、state transition |

## 15.1 Trace Evaluation Envelope

~~~json
{
  "schema_version": "2.0",
  "run": {
    "run_id": "run-...",
    "case_id": "SD-01",
    "pattern": "HA-M",
    "implementation_kind": "in_process_agent_as_tool"
  },
  "session": {
    "session_id_hash": "...",
    "conversation_id_hash": "...",
    "turn_count": 3,
    "resumed": true
  },
  "user_input": [],
  "response": {},
  "retrieved_contexts": [],
  "system_prompt": {},
  "tool_definitions": [],
  "tool_calls": [],
  "tool_output": [],
  "agent_trace": {
    "spans": [],
    "delegations": [],
    "governance_decisions": [],
    "validations": []
  },
  "conversation": [],
  "plan": {
    "plan_id": "plan-001",
    "version": 1,
    "status": "COMPLETED",
    "steps": []
  },
  "evaluation": {}
}
~~~

retrieved_contextsはtool_outputに埋もれさせず、Normalizerが独立Fieldへ抽出する。conversationは単一Traceではなく、同一Sessionの複数Turn / Traceをturn_index順に束ねる。

---

# 16. Silent Semantic Failure 14パターン

すべて技術StatusはSUCCESSとする。Fault Profileが発火したことをinjection_activatedで確認し、発火しなかったRunはFAILではなくINJECTION_MISSEDとする。

## 16.1 仕様・設計

| ID | 失敗 | Plan & Executeでの注入 | 主Trace | 判定 |
|---|---|---|---|---|
| SD-01 | タスク仕様の不遵守 | 3台、予算、来月まで等の制約を無視したDraftを返す | user_input、response | responseが全制約を満たすか |
| SD-02 | 役割仕様の不遵守 | CoordinatorがData Toolを直接呼ぶ、起案担当が検索する | system_prompt、tool_calls、agent_trace | role-tool allowlist |
| SD-03 | ステップの繰り返し | 完了済search_catalogまたは計算Stepを同一引数で再実行 | tool_calls、agent_trace | step / args / order重複 |
| SD-04 | 会話履歴の喪失 | Resume時に数量、申請者、選択商品を落とす | conversation、plan、session | Turn間State continuity |
| SD-05 | 終了条件の未認識 | COMPLETED後に子AgentやToolを再実行、または追加質問 | conversation、agent_trace | completion後のaction禁止 |

## 16.2 エージェント間

| ID | 失敗 | agent-as-toolでの注入 | 主Trace | 判定 |
|---|---|---|---|---|
| MA-01 | 会話のリセット | 子Agentへcontext_snapshotを渡さず、別Sessionとして初期化 | conversation、delegation、session | session / snapshot continuity |
| MA-02 | 確認を求めない | 曖昧なPC要件や申請者を推測して進める | user_input、response、plan | required clarification |
| MA-03 | タスクの逸脱 | 調達担当へ無関係な検索Taskを渡す | user_input、agent_trace | delegated task relevance |
| MA-04 | 情報の出し惜しみ | 子Agentが取得した候補、警告、根拠を返さない | agent_trace、conversation、response | required output completeness |
| MA-05 | 他Agent入力の無視 | 調達担当がinvalid / deadline missedと返すが起案・親が無視 | agent_trace、conversation、response | child result utilization |
| MA-06 | 推論と行動の不一致 | responseではSkill計算済みと主張するがTool Callなし | response、tool_calls、plan | action-response consistency |

## 16.3 タスク検証

| ID | 失敗 | 注入 | 主Trace | 判定 |
|---|---|---|---|---|
| TV-01 | 早すぎる終了 | catalog / code / skill Step前にDraftを提示しCOMPLETED | user_input、response、conversation、plan | required steps complete |
| TV-02 | 検証の欠如・不完全 | account codeまたはSkill計算を省略 | tool_calls、agent_trace、plan | verification coverage |
| TV-03 | 誤った検証 | 別商品の価格、失効コード、古い納期をvalidと判定 | tool_calls、agent_trace、response | evidence-value consistency |

## 16.4 注入方式

二段階で行う。

Stage A: Evaluator検証

- Handcrafted positive / negative Trace fixture
- 期待Labelを固定
- Deterministic EvaluatorのPrecision / Recallを測定

Stage B: Agent E2E

- Prompt fragment
- Tool Output mutation
- Session snapshot omission
- Plan state mutation
- Child Result mutation
- Middleware bypass
- Governance shadow decision

Failure ProfileはAgent種別に依存しない抽象設定と、Prompt / Hosted別Adapterに分ける。

---

# 17. Deterministic Evaluator

## 17.1 優先順位

1. Schema / required field
2. Exact value / arithmetic
3. Tool order / role allowlist
4. Provenance / evidence
5. Conversation / Plan state
6. LLM rubric

決定論で判定可能な項目をLLM Judgeへ委ねない。

## 17.2 主要Evaluator

| Evaluator | 対象 |
|---|---|
| constraint_adherence | 数量、予算、納期、カテゴリ等 |
| role_tool_compliance | Agent roleとTool / Agent Tool |
| step_sequence | 必須Stepの順序 |
| duplicate_step | 同一Step / args / input hash |
| conversation_continuity | Turn間の値とSession |
| completion_recognition | COMPLETED後のAction |
| clarification_required | 曖昧入力でのWAITING_USER |
| delegation_relevance | 子Agent TaskとUser goal |
| child_output_completeness | 子AgentのRequired Output |
| child_output_utilization | 子Agent ResultとDraft |
| response_action_consistency | response主張と実Tool Call |
| verification_coverage | 必須検証Tool / Skill |
| verification_correctness | evidenceと判定 |
| arithmetic_correctness | Script OutputとDraft |
| trace_completeness | 9 Fieldの取得率 |

## 17.3 Tool順序

Singleの正常な部分順序:

~~~text
search_catalog
  before get_catalog_item
get_catalog_item
  before calculate_request
lookup_account_code
  before validate_application
estimate_delivery
  before validate_application
calculate_request
  before validate_application
validate_application
  before present_draft
~~~

Multiの正常な部分順序:

~~~text
procurement_specialist
  before drafting_specialist
drafting_specialist
  before present_draft
~~~

完全な固定列ではなく、必要なpartial orderを判定する。独立した照会の順番違いをFalse Positiveにしない。

## 17.4 金額

~~~text
expected_subtotal = Decimal(quantity) × Decimal(unit_price)
expected_tax = round_by_rule(expected_subtotal × tax_rate)
expected_total = expected_subtotal + expected_tax
~~~

expected値はEvaluator側でも同じVersionのRuleから独立計算し、Agent response、Skill Output、Tool Outputの三者を照合する。

---

# 18. Foundry Evaluator / Rubric

Built-in Evaluatorは利用可能なCatalogを実装時に確認し、次へ割り当てる。

- Task adherence
- Intent resolution
- Tool call accuracy
- Tool output utilization
- Response completeness
- Groundedness / relevance

Rubric Evaluatorは、決定論だけでは判定しにくい次を補完する。

- PC要件の曖昧さに対する質問の適切性
- 無関係なTask drift
- 情報の出し惜しみ
- Userにとって理解可能な申請内容

Rubricはcase_id別に期待制約、必須質問、禁止事項、根拠を渡す。Judge modelとAgent modelは分離し、Judge model versionをReportへ記録する。

---

# 19. Evaluation Run Matrix

## 19.1 最小Run

| Failure group | Case数 | 対象Pattern | Runs |
|---|---:|---:|---:|
| 仕様・設計 | 5 | 4 | 20 |
| エージェント間 | 6 | 2 Multi | 12 |
| タスク検証 | 3 | 4 | 12 |
| 合計 / 1 pass | 14 |  | 44 |

Stage A fixtureとStage B E2Eを各1 pass実行するため、最小合計は88 runsとする。

Healthy controlは各Patternに最低1件追加する。非決定論評価は主要Caseをk回実行し、failure rate、first-pass success、trajectory variance、tool count variance、latency、token / costを集計する。

## 19.2 Report軸

- pattern
- implementation_kind
- agent_role
- failure_id
- injection_activated
- technical_status
- semantic_status
- deterministic result
- rubric result
- trace completeness
- plan step count
- tool / agent-tool count
- governance decision
- latency
- token / cost
- repeated-run failure rate

---

# 20. DevUI要件

devui_app.pyからHA-SとHA-Mを選択できるようにする。

- Hosted deploymentと同じbuild_agent factoryを使う
- 同じSystem Prompt、Tool、Skill、Policy、Middlewareを使う
- Demo専用の短絡ロジックを作らない
- New session / Resume sessionを選べる
- Plan、現在Step、Completed Step、Warningsを表示する
- Agent Toolの委譲結果を表示する
- Governance decisionを表示する
- Trace IDとrun IDを表示する
- Sessionのserialize / restoreを試験できる

DevUIで最低限、次を手動確認する。

1. 「開発用PCを3台、来月までに」でPlanが作られる
2. 曖昧な仕様なら質問する
3. 回答後、同じSessionで続行する
4. 調達担当 → 起案担当の順に委譲する
5. 計算Scriptの値がDraftへ反映される
6. Browser refreshまたは再接続後に許可された再開方式で続行する
7. COMPLETED後にToolを再実行しない

---

# 21. VersionとCompatibility Test

Agent Framework、Foundry SDK、Hosted Agent hosting package、Agent Governance Toolkitは別々にVersionを固定する。実装開始日に公式Releaseと互換性を再確認し、lockfileへ記録する。

必須Compatibility Test:

- AgentSession serialize / restore
- InMemoryContextProviderのTurn継続
- DevUIでの同一Session
- Hosted deploymentでのsession continuation
- child agent.as_toolのStructured I/O
- propagate_session=Falseでのsnapshot受け渡し
- propagate_session=Trueの隔離Test
- service_session_idとprevious response / conversation IDの混同防止
- Skill script runner
- Prompt AgentのToolbox Skill / calculate Function
- Prompt MultiのA2A Agent Tool
- OTel parent-child相関
- Governance Toolkit middleware
- Streaming時の重複Tool Call抑止

Compatibility Testが通らない機能はFallbackへ切り替え、known_limitations.mdに記録する。

---

# 22. 実装順

## Phase A: Domain / Local

- Pydantic Model
- Synthetic JSON
- Tool PortとJSON Adapter
- Calculation Script
- Application Validator
- Unit Test

## Phase B: Plan / Session / Harness

- ExecutionPlanとPlanExecutor
- AgentSession
- InMemoryContextProvider
- Resume / invalidation / idempotency
- 5要素Harnessの接続

## Phase C: Governance / Observability

- Agent Governance Toolkit Adapter
- policy.yaml
- OTel Span / Event / Log
- Trace Evaluation Envelope
- Sanitization

## Phase D: Hosted Agent

- HA-S
- HA-M Coordinator
- procurement_specialist agent-as-tool
- drafting_specialist agent-as-tool
- request-check SkillsProvider
- DevUI
- Hosted deployment

## Phase E: Prompt Agent

- PA-S
- PA-M Coordinator
- 調達担当Prompt Agent
- 起案担当Prompt Agent
- Remote Agent Tool / A2A
- Function / AI Search / Toolbox接続
- Foundry server-side Trace

## Phase F: Failure / Evaluation

- 14 positive / negative Trace fixtures
- 14 E2E Failure Profiles
- Deterministic Evaluator
- Foundry / Rubric Evaluator
- 88-run Matrix
- k反復
- Report

## Phase G: Production-equivalent telemetry

- Raw Content OFF
- Sanitized telemetry
- Hash / ID based Evaluator
- SKIP reason
- Sampling、retention、RBAC review

---

# 23. Acceptance Criteria

## 23.1 Agent / Plan

- [ ] 4つの論理Patternが実装される
- [ ] 8つのAgent役割定義と推奨6 Foundry Resourceの対応が明示される
- [ ] 4 Patternで同じ業務SchemaとSynthetic Dataを使う
- [ ] ReActではなく明示Planを作成・保存する
- [ ] Singleが依頼受付 → 検索 → 申請内容提示まで完走する
- [ ] MultiがCoordinator → 調達担当 → 起案担当 → 申請内容提示まで完走する
- [ ] HA-Mの子Agentがagent.as_tool()で登録される
- [ ] PA-MのRemote Agent Tool差がimplementation_kindへ記録される
- [ ] 不足情報がある場合にWAITING_USERとなる
- [ ] 同じAgentSessionから未完了Stepを再開する
- [ ] 完了済みStepを重複実行しない
- [ ] COMPLETED後にActionを再実行しない

## 23.2 Tool / Skill

- [ ] JSON DataがVersion管理される
- [ ] Local / Functions / AI Search AdapterのPortが共通である
- [ ] 商品、コード、価格、納期にevidenceが付く
- [ ] request-check SkillがScriptを使う
- [ ] 合計金額がLLM暗算ではなくScript Outputと一致する
- [ ] Tool Outputのtechnical statusとbusiness statusを分離する

## 23.3 Governance

- [ ] Agent Governance Toolkitが組み込まれる
- [ ] pre_input / pre_tool / post_tool / pre_outputがTrace化される
- [ ] Role別Tool allowlistが機能する
- [ ] ShadowとEnforceを切り替えられる
- [ ] Policy versionとrule_idが取得できる

## 23.4 Trace

- [ ] user_inputが取得・正規化される
- [ ] responseが取得・正規化される
- [ ] retrieved_contextsが独立Fieldになる
- [ ] system_promptのversion、hash、Synthetic raw/refが取得できる
- [ ] tool_definitionsのversion、hash、Synthetic raw/refが取得できる
- [ ] tool_callsの引数、順序、call ID、親Agentが取得できる
- [ ] tool_outputのbusiness statusと結果が取得できる
- [ ] agent_traceがPlan、Step、委譲、検証を含む
- [ ] conversationが複数Turn / Traceを束ねる
- [ ] Plan / Agent Tool / Skill / Governanceの相関が取れる
- [ ] Prompt Agentに存在しないCustom Spanを存在したように扱わない

## 23.5 Failure Evaluation

- [ ] 14 FailureのTrace fixtureでEvaluator Testが通る
- [ ] 14 FailureがE2E Failure Profileで再現される
- [ ] 技術StatusはSUCCESS、Semantic StatusはFAILとなる
- [ ] INJECTION_MISSEDを区別できる
- [ ] Healthy controlに対するFalse Positiveを測定できる
- [ ] 88-run Matrixを実行できる
- [ ] k反復で非決定論を測定できる

## 23.6 DevUI / Security

- [ ] HA-SとHA-MがDevUIで動作する
- [ ] DevUIでSessionを継続・再開できる
- [ ] 実データ・実Secretを使用しない
- [ ] Synthetic canary leakageをHard Gateにする
- [ ] Production相当ではRaw ContentをOFFにする
- [ ] Custom AttributeとBaggageへSensitive Dataを入れない

---

# 24. Codexが最終提出する成果物

1. 実装Repository
2. 4 logical Pattern / 8 Agent role definitions
3. Plan Schema / Executor
4. AgentSession / Context Provider
5. Synthetic JSON Data
6. Tool Port / Adapter
7. request-check Skill / Script
8. Agent Governance Toolkit統合
9. DevUI application
10. Failure Profiles
11. Trace fixtures
12. Trace Evaluation Envelope schema
13. App Insights Trace exporter / normalizer
14. Deterministic Evaluators
15. Foundry Evaluation integration
16. Rubric
17. Unit / Contract / Trace / Integration tests
18. Infrastructure / deployment scripts
19. README
20. Architecture / Harness / Observability / Evaluation docs
21. JSON / CSV / Markdown comparison report
22. Known limitations
23. Cleanup手順

---

# 25. 実装前に残る確認事項

回答がなくてもSynthetic DefaultでLocal実装を開始できる。Azure適用前に次を確定する。

1. 使用するAzure Subscription / Region / Foundry Project
2. 使用するModel deploymentとJudge model
3. 既存Application Insights / Log Analyticsを使うか、PoC専用を作るか
4. Synthetic評価環境でContent Recordingを有効にするか
5. PA-Mで利用可能なRemote Agent ToolがA2AかManaged Agent Toolか
6. Foundry Skills previewをPAで使うか、計算Functionだけで比較するか
7. 商品検索を最初からAzure AI Searchにするか、JSON / Functionsから開始するか
8. Agent Governance Toolkitを最初からenforceにするか、shadowから開始するか
9. MVPを申請ドラフト提示で止めるか、Synthetic submitまで含めるか
10. HostedのAgentSessionをFoundry session persistenceだけで保存するか、Application storeも併用するか

推奨Default:

- Local JSON → Azure Functions / Toolbox → 必要時にAzure AI Search
- HA-Mはin-process agent.as_tool()
- PA-MはA2A Agent Tool
- Coordinator Sessionを正本、子Agentは独立Session
- Context Snapshotを明示入力
- propagate_session=False
- Governanceはshadowで評価後、Hard Gate Caseだけenforce
- MVP終了点は検証済み申請ドラフトの提示
- Synthetic評価環境だけContent Recording ON

---

# 26. 公式参照資料

## Microsoft Agent Framework

- Overview  
  https://learn.microsoft.com/en-us/agent-framework/overview/
- Agent Harness  
  https://learn.microsoft.com/en-us/agent-framework/concepts/harness
- Agent Session  
  https://learn.microsoft.com/en-us/agent-framework/concepts/agents/conversations/session
- Context Providers  
  https://learn.microsoft.com/en-us/agent-framework/concepts/agents/conversations/context-providers
- Runtime Context / propagate_session  
  https://learn.microsoft.com/en-us/agent-framework/concepts/agents/middleware/runtime-context
- Agent Skills  
  https://learn.microsoft.com/en-us/agent-framework/agents/skills
- Agent Tools  
  https://learn.microsoft.com/en-us/agent-framework/agents/tools/
- Agent observability  
  https://learn.microsoft.com/en-us/agent-framework/agents/observability
- Hosted Agents  
  https://learn.microsoft.com/en-us/agent-framework/hosting/foundry-hosted-agent
- Releases  
  https://github.com/microsoft/agent-framework/releases

## Microsoft Foundry Agent Service

- Agent Service overview  
  https://learn.microsoft.com/en-us/azure/foundry/agents/overview
- Hosted Agents  
  https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agents
- Tool catalog  
  https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/tool-catalog
- Azure AI Search Tool  
  https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/ai-search
- Azure Functions Tool  
  https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/azure-functions
- Function calling  
  https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/function-calling
- Skills  
  https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/skills

## Foundry Observability / Evaluation

- Agent tracing overview  
  https://learn.microsoft.com/en-us/azure/foundry/observability/concepts/trace-agent-concept
- Set up tracing  
  https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-setup
- Client-side tracing  
  https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-client-side
- Agent evaluation  
  https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/evaluate-agent
- Agent evaluators  
  https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/agent-evaluators
- Rubric evaluators  
  https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/rubric-evaluators
- Application Insights data model  
  https://learn.microsoft.com/en-us/azure/azure-monitor/app/data-model-complete

## Agent Governance Toolkit

- Repository  
  https://github.com/microsoft/agent-governance-toolkit
- Tutorials  
  https://github.com/microsoft/agent-governance-toolkit/blob/main/docs/tutorials/README.md
- Multi-stage Policy Pipeline  
  https://github.com/microsoft/agent-governance-toolkit/blob/main/docs/tutorials/37-multi-stage-pipeline.md
- OTel observability  
  https://github.com/microsoft/agent-governance-toolkit/blob/main/docs/tutorials/40-otel-observability.md
- FAQ  
  https://github.com/microsoft/agent-governance-toolkit/blob/main/docs/FAQ.md

---

# 27. Done Definition

- [ ] LocalでPlan & Executeが動作する
- [ ] InMemoryContextProvider / AgentSessionで続きから再開できる
- [ ] JSON Catalog / Code / Price / Deliveryが決定論的に動く
- [ ] 4 logical Patternが実装される
- [ ] HA-Mの子Agentがagent-as-toolで動く
- [ ] PA-MのRemote Agent Tool差が明記される
- [ ] request-check Skill scriptが合計金額を計算する
- [ ] Agent Governance ToolkitがPolicyを評価する
- [ ] 5要素Harnessが実装される
- [ ] HA-S / HA-MがDevUIで動く
- [ ] 9種類のTrace情報がEnvelopeへ入る
- [ ] Plan Step、Tool、Skill、GovernanceがSpan相関される
- [ ] 14 Failure fixtureのEvaluatorが正答する
- [ ] 14 E2E Failure ProfileがSilent Failureを再現する
- [ ] 88-run MatrixのReportを生成できる
- [ ] Foundry Evaluatorと独自Evaluatorを並べられる
- [ ] k反復の非決定論Reportを生成できる
- [ ] Production相当のContent OFF Testができる
- [ ] Cleanupが既存Resourceを削除しない
- [ ] READMEだけで再現できる

以上。
