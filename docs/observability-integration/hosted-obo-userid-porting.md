# HostedAgentのOBO検証・user.id移植

2026-09-12更新。旧`app.identity.lookup`／`app.user.id`／表示名metadata契約を廃止した。[移植用Python](examples/hosted_obo_userid.py)も最新ソースから抽出し直している。

## 接続方法

```python
import os
from azure.identity import DefaultAzureCredential
from hosted_obo_userid import (
    IdentityResponsesHostServer, build_identity_tool, configure_host_observability,
)

# 既存のparent_agentはそのまま使用。HostedAgentBundleの移植は不要。
# parent_agent = ...
os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = "false"
os.environ.setdefault("OTEL_PROPAGATORS", "tracecontext,baggage")
credential = DefaultAzureCredential()
identity_tool = build_identity_tool(credential)
server = IdentityResponsesHostServer(
    parent_agent, identity_tool=identity_tool,
    configure_observability=configure_host_observability,
)
server.run(host="0.0.0.0", port=8088)
```

会話継続には現在のWeb同様に標準`conversation`を使用する。OBO応答は購買Framework sessionを作らないため、conversationなしの`previous_response_id`だけでOBOから通常購買へ継続する方式は対象外。

`PROCUREMENT_IDENTITY_TOOLBOX_ENDPOINT`には移植先ToolboxのMCP endpointを設定する。OBO未設定環境では`identity_tool=None`を渡せば、通常購買は利用でき、本人確認には未設定の案内を返す。既存SDK固定版と同じResponsesHostServerの履歴設定も維持する。

## 呼出しと責務

- Webは通常のResponses `input`だけを送る。本人確認用metadataは不要。
- `hosted_app.py:_latest_input_text`と`identity.py:is_identity_request`が今回の最後のuser入力を確認する。「私は誰ですか」「Who am I?」「私の名前を教えて」「OBOフローを実行して」等の明示的な質問だけをOBOへ振り分ける。任意の自然言語をLLMで分類する機能は追加していない。
- `identity.py:build_identity_tool`はLLMを使わない小さなAgentを`as_tool`にする。Toolboxの公開FunctionToolを使い、名前・metadataを保持して`whoami`を呼ぶ。
- Functionsが受信TokenのoidとGraph `/me` のidを照合する。Hostedは信頼済みToolboxのOBO成功結果を検査する。別環境でこのFunctionsを変更する場合も、この認証・本人照合は必要。
- `invoke_identity`は名前を要求内に限定し、終了時にContextVarをresetする。Webのメールやmetadataを本人照合に利用しない。
- 同意が必要ならSDKの`oauth_consent_request`と`response.incomplete`を返す。既存Webの同意ボタンで同意し、元の質問を再送する。tools/listとtools/callの同意例外を扱う。
- 成功時は名前をその応答へだけ出す。通常購買の親Agent、ContextProvider、購買セッションへは渡さない。Toolbox内にwhoamiがない場合やGraph失敗時は名前取得失敗を明示する。

## OTelとメール

`observability.py:current_request_attributes`は受信baggageのメール形式`user.id`を観測属性へ採用する。WebのEasyAuthメールから生成するため、OBOは不要。未到達なら属性を捏造せず省略する。Webの所有者キー・Web Spanはハッシュを維持しているため、成分間のuser.idが同じとは限らず、Trace／Conversation／Response IDでも相関する。

設定だけでPlan／Executeの独自Spanは生じない。既存Executorの実処理を[最小例](examples/minimal_agent_tool_otel.py)の`observed`で囲む。Hostのglobal providerを共有し、SDKのAgent／Tool／MCP Spanを手動で重複させない。

名前・Token・同意URLはSpanへ入れない。メールbaggageだけは利用者指定で伝播・表示する。`McpPrivacyProcessor`の固定SDK用内部hookは維持し、SDK更新時にはexport前の除去を確認する。
