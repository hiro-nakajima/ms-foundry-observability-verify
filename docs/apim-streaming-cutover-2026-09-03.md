# APIM SSE切替記録（2026-09-03）

## 承認と対象

ユーザーがDeveloper APIMへの切替と、最終的な旧Consumption APIM削除を明示承認した。
対象subscriptionは`d96eb8c2-2deb-4ed5-8cf2-f9fb178cb3ee`、RGは`rg-ms-foundry-observability-verify`。
参照RG `rg-ms-foundry-mcp` とFree Search `rag-ais-02` は変更しない。

| 項目 | 内容 |
|---|---|
| 新APIM | `apim-procurement-stream-nkjm`、East US、Developer 1台 |
| 旧APIM | `apim-procurement-observe-nkjm`、East US、Consumption |
| 費用要因 | Developer Unit $0.0658/時、730時間で$48.03/月。税・契約価格を除く概算、非production・SLAなし |
| 認証 | EasyAuth→Web App system MI→APIMのtenant/audience/oid検証→Bearer転送 |
| RBAC差分 | 追加なし。APIM用MIなし。既存Web MIのFoundry権限を利用 |
| 公開API | 固定親AgentへのConversations create/get/updateとResponses、計4操作 |
| Trace/SSE | W3C、buffer-response=false、body logging 0 bytes、header loggingなし、cachingなし |
| ネットワーク | Public、新VNet/Private Endpoint/DNS設定変更なし |

Consumptionは[公式SSE資料](https://learn.microsoft.com/en-us/azure/api-management/how-to-server-sent-events)で長時間接続のサポート対象外。既存policyもbuffer-response=falseであり、単なる設定漏れではない。

## 配備前とrollback

- account/RG/resource一覧、旧tier、Web MI、接続先、provider登録、名前availabilityを確認。
- `infra/apim.bicep`を単独Incremental配備。what-ifはCreate 9 / Ignore 10、既存Modify/Delete 0。
- `scripts/deploy_stream_apim.py`は新APIM配下のCreate以外を拒否し、接続先変更や削除は行わない。
- deployment `procurement-stream-apim-20260903122915`はSucceeded。実resourceの4操作、Web MI限定policy、W3C、`buffer-response=false`、body/header loggingなしをread-backして検証した。
- 設定・secure parameters・what-ifはignored `.local_state/deployment/stream-apim-*` にmode 600で保存。秘密値は文書・ログへ出さない。
- 切替前後に認証policy、4操作、SSE受信時刻を実測。失敗時は旧`PROJECT_ENDPOINT`と旧Web ZIPへ切戻し可能。
- 旧APIM削除前に参照残存と新経路成功を確認した。削除後は[48時間soft-delete](https://learn.microsoft.com/en-us/azure/api-management/soft-delete)を実際に照合し、purgeは行っていない。

## 検証の境界

Localは153 passed / 1 skipped（Azure Core未実行のplaceholder）。Hosted v7はACTIVE、ZIP SHA256は`d41d5dfcffb904e092f13bf01d501785009b89ea0106e72b253ad2248c1d3a2f`。

直接Foundry case `CHAT-DIRECT-20260903123137`は候補提示→選択と不足情報追加入力の2turnに成功。
1turn目はWAITING_USER（候補2件）、45.626秒、最初の進捗10.134秒。
2turn目は全status SUCCESS・draftあり、65.128秒、最初の進捗1.157秒。
Foundry Conversation/Framework Session hashの継続も確認した。これはWeb/APIM経路の証拠ではない。

Web ZIP v8は候補ボタン・下部composer・自然言語応答・NDJSON進捗を含む。後述の部署確認表示をWAITING_USER/NOT_FOUNDの両方に対応させたv10（SHA256 `313b12f2998aee79d6de175d84bc882037b76bccec1b33ea03062c502c570359`）をdeployment `bec7a99f-f95c-4d25-a7f9-4479cf5b915a`で配備した。実行コンテナのbackend/JavaScript hashはZIP内と一致し、uvicorn起動も確認した。v8/v9は履歴として保持。

Kudu SCM環境にはMI環境変数がないことを実測。管理者SSHで接続したapp containerには両変数が存在する。`scripts/invoke_web_runtime.py`はこの実MIから新APIMを呼び、候補→選択だけ→不足情報補完の3turnを計測する。CLI credential代用やEasyAuth header偽装はしない。この診断の成功もBrowser/EasyAuth/cookie/CSRF/描画の成功とは区別する。

新APIM経路と旧APIM削除は完了した。再配備後の実ユーザーBrowser/EasyAuth操作は未実施のため、Browser E2Eは完了扱いにしない。S1〜S5/V1〜V21/Stage A/Bの未実測をPASSへ変更しない。

## 切替・削除の実測（2026-09-04）

- app containerの実Managed Identityから新APIMへ`CHAT-WEBMI-20260904004800`を実行。同一Conversation/Framework Sessionで3 turnを継続し、候補提示（56.834秒）→選択だけで追加確認（33.578秒）→不足情報補完で全status SUCCESS・draft生成（104.414秒）を確認した。各turnで最終結果より前に進捗を受信した。これはBrowser/EasyAuthの証拠ではない。
- Web Appの`PROJECT_ENDPOINT`を新APIMへ変更し、v10をZIP配備。配置済みbackendのlocalhost経路でcase `WEB-412fcb3a9ae73c14`を実行し、最初の進捗6.459秒、最終60.552秒、進捗5件、候補2件、technical/MCP/Search/parse SUCCESS・business WAITING_USERを確認した。署名cookie、CSRF、Conversation作成、SSE、Web MI、新APIM、Hosted/Catalog/Searchを通るが、EasyAuth front-end自体はlocalhost検証の外である。
- Trace `0ea6b91c63359331457aa88fe6171281`ではWeb root→Conversations create/update→Responses client→Hosted親→Catalog proxyが同一Trace。Web client 3本の自動traceparentと`user.id` baggage送信booleanはTrue。Hosted下流の`user.id`は未記録で、`NOT_PROPAGATED`（欠落hop未特定）。Catalog managed側はTrace `d44ae8fabc6c9edc4b34ec8f1c69052a`へ分岐し、Response ID `resp_07912587212c9163006a9a1aac106c8195aa82268a9d4f9c1e`で相関した。APIM内部spanは未取得であり、別Traceを結合しない。
- 削除直前の直近1時間metricsは旧APIM Requests 0、新APIMは非0。旧APIM内はこのPoC API 1件だけ、Web設定は新endpointであることを再確認した。
- 旧Consumption `apim-procurement-observe-nkjm`を2026-09-04 01:13:50 UTCにsoft-delete。アクティブresourceからの消失と、2026-09-06 01:13:20 UTCまでの復元可能期間を確認した。purgeはしていない。新Developer `apim-procurement-stream-nkjm`は削除後もSucceeded。

## 構築待ちの追加検証

- S3自然な負例`S3-CONTROL-20260903123933`：存在しない型番でSearch NOT_FOUND、Catalog attempt 1→retry→attempt 2→replan/WAITING_USER、draftなし。64.218秒。Stage B SD-03/SD-05の注入とは区別する。
- S2自然な負例`S2-CONTROL-20260903124042`：Catalog成功後、Codeの`DEPARTMENT_NOT_FOUND`でWAITING_USER、draftなし。99.788秒。MCP/Search/parseはSUCCESS、business validation側の確認待ちであり、Search通信障害や注入成功とは扱わない。
- このS2で、完全入力の依頼にも`missing_fields=selected_product_code`を付ける分岐を確認。部分intake時だけ追加するよう修正し、UIは既知の部署不明reasonに対して架空の部署名を再確認する。親v7 ZIP SHA256 `d41d5dfcffb904e092f13bf01d501785009b89ea0106e72b253ad2248c1d3a2f`として追加配備。新しいenv/認証/RBACはなし。
- v7の最初の再測定`S2-V7-20260903124831`は`catalog_specification_mismatch`でCode未到達（56.439秒）。部署確認の成功には数えず、仕様照合に関する未解明の実測結果として保持。
- 仕様追加条件を外した独立control `S2-V7-ISOLATED-20260903125123`はCode到達後`DEPARTMENT_NOT_FOUND`/NOT_FOUND、draftなし、missing_fieldsなし、公開商品候補0件（71.478秒）。本来の目的以外の停止を成功扱いしない。
- Local全件153 passed / 1 skipped。Starlette 1.6で停止する旧TestClient互換層を追加依存なしの`httpx.AsyncClient`/ASGITransportへ置換し、request metadata/baggageの3件を含めて成功（既存FastAPI import由来の非推奨warningのみ）。Bicep compile / git diff --check成功。
- v6の同一会話に対応する2 Trace、56 spansを取得。Catalog子のwrapper約23.8/32.6秒に対し、Toolbox call約0.59/0.53秒。重なった親子spanを合算して遅延を水増ししない。LLMを含む子Agent時間が大きく、APIM切替で全応答時間が短縮したとは主張しない。

再照合でCode子のmanaged traceを別Traceとして取得した。親のCode proxy配下chat span `89100ba078366aa3`はTrace `2855457ed0dfe9abb1e2f20c7eb65325`。managed Code v2 span `2f297749db6ca63a`はTrace `ca975f8f833711892ec3237167fb26d2`（parent `8193b4d62df86312`）。両者の`gen_ai.response.id`が`resp_0c2ea73a061a97bc006a996909e46c8197869cf50d76ad0c3e`で一致するため、同じ呼出しとの対応は確認できる。同一Trace継続は`NOT_PROPAGATED`、Response IDによる代替相関は実測済み。異なるTraceをつないだ架空のparent chainは作らない。APIMなしの直接実行でも起きており、欠落の具体的なhopは未特定。証跡`trace-direct-v6-reconciled.json`。

### Local UI QA

Browser plugin not availableのため、既存Edge/Playwrightを使用。対象`http://127.0.0.1:8765/static/procurement.html`、API応答はSynthetic NDJSON fixture。Azure/EasyAuth経路ではない。

| 確認 | 結果 |
|---|---|
| URL/title、非blank、error overlayなし | PASS |
| 候補ボタン→選択turn、NDJSON処理 | PASS |
| 再読込時の会話継続、新規会話 | PASS |
| 1280×1000 / 390×844、会話の下にcomposer | PASS |
| 横はみ出し、console/page error | なし |

既存`webui-progress-qa.cjs`を再実行。証跡はCodex visualizations内の`webui-v8-desktop.png`/`webui-v8-mobile.png`。モバイルはresize後に新たに操作して候補表示を撮影した。Hallmark skillは利用不可のため既存最小UIを維持し、デザインの作り直しは行わない。
