"""
Foundry Agent OAuth UI — Backend Server

FastAPI server with background response jobs that:
  - Proxies Foundry Agent endpoint Responses API (agents/{agent}/endpoint/protocols/openai/responses?api-version=v1, streaming) from a job
  - Detects `oauth_consent_request` events from MCP tool calls
  - Persists conversation state (previous_response_id) in memory
  - Exposes /api/chat  (start a job for a chat turn)
  - Exposes /api/continue (start a job to resume after OAuth consent)
  - Exposes /api/jobs/{jobId} for polling job events

SSE events sent to the frontend
────────────────────────────────
  {"type": "text.delta",            "delta": "..."}
  {"type": "tool.start",            "toolName": "...", "callId": "..."}
  {"type": "tool.end",              "toolName": "...", "callId": "..."}
  {"type": "tool.error",            "toolName": "...", "callId": "...", "error": "..."}
    {"type": "mcp_approval_required", "approvalRequestId": "...",
                                                                        "serverLabel": "...", "toolName": "..."}
  {"type": "oauth_consent_required","consentLink": "...",
                                    "responseId": "...", "connectionName": "..."}
  {"type": "done",                  "responseId": "..."}
  {"type": "error",                 "message": "..."}

References
──────────
  MCP server authentication / OAuth Identity Passthrough:
    https://learn.microsoft.com/azure/ai-foundry/agents/how-to/mcp-authentication
  Foundry Agent endpoint migration:
    https://learn.microsoft.com/azure/foundry/agents/how-to/migrate-agent-applications
"""

from __future__ import annotations

import json
import logging
import os
import asyncio
from functools import partial
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
import telemetry
import auth
import foundry_client
import procurement_flow
from foundry_client import _sse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent
STATIC_DIR = BACKEND_DIR / "static"


def _event_status(event: dict[str, Any]) -> Optional[str]:
    event_type = event.get("type")
    if event_type == "done":
        return "completed"
    if event_type == "error":
        return "failed"
    if event_type == "mcp_approval_required":
        return "approval_required"
    if event_type == "oauth_consent_required":
        return "consent_required"
    return None


def _public_job(job: dict[str, Any], cursor: int = 0) -> dict[str, Any]:
    events = job.get("events", [])
    safe_cursor = max(0, min(cursor, len(events)))
    return {
        "jobId": job["id"],
        "conversationId": job["conversationId"],
        "status": job["status"],
        "events": events[safe_cursor:],
        "nextCursor": len(events),
        "responseId": job.get("responseId"),
        "error": job.get("error"),
        "createdAt": job["createdAt"],
        "updatedAt": job["updatedAt"],
        # 診断情報はサーバーが生成した値だけ。認証ヘッダーやTokenは含めない。
        "diagnostics": {
            "traceId": job.get("traceId"), "responseId": job.get("responseId"),
            "webConversationId": job["conversationId"],
            "foundryConversationId": job.get("foundryConversationId"),
            "testCaseId": job.get("testCaseId"), "turn": job.get("turn"),
            "status": job["status"], "sentHeaders": dict(job.get("sentHeaders", {})),
        },
        **{key: job.get(key) for key in ("testCaseId", "turn", "traceId")},
    }


def _public_conversation_state(conversation_id: str, state: Optional[dict[str, Any]]) -> dict[str, Any]:
    state = state or {}
    pending_approvals = [
        {
            "approvalRequestId": item.get("id", ""),
            "serverLabel": item.get("serverLabel", ""),
            "toolName": item.get("toolName", ""),
            "arguments": "{}",
        }
        for item in state.get("pending_approvals", [])
    ]
    return {
        "conversationId": conversation_id,
        "hasPreviousResponse": bool(state.get("previous_response_id")),
        "awaitingConsent": bool(state.get("awaiting_consent")),
        "pendingConsent": state.get("pending_consent"),
        "pendingApprovals": pending_approvals,
    }

# ──────────────────────────────────────────────────────────────────────────────
# In-memory conversation state
# conversationId -> {
#   previous_response_id: str | None,
#   pending_approvals: list[dict]
# }
#
# NOTE: This is intentionally simple for hands-on purposes.
#       In production use Redis, a DB, or a session store.
# ──────────────────────────────────────────────────────────────────────────────
_conversations: dict[str, dict] = {}
_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = asyncio.Lock()
TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled", "approval_required", "consent_required"}
JOB_RETENTION_SECONDS = int(os.environ.get("JOB_RETENTION_SECONDS", "1800"))


def _reset_conversation_state(conversation_state_key: str, conversation_id: str, reason: str) -> None:
    """Drop server-side response state so the next turn can start cleanly."""
    removed = _conversations.pop(conversation_state_key, None)
    if removed is not None:
        logger.warning(
            "Conversation state reset: conversation=%s owner=%s reason=%s",
            conversation_id,
            conversation_state_key.split(":", 1)[0],
            reason,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Pydantic models
# ──────────────────────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversationId: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    userMessage: str = Field(min_length=1, max_length=8000)


class ContinueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversationId: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    approve: bool = True
    approvalRequestIds: Optional[list[str]] = None


# ──────────────────────────────────────────────────────────────────────────────
# FastAPI app
# ──────────────────────────────────────────────────────────────────────────────
app = FastAPI(title="Foundry OAuth UI Backend", version="2.0.0", lifespan=telemetry.lifespan)

app.add_middleware(
    CORSMiddleware,
    # Allow the Next.js dev server and any additional origins configured via env
    allow_origins=os.environ.get(
        "CORS_ORIGINS", "http://localhost:8000,http://localhost:3000"
    ).split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def authenticated_api(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        user = auth._get_request_user(request)
        if not user["authenticated"] and os.getenv("WEBUI_ALLOW_ANONYMOUS") != "true":
            return JSONResponse({"detail": "Sign in with App Service Authentication."}, status_code=401)
        origin = request.headers.get("origin")
        if request.method in {"POST", "DELETE"} and (
            request.headers.get("sec-fetch-site") == "cross-site"
            or (origin and origin.rstrip("/") != os.getenv("WEB_APP_URL", "").rstrip("/"))
        ):
            return JSONResponse({"detail": "Invalid request origin."}, status_code=403)
    return await call_next(request)


# 後から登録したmiddlewareが外側になる。ブラウザー境界を計装より外側に置く。
app.add_middleware(telemetry.Instrumentation)
app.add_middleware(telemetry.BrowserBoundary)


# ──────────────────────────────────────────────────────────────────────────────
# Auth helper
# ──────────────────────────────────────────────────────────────────────────────

def _conversation_state_key(conversation_id: str, user: dict[str, Any]) -> str:
    return f"{user['storage_key']}:{conversation_id}"



def _get_foundry_config() -> tuple[str, str]:
    project_endpoint = os.environ.get("PROJECT_ENDPOINT", "").strip()
    # AGENT_NAME is the preferred setting for the new stable Agent endpoint.
    # AGENT_REFERENCE_NAME is accepted as a deprecated alias so existing App
    # Service settings can be migrated without an immediate rename.
    agent_name = (
        os.environ.get("AGENT_NAME", "").strip()
        or os.environ.get("AGENT_REFERENCE_NAME", "").strip()
    )
    if not project_endpoint or not agent_name:
        raise HTTPException(
            status_code=500,
            detail=(
                "PROJECT_ENDPOINT and AGENT_NAME environment variables must be set. "
                "AGENT_REFERENCE_NAME is accepted only as a deprecated alias."
            ),
        )
    return project_endpoint, agent_name


@app.get("/")
async def serve_index() -> FileResponse:
    """Serve the Python-hosted UI."""
    return FileResponse(STATIC_DIR / "index.html")


# ──────────────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "foundry-oauth-ui-backend",
        "version": "1.0.0",
    }


@app.get("/api/me")
async def me(request: Request):
    user = auth._get_request_user(request)
    return {
        "authenticated": user["authenticated"],
        "name": user["name"],
        "storageKey": user["storage_key"],
    }


@app.get("/api/conversations/{conversation_id}/state")
async def get_conversation_state(conversation_id: str, request: Request):
    user = auth._get_request_user(request)
    state_key = _conversation_state_key(conversation_id, user)
    return _public_conversation_state(
        conversation_id,
        _conversations.get(state_key),
    )


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation_state(conversation_id: str, request: Request):
    user = auth._get_request_user(request)
    state_key = _conversation_state_key(conversation_id, user)
    if _conversations.get(state_key, {}).get("active_job"):
        raise HTTPException(409, "Cancel the running job before clearing history.")
    _reset_conversation_state(state_key, conversation_id, "client_clear_history")
    return {"conversationId": conversation_id, "cleared": True}


async def _cleanup_old_jobs() -> None:
    cutoff = time.time() - JOB_RETENTION_SECONDS
    async with _jobs_lock:
        expired = [
            job_id
            for job_id, job in _jobs.items()
            if job.get("updatedAt", 0) < cutoff and job.get("status") in TERMINAL_JOB_STATUSES
        ]
        for job_id in expired:
            _jobs.pop(job_id, None)


async def _append_job_event(job_id: str, event: dict[str, Any]) -> None:
    now = time.time()
    async with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job["events"].append(event)
        job["updatedAt"] = now
        if event.get("responseId"):
            job["responseId"] = event["responseId"]
        next_status = _event_status(event)
        if next_status and job["status"] not in {"failed", "cancelled"}:
            job["status"] = next_status
        elif job["status"] == "queued":
            job["status"] = "running"
        if event.get("type") == "error":
            job["error"] = event.get("message") or "Unknown error"


async def _create_response_job(
    conversation_id: str, conversation_state_key: str, request: Request,
    *, user_message: str | None = None,
    approval_inputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    await _cleanup_old_jobs()
    job_id, now = uuid.uuid4().hex, time.time()
    async with _jobs_lock:
        state = _conversations.setdefault(conversation_state_key, {})
        if state.get("active_job"):
            raise HTTPException(409, "A job is already running for this conversation.")
        if user_message is not None:
            if state.get("flow"):
                raise HTTPException(409, "Complete the pending consent or approval first.")
            state["turn"] = state.get("turn", 0) + 1
            state["flow"] = {
                "message": user_message, "turn": state["turn"],
                "case_id": "WEB-" + job_id,
            }
        else:
            if not state.get("flow"):
                raise HTTPException(409, "No pending request to continue.")
            state["flow"].update(approval_inputs=approval_inputs)
        state["active_job"] = job_id
        job = {
            "id": job_id, "conversationId": conversation_id,
            "ownerKey": conversation_state_key.split(":", 1)[0],
            "sentHeaders": {},
            "status": "queued", "events": [], "responseId": None, "error": None,
            "createdAt": now, "updatedAt": now, "task": None,
            "testCaseId": state["flow"]["case_id"], "turn": state["flow"]["turn"],
        }
        _jobs[job_id] = job
        # create_taskは現在のOTel Contextを引き継ぐ。実処理はジョブSpanで測る。
        # モジュール全体ではなく、状態と通信・イベント保存の関数を明示的に渡す。
        job["task"] = asyncio.create_task(procurement_flow.run(
            job_id, request, state, job, conversation_state_key,
            append_event=_append_job_event,
            stream_response=partial(foundry_client._stream_response,
                conversations=_conversations, reset_conversation=_reset_conversation_state),
            get_config=_get_foundry_config,
        ))
    return _public_job(job)


@app.post("/api/chat")
async def chat(req: ChatRequest, request: Request):
    user = auth._get_request_user(request)
    if not req.userMessage.strip():
        raise HTTPException(422, "A non-empty message is required.")
    job = await _create_response_job(
        req.conversationId, _conversation_state_key(req.conversationId, user), request,
        user_message=req.userMessage,
    )
    return JSONResponse(job, status_code=202)


@app.post("/api/continue")
async def continue_after_consent(req: ContinueRequest, request: Request):
    user = auth._get_request_user(request)
    state_key = _conversation_state_key(req.conversationId, user)
    conversation_state = _conversations.get(state_key, {})
    pending = conversation_state.get("pending_approvals", [])
    if not conversation_state.get("awaiting_consent") and not pending:
        raise HTTPException(409, "No OAuth consent or MCP approval is pending.")
    selected = req.approvalRequestIds or [p["id"] for p in pending]
    if set(selected) - {p["id"] for p in pending}:
        raise HTTPException(400, "Unknown approval request id.")
    approval_inputs = ([{"type": "mcp_approval_response", "approve": req.approve,
                        "approval_request_id": p} for p in selected] if pending else None)
    job = await _create_response_job(
        req.conversationId, state_key, request, approval_inputs=approval_inputs,
    )
    return JSONResponse(job, status_code=202)


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str, request: Request, cursor: int = 0):
    owner_key = auth._get_request_user(request)["storage_key"]
    async with _jobs_lock:
        job = _jobs.get(job_id)
        if not job or job.get("ownerKey") != owner_key:
            raise HTTPException(status_code=404, detail=f"No job found for jobId={job_id}")
        return _public_job(job, cursor)


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, request: Request):
    owner_key = auth._get_request_user(request)["storage_key"]
    async with _jobs_lock:
        job = _jobs.get(job_id)
        if not job or job.get("ownerKey") != owner_key:
            raise HTTPException(status_code=404, detail=f"No job found for jobId={job_id}")
        if job["status"] in TERMINAL_JOB_STATUSES:
            return _public_job(job, 0)
        task = job.get("task")
        job["status"] = "cancelled"
        job["updatedAt"] = time.time()
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        # A task cancelled before its first instruction cannot run its finally.
        state_key = _conversation_state_key(job["conversationId"], auth._get_request_user(request))
        state = _conversations.get(state_key, {})
        if state.get("active_job") == job_id:
            state.pop("active_job", None)
            state.pop("flow", None)
    return {"jobId": job_id, "status": "cancelled"}


@app.get("/api/jobs/{job_id}/events")
async def stream_job_events(job_id: str, request: Request, cursor: int = 0):
    async def event_stream() -> AsyncIterator[str]:
        current_cursor = max(0, cursor)
        last_heartbeat_at = 0.0
        heartbeat_interval_seconds = 15.0
        while True:
            async with _jobs_lock:
                job = _jobs.get(job_id)
                if not job or job.get("ownerKey") != auth._get_request_user(request)["storage_key"]:
                    yield _sse({"type": "error", "message": f"No job found for jobId={job_id}"})
                    return
                events = job.get("events", [])
                new_events = events[current_cursor:]
                current_cursor = len(events)
                status = job["status"]

            for event in new_events:
                if _event_status(event):
                    # 終端イベントの前に診断値を渡し、SSEだけで終了する画面にも反映する。
                    yield _sse({"type": "diagnostics", "diagnostics": _public_job(job)["diagnostics"]})
                yield _sse(event)

            if status in TERMINAL_JOB_STATUSES:
                return

            now = time.monotonic()
            if not new_events and now - last_heartbeat_at >= heartbeat_interval_seconds:
                last_heartbeat_at = now
                yield ": heartbeat\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
