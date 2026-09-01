# Azure apply前確認

状態: **未承認・未実施**。この文書のcommandは実行していない。

## 変更対象

1. 既存Azure AI Search serviceへ2 indexを作成する。
   - `procurement-catalog-v1`
   - `procurement-code-master-v1`
2. version `2026-09-01.1`のSynthetic documentを投入する。
3. Search project connectionを参照する2 Toolboxを作成する。
4. 各Toolboxを1つだけ接続したPrompt Agent version 1を作成する。
5. Hosted親containerを作成し、2 Prompt Agent definitionを環境変数で参照する。
6. runtime、index管理、document投入の3 identityへ最小RBACを付与する。
7. Foundry projectを既存Application Insightsへ接続し、Core runだけを収集する。

Application Insights/DCR/Private Link/DNS/route/private collectorの変更は含めない。T1〜T4も有効化しない。

## RBAC

| Identity | Role | Scope | 理由 |
|---|---|---|---|
| runtime | Search Index Data Reader | Search service | Toolbox queryのみ |
| index manager | Search Service Contributor | Search service | index schema管理のみ |
| document ingestor | Search Index Data Contributor | Search service | document投入のみ |

実object IDは承認前確認時に取得する。Secret credentialは使用しない。

## 費用影響

- Prompt-based Agent自体の作成・実行に追加Agent料金はないが、model tokenとSearch/Tool接続は別課金になる。
- Hosted親は専用containerのvCPU-hour/GiB-hour、親modelはtoken、Azure AI Searchは選択tier/Search Unit、Application Insightsはingestion・拡張retentionが課金要素になる。
- 既存Search serviceを再利用する場合も稼働tierの時間課金は継続する。新規Search serviceはこのBicepでは作らない。
- 実金額はregion、契約通貨、Search SKU、Hosted compute、model deployment、run数、telemetry量が確定してからAzure Pricing Calculatorで再計算する。T2を有効化しないため、継続評価反復・cost観測反復は行わない。

## 実行前のread-only/static command

```bash
.venv313/bin/python scripts/validate_search_assets.py
.venv313/bin/python scripts/validate_deployment_assets.py
.venv313/bin/python scripts/prepare_search_documents.py --output-dir .artifacts/search
AZURE_CONFIG_DIR=/tmp/procurement-azure-config az bicep build --file infra/main.bicep --outfile /tmp/procurement-main.json
az deployment group what-if --resource-group <RESOURCE_GROUP> --template-file infra/main.bicep --parameters @<APPROVED_PARAMETERS_FILE>
```

`what-if`はAzureを変更しないが、外部subscriptionへの問い合わせを伴うため承認runで実施する。

## 承認後のapply順序

以下はplaceholderをread-only discovery結果で置換し、一覧を再提示してから順に実行する。

```bash
# 1. RBAC
az deployment group create --resource-group <RESOURCE_GROUP> --template-file infra/main.bicep --parameters @<APPROVED_PARAMETERS_FILE>

# 2. Search index schema
az rest --method put --url "https://<SEARCH_SERVICE>.search.windows.net/indexes/procurement-catalog-v1?api-version=2025-09-01" --resource "https://search.azure.com" --body @infra/search/indexes/procurement-catalog-v1.json
az rest --method put --url "https://<SEARCH_SERVICE>.search.windows.net/indexes/procurement-code-master-v1?api-version=2025-09-01" --resource "https://search.azure.com" --body @infra/search/indexes/procurement-code-master-v1.json

# 3. Synthetic document upload
az rest --method post --url "https://<SEARCH_SERVICE>.search.windows.net/indexes/procurement-catalog-v1/docs/index?api-version=2025-09-01" --resource "https://search.azure.com" --body @.artifacts/search/catalog-upload-batch.json
az rest --method post --url "https://<SEARCH_SERVICE>.search.windows.net/indexes/procurement-code-master-v1/docs/index?api-version=2025-09-01" --resource "https://search.azure.com" --body @.artifacts/search/code-upload-batch.json
```

Toolbox、Prompt Agent、Hosted親は、承認時点のFoundry project/model/ACR/identityをread-only確認後、Microsoft Foundry deployment workflowで作成する。`azd up`、ACR build、Agent create、container startを個別に先行実行しない。environment variable名とmask済みsourceを確認し、Prompt Agent → Hosted親 → invocation → Trace確認の順で進める。

## Rollback

rollbackは作成したresource IDと以前のAgent versionを記録してから実施する。

1. Hosted親containerを停止し、前versionへtrafficを戻す。
2. 今回作成したPrompt Agent versionとToolboxだけを削除する。
3. 今回投入した`source_version=2026-09-01.1` documentだけを削除する。
4. 今回作成した2 indexだけを削除する。
5. Bicepが作成した3 role assignmentだけを削除する。

既存Search service、Foundry project、Application Insights、model deploymentは削除しない。削除commandは対象resource IDをread-only再確認し、破壊操作として再承認を得てから提示・実行する。
