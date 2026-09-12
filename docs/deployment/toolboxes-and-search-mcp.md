# Toolbox 2つとAzure AI Search MCP tool

このPoCではSearch serviceを直接公開する独自MCP serverを追加しない。Foundry Toolboxのbuilt-in `azure_ai_search` toolへ既存Search connection/indexを設定し、Toolboxが公開するMCP endpointをPrompt Agentから利用する。

```text
Prompt Agent
  → Toolbox versioned MCP endpoint
    → azure_ai_search tool
      → Foundry project Search connection (Managed Identity)
        → Azure AI Search index
```

## Search connection

| 設定 | 値 |
| --- | --- |
| name | `procurement-search-connection` |
| category | `CognitiveSearch` |
| target | `PROCUREMENT_SEARCH_ENDPOINT` |
| auth | Project Managed Identity |
| audience | `https://search.azure.com` |

Search admin keyは使わない。Foundry project system MIへ各index scopeの`Search Index Data Reader`を付ける。Toolboxがindex definitionを読むために必要なread-only metadata roleもindex scopeへ限定する。document更新権限は付けない。

## Toolbox定義

| Toolbox | Tool name | Index | Query |
| --- | --- | --- | --- |
| `catalog-search-toolbox` | `catalog_search` | `procurement-catalog-v1` | simple、top 10 |
| `code-master-toolbox` | `code_master_search` | `procurement-code-master-v1` | simple、top 10 |

正本は`infra/foundry/toolboxes/*.yaml`。各toolに一意なname/descriptionを設定し、1つのToolboxが別indexを照会しないよう分離する。

## 作成

`scripts/deploy_foundry.py children`は次を順に行う。

1. Search connectionをread-backし、異なる既存設定なら停止
2. ToolboxがなければYAMLからversion 1を作成
3. versioned MCP endpoint用RemoteTool connectionを作成
4. 対応Prompt Agent versionを作成

```bash
PYTHONPATH=src/hosted-agent:scripts .venv/bin/python scripts/deploy_foundry.py children
```

ToolboxだけをPortalで作る場合は、上表とYAMLの値を設定してpublishし、versioned endpointを取得する。endpoint形式は次のとおり。

```text
https://<account>.services.ai.azure.com/api/projects/<project>/toolboxes/<toolbox>/versions/<version>/mcp?api-version=v1
```

## MCPとしてのverify

HTTP MCP clientはinitializeしてから`tools/list`を実行する。次を満たすまでPrompt Agentへ接続しない。

- HTTP 200
- tool数が1
- tool name、description、`inputSchema.properties`が存在
- `tools/call`が`isError=false`
- responseが対象indexのSynthetic source version/documentだけを含む

Toolbox versionはimmutableとして扱い、変更時は新versionを作る。旧versionを削除せず、Prompt Agent側で明示versionを切り替える。

公式資料:

- [Create and manage a toolbox](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/toolbox)
- [Toolbox overview and supported tools](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/toolbox-overview)
- [Connect agents to MCP endpoints](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/how-to/tools/model-context-protocol)
