# App Service／APIM／HostedAgent 設定内容

確認日: **2026-09-08 13:38 JST**（Azure設定の読取り開始時点）。設定値はARM、Microsoft Graphのアプリ登録、Foundry SDKで照会したもの。今回の資料更新でAzure設定・ソースの実装・配布物は変更していない。

実装・配備・実ユーザーの同意／名前表示とOBOのTrace確認は完了した。未検証のWeb購買全シナリオ等は[検証記録](../report/validation-results-2026-09-08-obo.md)で区別する。

| 資料 | 内容 |
| --- | --- |
| [App Service設定](appservice-settings.md) | 起動・依存配布・環境変数・EasyAuth・App A・MI・観測・運用 |
| [APIM設定](apim-settings.md) | API／操作一覧・backend・Token検証・SSE・診断・継承 |
| [HostedAgent設定](hosted-agent-settings.md) | v33・実行定義・環境変数・Tool／OAuth接続・権限・観測 |
| [統合ガイド](../observability-integration/README.md) | 別のPlan&Executeサンプルへ組み込むソースの対応 |
| [配備手順](README.md) | Search／Toolbox／Prompt／Hostedの再配置 |

別環境への移植では、この一覧の全設定をコピーせず、[必要な環境差分の抽出](../observability-integration/minimal-environment-and-executor.md)を参照する。

## 1. 共通リソース

| 項目 | 現在値 |
| --- | --- |
| Subscription ID | `d96eb8c2-2deb-4ed5-8cf2-f9fb178cb3ee` |
| Resource Group | `rg-ms-foundry-observability-verify` |
| Tenant ID | `d21866e6-786d-4625-8dc0-1e11e973489a` |
| Foundry account / project | `observability-verify / proj-default` |
| Foundry Project endpoint | `https://observability-verify.services.ai.azure.com/api/projects/proj-default` |
| Web URL | `https://web-procurement-observe-nkjm.azurewebsites.net` |
| APIM project base URL | `https://apim-procurement-stream-nkjm.azure-api.net/foundry/proj-default` |
| OBO Functions | `func-procurement-obo-nkjm`、`https://func-procurement-obo-nkjm.azurewebsites.net/mcp` |
| Application Insights | `web-procurement-observe-nkjm-insights` |
| Log Analytics workspace | `web-procurement-observe-nkjm-logs` |
| Workspace customer ID | `093a675c-1158-427f-ad72-8f766f9999ad` |

Foundry Project ARM ID:

```text
/subscriptions/d96eb8c2-2deb-4ed5-8cf2-f9fb178cb3ee/resourceGroups/rg-ms-foundry-observability-verify/providers/Microsoft.CognitiveServices/accounts/observability-verify/projects/proj-default
```

Entraアプリ登録はtenant配下であり、RG配下ではない。App B/Cは既存登録を再利用し、AzureのWeb／Functions／Agent／Toolboxは指定RG内の構成で動作する。

## 2. 接続と認証の設定対応

| 境界 | 認証・相関 | 設定と責任 |
| --- | --- | --- |
| Browser → App Service | EasyAuth cookie、認証済みtid/oid | WebのauthsettingsV2、App A |
| Web → APIM | aud=https://ai.azure.comの利用者委任Token | FOUNDRY_USER_AUTH_MODE=refresh_token、Foundry delegated scope |
| APIM → 購買Hosted | 受信した同じAuthorization header | API backend URL、署名／tenant／aud／Web client検査。Token交換なし |
| Hosted → Identity Toolbox | HostedのAzure credential + platform call ID | Hosted実行IDのFoundry User、PROCUREMENT_IDENTITY_TOOLBOX_ENDPOINT |
| Toolbox → Functions | App B API用の利用者委任Token | OAuth connection `procurement-whoami`、App C |
| Functions → Graph | App Bがuser_assertionでMSAL OBO | App B secret、Graph権限／scope |
| 観測の利用者対応 | SHA-256(lower(tid)+":"+lower(oid)) | WebとFunctionsが算出、Hostedが本人照合 |

APIMからHostedまでの経路は維持する。Hosted内のOBO ToolからToolbox／Functionsへ進むため、WebからOBO用Agentを別に呼ぶAPIM APIは不要である。

## 3. 実行IDと実際のRBAC

Azure照会で取得したrole名とGUIDを記載する。表示名だけで以前の名称と同一視しない。

| 主体 | Principal ID | 実際のrole／scope |
| --- | --- | --- |
| App Service system-assigned MI | `529d921e-f06b-4edf-af2e-f1ef256315d1` | Foundry Project Runtime User／project、Foundry Agent Consumer／購買Agent |
| Hosted v33 runtime identity | `80a1bbc5-c4b4-49da-b78e-b817696fe464` | Foundry User／project |
| Foundry project identity | `70c395fd-1d99-4849-a283-9344ee8c9cd6` | Search Index Data ReaderとReader／CatalogとCodeの各index |
| サインイン利用者 | 個人識別値を記載しない | 現行の委任TokenでAgentを実行できる権限が必要。検証利用者の実行成功を確認済み |

**現在のWeb実行主体は利用者委任である。Web MIへのrole付与だけでOBOが有効になるわけではない。** MI用の既存roleとAPIMのMI許可は残っているが、現在のrefresh_token経路で用いるTokenではない。利用者のeffective role／group membershipの全棚卸しは今回実施していない。

## 4. 配布方式と設定の正本

| 対象 | 現在の方式 | ソース／設定の正本 |
| --- | --- | --- |
| App Service | Python 3.13/Linux依存同梱ZIP。Oryx無効 | startup.sh、package-procurement.py、infra/webui.bicep、deploy_identity.py web |
| APIM | 既存APIにpolicyを設定 | infra/apim.bicep、infra/apim-foundry-policy.xml、deploy_identity.py web |
| Hosted | source ZIP、Python 3.13、remote_build、immutable v33 | scripts/deploy_foundry.py、scripts/package_hosted.py、.foundry/agent-metadata.yaml |
| OBO依存 | Functions remote build、Toolbox v1、OAuth connection | infra/identity-functions.bicep、scripts/deploy_identity.py functions |

実設定とIaCの既定値は同義ではない。例えばWebの `IDENTITY_LOOKUP_ENABLED` は現在trueだが、基盤Bicepは既定false。OBO連携スクリプトが実設定をtrueにする。値を再現するときは本書の実設定を読み、意図せず基盤全体を再適用しない。

シークレットとconnection stringの値は記載しない。各資料には設定名、利用先、設定の有無を記載する。現WebのsecretはApp Service app settingから参照される構成であり、Key Vault参照を使用しているとは確認していない。

## 5. 確認根拠と運用事項

- Web state=Running、Hosted v33=active、APIM provisioningState=Succeededを再照会した。
- APIMのAPI／4操作／API policy／global policy／診断を確認。API policyはXMLエンティティと整形を正規化するとソースの設定と一致した。
- RBACはsubscription内のassignmentを読み、対象サービスprincipalの分だけ抽出した。個人の表示名や生claimは資料化していない。
- 配布内容のhash・実Web OBOのTrace・名前省略時のnull確認は[2026-09-08検証記録](../report/validation-results-2026-09-08-obo.md)を参照。
- Web App Aの登録済みcredential期限は **2026-10-03 02:09:22 UTC（11:09:22 JST）**。継続利用する場合は期限前のcredential更新とWeb設定の切替が必要。今回の資料更新では変更していない。

読取りで得た秘密値を除く詳細控えは `.local_state/deployment/configuration-readback-20260908.json`（git管理外）に保存した。配布先を変更する場合はこの控えをそのまま流用せず、対象環境を再照会する。
