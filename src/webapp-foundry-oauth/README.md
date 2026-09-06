# webapp-foundry-oauth — 購買PoCのApp Service配置元

**このRepositoryの稼働入口は `backend/procurement.py:app` です。**
EasyAuth → App Service Managed Identity → APIM → Foundryの購買PoCとして配置します。
配備手順・検証境界は末尾の「このRepositoryでの購買PoC用入口」を参照してください。
以下のOAuth/Graph説明は提供された参考実装についての記録で、購買PoCには配備しません。

## 提供されたOAuth参考実装（非配備）

`webapp-foundry-oauth` は、Azure App Service 上で動く Foundry Agent チャット Web アプリです。FastAPI backend と静的 HTML/CSS/JavaScript UI で構成し、App Service EasyAuth で認証した現在ユーザーを起点に、APIM 経由で Azure AI Foundry Agent endpoint Responses API を呼び出します。

元サンプルの本線は **案A: EasyAuth ユーザー委任 -> APIM -> Foundry Agent -> OAuth Identity Passthrough -> Functions MCP Server -> OBO -> Microsoft Graph** です。

## この Web アプリの役割

- App Service EasyAuth で Web UI へのサインインを制御する。
- EasyAuth token store / refresh token を使い、Foundry 向け user delegated token を取得する。
- `Ocp-Apim-Subscription-Key` と `Authorization: Bearer <Foundry user delegated token>` を付けて APIM を呼び出す。
- APIM 経由で Foundry Agent endpoint Responses API を stream 実行する。
- Foundry の MCP approval / OAuth consent request を UI に表示し、ユーザー操作後に `/api/continue` で再開する。
- 通常チャットは SSE でジョブイベントを受信し、SSE が失敗した場合はポーリングに fallback する。
- 会話継続は現時点では Foundry `conversation` ではなく `previous_response_id` を使う。
- Foundry が stale な `previous_response_id` を `400` で拒否した場合、通常チャットに限り state reset + 1 回 retry する。

## 全体構成での位置づけ

```text
Browser
  ↓ HTTPS / EasyAuth session
webapp-foundry-oauth (App Service / FastAPI)
  ↓ Ocp-Apim-Subscription-Key
  ↓ Authorization: Bearer <Foundry user delegated token>
Azure API Management
  ↓ Authorization を上書きせず転送
Azure AI Foundry Agent endpoint Responses API
  ↓ OAuth Identity Passthrough
Azure Functions MCP Server
  ↓ OBO
Microsoft Graph API (/me)
```

このアプリは Foundry に直接ブラウザからアクセスさせず、backend 側で endpoint、subscription key、token 取得、ジョブ状態、approval / consent 再開を管理します。

## 主な機能

| 機能 | 内容 |
| --- | --- |
| EasyAuth 連携 | App Service の現在ユーザーを信頼源として扱う |
| Foundry user delegated 呼び出し | EasyAuth refresh token から Foundry 向け token を取得し APIM へ転送 |
| Agent endpoint Responses API | `/agents/{agent}/endpoint/protocols/openai/responses?api-version=v1` を呼び出す |
| ジョブ管理 | `/api/chat` / `/api/continue` が `jobId` を返し、backend task で Foundry stream を処理 |
| SSE | `/api/jobs/{jobId}/events` で job events を stream 配信 |
| ポーリング fallback | SSE が使えない場合に `/api/jobs/{jobId}` で状態取得 |
| MCP approval UI | `mcp_approval_request` をカード表示し approve / reject を送信 |
| OAuth consent UI | `oauth_consent_request` をカード表示し consent page を開く |
| 安全な承認継続 | approval / consent 検出後も `response.completed` まで Foundry stream を読み切り、応答ID確定後に UI を操作可能にする |
| 会話継続 | `previous_response_id` を保存し次回 request に利用 |
| stale state retry | `previous_response_id` 起因の Foundry 400 を通常チャットで自動復旧 |

## アーキテクチャ

```text
Browser (Static UI served by FastAPI)
  │
  │ POST /api/chat
  │ POST /api/continue
  │ GET  /api/jobs/{jobId}/events   # SSE
  │ GET  /api/jobs/{jobId}          # polling fallback
  ▼
FastAPI backend (server.py)
  │
  │ acquire Foundry user delegated token from EasyAuth refresh token
  │
  │ POST <PROJECT_ENDPOINT>/agents/<AGENT_NAME>/endpoint/protocols/openai/responses?api-version=v1
  │   stream=true
  │   headers:
  │     Ocp-Apim-Subscription-Key: <APIM_SUBSCRIPTION_KEY>
  │     Authorization: Bearer <Foundry user delegated token>
  ▼
API Management
  │
  │ forward Authorization
  │ remove Ocp-Apim-Subscription-Key before backend
  ▼
Azure AI Foundry Agent
```

## OAuth Consent / MCP Approval フロー

### OAuth Consent

```text
User sends message
  ↓
FastAPI -> APIM -> Foundry Responses API (stream)
  ↓ event: oauth_consent_request
FastAPI drains the stream through response.completed
  ↓
UI shows ConsentCard
  ├─ Open Consent Page -> popup -> user grants permission
  └─ I've Consented — Continue
       ↓
     POST /api/continue
       ↓
     FastAPI resumes with previous_response_id
```

### MCP Approval

```text
User sends message
  ↓
FastAPI -> APIM -> Foundry Responses API (stream)
  ↓ output item: mcp_approval_request
FastAPI drains the stream through response.completed
  ↓
UI shows ApprovalCard
  ├─ Approve and Continue
  └─ Reject
       ↓
     POST /api/continue
       ↓
     FastAPI sends mcp_approval_response with previous_response_id
```

## ディレクトリ構成

```text
webapp-foundry-oauth/
├── backend/
│   ├── server.py          # FastAPI backend / job / SSE / Foundry 呼び出し
│   ├── requirements.txt
│   ├── .env.template
│   └── static/
│       ├── index.html     # チャット UI
│       ├── app.js         # SSE / polling / approval / consent UI 制御
│       └── styles.css
├── scripts/
│   ├── deploy-web.sh
│   └── deploy-web.ps1
└── startup.sh
```

## 前提条件

- Azure App Service が作成済みであること。
- App Service Authentication / EasyAuth が有効であること。
- EasyAuth token store が有効であること。
- EasyAuth 用 App Registration に Foundry / Azure AI の delegated permission が設定されていること。
- App Service で `/.auth/me` から refresh token を取得できるセッションであること。
- APIM に Foundry Agent endpoint Responses API proxy が作成済みであること。
- APIM policy が案A用、つまり `Authorization` を managed identity で上書きせず転送する構成であること。
- Foundry Agent に OAuth Identity Passthrough 付き MCP tool が設定済みであること。
- Foundry API を呼ぶユーザーまたはグループに `Azure AI User` / `Foundry User` 相当の RBAC があること。

購買E2Eのidentity判断は[EasyAuth/OBO ADR](../../docs/adr-0001-easyauth-and-obo.md)、現在のAzure構成は[validation report](../../docs/report/validation-results-2026-09-06.md)を参照してください。

## ローカル実行

ローカル実行は UI / API の開発確認用です。EasyAuth は App Service の機能であるため、案Aの user delegated token 取得を完全に再現するには Azure 上の App Service で確認してください。

```bash
cd webapp-foundry-oauth/backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.template .env
uvicorn server:app --reload --port 8000
```

ブラウザで `http://localhost:8000` を開きます。

## 主な App Service app settings

| 設定名 | 必須 | 用途 |
| --- | --- | --- |
| `PROJECT_ENDPOINT` | 必須 | APIM 経由の Foundry Agent endpoint ベース URL。例: `https://<apim>.azure-api.net/foundry/<project>` |
| `AGENT_NAME` | 必須 | URL path で指定する Foundry Agent 名 |
| `APIM_SUBSCRIPTION_KEY` | 必須 | App Service -> APIM の subscription key |
| `WEBAPP_ENTRA_CLIENT_ID` | 必須 | EasyAuth 用 App Registration の client ID |
| `FOUNDRY_USER_AUTH_MODE` | 必須 | 案Aでは `refresh_token` |
| `FOUNDRY_TOKEN_SCOPES` | 必須 | Foundry token 取得 scope。例: `https://ai.azure.com/.default` |
| `CORS_ORIGINS` | 任意 | Web UI の公開 URL。デプロイスクリプトでは `WEB_APP_URL` が既定値 |
| `WEBSITES_PORT` | 必須 | App Service での Uvicorn 待ち受けポート。通常 `8080` |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | 推奨 | Oryx build automation 有効化 |
| `ENABLE_ORYX_BUILD` | 推奨 | App Service remote build 有効化 |

`FOUNDRY_USER_AUTH_MODE=refresh_token` では、EasyAuth の access token そのものではなく、EasyAuth token store の refresh token を使って Foundry 向け delegated token を取り直します。これにより、App Service の現在ユーザーと Foundry 呼び出しユーザーを合わせます。

## デプロイ

現在は UI も `backend/static` に統合されているため、App Service からは Python アプリ 1 つとして扱います。ZIP デプロイ時は `scripts/deploy-web.*` が `backend/`、`startup.sh`、ルートの `requirements.txt` をまとめて配置します。

Bash:

```bash
export RESOURCE_GROUP=sample-rg-foundry-mcp
export WEB_APP=sample-webapp-foundry-oauth
export WEB_APP_URL=https://sample-webapp-foundry-oauth-a1b2c3d4e5f6g7h8.canadaeast-01.azurewebsites.net
export PROJECT_ENDPOINT=https://sample-apim.azure-api.net/foundry/sample-project
export AGENT_NAME=sample-mcp-oauth-agent
read -rsp "APIM Subscription Key: " APIM_SUBSCRIPTION_KEY && echo
export APIM_SUBSCRIPTION_KEY
bash ./scripts/deploy-web.sh
```

PowerShell:

```powershell
$env:RESOURCE_GROUP = "sample-rg-foundry-mcp"
$env:WEB_APP = "sample-webapp-foundry-oauth"
$env:WEB_APP_URL = "https://sample-webapp-foundry-oauth-a1b2c3d4e5f6g7h8.canadaeast-01.azurewebsites.net"
$env:PROJECT_ENDPOINT = "https://sample-apim.azure-api.net/foundry/sample-project"
$env:AGENT_NAME = "sample-mcp-oauth-agent"
$env:APIM_SUBSCRIPTION_KEY = Read-Host "APIM Subscription Key"
.\scripts\deploy-web.ps1
```

`WEB_APP` は Azure リソース名、`WEB_APP_URL` は実際の公開 HTTPS origin です。secure unique default hostname を使う環境では両者が一致しないため、公開 URL をリソース名から組み立てないでください。PowerShell は同名の引数でも指定できますが、環境変数形式にそろえると Bash と同じ入力名で管理できます。

デプロイスクリプトは基本的な App Service 設定とコード配置を行います。案Aで必要な EasyAuth / Foundry user delegated 関連のapp settingsは、対象環境のEntra構成に合わせて追加してください。購買PoCの配備入口にはこの参考scriptを使用しません。

Startup command は `bash startup.sh` です。

## 動作確認

1. App Service URL にアクセスし、EasyAuth でサインインする。
2. チャット欄に `Who am I?` または `自分は誰？` と入力する。
3. 初回は MCP approval / OAuth consent が表示される場合がある。
4. Continue 後、`whoami` tool が実行される。
5. Graph `/me` のユーザー情報が、App Service でサインインしているユーザーと一致することを確認する。
6. 別ユーザーで再ログインして実行し、前ユーザーの情報が返らないことを確認する。

## SSE イベント仕様

| `type` | 内容 |
| --- | --- |
| `text.delta` | テキスト差分 |
| `tool.start` | ツール呼び出し開始 |
| `tool.end` | ツール呼び出し完了 |
| `tool.error` | ツール呼び出しエラー |
| `mcp_approval_required` | MCP 実行承認が必要 |
| `oauth_consent_required` | OAuth 同意が必要 |
| `done` | ストリーム完了 |
| `error` | エラー |

## 会話継続について

現在は Foundry `conversation` リソースではなく、前回の `response.id` を `previous_response_id` として次回 request に渡します。

- 小規模サンプルとして実装がシンプルです。
- App Service の in-memory state に依存します。
- App Service 再起動や Foundry 側 state の失効で stale になることがあります。
- stale な `previous_response_id` による `400` は、通常チャットに限り state reset + 1 回 retry します。

購買PoCの`procurement.py`はこの参考方式ではなく、Foundry Conversation IDを署名cookieへowner-boundで保持します。

## セキュリティ上の注意

- Foundry / Graph access token や refresh token をブラウザ、tool arguments、ログへ出さないでください。
- `APIM_SUBSCRIPTION_KEY` や EasyAuth provider secret は Key Vault 管理を検討してください。
- App Service 複数インスタンス運用では、job / conversation state の永続化を検討してください。
- 本番運用では Application Insights、Private Endpoint、Front Door Premium なども検討してください。

## 関連ドキュメント

- [Repository README](../../README.md)
- [EasyAuth/OBO ADR](../../docs/adr-0001-easyauth-and-obo.md)
- [Foundry deployment guide](../../docs/deployment/README.md)
- [Current validation report](../../docs/report/validation-results-2026-09-06.md)
# このRepositoryでの購買PoC用入口（2026-09-03）

App Serviceには `startup.sh` → `backend/procurement.py:app` を配置する。
既存の `backend/server.py` / `static/app.js` はOAuth/Graph参考実装として保存するが、購買PoCでは公開・packageしない。
Hallmark skillは利用不可だったため、既存CSSを使った最小の購買入力・結果・status・相関表示だけを追加した。

経路は Browser → EasyAuth → App Service system MI → APIM → Foundry Hosted親 → Prompt子 → Toolbox → Search。
元サンプルのrefresh token/OBOは使用しない。APIMはApp Service MIのtenant/audience/oidを検証し、そのBearerをFoundryへ転送する。
参照APIMのResponses経路に加え、Foundry Conversationsの作成・取得・metadata更新経路が必要。

## Packaging / deployment

`scripts/package-procurement.py /tmp/procurement-webapp-unique.zip` で6ファイルだけをZIP化する。
既存ZIP、`.env`、OAuth server、user claim/token、Agent商品データは含めない。既存出力名への上書きは拒否する。
元の `deploy-web.sh` / `.ps1` は古いpackageと設定を適用するため、誤実行を停止するguardを置いた。

Repository rootの `infra/webui.bicep` がApp Service/EasyAuth/APIM/Search/Insightsを定義する。
what-ifと必要な確認が完了した後、生成ZIPを対象Web Appへ `az webapp deploy --type zip --src-path ... --output none` で配置する。
実配置、EasyAuthログイン、APIM越しのFoundryアクセスはまだ未検証。

必要な設定: `PROJECT_ENDPOINT`（APIM URL）、`AGENT_NAME`、`WEB_APP_URL`（HTTPS origin）、
`WEBUI_SESSION_SIGNING_KEY`（32 bytes以上、安定したsecret）、`APPLICATIONINSIGHTS_CONNECTION_STRING`。
認証secret/署名keyはsecure deployment parametersで渡し、RepositoryやCLI出力に含めない。

## 会話・Traceの境界

- Foundry Conversationを作成し、Responses bodyの `conversation` にIDを設定する。`previous_response_id`方式は使わない。
- owner hash、turn、case IDはFoundry Conversation metadataに保持する。cookieは署名済み・HttpOnly/Secure/SameSite、owner-bound。
- 他ユーザーcookie、任意Conversation body、CSRF、未認証アクセスを拒否する。AzureではEasyAuthを必須にし、backendへ直接公開する認証迂回経路を設けない。
- browser traceparent/tracestate/baggageは破棄。ASGI server rootとHTTPXの自動注入を使う。手動traceparent注入なし。
- Local実HTTP fixtureでroot → client Span → outgoing traceparent、user.id baggage、2 turn会話を確認済み。
- Managed Foundry/APIM越しの伝播、Framework Session mapping、親のcase/turn相関、Azure traceは `AZURE_PENDING`。
- Foundryに履歴を置くが、UIで過去全メッセージを一覧表示する機能は未実装。同じ会話への次turn送信はcookieから再開する。
- 表示は業務結果の限定projectionのみ。raw result.trace、tool arguments、reasoning、token、claimsは返さない。

上記のOAuthサンプルの元の説明は、このPoCの稼働設定ではない。

---
