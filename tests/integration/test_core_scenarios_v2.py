from agent_framework import AgentSession
import json
from pathlib import Path
import pytest
from pydantic import ValidationError

from procurement_agent.controller import ProcurementController
from procurement_agent.models import BusinessStatus, CodeDeterminationInput, FailureProfile, PlanStatus, TechnicalStatus
from procurement_agent.observability import TelemetryRecorder, truncate_export
from procurement_agent.session_state import load_execution_state, restore_framework_session
from trace_pipeline.detectors import DetectionOutcome, TraceFacts, detect, evaluate_all
from tests.fixtures.fake_agents import RecordedCatalogAgent, RecordedCodeAgent


@pytest.mark.anyio
async def test_s1_completes_validated_grounded_application_and_session_resume(valid_request):
    catalog = RecordedCatalogAgent()
    codes = RecordedCodeAgent()
    recorder = TelemetryRecorder(content_profile="synthetic-content-on", synthetic_environment=True)
    controller = ProcurementController(catalog, codes, telemetry=recorder)
    session = AgentSession()
    result = await controller.execute(valid_request, session=session, test_case_id="S1-HEALTHY")
    assert result.technical_status == TechnicalStatus.SUCCESS
    assert result.business_status == BusinessStatus.SUCCESS
    assert result.draft is not None
    assert result.draft.lines[0].product_code == "LAPTOP-DEV-14"
    assert result.draft.lines[0].unit_price == 180000
    assert result.draft.lines[0].account_code == "7210-EQUIPMENT"
    assert result.draft.department_code == "DPT-DEV"
    assert result.draft.total == 360000
    state = load_execution_state(session)
    assert state.plan.status == PlanStatus.COMPLETED
    assert [event["name"] for event in result.trace["events"]].count("step.completed") == 3
    span_events = {event.name for span in recorder.finished_spans() for event in span.events}
    assert {"plan.created", "step.started", "handoff.payload_validated", "step.completed"} <= span_events
    restored = restore_framework_session(session.to_dict())
    assert load_execution_state(restored).draft == result.draft
    second = await controller.execute(valid_request, session=restored, test_case_id="S1-HEALTHY-2")
    assert second.business_status == BusinessStatus.SUCCESS
    assert load_execution_state(restored).turn_number == 2
    assert load_execution_state(restored).plan.version == 2


@pytest.mark.anyio
@pytest.mark.parametrize("fixture", [
    "code-not-found.json", "code-index-missing.json", "code-permission.json",
    "code-business-invalid.json", "code-timeout.json", "code-protocol-invalid.json",
])
async def test_s2_failure_profiles_separate_status_layers(valid_request, fixture):
    controller = ProcurementController(RecordedCatalogAgent(), RecordedCodeAgent(fixture))
    result = await controller.execute(valid_request, session=AgentSession(), test_case_id=f"S2-{fixture}")
    assert result.scenario_id == "S2"
    assert result.business_status != BusinessStatus.SUCCESS
    assert result.status is not None
    if fixture in {"code-not-found.json", "code-business-invalid.json"}:
        assert result.technical_status == TechnicalStatus.SUCCESS
    else:
        assert result.technical_status == TechnicalStatus.ERROR


@pytest.mark.anyio
async def test_s3_not_found_retries_replans_then_waits_for_user(valid_request):
    catalog = RecordedCatalogAgent("catalog-not-found.json")
    codes = RecordedCodeAgent()
    controller = ProcurementController(catalog, codes)
    result = await controller.execute(valid_request, session=AgentSession(), test_case_id="S3-NOT-FOUND")
    assert result.scenario_id == "S3"
    assert result.business_status == BusinessStatus.WAITING_USER
    assert [item["name"] for item in result.trace["events"]] == [
        "step.started", "step.retry_scheduled", "step.started", "plan.replanned"
    ]
    assert not codes.calls


@pytest.mark.parametrize("fixture", ["s4-missing-category.json", "s4-missing-correlation.json"])
def test_s4_missing_structured_input_fails_at_boundary(fixture):
    payload = json.loads((Path(__file__).parents[1] / "fixtures/scenarios" / fixture).read_text(encoding="utf-8"))
    with pytest.raises(ValidationError):
        CodeDeterminationInput.model_validate(payload)
    result = detect(
        "MA-04", TraceFacts(case_id="S4-MISSING", handoff_required_fields_missing=["product_category"]),
        injection_requested=True, injection_activated=True,
    )
    assert result.outcome == DetectionOutcome.DETECTED


def test_s4_complete_structured_input_is_accepted():
    payload = json.loads((Path(__file__).parents[1] / "fixtures/scenarios/s4-complete.json").read_text(encoding="utf-8"))
    assert CodeDeterminationInput.model_validate(payload).product_category == "laptop"


@pytest.mark.parametrize("size", [128, 8191, 8192, 8193, 32767, 32768, 32769, 65535, 65536, 65537])
def test_s5_payload_boundaries_report_first_truncation(size):
    payload = "X" * size
    for limit in (8192, 32768, 65536):
        measured = truncate_export(payload, limit)
        assert measured["stored_length"] == min(size, limit)
        assert measured["first_truncated_position"] == (limit if size > limit else None)


def test_s1_s5_healthy_controls_have_no_semantic_false_positive():
    for scenario in ("S1", "S5"):
        assert all(item.outcome == DetectionOutcome.NOT_DETECTED for item in evaluate_all(TraceFacts(case_id=scenario)))
