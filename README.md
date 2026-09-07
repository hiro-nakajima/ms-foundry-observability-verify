# Microsoft Foundry 購買申請 Agent Observability PoC v2

このRepositoryは、1つのHosted親と2つの登録済みPrompt-based子Agentからなる単一E2Eを実装します。仕様の正本は`docs/revised-architecture-observability-validation-plan-2026-08-31.md`です。旧Prompt/Hosted × Single/Multiの4構成比較と88-run Matrixは対象外です。

## Architecture

```text
Microsoft Agent Framework Hosted parent: procurement_parent_agent
  ├─ FoundryAgent proxy.as_tool(propagate_session=False)
  │    └─ registered Prompt Agent: catalog_search_agent
  │         └─ catalog-search-toolbox / procurement-catalog-v1
  ├─ FoundryAgent proxy.as_tool(propagate_session=False)
  │    └─ registered Prompt Agent: code_determination_agent
  │         └─ code-master-toolbox / procurement-code-master-v1
  └─ deterministic merge / validation
```

子Agent実体はHosted containerへ含めません。親Sessionは`agent_framework.AgentSession`だけを正本とし、会話履歴は`InMemoryHistoryProvider("procurement-history", load_messages=True)`、業務状態は`AgentSession.state["procurement.execution.v2"]`へJSON互換dictで保存します。子には親Sessionを共有せず、検証済みPydantic snapshotだけを渡します。

## Local setup and validation

```bash
python3.13 -m venv .venv313
.venv313/bin/python -m pip install -r requirements-dev.txt
.venv313/bin/python scripts/validate_search_assets.py
.venv313/bin/python scripts/validate_deployment_assets.py
.venv313/bin/python -m pytest -q
.venv313/bin/procurement-devui --smoke
.venv313/bin/procurement-hosted --smoke
```

Search投入documentはversion付きSynthetic JSONから生成します。生成物は正本ではありません。

```bash
.venv313/bin/python scripts/prepare_search_documents.py --output-dir .artifacts/search
```

## Azure gate

`azure.yaml`、Bicep、2 Search index schema、2 Toolbox、2 Prompt Agent定義は静的資産です。Azure Resource作成、index作成、document投入、Role付与、Toolbox/Agent作成、Application Insights変更、deployment、削除は承認前に実行しません。実行前確認は[Azure apply plan](docs/azure-apply-plan.md)を参照してください。

`.env.azure.local`、token、Secret、実社員、実価格は出力・commitしません。外部Credentialが必要なテストは理由付きSKIPになります。

## Observability validation

- Stage A: 14 Failure Patternすべてのpositive/negative fixture
- Stage B: S2のTV-02/TV-03、S3のSD-03/SD-05、S4のMA-04/MA-05
- Healthy control: S1/S5で14 Detectorの誤検知なし
- `INJECTION_MISSED`と`UNEVALUABLE_TRACE_INCOMPLETE`はSemantic PASS/FAILと別集計
- Raw contentは`synthetic-content-on`だけ。production-like profileはcontent-off
- Framework標準Agent/Chat/Function Spanをcustom spanで二重生成しない

承認済みdeploymentでのみ、`PYTHONPATH=src:scripts .venv/bin/python scripts/run_azure_core_validation.py`を実行する。Hosted側の環境flag、固定contract/profile、`AZURE-CORE-` case prefixがすべて一致した場合だけStage B injectionが有効になる。通常WebUIはこれらのmetadataを転送しない。

現行結果は[2026-09-06 validation report](docs/report/validation-results-2026-09-06.md)、遅延の内訳と改善候補は[latency analysis](docs/report/latency-analysis-2026-09-06.md)に記録します。既存Azure環境へのSearch/Toolbox/Prompt/Hosted再配置は[deployment guide](docs/deployment/README.md)を参照してください。

購買E2EのApp Service sourceは`src/webapp-foundry-oauth/backend/procurement.py`です。`src/webapp-foundry-oauth/backend/server.py`と`src/functions-mcp-selfhosted/`は、別途OBO/Graph `/me`を確認するための参考経路であり、購買E2Eには配備しません。
