# functions-mcp-selfhosted

`functions-mcp-selfhosted` は、Azure Functions 上で動く self-hosted MCP Server です。現在の本線である **案A: App Service EasyAuth ユーザー委任 -> APIM -> Foundry -> OAuth Identity Passthrough -> Functions MCP Server -> OBO -> Microsoft Graph** のうち、Foundry から呼び出される MCP Server と Graph OBO 部分を担当します。

現在の推奨実行形態は **Linux Flex Consumption + Python runtime + Azure Functions ASGI Middleware + FastMCP** です。

## 全体構成での位置づけ

```text
Azure AI Foundry Agent
  ↓ OAuth Identity Passthrough
  ↓ Authorization: Bearer <token for MCP API>
Azure Functions MCP Server (/mcp)
  ↓ validate aud / tid
  ↓ On-Behalf-Of exchange
Microsoft Entra ID
  ↓ delegated Graph token
Microsoft Graph API (/me)
```

Functions は Graph token を直接受け取るのではなく、MCP API 用 token を受け取り、Functions 側で OBO 交換して Graph `/me` を呼びます。

## この MCP Server の役割

- Foundry からの MCP JSON-RPC request を `/mcp` で受ける。
- HTTP `Authorization` ヘッダーから bearer token を抽出する。
- 受信 token の `aud` / `tid` を軽量チェックする。
- MSAL の `acquire_token_on_behalf_of` で Microsoft Graph delegated token に交換する。
- `whoami` tool で Microsoft Graph `/me` を呼び、現在ユーザー情報を返す。
- `greet` tool で疎通確認を行う。

## 実装の要点

- `custom handler` は使いません。
- `FUNCTIONS_WORKER_RUNTIME=python` です。
- `azure.functions.AsgiMiddleware` で FastMCP の ASGI app を受けます。
- Flex + Python runtime では Functions runtime が Starlette lifespan を自動実行しないため、request ごとに FastMCP app / session manager を扱う実装にしています。
- `whoami` は受信した MCP API 用 token を OBO assertion として使います。
- Graph scope は `GRAPH_SCOPES` で上書きできます。
- Graph endpoint は `GRAPH_BASE_URL` で上書きできます。
- OBO 交換と Graph `/me` 呼び出しには retry / timeout を入れています。

本体コード:

- ASGI / MCP / OBO 実装: `mcp_server.py`
- Azure Functions 入口: `mcp_handler/__init__.py`
- Functions 定義: `mcp_handler/function.json`

## このRepositoryでの位置づけ

このFunctionsは購買E2Eとは別のOBO/Graph `/me`検証用sourceで、現行Azure購買経路へは配備していません。購買Agentの正本は[Repository README](../../README.md)、EasyAuth/OBO判断は[ADR](../../docs/adr-0001-easyauth-and-obo.md)、現行検証結果は[validation report](../../docs/report/validation-results-2026-09-06.md)を参照してください。

## ディレクトリ構成

```text
functions-mcp-selfhosted/
├── mcp_server.py
├── host.json
├── requirements.txt
├── local.settings.json.template
├── mcp_handler/
│   ├── __init__.py
│   └── function.json
├── infra/
│   ├── azure/
│   └── entra/
└── scripts/
    ├── deploy-functions-azure-bicep.*
    ├── deploy-functions-entra-obo.*
    ├── deploy-foundry-oauth-client-app.*
    ├── update-foundry-mcp-oauth-connection.*
    ├── remove-server-app-foundry-redirects.*
    ├── apply-function-entra-settings.*
    ├── deploy-functions-zip.*
    └── warmup-mcp-endpoint.*
```

## 必要な Entra ID 構成

Functions MCP Server から見ると、重要なのは App B です。App C は Foundry OAuth Identity Passthrough の OAuth client であり、Function App の app settings には入れません。

### App B: MCP Server API / Functions OBO 用 App Registration

- `Expose an API` で Application ID URI を設定する。
- delegated scope を公開する。
  - 例: `api://<app-b-client-id>/access_as_user`
- Client secret を作成し、Functions の confidential client として使う。
- Microsoft Graph delegated permission を追加する。
  - 例: `User.Read`
- 必要に応じて admin consent を実施する。

### App C: Foundry OAuth client 用 App Registration

- Foundry OAuth Identity Passthrough の OAuth connection で Client ID / Secret として使う。
- App B の delegated scope を API permission に追加する。
- Foundry OAuth connection 用の redirect URI を登録する。
- Foundry の Scope には App B の `api://<app-b-client-id>/access_as_user` を指定する。

## 環境変数 / app settings

`local.settings.json.template` にテンプレートがあります。

| 変数名 | 必須 | 用途 |
| --- | --- | --- |
| `FUNCTIONS_WORKER_RUNTIME` | 必須 | `python` |
| `ENTRA_TENANT_ID` | 必須 | OBO 交換に使う tenant ID |
| `ENTRA_CLIENT_ID` | 必須 | App B: MCP Server API / Functions OBO 用 App Registration の client ID |
| `ENTRA_CLIENT_SECRET` | 必須 | App B の client secret |
| `EXPECTED_TOKEN_AUDIENCES` | 推奨 | 受信 token の `aud` 許可値。カンマ区切り。例: `api://<client-id>,<client-id>` |
| `EXPECTED_TENANT_ID` | 任意 | 受信 token の `tid` 許可値。未設定時は `ENTRA_TENANT_ID` を利用 |
| `GRAPH_SCOPES` | 任意 | OBO 交換先 scope。既定値は `https://graph.microsoft.com/User.Read` |
| `GRAPH_BASE_URL` | 任意 | Graph 呼び出し先。既定値は `https://graph.microsoft.com/v1.0` |
| `OBO_MAX_RETRIES` | 任意 | OBO 交換の retry 回数。既定値は `2` |
| `OBO_RETRY_BACKOFF_SECONDS` | 任意 | OBO retry の指数バックオフ初期秒数。既定値は `0.5` |
| `GRAPH_TIMEOUT_SECONDS` | 任意 | Graph 呼び出し timeout 秒数。既定値は `15` |
| `GRAPH_MAX_RETRIES` | 任意 | Graph 呼び出し retry 回数。既定値は `2` |
| `GRAPH_RETRY_BACKOFF_SECONDS` | 任意 | Graph retry の指数バックオフ初期秒数。既定値は `0.5` |

`GRAPH_SCOPES` は `mcp_server.py` 起動時に読み込まれます。Functions の app settings を変更した場合は、Function App の再起動または新しい worker 起動後に反映されます。

## Azure リソースのデプロイ

Azure リソースは Bicep で作成します。

- テンプレート: `infra/azure/main.bicep`
- パラメータ例: `infra/azure/main.parameters.example.json`
- デプロイスクリプト:
  - `scripts/deploy-functions-azure-bicep.sh`
  - `scripts/deploy-functions-azure-bicep.ps1`

現在の既定構成は **Linux Flex Consumption / Python 3.13** です。デプロイモードは既定で `Incremental` です。差分確認だけしたい場合は `WHAT_IF=true` で `what-if` 実行に切り替えられます。

## Entra App B / App C の作成

### App B

- 設定ファイル例: `infra/entra/obo-app-config.example.json`
- デプロイスクリプト:
  - `scripts/deploy-functions-entra-obo.sh`
  - `scripts/deploy-functions-entra-obo.ps1`

作成後、出力された `clientId`、`tenantId`、`clientSecret`、audience / scope を Function App へ反映します。

### App C

- 設定ファイル例: `infra/entra/foundry-oauth-client-app-config.example.json`
- デプロイスクリプト:
  - `scripts/deploy-foundry-oauth-client-app.sh`
  - `scripts/deploy-foundry-oauth-client-app.ps1`
- Foundry connection 更新スクリプト:
  - `scripts/update-foundry-mcp-oauth-connection.sh`
  - `scripts/update-foundry-mcp-oauth-connection.ps1`

作成後、App C の `clientId` と `clientSecret` を Foundry OAuth connection に設定し、Scope には App B の `api://<app-b-client-id>/access_as_user` を指定します。

## Functions への Entra 設定反映

- `scripts/apply-function-entra-settings.sh`
- `scripts/apply-function-entra-settings.ps1`

設定される代表値:

- `ENTRA_TENANT_ID`
- `ENTRA_CLIENT_ID`
- `ENTRA_CLIENT_SECRET`
- `EXPECTED_TOKEN_AUDIENCES`
- `EXPECTED_TENANT_ID`
- `GRAPH_SCOPES`
- `GRAPH_BASE_URL`

## コードデプロイ

Python 3.13 の Flex Consumption では **Remote Build ZIP** を既定にしています。デプロイ端末に Python 開発環境がなくても、ソースと `requirements.txt` だけで Azure 側が依存関係を解決します。

Bash:

```bash
RESOURCE_GROUP=sample-rg-foundry-mcp \
FUNCTION_APP_NAME=sample-func-mcp-server \
FUNCTION_APP_URL=https://sample-func-mcp-server-a1b2c3d4e5f6g7h8.canadaeast-01.azurewebsites.net \
bash ./scripts/deploy-functions-zip.sh
```

PowerShell:

```powershell
$env:RESOURCE_GROUP = "sample-rg-foundry-mcp"
$env:FUNCTION_APP_NAME = "sample-func-mcp-server"
$env:FUNCTION_APP_URL = "https://sample-func-mcp-server-a1b2c3d4e5f6g7h8.canadaeast-01.azurewebsites.net"
.\scripts\deploy-functions-zip.ps1
```

`FUNCTION_APP_NAME` は Azure リソース名、`FUNCTION_APP_URL` は path を含まない実際の公開 HTTPS origin です。secure unique default hostname を使用する場合、両者は一致しません。Bicep デプロイスクリプトが表示する `Function URL`、または Azure portal の **Default domain** を指定してください。

`VENDORED_PACKAGES_DIR` を指定した場合のみ、従来どおり `.python_packages/` を同梱し `--build-remote false` でデプロイします。

## ローカル実行

```bash
cd functions-mcp-selfhosted
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp local.settings.json.template local.settings.json
func start
```

エンドポイントは `http://localhost:7071/mcp` です。

## 動作確認

### tools/list

```bash
curl -X POST http://localhost:7071/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

### whoami

```bash
curl -X POST http://localhost:7071/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer <token-for-your-mcp-api>" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"whoami","arguments":{}}}'
```

注意:

- `Authorization` には Graph token ではなく MCP API 用 token を渡してください。
- `whoami` は内部で OBO 交換してから Graph `GET /me` を実行します。
- Foundry 経由で呼ぶ場合は、Foundry OAuth Identity Passthrough がこの `Authorization` ヘッダーを付与します。

## Foundry MCP Tool 設定の要点

Foundry Portal で MCP tool を追加する場合は、Functions の direct endpoint を指定します。

```text
https://<function-app-default-hostname>/mcp
```

認証は OAuth Identity Passthrough を使います。Client ID / Secret は App C、Scope は App B を指定します。

```text
Client ID     = <app-c-client-id>
Client Secret = <app-c-client-secret-value>
Scope         = api://<app-b-client-id>/access_as_user
```

この構成では Functions の HTTP Trigger は `authLevel=anonymous` でも、実際のユーザー識別は OAuth Identity Passthrough の bearer token で行います。

## 安定化のメモ

- OBO 交換は既定で `2` 回まで retry します。
- Graph `/me` 呼び出しは既定で `15` 秒 timeout、`2` 回まで retry します。
- retry は指数バックオフです。
- Flex Consumption のコールドスタート対策として、外部スケジューラから定期的に `tools/list` を呼ぶウォームアップ運用ができます。

ウォームアップ例:

```bash
MCP_ENDPOINT="https://<function-app-default-hostname>/mcp" \
bash ./scripts/warmup-mcp-endpoint.sh
```

```powershell
.\scripts\warmup-mcp-endpoint.ps1 -McpEndpoint "https://<function-app-default-hostname>/mcp"
```

Azure Automation / Logic Apps / GitHub Actions / cron などから 5〜10 分おきに実行すると、低頻度アクセス時の初回遅延を和らげやすくなります。

## セキュリティ上の注意

- 現在の実装は JWT の完全な署名検証ではなく、`aud` / `tid` の軽量チェックです。
- 本番では EasyAuth / APIM / Front Door / Functions middleware などで厳密な token 検証を検討してください。
- `ENTRA_CLIENT_SECRET` は Key Vault 管理を検討してください。
- Functions endpoint を公開する場合は、Access Restrictions、Private Endpoint、Front Door Premium なども検討してください。
- token 本体を tool arguments やログに出さないでください。
- `whoami`は表示用途のGraph属性を返しますが、token preview、raw Entra claims、Graph object IDは返しません。

## 関連ドキュメント

- [Repository README](../../README.md)
- [EasyAuth/OBO ADR](../../docs/adr-0001-easyauth-and-obo.md)
- [Foundry deployment guide](../../docs/deployment/README.md)
- [Current validation report](../../docs/report/validation-results-2026-09-06.md)
