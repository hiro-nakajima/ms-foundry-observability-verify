# Azure AI Search: 現行JSON定義の再投入

この手順ではPython deployment scriptを必須にしない。現在のPoCで実際に使用しているData source、Index、Indexer、およびBlobへ格納するSearch documentを静的JSONとしてRepositoryに保存し、別環境へ投入する。

公式資料: [JSON Blobのindexing](https://learn.microsoft.com/en-us/azure/search/search-how-to-index-azure-blob-json)

## JSON資産

| 種別 | Catalog | Code master |
| --- | --- | --- |
| Blob document | `infra/search/documents/procurement-catalog/documents.json` | `infra/search/documents/procurement-code-master/documents.json` |
| Data source | `infra/search/datasources/procurement-catalog-blob-source.json` | `infra/search/datasources/procurement-code-master-blob-source.json` |
| Index | `infra/search/indexes/procurement-catalog-v1.json` | `infra/search/indexes/procurement-code-master-v1.json` |
| Indexer | `infra/search/indexers/procurement-catalog-blob-indexer.json` | `infra/search/indexers/procurement-code-master-blob-indexer.json` |

`infra/search/documents/manifest.json`には、現行データversion、件数、document hashを記録している。現行値はCatalog 11件、Code master 10件、source version `2026-09-04.1`である。

各`documents.json`はJSON arrayであり、Indexerの`parsingMode=jsonArray`によって配列要素を1 Search documentとして取り込む。Pythonを実行してdocumentを生成する必要はない。

## 環境固有値

Data source JSONの`credentials.connectionString`はsecretではなく、現在のStorage Account resource IDを次の形式で保持している。

```text
ResourceId=/subscriptions/.../resourceGroups/.../providers/Microsoft.Storage/storageAccounts/...;
```

別環境へ投入する前に、このresource IDだけを別環境のStorage Accountへ置換する。Search key、Storage key、SAS、接続文字列のsecretをJSONへ追加しない。

AzureのGET responseに含まれる`@odata.etag`、Indexer実行履歴、status、`null`の既定値はcreate/update用payloadではないため、RepositoryのJSONには含めていない。

## 前提RBAC

| Identity | Scope | Role |
| --- | --- | --- |
| JSONを投入する操作者 | Search service | Search Service Contributor |
| Search service system MI | 2つのBlob container | Storage Blob Data Reader |
| Blob upload操作者 | 2つのBlob container | Storage Blob Data Contributor |
| Foundry/Toolbox runtime identity | 対象index | Search Index Data Readerと必要最小のread-only metadata role |

query identityへdocument更新権限を付けない。

## 再投入の順序

### 1. Blob containerとdocument

既存Storage Accountに次のprivate containerを作成する。

- `procurement-catalog`
- `procurement-code-master`

それぞれへ対応する静的JSONを`documents.json`というBlob名でuploadする。Azure CLIを使用する場合の例:

```bash
az storage blob upload \
  --auth-mode login \
  --account-name '<storage-account>' \
  --container-name 'procurement-catalog' \
  --name 'documents.json' \
  --file 'infra/search/documents/procurement-catalog/documents.json' \
  --overwrite

az storage blob upload \
  --auth-mode login \
  --account-name '<storage-account>' \
  --container-name 'procurement-code-master' \
  --name 'documents.json' \
  --file 'infra/search/documents/procurement-code-master/documents.json' \
  --overwrite
```

### 2. Index

Azure PortalのSearch serviceで各Index JSONを指定して作成するか、REST APIのrequest bodyとしてそのまま使用する。

```bash
az rest --method put --resource https://search.azure.com \
  --url 'https://<search-service>.search.windows.net/indexes/procurement-catalog-v1?api-version=2026-08-01-preview' \
  --body @infra/search/indexes/procurement-catalog-v1.json

az rest --method put --resource https://search.azure.com \
  --url 'https://<search-service>.search.windows.net/indexes/procurement-code-master-v1?api-version=2026-08-01-preview' \
  --body @infra/search/indexes/procurement-code-master-v1.json
```

既存の同名Indexとfield/typeが異なる場合は上書きしない。新しいversion名のIndexを作成する。

### 3. Data source

Data source JSON内のStorage resource IDを別環境の値へ置換してから投入する。

```bash
az rest --method put --resource https://search.azure.com \
  --url 'https://<search-service>.search.windows.net/datasources/procurement-catalog-blob-source?api-version=2026-08-01-preview' \
  --body @infra/search/datasources/procurement-catalog-blob-source.json

az rest --method put --resource https://search.azure.com \
  --url 'https://<search-service>.search.windows.net/datasources/procurement-code-master-blob-source?api-version=2026-08-01-preview' \
  --body @infra/search/datasources/procurement-code-master-blob-source.json
```

### 4. Indexer

最後にIndexer JSONを投入する。新規Indexerは通常作成時に実行される。必要ならPortalのRun、または`POST /indexers/<name>/run`を1回実行する。

```bash
az rest --method put --resource https://search.azure.com \
  --url 'https://<search-service>.search.windows.net/indexers/procurement-catalog-blob-indexer?api-version=2026-08-01-preview' \
  --body @infra/search/indexers/procurement-catalog-blob-indexer.json

az rest --method put --resource https://search.azure.com \
  --url 'https://<search-service>.search.windows.net/indexers/procurement-code-master-blob-indexer?api-version=2026-08-01-preview' \
  --body @infra/search/indexers/procurement-code-master-blob-indexer.json
```

## 完了確認

- Catalog Indexer: `success`、processed 11、failed 0、warning 0
- Code master Indexer: `success`、processed 10、failed 0、warning 0
- Index document countがmanifestと一致
- Catalog検索結果に商品コード、価格、仕様、source versionが含まれる
- Code master検索結果に勘定科目コード、部署コード、source versionが含まれる
- Toolboxの`tools/call`が対応するIndexだけを参照する

JSONの要素削除は既存Search documentを自動削除しない。削除同期が必要な場合は明示的なdelete actionまたは新version Indexへのrebuildを行う。この手順は既存資産の削除を含まない。
