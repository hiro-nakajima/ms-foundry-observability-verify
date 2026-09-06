import importlib
import json
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def deployment(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    return importlib.import_module("deploy_search")


def test_schema_only_action_creates_missing_index_without_document_push(deployment):
    schemas = {
        name: json.loads(
            (deployment.ROOT / "infra/search/indexes" / f"{name}.json").read_text()
        )
        for name in deployment.INDEXES
    }
    requests = []

    def handle(request):
        requests.append((request.method, request.url.path))
        index = request.url.path.rsplit("/", 1)[-1]
        if request.method == "GET" and index == deployment.INDEXES[0]:
            return httpx.Response(404)
        if request.method == "PUT":
            assert request.headers["if-none-match"] == "*"
            return httpx.Response(201, json=schemas[index])
        return httpx.Response(200, json=schemas[index])

    with httpx.Client(
        base_url="https://fixture.search.windows.net",
        transport=httpx.MockTransport(handle),
    ) as client:
        result = deployment._ensure_schemas(client)

    assert result == [
        {"index": deployment.INDEXES[0], "result": "created"},
        {"index": deployment.INDEXES[1], "result": "matched"},
    ]
    assert all("/docs" not in path for _, path in requests)


def test_optional_obo_source_does_not_return_token_preview_or_raw_object_id():
    source = (
        Path(__file__).resolve().parents[2]
        / "src/functions-mcp-selfhosted/mcp_server.py"
    ).read_text()

    assert "token[:10]" not in source
    assert '"inbound_claims": inbound_claims' not in source
    assert '"id": user_data.get("id")' not in source
