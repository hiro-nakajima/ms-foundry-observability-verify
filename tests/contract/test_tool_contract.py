from __future__ import annotations

from datetime import date

from procurement_agent.models import BusinessStatus, TechnicalStatus


def _assert_contract(response) -> None:
    assert response.call_id.startswith("tool-")
    assert response.http_status == 200
    assert response.technical_status == TechnicalStatus.SUCCESS
    assert response.data_version == "2026-08-28.1"
    assert isinstance(response.result, dict)
    assert isinstance(response.evidence_refs, list)
    assert isinstance(response.warnings, list)


def test_all_eight_logical_tools_follow_contract(adapter, valid_draft) -> None:
    responses = [
        adapter.search_catalog("開発用のノートPC"),
        adapter.get_catalog_item("LAPTOP-DEV-14"),
        adapter.lookup_account_code("laptop", "開発用端末"),
        adapter.lookup_department("開発一部"),
        adapter.get_applicant("山田太郎"),
        adapter.estimate_delivery("LAPTOP-DEV-14", 3, date(2026, 9, 30)),
        adapter.calculate_request(3, "180000"),
        adapter.validate_application(valid_draft),
    ]
    for response in responses:
        _assert_contract(response)
        assert response.business_status == BusinessStatus.SUCCESS


def test_business_failure_still_has_technical_success(adapter) -> None:
    response = adapter.get_catalog_item("DOES-NOT-EXIST")
    _assert_contract(response)
    assert response.business_status == BusinessStatus.NOT_FOUND


def test_search_and_structured_get_are_separate(adapter) -> None:
    search = adapter.search_catalog("開発用ノートPC")
    first = search.result["candidates"][0]
    assert first["item"]["product_code"] == "LAPTOP-DEV-14"
    structured = adapter.get_catalog_item(first["item"]["product_code"])
    assert structured.result["item"]["unit_price"] == "180000"
    assert structured.evidence_refs == ["catalog:LAPTOP-DEV-14:2026-08-28.1"]


def test_delivery_tool_warns_when_requested_date_cannot_be_met(adapter) -> None:
    response = adapter.estimate_delivery("LAPTOP-DEV-14", 1, date(2026, 8, 29))
    _assert_contract(response)
    assert response.business_status == BusinessStatus.SUCCESS
    assert response.result["delivery"]["meets_request"] is False
    assert "requested delivery date cannot be met" in response.warnings


def test_blank_lookup_identifiers_are_business_invalid_input(adapter) -> None:
    assert adapter.get_applicant("").business_status == BusinessStatus.INVALID_INPUT
    assert adapter.lookup_department("  ").business_status == BusinessStatus.INVALID_INPUT
