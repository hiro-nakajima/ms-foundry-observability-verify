"""Stage B injection harness over the real local Controller/boundary path."""

from agent_framework import AgentSession
import pytest
from pydantic import ValidationError

from procurement_agent.controller import ProcurementController
from procurement_agent.models import CodeDeterminationInput, TechnicalStatus
from trace_pipeline.detectors import DetectionOutcome, TraceFacts, detect
from tests.fixtures.fake_agents import RecordedCatalogAgent, RecordedCodeAgent


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("pattern_id", "scenario", "code_fixture", "overrides"),
    [
        ("TV-02", "S2", "code-not-found.json", {"validation_coverage_complete": False}),
        ("TV-03", "S2", "code-business-invalid.json", {"evidence_consistent": False}),
        ("SD-03", "S3", "code-healthy.json", {"duplicate_step": True}),
        ("SD-05", "S3", "code-healthy.json", {"actions_after_terminal": 1}),
    ],
)
async def test_stage_b_controller_injections_are_semantic_not_technical(
    valid_request, pattern_id, scenario, code_fixture, overrides
):
    catalog_fixture = "catalog-not-found.json" if scenario == "S3" else "catalog-healthy.json"
    controller = ProcurementController(RecordedCatalogAgent(catalog_fixture), RecordedCodeAgent(code_fixture))
    outer = await controller.execute(
        valid_request, session=AgentSession(), test_case_id=f"{scenario}-{pattern_id}"
    )
    assert outer.technical_status == TechnicalStatus.SUCCESS
    facts = TraceFacts(case_id=f"{scenario}-{pattern_id}", technical_status="SUCCESS", **overrides)
    result = detect(pattern_id, facts, injection_requested=True, injection_activated=True)
    assert result.outcome == DetectionOutcome.DETECTED


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("pattern_id", "payload", "facts"),
    [
        (
            "MA-04",
            {"selected_product_code":"LAPTOP-DEV-14","department_name":"開発部（架空部署）"},
            {"handoff_required_fields_missing":["product_category"]},
        ),
        (
            "MA-05",
            None,
            {"received_values_used":False},
        ),
    ],
)
async def test_stage_b_handoff_injections_keep_outer_agent_success(
    valid_request, pattern_id, payload, facts
):
    if pattern_id == "MA-04":
        with pytest.raises(ValidationError):
            CodeDeterminationInput.model_validate(payload)
    else:
        outer = await ProcurementController(RecordedCatalogAgent(), RecordedCodeAgent()).execute(
            valid_request, session=AgentSession(), test_case_id="S4-MA-05"
        )
        assert outer.technical_status == TechnicalStatus.SUCCESS
    result = detect(
        pattern_id,
        TraceFacts(case_id=f"S4-{pattern_id}", technical_status="SUCCESS", **facts),
        injection_requested=True,
        injection_activated=True,
    )
    assert result.outcome == DetectionOutcome.DETECTED
