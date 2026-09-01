"""Recorded child-Agent fixtures. Production source contains only Foundry proxies."""

from __future__ import annotations

from pathlib import Path

from procurement_agent.mcp_contract import classify_transcript, load_transcript, result_documents
from procurement_agent.models import (
    BusinessStatus, CatalogCandidate, CatalogSearchInput, CatalogSearchResult,
    CodeDeterminationInput, CodeDeterminationResult, Evidence,
)


MCP_FIXTURES = Path(__file__).parent / "mcp"


class RecordedCatalogAgent:
    def __init__(self, fixture: str = "catalog-healthy.json") -> None:
        self.fixture = fixture
        self.calls: list[CatalogSearchInput] = []

    async def __call__(self, payload):
        value = CatalogSearchInput.model_validate(payload)
        self.calls.append(value)
        transcript = load_transcript(MCP_FIXTURES / self.fixture)
        status = classify_transcript(transcript)
        documents = result_documents(transcript)
        candidates = [CatalogCandidate(
            product_code=item["product_code"], product_name=item["product_name"],
            category=item["category"], unit_price=item["unit_price"],
            currency=item["currency"], specifications=item.get("specifications", {}),
            evidence_id=f"evidence:{item['document_id']}",
        ) for item in documents]
        evidence = [Evidence(
            evidence_id=f"evidence:{item['document_id']}", index_name="procurement-catalog-v1",
            document_id=item["document_id"], source_version=item["source_version"],
            record_type="product", record_key=item["product_code"],
            rank=item.get("rank"), score=item.get("score"),
        ) for item in documents]
        return CatalogSearchResult(
            correlation=value.correlation, status=status, candidates=candidates,
            selected_product_code=candidates[0].product_code if candidates else None,
            evidence=evidence,
        )


class RecordedCodeAgent:
    def __init__(self, fixture: str = "code-healthy.json") -> None:
        self.fixture = fixture
        self.calls: list[CodeDeterminationInput] = []

    async def __call__(self, payload):
        value = CodeDeterminationInput.model_validate(payload)
        self.calls.append(value)
        transcript = load_transcript(MCP_FIXTURES / self.fixture)
        status = classify_transcript(transcript)
        documents = result_documents(transcript)
        account = next((item for item in documents if item.get("record_type") == "account_code"), None)
        department = next((item for item in documents if item.get("record_type") == "department"), None)
        evidence = [Evidence(
            evidence_id=f"evidence:{item['document_id']}", index_name="procurement-code-master-v1",
            document_id=item["document_id"], source_version=item["source_version"],
            record_type=item["record_type"],
            record_key=item.get("account_code") or item.get("department_code"),
        ) for item in documents]
        return CodeDeterminationResult(
            correlation=value.correlation, status=status,
            account_code=account.get("account_code") if account else None,
            account_name=account.get("display_name") if account else None,
            department_code=department.get("department_code") if department else None,
            department_name=department.get("display_name") if department else None,
            evidence=evidence,
        )
