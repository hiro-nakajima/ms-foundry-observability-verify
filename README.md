# Microsoft Foundry Procurement Agent Observability / Evaluation PoC

架空データだけを使う購買支援Agentの比較Repositoryです。正本は
`docs/codex-handoff-foundry-procurement-observability-evaluation-poc-2026-08-28.md`
です。AgentはReActではなく、保存・再開可能なPlan & Executeとして実装します。

このcheckoutは**最初のCodex Task**までを実装しています。HA-S / HA-MのLocal実行と
DevUI scaffoldは利用できます。PA-S / PA-M、14 Failure Evaluator、88-run Matrix、Azure
deploymentはReview後のTaskで実装します。Azure Resource作成、Role付与、設定変更、
deployment、削除は実行していません。

## 実装済みの範囲

- Pydantic Domain Model、`ExecutionPlan`、`PlanStep`
- Version付きSynthetic JSON 6種と8つの論理Tool契約
- `AgentSession` serialize / restore、部分invalidation、重複Step抑止
- Pydantic `AgentPlanResponse`を使う計画専用`response_format`
- 空のStructured responseを以前のSessionから補わない決定論的fallback
- `request-check` Skill、Decimal計算、検証Script、許可済みScript runner
- Agent Governance Toolkitの4 stage policy、shadow / enforce
- 9 Trace Field envelopeとOpenTelemetry Span / Event helper
- HA-S Local Plan & Execute
- HA-M Coordinatorと2つの`agent.as_tool(propagate_session=False)`
- 同じAgent Factoryを使うAgent Framework DevUI / Responses host scaffold
- Azure OpenAI Structured OutputによるDevUIの自然言語受付
- 不足項目確認、部門候補の曖昧性解消、明示的な`確定`、同一Plan / Sessionでの継続ターン

## Setup

Foundryのsource-code deployment runtimeに合わせ、Python 3.13を推奨します。Project自体は
Python 3.13 / 3.14を許可します。依存関係の入口は`requirements.txt`、完全なVersion制約は
`requirements-lock.txt`、Test依存は`requirements-dev.txt`です。`uv`は不要です。

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python -m pytest -q
```

`pyproject.toml`のruntime dependencyはwheel metadata用のmirrorです。Testで
`requirements.txt`との一致を検証し、依存関係の変更は両方を同時に更新します。

## DevUI

自然言語入力にはAzure OpenAI endpointとmodel deploymentが必要です。認証は既定で
`DefaultAzureCredential`を使用します。Localでは先に`az login`し、次の環境変数を設定します。
API keyを明示する場合だけ`AZURE_OPENAI_API_KEY`も使用できますが、Repositoryや`.env`へ
Secretを保存しないでください。

```bash
export AZURE_OPENAI_ENDPOINT="https://<resource>.openai.azure.com"
export AZURE_OPENAI_CHAT_MODEL="<model-deployment-name>"
export AZURE_OPENAI_API_VERSION="<supported-api-version>"  # 必要な場合だけ
export AZURE_OPENAI_TIMEOUT_SECONDS="90"
export AZURE_OPENAI_REASONING_EFFORT="minimal"  # gpt-5-mini 2025-08-07の低遅延設定
export AZURE_OPENAI_MAX_OUTPUT_TOKENS="2048"
```

その後、HA-SまたはHA-Mを選択します。

```bash
.venv/bin/procurement-devui --pattern HA-S
.venv/bin/procurement-devui --pattern HA-M
```

DevUIには自然言語で入力できます。たとえば最初に次のように入力します。

```text
開発用ノートPCを購入したい
```

AgentはLLMのStructured Outputを`ProcurementTurnExtraction(BaseModel)`として受け取り、
Plannerも`AgentPlanResponse(BaseModel)`を返します。アプリケーションは承認済みTemplateと照合後に
実行Planを保存して、ステップ列と不足項目を表示します。
不足項目は一度に全部でも、1項目ずつでも回答できます。自然言語の解釈InvocationにはToolを
登録せず、空の結果は安全な既定値として扱って現在の不足項目を再質問します。

```text
数量は3台、部門は開発一部、申請者は山田太郎、用途は開発、希望納期は2026-09-30です
```

部門に`情報シス`のような複数候補がある場合は、Synthetic Dataの正式名称と部門コードを候補表示し、
`情報システム1部` / `情報システム2部`などの選択を求めます。LLMは候補を勝手に確定できません。
すべての情報が揃うと検証済みDraftを表示しますが、この時点ではPlanは`WAITING_USER`です。
内容を確定するときは次のように入力します。

```text
確定
```

確定前に数量などを変更した場合は、影響Stepだけを`INVALIDATED`にして再計算・再検証し、
更新後のDraftに対して改めて`確定`を求めます。

LLMはユーザーが明示した数量、申請者、部門、用途、希望納期などを
`ProcurementRequestPatch`へ抽出するだけです。商品コード、単価、納期見込、勘定科目、
合計金額は推測せず、Structured Toolと計算Scriptで確定します。
自動実行やContract確認では、次の`ProcurementRequest` JSONも引き続き入力できます。

```json
{
  "request_id": "REQ-DEMO-001",
  "query": "開発用ノートPC",
  "quantity": 3,
  "applicant_name": "山田太郎",
  "department_name": "開発一部",
  "purpose": "開発",
  "constraints": {
    "requested_by": "2026-09-30",
    "budget_limit": null,
    "specifications": {}
  }
}
```

自然言語応答にはPlan、現在の入力待ち、完了Step、Agent Tool委譲、Governance decision、
Trace ID、Warning、Session resumeを表示します。正規化された機械応答はFramework Sessionの
`last_machine_response`にも保持します。JSON入力時は従来どおり`observability`を含むJSONを
返します。JSON Contractは自動実行用途のため、検証成功後に`STRUCTURED_API`確認として完了し、
対話的な`確定`Turnは要求しません。

DevUIを起動せずFactoryだけを検査するsmoke command:

```bash
.venv/bin/procurement-devui --pattern HA-M --smoke
.venv/bin/procurement-hosted --pattern HA-M --smoke
```

## Test suites

```bash
.venv/bin/python -m pytest -q tests/unit
.venv/bin/python -m pytest -q tests/contract
.venv/bin/python -m pytest -q tests/trace
.venv/bin/python -m pytest -q tests/integration
```

実Azure OpenAIに対する最小Structured Output smoke testは明示的に有効化します。Repositoryの
`.env.azure.local`はgit対象外のローカル設定です。Secretは保存せず、`az login`のCredentialを
使用します。

```bash
set -a
source .env.azure.local
set +a
PROCUREMENT_RUN_EXTERNAL_LLM=1 .venv/bin/python -m pytest -q \
  tests/external/test_azure_openai_intake.py
```

外部Credentialを必要とするFoundry/Azure testはこのTaskでは作動対象外です。LLM境界は同じ
`BaseChatClient`契約のFake Clientで、`BaseModel response_format`、Toolなし、Session継続を検証します。
Domain、Tool、Plan、Session、Governance、Trace、Agent Tool、DevUI entrypointはLocalで検証します。

## Security and data boundary

- `data/`はすべて`synthetic: true`で、実社員、実価格、実Secretを含みません。
- Raw contentはSynthetic環境かつ明示opt-inの場合だけprocess-local content storeへ記録します。
- Production相当はRaw OFFで、Trace attribute / baggageにはhash、ID、statusだけを入れます。
- Script runnerは`calculate_request.py`と`validate_request.py`だけをshellなしで実行します。
- HTTP/technical statusとbusiness statusを別Fieldで記録します。
- Chain-of-ThoughtはModel、Session、TraceのSchemaにありません。

設計は[architecture-first-task.md](docs/architecture-first-task.md)、Version選定は
[dependency-versions.md](docs/dependency-versions.md)、未実装境界は
[known-limitations.md](docs/known-limitations.md)を参照してください。
