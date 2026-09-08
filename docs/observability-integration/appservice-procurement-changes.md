# App Service：旧OAuth版を再利用した購買支援向け変更

更新日: 2026-09-08。稼働入口は **server.py**、UIは元のOAuth版。購買専用procurement.pyを入口としていた構成から戻した。[実設定](../deployment/appservice-settings.md)／[統合ガイド](README.md)を参照。

## 1. 旧OAuth版から何を変えたか

| 対象 | 今回使用するもの／変更内容 | 理由 |
| --- | --- | --- |
| HTML/JS/CSS | 元の `index.html` / `app.js` / `styles.css` を使用 | チャット、job/SSE、OAuth同意カードを再利用 |
| 起動 | startup.sh → `uvicorn server:app --workers 1` | 旧OAuth APIを稼働入口に戻す |
| 接続先 | PROJECT_ENDPOINT=既存APIM、AGENT_NAME=購買Hosted | Webを単一Agentのラッパーにする |
| 認証 | EasyAuthとMSALの既存方式を再利用し、委任Tokenの主体照合を追加 | Web利用者とFoundry利用者の一致を確認 |
| 購買実行 | 新規 `procurement_flow.py` | 会話作成、相関metadata、同意後の元依頼再送をまとめる |
| OTel | 新規 `telemetry.py` とserverへの接続 | 受信／送信HTTP、job、Token取得、Hosted呼び出しを観測 |
| 利用者分離 | hashをjob／会話のownerに使用、認証・Origin検査 | 他利用者のjobや状態を参照させない |
| 名前取得 | Hosted内の任意OBO Toolへ委譲 | WebでGraph結果を取得・氏名を送信する処理は不要 |
| API追加項目 | chatのlookupApplicant、continueのskipIdentity | 名前取得を省略可能にする |
| 配布 | 旧UIとserver/flow/telemetryを許可リストZIPへ収録 | 稼働に必要な入口を明確にする |

このWebは購買の商品選択や部署コード決定を独自処理しない。それらはHostedの会話・Controllerが担当する。元のOAuth版はラッパーとして利用でき、今回必要だった変更はOTel、単一接続先、利用者相関と状態分離、Hostedが返す同意待ち／再開への対応である。

## 2. ファイル単位の組み込み箇所

| ファイル・関数 | 組み込む内容 |
| --- | --- |
| [requirements.txt](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/requirements.txt) | MSAL/dotenv、OTel ASGI/HTTPX、Azure Monitor exporter。backendのrequirementsはこのファイルを参照 |
| [lifespan](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/telemetry.py:55) | Provider/exporter/Resourceのprocess初期化と終了 |
| [server.py / FastAPI生成](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py) | FastAPI生成時に観測lifespanを接続 |
| [BrowserBoundary](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/telemetry.py:90)／[Instrumentation](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/telemetry.py:75) | Browser文脈を破棄してからASGI Spanを生成 |
| [_get_request_user](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:349)／[_conversation_state_key](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:392) | 認証済み利用者hashとowner key |
| [_build_outbound_headers](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:590)／[_validate_delegated_subject](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:638) | 選択した認証方式でToken取得、同一利用者確認 |
| [_get_foundry_config](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:649) | PROJECT_ENDPOINTとAGENT_NAMEから接続先を読む |
| [run](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/procurement_flow.py:29) | Hostedを1つ呼ぶ、同一Foundry会話、OTel、metadata |
| [_stream_response](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/backend/server.py:678) | Responses SSEを既存UIのeventへ変換。consent付きincompleteをpause扱い |
| [package-procurement.py](/home/hnakajima/work/foundry-procurement-agent/src/webapp-foundry-oauth/scripts/package-procurement.py) | 配布8ファイル＋依存パッケージの許可リスト |

ソース内に残る `_build_outbound_headers()` の「procurement always explicitly selects MI」というdocstringは旧説明である。実際の呼出し元 `procurement_flow.run()` とAzure設定では `refresh_token` を明示選択しており、本書は実行コード・実設定を基準にする。

## 3. リクエストと同意の流れ

1. EasyAuth認証済みBrowserから `/api/chat` へ依頼を送る。
2. Webがownerを確認し、バックグラウンドjobとcase/turnを作る。
3. EasyAuth refresh tokenからFoundry委任Tokenを取得し、EasyAuth利用者とTokenのtid/oidを照合する。署名検証はAPIM/Foundryが担当する。
4. 初回はAPIM経由でFoundry Conversationを作成し、以降もその会話でResponsesを呼ぶ。
5. Hostedが同意を要求すると、Webは既存の同意カードを表示する。`response.incomplete` だけを一律成功扱いにはしない。
6. `/api/continue` で同じ認証方式・会話を維持し、保存した元の依頼を再送する。
7. Hostedが名前照合と購買処理を行い、Webが応答をSSEで表示する。

購買専用NDJSON APIは今回の稼働入口では使わない。Web APIのjob/SSE方式を維持する。Browserへ公開するTool eventのargumentsは `{}` に縮小する。氏名を指定するBrowser APIは設けない。

| APIの項目 | 挙動 |
| --- | --- |
| POST /api/chat のlookupApplicant省略 | IDENTITY_LOOKUP_ENABLEDの設定値を使用（現環境true） |
| lookupApplicant=false | このturnはOBO省略。Hostedの申請者名をnullへ |
| POST /api/continue のskipIdentity=true | 同意待ちを省略し、元の依頼をlookup=falseで再送 |
| job状態／eventsの取得 | 認証済みownerと照合。API pathはserver.pyのrouteが正本 |

上記はAPI機能であり、既存UIに新しい省略ボタンを追加したという意味ではない。OBOを使わない運用は環境設定でも選べる。

## 4. 認証・相関・状態の注意点

Webからのmetadataはuser hash／case／turn／Web trace ID／lookupの5項目。TokenはAuthorization headerだけに入れる。申請者名はGraphからHostedへ入り、Webからmetadataへ設定しない。

`refresh_token` はWeb→FoundryのToken取得方式である。検証対象のGraph OBOはFunctions側の `acquire_token_on_behalf_of()` で実行する別処理。名称が似ていても同じTokenや同じ交換処理ではない。

OBO有効時にMIモードを指定するとエラーにする。委任Token取得失敗でMIへ自動切替せず、会話中の認証方式変更も拒否する。MIを選ぶ場合は名前取得を無効にして新規会話を使用する。

Webのjob・再開情報は **1workerのメモリ内**。App Serviceの再起動・再配布で消えるため、新しい会話を始める。複数worker化、永続化、完全な購買UI再設計は今回の変更に含めていない。

## 5. 配布と検証

配布ZIPはstartup.sh、root requirements、server.py、procurement_flow.py、telemetry.py、旧HTML/JS/CSSの8ファイルとLinux/Python 3.13依存を含む。旧購買専用procurement.py／procurement.* UIは参考ソースとして残るが収録しない。Oryx無効設定との組み合わせは[App Service設定](../deployment/appservice-settings.md)を参照。

最終全体回帰は234 passed、1 skipped、2 subtests。同梱したWeb依存での回帰は22 passedと2 subtests。実Webから同意後に名前表示を確認し、Web→Hosted→Functions→GraphのTraceも照合済み。Web全購買シナリオは未検証であり、[検証記録](../report/validation-results-2026-09-08-obo.md)で分けて記載する。
