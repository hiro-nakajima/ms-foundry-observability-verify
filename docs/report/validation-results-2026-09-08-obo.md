# OAuth Web・Hosted内OBO Agent Tool 検証記録

対象日: 2026-09-08。指定RG `rg-ms-foundry-observability-verify` に配備。
実装の対応箇所は [統合ガイド](../observability-integration/README.md)／[OAuth連携詳細](../trash/observability-integration/oauth-wrapper-implementation.md)、実設定の再照会結果は[設定資料](../deployment/configuration.md)を参照。

## 配備済み構成

| 対象 | 配備内容 |
|---|---|
| App Service | `web-procurement-observe-nkjm`。元のOAuth画面、単一の購買Hosted接続、OTel |
| Hosted | `procurement-parent-agent` v33 ACTIVE。Controllerの前に専用OBO Agent Toolを実行 |
| Toolbox | `procurement-identity-toolbox` v1、OAuth connection `procurement-whoami` |
| Functions | `func-procurement-obo-nkjm`。MSAL OBO、Graph /me、本人照合、OTel |
| APIM | 既存 `/foundry/proj-default`。Web委任Tokenを受け付けるpolicyへ更新 |

既存の遠隔OBO Agentインスタンスを呼ぶのではなく、そのToolbox方式をHosted内の専用Agentとして再利用する。OBO専用のAPIM APIは追加しない。

Web配布IDは `eb3dc567-dec1-4e45-a175-3284d7f88e09`。初回のOryx buildが中断したため、Linux/Python 3.13依存を同梱するZIPへ切り替え、配布成功・ソースのhash一致・利用者による画面表示を確認した。Web ZIPのSHA-256は `67b37f892c4f92d9b32496f8bad98307892db7e399483a823b73cf6b1740ab20`。

Functions配布IDは `a5a45d82-30b8-4bfb-bdd2-23843f846d36`。SHA-256は `650f8d0d2906e34d61a9e7d7ab18ec28326b1db91d8a68076a144e57f6677d33`。Hostedの最終バージョンとhashは [配備メタデータ](../../.foundry/agent-metadata.yaml) に記録する。

## 確認済み

| 検証 | 結果・証拠 |
|---|---|
| ローカル全体回帰 | 最終修正版で234 passed、1 skipped（明示的なAzure gate）、2 subtests passed |
| Web同梱依存での回帰 | 22 passed、2 subtests passed |
| SDK公開名・metadata契約 | 実SDKのtools/list→FunctionTool.invokeで、3個のアンダースコア形式とドット形式を検証 |
| Python/Bicep/差分 | compile、Bicep build、`git diff --check` 成功 |
| Functions MCP | initialize/tools-list成功、匿名whoamiはプロフィールを返さず拒否 |
| APIM認証 | 匿名401。実WebのFoundry委任Token取得と購買Hosted呼び出し成功 |
| 利用者操作 | Web表示・同意・「私は誰ですか」への名前表示を利用者が確認 |
| Web→Hosted→Functions→Graph相関 | Trace `ac05d5d0796bca9975933c1647ace37f`。Web job、Hosted identity.lookup、Functions whoami、OBO交換、Graph /meが同じOperationIdで成功 |
| 氏名の取得・引き継ぎ | v33、`OBO-CHAIN-20260908042318` turn 1。HostedがGraph OBOを取得元として本人の名前を応答 |
| 同じ会話で取得を省略 | 同case turn 2。lookup=falseで以前の名前を消去、未取得の応答を確認 |
| 氏名未取得の購買処理 | v29、`S1-DIRECT-20260908033625`。技術SUCCESS、Search成功、必要項目待ち |
| native OAuth同意要求 | v29、`OBO-HOSTED-20260908033842`。`oauth_consent_request` と `response.incomplete` |
| 同意URLのTrace流出 | 上記同意TraceのAppExceptions/AppTraces/AppRequests/AppDependenciesを集計し、OAuth URL/stateを含む行は0件 |
| 名前取得成功時のログ | 直接Foundryの成功Trace 2件の観測行167件を照合し、取得した氏名・OAuth URLを含む行は0件。検証レポートには件数のみ保存 |

ローカル回帰と直接Foundry呼び出しは、実Webでの全操作を検証したものではない。購買処理の技術SUCCESSだけで、任意の名前取得が成功したとは判定しない。

## 同意後の問題と診断

実Webから同意後に実行した名前取得で、Toolbox `tools/call` がJSON-RPC `-32602` を返した。Functionsのwhoami処理に到達せず、購買処理は仕様どおり氏名nullで継続した。

診断Trace `aaf6be6f358e48488d819808c64fc23d` で、実際の公開名が `whoami_func___whoami` であることを確認した。固定名のcall_toolを、SDKが公開一覧から生成したFunctionToolのinvokeへ変更した。remote名とtools/listのmetadataを維持し、最終v33で実Webの名前表示とOBO/Graph成功を確認した。

診断中、一部の直接Foundry要求ではアプリSpanが記録されなかった。診断用のtraceparentをsampled=01として再実行したところ、必要なSpanを確認できた。通常要求の一件でSpanが見つからないことだけでは未実行と断定しない。

## 検証範囲

Graphで取得した本人の氏名がHosted内へ渡り、実Webに表示される経路を確認済み。同会話の省略→氏名消去は直接Foundry APIとローカル契約テストで検証した。新構成での全購買シナリオ・複数利用者・同意取消後の再同意を実Webから網羅した検証ではない。氏名・Token・生のclaims・OAuth URLを検証レポートに保存しない。

Webのjob/stateは1workerのメモリ内。再起動時のjob継続や複数workerへの拡張は対象外。commit、push、PR作成は実施していない。
