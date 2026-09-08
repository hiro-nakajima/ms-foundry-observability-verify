from typing import Any, Dict
from collections.abc import Mapping
import base64
import hashlib
import json
import logging
import os
import time
import mcp_telemetry

import msal
import requests
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings


logging.getLogger("mcp").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=False,
)

GRAPH_BASE_URL = os.environ.get("GRAPH_BASE_URL", "https://graph.microsoft.com/v1.0").rstrip("/")
DEFAULT_GRAPH_SCOPES = os.environ.get("GRAPH_SCOPES", "https://graph.microsoft.com/User.Read")
logger.info(
    "Graph scope configuration loaded: GRAPH_SCOPES set=%s default_scopes=%s",
    bool(os.environ.get("GRAPH_SCOPES", "").strip()),
    DEFAULT_GRAPH_SCOPES,
)
DEFAULT_GRAPH_TIMEOUT_SECONDS = 15.0
DEFAULT_OBO_MAX_RETRIES = 2
DEFAULT_OBO_RETRY_BACKOFF_SECONDS = 0.5
DEFAULT_GRAPH_MAX_RETRIES = 2
DEFAULT_GRAPH_RETRY_BACKOFF_SECONDS = 0.5
RETRYABLE_HTTP_STATUS_CODES = {429, 500, 502, 503, 504}
RETRYABLE_OBO_ERRORS = {"temporarily_unavailable", "server_error"}
_graph_session = requests.Session()


def _get_env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        logger.warning("Invalid integer for %s: %s. Using default %s.", name, raw, default)
        return default


def _get_env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        logger.warning("Invalid float for %s: %s. Using default %s.", name, raw, default)
        return default


def _backoff_delay(base_seconds: float, attempt_index: int) -> float:
    if base_seconds <= 0:
        return 0.0
    return base_seconds * (2**attempt_index)


def _normalize_bearer(token: str) -> str:
    t = (token or "").strip()
    return t[7:].strip() if t.lower().startswith("bearer ") else t


def _get_authorization_from_headers(headers: Any) -> str | None:
    if isinstance(headers, Mapping):
        auth = headers.get("authorization") or headers.get("Authorization")
        if isinstance(auth, str) and auth.strip():
            return auth
    return None


def extract_bearer_token_from_context(ctx: Context) -> str | None:
    try:
        request_context = getattr(ctx, "request_context", None)
        if request_context is None:
            return None

        request = getattr(request_context, "request", None)

        if request is not None:
            headers = getattr(request, "headers", None)
            auth = _get_authorization_from_headers(headers)
            if auth:
                return _normalize_bearer(auth)

            meta = getattr(request, "meta", None)
            if isinstance(meta, dict):
                auth = _get_authorization_from_headers(meta.get("headers"))
                if auth:
                    return _normalize_bearer(auth)

        meta = getattr(request_context, "meta", None)
        if isinstance(meta, dict):
            auth = _get_authorization_from_headers(meta.get("headers"))
            if auth:
                return _normalize_bearer(auth)

    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to extract Authorization header from context: %s", exc)

    return None


def get_token_info(access_token: str) -> Dict[str, Any]:
    token = (access_token or "").strip()
    if not token:
        return {"received": False}
    return {"received": True}


def _sanitize_claims_for_log(claims: Mapping[str, Any] | None) -> Dict[str, Any]:
    if not claims:
        return {}
    # Log only presence flags. Raw tenant/user/client claims are not telemetry.
    return {
        "audience_present": bool(claims.get("aud")),
        "tenant_present": bool(claims.get("tid")),
        "user_present": bool(claims.get("oid")),
        "scopes_present": bool(claims.get("scp")),
        "client_present": bool(claims.get("azp")),
    }


def log_inbound_token_summary(access_token: str, claims: Mapping[str, Any] | None = None) -> None:
    token_info = get_token_info(access_token)
    logger.info(
        "Inbound token summary: received=%s claims=%s",
        token_info.get("received"),
        _sanitize_claims_for_log(claims),
    )


def decode_jwt_payload(token: str) -> Dict[str, Any]:
    normalized = _normalize_bearer(token)
    parts = normalized.split(".")
    if len(parts) < 2:
        return {"_error": "not_a_jwt"}

    payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload_b64.encode("utf-8"))
        payload = json.loads(decoded)
        return payload if isinstance(payload, dict) else {"_error": "payload_not_object"}
    except Exception as exc:  # noqa: BLE001
        return {"_error": f"decode_failed: {exc}"}


def _split_csv_env(name: str, default: str = "") -> list[str]:
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def validate_incoming_token(access_token: str) -> Dict[str, Any]:
    payload = decode_jwt_payload(access_token)
    if payload.get("_error"):
        return {
            "valid": False,
            "error": "Invalid inbound bearer token format",
            "details": payload["_error"],
        }

    allowed_audiences = set(
        _split_csv_env("EXPECTED_TOKEN_AUDIENCES", os.environ.get("ENTRA_CLIENT_ID", ""))
    )
    actual_audience = str(payload.get("aud", "")).strip()
    if allowed_audiences and actual_audience not in allowed_audiences:
        return {
            "valid": False,
            "error": "Unexpected token audience",
            "details": {
                "expected": sorted(allowed_audiences),
                "actual": actual_audience or None,
            },
        }

    expected_tenant = os.environ.get("EXPECTED_TENANT_ID", os.environ.get("ENTRA_TENANT_ID", "")).strip()
    actual_tenant = str(payload.get("tid", "")).strip()
    if expected_tenant and actual_tenant and actual_tenant != expected_tenant:
        return {
            "valid": False,
            "error": "Unexpected tenant in inbound token",
            "details": {
                "expected": expected_tenant,
                "actual": actual_tenant,
            },
        }

    return {
        "valid": True,
        "claims": {
            "aud": actual_audience or None,
            "tid": actual_tenant or None,
            "oid": payload.get("oid"),
            "scp": payload.get("scp"),
            "azp": payload.get("azp"),
        },
    }


def _get_required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _get_graph_scopes() -> list[str]:
    scopes = _split_csv_env("GRAPH_SCOPES", DEFAULT_GRAPH_SCOPES)
    logger.info("Graph OBO scopes resolved: %s", scopes)
    return scopes


def _get_confidential_client(
    tenant_id: str,
    client_id: str,
    client_secret: str,
) -> msal.ConfidentialClientApplication:
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    # Create a fresh MSAL client per OBO exchange. This avoids sharing an
    # in-memory token cache across users in the long-lived Functions worker.
    return msal.ConfidentialClientApplication(
        client_id=client_id,
        client_credential=client_secret,
        authority=authority,
    )


def acquire_graph_token_via_obo(access_token: str) -> Dict[str, Any]:
    tenant_id = _get_required_env("ENTRA_TENANT_ID")
    client_id = _get_required_env("ENTRA_CLIENT_ID")
    client_secret = _get_required_env("ENTRA_CLIENT_SECRET")
    scopes = _get_graph_scopes()
    confidential_client = _get_confidential_client(tenant_id, client_id, client_secret)
    max_retries = _get_env_int("OBO_MAX_RETRIES", DEFAULT_OBO_MAX_RETRIES)
    backoff_seconds = _get_env_float("OBO_RETRY_BACKOFF_SECONDS", DEFAULT_OBO_RETRY_BACKOFF_SECONDS)
    attempts = max_retries + 1
    last_result: Dict[str, Any] = {}

    for attempt in range(attempts):
        result = confidential_client.acquire_token_on_behalf_of(
            user_assertion=_normalize_bearer(access_token),
            scopes=scopes,
        )
        last_result = result

        exchanged_token = result.get("access_token")
        if exchanged_token:
            if attempt > 0:
                logger.info("OBO token exchange succeeded after retry %s/%s.", attempt, max_retries)
            return {
                "success": True,
                "access_token": exchanged_token,
                "scopes": scopes,
                "attempts": attempt + 1,
            }

        error_code = str(result.get("error") or "").strip()
        error_description = result.get("error_description") or error_code or "unknown_error"
        is_retryable = error_code in RETRYABLE_OBO_ERRORS
        logger.warning(
            "OBO token exchange attempt %s/%s failed: %s",
            attempt + 1,
            attempts,
            error_code,
        )
        if not is_retryable or attempt == max_retries:
            break

        delay = _backoff_delay(backoff_seconds, attempt)
        if delay > 0:
            time.sleep(delay)

    error_description = last_result.get("error_description") or last_result.get("error")
    logger.error("OBO token exchange failed after retries")
    return {
        "success": False,
        "error": error_description or "unknown_error",
        "details": {
            "error": last_result.get("error"),
            "suberror": last_result.get("suberror"),
            "correlation_id": last_result.get("correlation_id"),
            "trace_id": last_result.get("trace_id"),
            "attempts": attempts,
        },
    }


def call_graph_api(access_token: str, endpoint: str = "me") -> Dict[str, Any]:
    url = f"{GRAPH_BASE_URL}/{endpoint.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    timeout_seconds = _get_env_float("GRAPH_TIMEOUT_SECONDS", DEFAULT_GRAPH_TIMEOUT_SECONDS)
    max_retries = _get_env_int("GRAPH_MAX_RETRIES", DEFAULT_GRAPH_MAX_RETRIES)
    backoff_seconds = _get_env_float("GRAPH_RETRY_BACKOFF_SECONDS", DEFAULT_GRAPH_RETRY_BACKOFF_SECONDS)
    attempts = max_retries + 1

    for attempt in range(attempts):
        try:
            response = _graph_session.get(url, headers=headers, timeout=timeout_seconds)
            if response.status_code in RETRYABLE_HTTP_STATUS_CODES and attempt < max_retries:
                logger.warning(
                    "Graph API call attempt %s/%s returned retryable status %s.",
                    attempt + 1,
                    attempts,
                    response.status_code,
                )
                delay = _backoff_delay(backoff_seconds, attempt)
                if delay > 0:
                    time.sleep(delay)
                continue

            response.raise_for_status()
            if attempt > 0:
                logger.info("Graph API call succeeded after retry %s/%s.", attempt, max_retries)
            return {"success": True, "data": response.json(), "attempts": attempt + 1}
        except requests.exceptions.RequestException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            is_retryable = status_code in RETRYABLE_HTTP_STATUS_CODES or status_code is None
            logger.warning(
                "Graph API call attempt %s/%s failed: %s",
                attempt + 1,
                attempts,
                type(exc).__name__,
            )
            if not is_retryable or attempt == max_retries:
                logger.error("Graph API call failed after retries: %s", type(exc).__name__)
                return {
                    "success": False,
                    "error": str(exc),
                    "status_code": status_code,
                    "attempts": attempt + 1,
                }

            delay = _backoff_delay(backoff_seconds, attempt)
            if delay > 0:
                time.sleep(delay)

    return {
        "success": False,
        "error": "Graph API call failed after retries",
        "status_code": None,
        "attempts": attempts,
    }


def build_whoami_response(access_token: str) -> Dict[str, Any]:
    token_info = get_token_info(access_token)
    inbound_validation = validate_incoming_token(access_token)
    log_inbound_token_summary(access_token, inbound_validation.get("claims"))
    if not inbound_validation.get("valid"):
        logger.warning(
            "Inbound token validation failed",
        )
        return {
            "error": inbound_validation.get("error"),
            "details": inbound_validation.get("details"),
            "token_info": token_info,
        }

    try:
        with mcp_telemetry.step("auth.obo.exchange") as span:
            obo_result = acquire_graph_token_via_obo(access_token)
            span.set_attribute("app.obo.success", bool(obo_result.get("success")))
    except RuntimeError as exc:
        logger.error("OBO configuration error: %s", exc)
        return {
            "error": "OBO configuration is incomplete",
            "details": str(exc),
            "token_info": token_info,
        }

    if not obo_result.get("success"):
        logger.error(
            "OBO exchange failed for inbound claims=%s correlation_id=%s trace_id=%s",
            _sanitize_claims_for_log(inbound_validation.get("claims")),
            obo_result.get("details", {}).get("correlation_id"),
            obo_result.get("details", {}).get("trace_id"),
        )
        return {
            "error": "Failed to exchange token via OBO",
            "details": obo_result.get("error"),
            "obo_error": obo_result.get("details"),
            "token_info": token_info,
        }

    with mcp_telemetry.step("graph.me") as span:
        graph_result = call_graph_api(obo_result["access_token"], "me")
        span.set_attribute("app.graph.success", bool(graph_result.get("success")))

    if graph_result.get("success"):
        user_data = graph_result.get("data", {})
        inbound_claims = inbound_validation.get("claims", {})
        inbound_oid = str(inbound_claims.get("oid") or "").strip().lower()
        graph_user_id = str(user_data.get("id") or "").strip().lower()
        if not inbound_oid or not graph_user_id or inbound_oid != graph_user_id:
            logger.error(
                "Security check failed: inbound token oid does not match Graph /me id. inbound_claims=%s graph_user_id_present=%s",
                _sanitize_claims_for_log(inbound_claims),
                bool(graph_user_id),
            )
            return {
                "error": "Inbound token user does not match Microsoft Graph /me user",
                "details": "The OBO result appears to resolve to a different user than the inbound token.",
                "obo": {"scopes": obo_result.get("scopes", [])},
            }
        if not inbound_oid or not graph_user_id:
            logger.warning(
                "Security check skipped because user identifiers are incomplete: inbound_claims=%s graph_user_id_present=%s",
                _sanitize_claims_for_log(inbound_claims),
                bool(graph_user_id),
            )
        logger.info(
            "whoami succeeded: inbound_claims=%s obo_attempts=%s graph_attempts=%s",
            _sanitize_claims_for_log(inbound_claims),
            obo_result.get("attempts"),
            graph_result.get("attempts"),
        )
        return {
            "tool": "whoami",
            "auth_mode": "obo",
            "user": {
                "subjectHash": hashlib.sha256(f"{inbound_claims['tid'].lower()}:{graph_user_id}".encode()).hexdigest(),
                "displayName": user_data.get("displayName"),
                "userPrincipalName": user_data.get("userPrincipalName"),
                "jobTitle": user_data.get("jobTitle"),
                "mail": user_data.get("mail"),
            },
            "token_info": token_info,
            "obo": {
                "scopes": obo_result.get("scopes", []),
                "attempts": {
                    "obo": obo_result.get("attempts"),
                    "graph": graph_result.get("attempts"),
                },
            },
        }

    logger.error(
        "Failed to call Graph API: error=%s status_code=%s inbound_claims=%s",
        graph_result.get("error"),
        graph_result.get("status_code"),
        _sanitize_claims_for_log(inbound_validation.get("claims")),
    )
    return {
        "error": "Failed to call Microsoft Graph API",
        "details": graph_result.get("error"),
        "status_code": graph_result.get("status_code"),
    }


def create_mcp_server() -> FastMCP:
    mcp = FastMCP(
        "calculator",
        stateless_http=True,
        transport_security=transport_security,
    )

    @mcp.tool()
    def whoami(ctx: Context) -> Dict[str, Any]:
        access_token = extract_bearer_token_from_context(ctx)
        if not access_token:
            return {
                "error": "Missing Authorization header",
                "message": (
                    "Pass a delegated access token for this MCP API via the "
                    "'Authorization: Bearer <token>' HTTP header; the server will "
                    "exchange it for Microsoft Graph using OBO. Do not include "
                    "tokens in tool arguments."
                ),
            }

        logger.info("whoami MCP tool called (python runtime, OBO)")
        with mcp_telemetry.step("mcp.whoami", mcp_telemetry.carrier_from_mcp(ctx)) as span:
            result = build_whoami_response(access_token)
            mcp_telemetry.record_outcome(span, result)
            # The procurement lookup needs only the verified subject and name.
            # Do not send Graph profile fields or Entra error bodies to an Agent.
            if result.get("error"):
                return {"tool": "whoami", "error": "Graph OBO lookup failed"}
            return {"tool": "whoami", "auth_mode": "obo", "user": {
                key: result["user"].get(key) for key in ("subjectHash", "displayName")}}

    @mcp.tool()
    def greet(name: str = "World") -> str:
        return f"Hello, {name}!"

    return mcp


async def app(scope, receive, send):
    mcp = create_mcp_server()
    streamable_http_app = mcp.streamable_http_app()
    async with mcp.session_manager.run():
        await streamable_http_app(scope, receive, send)
