import base64
import hashlib
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def functions(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2] / "src/functions-mcp-selfhosted"))
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    monkeypatch.setenv("ENTRA_TENANT_ID", "tenant")
    monkeypatch.setenv("EXPECTED_TOKEN_AUDIENCES", "api://synthetic")
    module = importlib.import_module("mcp_server")
    monkeypatch.setattr(module, "acquire_graph_token_via_obo", lambda token: {"success": True, "access_token": "SECRET", "attempts": 1})
    graph = {"id": "user", "displayName": "架空 利用者", "mail": "PRIVATE@example.test"}
    monkeypatch.setattr(module, "call_graph_api", lambda *args: {"success": True, "data": graph, "attempts": 1})
    claims = {"tid": "tenant", "oid": "user", "aud": "api://synthetic", "scp": "access_as_user"}
    token = "header." + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=") + ".signature"
    return module, graph, token


def test_obo_result_verifies_subject_and_only_exposes_name_hash(functions):
    module, graph, token = functions
    mcp = module.create_mcp_server()
    ctx = SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(headers={"Authorization": "Bearer " + token}), meta=None))
    result = mcp._tool_manager.get_tool("whoami").fn(ctx)
    assert result == {"tool": "whoami", "auth_mode": "obo", "user": {
        "displayName": "架空 利用者", "subjectHash": hashlib.sha256(b"tenant:user").hexdigest()}}
    assert "PRIVATE" not in json.dumps(result) and "SECRET" not in json.dumps(result)
    graph["id"] = "other"
    failed = mcp._tool_manager.get_tool("whoami").fn(ctx)
    assert failed == {"tool": "whoami", "error": "Graph OBO lookup failed"}
