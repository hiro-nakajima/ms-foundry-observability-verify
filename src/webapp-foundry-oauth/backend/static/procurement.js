"use strict";
const element = id => document.getElementById(id);
let csrf = "";
const fields = {
  testCaseId: "test.case.id", turn: "Turn", traceId: "Trace ID", spanId: "Span ID",
  parentSpanId: "Parent Span ID", conversationId: "Foundry Conversation ID",
  responseId: "Foundry Response ID", frameworkSessionIdHash: "Framework Session ID hash",
  platformPropagation: "Managed境界の伝播"
};
function addMessage(role, content) {
  element("empty-state")?.remove();
  const row = document.createElement("div"), bubble = document.createElement("div"), label = document.createElement("span"), text = document.createElement("div");
  row.className = `message-row ${role}`;
  bubble.className = "message-bubble";
  label.className = "message-label";
  label.textContent = role === "user" ? "あなた" : "Agent";
  text.textContent = typeof content === "string" ? content : "応答の表示形式を確認できませんでした。元のデータは表示していません。";
  if (role === "assistant") {
    element("response")?.removeAttribute("id");
    text.id = "response";
  }
  bubble.append(label, text); row.append(bubble); element("chat-history").append(row);
  element("messages").scrollTop = element("messages").scrollHeight;
  return text;
}
function show(value, target) {
  if (value.csrf) csrf = value.csrf;
  const details = element("details");
  details.replaceChildren();
  const entries = Object.entries(value.statuses || {}).concat(Object.entries(fields).map(([key, label]) => [label, value[key]]));
  for (const [label, content] of entries) {
    const term = document.createElement("dt"), description = document.createElement("dd");
    term.textContent = label;
    description.textContent = content ?? "未取得";
    details.append(term, description);
  }
  if (target) target.textContent = value.response || value.error || "完了を確認できませんでした。";
  else if (value.response !== undefined) target = addMessage("assistant", value.response);
  else if (value.error) target = addMessage("assistant", value.error);
  for (const candidate of value.candidates || []) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary-button candidate-choice";
    button.textContent = `${candidate.product_name}（${candidate.product_code}／単価 ${candidate.unit_price}円）を選ぶ`;
    button.addEventListener("click", () => {
      if (element("send").disabled) return;
      element("request").value = `商品コード ${candidate.product_code} を選びます。`;
      element("request-form").requestSubmit();
    });
    const row = document.createElement("div"); row.append(button); target?.parentElement.append(row);
  }
  element("notice").textContent = value.error || (value.conversationReset
    ? "Agent更新に合わせて新しい会話状態を開始しました。以前のFoundry履歴は削除していません。"
    : value.conversationId ? "同じ会話で続けられます。履歴はFoundry側に保持されます。" : "新しい会話を開始できます。");
  element("messages").scrollTop = element("messages").scrollHeight;
}
async function call(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST", credentials: "same-origin",
    headers: {"Content-Type": "application/json", "X-CSRF-Token": csrf},
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  if (response.status === 502) return response.json();
  if (!response.ok) throw new Error(`リクエスト失敗 (${response.status})。認証・会話状態を確認してください。`);
  return response.json();
}
async function streamChat(message, target) {
  const response = await fetch("/api/chat/stream", {method: "POST", credentials: "same-origin",
    headers: {"Content-Type": "application/json", "X-CSRF-Token": csrf}, body: JSON.stringify({message})});
  if (!response.ok) throw new Error(`リクエスト失敗 (${response.status})。認証・会話状態を確認してください。`);
  if (!response.headers.get("content-type")?.includes("application/x-ndjson")) {
    const value = await response.json(); show(value, target); return value;
  }
  const reader = response.body.getReader(), decoder = new TextDecoder();
  let buffer = "", final;
  try {
    while (true) {
      const {value, done} = await reader.read();
      buffer += decoder.decode(value, {stream: !done});
      const lines = buffer.split("\n"); buffer = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        if (event.type === "progress" && typeof event.text === "string") {
          target.textContent += (target.textContent ? "\n" : "") + event.text;
          element("messages").scrollTop = element("messages").scrollHeight;
        } else if (event.type === "result") { final = event.value; show(final, target); }
      }
      if (done) break;
    }
  } finally { reader.releaseLock(); }
  if (!final) throw new Error("通信が中断されました。処理の完了は確認できていません。");
  return final;
}
element("request-form").addEventListener("submit", async event => {
  event.preventDefault();
  const message = element("request").value.trim();
  if (!message) return;
  element("send").disabled = element("new").disabled = true;
  element("request").disabled = true;
  addMessage("user", message);
  element("notice").textContent = "Agentを実行しています…";
  const progress = addMessage("assistant", "");
  try { const value = await streamChat(message, progress); if (!value.error) element("request").value = ""; }
  catch (error) { element("notice").textContent = error.message; addMessage("assistant", error.message); }
  finally { element("send").disabled = element("new").disabled = element("request").disabled = false; element("request").focus(); }
});
element("new").addEventListener("click", async () => {
  element("send").disabled = element("new").disabled = true;
  try { const value = await call("/api/conversation", {}); element("chat-history").replaceChildren(); show(value); addMessage("assistant", "新しい会話です。以前のFoundry履歴は削除していません。"); }
  catch (error) { element("notice").textContent = error.message; }
  finally { element("send").disabled = element("new").disabled = false; }
});
call("/api/state").then(value => {
  show(value);
  if (value.conversationId) element("response").textContent = "同じ会話を再開できます。以前の履歴はFoundry側に保持され、この画面の会話表示は再読み込みでリセットされます。";
  element("send").disabled = element("new").disabled = false;
}).catch(error => { element("notice").textContent = error.message; });
