"""Stage B injections over executed Controller and child-invoker artifacts."""

import pytest

from procurement_agent.models import BusinessStatus, TechnicalStatus
from procurement_agent.observability import TelemetryRecorder
from trace_pipeline.detectors import DetectionOutcome, detect, evaluate_all
from trace_pipeline.stage_b import (
    StageBHealthyControlHarness, StageBInjectionHarness, derive_trace_facts,
)
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
    telemetry = TelemetryRecorder()
    artifact = await StageBInjectionHarness(
        pattern_id,
        catalog_invoker=catalog,
        code_invoker=code,
        telemetry=telemetry,
    ).run(valid_request, test_case_id=f"{scenario}-{pattern_id}")

    assert artifact.result.technical_status == TechnicalStatus.SUCCESS
    assert artifact.injection_activated is True
    assert any(
        span.name == "response.generate"
        and span.attributes["test.case.id"] == artifact.case_id
        for span in telemetry.finished_spans()
    )
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
        assert artifact.result.draft.status == "VALIDATED"
        assert all(
            item["kind"] not in {"validation.skipped", "evidence.accepted_without_match"}
            for item in artifact.sequence
        )
        if pattern_id == "TV-02":
            assert facts.validation_coverage_complete is False
        else:
            assert facts.evidence_consistent is False
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


@pytest.mark.anyio
@pytest.mark.parametrize("scenario_id", ["S1", "S5"])
async def test_healthy_controls_use_real_invokers_and_shared_telemetry(
    valid_request, scenario_id,
):
    if scenario_id == "S5":
        valid_request = valid_request.model_copy(update={"memo": "X" * 8192})
    catalog = RecordedCatalogAgent()
    code = RecordedCodeAgent()
    telemetry = TelemetryRecorder()

    artifact = await StageBHealthyControlHarness(
        scenario_id,
        catalog_invoker=catalog,
        code_invoker=code,
        telemetry=telemetry,
    ).run(valid_request, test_case_id=f"{scenario_id}-HEALTHY-REAL")

    assert artifact.scenario_id == scenario_id
    assert artifact.result.technical_status == TechnicalStatus.SUCCESS
    assert artifact.result.business_status == BusinessStatus.SUCCESS
    assert artifact.result.status.technical_status == TechnicalStatus.SUCCESS
    assert artifact.result.status.business_status == BusinessStatus.SUCCESS
    assert artifact.injection_requested is False
    assert artifact.injection_activated is False
    assert len(catalog.calls) == len(code.calls) == 1
    assert {
        item.outcome for item in evaluate_all(derive_trace_facts(artifact))
    } == {DetectionOutcome.NOT_DETECTED}
    assert any(
        span.name == "response.generate"
        and span.attributes["test.case.id"] == artifact.case_id
        for span in telemetry.finished_spans()
    )
