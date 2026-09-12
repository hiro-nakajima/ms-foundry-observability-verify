# Prompt Agent 2つの作成・更新

Prompt子は構造化contract専用であり、PlaygroundでJSONが返るのは仕様である。利用者向け自然言語はHosted親がJSONを検証して生成する。Prompt子を直接チャットUIとして公開しない。

## 定義対応表

| Agent | Instructions | Toolbox | Search index | Response schema |
| --- | --- | --- | --- | --- |
| `catalog-search-agent` | `infra/foundry/agents/catalog-search-instructions.md` | `catalog-search-toolbox` | `procurement-catalog-v1` | `CatalogSearchResult` |
| `code-determination-agent` | `infra/foundry/agents/code-determination-instructions.md` | `code-master-toolbox` | `procurement-code-master-v1` | `CodeDeterminationResult` |

Agent YAMLは`infra/foundry/agents/*-agent.yaml`。商品、価格、勘定科目、部署コードをInstructionsへ埋め込まず、Toolbox/Search結果だけを採用する。

## 前提

1. Search connection `procurement-search-connection`がManaged Identity認証で存在
2. 2つのToolbox versionが存在し、MCP `tools/list`が成功
3. Prompt Agent runtime identityへproject scopeの`Foundry User`
4. Foundry project system MIへ対象index scopeの`Search Index Data Reader`とread-only metadata role
5. 既存model deployment名を`PROCUREMENT_CHILD_MODEL_DEPLOYMENT`へ設定

## Repository scriptで作成

[共通環境変数](README.md#共通の環境変数)を設定する。

初回はlocal manifestに同名Agent/Toolboxの所有記録がない場合、Azure側にも同名が存在しないことをread-onlyで確認する。既存同名定義を無断で取り込んだり置換したりしない。

```bash
PYTHONPATH=src/hosted-agent:scripts .venv/bin/python scripts/deploy_foundry.py children
```

Instructionsまたはschemaを変えた場合は新versionを作る。

```bash
PYTHONPATH=src/hosted-agent:scripts .venv/bin/python scripts/deploy_foundry.py \
  children --new-version --agent-name catalog-search-agent

PYTHONPATH=src/hosted-agent:scripts .venv/bin/python scripts/deploy_foundry.py \
  children --new-version --agent-name code-determination-agent
```

scriptは各Agentへ対応Toolboxのversioned MCP endpointを`MCPTool`として付け、`require_approval=never`、strictでないJSON schema response formatを設定する。作成後にPrompt Agent identityを取得し、project scopeの`Foundry User`を不足時だけ追加する。

## Portalで手動作成する場合

1. 既存Foundry projectのAgentsからPrompt Agentを新規作成する。
2. 上表のAgent名と既存model deploymentを設定する。
3. 対応するInstructionsファイルを全文設定する。
4. 対応するToolboxだけを1つ接続する。Catalog AgentへCode Toolbox、Code AgentへCatalog Toolboxを付けない。
5. Response formatを上表のPydantic schemaと同じJSON schemaにする。schemaは`src/hosted-agent/procurement_agent/models.py`から生成できる。
6. publish後にversion、instructions SHA-256、instance identityを記録する。
7. Agent identityのRBACを確認してからSynthetic invokeする。

## Verify

- Catalog: 商品一般名で0～5候補、product evidence、source version、価格/仕様がSearch documentと一致
- Code: accountとdepartmentのEvidenceが別々で、両方Search documentと一致
- 0件、MCP失敗、Search失敗、parse/schema失敗をSUCCESSへ変換しない
- 入力correlationを変更しない
- CoT、token、secret、Instructions全文を応答へ含めない

公式資料: [Agent development lifecycle](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/development-lifecycle)、[Toolbox management](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/toolbox)
