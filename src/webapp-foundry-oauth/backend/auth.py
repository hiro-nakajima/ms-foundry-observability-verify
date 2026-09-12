"""EasyAuthの本人識別とFoundryトークン取得。Tokenと生claimsはログへ出さない。

配備先はEasyAuthで保護する。ヘッダーの読み取りだけで認証を代替しない。
"""
import asyncio
import base64
import hashlib
import json
import logging
import os
import re
from typing import Any

import msal
from azure.identity.aio import ManagedIdentityCredential
from fastapi import HTTPException, Request
from opentelemetry import trace
import telemetry

logger = logging.getLogger(__name__)


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
    # 値そのものではなく、claimの有無だけを診断ログに残す。
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
    tenant_id = _extract_claim(principal, "tid", "http://schemas.microsoft.com/identity/claims/tenantid")
    authenticated = bool(user_id and tenant_id)
    if not user_id:
        # Local development fallback. In Azure App Service, EasyAuth should
        # populate x-ms-client-principal-id before these API routes are reached.
        user_id = "local-anonymous-user"
        user_name = user_name or "local-anonymous-user"

    # メールclaimを優先し、なければEasyAuthのメール形式ログイン名を使う。
    # 取得できない値をGraph呼び出しや推測で補わない。所有者判定は従来のハッシュを使う。
    email = _extract_claim(principal, "email", "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress") or user_name
    if not authenticated or not re.fullmatch(r"[^\s@,;=]+@[^\s@,;=]+\.[^\s@,;=]+", email):
        email = None
    # Spanの相関と会話の所有者判定には安定したtenant/object IDハッシュを維持する。
    storage_key = hashlib.sha256(f"{tenant_id.lower()}:{user_id.lower()}".encode()).hexdigest()
    if authenticated:
        trace.get_current_span().set_attribute("user.id", storage_key)
    return {
        "id": user_id,
        "tenant_id": tenant_id,
        "name": user_name or "unknown",
        "storage_key": storage_key,
        "authenticated": authenticated,
        "email": email,
    }


async def _fetch_easyauth_me(request: Request) -> list[dict[str, Any]]:
    cookie = request.headers.get("cookie", "").strip()
    if not cookie:
        return []
    host = os.environ.get("WEBSITE_HOSTNAME", "").strip()
    if not host:
        return []
    url = f"https://{host}/.auth/me"
    try:
        async with telemetry.http_client(timeout=10.0, follow_redirects=False) as client:
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
        logger.warning("Failed to fetch /.auth/me: %s", type(exc).__name__)
    return []


async def _refresh_easyauth_tokens(request: Request) -> None:
    cookie = request.headers.get("cookie", "").strip()
    if not cookie:
        return
    host = os.environ.get("WEBSITE_HOSTNAME", "").strip()
    if not host:
        return
    url = f"https://{host}/.auth/refresh"
    try:
        async with telemetry.http_client(timeout=10.0, follow_redirects=False) as client:
            response = await client.get(url, headers={"Cookie": cookie, "Accept": "application/json"})
        logger.info("/.auth/refresh returned HTTP %s", response.status_code)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to call /.auth/refresh: %s", type(exc).__name__)


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
        or os.environ.get("ENTRA_CLIENT_SECRET", "").strip()
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
        detail="Failed to acquire Foundry delegated token by refresh token.",
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
        detail="Failed to acquire Foundry delegated token via OBO.",
    )


async def _get_token() -> str:
    """Acquire Azure access token for the Foundry scope (ai.azure.com)."""
    credential = ManagedIdentityCredential(client_id=os.getenv("AZURE_CLIENT_ID") or None)
    try:
        token = await credential.get_token("https://ai.azure.com/.default")
        return token.token
    finally:
        await credential.close()


async def _build_outbound_headers(request: Request, auth_mode: str = "managed_identity") -> dict[str, str]:
    """呼び出し元が選んだ認証モードでヘッダーを作る。既定の実行経路はrefresh_token。"""
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "Foundry-Features": "AgentEndpoints=V1Preview",
    }
    apim_subscription_key = os.environ.get("APIM_SUBSCRIPTION_KEY", "").strip()
    if apim_subscription_key:
        headers["Ocp-Apim-Subscription-Key"] = apim_subscription_key

    auth_mode = auth_mode.strip().lower()
    if auth_mode in ("refresh_token", "refresh"):
        # EasyAuth's access token can be for Microsoft Graph depending on the
        # provider configuration. Use the EasyAuth refresh token to mint a
        # fresh user delegated token for Foundry instead.
        _get_easyauth_access_token(request)  # validates/logs current EasyAuth user claims
        refresh_token = await _get_easyauth_refresh_token(request)
        foundry_token = await asyncio.to_thread(_acquire_foundry_token_by_refresh_token, refresh_token)
        _validate_delegated_subject(foundry_token, request)
        headers["Authorization"] = f"Bearer {foundry_token}"
        return headers

    if auth_mode in ("obo", "on_behalf_of"):
        user_token = _get_easyauth_access_token(request)
        foundry_token = await asyncio.to_thread(_acquire_foundry_token_on_behalf_of, user_token)
        _validate_delegated_subject(foundry_token, request)
        headers["Authorization"] = f"Bearer {foundry_token}"
        return headers

    if auth_mode in ("forward", "easyauth"):
        user_token = _get_easyauth_access_token(request)
        _validate_delegated_subject(user_token, request)
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


def _validate_delegated_subject(token: str, request: Request) -> None:
    # 署名検証はFoundry/APIM側が実施する。ここでは信頼済みEasyAuth/MSAL経路の
    # Tokenについて、ログイン本人・委任scope・宛先が一致することを追加確認する。
    claims, user = _decode_jwt_payload(token), _get_request_user(request)
    if (not user["authenticated"] or not claims.get("scp")
            or str(claims.get("aud", "")).rstrip("/") != "https://ai.azure.com"
            or str(claims.get("oid", "")).lower() != user["id"].lower()
            or str(claims.get("tid", "")).lower() != user["tenant_id"].lower()):
        raise HTTPException(401, "Foundry delegated token does not match the signed-in user.")
