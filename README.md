# Foundry 購買支援・オブザーバビリティ検証

Webから購買HostedAgentを呼び、商品・部署検索とPlan & Executeの観測を検証するPoCです。明示的な本人確認の質問は同じHosted内の独立OBO経路へ分岐します。通常購買ではOBOを呼ばず、取得した名前を購買へ持ち越しません。

## 最初に読む資料

| 対象 | 実装・設定・Azure配布手順 |
|---|---|
| App ServiceのWeb | [WebApps README](src/webapp-foundry-oauth/README.md) |
| 購買HostedAgent | [HostedAgent README](src/hosted-agent/README.md) |
| OBO用MCP Functions | [Functions README](src/functions-mcp-selfhosted/README.md) |
| 別環境・別Agentへの移植 | [統合ガイド](docs/observability-integration/README.md) |
| Search／Prompt／APIM等の基盤 | [配備資料](docs/deployment/README.md) |
| 仕様・制限・検証結果 | [ドキュメント一覧](docs/README.md) |

## フォルダー構成

```text
src/
  webapp-foundry-oauth/       # Web、requirements、起動・ZIP梱包
  hosted-agent/              # main.py、requirements、pyproject、Pythonパッケージ
  functions-mcp-selfhosted/  # MCP/OBO、host.json、Functions配布
scripts/                    # 共通基盤・Foundry配布・検証スクリプト
infra/                      # 共通Azure／Foundry／Search定義
data/                       # 検索データの正本
trace_fixtures/              # 観測検証fixture
tests/                      # コンポーネントをまたぐ回帰テスト
docs/                       # 現行資料・日付付き検証報告
  trash/                    # 旧資料。現在の手順には使用しない
.foundry/                   # 配布先メタデータ・Azure検証証跡
azure.yaml                  # プロジェクト全体のazdサービス定義
pytest.ini                  # 共通テスト設定
```

`.local_state/`は環境別の配備manifest／状態、`.artifacts/`は配布ZIP等の生成物です。個人設定・仮想環境・未追跡の証跡は構成整理で削除しません。`.foundry/agent-metadata.yaml`は配備時点の記録で、ソース移動自体はAzure上のコードを変更しません。

## 開発とローカル検証

以下はリポジトリルート、Linux／WSL、Python 3.13で実行します。

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -e ./src/hosted-agent -r src/hosted-agent/requirements-dev.txt -r src/webapp-foundry-oauth/requirements.txt
TMPDIR=/tmp PYTHONPATH=src/hosted-agent:scripts .venv/bin/python -m pytest -q tests src/webapp-foundry-oauth/tests/test_stream_response.py
PYTHONPATH=src/hosted-agent:scripts .venv/bin/python scripts/validate_deployment_assets.py
PYTHONPATH=src/hosted-agent:scripts .venv/bin/python scripts/validate_search_assets.py
```

既存のeditable installは配置変更後に`pip install -e ./src/hosted-agent --no-deps`で更新できます。Functions単体の起動環境はFunctions READMEを参照してください。通常テストはAzureに接続せず、外部E2Eは明示的な環境設定がない場合スキップします。

Azureへの配布は各READMEの手順で実行します。環境変数、権限、配備先を確認し、ローカル検証と実Azure検証を区別してください。過去の配置からの移動一覧は[整理記録](docs/repository-layout.md)にあります。
