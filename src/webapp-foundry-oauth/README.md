# webapp-foundry-oauth — OAuth画面を使う購買支援Web

2026-09-08更新。起動入口は **`backend/server.py:app`**。旧OAuth版のHTML/JavaScript・ジョブ・SSE・同意／承認画面を再利用します。

ユーザー委任Tokenで購買Hosted Agentだけを呼びます。名前取得が有効ならHosted内のOBO Agent ToolがFoundryToolbox経由でGraph /meを呼び、本人照合した名前をControllerへ渡します。省略・失敗時は名前をnullとして購買を継続します。

詳細なソース対応、API・metadata契約、OTel、配備先、必要設定と検証境界は [OAuth Web復帰・任意OBO連携ガイド](/home/hnakajima/work/foundry-procurement-agent/docs/observability-integration/oauth-wrapper-implementation.md) にまとめています。

## 設定

[.env.example](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/.env.example) を参照してください。`PROJECT_ENDPOINT`／`AGENT_NAME` は購買向け、`IDENTITY_PROJECT_ENDPOINT`／`IDENTITY_AGENT_NAME` は名前取得向けです。購買認証は常にMI、名前取得は `IDENTITY_USER_AUTH_MODE`（既定refresh_token）です。旧 `FOUNDRY_USER_AUTH_MODE` による全呼び先一括切替は使用しません。

旧画面の既定動作は `IDENTITY_LOOKUP_ENABLED=true/false` で切り替えます。省略時はfalse。`POST /api/chat` の `lookupApplicant` でturnごとに上書き可能です。元UIへ切替ボタンは追加していません。名前取得の承認拒否、または `/api/continue` の `skipIdentity:true` で名前なしの購買へ進めます。

EasyAuth token store・Foundry委任permission・利用者のFoundry権限・APIMの新しい委任経路が未設定だと、名前取得はFAILEDになります。詳細は上記ガイドを参照してください。Web MIの既存購買経路と権限はそのまま使います。

## 配布

```bash
python scripts/package-procurement.py /tmp/procurement-oauth-web.zip
```

ZIPは8ファイルのallowlistで生成し、既存ファイルを上書きしません。Oryxはルートrequirementsを読み、startup.shがserver:appを1workerで起動します。元の提供ZIPを上書きするdeploy-web.sh／.ps1は引き続き停止しています。

`backend/procurement.py` と `static/procurement.*` は2026-09-07までの購買専用UI実装としてソースに残りますが、今回のZIPには入りません。以前の実装・配布方法はGit履歴の `e7fd85c` を参照してください。

## 観測と状態

Provider／Azure Monitor Trace Exporterは `backend/telemetry.py` のlifespanで初期化し、実際のHTTPX clientへ計装します。氏名やTokenをログ・Spanへ記録しません。`user.id` はEasyAuthのtid/oidのSHA-256です。

購買・OAuth同意後の再実行は同じFoundry Conversationを使用し、元の依頼を再送します。ジョブ・Webの再開情報は1インスタンスのメモリ内です。再起動・配布後は新しい会話から再開してください。旧画面は利用者別localStorageに会話を保存します。

## ローカル検証

リポジトリrootから、Azureに接続しないHTTPX/SSE fixtureで検証できます。

```bash
TMPDIR=/tmp PYTHONPATH=src:scripts .venv/bin/python -m pytest -q tests/unit/test_oauth_procurement.py src/webapp-foundry-oauth/tests/test_stream_response.py
```

配備済みバージョンと実Azure検証の結果は実装ガイドを参照してください。
