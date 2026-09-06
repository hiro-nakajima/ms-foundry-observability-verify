# Azure AI Search: JSON Data source / Indexer / Index

対象は既存Azure AI Searchへ、Repositoryのversion付きSynthetic JSONをBlob Indexer経由で投入する手順である。商品・価格・勘定科目・部署コードをAgent Instructionsやcontainer imageへデータとして埋め込まない。

公式資料: [JSON Blobのindexing](https://learn.microsoft.com/en-us/azure/search/search-how-to-index-azure-blob-json)

## 完成形

| Source | Blob container | Indexer | Target index |
| --- | --- | --- | --- |
| `data/catalog.json` | `procurement-catalog` | `procurement-catalog-blob-indexer` | `procurement-catalog-v1` |
| `data/account_codes.json` + `data/departments.json` | `procurement-code-master` | `procurement-code-master-blob-indexer` | `procurement-code-master-v1` |

各containerには`documents.json`を1つ置く。形式はJSON arrayで、Indexerの`parsingMode=jsonArray`により配列要素を1 Search documentとして取り込む。

## RBAC

| Identity | Scope | Role |
| --- | --- | --- |
| schema管理者 | Search service | Search Service Contributor |
| document投入者 | 2 index | Search Index Data Contributor |
| Search service system MI | 各Blob container | Storage Blob Data Reader |
| JSON upload caller | 各Blob container | Storage Blob Data Contributor |
| Foundry project MI | 各index | Search Index Data Reader +必要最小read-only metadata role |

共有key、Search admin key、Storage account keyを使わない。query identityへdocument更新権限を付けない。

## 1. JSON documentを生成

```bash
PYTHONPATH=src:scripts .venv/bin/python scripts/prepare_search_documents.py \
  --output-dir .artifacts/search
```

生成物の`manifest.json`で次を確認する。

- source versionが3つのRepository JSONで一致
- Catalog 11件、Code Master 10件（現行data version）
- document hash
- `synthetic=true`

## 2. StorageとSearch identity

Storageがまだない場合だけwhat-if後に作成する。`infra/search-blob.bicep`はStorageV2/Standard_LRS/Hot、public blob/shared key無効、TLS 1.2、soft delete 7日、2 private container、container-scope RBACを定義する。

```bash
PYTHONPATH=src:scripts .venv/bin/python scripts/deploy_blob_indexers.py plan
# what-ifがCreate/NoChange/Ignoreだけであることを人が確認
PYTHONPATH=src:scripts .venv/bin/python scripts/deploy_blob_indexers.py apply
```

既存Storageを使う場合は`plan/apply`を実行せず、同じ2 containerとRBACを準備して次へ進む。

## 3. Index schemaだけを作成

schema正本:

- `infra/search/indexes/procurement-catalog-v1.json`
- `infra/search/indexes/procurement-code-master-v1.json`

```bash
PYTHONPATH=src:scripts .venv/bin/python scripts/deploy_search.py permissions
PYTHONPATH=src:scripts .venv/bin/python scripts/deploy_search.py schemas
```

`schemas`はindexがなければ`If-None-Match: *`で作り、存在時はfield名/typeをread-backする。異なるschemaを置換しない。Blob経路を使う場合、`deploy_search.py push`は実行しない。

## 4. Blob/Data source/Indexerを作成して投入

```bash
PYTHONPATH=src:scripts .venv/bin/python scripts/deploy_blob_indexers.py ingest
```

scriptは次を行う。

1. Repository JSONからdocumentを再生成
2. Blobへuploadしてread-back byte一致を確認
3. Data sourceを`ResourceId=<storage-resource-id>;`のManaged Identity接続で作成
4. `jsonArray`、失敗許容0、scheduleなしのIndexerを作成
5. 既存定義はETag/allowlist内容を照合し、差異があれば上書きせず停止
6. 新規Indexerは自動実行、既存Indexerは明示run

## 5. Verify

```bash
PYTHONPATH=src:scripts .venv/bin/python scripts/deploy_blob_indexers.py verify
```

PASS条件:

- 両Indexerのstatusが`success`
- items failed/error/warningが0
- full ingestion時刻が今回の投入以後
- document countがRepository manifestと一致
- 全document projectionがRepository生成値と一致

その後、両ToolboxのMCP `tools/call`でCatalog仕様/価格/source versionと、Code Masterのaccount/department code/source versionを確認する。

## 更新と削除の注意

- JSONの要素削除は既存Search documentを自動削除しない。削除同期を要件にする場合は明示的なdelete actionまたはindex rebuild設計が必要。
- field削除/型変更はin-placeで行わず、新version indexへ移行する。
- Indexer/Data source/Index/Storageの削除はこの手順に含めない。
- Serverless Developerはpreview/SLAなしでscale-to-zeroする。Indexer自体は対応するが、private networking for indexers等のpreview制約がある。最新の[Search tier資料](https://learn.microsoft.com/en-us/azure/search/search-sku-tier)を配備直前に確認する。
