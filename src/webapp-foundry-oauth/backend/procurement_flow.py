"""Single-target OAuth wrapper for the procurement Hosted Agent."""
import asyncio
import os
from urllib.parse import quote
from opentelemetry.trace import StatusCode
import telemetry


def public_event(event):
    event = dict(event)
    if "arguments" in event:
        event["arguments"] = "{}"
    if "pendingApprovals" in event:
        event["pendingApprovals"] = [public_event(item) for item in event["pendingApprovals"]]
    return event


async def _create_conversation(endpoint, agent, headers):
    url = f"{endpoint.rstrip('/')}/agents/{quote(agent, safe='')}/endpoint/protocols/openai/conversations?api-version=v1"
    async with telemetry.http_client(timeout=30) as client:
        response = await client.post(url, headers=headers, json={})
        response.raise_for_status()
        conversation_id = response.json().get("id")
        if not isinstance(conversation_id, str) or not conversation_id.startswith("conv_"):
            raise ValueError("invalid_conversation_id")
        return conversation_id


async def run(api, job_id, request, state_key, *, skip_identity=False):
    state = api._conversations[state_key]
    flow, job = state["flow"], api._jobs[job_id]
    user = api._get_request_user(request)
    job["status"] = "running"
    with telemetry.job_context(user["storage_key"], flow["case_id"], flow["turn"]), telemetry.observe("web.chat.job") as span:
        job["traceId"] = f"{span.get_span_context().trace_id:032x}"
        try:
            lookup = flow["lookup"] and not skip_identity
            mode = os.getenv("FOUNDRY_USER_AUTH_MODE", "refresh_token").strip().lower()
            if lookup and mode not in {"refresh_token", "refresh", "obo", "on_behalf_of", "forward", "easyauth"}:
                raise ValueError("identity_requires_delegated_auth")
            if state.get("auth_mode", mode) != mode:
                raise ValueError("start_new_conversation_after_auth_mode_change")
            state["auth_mode"] = mode
            metadata = {"app.user.id": user["storage_key"], "test.case.id": flow["case_id"],
                        "app.turn.number": str(flow["turn"]), "app.web.trace_id": job["traceId"],
                        "app.identity.lookup": str(lookup).lower()}
            with telemetry.observe("auth.foundry.token", **{"app.auth.mode": mode}):
                headers = await api._build_outbound_headers(request, auth_mode=mode)
            endpoint, agent = api._get_foundry_config()
            with telemetry.observe("procurement.agent.invoke", **{"app.auth.mode": mode}) as invocation:
                if not state.get("foundry_conversation_id"):
                    state["foundry_conversation_id"] = await _create_conversation(endpoint, agent, headers)
                invocation.set_attribute("gen_ai.conversation.id", state["foundry_conversation_id"])
                completed, failed = False, False
                async for payload in api._stream_response(
                    project_endpoint=endpoint, agent_name=agent,
                    # Identity consent pauses before procurement runs. Replay the
                    # original user request on the same Foundry conversation.
                    user_message=flow["message"], previous_response_id=None,
                    approval_inputs=flow.get("approval_inputs") if not skip_identity else None,
                    conversation_id=state_key, outbound_headers=headers, metadata=metadata,
                    foundry_conversation_id=state["foundry_conversation_id"],
                ):
                    event = api._parse_sse_payload(payload)
                    if not event:
                        continue
                    if event.get("responseId"):
                        job["procurementResponseId"] = event["responseId"]
                        invocation.set_attribute("gen_ai.response.id", event["responseId"])
                    if event["type"] in {"oauth_consent_required", "mcp_approval_required"}:
                        job["identityStatus"] = "WAITING_USER"
                        await api._append_job_event(job_id, public_event(event))
                        return
                    if event["type"] == "error":
                        failed = True
                        invocation.set_status(StatusCode.ERROR)
                    if event["type"] == "done" and failed:
                        continue
                    completed = completed or event["type"] == "done"
                    await api._append_job_event(job_id, public_event(event))
                if not completed:
                    invocation.set_status(StatusCode.ERROR)
            state.pop("flow", None)
        except asyncio.CancelledError:
            state.pop("flow", None)
            job["status"] = "cancelled"
            span.set_attribute("app.cancelled", True)
            raise
        except Exception as exc:
            state.pop("flow", None)
            span.set_attribute("error.type", type(exc).__name__)
            span.set_status(StatusCode.ERROR)
            await api._append_job_event(job_id, {"type": "error", "message": "購買Agentの呼び出しに失敗しました。接続設定と実行状況を確認してください。"})
        finally:
            state.pop("active_job", None)
