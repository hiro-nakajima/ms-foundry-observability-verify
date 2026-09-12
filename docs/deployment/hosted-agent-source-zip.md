# Hosted source ZIP配布

現在の手順・必要設定・ファイル概要は[HostedAgent README](../../src/hosted-agent/README.md)を正本とします。ソースは`src/hosted-agent/`へ集約しました。`azure.yaml`は複数コンポーネントのサービス定義なのでリポジトリrootに残します。

| ソース | 配布ZIP |
|---|---|
| `src/hosted-agent/main.py` | `main.py` |
| `src/hosted-agent/requirements.txt`／lock | ZIP rootのrequirements／lock |
| `src/hosted-agent/procurement_agent/*.py` | `procurement_agent/*.py`（devui除外） |
| `src/hosted-agent/trace_pipeline/` | 評価に必要な4ファイルのみ |

`../../scripts/package_hosted.py`がこの対応で梱包します。配置変更によってZIPの実行入口やPython import名は変更しません。デプロイ前に新配置での梱包・展開起動テストを実行してください。

[共通の環境変数](README.md#共通の環境変数)／[既存設定の読取資料](hosted-agent-settings.md)／[検証記録](../observability-integration/hosted-refactor-validation-20260912.md)
