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

HA-SまたはHA-Mを選択します。

```bash
.venv/bin/procurement-devui --pattern HA-S
.venv/bin/procurement-devui --pattern HA-M
```

Local Deterministic modeでは、モデルに自然言語を解釈させず、次の
`ProcurementRequest` JSONを入力します。これにより商品コード、単価、納期、勘定科目、
合計金額を推測しません。

```json
{
  "request_id": "REQ-DEMO-001",
  "query": "開発用ノートPC",
  "quantity": 3,
  "applicant_name": "山田太郎",
  "department_name": null,
  "purpose": "開発",
  "constraints": {
    "requested_by": "2026-09-30",
    "budget_limit": null,
    "specifications": {}
  }
}
```

応答の`observability`でPlan、現在Step、完了Step、Agent Tool委譲、Governance decision、
Trace ID、Warning、Session resumeを確認できます。

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

外部Credentialを必要とするFoundry/Azure testはこのTaskでは作動対象外です。Local fixtureで
Domain、Tool、Plan、Session、Governance、Trace、Agent Tool、DevUI entrypointを検証します。

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
