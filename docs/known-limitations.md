# Known limitations

- Azure applyは未承認・未実施であり、Search index、document、RBAC、Toolbox、Prompt Agent、Hosted親はAzure上に作成していない。
- `FoundryAgent.as_tool()`のclient/proxy SpanからManaged Prompt Agent server-side Spanへ`traceparent`が維持されるかは実AzureのV7で判定する。LocalではStructured correlation fallbackだけを検証した。
- Toolbox resultにrank、score、chunk本文が全て現れる保証はない。V6は実測で取得できたfieldだけを記録し、非公開fieldをLLMで補完しない。
- S5は送信前exporter相当の8,192／32,768／65,536境界をLocal測定した。Application Insights ingestionとFoundry Portalの先行切詰めは未測定である。
- V12、V14、V18、V19はT2未有効のため未完了。継続評価、sampling反復、usage/cost集計資産は作成・実行していない。
- V10、V20、V21はT4未有効、V16/V17はT3未有効であり、Private network、DCR、table RBACを変更していない。
- Prompt-based Agentのinstructions実値、未選択Tool定義、content-off evaluator可否はManaged traceで未検証である。
- 外部E2E testはAzure applyとCredentialがないため理由付きSKIPする。Local recorded MCP fixtureはAzure runtimeそのものの代替証明ではない。
