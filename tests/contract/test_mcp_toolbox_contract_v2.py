from pathlib import Path

import pytest

from procurement_agent.mcp_contract import classify_transcript, load_transcript
from procurement_agent.models import FailureLayer, McpStatus, SearchStatus, TechnicalStatus


FIXTURES = Path(__file__).parents[1] / "fixtures" / "mcp"


@pytest.mark.parametrize(
    ("name", "technical", "mcp", "search", "layer"),
    [
        ("catalog-healthy.json", "SUCCESS", "SUCCESS", "SUCCESS", "NONE"),
        ("catalog-not-found.json", "SUCCESS", "SUCCESS", "NOT_FOUND", "NONE"),
        ("code-healthy.json", "SUCCESS", "SUCCESS", "SUCCESS", "NONE"),
        ("code-not-found.json", "SUCCESS", "SUCCESS", "NOT_FOUND", "NONE"),
        ("code-index-missing.json", "ERROR", "SUCCESS", "INDEX_MISSING", "SEARCH"),
        ("code-permission.json", "ERROR", "SUCCESS", "PERMISSION_DENIED", "SEARCH"),
        ("code-business-invalid.json", "SUCCESS", "SUCCESS", "SUCCESS", "VALIDATION"),
        ("code-timeout.json", "ERROR", "TIMEOUT", "NOT_RUN", "MCP"),
        ("code-protocol-invalid.json", "ERROR", "PROTOCOL_ERROR", "NOT_RUN", "MCP"),
    ],
)
def test_recorded_contract_separates_failure_layers(name, technical, mcp, search, layer):
    status = classify_transcript(load_transcript(FIXTURES / name))
    assert status.technical_status == TechnicalStatus(technical)
    assert status.mcp_status == McpStatus(mcp)
    assert status.search_status == SearchStatus(search)
    assert status.failure_layer == FailureLayer(layer)


def test_all_transcripts_use_initialize_list_call_sequence():
    for path in FIXTURES.glob("*.json"):
        transcript = load_transcript(path)
        assert [exchange.method for exchange in transcript.exchanges] == [
            "initialize", "tools/list", "tools/call"
        ]
