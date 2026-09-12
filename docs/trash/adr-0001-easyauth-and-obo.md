# ADR-0001: 購買Hosted内の任意Graph OBO Agent Tool

更新日: 2026-09-08。

Webは旧OAuth画面・ジョブ・SSE・同意後の再開機能を維持し、ユーザー委任Tokenで既存APIMの購買経路を呼ぶ。追加のidentity用APIM経路は作らない。App Service MIの権限だけでは利用者OBOは成立しない。

OBO処理は既存Hosted OBO sampleと同じFoundryToolbox方式を、購買Hosted内の `obo_identity_agent.as_tool(propagate_session=False)` に組み込む。Graph /meを呼ぶだけなので、この専用Agentの実行は決定的な処理としLLMを使用しない。既存の遠隔OBO Agentインスタンスをそのまま呼ぶ方式ではない。

FunctionsはOAuth connectionからMCP API用の委任Tokenを受け、MSAL OBOでGraph Tokenを取得する。Graph idと受信oidの一致を検証し、氏名とSHA-256(tid:oid)のみ返す。HostedはWeb由来の観測IDと照合し、成功した氏名のみControllerへ渡す。氏名を認可に使用しない。

OAuth同意要求は購買処理開始前にnative Responses itemとしてWebへ返す。Webは同じFoundry会話へ元の依頼を再送する。省略・失敗したturnでは氏名をnullにし、以前の氏名を持ち越さない。省略時もWebの認証主体は変更しない。

配備先は `rg-ms-foundry-observability-verify`。Entraアプリはtenantリソースのため既存App B/Cを再利用し、既存redirect URIを残したまま新connectionのURIを追加する。Functionsは既存client secret方式を維持し、FICは追加しない。

ソース対応・設定・配備結果は [実装ガイド](observability-integration/oauth-wrapper-implementation.md) を正本とする。
