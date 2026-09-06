(function () {
  const STORAGE_KEY_BASE = "foundry-oauth-ui-state-v2";
  const TERMINAL_STATUSES = ["completed", "failed", "cancelled", "approval_required", "consent_required"];

  let storageKey = STORAGE_KEY_BASE + ":anonymous";
  let state = createInitialState();

  const elements = {
    messages: document.getElementById("messages"),
    emptyState: document.getElementById("empty-state"),
    cards: document.getElementById("cards"),
    input: document.getElementById("chat-input"),
    form: document.getElementById("chat-form"),
    sendButton: document.getElementById("send-button"),
    toolPanel: document.getElementById("tool-panel"),
    toolLogs: document.getElementById("tool-logs"),
    toolToggle: document.getElementById("tool-toggle"),
    toolIndicator: document.getElementById("tool-indicator"),
    toolClose: document.getElementById("tool-close"),
    clearHistory: document.getElementById("clear-history-button"),
  };

  let pollTimer = null;
  let streamAbortController = null;
  const TERMINAL_EVENT_TYPES = ["done", "error", "mcp_approval_required", "oauth_consent_required"];

  class ApiError extends Error {
    constructor(status, body) {
      super("HTTP " + status + ": " + body);
      this.name = "ApiError";
      this.status = status;
      this.body = body;
    }
  }

  function uid() {
    if (window.crypto && window.crypto.randomUUID) {
      return window.crypto.randomUUID();
    }
    return Math.random().toString(36).slice(2, 10);
  }

  function createInitialState() {
    return {
      conversationId: uid(),
      messages: [],
      toolLogs: [],
      approvalInfo: null,
      consentInfo: null,
      currentJobId: null,
      currentCursor: 0,
      activeAssistantId: null,
      streaming: false,
      toolPanelOpen: false,
    };
  }

  function loadState() {
    try {
      const saved = window.localStorage.getItem(storageKey);
      return saved ? JSON.parse(saved) : null;
    } catch (_error) {
      return null;
    }
  }

  function saveState() {
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(state));
    } catch (_error) {
      // Ignore storage failures; the in-page session can still continue.
    }
  }

  async function initializeUserScopedState() {
    try {
      const response = await fetch("/api/me", { headers: { Accept: "application/json" } });
      if (response.ok) {
        const user = await response.json();
        if (user && user.storageKey) {
          storageKey = STORAGE_KEY_BASE + ":" + user.storageKey;
        }
      }
    } catch (_error) {
      // Fall back to the anonymous local storage bucket. The server still
      // enforces user ownership for conversation and job state.
    }
    state = loadState() || createInitialState();
  }

  function setStreaming(isStreaming) {
    const waitingForResume = Boolean(state.approvalInfo || state.consentInfo);
    state.streaming = isStreaming;
    elements.input.disabled = isStreaming || waitingForResume;
    elements.sendButton.disabled =
      (!isStreaming && waitingForResume) || (!isStreaming && !elements.input.value.trim());
    elements.input.placeholder = isStreaming
      ? "Agent is responding..."
      : waitingForResume
        ? "Complete approval or consent to continue..."
        : "Send a message...";
    elements.sendButton.textContent = isStreaming ? "Stop" : "Send";
    saveState();
  }

  function escapeHtml(text) {
    return String(text || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }

  function renderMessages() {
    elements.emptyState.classList.toggle("hidden", state.messages.length > 0);
    elements.messages.querySelectorAll(".message-row").forEach((node) => node.remove());

    for (const message of state.messages) {
      const row = document.createElement("div");
      row.className = "message-row " + message.role;

      const bubble = document.createElement("div");
      bubble.className = "message-bubble";
      bubble.innerHTML =
        escapeHtml(message.content) +
        (message.streaming ? '<span class="stream-cursor"></span>' : "");

      row.appendChild(bubble);
      elements.messages.appendChild(row);
    }

    elements.messages.scrollTop = elements.messages.scrollHeight;
  }

  function renderCards() {
    elements.cards.innerHTML = "";

    if (state.approvalInfo) {
      const pendingApprovals =
        state.approvalInfo.pendingApprovals && state.approvalInfo.pendingApprovals.length
          ? state.approvalInfo.pendingApprovals
          : [state.approvalInfo];
      const approvalCount = pendingApprovals.length;
      const approvalDetails = pendingApprovals
        .map(function (approval, index) {
          return `
            <section class="approval-request">
              ${approvalCount > 1 ? `<h4>MCP call ${index + 1}</h4>` : ""}
              <p>Server: <span class="mono">${escapeHtml(approval.serverLabel || "(unknown)")}</span></p>
              <p>Tool: <span class="mono">${escapeHtml(approval.toolName || "(unknown)")}</span></p>
              ${
                approval.arguments && approval.arguments !== "{}"
                  ? `<pre>${escapeHtml(approval.arguments)}</pre>`
                  : ""
              }
            </section>
          `;
        })
        .join("");
      const card = document.createElement("section");
      card.className = "info-card approval";
      card.innerHTML = `
        <h3>MCP Tool Approval Required</h3>
        ${approvalDetails}
        <p>${
          approvalCount > 1
            ? `Review all ${approvalCount} MCP calls above. Your decision applies to every listed call.`
            : "This MCP call requires explicit approval before it can run."
        }</p>
        <div class="button-row">
          <button id="approve-button" class="primary-button" type="button">Approve and Continue</button>
          <button id="reject-button" class="danger-button" type="button">Reject</button>
        </div>
      `;
      elements.cards.appendChild(card);
      document.getElementById("approve-button").onclick = function () {
        approveMcpCall(true);
      };
      document.getElementById("reject-button").onclick = function () {
        approveMcpCall(false);
      };
    }

    if (state.consentInfo) {
      const card = document.createElement("section");
      card.className = "info-card consent";
      card.innerHTML = `
        <h3>OAuth Consent Required</h3>
        ${
          state.consentInfo.connectionName
            ? `<p>Connection: <span class="mono">${escapeHtml(state.consentInfo.connectionName)}</span></p>`
            : ""
        }
        <p>Open the consent page, sign in, then return here and continue.</p>
        <div class="button-row">
          <button id="consent-open-button" class="secondary-button" type="button">Open Consent Page</button>
          <button id="consent-continue-button" class="primary-button" type="button">I've Consented - Continue</button>
        </div>
      `;
      elements.cards.appendChild(card);
      document.getElementById("consent-open-button").onclick = openConsentPopup;
      document.getElementById("consent-continue-button").onclick = continueAfterConsent;
    }
  }

  function renderToolLogs() {
    elements.toolLogs.innerHTML = "";

    if (state.toolLogs.length === 0) {
      elements.toolLogs.innerHTML = '<p class="tool-placeholder">No tool calls yet.</p>';
    } else {
      for (const log of [...state.toolLogs].reverse()) {
        const card = document.createElement("div");
        card.className = "tool-log-card " + log.status;
        card.innerHTML = `
          <div class="tool-log-header">
            <strong class="tool-log-name">${escapeHtml(iconForStatus(log.status) + " " + log.toolName)}</strong>
            <span>${escapeHtml(log.startedAt)}</span>
          </div>
          <div class="tool-log-meta">
            <span class="mono">${escapeHtml(shortCallId(log.callId))}</span>
            <span>${escapeHtml(log.status)}</span>
          </div>
          ${
            log.error
              ? `<div class="tool-log-error">${escapeHtml(log.error)}</div>`
              : ""
          }
          ${
            log.detail
              ? `<div class="tool-log-detail">${escapeHtml(log.detail)}</div>`
              : ""
          }
          ${
            log.arguments && log.arguments !== "{}"
              ? `<pre>${escapeHtml(log.arguments)}</pre>`
              : ""
          }
        `;
        elements.toolLogs.appendChild(card);
      }
    }

    const running = state.toolLogs.some((log) => log.status === "running");
    elements.toolIndicator.classList.toggle("hidden", !running);
  }

  function shortCallId(callId) {
    return callId && callId.length > 16 ? callId.slice(0, 16) + "..." : callId || "";
  }

  function iconForStatus(status) {
    if (status === "running") return "In Progress";
    if (status === "waiting") return "Waiting";
    if (status === "error") return "Error";
    if (status === "rejected") return "Rejected";
    return "Done";
  }

  function toggleToolPanel(open) {
    state.toolPanelOpen = open;
    elements.toolPanel.classList.toggle("tool-panel-closed", !open);
    saveState();
  }

  function getActiveAssistantMessage() {
    let message = state.messages.find((item) => item.id === state.activeAssistantId);
    if (!message) {
      message = {
        id: uid(),
        role: "assistant",
        content: "",
        streaming: true,
      };
      state.activeAssistantId = message.id;
      state.messages.push(message);
    }
    return message;
  }

  function finishActiveMessage(extraText) {
    const message = getActiveAssistantMessage();
    if (extraText) {
      message.content += extraText;
    }
    message.streaming = false;
    renderMessages();
    saveState();
  }

  function updateToolLog(callId, patch) {
    for (const log of state.toolLogs) {
      if (log.callId === callId) {
        Object.assign(log, patch);
      }
    }
    renderToolLogs();
    saveState();
  }

  function addToolLog(entry) {
    state.toolLogs.push({
      id: uid(),
      callId: entry.callId || uid(),
      toolName: entry.toolName || "unknown_tool",
      status: entry.status || "running",
      detail: entry.detail || "",
      arguments: entry.arguments || "",
      error: entry.error || "",
      startedAt: new Date().toLocaleTimeString(),
    });
    toggleToolPanel(true);
    renderToolLogs();
    saveState();
  }

  function applyJobEvent(event) {
    const type = event.type;
    const assistantMessage = getActiveAssistantMessage();

    if (type === "text.delta") {
      assistantMessage.content += event.delta || "";
      renderMessages();
    } else if (type === "tool.start") {
      addToolLog({
        toolName: event.toolName || "unknown_tool",
        callId: event.callId || uid(),
        status: "running",
        detail: event.detail || event.toolType || "",
        arguments: event.arguments || "",
      });
    } else if (type === "tool.end") {
      updateToolLog(event.callId, { status: "done" });
    } else if (type === "tool.error") {
      updateToolLog(event.callId, { status: "error", error: event.error || "" });
    } else if (type === "mcp_approval_required") {
      finishActiveMessage();
      const pendingApprovals =
        event.pendingApprovals && event.pendingApprovals.length
          ? event.pendingApprovals
          : [
              {
                approvalRequestId: event.approvalRequestId,
                serverLabel: event.serverLabel,
                toolName: event.toolName,
                arguments: event.arguments || "{}",
              },
            ];
      state.approvalInfo = {
        ...pendingApprovals[0],
        approvalRequestIds:
          event.approvalRequestIds && event.approvalRequestIds.length
            ? event.approvalRequestIds
            : pendingApprovals
                .map(function (approval) {
                  return approval.approvalRequestId;
                })
                .filter(Boolean),
        pendingApprovals: pendingApprovals,
      };
      addToolLog({
        toolName: event.toolName || "MCP tool",
        callId: event.approvalRequestId || uid(),
        status: "waiting",
        detail: "MCP approval required" + (event.serverLabel ? " on " + event.serverLabel : ""),
        arguments: event.arguments || "{}",
      });
      renderCards();
    } else if (type === "oauth_consent_required") {
      finishActiveMessage();
      state.consentInfo = {
        consentLink: event.consentLink,
        connectionName: event.connectionName,
      };
      addToolLog({
        toolName: event.connectionName || "OAuth consent",
        callId: event.responseId || uid(),
        status: "waiting",
        detail: "OAuth consent required",
      });
      renderCards();
    } else if (type === "error") {
      finishActiveMessage("\n\nError: " + (event.message || "Unknown error"));
    } else if (type === "done") {
      finishActiveMessage();
    }

    renderMessages();
    saveState();
  }

  async function startJob(endpoint, body) {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      throw new ApiError(response.status, await response.text());
    }
    const job = await response.json();
    state.currentJobId = job.jobId;
    state.currentCursor = job.nextCursor || 0;
    setStreaming(true);
    saveState();
    startJobEventStream();
  }

  async function refreshConversationState() {
    const response = await fetch(
      "/api/conversations/" + encodeURIComponent(state.conversationId) + "/state",
      { headers: { Accept: "application/json" } }
    );
    if (!response.ok) {
      throw new ApiError(response.status, await response.text());
    }

    const remoteState = await response.json();
    const pendingApprovals = remoteState.pendingApprovals || [];
    const pendingApproval = pendingApprovals[0];
    if (pendingApproval && pendingApproval.approvalRequestId) {
      state.approvalInfo = {
        ...pendingApproval,
        approvalRequestIds: pendingApprovals
          .map(function (approval) {
            return approval.approvalRequestId;
          })
          .filter(Boolean),
        pendingApprovals: pendingApprovals,
      };
      state.consentInfo = null;
      renderCards();
      setStreaming(false);
      saveState();
      return true;
    }

    if (remoteState.awaitingConsent) {
      state.approvalInfo = null;
      state.consentInfo =
        remoteState.pendingConsent ||
        state.consentInfo || {
          consentLink: "",
          connectionName: "",
        };
      renderCards();
      setStreaming(false);
      saveState();
      return true;
    }

    return false;
  }

  async function recoverWaitingConversation(error, fallbackMessage) {
    if (!(error instanceof ApiError) || error.status !== 409) {
      return false;
    }
    const recovered = await refreshConversationState();
    if (recovered) {
      finishActiveMessage(fallbackMessage);
      return true;
    }
    return false;
  }

  function stopJobEventStream() {
    if (streamAbortController) {
      streamAbortController.abort();
      streamAbortController = null;
    }
  }

  function finishCurrentJob() {
    state.currentJobId = null;
    state.currentCursor = 0;
    state.activeAssistantId = null;
    setStreaming(false);
    saveState();
  }

  function parseSseMessage(message) {
    const dataLines = message
      .split(/\r?\n/)
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart());
    if (!dataLines.length) {
      return null;
    }
    const data = dataLines.join("\n").trim();
    if (!data || data === "[DONE]") {
      return null;
    }
    return JSON.parse(data);
  }

  async function streamCurrentJobEvents() {
    if (!state.currentJobId) {
      return;
    }

    const jobId = state.currentJobId;
    const controller = new AbortController();
    streamAbortController = controller;

    try {
      const response = await fetch(
        "/api/jobs/" + encodeURIComponent(jobId) + "/events?cursor=" + state.currentCursor,
        {
          headers: { Accept: "text/event-stream" },
          signal: controller.signal,
        }
      );
      if (!response.ok || !response.body) {
        throw new Error("HTTP " + response.status + ": " + (await response.text()));
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }
        buffer += decoder.decode(value, { stream: true });

        let separatorIndex;
        while ((separatorIndex = buffer.indexOf("\n\n")) >= 0) {
          const rawMessage = buffer.slice(0, separatorIndex);
          buffer = buffer.slice(separatorIndex + 2);
          const event = parseSseMessage(rawMessage);
          if (!event) {
            continue;
          }
          if (state.currentJobId !== jobId) {
            return;
          }

          applyJobEvent(event);
          state.currentCursor += 1;

          if (TERMINAL_EVENT_TYPES.includes(event.type)) {
            finishCurrentJob();
            return;
          }
        }
      }

      if (state.currentJobId === jobId) {
        // If the SSE connection closes without a terminal event, fall back to
        // the existing polling path so the UI can still recover.
        schedulePoll(0);
      }
    } catch (error) {
      if (error && error.name === "AbortError") {
        return;
      }
      if (state.currentJobId === jobId) {
        schedulePoll(0);
      }
    } finally {
      if (streamAbortController === controller) {
        streamAbortController = null;
      }
    }
  }

  function startJobEventStream() {
    window.clearTimeout(pollTimer);
    stopJobEventStream();
    streamCurrentJobEvents();
  }

  async function pollCurrentJob() {
    if (!state.currentJobId) {
      return;
    }

    try {
      const response = await fetch(
        "/api/jobs/" + encodeURIComponent(state.currentJobId) + "?cursor=" + state.currentCursor,
        { headers: { Accept: "application/json" } }
      );
      if (!response.ok) {
        throw new Error("HTTP " + response.status + ": " + (await response.text()));
      }

      const job = await response.json();
      for (const event of job.events || []) {
        applyJobEvent(event);
      }
      state.currentCursor = job.nextCursor || state.currentCursor;

      if (TERMINAL_STATUSES.includes(job.status)) {
        if (job.status === "cancelled") {
          finishActiveMessage("\n\nRequest cancelled.");
        } else if (job.status === "failed" && job.error && !(job.events || []).some((event) => event.type === "error")) {
          finishActiveMessage("\n\nError: " + job.error);
        } else if (job.status === "completed") {
          finishActiveMessage();
        }
        finishCurrentJob();
        return;
      }

      schedulePoll(900);
    } catch (error) {
      finishActiveMessage(
        "\n\nPolling failed: " + (error instanceof Error ? error.message : String(error))
      );
      finishCurrentJob();
    }
  }

  function schedulePoll(delay) {
    window.clearTimeout(pollTimer);
    pollTimer = window.setTimeout(pollCurrentJob, delay);
  }

  async function clearHistory() {
    if (state.streaming && state.currentJobId) {
      await cancelCurrentJob();
    }
    window.clearTimeout(pollTimer);
    stopJobEventStream();
    const oldConversationId = state.conversationId;
    state.conversationId = uid();
    state.messages = [];
    state.toolLogs = [];
    state.approvalInfo = null;
    state.consentInfo = null;
    state.currentJobId = null;
    state.currentCursor = 0;
    state.activeAssistantId = null;
    state.streaming = false;
    elements.input.value = "";
    renderMessages();
    renderCards();
    renderToolLogs();
    setStreaming(false);
    saveState();
    clearServerConversation(oldConversationId);
  }

  async function clearServerConversation(conversationId) {
    if (!conversationId) {
      return;
    }
    try {
      await fetch("/api/conversations/" + encodeURIComponent(conversationId), {
        method: "DELETE",
      });
    } catch (_error) {
      // Local history is already cleared. Server cleanup is best-effort.
    }
  }

  async function sendMessage() {
    if (state.streaming && state.currentJobId) {
      await cancelCurrentJob();
      return;
    }

    const text = elements.input.value.trim();
    if (!text || state.approvalInfo || state.consentInfo) {
      return;
    }

    state.approvalInfo = null;
    state.consentInfo = null;
    renderCards();

    state.messages.push({
      id: uid(),
      role: "user",
      content: text,
      streaming: false,
    });
    const assistantMessage = {
      id: uid(),
      role: "assistant",
      content: "",
      streaming: true,
    };
    state.activeAssistantId = assistantMessage.id;
    state.messages.push(assistantMessage);
    renderMessages();
    elements.input.value = "";
    setStreaming(true);

    try {
      await startJob("/api/chat", {
        conversationId: state.conversationId,
        userMessage: text,
      });
    } catch (error) {
      const recovered = await recoverWaitingConversation(
        error,
        "This conversation is waiting for MCP approval or OAuth consent. Please continue from the card below."
      ).catch(function () {
        return false;
      });
      if (!recovered) {
        finishActiveMessage("Error: " + (error instanceof Error ? error.message : String(error)));
      }
      state.currentJobId = null;
      state.activeAssistantId = null;
      setStreaming(false);
    }
  }

  async function continueConversation(options) {
    const hasPendingApproval =
      Boolean(options && options.approvalRequestIds && options.approvalRequestIds.length);
    if (!state.approvalInfo && !state.consentInfo && !hasPendingApproval) {
      return;
    }

    if (options && options.clearConsent) {
      state.consentInfo = null;
    }
    renderCards();

    const assistantMessage = {
      id: uid(),
      role: "assistant",
      content: "",
      streaming: true,
    };
    state.activeAssistantId = assistantMessage.id;
    state.messages.push(assistantMessage);
    renderMessages();
    setStreaming(true);

    try {
      await startJob("/api/continue", {
        conversationId: state.conversationId,
        approve: options && options.approve !== undefined ? options.approve : true,
        approvalRequestIds: options ? options.approvalRequestIds : undefined,
      });
    } catch (error) {
      const recovered = await recoverWaitingConversation(
        error,
        "This conversation is still waiting for approval or consent. Please use the card below."
      ).catch(function () {
        return false;
      });
      if (!recovered) {
        finishActiveMessage(
          "Failed to continue: " + (error instanceof Error ? error.message : String(error))
        );
      }
      state.currentJobId = null;
      state.activeAssistantId = null;
      setStreaming(false);
    }
  }

  async function cancelCurrentJob() {
    if (!state.currentJobId) {
      return;
    }
    const jobId = state.currentJobId;
    state.currentJobId = null;
    window.clearTimeout(pollTimer);
    stopJobEventStream();
    try {
      await fetch("/api/jobs/" + encodeURIComponent(jobId) + "/cancel", { method: "POST" });
    } catch (_error) {
      // The local UI should stop even if the cancellation request cannot be delivered.
    }
    finishActiveMessage("\n\nRequest cancelled.");
    state.currentCursor = 0;
    state.activeAssistantId = null;
    setStreaming(false);
  }

  function approveMcpCall(approve) {
    if (!state.approvalInfo) {
      return;
    }
    const approvalRequestId = state.approvalInfo.approvalRequestId;
    const approvalRequestIds =
      state.approvalInfo.approvalRequestIds && state.approvalInfo.approvalRequestIds.length
        ? state.approvalInfo.approvalRequestIds
        : [approvalRequestId].filter(Boolean);
    state.approvalInfo = null;
    updateToolLog(approvalRequestId, {
      status: approve ? "done" : "rejected",
      detail: approve ? "MCP approval accepted" : "MCP approval rejected",
    });
    renderCards();
    continueConversation({
      approve: approve,
      approvalRequestIds: approvalRequestIds,
      clearConsent: false,
    });
  }

  function continueAfterConsent() {
    continueConversation({ clearConsent: true });
  }

  function openConsentPopup() {
    if (!state.consentInfo || !state.consentInfo.consentLink) {
      return;
    }
    const popup = window.open(
      state.consentInfo.consentLink,
      "foundry-oauth-consent",
      "width=600,height=720,scrollbars=yes,resizable=yes"
    );
    if (!popup) {
      window.alert("Popup was blocked. Please allow popups for this page.");
    }
  }

  elements.form.addEventListener("submit", function (event) {
    event.preventDefault();
    sendMessage();
  });

  elements.input.addEventListener("input", function () {
    const waitingForResume = Boolean(state.approvalInfo || state.consentInfo);
    elements.sendButton.disabled =
      (!state.streaming && waitingForResume) || (!state.streaming && !elements.input.value.trim());
  });

  elements.toolToggle.addEventListener("click", function () {
    toggleToolPanel(!state.toolPanelOpen);
  });

  elements.toolClose.addEventListener("click", function () {
    toggleToolPanel(false);
  });

  elements.clearHistory.addEventListener("click", function () {
    clearHistory();
  });

  async function initialize() {
    await initializeUserScopedState();
    renderMessages();
    renderCards();
    renderToolLogs();
    toggleToolPanel(Boolean(state.toolPanelOpen));
    setStreaming(Boolean(state.currentJobId));
    if (state.currentJobId) {
      startJobEventStream();
    } else if (!state.approvalInfo && !state.consentInfo) {
      refreshConversationState().catch(function () {
        // A missing server-side conversation is harmless for a fresh page load.
      });
    }
  }

  initialize().catch(function (error) {
    finishActiveMessage("Initialization failed: " + (error instanceof Error ? error.message : String(error)));
    setStreaming(false);
  });
})();
