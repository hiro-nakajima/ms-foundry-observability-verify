# Functions — OBO検証用MCPサーバー

このフォルダーがAzure Functionsへの配布ルートです。Hostedの明示的OBO質問からToolbox経由で呼ばれ、受信TokenをMicrosoft Graph用TokenへOBO交換し、`/me`から表示名を取得します。商品・部署検索は別のPrompt Agent／AI Search Toolが担当します。

## 構成とファイル

```text
Hosted OBO Agent Tool → Foundry Toolbox／OAuth connection
  → Functions /mcp → MSAL OBO → Graph /me
```

| パス | 役割 |
|---|---|
| `host.json` | Functions Host設定 |
| `requirements.txt` | Python実行依存の正本。remote buildも使用 |
| `local.settings.json.template` | Core Toolsでのローカル設定例。Azureへ配布しない |
| `mcp_handler/__init__.py` | Functions HTTP入口。ASGI middlewareへ委譲 |
| `mcp_handler/function.json` | HTTPトリガー定義 |
| `mcp_server.py` | FastMCP、Tokenチェック、OBO交換、Graph呼出し、whoami／greet |
| `mcp_telemetry.py` | プロセス共通Provider、MCP／OBO／Graph Span |
| `infra/azure/` | Functions基盤のBicepとパラメータ例 |
| `infra/entra/` | OBO API／Foundry OAuth clientの設定例 |
| `scripts/deploy-functions-zip.*` | ソースZIP配布。通常のコード更新で使用 |
| `scripts/deploy-functions-azure-bicep.*` | 基盤作成／what-if |
| `scripts/deploy-functions-entra-obo.*` | MCP API・OBO用Entra app作成 |
| `scripts/deploy-foundry-oauth-client-app.*` | Foundry OAuth client app作成 |
| `scripts/apply-function-entra-settings.*` | Entra設定をFunctionsへ反映 |
| `scripts/update-foundry-mcp-oauth-connection.*` | OAuth connection更新 |
| `scripts/warmup-mcp-endpoint.*` | MCP疎通確認 |
| `scripts/remove-server-app-foundry-redirects.*` | 旧構成のredirect整理用。通常配布には不要 |

`.*`はBash／PowerShell版です。重複し内容も一致していなかった`pyproject.toml`は削除し、requirementsへ統一しました。

## 認証の前提

FunctionsはGraph Tokenを直接受け取るのではなく、MCP API用の委任Tokenを受け取ります。受信aud／tid等のチェックとOBO交換を行い、受信TokenのoidとGraph `/me.id`の一致を確認します。Hostedへ返すwhoami結果はOBO成功状態・表示名・subjectHashです。

- MCP API／OBO用Entra app: API scope公開、client資格情報、Graphの委任User.Read等が必要。
- Foundry OAuth client app: MCP APIの委任scopeとFoundry connection用redirect URIを設定する。
- Foundry OAuth connection／Toolbox: 上記clientとMCP endpointを接続する。

既存Entra app・OAuth connectionがある環境は、再作成せず値とpermissionを照合します。基盤変更とコード更新を同じ手順だと考えないでください。

## Functionsの環境変数

| 設定 | 用途 |
|---|---|
| `ENTRA_TENANT_ID` | OBO tenant |
| `ENTRA_CLIENT_ID` | MCP API／OBO用appのclient ID |
| `ENTRA_CLIENT_SECRET` | 同appのclient資格情報 |
| `EXPECTED_TOKEN_AUDIENCES` | 許可するaud。カンマ区切り |
| `EXPECTED_TENANT_ID` | 許可するtid。未指定時はENTRA_TENANT_ID |
| `GRAPH_SCOPES` | 既定`https://graph.microsoft.com/User.Read` |
| `GRAPH_BASE_URL` | 既定`https://graph.microsoft.com/v1.0` |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | カスタムSpanのAzure Monitor export |
| `OBO_MAX_RETRIES`／`OBO_RETRY_BACKOFF_SECONDS` | 既定2／0.5 |
| `GRAPH_TIMEOUT_SECONDS`／`GRAPH_MAX_RETRIES`／`GRAPH_RETRY_BACKOFF_SECONDS` | 既定15／2／0.5 |

Python worker・ストレージなどHostに必要な値はAzure基盤設定が管理します。現在の構成はLinux Flex Consumption／Python 3.13。ローカルCore Toolsでは`FUNCTIONS_WORKER_RUNTIME=python`等をlocal.settings.jsonに設定します。

`local.settings.json.template`は自動読込しません。AzureではFunction Appの設定を環境変数として参照し、ローカルでは必要な値を`local.settings.json`へ設定します。秘密値はGitへ含めません。

## Azureへの配布

### 既存Function Appのコード更新

Azure CLIへ対象tenant／subscriptionでサインインします。以下はこのフォルダーをcwdとして実行します。

```bash
export RESOURCE_GROUP='<resource-group>'
export FUNCTION_APP_NAME='<function-app-name>'
export FUNCTION_APP_URL='https://<実際のFunction-App-hostname>'
export BUILD_REMOTE=true
bash scripts/deploy-functions-zip.sh
```

PowerShellの場合:

```powershell
$env:RESOURCE_GROUP = "<resource-group>"
$env:FUNCTION_APP_NAME = "<function-app-name>"
$env:FUNCTION_APP_URL = "https://<実際のFunction-App-hostname>"
$env:BUILD_REMOTE = "true"
./scripts/deploy-functions-zip.ps1
```

hostnameは実リソースの`defaultHostName`を使用します。スクリプトは必要なソースとrequirementsだけをZIP化し、Azureで依存を解決します。`.env`、local.settings.json、infra、Entra資格情報は梱包しません。

Linux Python 3.13用依存を事前同梱する場合は`VENDORED_PACKAGES_DIR`を指定できます。その場合はスクリプトがremote buildを無効にします。通常はremote buildを使ってください。

### 新しい基盤・認証接続を準備する場合

`infra/azure/main.parameters.example.json`と`infra/entra/*example.json`を移植先の値に合わせ、対応する基盤／Entraスクリプトを使用します。Bicepスクリプトは`WHAT_IF=true`で差分確認ができます。購買projectのIdentity Toolbox登録は共通の`../../scripts/deploy_identity.py`が担当します。これはコードZIP更新とは別操作です。

## 観測と確認

`mcp_telemetry.py`のProvider／Exporterはプロセス単位で作成し、要求ごとのMCP app作成では初期化し直しません。`auth.obo.exchange`、`graph.me`等を記録し、例外本文やTokenをSpanへ出しません。Functionsのuser.idはsubjectHashであり、Webのメールbaggageと同じ値ではありません。

配布後は起動ログ、`/mcp`への認証付き疎通、Webで「私は誰ですか」を送り同意→名前表示を確認します。TokenのないHTTP応答だけではOBO成功の証拠になりません。

ローカル起動には別のPython環境とAzure Functions Core Toolsを用意します。

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
# local.settings.jsonを設定してから実行
func start
```

共通テストはリポジトリルートのREADMEを参照。[OBO移植ガイド](../../docs/observability-integration/hosted-obo-userid-porting.md)／[実ユーザー検証記録](../../docs/observability-integration/hosted-refactor-validation-20260912.md)。
