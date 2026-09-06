# 購買申請Agent 遅延分析

記録日: 2026-09-06
対象: App Service → Developer APIM → Foundry Hosted親 → Prompt子 → Toolbox → Azure AI Search

## 結論

現時点の主要因はServerless DeveloperのSearch queryではなく、Hosted親のplanningとPrompt子AgentのLLM推論・managed orchestrationである。Developer APIMのSSEは最初の進捗を早く見せ、長時間応答のbufferingやtimeoutを避けるために有効だが、Agent処理そのものの総時間は短縮しない。

Serverless Developerはidle時にscale-to-zeroするpreviewであるため、コールド時の寄与がゼロとは断定しない。ただし現在の11件/10件の小規模indexでは、Toolbox/Search envelopeが約1.5～1.7秒なのに対し、Prompt子の`invoke_agent`は約22秒、turn全体は十数～50秒超である。SKU変更を第一手にする根拠はない。

## 実測内訳

| 対象 | 実測 | 判断 |
| --- | ---: | --- |
| v20 turn 1 商品検索 | 49.282秒 | 親intake/planningとCatalog Prompt子を含む |
| v20 turn 2 商品選択 | 14.208秒 | 保存候補を使用。入力解釈の親LLM区間が残る |
| v20 turn 3 数量等入力 | 13.249秒 | 親LLMによるintake更新が中心 |
| v20 turn 4 確認票生成 | 53.530秒 | Code Prompt子`invoke_agent`約22.111秒を含む |
| v20 turn 5 「確定」 | 1.478秒 | Catalog/Codeを再実行せず、保存済みEvidenceとmergeだけを実行 |
| v18 Toolbox/Search envelope | 約1.5～1.7秒 | Searchは存在するが全体の支配要因ではない |

上記はApplication Insightsのallowlist evidenceとAzure会話の受信時間から得た値である。APIM内部とSearch service内部のspanはPlatformから取得できないため、1.5～1.7秒をSearch engineだけの純粋な処理時間とはみなさない。

## 早くする優先順位

1. Hosted側に既知stepの決定論的short pathを追加する。商品候補をAgentSessionへ保存済みなら、候補ボタンの定型文、数量だけ、部署だけ、メモだけを親LLMへ再投入せず更新する。業務ロジックはWebAppへ置かない。現行でも候補ボタンと「確定」は一部short pathになっており、最終確定1.478秒が効果を示している。
2. Prompt子の呼出し回数を維持しつつ、必要時だけ呼ぶ。Catalogは商品query変更時、Codeは商品・数量・部署・メモが揃った時に限定し、AgentSessionのgrounded evidenceを再利用する。
3. 親/子Promptの入力を短くする。履歴全文ではなく、現在の構造化intake、選択候補、相関属性だけを渡す。InstructionsとJSON schemaはcontractを壊さない範囲で縮小する。
4. 現行`gpt-5-mini`と別の低遅延model/reasoning設定を、S1～S5とStage A/Bを固定してA/B測定する。精度低下やschema不正があれば採用しない。
5. Search SKU変更は最後にA/B測定する。同一queryをServerless warm/cold、必要ならDedicatedで比較し、`SearchLatency`とthrottlingを取得してから判断する。

最も効果が見込める次の実装は1である。特に商品選択後の数量・部署・メモを既知stepとして解釈すれば、各turnの十数秒を1～数秒台へ近づけられる可能性がある。ただし自由文を過剰に正規表現化せず、解釈できない入力だけ親LLMへfallbackするのが安全である。

## SSE/APIMで変わるもの

現在のDeveloper APIMはSSE対応tierで、`forward-request buffer-response="false"`を使う。これにより進捗eventをBrowserへ順次relayできる。response body logging、response cache、本文をbufferするpolicyはSSE APIで無効にする。これらはtime-to-first-progressを改善するが、LLM/Toolbox/Searchの完了時刻を早めるものではない。

公式資料:

- [API ManagementでSSEを構成する](https://learn.microsoft.com/en-us/azure/api-management/how-to-server-sent-events)
- [Azure AI Searchのpricing modelとtier](https://learn.microsoft.com/en-us/azure/search/search-sku-tier)
- [Azure AI Search performance tips](https://learn.microsoft.com/en-us/azure/search/search-performance-tips)
- [Search query latencyの監視](https://learn.microsoft.com/en-us/azure/search/search-monitor-queries)

## 測定を追加する場合

最適化前後で次を同じtest.case.idへ記録する。

- Browser送信から最初の`progress`まで
- Hosted request全体
- parent intake/planner
- Catalog/Code各`invoke_agent`
- Toolbox tools/call envelope
- merge/response
- warm/cold区分、Agent/Toolbox/index version

APIM SSEの有無とSearch SKUを同時に変えない。1要因ずつ比較し、Managed境界の未取得spanは`NOT_RECORDED_BY_PLATFORM`のまま扱う。
