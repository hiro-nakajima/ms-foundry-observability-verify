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

import base64
import hashlib
import json
import logging
import os
import asyncio
import time
import uuid
from pathlib import Path
from urllib.parse import quote
from typing import Any, AsyncIterator, Optional

import httpx
import msal
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent
STATIC_DIR = BACKEND_DIR / "static"


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
    arguments = item.get("arguments", "")
    if arguments and not isinstance(arguments, str):
        arguments = json.dumps(arguments, ensure_ascii=False)

    return {
        "callId": str(call_id),
        "toolName": str(tool_name),
        "toolType": item_type,
        "detail": detail,
        "arguments": arguments or "",
    }


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
    }


def _public_conversation_state(conversation_id: str, state: Optional[dict[str, Any]]) -> dict[str, Any]:
    state = state or {}
    pending_approvals = [
        {
            "approvalRequestId": item.get("id", ""),
            "serverLabel": item.get("serverLabel", ""),
            "toolName": item.get("toolName", ""),
            "arguments": item.get("arguments", "{}"),
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
    conversationId: str
    userMessage: str


class ContinueRequest(BaseModel):
    conversationId: str
    approve: bool = True
    approvalRequestIds: Optional[list[str]] = None


# ──────────────────────────────────────────────────────────────────────────────
# FastAPI app
# ──────────────────────────────────────────────────────────────────────────────
app = FastAPI(title="Foundry OAuth UI Backend", version="1.0.0")

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


# ──────────────────────────────────────────────────────────────────────────────
# Auth helper
# ──────────────────────────────────────────────────────────────────────────────

def _safe_b64decode_json(value: str) -> dict[str, Any]:
    raw = (value or "").strip()
    if not raw:
        return {}
    try:
        raw += "=" * (-len(raw) % 4)
        decoded = base64.b64decode(raw).decode("utf-8")
        data = json.loads(decoded)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}



def _decode_jwt_payload(token: str) -> dict[str, Any]:
    raw = (token or "").strip()
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    parts = raw.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload.encode("utf-8"))
        data = json.loads(decoded)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _sanitize_token_claims(claims: dict[str, Any]) -> dict[str, Any]:
    # This reference path must not place raw Entra claims in App Service logs.
    return {
        "audience_present": bool(claims.get("aud")),
        "issuer_present": bool(claims.get("iss")),
        "tenant_present": bool(claims.get("tid")),
        "user_present": bool(claims.get("oid") or claims.get("sub")),
        "scopes_present": bool(claims.get("scp")),
        "roles_present": bool(claims.get("roles")),
        "client_present": bool(claims.get("azp") or claims.get("appid")),
        "expiry_present": claims.get("exp") is not None,
    }


def _extract_claim(principal: dict[str, Any], *claim_types: str) -> str:
    claims = principal.get("claims")
    if not isinstance(claims, list):
        return ""
    wanted = set(claim_types)
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        typ = str(claim.get("typ") or claim.get("type") or "")
        if typ in wanted:
            value = claim.get("val") or claim.get("value") or ""
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _hash_user_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _get_request_user(request: Request) -> dict[str, Any]:
    """Resolve the App Service EasyAuth user for request-scoped state isolation."""
    principal = _safe_b64decode_json(request.headers.get("x-ms-client-principal", ""))
    user_id = (
        request.headers.get("x-ms-client-principal-id", "").strip()
        or str(principal.get("userId") or "").strip()
        or _extract_claim(
            principal,
            "http://schemas.microsoft.com/identity/claims/objectidentifier",
            "oid",
        )
    )
    user_name = (
        request.headers.get("x-ms-client-principal-name", "").strip()
        or str(principal.get("userDetails") or "").strip()
        or _extract_claim(
            principal,
            "preferred_username",
            "upn",
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/upn",
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
        )
    )
    authenticated = bool(user_id)
    if not user_id:
        # Local development fallback. In Azure App Service, EasyAuth should
        # populate x-ms-client-principal-id before these API routes are reached.
        user_id = "local-anonymous-user"
        user_name = user_name or "local-anonymous-user"

    storage_key = _hash_user_key(user_id)
    return {
        "id": user_id,
        "name": user_name or "unknown",
        "storage_key": storage_key,
        "authenticated": authenticated,
    }


def _conversation_state_key(conversation_id: str, user: dict[str, Any]) -> str:
    return f"{user['storage_key']}:{conversation_id}"



async def _fetch_easyauth_me(request: Request) -> list[dict[str, Any]]:
    cookie = request.headers.get("cookie", "").strip()
    if not cookie:
        return []
    host = os.environ.get("WEBSITE_HOSTNAME", "").strip() or request.headers.get("host", "").strip()
    if not host:
        return []
    url = f"https://{host}/.auth/me"
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            response = await client.get(url, headers={"Cookie": cookie, "Accept": "application/json"})
        if response.status_code != 200:
            logger.warning("/.auth/me returned HTTP %s", response.status_code)
            return []
        data = response.json()
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            return [data]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch /.auth/me: %s", exc)
    return []


async def _refresh_easyauth_tokens(request: Request) -> None:
    cookie = request.headers.get("cookie", "").strip()
    if not cookie:
        return
    host = os.environ.get("WEBSITE_HOSTNAME", "").strip() or request.headers.get("host", "").strip()
    if not host:
        return
    url = f"https://{host}/.auth/refresh"
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            response = await client.get(url, headers={"Cookie": cookie, "Accept": "application/json"})
        logger.info("/.auth/refresh returned HTTP %s", response.status_code)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to call /.auth/refresh: %s", exc)


async def _get_easyauth_refresh_token(request: Request) -> str:
    token = request.headers.get("x-ms-token-aad-refresh-token", "").strip()
    if token:
        return token

    auth_me = await _fetch_easyauth_me(request)
    for item in auth_me:
        token = str(item.get("refresh_token") or item.get("refreshToken") or "").strip()
        if token:
            logger.info("Using EasyAuth refresh token from /.auth/me entry provider=%s", item.get("provider_name"))
            return token

    await _refresh_easyauth_tokens(request)
    auth_me = await _fetch_easyauth_me(request)
    for item in auth_me:
        token = str(item.get("refresh_token") or item.get("refreshToken") or "").strip()
        if token:
            logger.info("Using EasyAuth refresh token from /.auth/me after refresh provider=%s", item.get("provider_name"))
            return token

    available_keys = sorted({key for item in auth_me for key in item.keys()})
    logger.warning("EasyAuth refresh token not found. /.auth/me keys=%s", available_keys)
    raise HTTPException(
        status_code=401,
        detail=(
            "EasyAuth refresh token is not available in headers or /.auth/me. "
            "Token store is enabled, but the current EasyAuth session did not expose a refresh token."
        ),
    )


def _get_easyauth_access_token(request: Request) -> str:
    token = request.headers.get("x-ms-token-aad-access-token", "").strip()
    if not token:
        raise HTTPException(
            status_code=401,
            detail=(
                "EasyAuth access token is not available. Ensure App Service Authentication token store is enabled "
                "and the request is authenticated with Microsoft Entra ID."
            ),
        )

    user = _get_request_user(request)
    claims = _decode_jwt_payload(token)
    principal_oid = user.get("id", "")
    token_oid = str(claims.get("oid") or claims.get("sub") or "").strip()
    if principal_oid and token_oid and principal_oid != token_oid:
        logger.error(
            "EasyAuth principal does not match access token claims: principal=%s token_claims=%s",
            _hash_user_key(principal_oid),
            _sanitize_token_claims(claims),
        )
        raise HTTPException(status_code=401, detail="EasyAuth user does not match access token user.")
    logger.info("EasyAuth access token claims: %s", _sanitize_token_claims(claims))
    return token


def _get_foundry_obo_config() -> tuple[str, str, str, list[str]]:
    tenant_id = (
        os.environ.get("FOUNDRY_OBO_TENANT_ID", "").strip()
        or os.environ.get("ENTRA_TENANT_ID", "").strip()
        or os.environ.get("WEBSITE_AUTH_AAD_ALLOWED_TENANTS", "").split(",")[0].strip()
    )
    client_id = (
        os.environ.get("FOUNDRY_OBO_CLIENT_ID", "").strip()
        or os.environ.get("WEBAPP_ENTRA_CLIENT_ID", "").strip()
        or os.environ.get("ENTRA_CLIENT_ID", "").strip()
    )
    client_secret = (
        os.environ.get("FOUNDRY_OBO_CLIENT_SECRET", "").strip()
        or os.environ.get("WEBAPP_ENTRA_CLIENT_SECRET", "").strip()
        or os.environ.get("MICROSOFT_PROVIDER_AUTHENTICATION_SECRET", "").strip()
    )
    scopes_raw = os.environ.get("FOUNDRY_TOKEN_SCOPES", "https://ai.azure.com/.default")
    scopes = [item.strip() for item in scopes_raw.split(",") if item.strip()]
    if not tenant_id or not client_id or not client_secret or not scopes:
        raise HTTPException(
            status_code=500,
            detail="FOUNDRY OBO configuration is incomplete. Set tenant/client/secret and FOUNDRY_TOKEN_SCOPES.",
        )
    return tenant_id, client_id, client_secret, scopes



def _acquire_foundry_token_by_refresh_token(refresh_token: str) -> str:
    tenant_id, client_id, client_secret, scopes = _get_foundry_obo_config()
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    client = msal.ConfidentialClientApplication(
        client_id=client_id,
        client_credential=client_secret,
        authority=authority,
    )
    result = client.acquire_token_by_refresh_token(refresh_token=refresh_token, scopes=scopes)
    token = result.get("access_token")
    if token:
        logger.info(
            "Acquired Foundry user delegated token via EasyAuth refresh token: scopes=%s claims=%s",
            scopes,
            _sanitize_token_claims(_decode_jwt_payload(token)),
        )
        return token
    logger.error(
        "Failed to acquire Foundry token by refresh token: error=%s suberror=%s correlation_id=%s",
        result.get("error"),
        result.get("suberror"),
        result.get("correlation_id"),
    )
    raise HTTPException(
        status_code=502,
        detail=f"Failed to acquire Foundry token by refresh token: {result.get('error_description') or result.get('error')}",
    )


def _acquire_foundry_token_on_behalf_of(user_assertion: str) -> str:
    tenant_id, client_id, client_secret, scopes = _get_foundry_obo_config()
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    client = msal.ConfidentialClientApplication(
        client_id=client_id,
        client_credential=client_secret,
        authority=authority,
    )
    result = client.acquire_token_on_behalf_of(user_assertion=user_assertion, scopes=scopes)
    token = result.get("access_token")
    if token:
        logger.info(
            "Acquired Foundry user delegated token via OBO: scopes=%s claims=%s",
            scopes,
            _sanitize_token_claims(_decode_jwt_payload(token)),
        )
        return token
    logger.error(
        "Failed to acquire Foundry token via OBO: error=%s suberror=%s correlation_id=%s",
        result.get("error"),
        result.get("suberror"),
        result.get("correlation_id"),
    )
    raise HTTPException(
        status_code=502,
        detail=f"Failed to acquire Foundry token via OBO: {result.get('error_description') or result.get('error')}",
    )


async def _get_token() -> str:
    """Acquire Azure access token for the Foundry scope (ai.azure.com)."""
    credential = DefaultAzureCredential()
    try:
        token = await credential.get_token("https://ai.azure.com/.default")
        return token.token
    finally:
        await credential.close()


async def _build_outbound_headers(request: Request) -> dict[str, str]:
    """Build outbound headers for the Responses API call.

    By default, calls Foundry/APIM with a user delegated token derived from
    the current App Service EasyAuth user. This keeps Foundry OAuth Identity
    Passthrough aligned with the signed-in App Service user.
    """
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "Foundry-Features": "AgentEndpoints=V1Preview",
    }
    apim_subscription_key = os.environ.get("APIM_SUBSCRIPTION_KEY", "").strip()
    if apim_subscription_key:
        headers["Ocp-Apim-Subscription-Key"] = apim_subscription_key

    auth_mode = os.environ.get("FOUNDRY_USER_AUTH_MODE", "obo").strip().lower()
    if auth_mode in ("refresh_token", "refresh"):
        # EasyAuth's access token can be for Microsoft Graph depending on the
        # provider configuration. Use the EasyAuth refresh token to mint a
        # fresh user delegated token for Foundry instead.
        _get_easyauth_access_token(request)  # validates/logs current EasyAuth user claims
        refresh_token = await _get_easyauth_refresh_token(request)
        foundry_token = _acquire_foundry_token_by_refresh_token(refresh_token)
        headers["Authorization"] = f"Bearer {foundry_token}"
        return headers

    if auth_mode in ("obo", "on_behalf_of"):
        user_token = _get_easyauth_access_token(request)
        foundry_token = _acquire_foundry_token_on_behalf_of(user_token)
        headers["Authorization"] = f"Bearer {foundry_token}"
        return headers

    if auth_mode in ("forward", "easyauth"):
        user_token = _get_easyauth_access_token(request)
        logger.info(
            "Forwarding EasyAuth access token to Foundry/APIM: claims=%s",
            _sanitize_token_claims(_decode_jwt_payload(user_token)),
        )
        headers["Authorization"] = f"Bearer {user_token}"
        return headers

    if auth_mode in ("managed_identity", "mi", "default_credential"):
        token = await _get_token()
        headers["Authorization"] = f"Bearer {token}"
        return headers

    raise HTTPException(status_code=500, detail=f"Unsupported FOUNDRY_USER_AUTH_MODE: {auth_mode}")


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
# SSE streaming from Foundry Responses API
# ──────────────────────────────────────────────────────────────────────────────
async def _stream_response(
    project_endpoint: str,
    agent_name: str,
    user_message: Optional[str],
    previous_response_id: Optional[str],
    approval_inputs: Optional[list[dict[str, Any]]],
    conversation_id: str,
    outbound_headers: dict[str, str],
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

    if previous_response_id:
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
    existing_pending_consent = _conversations.get(conversation_id, {}).get(
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
    async with httpx.AsyncClient(timeout=120.0) as client:
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
                        # Keep reading until EOF so proxies observe a normally
                        # drained response instead of a client-side close.
                        continue

                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        logger.debug("Non-JSON SSE data (skipped): %s", data_str[:120])
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
                    elif event_type == "response.completed":
                        resp_obj = data.get("response", {})
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
                        err = data.get("error", data)
                        msg = (
                            err.get("message", str(err))
                            if isinstance(err, dict)
                            else str(err)
                        )
                        logger.error("Foundry error event: %s", msg)
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

            state = _conversations.setdefault(
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
            try:
                body_preview = (await exc.response.aread()).decode("utf-8", "ignore")[:1000]
            except Exception:
                body_preview = ""
            msg = f"Foundry API HTTP {exc.response.status_code}: {body_preview}"
            logger.error(msg)
            if exc.response.status_code == 400 and previous_response_id:
                _reset_conversation_state(
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
                    ):
                        yield retry_payload
                    return
                msg = (
                    f"{msg}\n\nConversation state was reset because Foundry rejected "
                    "the stored previous_response_id. Please send the message again."
                )
            yield _sse({"type": "error", "message": msg})

        except Exception as exc:
            msg = f"Unexpected error: {exc}"
            logger.exception(msg)
            yield _sse({"type": "error", "message": msg})


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
    user = _get_request_user(request)
    return {
        "authenticated": user["authenticated"],
        "name": user["name"],
        "storageKey": user["storage_key"],
    }


@app.get("/api/conversations/{conversation_id}/state")
async def get_conversation_state(conversation_id: str, request: Request):
    user = _get_request_user(request)
    state_key = _conversation_state_key(conversation_id, user)
    return _public_conversation_state(
        conversation_id,
        _conversations.get(state_key),
    )


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation_state(conversation_id: str, request: Request):
    user = _get_request_user(request)
    state_key = _conversation_state_key(conversation_id, user)
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
        if next_status:
            job["status"] = next_status
        elif job["status"] == "queued":
            job["status"] = "running"
        if event.get("type") == "error":
            job["error"] = event.get("message") or "Unknown error"


async def _run_response_job(
    job_id: str,
    project_endpoint: str,
    agent_name: str,
    user_message: Optional[str],
    previous_response_id: Optional[str],
    approval_inputs: Optional[list[dict[str, Any]]],
    conversation_id: str,
    conversation_state_key: str,
    outbound_headers: dict[str, str],
) -> None:
    async with _jobs_lock:
        job = _jobs.get(job_id)
        if job:
            job["status"] = "running"
            job["updatedAt"] = time.time()

    try:
        async for payload in _stream_response(
            project_endpoint=project_endpoint,
            agent_name=agent_name,
            user_message=user_message,
            previous_response_id=previous_response_id,
            approval_inputs=approval_inputs,
            conversation_id=conversation_state_key,
            outbound_headers=outbound_headers,
        ):
            event = _parse_sse_payload(payload)
            if not event:
                continue
            await _append_job_event(job_id, event)
    except asyncio.CancelledError:
        await _append_job_event(job_id, {"type": "error", "message": "Request was cancelled."})
        async with _jobs_lock:
            job = _jobs.get(job_id)
            if job:
                job["status"] = "cancelled"
                job["updatedAt"] = time.time()
        raise
    except Exception as exc:
        logger.exception("Chat job failed: job_id=%s", job_id)
        await _append_job_event(job_id, {"type": "error", "message": str(exc)})


async def _create_response_job(
    conversation_id: str,
    conversation_state_key: str,
    user_message: Optional[str],
    approval_inputs: Optional[list[dict[str, Any]]],
    previous_response_id: Optional[str],
    request: Request,
) -> dict[str, Any]:
    await _cleanup_old_jobs()
    project_endpoint, agent_name = _get_foundry_config()
    outbound_headers = await _build_outbound_headers(request)
    job_id = uuid.uuid4().hex
    now = time.time()
    job: dict[str, Any] = {
        "id": job_id,
        "conversationId": conversation_id,
        "ownerKey": conversation_state_key.split(":", 1)[0],
        "status": "queued",
        "events": [],
        "responseId": None,
        "error": None,
        "createdAt": now,
        "updatedAt": now,
        "task": None,
    }
    async with _jobs_lock:
        _jobs[job_id] = job

    task = asyncio.create_task(
        _run_response_job(
            job_id=job_id,
            project_endpoint=project_endpoint,
            agent_name=agent_name,
            user_message=user_message,
            previous_response_id=previous_response_id,
            approval_inputs=approval_inputs,
            conversation_id=conversation_id,
            conversation_state_key=conversation_state_key,
            outbound_headers=outbound_headers,
        )
    )
    async with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id]["task"] = task
    return _public_job(job, 0)


@app.post("/api/chat")
async def chat(req: ChatRequest, request: Request):
    """
    Start a new conversation turn (or continue an existing one).

    If the conversation already has a `previous_response_id` stored
    (from a prior turn), it is included automatically so the agent
    maintains context across turns.

    Returns: JSON job metadata. Poll /api/jobs/{jobId} for events.
    """
    user = _get_request_user(request)
    conversation_state_key = _conversation_state_key(req.conversationId, user)
    state = _conversations.get(conversation_state_key, {})
    if state.get("pending_approvals"):
        raise HTTPException(
            status_code=409,
            detail=(
                "This conversation is waiting for MCP approval. "
                "Use /api/continue to resume it."
            ),
        )
    if state.get("awaiting_consent"):
        raise HTTPException(
            status_code=409,
            detail=(
                "This conversation is waiting for OAuth consent. "
                "Complete consent and use /api/continue to resume it."
            ),
        )
    previous_response_id = state.get("previous_response_id")

    job = await _create_response_job(
        conversation_id=req.conversationId,
        conversation_state_key=conversation_state_key,
        user_message=req.userMessage,
        approval_inputs=None,
        previous_response_id=previous_response_id,
        request=request,
    )
    return JSONResponse(job, status_code=202)


@app.post("/api/continue")
async def continue_after_consent(req: ContinueRequest, request: Request):
    """
    Resume a paused conversation after the user has completed OAuth consent.

    The stored `previous_response_id` is sent to Foundry so the agent can
    pick up exactly where it left off before requesting consent.

    Reference:
      https://learn.microsoft.com/azure/ai-foundry/agents/how-to/mcp-authentication

    Returns: JSON job metadata. Poll /api/jobs/{jobId} for events.
    """
    user = _get_request_user(request)
    conversation_state_key = _conversation_state_key(req.conversationId, user)
    state = _conversations.get(conversation_state_key)
    if not state:
        raise HTTPException(
            status_code=404,
            detail=f"No conversation found for conversationId={req.conversationId}",
        )

    previous_response_id = state.get("previous_response_id")
    if not previous_response_id:
        raise HTTPException(
            status_code=400,
            detail="No previous_response_id stored; cannot continue.",
        )

    approval_inputs: Optional[list[dict[str, Any]]] = None
    pending_approvals = state.get("pending_approvals", [])
    if pending_approvals:
        selected_ids = req.approvalRequestIds or [
            item.get("id") for item in pending_approvals if item.get("id")
        ]
        if not selected_ids:
            raise HTTPException(
                status_code=400,
                detail="No approval_request_id available for pending MCP approval.",
            )
        approval_inputs = [
            {
                "type": "mcp_approval_response",
                "approve": req.approve,
                "approval_request_id": approval_id,
            }
            for approval_id in selected_ids
        ]
        logger.info(
            "Sending MCP approval response(s): conversation=%s approve=%s count=%d",
            req.conversationId,
            req.approve,
            len(approval_inputs),
        )

    logger.info(
        "Continuing conversation %s with previous_response_id=%s",
        req.conversationId,
        previous_response_id,
    )

    job = await _create_response_job(
        conversation_id=req.conversationId,
        conversation_state_key=conversation_state_key,
        user_message=None,
        approval_inputs=approval_inputs,
        previous_response_id=previous_response_id,
        request=request,
    )
    return JSONResponse(job, status_code=202)


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str, request: Request, cursor: int = 0):
    owner_key = _get_request_user(request)["storage_key"]
    async with _jobs_lock:
        job = _jobs.get(job_id)
        if not job or job.get("ownerKey") != owner_key:
            raise HTTPException(status_code=404, detail=f"No job found for jobId={job_id}")
        return _public_job(job, cursor)


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, request: Request):
    owner_key = _get_request_user(request)["storage_key"]
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
                if not job or job.get("ownerKey") != _get_request_user(request)["storage_key"]:
                    yield _sse({"type": "error", "message": f"No job found for jobId={job_id}"})
                    return
                events = job.get("events", [])
                new_events = events[current_cursor:]
                current_cursor = len(events)
                status = job["status"]

            for event in new_events:
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
