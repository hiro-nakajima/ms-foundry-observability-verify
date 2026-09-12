# Hosted整理・OBO検証経路の検証記録

2026-09-12。Webは前回配布版を継続使用し、今回Hostedのみ変更。

## 変更した内容

| ファイル | 変更 |
|---|---|
| `src/hosted-agent/procurement_agent/hosted_app.py` | identity metadata・氏名metadataを廃止。標準Responsesの最新user inputで明示的OBO質問を独立経路へ振り分ける。通常購買は親へ委譲する |
| `src/hosted-agent/procurement_agent/identity.py` | 起動用ContextVarとWebハッシュ再照合を廃止。Functionsの認証済みOBO結果を採用し、氏名は応答内のみ。Tool未設定・失敗を明示。呼出しごとのContextをreset |
| `src/hosted-agent/procurement_agent/hosted.py` | 購買親Agentのidentity Tool登録、本人情報ContextVar、OBO状態に基づく名前転記、旧「今回は名前を取得していません」応答を削除。通常購買へ旧氏名を持ち越さない |
| `src/hosted-agent/procurement_agent/observability.py` | メール形式user.id baggageの採用、自動例外本文記録の抑制、error.type／ERROR記録 |
| `src/hosted-agent/procurement_agent/controller.py` | Plan生成・step実行の観測ポイントへ日本語コメント追加 |

旧`app.identity.lookup`／`app.user.id`／`app.authenticated.display_name`等を送っても採用しない。`test.case.id`やWeb Trace IDの相関metadata、既存検証ハーネスのJSON出力・障害注入契約は観測検証用に維持している。通常Webの動作要件ではない。

OBOは通常の「私は誰ですか」「OBOフローを実行して」等で実行する。現在のWeb同様、会話継続には標準`conversation`を使う。OBOから通常購買へ`previous_response_id`だけで継続する方式は対象外。

## ローカル検証

- 全体: `tests`とWeb stream testで **245 passed、1 skipped、2 subtests passed**。スキップは実Azure資格情報を要求するE2E。
- キャンセル対応追加後: identity／protocol／factoryの関連テスト **37 passed**。Graph相当処理の待機中に停止シグナルで中断できることを含む。
- OBO同意（tools/list・tools/call）と再開、通常購買にOBOが呼ばれないこと、並行要求の結果分離、偽identity metadataの無視、メールbaggage、例外本文の非exportを確認。
- 移植用の単独Pythonはimport実行が成功。`validate_deployment_assets.py`、`git diff --check`も成功。
- 認証・制御フローの限定レビューで現在Web経路のP0/P1指摘なし。

## 配備

- RG: `rg-ms-foundry-observability-verify`
- Project: `observability-verify / proj-default`
- Hosted: `procurement-parent-agent` v35、source ZIP、Python 3.13 remote_build。
- ZIP SHA-256: `e2ad58342f53b2e6d8a05d7295fa61a5f9d2e319844c61b90a05afc76d78fd9f`。
- 既存Toolbox・Functions・App Service・APIMの基盤設定は変更しない。旧Hostedバージョンも維持。
- 現在状態と実Azure検証結果は以下へ追記する。実ユーザーのWeb OBO応答・メールbaggage到達は、ローカル検証だけでは確認済みとしない。

- 読み戻しでv35 **ACTIVE**、ソースハッシュ一致、v34との環境変数全値一致を確認。

## 実Azureの確認結果

- テスト `OBO-ROUTE-65466af2bea7`。独自identity metadataなしで、同じFoundry Conversationへ本人確認→通常購買の順に送信。
- 本人確認: `oauth_consent_request`／`incomplete`。旧スキップ文は出ず、OBO同意経路へ到達。
- 通常購買: `completed`／message。OBO同意は要求せず応答を返した。
- Application Insights: Trace `90235856a25d4550bacfb68e2b36b5d5`のturn 2で`plan.create`、`plan.step.execute`、`response.generate`のsuccess=Trueを確認。
- その3つのSpanの`user.id`は未記録。テスト用メールbaggageを直接Foundryへ送ったが、実サービス境界での伝播はこの試行で確認できなかった。入力baggageの採用自体はSDK middlewareを通したローカルテストで確認済み。metadataで補完する独自契約は復活させていない。
- 生の氏名・メール値・同意URLは検証記録へ保存していない。実Webで新しい会話から本人名が表示されたことをユーザーが確認済み。実ユーザーの当該Trace IDは未特定。
- 機械可読の応答ID等は `.foundry/results/OBO-ROUTE-65466af2bea7.json` に保存。

- 実ユーザー確認: 「名前が表示された」と回答あり。新Web→Hosted v35の独自metadataなしOBO名前取得を確認。通常購買では名前を使用しない。
