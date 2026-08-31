# First Task Architecture

確認日: 2026-08-31
対象: Repository scaffoldからHosted Agent Local / DevUI scaffoldまで

## 実行構成

```mermaid
flowchart LR
  U[自然言語またはProcurementRequest JSON] --> NI[LLM Structured Intake]
  NI -->|response_format = ProcurementTurnExtraction BaseModel<br/>tools = empty| PB[ProcurementRequestPatch]
  PB --> CP[Serialized Context Provider]
  CP --> S[Coordinator AgentSession]
  S --> P[Planner Agent]
  P -->|response_format = AgentPlanResponse<br/>tool_choice = none| E[ExecutionPlan / PlanExecutor]
  E --> HS[HA-S Structured Tools]
  E --> HM[HA-M Coordinator]
  HM -->|AgentToolTask JSON| PS[procurement_specialist.as_tool]
  PS -->|AgentToolResult JSON| HM
  HM -->|ProcurementContextSnapshot JSON| DS[drafting_specialist.as_tool]
  DS -->|AgentToolResult JSON| HM
  HS --> V[request-check Scripts / Validation]
  HM --> V
  V --> C[WAITING_USER / explicit confirmation]
  C --> O[Confirmed Draft + 9-field Trace Envelope]
```

### Plan generation boundary

`AgentPlanResponse(BaseModel)`だけをPlanner Invocationの`response_format`へ指定します。この
InvocationにはToolを登録せず、`tool_choice=none`を固定します。後続のTool実行は別Invocation
とapplication-owned loopで行うため、Structured outputとTool callが同じmodel turnで競合しません。
Azure OpenAI設定がある実行ではIntakeとPlannerが同じConfigured Chat Clientを使用します。
CredentialのないLocal Testでは同じ`BaseChatClient`契約の決定論的fixtureに差し替えます。

Modelが設定できるのは承認済みStepの`step_id`、`step_type`、`owner`、`input_refs`です。
status、attempt、timestamps、evidence、completionはModelから受け取りません。

| Structured result | Behavior |
|---|---|
| Valid approved sequence | `MODEL_STRUCTURED` |
| `{}`または`steps=[]` | `EMPTY_RESPONSE_FALLBACK` + warning |
| Schema/order/owner mismatch | deterministic template + warning |
| Plannerを使用しない | `DETERMINISTIC_DEFAULT` |

新規Planとresumeは別APIです。新規Planではselected item、evidence、draft、completed-step keyを
消去します。これにより空のmodel resultから古いSession値を再利用しません。

### Plan execution

`PlanExecutor`が`plan_version + step_id + input_hash`をidempotency keyとして保持します。
同じkeyの再実行は`DuplicateStepSuppressed`です。User入力が変わると宣言済み`input_refs`から
影響Stepと下流Stepだけを`INVALIDATED`にし、Plan versionを上げて再実行します。

不足情報は`WAITING_USER`です。Framework `AgentSession.to_dict()`でProvider stateをserializeし、
別のFactory instanceで`from_dict()`した後、application `AgentSession.restore()`から再開できます。

### DevUI conversation boundary

JSON Contractは維持しつつ、DevUIの自然言語TurnはAzure OpenAI Chat Clientへ渡し、
`ProcurementTurnExtraction(BaseModel)`のStructured Outputから`ProcurementRequestPatch`を取得します。
このInvocationはToolなし、`tool_choice=none`です。ユーザーが明示した値だけを既存Requestへmergeし、
空のStructured Outputは空Patchとして扱います。queryがまだないTurnは商品を質問し、query取得後に
`AgentPlanResponse`の計画境界へ進みます。

自然言語会話では数量、部門、申請者、用途、希望納期を順に確認します。部門の部分一致が複数ある場合、
LLM出力を確定値にせず、Version付きSynthetic Dataで候補を解決して選択を要求します。検証後は
`confirm_application`を`WAITING_USER`にし、LLMが明示的な確認を`intent=CONFIRM`として返した場合だけ
`present_draft`へ進みます。確定前の条件変更ではStructured referenceの親子関係を含めて影響Stepを
`INVALIDATED`にし、再実行・再検証後にもう一度確認を求めます。

価格、商品コード、勘定科目、納期見込、合計はintakeで抽出せず、既存Structured Toolと
`request-check` Scriptだけで確定します。自然言語本文は`pre_input`を通した後、Trace envelopeの
保護済み`user_input`とCoordinator `AgentSession`の会話Turnとして扱います。JSON入力時は従来の
machine-readable responseを返し、自然言語時だけ同じmachine responseを日本語表示へ整形します。

## Hosted Single

`hosted-procurement-single`が8つの論理Toolを持ちます。検索結果から商品コードを選択した後、
`get_catalog_item`のStructured outputでコードと単価を確定します。合計は許可済み
`calculate_request.py`、最終検証は`validate_request.py`の出力だけを使用します。

## Hosted Multi

CoordinatorのToolは次の2つだけです。

- `procurement_specialist.as_tool(propagate_session=False)`
- `drafting_specialist.as_tool(propagate_session=False)`

Coordinator Sessionが正本です。子Agentへ親Sessionを渡さず、Pydantic
`AgentToolTask`内の`ProcurementContextSnapshot`だけを入力します。戻り値の
`AgentToolResult`をSchema検証してからmergeし、Coordinatorが決定論的な最終検証を行います。
`propagate_session=True`は選択肢にしていません。

## Skill execution

Agent Framework `SkillsProvider.from_paths()`へ`AllowlistedSkillScriptRunner`を登録します。
runnerは2本の絶対パスだけを許可し、shellを使わず、JSON stdin/stdout、5秒timeout、最小環境で
subprocess実行します。HA-S/HA-Mの正常系もこのrunnerを経由します。

## Governance

Agent Governance Toolkit `PolicyEngine`を`GovernanceMiddleware`へ接続します。application loopは
`pre_input`、`pre_tool`、`post_tool`、`pre_output`を必ず通り、各decisionのpolicy version、
rule ID、stage、outcome、role、tool、plan/stepをSessionとSpanへ記録します。

defaultは`shadow`です。Hard Gate testは`enforce`を明示します。

## Observability

Spanには観測可能な実行境界、Eventには状態遷移を記録します。隠れた推論は記録しません。
Trace Evaluation Envelopeは次の9 Fieldを独立させます。

1. `user_input`
2. `response`
3. `retrieved_contexts`
4. `system_prompt`
5. `tool_definitions`
6. `tool_calls`
7. `tool_output`
8. `agent_trace`
9. `conversation`

各Run identityは`logical_pattern`、`agent_role`、`agent_definition_id`、
`foundry_resource_id`、`implementation_kind`を分離します。Localでは
`foundry_resource_id=null`です。

## Port boundary

`ProcurementToolPort`の8契約を`LocalJsonAdapter`が実装します。Azure Functions、Foundry
Toolbox/MCP、Azure AI Searchは同じPortへ差し替える前提です。AI Searchを追加しても、商品コード、
単価、納期はStructured get/estimate Toolで確定します。

## Deployment boundary

`procurement-hosted`は現行`ResponsesHostServer`を使うLocal Responses host scaffoldです。
Azure metadata、Bicep/azd、Agent Resource definitionはReview後のTaskへ延期しています。
Azure apply、Role assignment、deployment、deleteは実行していません。

将来のsource-code deploymentは`runtime: python_3_13`を使用します。Local/package metadataも
Python 3.13を基準にし、3.14は互換範囲に含めます。Container方式ではimage側runtimeを選べますが、
同一依存集合を比較できるよう本PoCでは3.13を共通基準とします。
