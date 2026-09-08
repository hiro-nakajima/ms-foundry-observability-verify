# 既存Azure環境への再配置ガイド

このディレクトリは、Foundry account/project、Azure AI Search、App Serviceが既に存在する環境へ、購買申請Agentの定義・データ・コードを再配置する手順をまとめる。新しいFoundry resourceやnetworkを作る手順ではない。

現在の配布状態・認証・環境変数・RBACは **[App Service／APIM／HostedAgent設定資料](configuration.md)** を参照する。2026-09-08に実設定を読み戻して照合済み。別サンプルへのソース統合は[統合ガイド](../observability-integration/README.md)。

## 手順の順序

1. [Azure AI Searchの静的JSON定義・document再投入](search-json-indexer.md)
2. [2つのToolboxとAzure AI Search MCP tool](toolboxes-and-search-mcp.md)
3. [2つのPrompt Agent](prompt-agents.md)
4. [Hosted親Agentのsource ZIP deployment](hosted-agent-source-zip.md)

App Serviceのresource/EasyAuth/APIM新規作成は上記の再配置手順の対象外。現在の購買Web入口は`src/webapp-foundry-oauth/backend/server.py`で、既存APIM経由で購買Hostedを呼ぶ。任意OBOはHosted内の専用Agent Tool → Identity Toolbox → Functionsで実行する。OBOを再現する場合はHosted新version作成前に、[Hosted設定](hosted-agent-settings.md)のOAuth connection／Identity Toolbox／Functionsとidentity manifestを用意する。Webの起動・依存同梱ZIPは[App Service設定](appservice-settings.md)を参照。

## 共通の環境変数

配備scriptは現在のPoC値をdefaultに持つが、別環境では必ず次を明示する。

```bash
export AZURE_SUBSCRIPTION_ID='<subscription-id>'
export AZURE_RESOURCE_GROUP='<resource-group-name>'
export PROCUREMENT_WEB_APP_NAME='<existing-web-app-name>'
export FOUNDRY_ACCOUNT_NAME='<existing-foundry-account-name>'
export FOUNDRY_PROJECT_NAME='<existing-project-name>'
export FOUNDRY_PROJECT_ENDPOINT='https://<account>.services.ai.azure.com/api/projects/<project>'
export PROCUREMENT_SEARCH_SERVICE_NAME='<existing-search-service-name>'
export PROCUREMENT_SEARCH_ENDPOINT='https://<search-service>.search.windows.net'
export PROCUREMENT_SEARCH_SKU='serverless'
export PROCUREMENT_SEARCH_LOCATION='westcentralus'
export PROCUREMENT_STORAGE_ACCOUNT_NAME='<storage-account-name>'
export PROCUREMENT_STORAGE_LOCATION='<storage-region>'
export PROCUREMENT_APP_INSIGHTS_RESOURCE_ID='/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Insights/components/<name>'
export PROCUREMENT_PARENT_MODEL_DEPLOYMENT='<existing-model-deployment>'
export PROCUREMENT_CHILD_MODEL_DEPLOYMENT='<existing-model-deployment>'
export PROCUREMENT_DEPLOYMENT_STATE_DIR="$PWD/.local_state/<environment-name>"
```

SKU/locationは実resourceと一致する値を明示する。state directoryは環境ごとに分離し、別projectのAgent/Toolbox version manifestを流用しない。scriptはsubscription、Search SKU/location、既存schema/definitionを照合し、不一致なら上書きせず停止する。

## 前提ツール

- Azure CLIで対象tenant/subscriptionへlogin済み
- Python 3.13のvirtual environmentとroot `requirements.txt`のinstall
- Foundry SDK操作では`azure-ai-projects` 2.3.0
- source ZIP deploymentでは`azure-ai-projects` 2.2.0以上
- Azureへのwrite前にread-only inventoryとRBAC確認

```bash
az account show --query '{subscription:id,tenant:tenantId}' -o json
az resource list --subscription "$AZURE_SUBSCRIPTION_ID" \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --query '[].{name:name,type:type,location:location}' -o table
```

secret、token、connection stringは標準出力、shell history、Repositoryへ保存しない。削除、既存definitionの置換、role assignment削除は各手順に含めない。
