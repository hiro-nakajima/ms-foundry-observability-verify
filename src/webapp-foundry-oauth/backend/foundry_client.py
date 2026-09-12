"""FoundryとのHTTP通信と、画面用SSEイベントへの変換。

会話状態とリセット関数は呼び出し元から受け取り、Web APIへ依存しない。
"""
import json
import logging
import uuid
from urllib.parse import quote
from typing import Any, AsyncIterator, Optional

import httpx
import telemetry

logger = logging.getLogger(__name__)


def _extract_text_from_response(response_obj: dict[str, Any]) -> str:
    """Extract assistant text from a Responses API response payload."""
    output_items = response_obj.get("output", [])
    if not isinstance(output_items, list):
        return ""

    chunks: list[str] = []
    for item in output_items:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "message":
            continue
        content = item.get("content", [])
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            part_type = part.get("type")
            if part_type in ("output_text", "text", "input_text"):
                text = part.get("text", "")
                if isinstance(text, str) and text:
                    chunks.append(text)
    return "".join(chunks)


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _parse_sse_payload(payload: str) -> Optional[dict[str, Any]]:
    line = payload.strip()
    if not line.startswith("data:"):
        return None
    data = line[5:].strip()
    if not data or data == "[DONE]":
        return None
    try:
        event = json.loads(data)
    except json.JSONDecodeError:
        return None
    return event if isinstance(event, dict) else None


def _tool_event_from_item(item: dict[str, Any]) -> Optional[dict[str, str]]:
    item_type = item.get("type", "")
    if not isinstance(item_type, str):
        return None
    if item_type in ("message", "reasoning", "mcp_approval_request", "oauth_consent_request"):
        return None
    if item_type != "function_call" and not item_type.endswith("_call"):
        return None

    call_id = item.get("call_id") or item.get("id") or uuid.uuid4().hex
    tool_name = (
        item.get("name")
        or item.get("tool_name")
        or item.get("server_label")
        or item_type
    )
    server_label = item.get("server_label", "")
    detail = f"{item_type}"
    if server_label:
        detail = f"{detail} on {server_label}"

    return {
        "callId": str(call_id),
        "toolName": str(tool_name),
        "toolType": item_type,
        "detail": detail,
        "arguments": "",  # Tool arguments are not part of the public execution log.
    }


async def _stream_response(
    project_endpoint: str,
    agent_name: str,
    user_message: Optional[str],
    previous_response_id: Optional[str],
    approval_inputs: Optional[list[dict[str, Any]]],
    conversation_id: str,
    outbound_headers: dict[str, str],
    metadata: Optional[dict[str, str]] = None,
    foundry_conversation_id: Optional[str] = None,
    output_items: Optional[list[dict[str, Any]]] = None,
    tool_choice: Optional[dict[str, str]] = None,
    *, conversations: dict, reset_conversation, diagnostics: dict | None = None,
) -> AsyncIterator[str]:
    """
    Call the Foundry Responses API with streaming and translate the raw SSE
    events into the simplified event schema consumed by the frontend.

    The Foundry API is OpenAI-compatible; the new stable Agent endpoint is:
        POST {project_endpoint}/agents/{agent_name}/endpoint/protocols/openai/responses?api-version=v1

    With `stream: true` the server returns Server-Sent Events.
    Foundry additionally emits `oauth_consent_request` events when MCP tools
    require user-delegated OAuth consent.
    See: https://learn.microsoft.com/azure/ai-foundry/agents/how-to/mcp-authentication
    """
    # ── Build request body ───────────────────────────────────────────────────
    # Agent selection is now part of the URL path. Do not send the legacy
    # project-endpoint `agent_reference` body or the older `model` selector.
    body: dict = {
        "stream": True,
    }
    if metadata:
        body["metadata"] = metadata
    if foundry_conversation_id:
        body["conversation"] = foundry_conversation_id
    if tool_choice:
        body["tool_choice"] = tool_choice

    if previous_response_id and not foundry_conversation_id:
        # Continue the previous response (after OAuth consent or multi-turn)
        # Reference: https://learn.microsoft.com/azure/ai-foundry/agents/how-to/mcp-authentication
        body["previous_response_id"] = previous_response_id

    if approval_inputs is not None:
        body["input"] = approval_inputs

    if user_message:
        user_input_item = {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": user_message}],
        }
        if "input" in body and isinstance(body["input"], list):
            body["input"].append(user_input_item)
        else:
            body["input"] = [user_input_item]

    if previous_response_id and "input" not in body:
        body["input"] = []

    encoded_agent_name = quote(agent_name, safe="")
    url = (
        f"{project_endpoint.rstrip('/')}"
        f"/agents/{encoded_agent_name}/endpoint/protocols/openai/responses?api-version=v1"
    )
    logger.info(
        "Calling Foundry Agent endpoint Responses API url=%s previous_response_id=%s agent=%s",
        url,
        previous_response_id,
        agent_name,
    )

    # ── Mutable state across the stream ─────────────────────────────────────
    response_id: Optional[str] = None
    response_completed = False
    deferred_action_event: Optional[dict[str, Any]] = None
    deferred_approval_events: dict[str, dict[str, Any]] = {}
    deferred_consent_event: Optional[dict[str, Any]] = None
    carried_consent_event: Optional[dict[str, Any]] = None
    existing_pending_consent = conversations.get(conversation_id, {}).get(
        "pending_consent"
    )
    if approval_inputs is not None and existing_pending_consent:
        carried_consent_event = {
            "type": "oauth_consent_required",
            "consentLink": existing_pending_consent.get("consentLink", ""),
            "connectionName": existing_pending_consent.get("connectionName", ""),
        }
    emitted_text = False
    active_tool_calls: dict[str, str] = {}  # call_id → tool_name
    # 計装済みHTTPXを通すことで、依存Spanとtraceparent/baggageの送信を揃える。
    async def capture_response(response):
        if diagnostics is not None:
            telemetry.capture_sent_headers(response, diagnostics)

    async with telemetry.http_client(timeout=210.0, event_hooks={"response": [capture_response]}) as client:
        try:
            async with client.stream(
                "POST",
                url,
                headers=outbound_headers,
                json=body,
            ) as resp:
                resp.raise_for_status()

                current_event_type: Optional[str] = None

                async for raw_line in resp.aiter_lines():
                    line = raw_line.strip()
                    if not line:
                        # Empty line = end of one SSE event block
                        current_event_type = None
                        continue

                    # SSE `event:` field
                    if line.startswith("event:"):
                        current_event_type = line[6:].strip()
                        continue

                    # SSE `data:` field
                    if not line.startswith("data:"):
                        continue

                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        # [DONE]だけで切断すると上流の処理が取り消される場合がある。
                        # EOFまで読み切り、正常終了後に会話の再開状態を確定する。
                        continue

                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        logger.debug("Non-JSON SSE data skipped")
                        continue

                    # Use the SSE event field, or fall back to the "type" key in data
                    event_type = current_event_type or data.get("type", "")

                    # ── Response created → capture response ID ───────────────
                    if event_type == "response.created":
                        response_id = (
                            data.get("response", {}).get("id")
                            or data.get("id")
                        )

                    # ── Text output delta ────────────────────────────────────
                    elif event_type in (
                        "response.output_text.delta",
                        "response.text.delta",
                    ):
                        delta = data.get("delta", "")
                        if delta:
                            emitted_text = True
                            yield _sse({"type": "text.delta", "delta": delta})

                    elif event_type == "response.content_part.delta":
                        delta = data.get("delta", {})
                        text = (
                            delta.get("text", "")
                            if isinstance(delta, dict)
                            else str(delta)
                        )
                        if text:
                            emitted_text = True
                            yield _sse({"type": "text.delta", "delta": text})

                    # ── Tool call started ────────────────────────────────────
                    elif event_type == "response.output_item.added":
                        item = data.get("item", {})
                        tool_event = _tool_event_from_item(item)
                        if tool_event:
                            call_id = tool_event["callId"]
                            tool_name = tool_event["toolName"]
                            active_tool_calls[call_id] = tool_name
                            logger.info(
                                "Tool call started: %s (call_id=%s)", tool_name, call_id
                            )
                            yield _sse(
                                {
                                    "type": "tool.start",
                                    "toolName": tool_name,
                                    "callId": call_id,
                                    "toolType": tool_event["toolType"],
                                    "detail": tool_event["detail"],
                                    "arguments": tool_event["arguments"],
                                }
                            )
                        elif item.get("type") == "oauth_consent_request":
                            deferred_action_event = {
                                "type": "oauth_consent_required",
                                "consentLink": item.get("consent_link", ""),
                                "responseId": response_id,
                                "connectionName": item.get("server_label", ""),
                            }
                            deferred_consent_event = deferred_action_event
                            logger.info(
                                "OAuth consent detected (output item); draining Foundry stream before UI notification: "
                                "connection=%s response_id=%s",
                                deferred_action_event["connectionName"],
                                response_id,
                            )
                        elif item.get("type") == "mcp_approval_request":
                            deferred_action_event = {
                                "type": "mcp_approval_required",
                                "approvalRequestId": item.get("id", ""),
                                "serverLabel": item.get("server_label", ""),
                                "toolName": item.get("name", ""),
                                "arguments": item.get("arguments", "{}"),
                                "responseId": response_id,
                            }
                            approval_request_id = deferred_action_event[
                                "approvalRequestId"
                            ]
                            if approval_request_id:
                                deferred_approval_events[approval_request_id] = (
                                    deferred_action_event
                                )
                            logger.info(
                                "MCP approval detected; draining Foundry stream before UI notification: "
                                "server=%s tool=%s approval_id=%s response_id=%s",
                                deferred_action_event["serverLabel"],
                                deferred_action_event["toolName"],
                                deferred_action_event["approvalRequestId"],
                                response_id,
                            )

                    elif event_type == "mcp_approval_request":
                        deferred_action_event = {
                            "type": "mcp_approval_required",
                            "approvalRequestId": data.get("id", ""),
                            "serverLabel": data.get("server_label", ""),
                            "toolName": data.get("name", ""),
                            "arguments": data.get("arguments", "{}"),
                            "responseId": response_id,
                        }
                        approval_request_id = deferred_action_event[
                            "approvalRequestId"
                        ]
                        if approval_request_id:
                            deferred_approval_events[approval_request_id] = (
                                deferred_action_event
                            )
                        logger.info(
                            "MCP approval detected (direct event); draining Foundry stream before UI notification: "
                            "server=%s tool=%s approval_id=%s response_id=%s",
                            deferred_action_event["serverLabel"],
                            deferred_action_event["toolName"],
                            deferred_action_event["approvalRequestId"],
                            response_id,
                        )

                    # ── Tool call completed ──────────────────────────────────
                    elif event_type == "response.output_item.done":
                        item = data.get("item", {})
                        if output_items is not None and item.get("type") == "mcp_call":
                            output_items.append(item)
                        tool_event = _tool_event_from_item(item)
                        if tool_event:
                            call_id = tool_event["callId"]
                            tool_name = active_tool_calls.get(
                                call_id, tool_event["toolName"]
                            )
                            logger.info(
                                "Tool call done: %s (call_id=%s)", tool_name, call_id
                            )
                            yield _sse(
                                {
                                    "type": "tool.end",
                                    "toolName": tool_name,
                                    "callId": call_id,
                                }
                            )
                        elif item.get("type") == "oauth_consent_request":
                            deferred_action_event = {
                                "type": "oauth_consent_required",
                                "consentLink": item.get("consent_link", ""),
                                "responseId": response_id,
                                "connectionName": item.get("server_label", ""),
                            }
                            deferred_consent_event = deferred_action_event
                        elif item.get("type") == "mcp_approval_request":
                            deferred_action_event = {
                                "type": "mcp_approval_required",
                                "approvalRequestId": item.get("id", ""),
                                "serverLabel": item.get("server_label", ""),
                                "toolName": item.get("name", ""),
                                "arguments": item.get("arguments", "{}"),
                                "responseId": response_id,
                            }
                            approval_request_id = deferred_action_event[
                                "approvalRequestId"
                            ]
                            if approval_request_id:
                                deferred_approval_events[approval_request_id] = (
                                    deferred_action_event
                                )

                    # ── OAuth consent required ───────────────────────────────
                    # Foundry emits this event when an MCP tool needs the user
                    # to grant OAuth delegated access.
                    # After the user grants consent, the app must call
                    # /api/continue with the stored previous_response_id.
                    # Reference:
                    #   https://learn.microsoft.com/azure/ai-foundry/agents/how-to/mcp-authentication
                    elif event_type in (
                        "oauth_consent_request",
                        "response.oauth_consent_requested",
                    ):
                        deferred_action_event = {
                            "type": "oauth_consent_required",
                            "consentLink": data.get("consent_link", ""),
                            "responseId": response_id,
                            "connectionName": (
                                data.get("connection_name", "")
                                or data.get("server_label", "")
                            ),
                        }
                        deferred_consent_event = deferred_action_event
                        # SECURITY: Do NOT log the full consent_link as it may
                        # contain OAuth state / nonce parameters.
                        logger.info(
                            "OAuth consent detected; draining Foundry stream before UI notification: "
                            "connection=%s response_id=%s",
                            deferred_action_event["connectionName"],
                            response_id,
                        )

                    # Handle oauth_consent_request embedded as a key in data
                    elif "oauth_consent_request" in data:
                        consent_obj = data["oauth_consent_request"]
                        deferred_action_event = {
                            "type": "oauth_consent_required",
                            "consentLink": consent_obj.get("consent_link", ""),
                            "responseId": response_id,
                            "connectionName": consent_obj.get("connection_name", ""),
                        }
                        deferred_consent_event = deferred_action_event
                        logger.info(
                            "OAuth consent detected (embedded); draining Foundry stream before UI notification: "
                            "connection=%s response_id=%s",
                            deferred_action_event["connectionName"],
                            response_id,
                        )

                    # ── Response completed → persist response_id ────────────
                    elif event_type == "response.incomplete" and deferred_consent_event:
                        # Hosted Toolbox consent is a paused response, with
                        # incomplete as its native terminal event.
                        response_completed = True
                        response_id = data.get("response", {}).get("id") or response_id
                    elif event_type == "response.completed":
                        resp_obj = data.get("response", {})
                        if output_items is not None:
                            output_items.extend(item for item in resp_obj.get("output", [])
                                                if isinstance(item, dict) and item.get("type") == "mcp_call")
                        if not emitted_text and isinstance(resp_obj, dict):
                            final_text = _extract_text_from_response(resp_obj)
                            if final_text:
                                emitted_text = True
                                yield _sse({"type": "text.delta", "delta": final_text})
                        response_id = resp_obj.get("id", response_id)
                        response_completed = True
                        logger.info(
                            "Foundry response completed upstream; draining remaining SSE framing: %s",
                            response_id,
                        )

                    # ── Error event ──────────────────────────────────────────
                    elif event_type == "error":
                        msg = "Foundry returned an error event."
                        logger.error(msg)
                        yield _sse({"type": "error", "message": msg})

            # Only make continuation state actionable after the upstream stream
            # has reached response.completed and the HTTP response has been
            # drained/closed normally. Closing a synchronous Responses API
            # stream earlier can cancel the response and invalidate its ID.
            if not response_completed:
                logger.error(
                    "Foundry stream ended before response.completed; response_id=%s deferred_action=%s",
                    response_id,
                    deferred_action_event.get("type") if deferred_action_event else None,
                )
                yield _sse(
                    {
                        "type": "error",
                        "message": (
                            "Foundry stream ended before response.completed. "
                            "Conversation state was not advanced; please retry."
                        ),
                    }
                )
                return

            state = conversations.setdefault(
                conversation_id,
                {
                    "previous_response_id": None,
                    "pending_approvals": [],
                    "awaiting_consent": False,
                },
            )
            state["previous_response_id"] = response_id

            consent_action_event = deferred_consent_event or carried_consent_event
            if deferred_approval_events or consent_action_event or deferred_action_event:
                approval_events = list(deferred_approval_events.values())
                if (
                    not approval_events
                    and deferred_action_event
                    and deferred_action_event["type"] == "mcp_approval_required"
                ):
                    approval_events = [deferred_action_event]

                if approval_events:
                    state["pending_approvals"] = [
                        {
                            "id": approval_event.get("approvalRequestId", ""),
                            "serverLabel": approval_event.get("serverLabel", ""),
                            "toolName": approval_event.get("toolName", ""),
                            "arguments": approval_event.get("arguments", "{}"),
                        }
                        for approval_event in approval_events
                    ]
                    deferred_action_event = dict(approval_events[0])
                    deferred_action_event["responseId"] = response_id
                    deferred_action_event["approvalRequestIds"] = [
                        approval["id"]
                        for approval in state["pending_approvals"]
                        if approval["id"]
                    ]
                    deferred_action_event["pendingApprovals"] = [
                        {
                            "approvalRequestId": approval["id"],
                            "serverLabel": approval["serverLabel"],
                            "toolName": approval["toolName"],
                            "arguments": approval["arguments"],
                        }
                        for approval in state["pending_approvals"]
                    ]
                    state["awaiting_consent"] = consent_action_event is not None
                    if consent_action_event:
                        state["pending_consent"] = {
                            "consentLink": consent_action_event.get("consentLink", ""),
                            "connectionName": consent_action_event.get(
                                "connectionName", ""
                            ),
                        }
                    else:
                        state.pop("pending_consent", None)
                    logger.info(
                        "MCP approval ready after completed response: response_id=%s approval_ids=%s consent_pending=%s",
                        response_id,
                        deferred_action_event["approvalRequestIds"],
                        state["awaiting_consent"],
                    )
                else:
                    deferred_action_event = dict(consent_action_event or {})
                    deferred_action_event["responseId"] = response_id
                    state["pending_approvals"] = []
                    state["awaiting_consent"] = True
                    state["pending_consent"] = {
                        "consentLink": deferred_action_event.get("consentLink", ""),
                        "connectionName": deferred_action_event.get(
                            "connectionName", ""
                        ),
                    }
                    logger.info(
                        "OAuth consent ready after completed response: response_id=%s connection=%s",
                        response_id,
                        deferred_action_event.get("connectionName", ""),
                    )
                yield _sse(deferred_action_event)
                return

            state["pending_approvals"] = []
            state["awaiting_consent"] = False
            state.pop("pending_consent", None)
            logger.info("Response completed: %s", response_id)
            yield _sse({"type": "done", "responseId": response_id or ""})

        except httpx.HTTPStatusError as exc:
            msg = f"Foundry API HTTP {exc.response.status_code}"
            logger.error(msg)
            if exc.response.status_code == 400 and previous_response_id:
                reset_conversation(
                    conversation_id,
                    conversation_id,
                    "foundry_400_with_previous_response_id",
                )
                if user_message and approval_inputs is None:
                    logger.warning(
                        "Foundry rejected previous_response_id; retrying once without conversation state: "
                        "conversation=%s rejected_previous_response_id=%s",
                        conversation_id,
                        previous_response_id,
                    )
                    async for retry_payload in _stream_response(
                        project_endpoint=project_endpoint,
                        agent_name=agent_name,
                        user_message=user_message,
                        previous_response_id=None,
                        approval_inputs=None,
                        conversation_id=conversation_id,
                        outbound_headers=outbound_headers,
                        metadata=metadata,
                        output_items=output_items,
                        tool_choice=tool_choice,
                        conversations=conversations, reset_conversation=reset_conversation, diagnostics=diagnostics,
                    ):
                        yield retry_payload
                    return
                msg = (
                    f"{msg}\n\nConversation state was reset because Foundry rejected "
                    "the stored previous_response_id. Please send the message again."
                )
            yield _sse({"type": "error", "message": msg})

        except Exception as exc:
            msg = f"Foundry request failed ({type(exc).__name__})."
            logger.error(msg)
            yield _sse({"type": "error", "message": msg})



async def _create_conversation(endpoint, agent, headers):
    url = f"{endpoint.rstrip('/')}/agents/{quote(agent, safe='')}/endpoint/protocols/openai/conversations?api-version=v1"
    async with telemetry.http_client(timeout=30) as client:
        response = await client.post(url, headers=headers, json={})
        response.raise_for_status()
        conversation_id = response.json().get("id")
        if not isinstance(conversation_id, str) or not conversation_id.startswith("conv_"):
            raise ValueError("invalid_conversation_id")
        return conversation_id
