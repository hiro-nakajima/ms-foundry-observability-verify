# WebApps — Foundry OAuthチャットラッパー

このフォルダーがApp Serviceへの配布ルートです。起動入口は`backend/server.py:app`。設定されたAgentへユーザー入力を送り、SSE応答、OAuth同意、MCP承認／拒否、診断情報を表示します。購買用のidentity metadataは送りません。

## フォルダー・ファイル

| パス | 役割 |
|---|---|
| `requirements.txt` | Web実行依存。Oryxが配布rootで読む |
| `startup.sh` | 配布rootと依存を解決し、backendのUvicornを1workerで起動 |
| `.env.example` | 設定のひな形。自動読込しない |
| `backend/server.py` | API、ジョブ・会話の所有者管理、SSE／ポーリング |
| `backend/auth.py` | EasyAuthユーザー確認、Foundry委任／MIトークン取得 |
| `backend/foundry_client.py` | Conversation作成、Responses通信、イベント変換 |
| `backend/procurement_flow.py` | 1ジョブの実行・同意待ち・再開・観測結果 |
| `backend/telemetry.py` | OTel初期化、HTTP計装、ログ相関、診断ヘッダー取得 |
| `backend/static/` | HTML／JavaScript／CSS。チャット、同意・承認、診断欄 |
| `scripts/package-procurement.py` | 10ファイルのallowlistと任意の依存をZIPへ同梱 |
| `tests/test_stream_response.py` | 通信・イベント変換のローカル検証 |

## Azure側に必要な設定

Python 3.13のLinux App Serviceを使用し、起動コマンドを`bash startup.sh`に設定します。

| 環境変数 | 用途 |
|---|---|
| `PROJECT_ENDPOINT` | Foundry projectまたは既存APIMのベースURL |
| `AGENT_NAME` | 呼び出すAgent名。`AGENT_REFERENCE_NAME`は旧別名 |
| `WEB_APP_URL` | Webの公開origin。要求元確認に使用 |
| `FOUNDRY_USER_AUTH_MODE` | 既定`refresh_token`。OBO検証は委任認証を使用 |
| `FOUNDRY_TOKEN_SCOPES` | 既定`https://ai.azure.com/.default` |
| `FOUNDRY_OBO_TENANT_ID`／`FOUNDRY_OBO_CLIENT_ID` | 委任トークン取得に使うEntra app。auth.pyに旧別名のfallbackあり |
| `ENTRA_CLIENT_SECRET`等 | 委任トークン取得用資格情報。Key Vault参照等で設定 |
| `APIM_SUBSCRIPTION_KEY` | 接続先APIMがキーを要求する場合のみ |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Trace・Log Exporterを有効化 |
| `OTEL_TRACES_SAMPLER` | SDKのサンプリング設定。全件取得は`always_on` |
| `WEBUI_ALLOW_ANONYMOUS` | 通常はfalse。ローカルfixture以外で不用意に有効化しない |

EasyAuthの`authsettingsV2`、token store、Entraの委任permission・同意、利用者のFoundry権限、APIMの認証転送が別途必要です。環境変数だけでEasyAuthを作成するものではありません。設定の読取例は[App Service設定](../../docs/deployment/appservice-settings.md)と[APIM設定](../../docs/deployment/apim-settings.md)を参照。

`managed_identity`モードではWeb MIを使います。ローカルの`az login`への自動fallbackはありません。`IDENTITY_LOOKUP_ENABLED`、`lookupApplicant`、`skipIdentity`は使用しません。

## .envの扱い

App Serviceでは環境変数で設定すればよく、`.env`の配布は不要です。`load_dotenv()`は通常起動でbackendから上位へ最初の`.env`を探し、未設定の環境変数だけを補います。backendとrootの.envは合成せず、既存のApp Service設定を上書きしません。デバッガー実行では探索開始がcwdになる場合があります。

ひな形はrootの`.env.example`へ統一しました。重複する`backend/.env.template`は削除しました。既存のローカル`backend/.env`は個人設定として保持し、Git管理・ZIP配布から除外します。

## Azureへ配布する方法

### A. VS Codeからソースを配布する

1. VS Codeでこのフォルダーを開く。リポジトリ全体を開く場合は配布対象を`src/webapp-foundry-oauth`に指定する。
2. Azure拡張の対象App Serviceを選び、配布先を確認する。
3. App Serviceのビルド設定を次の値にする。

```text
SCM_DO_BUILD_DURING_DEPLOYMENT=true
ENABLE_ORYX_BUILD=true
```

4. 起動コマンド`bash startup.sh`、必要な環境変数・EasyAuth設定を確認する。
5. `.env`、仮想環境、既存ZIPを配布対象から除外し、Deploy to Web Appを実行する。
6. Oryxログでrequirementsのインストール、実行ログで起動成功を確認し、サインイン後の新しい会話で応答・診断欄を確認する。

配布ZIP直下に`requirements.txt`、`startup.sh`、`backend/`が必要です。requirementsをrootへ置くだけでは、無効なビルド設定は有効になりません。VS Code拡張では既存のallowlistスクリプトは自動使用されません。構成として対応していますが、実際のVS Code拡張からの配布は未検証です。

### B. 依存を同梱したZIPを配布する（現在の検証環境）

以下はこのフォルダーをcwdとし、Linux／Python 3.13で実行します。Windowsで解決したネイティブ依存をLinux用として同梱しないでください。

```bash
python3.13 -m pip install --target /tmp/procurement-web-vendor --only-binary :all: -r requirements.txt
python3.13 scripts/package-procurement.py /tmp/procurement-web.zip --vendor /tmp/procurement-web-vendor
```

出力ZIPは既存ファイルを上書きしません。再実行時は新しい出力名と未使用の依存ディレクトリを使用します。次に対象を設定します。

```bash
export RESOURCE_GROUP='<resource-group>'
export WEB_APP_NAME='<web-app-name>'
az webapp config set -g "$RESOURCE_GROUP" -n "$WEB_APP_NAME" --startup-file 'bash startup.sh'
az webapp config appsettings set -g "$RESOURCE_GROUP" -n "$WEB_APP_NAME" --settings SCM_DO_BUILD_DURING_DEPLOYMENT=false ENABLE_ORYX_BUILD=false
az webapp deploy -g "$RESOURCE_GROUP" -n "$WEB_APP_NAME" --src-path /tmp/procurement-web.zip --type zip --clean true --restart true --async true --enable-kudu-warmup false --track-status false
```

配布受理と起動完了は別です。デプロイ状態と起動ログを確認します。EasyAuthにより未認証の`/health`も401になるため、401だけでアプリ起動成功とは判断しません。

方式AとBのビルド設定を混ぜないでください。直近のAzure検証では方式Bを使用しています。再起動でメモリ内のジョブ・再開状態は失われるため、新しい会話で確認します。

## 観測とUI

- Trace ID、Response ID、Web／Foundry Conversation ID、case／turn／status、直近Responses要求のtraceparent／user.id baggageを下部に表示・コピーする。
- `HTTPX response hook`で計装後の実要求ヘッダーを取得する。応答前の接続失敗などは未取得とする。下流記録の保証ではない。
- baggageのuser.idはEasyAuthのemail claim、なければメール形式ログイン名。UPNと実メールボックスは同じとは限らない。未取得なら省略。
- Web Span・会話所有者判定は従来のtenant/object IDハッシュ。メールbaggageを認証に使わない。
- 診断値は表示専用で、既存の利用者別localStorageへ会話と一緒に保存する。Clear Historyで消去する。
- 同意・承認ボタンは維持。「私は誰ですか」は現在のHosted内のOBO検証を呼ぶ。通常購買の名前取得指示は送らない。
- OTel Provider／Trace・Log Exporterはlifespanで初期化。通常ログへTrace／Span IDを付与し、Token・生claims・氏名・応答本文は記録しない。
- `OTEL_PROPAGATORS`はlifespanでW3C Trace Context＋Baggageへ固定する。環境変数だけで別構成へ変更できない。

1worker／1インスタンスのPoCです。サーバー内状態を共有する外部ストアはありません。

## 検証と参考

リポジトリルートで実行します。

```bash
TMPDIR=/tmp PYTHONPATH=src/hosted-agent:scripts .venv/bin/python -m pytest -q tests/unit/test_oauth_procurement.py src/webapp-foundry-oauth/tests/test_stream_response.py
```

[Web検証記録](../../docs/observability-integration/webapp-refactor-validation-20260912.md)／[Hosted・OBO検証記録](../../docs/observability-integration/hosted-refactor-validation-20260912.md)

公式: [Python App Service設定](https://learn.microsoft.com/azure/app-service/configure-language-python)、[VS Code ZIP配布設定](https://github.com/microsoft/vscode-azureappservice/wiki/Configuring-Zip-Deployment)。
