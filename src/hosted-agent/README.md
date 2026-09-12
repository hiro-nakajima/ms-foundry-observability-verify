# HostedAgent — 購買Plan & ExecuteとOBO検証

このフォルダーがHostedAgentのソースルートです。配布入口は`main.py`、実装パッケージは`procurement_agent/`。Pythonのimport名は従来と同じです。

## 実行経路

```text
Responses入力
  ├─ 「私は誰ですか」等 → OBO Agent Tool → Toolbox → Functions → Graph /me
  └─ 購買要求 → 親Agent → ControllerContextProvider → Plan & Execute
                    Catalog Agent → Code Agent → 統合・検証・応答
```

OBOはHostが明示的な入力で選択する独立経路です。購買LLMが任意にOBOを選ぶ構成ではありません。名前はOBO応答だけに使い、通常購買へ持ち越しません。Web独自のidentity metadataは不要です。

## フォルダー・ファイル

| パス | 役割 |
|---|---|
| `main.py` | Azure source ZIPの起動入口 |
| `requirements.txt`／`requirements-lock.txt` | 実行依存と固定した依存制約。Azure remote buildの正本 |
| `requirements-dev.txt` | ローカルテスト用依存 |
| `pyproject.toml` | ローカルパッケージ・CLI定義。ZIPには含めない |
| `.env.example` | 必要な環境変数のひな形。自動読込しない |
| `procurement_agent/hosted_app.py` | Responses Host、要求の振り分け、OBO同意応答 |
| `procurement_agent/hosted.py` | 親／Planner／子Agent Toolの組立、ContextProvider |
| `procurement_agent/controller.py` | Plan生成、step実行、保存結果再利用、統合検証 |
| `procurement_agent/identity.py` | OBO Agent Tool、Toolbox whoami、結果・同意の処理 |
| `procurement_agent/observability.py` | Host共通Provider、業務Span、例外本文の抑止 |
| `procurement_agent/models.py`／`session_state.py` | 型付き入出力・購買状態 |
| `procurement_agent/framework.py`／`middleware.py` | Framework接続と入出力の検証 |
| `procurement_agent/azure_validation.py`／`trace_pipeline/` | 障害注入・検出器などPoC評価用。通常購買への移植には不要 |
| `procurement_agent/devui_app.py` | ローカルDevUI。配布ZIPから除外 |

商品・部署検索Prompt Agentの定義は[共通infra](../../infra/foundry/agents)にあり、Hosted内部へ子の実装は同梱しません。共通配布スクリプトは[ルートscripts](../../scripts)に残しています。

## 必要な環境設定

| 設定 | 用途 |
|---|---|
| `FOUNDRY_PROJECT_ENDPOINT` | Foundry project。Hostedではプラットフォーム注入値を利用する |
| `PROCUREMENT_PARENT_MODEL_DEPLOYMENT` | Plannerで使う既存モデルdeployment名 |
| `PROCUREMENT_CATALOG_AGENT_NAME`／`PROCUREMENT_CATALOG_AGENT_VERSION` | 登録済み商品検索Agentの名前・version |
| `PROCUREMENT_CODE_AGENT_NAME`／`PROCUREMENT_CODE_AGENT_VERSION` | 登録済みコード決定Agentの名前・version |
| `PROCUREMENT_IDENTITY_TOOLBOX_ENDPOINT` | OBO検証用Toolbox。未設定なら購買は動作し、本人確認には未設定を案内 |
| `OTEL_PROPAGATORS` | `tracecontext,baggage` |
| `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` | 起動コードで`false`を設定 |
| `PROCUREMENT_ENABLE_SYNTHETIC_INJECTIONS` | 検証用。通常利用では省略／false。既存配布scriptはPoC検証のためtrue |

Hostの`configure_observability`と共有Providerを使用します。Agent／Tool／MCP SpanはSDKに任せ、`plan.create`／`plan.step.execute`等の業務境界だけを追加します。受信baggageのメール`user.id`は観測専用です。本人認証には使いません。実サービス境界でbaggageが欠落する場合は、Trace／Conversation／Response IDで相関します。

## ローカル起動確認

ルートREADMEの依存インストール後、このフォルダーで実行します。

```bash
../../.venv/bin/python main.py --smoke
```

実Foundryへ接続するローカル起動では`.env.example`の値をプロセス環境変数へ設定し、必要なAzure資格情報を用意してください。`--smoke`は資格情報不要です。別Agentへ移植する場合、`HostedAgentBundle`をそのまま採用する必要はなく、既存Executorから観測ヘルパーを使用できます。

## Azureへのsource ZIP配布

ACRは使用しません。以下はリポジトリルートで実行します。

1. [共通環境変数](../../docs/deployment/README.md#共通の環境変数)で対象projectを明示し、Azure CLIへサインインする。
2. Search／Toolbox／Prompt子Agentを準備し、実際の子versionを環境別`.local_state`のmanifestへ記録する。別環境のmanifestを流用しない。
3. OBOを使う場合、Functions／OAuth connection／Identity Toolboxを準備する。`identity-deployment.json`の`toolboxEndpoint`を配布scriptが参照する。
4. ZIP梱包とローカル検証を行う。

```bash
PYTHONPATH=src/hosted-agent:scripts .venv/bin/python scripts/package_hosted.py /tmp/procurement-hosted.zip
PYTHONPATH=src/hosted-agent:scripts .venv/bin/python scripts/validate_deployment_assets.py
```

ZIP直下には`main.py`、`requirements.txt`、`requirements-lock.txt`と、`procurement_agent/`、`trace_pipeline/`を配置します。trace_pipelineには評価に必要な4ファイルだけを含めます。梱包はallowlist方式で、README・データ・Web・Functions・.env・ローカル状態を含めません。同名ZIPが存在すると上書きせず失敗します。

既存Agentを更新するとき:

```bash
PYTHONPATH=src/hosted-agent:scripts .venv/bin/python scripts/deploy_foundry.py hosted --new-version
```

初回は子version等のmanifestを用意したうえで`--new-version`を省略します。scriptはPython 3.13／remote_build／`python main.py`で新versionを作成し、既存Web MIへのロール付与も確認・実行します。既存versionを削除しません。受理時のCREATINGと稼働可能なACTIVEを区別し、読み戻し後に呼出し確認してください。

配布先は`.foundry/agent-metadata.yaml`、version／ZIP hashは`.local_state`のmanifestに記録します。現在の検証履歴は[Hosted検証記録](../../docs/observability-integration/hosted-refactor-validation-20260912.md)。今回はフォルダー移動であり、Azureへの再配布は実行していません。

参考: [Microsoft公式source deployment](https://learn.microsoft.com/azure/foundry/agents/how-to/deploy-hosted-agent-code)。
