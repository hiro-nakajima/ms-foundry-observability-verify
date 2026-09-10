# 別環境への最小統合：環境差分とContext Provider型Executor

更新日: 2026-09-08。基準ソース: main `79bdb0e`。App Service／Functionsはこのリポジトリのコードをそのまま配布し、別の購買Plan&Execute Hostedへ統合する前提。

移植先のソース・Azure設定は未提供なので、「差分あり」と断定する一覧ではなく、**一致していれば変更不要な照合条件**を示す。具体的な配布先のID・秘密値をこの検証環境の値に置き換えない。詳細な検証環境の値は[設定資料](../deployment/configuration.md)にある。

## 1. 結論と必要な範囲

- App Service／Functions：コード差分の分析は不要。既存のEasyAuth／OBOアプリを再利用し、接続先・委任Token・同意接続・観測先の一致を確認する。
- Hosted：HostedAgentBundleは不要。既存ExecutorがContext Providerなら、そのままAgent Toolを受け取り、既存stepの呼出しを差し替える。
- OTel：HostのProvider/exporterでSDK標準Spanを送信できる。Plan/Stepの意味・再試行・確認待ち等を見たい場合だけ、既存処理へ追加Spanを置く。
- OBOも引き継ぐ場合：Agent Toolの登録以外に、利用者context、OAuth同意の中断／再開、検証済み氏名の反映／null消去が必要。

## 2. App Service：環境差分の最小一覧

### 2.1 既存EasyAuthの設定

`authsettingsV2` を丸ごと置換しない。以下はARM応答の **properties配下** の位置。

| 項目 | 現方式で必要な条件 | 変更が必要な場合 |
| --- | --- | --- |
| platform.enabled、globalValidation.requireAuthentication | true。Entraで認証済み利用者のtid/oidがWebへ届く | すでにEasyAuthが有効なら維持 |
| identityProviders.azureActiveDirectory.registration | 既存Web App Aのtenant／client ID／secret設定名 | App Aを変えないなら維持。今回のIDへ変更する必要はない |
| 同providerのvalidation.allowedAudiences | Webの認証設定としてApp Aと整合 | Foundry向けTokenを使うために、ここをhttps://ai.azure.comへ変更しない |
| login.tokenStore.enabled | true | falseなら変更。現WebはEasyAuthのrefresh tokenを使用 |
| 同providerのlogin.loginParameters | scopeにoffline_accessを要求。現配備はopenid profile email offline_access https://ai.azure.com/.default | refresh tokenが取得できない、またはFoundryの初回委任同意が不足している場合に調整 |

今回の `scripts/deploy_identity.py` の `configure_web()` が変更したEasyAuth項目は、**tokenStore.enabledとloginParametersの2か所**。App Aの登録client ID／issuer／allowedAudiencesは既存値を維持した。別の `infra/webui.bicep` は新規構築用なので、既存EasyAuthへ一律再適用する必要はない。

現配備で使用した変更部分（完全なPUT本文ではない）:

```json
{
  "properties": {
    "login": {"tokenStore": {"enabled": true}},
    "identityProviders": {
      "azureActiveDirectory": {
        "login": {
          "loginParameters": [
            "scope=openid profile email offline_access https://ai.azure.com/.default"
          ]
        }
      }
    }
  }
}
```

GETした既存設定へ必要な項目だけ反映する。上記断片だけをそのままPUTしない。scope以外の既存loginParametersも確認して維持する。Foundryのdelegated grantが既にあり、refresh tokenからFoundry用Tokenを取得できているなら、同じscope文字列にそろえること自体が目的ではない。設定変更後は必要に応じて再ログイン／同意を行う。[EasyAuthのToken管理](https://learn.microsoft.com/en-us/azure/app-service/configure-authentication-oauth-tokens)

### 2.2 Web App Aの委任権限

EasyAuthでログインできることと、Foundryの利用者委任Tokenを取得できることは別。App AでFoundryの **user_impersonation（delegated）** と必要な同意が成立しているかを確認する。今回の配備では既存App Aへこのscopeを追加した。既に設定・同意済みなら追加不要。

現在の実行主体は利用者委任。利用者にも対象FoundryでのAgent実行権限が必要であり、Web MIへのFoundry role追加だけで置き換えられない。App AにGraph権限を追加することは今回の名前取得に必須ではない。Graph OBOはFunctionsのApp Bが担当する。

### 2.3 Web app settings

| 設定 | 別環境で指定／確認するもの | 必須性 |
| --- | --- | --- |
| PROJECT_ENDPOINT | 対象APIMのproject base URL | 現Web実装で必須 |
| AGENT_NAME | 移植先の購買Hosted名 | 必須。AGENT_REFERENCE_NAMEは旧alias |
| WEB_APP_URL | 実際のWeb origin（https://...） | Origin検査に必要 |
| FOUNDRY_USER_AUTH_MODE | refresh_token | 現方式を明示する設定。コード既定も同値 |
| IDENTITY_LOOKUP_ENABLED | OBOを既定有効にするならtrue、取得しないならfalse | 動作選択。通常UIはlookupApplicantを指定しない |
| FOUNDRY_OBO_TENANT_ID／FOUNDRY_OBO_CLIENT_ID | 既存Web App Aのtenant／client ID | 認識済みaliasで供給できていれば重複設定不要 |
| FOUNDRY_OBO_CLIENT_SECRETまたは既存alias | Web App Aのsecret | refresh方式のMSALにも必要。App B/Cのsecretを混用しない |
| FOUNDRY_TOKEN_SCOPES | https://ai.azure.com/.default | コード既定と同値なら省略可。明示すると分かりやすい |
| APPLICATIONINSIGHTS_CONNECTION_STRING | 観測先のApp Insights | WebのTrace送信に必要 |

Webが認識するaliasの優先順は `server._get_foundry_obo_config()` が正本:

| 用途 | 優先順 |
| --- | --- |
| tenant | FOUNDRY_OBO_TENANT_ID → ENTRA_TENANT_ID → WEBSITE_AUTH_AAD_ALLOWED_TENANTSの先頭 |
| client ID | FOUNDRY_OBO_CLIENT_ID → WEBAPP_ENTRA_CLIENT_ID → ENTRA_CLIENT_ID |
| client secret | FOUNDRY_OBO_CLIENT_SECRET → ENTRA_CLIENT_SECRET → WEBAPP_ENTRA_CLIENT_SECRET → MICROSOFT_PROVIDER_AUTHENTICATION_SECRET |

**EasyAuthのclientSecretSettingNameを設定しただけで、任意の名前のsecretをPython側が自動で探すわけではない。** 既存名が上記にあればそのまま使い、独自名ならPython側が読む設定名でも供給する。EasyAuthのsecret設定名をENTRA_CLIENT_SECRETへ改名すること自体は必須ではない。

### 2.4 配布方式に依存する項目と不要な移植

| 項目 | 判断 |
| --- | --- |
| Linux／Python 3.13、bash startup.sh | 現ZIPの実行前提として一致させる |
| vendor依存同梱ZIP | SCM_DO_BUILD_DURING_DEPLOYMENT=false、ENABLE_ORYX_BUILD=falseを組み合わせる |
| vendorなしZIP | 依存を導入するbuild方式が必要。上記falseだけをコピーしない |
| 1worker | job／同意再開状態がメモリ内のため現実装で維持 |
| WEBUI_SESSION_SIGNING_KEY | 旧procurement.py向け残存設定。現在のserver.pyには不要 |
| OTEL_PROPAGATORS | 現telemetry.pyでもW3C+baggageを明示構成。設定名を追加するだけでuserid全伝播が保証されるわけではない |
| OTEL_TRACES_SAMPLER=always_on | 検証でsamplingを明示する場合。接続／OBOの成立条件ではない |
| B1、region、Always On、APIM Developer | この検証環境の選択。OBOのために同じSKU／regionへ変更する要件ではない |

## 3. Functions：既存OBOアプリを維持する条件

| 項目 | 別環境での確認 | 変更条件 |
| --- | --- | --- |
| ENTRA_TENANT_ID | App Bのtenant | 既存App Bを使うなら維持 |
| ENTRA_CLIENT_ID | MCP API／OBO実行用のApp B | App A/Cと取り違えない |
| ENTRA_CLIENT_SECRET | 有効なApp B secret | 現コードはsecret方式。既存FIC専用構成ならそのままでは同一方式にならない |
| GRAPH_SCOPES | Graph /me用の委任scope | 既定https://graph.microsoft.com/User.Read。既存の有効な設定なら維持 |
| EXPECTED_TOKEN_AUDIENCES | Toolboxが送るTokenのaudとApp Bが一致 | 未設定時はENTRA_CLIENT_IDが既定。実Tokenがapi://形式等なら許可値を調整 |
| EXPECTED_TENANT_ID | 対象tenant | 未設定時はENTRA_TENANT_IDが既定 |
| APPLICATIONINSIGHTS_CONNECTION_STRING | 観測先のApp Insights | Functionsの手動Span送信に必要 |
| /mcpへの到達性 | Foundry Toolboxから実際のURLへ接続できる | URL・既存network設定が変わる場合のみ確認 |
| Python／Storage／配布設定 | Functionsが起動できる既存基盤 | 同じOBOのためだけにFlex planやStorageを作り直さない |

今回の `configure_functions()` は既存App Bの設定を再利用し、観測設定を追加した。**FunctionsのauthsettingsV2を新設・変更する処理はない。** Web用EasyAuth設定をFunctionsにもコピーする必要はない。

HTTP triggerの `authLevel=anonymous` はFunctions keyを要求しないという意味。Graphプロフィールの取得には受信Bearer Token、EntraでのOBO交換、Graph本人照合が必要である。独自のJWT decodeを署名検証と呼ばない。既存FunctionsでEasyAuthも使っているなら、BearerのaudienceとMCPの認証応答が整合するかを別途確認し、無条件に無効化しない。

現Functionsの `host.json` はtelemetryModeを追加していない。mcp_telemetry.pyがworker内にProvider/exporterを作るので、今回の `mcp.whoami`／`auth.obo.exchange`／`graph.me` を出すために `telemetryMode=OpenTelemetry` やPython Worker自動計装を重ねる必要はない。Host自身の追加観測は別の設定事項である。

`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false` は配備時に設定したが、現Functionsの独自Spanは本文を記録していない。接続文字列と観測モジュールの配布がTrace送信の直接の条件。新モジュールはBash／PowerShell両方のZIP許可リストに含まれている。

## 4. APIM・Foundry側で見落としやすい環境差

| 項目 | 必要な差分 |
| --- | --- |
| APIM backend／operation path | 対象projectと購買Hosted名へ向ける。既存経路を維持可能 |
| APIM inbound許可 | MI専用policyなら、App A client IDかつuser_impersonation付き委任Tokenの許可を追加 |
| APIM Token転送 | 受信Authorizationを維持。MI Tokenへ交換しない |
| APIM SSE | forward-requestのbuffer-response=false。既に対応済みなら維持 |
| APIM観測 | 必要なAPIへW3C診断。headers=[]／body.bytes=0で本文を収集しない |
| Foundry OAuth connection | **移植先project**から参照できるconnection。targetは実Functions /mcp、scopeはApp Bのaccess_as_user、OAuth clientはApp C |
| App Cのredirect URI | connectionのredirectUrlが既存登録に含まれること。新project／新connectionで値が変わった場合だけ追加 |
| Identity Toolbox | 同projectのOAuth connectionを参照し、Functions URLとallowed_tools=[whoami]を指定 |
| server_label | 現identity.pyを使うならwhoami_func。公開名whoami_func___whoami／whoami_func.whoamiをコードが期待 |
| Hosted環境 | PROCUREMENT_IDENTITY_TOOLBOX_ENDPOINTを対象Toolbox versionのURLへ |
| Hosted runtime identity | 対象projectでFoundry User等の必要権限。Web MIとは別主体 |
| Foundry観測先 | projectのApp Insights接続／Host exporterの実際の宛先が有効 |

App B/Cのアプリ登録が同じでも、**新しいFoundry projectのOAuth connectionと、そのredirect URIの整合**は別に確認する。同じconnectionを既に利用できるなら新設不要。旧環境の遠隔OBO Agentの名前を登録する必要はなく、Hosted内ToolがToolboxを直接使う。

App Service／Functions／Hostedの送信先を同じApp Insights／workspaceへ集めると照合が容易。ただし単一リソースへの統一それ自体がOBOの認証条件ではない。

`scripts/deploy_identity.py` はこの検証環境の旧／新RG・リソース名を持ち、実行scopeを限定している。**別環境の汎用移植スクリプトとしてそのまま実行しない。** 上の条件を使い、対象環境に必要な設定操作だけ行う。

## 5. HostedAgentBundleがない構成への対応

こちらの実装も `ControllerContextProvider.before_run()` がPlan&Executeを起動する。HostedAgentBundleはfactoryからparent／planner／tools等をまとめて返すためのこのアプリ独自のdataclassであり、SDKの必須型ではない。

| 現リポジトリ | 移植先で対応させる場所 |
| --- | --- |
| build_hosted_bundle()のAgent／Tool生成 | 既存のAgent作成処理へ必要なToolだけ追加 |
| bundle.catalog_tool／code_tool | 既存Executorのconstructor引数や既存のdispatch map |
| ControllerContextProvider.before_run() | 既存ExecutorのContext Provider hook |
| _invoke_remote_tool() | 既存stepの呼出し部分。Agent Tool.invokeへ接続 |
| TelemetryRecorder | 必須ではない。global tracerを直接使う最小例でもよい |
| bundle.parent | 既存の親Agent変数をそのままHostへ渡す |

以下は **agent-framework-core 1.16.0 / agent-framework-foundry 1.11.0 / hosting 1.0.0b260827** の実SDKで確認したPython API。移植先が旧invoking()方式ならhookのシグネチャが異なる。サンプルのSDK確認前に最新版へ一括更新する前提にはしない。[Context Providers公式資料](https://learn.microsoft.com/en-us/agent-framework/concepts/agents/conversations/context-providers)

### 5.1 子AgentをToolにして既存Executorへ渡す

次の既存Executor生成関数とchildの入力schemaは、移植先の接続点を表す。現在のサンプルにこの関数があるという意味ではない。

```python
from agent_framework import Agent
from agent_framework_foundry import FoundryAgent
from agent_framework_foundry_hosting import ResponsesHostServer


def compose(parent_client, credential, endpoint, child_name, child_version,
            make_existing_executor):
    child = FoundryAgent(
        project_endpoint=endpoint, agent_name=child_name,
        agent_version=child_version, credential=credential,
    )
    child_tool = child.as_tool(name="catalog_search_agent", propagate_session=False)
    executor = make_existing_executor(child_tool)
    parent = Agent(parent_client, context_providers=[executor])
    return ResponsesHostServer(parent)
```

この例ではExecutorが順序を決めてToolを直接invokeする。親の `tools=[child_tool]` へ登録することは、この直接呼出しの必須条件ではない。親LLMにも同じToolを公開すると、Executorの後に再度呼ぶ可能性があるため、LLMに選ばせる方式かExecutorが実行する方式かを既存設計に合わせる。元のhistory provider／middleware／instructionsは既存Agent生成時に維持する。

遠隔Agentの入力・結果schemaは別途そろえる。as_tool()だけで元のソース内検索関数と同じ戻り値になるわけではない。検索を外部Agentへ移さないなら、既存検索Toolを維持してOBOだけ追加してよい。

### 5.2 Executorのstepから実際に呼ぶ

```python
import json
from agent_framework import FunctionInvocationContext


async def invoke_agent_tool(tool, payload, session):
    arguments = {"task": json.dumps(payload, ensure_ascii=False)}
    return await tool.invoke(
        arguments=arguments,
        context=FunctionInvocationContext(
            function=tool, arguments=arguments, session=session,
        ),
        skip_parsing=True,
    )
```

現在のAgent.as_toolの既定入力名はtask。別のarg_nameを指定した場合は一致させる。sessionをinvoke contextへ渡しても、as_toolのpropagate_session=falseにより親会話履歴を子へ共有する構成にはしない。結果のContent list／text／JSONを既存のparse・schema検証へ接続する。

## 6. OBOを組み込む場合の追加部分

[OBO・user.idの移植用抜粋](hosted-obo-userid-porting.md)に、Bundle依存を外したPythonファイル、接続方法、Tool未設定時の分岐をまとめた。

OBOも含めた今回の挙動を維持する場合、先に **Host入口で名前取得→必要なら同意待ち→既存Executor** の順にする。現在のSDKではnested Agent Toolの同意を旧Webへそのまま届けるためにprotocol adapterを実装している。ToolをContext Providerへ追加するだけで同意カードまで完成するとは扱わない。

```text
Responses Host
  → OBO Agent Tool / 名前の本人照合
  → 同意が必要ならoauth_consent_request + response.incompleteで停止
  → 取得済み／省略／失敗なら既存Agent
      → context_providers=[既存Executor]
      → Plan / Execute / 既存応答
```

Bundle依存のある現在のHost constructorは、移植先では次の形へ変えられる。これは **constructorの置換例**。同意処理を省略してよいという意味ではない。

```python
from agent_framework_foundry_hosting import ResponsesHostServer


class IdentityResponsesHostServer(ResponsesHostServer):
    def __init__(self, parent_agent, identity_tool, **kwargs):
        self.identity_tool = identity_tool
        super().__init__(parent_agent, **kwargs)

    # 現hosted_app.pyの_handle_response()を移植する。
    # invoke_identity、OAuth item生成、ContextVarのfinally resetを含める。
```

必要なソースの部分:

| 部分 | 移植対象 |
| --- | --- |
| identity.py | build_identity_tool／invoke_identity／parse_whoami_result／verified_name、request用ContextVar |
| framework.py | identity用DeterministicChatClientだけ。購買Controllerを移す必要はない |
| observability.py | current_request_attributes、hash、必要ならMcpPrivacyProcessor／configure_host_observability |
| hosted_app.py | metadataからuser hash／lookupフラグを取り込む処理、_handle_responseの同意bridge、finally reset |
| 既存Executor／state | 成功時は検証済み氏名を取り込み、省略・失敗時は以前の氏名もnullへ。氏名を必須入力から外す |

hosted.py全体をimportしてBundleを作る必要はない。名前／statusのContextVarは、移植先の小さな共通モジュールへ切り出してHostとExecutorから参照できる。これらは新設先の役割であり、移植先の実ファイル名は未確認。

user.id hash、case／turn／conversation IDは相関用で、Tokenの代用品ではない。利用者委任の認証文脈はHost platformとToolbox SDKが扱う。Tokenや氏名をTool引数・baggage・Span属性に載せない。Webから届くmetadataを受け取るコードを省くと、現identity.pyの本人照合も成立しない。

## 7. OTelの自動部分と追加部分

| 観測したい内容 | 必要なもの |
| --- | --- |
| Agent／LLM／Framework Toolの呼出し、時間、標準属性 | SDK標準計装＋送信先／Provider設定 |
| 手書きPlanの生成時間、Step ID、各attempt、確認待ち、業務成否 | 既存処理へ明示的なSpan／属性を追加 |
| userid、case、turnの業務相関 | Web metadata等を検証してSpanへ設定する処理 |
| SDK Workflowがすでに出すstep Span | 先に記録を確認。同じ範囲のSpanを追加しない |

したがって質問の認識は正しい。現在のplan.create／plan.step.execute等は、汎用SDKが知らない **購買Plan/Executeの業務境界を観測するための追加計装**である。氏名・検索本文・LLMの思考過程を記録するためではない。[Agent Framework Observability](https://learn.microsoft.com/en-us/agent-framework/agents/observability)

### 7.1 初期化の最小形

同じResponsesHostServerを使うならHostが既定の観測初期化を持つ。独立したTracerProviderをExecutor内で作らない。

```python
import os
from agent_framework_foundry_hosting import ResponsesHostServer


def serve(parent_agent):
    os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = "false"
    os.environ["ENABLE_SENSITIVE_DATA"] = "false"
    os.environ.setdefault("OTEL_PROPAGATORS", "tracecontext,baggage")
    server = ResponsesHostServer(parent_agent)
    server.run()
```

環境変数は実際の配布では起動前に設定する。上の呼出し前にもSDK Spanを出す処理があるなら、そこより前に設定する。実際にAzureへ送るには、Host SDKが使用する有効なApp Insights設定／connection stringが必要。環境変数を置くだけで、任意の別Host／別Frameworkが同じexporterを構成するわけではない。

OBOを採用する場合は、既存 `configure_host_observability` のMCP例外内容除去も使い、`IdentityResponsesHostServer(parent_agent, identity_tool, configure_observability=configure_host_observability)` とする。本文記録falseだけでSDKのOAuth同意例外に含まれるURLが消えるとは限らない。これは今回実測したSDKの対処である。

### 7.2 Plan／Stepの最小挿入例

[最小コード例](examples/minimal_agent_tool_otel.py)は、Exporterを作らずglobal tracerを使う。既存Executorへ次の境界を差し込む。plan／execute／apply_resultはサンプル側の既存処理を束ねた接続点である。

```python
async def before_run(self, *, agent, session, context, state):
    with observed("plan.create") as span:
        steps = await self.plan(context, state)
        span.set_attribute("plan.step.count", len(steps))

    for step in steps:
        with observed("plan.step.execute", **{
            "plan.step.id": step["id"],
            "execution.attempt": step.get("attempt", 1),
        }) as span:
            result = await self.execute(step, session, state)
            span.set_attribute("business.status", result["business_status"])
        if self.apply_result(context, state, step, result):
            break
```

observed()は例外型とERRORだけ記録し、生例外本文を記録しない小さなwrapper。正常時のset_status(OK)は必須ではない。business_statusは既存処理で検証した機械判定値を使用し、HTTP成功と業務成功を分ける。

この例のcallback契約は以下のとおり。

- plan：検証済みstep配列を返す。step.idは生成文や個人情報を含まないID。
- execute：既存Tool／Agent Toolを呼び、結果をparse・検証してbusiness_statusを返す。
- apply_result：既存の状態保存と応答反映を行う。確認待ち／失敗／完了で停止するならtrueを返す。

既存Executorのretry／replan／結果再利用をこの短いforループへ置き換えない。既存の各attemptを囲むようにSpanを差し込む。ProviderのselfにはTool等の共有参照だけを保持し、利用者ごとのPlan・氏名・結果は引数state／session／request ContextVarへ置く。

TelemetryRecorder、HostedAgentBundle、購買Controller、Synthetic評価機能を全部移植することは最小条件ではない。Webからのuser.id等も追加したい場合は、検証済みmetadataから得た共通属性をobservedへ渡す。

## 8. 検証範囲

この資料は現リポジトリのソース／固定SDKとMicrosoft公式仕様を照合した。最小例はAzureを呼ばないsmoke検証で、Context Providerからの実SDK Agent Tool呼出し、Plan/Step Spanの共通Traceと親、確認待ち時の後続停止、自作Spanでの例外型のみの記録を確認済み。SDK内部の全例外Spanがこのwrapperだけで秘匿されるという意味ではない。別環境のEasyAuth／RBAC／同意の実設定と、未提供サンプルのAPI適合は未検証である。

移植先のContext Providerがbefore_runではなく旧invokingを使う場合は、SDKとhookに合わせて例を調整する。確認したい範囲はExecutorの定義、Agentへ登録する箇所、Host起動、requirementsの4点で足りる。

## 9. 確認した移植元

- [Web認証設定変更](/home/hnakajima/work/foundry-procurement-agent/scripts/deploy_identity.py:96)
- [WebのMSAL設定alias](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:494)
- [FunctionsのOBO設定](/home/hnakajima/work/foundry-procurement-agent/src/functions-mcp-selfhosted/mcp_server.py:239)
- [Functions基盤](/home/hnakajima/work/foundry-procurement-agent/infra/identity-functions.bicep)
- [Context Providerとしての購買実行](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:121)
- [Agent Toolの実invoke](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted.py:443)
- [OBO Tool](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/identity.py:83)
- [同意bridge](/home/hnakajima/work/foundry-procurement-agent/src/procurement_agent/hosted_app.py:99)
