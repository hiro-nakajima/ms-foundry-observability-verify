# WebApp整理・観測改善の検証記録（2026-09-12）

## 変更

- `server.py`から認証を`auth.py`、Foundry HTTP/SSE通信を`foundry_client.py`へ分離。
- `procurement_flow.run`へ状態と関数を明示的に渡し、serverモジュール全体への依存を除去。
- ジョブSpanへ結果属性、失敗状態、Foundry Conversation/Response IDを記録。
- アプリloggerをTrace/Span IDと関連付け、Azure Monitorへログを送信。
- 移植上の要点に日本語コメントを追加。認証・同意・画面の機能は追加していない。
- 未配布の旧購買UI、旧デプロイスクリプト、旧UI専用テスト、重複requirementsを削除。
- 現行コードが直接使用しない`azure-ai-projects`と`openai`をWebの依存から削除。

最新の責務分担と組み込み方は[WebApp README](../../src/webapp-foundry-oauth/README.md)を参照。

## ローカル検証

- 現行unit suite: 84件成功。
- Web回帰: 27件＋2 subtests成功。上記unit suiteと重複するため合算しない。
- 配布ZIPへ同梱した依存でもWeb回帰27件＋2 subtests成功。
- 認証16関数は移動前と処理のASTが一致。docstring変更のみ除外。
- 日本語コメント追加前後で全5モジュールの処理ASTが一致。
- `compileall`と`git diff --check`成功。
- 通常完了、上流HTTP失敗、OAuth同意待ち、MCP承認待ち、キャンセル、ログとSpanのID一致、ログへのfixture秘密値の非混入を検証。
- 既存Starlette TestClientの非推奨警告は残る。テスト成功に影響なし。

## Azure配布

- Subscription: `d96eb8c2-2deb-4ed5-8cf2-f9fb178cb3ee`
- Resource group: `rg-ms-foundry-observability-verify`
- WebApp: `web-procurement-observe-nkjm`
- Runtime: `PYTHON|3.13`、startup: `bash startup.sh`
- 既存のEasyAuth・APIM・Hosted Agent設定は変更していない。
- 最終Deployment ID: `0eefe607-54a9-4872-ae18-500548deed58`
- Kudu: `status=4`, `complete=true`, `active=true`。完了時刻: `2026-09-12T08:13:52.5128259Z`。
- ZIP SHA-256: `5fbe73c56c68b4f8ad5ac8d0d1984921e197b45046ac197cfc324d1f85eccdc9`
- 最初の配布（コメント追加前）はARMで`RuntimeSuccessful`、成功1インスタンスを確認。
- 最終版もARM deploymentStatusで`RuntimeSuccessful`、成功1・失敗0・起動中0インスタンスを確認。
- 最終版は下記6ファイルをKuduから読み戻し、ローカルとバイト単位で一致。

| 配布ファイル | SHA-256 |
|---|---|
| `backend/server.py` | `07b3177027cc00502d615528bb539ce3cb8454bb6f58c0298ba6cad786c3dabf` |
| `backend/auth.py` | `1d80afd7a9ec1905285cc820719576fd86531a2a26ba8927f771d4f9e91a258f` |
| `backend/foundry_client.py` | `2048693a718db2893ae5efc73ba7cac75afc97142166d9a5fe767bc8a6aef04d` |
| `backend/procurement_flow.py` | `d0e34f747236a6fa24025a62aa274a5f866b8c3f611a73490b4f2a4d0401bf18` |
| `backend/telemetry.py` | `8cafdbcbfb1da7a105a762b919c9351fbc0311650ac83c1dadf6c1c3c733b863` |
| `requirements.txt` | `782e9bc789d271f03a2f204b190fd7037a47f54c2821c3cc766939c29ac7c3c0` |

## 検証境界

未認証の`/health`と`/api/me`はEasyAuthで401となった。認証保護は維持されているが、この結果だけではPythonアプリのヘルス確認にはならない。

実ユーザー操作でWeb→Hostedの応答とTrace/Logの到達を確認。Trace ID `977ff95bfcf1a1007b1bef3e296903ff`、Response ID `caresp_062226078ba169aa00XnXuxZQwf5i64NvP97ohgeglJAUrEyBW`。Webの`web.chat.job`、認証Span、呼出しSpanと通常ログが同じOperation IDを持ち、ジョブ結果は`completed`。

初回確認では名前取得が未成功だった。Hosted v33で`identity.lookup=FAILED`、stage=`call`、`ToolExecutionException`、RPC=`-32006`。ツール一覧取得は成功し、whoami実行時にOAuth同意URL単体が返っていた。SDKの同意パーサーはtools/listのJSON形式のみ対応するため、同意待ちに変換できず名前nullで継続した。Webの名前取得設定はtrue、委任トークン取得も成功している。

Hostedの`identity._consent`へURL単体形式の処理を追加。HTTPSかつ既知のFoundry同意ホスト・パスだけを許容し、URLをログに出すSDKの未対応形式warningを避ける。修正版配布後、実Webでの再同意・Graph OBO成功を確認した（以下参照）。

Webの状態はメモリ内のため、配布後は新しい会話を使用する。GitHubへのcommit/push/PR/mergeは今回実施していない。

## 名前取得の再同意対応

- Hosted v34を作成し、`get_version`で`ACTIVE`を確認。
- Source ZIP SHA-256: `0a1eacefcd1e418f4e94d5e078c82f754cee217e8f726d725e865aa601771b1a`。
- v33の環境変数9項目と同じ値を使用。既存v33は保持。
- 旧container向けCLI startは404。このsource-ZIP方式は作成後にACTIVEとなるため、追加のcontainer起動操作は不要。
- Hosted修正後のunit suiteは89件成功。URL単体・JSON形式の同意待ち／再開、許可外URLの拒否、パーサーのログ非混入を含む。
- 修正版の直接Foundry呼び出しで`oauth_consent_request`＋`response.incomplete`を確認。Case `OBO-CALL-CONSENT-e4c965ee8640`、Response `caresp_027a559e9e9e311900iFOytpxYRwIZ5GzeLGe6AnpnLw5cfMmt`。同意URL・氏名は保存していない。
- 利用者が実Webで同意後の名前表示を確認。
- Application Insightsでも修正版Trace `72d6da06a943af449e78fbb12e1121cd`の`identity.lookup`がversion `34`、`WAITING_USER`であることを確認。

## 最終Web検証

- 同意待ちTrace: `90ec77254efa0990595d3db65d4313e8`。Webジョブは`oauth_consent_required`、Hosted v34は`WAITING_USER`。
- 同意後Trace: `dd01e985bfb0b03fcef270fac0795ee1`（2026-09-12 08:30 UTC）。Webジョブ`completed`、Hosted v34の`identity.lookup=SUCCESS`、Functionsの`auth.obo.exchange`と`graph.me`は成功。同一Operation IDで相関を確認。
- 利用者の名前表示確認とAzure Traceの双方で、今回のWeb→Hosted→OBO→Graph経路の成功を確認。氏名やTokenは検証記録へ保存していない。
- 今回の実機確認はこの同意・名前取得経路であり、全購買シナリオや複数利用者の網羅検証ではない。

## 追加変更: 独自契約削除・診断表示・メールbaggage

- Webから`app.identity.lookup`／`app.user.id`送信を削除。APIの`lookupApplicant`／`skipIdentity`も削除し、承認拒否はAgentへそのまま中継する。
- EasyAuthのメール（email claim優先、メール形式ログイン名をfallback）をbaggageのuser.idへ設定。取得不可なら省略。Web Span・所有者ハッシュは維持。
- 下部診断欄へTrace／Response／Web・Foundry Conversation ID、case／turn／status、実際の直近Responses要求のtraceparentとuser.id baggageを表示。読み取り用メール表示とJSONコピーを追加。
- `tests/unit`とWeb stream test: **101 passed、2 subtests passed**。最後の診断値リセット修正後、Web関連 **31 passed、2 subtests passed**。既存Starlette非推奨警告2件。
- Edge／Playwrightで静的ファイルと架空APIをブラウザー内で差し替え、メール表示、コピー、390px幅、OAuth同意ボタン、MCP承認拒否のapprove:false送信、page errorなしを確認。外部公開サーバーは使用していない。
- ZIP: `/tmp/procurement-web-20260912-diagnostics.zip`、SHA-256 `85117f954dc08173ff60d9eaaf3ed37d0c5ae6f272e643c6c0f477215367ba63`。
- App Service配布ID: `cbc85fab-895e-4378-99e6-f11fcbe10255`、Kudu status 4。変更対象8ソース／静的ファイルはSCM読取りでローカルと一致。
- EasyAuth／APIM／Hostedの基盤設定は今回変更していない。App Serviceに残る`IDENTITY_LOOKUP_ENABLED`は新コードでは参照しない。
- 実利用者のメール診断表示と下流でのメールbaggage受信は未確認。現在のHostedの64桁ハッシュ制限は変更していない。
- Hostedの改善候補は[整理案](../trash/observability-integration/hosted-simplification-proposal-20260912.md)に記載。今回のHosted変更・新規OBO検証Agent作成は行っていない。
- ARM deploymentStatusで **RuntimeSuccessful**、成功1インスタンス・失敗0・errors nullを確認。実ユーザー確認とは区別する。
