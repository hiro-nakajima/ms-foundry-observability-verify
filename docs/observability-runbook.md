# Core Observability runbook

## Runtime別設定

| Runtime | 計装箇所 | Core確認 |
|---|---|---|
| Hosted親 | Agent Framework OTel、Responses host、Application Insights connection | Framework Agent/Chat/Function Span、4業務Span、Session/Turn/Plan属性 |
| Prompt子 | Foundry projectのApplication Insights connection、Agent versionのserver-side tracing | Prompt Agent root、Toolbox MCP、Search query Span、Structured correlation |

`synthetic-content-on`はSynthetic Core runだけで使用する。`production-like-content-off`ではRaw message/tool contentを記録せず、hash、length、status、IDを残す。Chain-of-Thoughtはどちらでも記録しない。

## Core run順序

1. S1を同じFramework Sessionのserialize/restoreを挟んで2回実行する。
2. S2の`not_found/index_missing/permission/business_invalid`をToolbox/Searchで、`timeout/protocol_invalid`をLocal MCP fixtureで実行する。
3. S2 TV-02/TV-03、S3 SD-03/SD-05、S4 MA-04/MA-05を1回ずつ注入する。外側technical statusは`SUCCESS`のままにする。
4. S3のnot-found controlでretry、replan、`WAITING_USER`、終了後actionなしを確認する。
5. S4のcomplete、商品分類欠落、correlation欠落fixtureを確認する。
6. S5の128、8,192近傍、32,768近傍、64KB近傍と超過payloadを実行する。
7. exact operation IDを`infra/observability/kql/export-exact-operation.kql`へ一時指定し、JSONLへexportして再読込する。IDをcommitしない。

## 判定

- HTTP、technical、MCP、Search、parse、business statusを別columnで照合する。
- 注入が発火しなければ`INJECTION_MISSED`、Detector必須fieldがTraceから欠ければ`UNEVALUABLE_TRACE_INCOMPLETE`とする。
- Platformが値を記録しない場合は`NOT_RECORDED_BY_PLATFORM`、相関を伝播しない場合は`NOT_PROPAGATED`とし、PASSへ置き換えない。
- T1〜T4のtriggerがないため、継続評価rule、sampling反復、billing KQL、DCR、table RBAC、Private Linkは作成・実行しない。
