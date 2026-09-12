"""購買Hosted Agentへの1ターンを実行し、同意待ちと観測結果を管理する。"""
import asyncio
import os
from opentelemetry.trace import StatusCode
import telemetry
import auth
import foundry_client
import logging

logger = logging.getLogger(__name__)


def public_event(event):
    event = dict(event)
    if "arguments" in event:
        event["arguments"] = "{}"
    if "pendingApprovals" in event:
        event["pendingApprovals"] = [public_event(item) for item in event["pendingApprovals"]]
    return event


async def run(job_id, request, state, job, state_key, *, append_event, stream_response, get_config):
    """状態と必要な関数を受け取り、serverモジュールに依存せずジョブを実行する。"""
    flow = state["flow"]
    user = auth._get_request_user(request)
    job["status"] = "running"
    with telemetry.job_context(user["storage_key"], flow["case_id"], flow["turn"], email=user["email"]), telemetry.observe("web.chat.job") as span:
        job["traceId"] = f"{span.get_span_context().trace_id:032x}"
        outcome = "failed"
        try:
            mode = os.getenv("FOUNDRY_USER_AUTH_MODE", "refresh_token").strip().lower()
            if state.get("auth_mode", mode) != mode:
                raise ValueError("start_new_conversation_after_auth_mode_change")
            state["auth_mode"] = mode
            # Managed Agent境界でTraceが分かれても追跡できるよう、相関IDも渡す。
            # 認証済み氏名やTokenをmetadataへ入れない。
            metadata = {"test.case.id": flow["case_id"],
                        "app.turn.number": str(flow["turn"]), "app.web.trace_id": job["traceId"]}
            with telemetry.observe("auth.foundry.token", **{"app.auth.mode": mode}):
                headers = await auth._build_outbound_headers(request, auth_mode=mode)
            endpoint, agent = get_config()
            with telemetry.observe("procurement.agent.invoke", **{"app.auth.mode": mode}) as invocation:
                if not state.get("foundry_conversation_id"):
                    state["foundry_conversation_id"] = await foundry_client._create_conversation(endpoint, agent, headers)
                for current in (span, invocation):
                    current.set_attribute("gen_ai.conversation.id", state["foundry_conversation_id"])
                job["foundryConversationId"] = state["foundry_conversation_id"]
                completed, failed = False, False
                async for payload in stream_response(
                    project_endpoint=endpoint, agent_name=agent,
                    # 接続先Agentの同意・承認イベントを扱う。購買や名前取得の判定はしない。
                    user_message=flow["message"], previous_response_id=None,
                    approval_inputs=flow.get("approval_inputs"),
                    conversation_id=state_key, outbound_headers=headers, metadata=metadata,
                    foundry_conversation_id=state["foundry_conversation_id"],
                    diagnostics=job["sentHeaders"],
                ):
                    event = foundry_client._parse_sse_payload(payload)
                    if not event:
                        continue
                    if event.get("responseId"):
                        job["responseId"] = event["responseId"]
                        for current in (span, invocation):
                            current.set_attribute("gen_ai.response.id", event["responseId"])
                    if event["type"] in {"oauth_consent_required", "mcp_approval_required"}:
                        # 同意・承認待ちは失敗ではなく、利用者操作による再開待ち。
                        outcome = event["type"]
                        await append_event(job_id, public_event(event))
                        return
                    if event["type"] == "error":
                        # 例外ではなくエラーイベントでも、親ジョブをERRORにする。
                        failed = True
                        span.set_status(StatusCode.ERROR)
                        invocation.set_status(StatusCode.ERROR)
                    if event["type"] == "done" and failed:
                        continue
                    completed = completed or event["type"] == "done"
                    await append_event(job_id, public_event(event))
                if not completed:
                    invocation.set_status(StatusCode.ERROR)
                    span.set_status(StatusCode.ERROR)
                outcome = "completed" if completed and not failed else "failed"
            state.pop("flow", None)
        except asyncio.CancelledError:
            outcome = "cancelled"
            state.pop("flow", None)
            job["status"] = "cancelled"
            span.set_attribute("app.cancelled", True)
            raise
        except Exception as exc:
            state.pop("flow", None)
            span.set_attribute("error.type", type(exc).__name__)
            span.set_status(StatusCode.ERROR)
            await append_event(job_id, {"type": "error", "message": "購買Agentの呼び出しに失敗しました。接続設定と実行状況を確認してください。"})
        finally:
            # 正常完了・失敗・同意待ち・キャンセルを、本文なしで区別できるようにする。
            span.set_attribute("app.operation.outcome", outcome)
            logger.info("Web job finished: outcome=%s", outcome)
            state.pop("active_job", None)
