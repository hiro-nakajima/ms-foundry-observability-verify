# HostedAgentの整理案とWeb診断表示

2026-09-12。下表は当初の改善案。ユーザー承認後、項目1〜4を実装した。項目5・6は不要な構造変更をせず、既存ContextProvider／Bundleを維持して移植範囲を資料と日本語コメントで明示した。

実装結果: 通常購買と同じHosted endpointに明示的OBO検証の入口を置き、「私は誰ですか」等を振り分ける。別のAzure AgentリソースやWeb切替UIは不要。OBO Toolを購買親Agentのtoolsから外し、名前は検証応答のみへ返す。独自identity metadata、Webハッシュ再照合、購買のOBO前処理、本人情報用ContextVarを削除した。メールbaggageは観測属性のみへ採用し、手動Spanの自動例外本文記録を抑制した。

現行の接続・移植手順は[OBO検証移植ガイド](../../observability-integration/hosted-obo-userid-porting.md)を参照。

## 今回のWeb変更

- `backend/procurement_flow.py:run`から`app.identity.lookup`／`app.user.id`送信を削除。名前取得の有効化、スキップ、拒否時の購買への読み替えを削除。
- `backend/server.py`の`lookupApplicant`／`skipIdentity`を削除。未対応引数は422。OAuth同意とMCP承認／拒否は一般的な再開入力として中継する。
- `backend/auth.py:_get_request_user`でEasyAuthのemail claim、なければメール形式のログイン名を取得。後者はUPNの場合があり、実メールボックスと同一とは限らない。取得できなければNone。
- `backend/telemetry.py:job_context`がメールをW3C baggageの`user.id`へ設定する。OBO実行は不要。WebのSpan属性・所有者キーのハッシュは維持する。
- `backend/foundry_client.py:_stream_response`のHTTPX response hookから`capture_sent_headers`を呼ぶ。HTTP計装後の実要求ヘッダーを取得し、traceparentとuser.id baggageだけを診断用に採用する。
- `_public_job`がIDと診断値を返す。SSEの終了イベント直前にも診断値を送り、ポーリング時と同じ情報を表示する。診断イベントは業務イベントのcursorを進めない。
- 診断欄はチャット下部の折りたたみ表示。Response ID、Web／Foundry Conversation ID、Trace ID、case、turn、status、送信traceparent／baggageと読み取り用メールを表示・コピーできる。認証判断やAgentへの入力には使わない。

メールは下流サービスが参照可能になる。また診断値は既存の利用者別localStorageにも保存される。Authorization、Cookie、生claimsや任意のbaggageを表示するものではない。HTTP応答前に接続が失敗した場合など、実ヘッダーを取得できなければ未取得とする。表示はWeb送信の証拠であり、下流での記録の証拠ではない。

## 優先順位付きのHosted改善案

| 順番 | 現在の箇所 | 変更案・理由 | 確認すべきこと |
|---|---|---|---|
| 1 | `observability.py:current_request_attributes` | 現在はbaggageのuser.idを64桁ハッシュに制限している。メールを観測属性にも採用する方針に変更するなら、この制限と属性の意味を統一する。メール／ハッシュの混在を暗黙にしない | 実環境でbaggage到達を確認。未到達ならConversation／Response／Web Trace IDで相関する。baggageを認証・認可に利用しない |
| 2 | `hosted_app.py:_RequestCorrelationMiddleware` | 通常購買から`app.identity.lookup`、`app.user.id`、旧表示名・source・lookup statusの解釈を外す。観測の相関と業務上の本人確認を分離する | metadataなしの購買、新しい会話、同一会話での複数turn、他利用者との分離 |
| 3 | `hosted.py:build_hosted_bundle`、`hosted_app.py`のOBO実行分岐、`identity.py:build_identity_tool` | 通常購買のidentity tool登録・名前取得前処理を外し、OBO検証用Agentへ保存・移設する。商品／部署検索のAgent as Toolは維持 | 購買ではGraph呼出しがない。検証Agentでは初回同意、再開、Graph /me、拒否・失効を確認 |
| 4 | `observability.py:TelemetryRecorder.span` | 自動例外記録の範囲を明確化する。現在の属性sanitizeはOTelが自動生成するexception event本文には作用しない。本文を含む例外がここまで伝播すると、その本文が記録対象になり得る | 必要ならWeb同様に自動例外本文記録を無効化し、error.typeとERROR状態を明示。架空の機密文字列を含む例外でExporter出力を確認 |
| 5 | `hosted.py:ControllerContextProvider`と`HostedAgentBundle` | Bundleは組立用コンテナで、OTelの要件ではない。移植先がexecutorのContextProviderから制御しているなら、その構成を維持して呼出し・Spanだけ組み込む | Providerが二重実行されないこと、各実行で別のrequest contextを持つこと |
| 6 | `observability.py`、評価・障害注入関連コード | 最小OTel部分とPoC評価用拡張を資料で区別する。単にファイルを細分化するより、移植必須部分を限定する | 評価fixture・検出器を必要とする既存検証を壊さない |

現在の`verified_name`はFunctionsの認証済みOBO結果と名前の構造を検査する。本人照合はFunctionsのtoken oid／Graph id比較が担い、Web metadataやメールbaggageは認証に使わない。通常購買へ名前を保存しない。内部の業務APIで申請者名を渡す引数は残すが、Webから受け取る契約ではない。

## OTelサンプルとして残す部分

1. Hostの`configure_observability`をプロセス起動時に初期化し、`TelemetryRecorder.for_hosted_runtime()`で既存global providerを使う。各要求でProvider／Exporterを作らない。
2. SDKが作るAgent／Chat／Function／MCP Spanを活用する。手動で`tool.invoke`等の重複Spanを追加しない。
3. SDKが知らない業務境界だけを`plan.create`、`plan.step.execute`、`merge.validate`、`response.generate`として囲む。`semantic.evaluate`はその評価機能を使う場合だけ必要。
4. 要求単位のContextを終了時にresetし、concurrentな会話の属性を混ぜない。
5. Agent／MCP本文やOAuth同意URLを抑制する既存処理は維持する。`McpPrivacyProcessor`はSDK内部hookを使用するため、SDK更新時にexport前除去のテストを行う。コード量だけを理由に削除しない。

最小の移植順序は「Host初期化 → 既存executor／ContextProviderから観測ヘルパー利用 → planと各stepの実処理を囲む → SDKのTool Spanと同一Traceになることを確認」。`HostedAgentBundle`そのものの移植は不要。実処理を囲まずにヘルパーを追加するだけでは、Plan／Executeの独自Spanは発生しない。

## 検証境界

今回のWeb変更はHTTPX fixtureによる単体テストと、外部サーバーを公開しないEdge/Playwrightで確認する。実利用者のメール表示やAzureの下流baggage到達は別の実環境確認が必要。Hostedもローカル回帰テストを実施した。配備・実Azureの検証結果は検証記録に分けて記載する。

配備済みv35と実Azureの確認結果は[Hosted検証記録](../../observability-integration/hosted-refactor-validation-20260912.md)を参照。
