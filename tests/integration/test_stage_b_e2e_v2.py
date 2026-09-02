"""Stage B injections over executed Controller and child-invoker artifacts."""

import pytest

from procurement_agent.models import BusinessStatus, TechnicalStatus
from trace_pipeline.detectors import DetectionOutcome, detect
from trace_pipeline.stage_b import StageBInjectionHarness, derive_trace_facts
from tests.fixtures.fake_agents import RecordedCatalogAgent, RecordedCodeAgent


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("pattern_id", "scenario", "catalog_fixture", "code_fixture"),
    [
        ("TV-02", "S2", "catalog-healthy.json", "code-not-found.json"),
        ("TV-03", "S2", "catalog-healthy.json", "code-business-invalid.json"),
        ("SD-03", "S3", "catalog-not-found.json", "code-healthy.json"),
        ("SD-05", "S3", "catalog-not-found.json", "code-healthy.json"),
        ("MA-04", "S4", "catalog-healthy.json", "code-healthy.json"),
        ("MA-05", "S4", "catalog-healthy.json", "code-healthy.json"),
    ],
)
async def test_stage_b_facts_are_derived_from_activated_execution(
    valid_request, pattern_id, scenario, catalog_fixture, code_fixture,
):
    catalog = RecordedCatalogAgent(catalog_fixture)
    code = RecordedCodeAgent(code_fixture)
    artifact = await StageBInjectionHarness(
        pattern_id,
        catalog_invoker=catalog,
        code_invoker=code,
    ).run(valid_request, test_case_id=f"{scenario}-{pattern_id}")

    assert artifact.result.technical_status == TechnicalStatus.SUCCESS
    assert artifact.injection_activated is True
    facts = derive_trace_facts(artifact)
    detection = detect(
        pattern_id, facts,
        injection_requested=artifact.injection_requested,
        injection_activated=artifact.injection_activated,
    )
    assert detection.outcome == DetectionOutcome.DETECTED

    if pattern_id in {"TV-02", "TV-03"}:
        assert artifact.result.business_status == BusinessStatus.SUCCESS
        assert artifact.result.status.business_status != BusinessStatus.SUCCESS
    elif pattern_id == "SD-03":
        assert facts.duplicate_step is True
        assert len(catalog.calls) == 3  # duplicated attempt 1 plus normal attempt 2
    elif pattern_id == "SD-05":
        assert facts.actions_after_terminal == 1
        assert artifact.sequence[-1]["after_terminal"] is True
    elif pattern_id == "MA-04":
        assert facts.handoff_required_fields_missing == ["product_category"]
        assert not code.calls
    elif pattern_id == "MA-05":
        assert facts.received_values_used is False
        assert code.calls[0].department_name == "無視された部名（Stage B）"
