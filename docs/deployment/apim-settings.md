# APIM 設定内容

更新・実設定照会: 2026-09-08。[共通構成](configuration.md)／[App Service](appservice-settings.md)／[Hosted](hosted-agent-settings.md)。既存APIMを維持し、購買Hostedへの入口に使用する。

## 1. Service / API

| 項目 | 現在値 |
| --- | --- |
| APIM name | apim-procurement-stream-nkjm |
| RG / location | rg-ms-foundry-observability-verify / East US |
| SKU / capacity | Developer / 1 |
| provisioningState | Succeeded |
| Gateway URL | https://apim-procurement-stream-nkjm.azure-api.net |
| virtualNetworkType / publicNetworkAccess | None / Enabled |
| API ID / revision | foundry-proj-default / 1 |
| API displayName | Procurement Foundry project |
| path | foundry/proj-default |
| protocols / subscriptionRequired | https / false |
| backend serviceUrl | https://observability-verify.services.ai.azure.com/api/projects/proj-default |

ソース: [apim.bicep](../../infra/apim.bicep)、[apim-foundry-policy.xml](../../infra/apim-foundry-policy.xml)、[configure_web](../../scripts/deploy_identity.py)。PortalではAPIM → APIs → `foundry-proj-default` のSettings／Design／Diagnosticsで確認する。

## 2. 公開する4操作

Gatewayへの完全なpathは次の共通prefixに各suffixを連結する。

```text
/foundry/proj-default/agents/procurement-parent-agent/endpoint/protocols/openai
```

| Operation ID | HTTP method | suffix |
| --- | --- | --- |
| create-conversation | POST | `/conversations` |
| get-conversation | GET | `/conversations/{conversation}` |
| parent-response | POST | `/responses` |
| update-conversation | POST | `/conversations/{conversation}` |

Webは会話作成とResponses送信にこの経路を使い、queryの `api-version=v1` はbackendへ渡る。APIのserviceUrlがprojectまでを指定し、operation pathがAgent endpointを指定する。個別のrewrite-uri／set-backend-serviceはない。

任意Agentのwildcard API、Agent管理API、会話削除API、OBO専用APIはこのAPIに追加していない。Toolbox／Functionsの名前取得はHostedの内部から呼ぶ。

## 3. Policyの適用範囲と処理

| Scope | 実際の内容 |
| --- | --- |
| Global | inbound空、backendにforward-request、outbound空 |
| API | 本節のToken検証・許可主体・header削除・SSE転送 |
| 4つのoperation | policy overrideなし。個別policyのGETは404で、APIの設定を使用 |

API policyはinbound/outbound/on-errorでbaseを参照する。backendには専用forward-requestを置く。以下は設定内容の説明であり、秘密のTokenやsubscription keyを含むpolicyではない。

### Inbound

1. `validate-azure-ad-token` でAuthorization headerを検証する。tenantは `d21866e6-786d-4625-8dc0-1e11e973489a`、audienceは `https://ai.azure.com`。検証失敗は401。
2. 検証済みJWTに対して、次のどちらかの呼出し主体を許可する。
3. 条件に合わない主体は403。
4. `Ocp-Apim-Subscription-Key` headerをbackend転送前に削除する。

| 許可パターン | Policyの条件 | 現在の利用 |
| --- | --- | --- |
| 利用者委任 | scpにuser_impersonation、azp（なければappid）がWeb App Aのclient ID `c4910d3e-20b6-4aeb-ac3d-330d36e39411` | 現Webのrefresh_token経路 |
| Web MI | scpなし、oidがWeb MI principal `529d921e-f06b-4edf-af2e-f1ef256315d1` | MIを明示選択した場合の既存経路 |

署名検証のあとでclaim条件を評価する。APIMはTokenを交換せず、AuthorizationをMI Tokenへ置き換える `authentication-managed-identity` policyも使わない。Foundry側のRBACは別途適用される。APIMを通過しただけでFoundry実行権限が付くわけではない。

### Backend / SSE

```xml
<backend>
  <forward-request timeout="210"
                   buffer-response="false"
                   fail-on-error-status-code="false" />
</backend>
```

`buffer-response=false` はSSEの応答バッファリングを抑制する設定。`timeout=210` はforward-requestのbackend応答待ちの設定で、全処理が必ず210秒以内に完了する保証ではない。`fail-on-error-status-code=false` はbackendの4xx/5xxをこの設定でpolicy errorへ変換しない指定であり、業務成功に変えるものではない。[forward-request公式仕様](https://learn.microsoft.com/en-us/azure/api-management/forward-request-policy)

## 4. Application Insights診断

| 項目 | 現在値 |
| --- | --- |
| 診断scope / name | API / applicationinsights |
| logger | application-insights |
| App Insights | web-procurement-observe-nkjm-insights（共通構成） |
| alwaysLog | allErrors |
| sampling | fixed / 100% |
| httpCorrelationProtocol | W3C |
| verbosity | error |
| logClientIp | false |
| frontend request/response headers | [] / [] |
| backend request/response headers | [] / [] |
| frontend/backend body bytes | すべて0 |
| service-level diagnostics | なし |

APIMはマネージド診断を使うため、App Service／Hostedのようなrequirements.txtやPython Providerの組み込みはない。W3C診断とforward-requestでWeb／backendの通信を観測する。headers/bodyの設定でToken・入力本文を記録しない。

今回の成功OBOではWeb／Hosted／Functionsの同一OperationIdを確認した。APIMのdiagnostic設定だけを根拠に、すべての管理内部SpanやSDK境界が必ず同じTraceになるとは判断しない。実際のレコードが必要な検証ではTraceとcase/response IDを照合する。

## 5. ソースと実設定の照合

API policyのARM読取り値SHA-256:

```text
0d9ae2001833d9db406f096a96505a938a0ca5fb2f64ba8f7d75563bfc511a7b
```

ARMはformat=xmlで返し、policy式の引用符・アンパサンドのエンティティ表現がローカルrawxmlと異なる。単純な文字列／hash比較では一致しなかったが、XML要素・属性と追加エンティティを正規化すると、tenant／Web principal／Web clientを展開した `infra/apim-foundry-policy.xml` と一致した。設定の差として修正はしていない。

再配置ではdeploy_identity.py webが既存API policyを更新する。基盤作成用Bicep全体の再適用は、このpolicy更新だけを目的に行う必要はない。操作の追加・削除やAPIMの置換は今回の資料更新に含めない。

## 6. 読取り確認と切り分け

```bash
az apim api show -g rg-ms-foundry-observability-verify   --service-name apim-procurement-stream-nkjm --api-id foundry-proj-default   --query '{path:path,serviceUrl:serviceUrl,subscriptionRequired:subscriptionRequired}' -o json
az apim api operation list -g rg-ms-foundry-observability-verify   --service-name apim-procurement-stream-nkjm --api-id foundry-proj-default   --query '[].{name:name,method:method,urlTemplate:urlTemplate}' -o json
```

| 現象 | 確認先 |
| --- | --- |
| APIMで401 | tenant／audience／署名／期限。匿名呼出しの401は確認済み |
| APIMで403 | Web client ID、user_impersonation、またはWeb MI oid |
| Foundryで403 | 実際に使用する利用者／MIのFoundry RBAC。APIM条件とは別 |
| 404 | API path、操作のHTTP method、Agent endpointの名前 |
| 同意カード | Hosted/Toolboxが返したnative consent。APIMエラーではない |
| SSEがまとめて届く | forward-requestのbuffer-responseと呼出しclientのstream処理 |
