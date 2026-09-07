# Hosted親Agentのデプロイ

対象は既存Foundry projectへ`procurement-parent-agent`の新しいimmutable versionをsource ZIPで作成する手順である。ACRは使わない。

公式資料: [Deploy a hosted agent from source code](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/deploy-hosted-agent-code)

## Repository配置の判断

`azure.yaml`はHosted専用ファイルではなく、azdがproject全体のservice mappingを読むmanifestである。公式[azure.yaml schema](https://learn.microsoft.com/en-us/azure/developer/azure-developer-cli/azd-schema)のconventionどおりRepository rootに置く。`src/procurement_agent`へ移さない。

`requirements-lock.txt`もrootの`requirements.txt`から相対参照され、`scripts/package_hosted.py`がZIP rootへ配置する。移動するとlocal installまたはremote buildの片方が別lockを使うため、rootに保持する。

Source treeとdeployment artifactの対応は次のとおり。

```text
Repository root
├─ azure.yaml                    # azd project manifest。ZIPには含めない
├─ main.py                       # ZIP root entry point
├─ requirements.txt             # ZIP root
├─ requirements-lock.txt        # ZIP root constraints
├─ src/procurement_agent/*.py    # ZIP内 procurement_agent/*.py
├─ src/trace_pipeline/           # ZIP内 Stage B harness/detectorの4 allowlist file
└─ scripts/package_hosted.py     # allowlist packager
```

公式source deploymentの最小条件である`main.py`と`requirements.txt`のZIP root配置を満たす。データ、WebApp、`.env`、local state、ACR情報は含めない。

## 1. 前提確認

- 2つのPrompt子Agentが`ACTIVE`
- 使用versionを記録済み
- deployment callerに既存Foundry projectの`Foundry Project Manager`相当
- Hosted identityはAgent version作成後にFoundryが作る
- App Service system MIへHosted endpoint呼出し用`Foundry Agent Consumer`をAgent scopeで付与できる

## 2. Local検証とZIP作成

既存出力を上書きしない一意名を使う。

```bash
PYTHONPATH=src:scripts .venv/bin/python scripts/validate_deployment_assets.py
PYTHONPATH=src:scripts .venv/bin/python scripts/package_hosted.py \
  /tmp/procurement-parent-source-$(date +%Y%m%d%H%M%S).zip
unzip -l /tmp/procurement-parent-source-*.zip
```

期待するallowlistは`main.py`、`requirements.txt`、`requirements-lock.txt`、`procurement_agent/*.py`と、`trace_pipeline`の`__init__.py`/`detectors.py`/`envelope.py`/`stage_b.py`だけ。packagerはSHA-256を表示するのでdeployment記録へ保存する。

## 3. 新version作成

[共通環境変数](README.md#共通の環境変数)を設定し、Prompt子の既存versionを`.local_state/deployment/foundry-deployment.json`へ記録してから実行する。別環境へ持ち込む場合、manifestをblind copyせず、実projectで取得したversionを記録する。

```bash
PYTHONPATH=src:scripts .venv/bin/python scripts/deploy_foundry.py hosted --new-version
```

scriptが作成する定義:

| 設定 | 値 |
| --- | --- |
| protocol | Responses `2.0.0` |
| runtime | Python 3.13 |
| dependency resolution | `remote_build` |
| entry point | `python main.py` |
| CPU/memory | 0.5 CPU / 1 GiB |
| parent model | `PROCUREMENT_PARENT_MODEL_DEPLOYMENT` |
| child references | Catalog/Codeの記録済みimmutable version |
| propagator | `tracecontext,baggage` |
| content capture | Hosted側はfalse。Managed Prompt側への適用は保証しない |
| Azure Core injection gate | `PROCUREMENT_ENABLE_SYNTHETIC_INJECTIONS=true`。`synthetic=true`、`stage-b-v1` contract、固定profile、`AZURE-CORE-` case prefixの全条件が必要 |

既存Agentの上書きや削除は行わず、新versionだけを作る。記録済み既存versionがない状態で同名Agentを検出した場合は停止する。

## 4. Verify

作成応答だけで完了とせず、version statusが`ACTIVE`になるまで確認する。次にSynthetic 1会話をResponses protocolで実行し、少なくとも次を確認する。

- application/plan/catalog/code/merge/response span
- child Agent/Toolbox/index version
- technical/business/MCP/Search/parse status
- Conversation ID、Framework Session hash、turn、test.case.id
- draftは全検証成功時だけ存在

Platform境界でTraceが分かれる場合は`NOT_PROPAGATED`とし、response ID/Conversation IDで代替相関する。失敗versionや以前のversionを削除しない。rollbackは既知の正常versionを呼出し先として再選択する。

Stage Bを別環境で再現するときは、通常WebUIからmetadataを転送せず、project RBACを持つ検証callerだけが`scripts/run_azure_core_validation.py`を明示実行する。6 injectionとS1/S5 Healthyの結果は`semantic.evaluate` spanで確認し、通常会話にfailure profileを混在させない。
