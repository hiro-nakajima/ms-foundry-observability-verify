# App Service 設定内容

更新・実設定照会: 2026-09-08。[共通リソース・認証](configuration.md)／[購買向けソース変更](../observability-integration/appservice-procurement-changes.md)。以下はAzureの現在値であり、Bicepの既定値だけを転記したものではない。

## 1. リソースと起動

| 項目 | 現在値 | 意味 |
| --- | --- | --- |
| App name | web-procurement-observe-nkjm | 指定RG内のWeb |
| URL | https://web-procurement-observe-nkjm.azurewebsites.net | 利用者の入口 |
| 状態／region | Running / Sweden Central | 読取り時点 |
| App Service Plan | asp-procurement-observe | Basic B1、capacity=1 |
| runtime | PYTHON&#124;3.13 | Linux Python 3.13 |
| startup command | bash startup.sh | backendへ移動してserver:appを起動 |
| process | uvicorn server:app --workers 1 | job・再開状態は1workerのメモリ内 |
| HTTPS only／minimum TLS | true / 1.2 | EasyAuth側もrequireHttps=true |
| FTPS | Disabled | 現設定 |
| Always On | false | 常時稼働保証は設定していない |
| HTTP/2 | false | SSEの非バッファ転送とは別設定 |
| healthCheckPath | 未設定（null） | 専用health check設定なし |
| publicNetworkAccess | ARM値null | 明示値なし。現Web URLのアクセスは確認済み |

ソース: [startup.sh](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/startup.sh)、[webui.bicep](/home/hnakajima/work/foundry-procurement-agent/infra/webui.bicep)。起動時にはZIP内 `.python_packages/lib/site-packages` をPYTHONPATHへ追加する。

## 2. App settingsの現在値

| 設定名 | 現在値 | 用途 |
| --- | --- | --- |
| `AGENT_NAME` | `procurement-parent-agent` | 購買Hostedのstable endpoint名。旧AGENT_REFERENCE_NAMEは未設定 |
| `ENABLE_ORYX_BUILD` | `false` | Oryx build無効 |
| `ENABLE_SENSITIVE_DATA` | `false` | false。現在の手動計装でも本文・Tokenを記録しない |
| `FOUNDRY_OBO_CLIENT_ID` | `c4910d3e-20b6-4aeb-ac3d-330d36e39411` | MSALのWeb App A client ID。refresh方式でも使用 |
| `FOUNDRY_OBO_TENANT_ID` | `d21866e6-786d-4625-8dc0-1e11e973489a` | MSALのtenant ID |
| `FOUNDRY_TOKEN_SCOPES` | `https://ai.azure.com/.default` | Web→Foundry用scope。Graph用scopeとは別 |
| `FOUNDRY_USER_AUTH_MODE` | `refresh_token` | EasyAuth refresh tokenからFoundryの利用者委任Tokenを取得 |
| `IDENTITY_LOOKUP_ENABLED` | `true` | chatで指定しない場合の名前取得既定値 |
| `OTEL_PROPAGATORS` | `tracecontext,baggage` | W3C TraceContext／Baggage。telemetry.pyでも明示構成 |
| `OTEL_TRACES_SAMPLER` | `always_on` | 常時sampling |
| `PROJECT_ENDPOINT` | `https://apim-procurement-stream-nkjm.azure-api.net/foundry/proj-default` | 既存APIMのproject base URL。末尾にAgent名を含めない |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | `false` | 依存同梱ZIPを使用するためremote build無効 |
| `WEB_APP_URL` | `https://web-procurement-observe-nkjm.azurewebsites.net` | Origin検査に使用するWeb公開URL |

### 秘密値・接続情報

| 設定名 | 現状態 | 用途・扱い |
| --- | --- | --- |
| ENTRA_CLIENT_SECRET | 設定あり、値非掲載 | EasyAuthのclientSecretSettingName。MSALも代替secretとして使用 |
| FOUNDRY_OBO_CLIENT_SECRET | 未設定 | server.pyはENTRA_CLIENT_SECRETへfallbackする |
| APPLICATIONINSIGHTS_CONNECTION_STRING | 設定あり、値非掲載 | telemetry.pyのAzure Monitor exporter |
| APIM_SUBSCRIPTION_KEY | 未設定 | 現APIはsubscriptionRequired=false |
| WEBUI_SESSION_SIGNING_KEY | 設定あり、値非掲載 | 旧procurement.py用設定が残存。現server.pyの会話分離には使わない |

`WEBUI_ALLOW_ANONYMOUS` は未設定で、認証を要求する。`JOB_RETENTION_SECONDS` は未設定のためコード既定1800秒。`CORS_ORIGINS` は未設定でコード既定localhost:8000／localhost:3000だが、実Webは同一originで呼ぶ。POST等のOrigin検査は `WEB_APP_URL` で別途行う。`WEBSITE_RUN_FROM_PACKAGE` は未設定で、現在は展開したZIPとvendor依存を利用する。

`ENABLE_SENSITIVE_DATA=false` だけで全SDKの記録制御が完了するわけではない。実際の本文除外、Browser境界、例外型のみの記録はtelemetry.pyとserver.pyの実装にも依存する。

## 3. EasyAuth / authsettingsV2

| 設定 | 現在値 |
| --- | --- |
| platform.enabled / runtimeVersion | true / ~1 |
| requireAuthentication | true |
| unauthenticatedClientAction | RedirectToLoginPage |
| redirectToProvider | azureactivedirectory |
| Azure AD provider enabled | true |
| openIdIssuer | https://login.microsoftonline.com/d21866e6-786d-4625-8dc0-1e11e973489a/v2.0 |
| registration.clientId | c4910d3e-20b6-4aeb-ac3d-330d36e39411 |
| registration.clientSecretSettingName | ENTRA_CLIENT_SECRET |
| allowedAudiences | 上記Web App A client ID |
| loginParameters | scope=openid profile email offline_access https://ai.azure.com/.default |
| tokenStore.enabled | true |
| tokenRefreshExtensionHours | 72 |
| apiPrefix | /.auth |
| requireHttps / forwardProxy | true / NoProxy |

EasyAuthのaudience（Web App A）と、WebからFoundryへ渡すTokenのaudience（https://ai.azure.com）は別である。Webは `/.auth/me`／必要時 `/.auth/refresh` とMSALを使いFoundry用Tokenを取得する。offline_accessとtokenStoreはrefresh tokenを利用するための設定。[App Service OAuth token管理](https://learn.microsoft.com/en-us/azure/app-service/configure-authentication-oauth-tokens)

## 4. Web Entraアプリ（App A）

| 項目 | 現在値 |
| --- | --- |
| Client ID | c4910d3e-20b6-4aeb-ac3d-330d36e39411 |
| tenant / signInAudience | d21866e6-786d-4625-8dc0-1e11e973489a / AzureADMyOrg |
| redirect URI | https://web-procurement-observe-nkjm.azurewebsites.net/.auth/login/aad/callback |
| Foundry resource App ID | 18a66f5f-dbdf-4c17-9dd7-1634712a9cbe |
| delegated permission | user_impersonation（Scope） |
| delegated scope ID | 1a7925b5-f871-417a-9b8b-303f9f29fa10 |
| implicitGrantSettings | accessToken=false、idToken=true |
| 登録済みcredential期限 | 2026-10-03 02:09:22 UTC（11:09:22 JST） |

requiredResourceAccessの登録を確認し、実ユーザーの同意・委任実行成功も確認した。新規ユーザーへの同意状態やeffective Foundry roleの全件確認は行っていない。secret更新時は新credentialの作成、App Service設定切替、再ログイン／Foundry呼び出し確認を別の変更として行う。

## 5. Managed IdentityとFoundry権限

Web system-assigned MI principal: `529d921e-f06b-4edf-af2e-f1ef256315d1`。

| 実際のrole | Role definition GUID | Scope |
| --- | --- | --- |
| Foundry Project Runtime User | `142bfaed-a13f-4c2d-bed2-6db62c4a1009` | Foundry project |
| Foundry Agent Consumer | `eed3b665-ab3a-47b6-8f48-c9382fb1dad6` | 購買Agent |

現在の `refresh_token` 経路では利用者のTokenを使う。MIを用いる設定も残っているが、OBOを実行する場合にWeb MI権限だけを付ける構成にはしない。OBOを省略しMIで呼ぶ場合は `FOUNDRY_USER_AUTH_MODE=managed_identity`、`IDENTITY_LOOKUP_ENABLED=false` と新規会話を組み合わせる。モード変更後に既存会話を流用するとコードが拒否する。

## 6. 観測設定と情報の受け渡し

Providerは [lifespan](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/telemetry.py:55) がworkerごとに一度生成する。service.name=`procurement-webapp`、Azure Monitor TraceExporter＋BatchSpanProcessor。ASGIと各HTTPX clientを計装する。明示的なOTel LogExporterは設定していない。

`web.chat.job`、`auth.foundry.token`、`procurement.agent.invoke` にuser.id hash、case、turnを付け、会話／応答IDを記録する。Browserからのtrace/baggageは受信Span作成前に破棄する。Hostedへは検証した相関metadataを渡し、氏名・Token・生claimは入れない。

接続先App Insightsは共通の `web-procurement-observe-nkjm-insights`。connection string値はApp settingで管理し資料へ記載しない。

## 7. 配布と変更時の組み合わせ

| 項目 | 配布済み値 |
| --- | --- |
| 最終Web deployment ID | eb3dc567-dec1-4e45-a175-3284d7f88e09 |
| ZIP SHA-256 | 67b37f892c4f92d9b32496f8bad98307892db7e399483a823b73cf6b1740ab20 |
| ZIP方式 | 8 source files＋Linux/Python 3.13のvendor依存 |
| build flags | SCM_DO_BUILD_DURING_DEPLOYMENT=false、ENABLE_ORYX_BUILD=false |

[package-procurement.py](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/scripts/package-procurement.py) が配布対象を制限する。vendorなしZIPをbuild無効の環境へ配ると依存を導入できないため、ZIPとbuild設定を組み合わせる。既存ZIPを上書きしない生成例は[OAuth実装ガイド](../observability-integration/oauth-wrapper-implementation.md)を参照。

基盤Bicepの `IDENTITY_LOOKUP_ENABLED` 既定はfalse、現在値trueはdeploy_identity.py webによる。`WEBUI_SESSION_SIGNING_KEY` 等の残存設定を今回削除していない。job/同意再開情報は再起動で失われるので再配布後は新規会話で確認する。

## 8. 読取りで確認する項目

```bash
az webapp show -g rg-ms-foundry-observability-verify -n web-procurement-observe-nkjm   --query '{name:name,state:state,principal:identity.principalId,host:defaultHostName}' -o json
az webapp config show -g rg-ms-foundry-observability-verify -n web-procurement-observe-nkjm   --query '{runtime:linuxFxVersion,startup:appCommandLine,alwaysOn:alwaysOn}' -o json
az webapp auth show -g rg-ms-foundry-observability-verify -n web-procurement-observe-nkjm   --query '{enabled:platform.enabled,requireAuth:globalValidation.requireAuthentication,tokenStore:login.tokenStore.enabled}' -o json
```

appsettingsの全値を表示・共有せず、必要な非秘密の設定名だけを選んで確認する。実行成功の根拠は[検証記録](../report/validation-results-2026-09-08-obo.md)にある。
