from agent_framework import AgentSession, InMemoryHistoryProvider
from decimal import Decimal
import json
from pathlib import Path
import pytest
from pydantic import ValidationError

from procurement_agent.controller import ProcurementController
from procurement_agent.models import (
    BusinessStatus, CatalogSearchInput, CatalogSearchResult, CodeDeterminationInput,
    CodeDeterminationResult, FailureLayer, McpStatus, OperationStatus, ParseStatus,
    PlanStatus, SearchStatus, TechnicalStatus,
)
from procurement_agent.observability import TelemetryRecorder, truncate_export
from procurement_agent.session_state import load_execution_state, restore_framework_session
from trace_pipeline.detectors import DetectionOutcome, TraceFacts, detect, evaluate_all
from trace_pipeline.envelope import RunIdentity
from trace_pipeline.normalize import build_envelope
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
    assert state.last_machine_response["http_status"] == 200
    assert state.last_machine_response["mcp_status"] == "SUCCESS"
    assert state.last_machine_response["search_status"] == "SUCCESS"
    assert state.last_machine_response["parse_status"] == "SUCCESS"
    assert state.last_machine_response["business_status"] == "SUCCESS"
    assert state.last_machine_response["outer_technical_status"] == "SUCCESS"
    assert state.last_machine_response["outer_business_status"] == "SUCCESS"
    assert set(state.last_machine_response["step_statuses"]) == {"catalog", "code"}
    assert all(
        item["mcp_status"] == item["search_status"] == item["parse_status"] == "SUCCESS"
        for item in state.last_machine_response["step_statuses"].values()
    )
    envelope = await build_envelope(
        run=RunIdentity(
            run_id="run-s1-healthy", case_id="S1-HEALTHY", agent_role="coordinator",
            agent_definition_name="procurement_parent_agent", agent_definition_version="1",
            implementation_kind="hosted_framework",
        ),
        session=session,
        history_provider=InMemoryHistoryProvider("procurement-history", load_messages=True),
        telemetry=recorder,
        user_input=[], response={}, retrieved_contexts=[], system_prompt={},
        tool_definitions=[], tool_calls=[], tool_output=[],
    )
    assert envelope.statuses["mcp_status"] == "SUCCESS"
    assert set(envelope.statuses["step_statuses"]) == {"catalog", "code"}
    assert [item["step_id"] for item in envelope.correlation.child_invocations] == [
        "catalog", "code",
    ]
    assert [event["name"] for event in result.trace["events"]].count("step.completed") == 3
    finished_spans = recorder.finished_spans()
    span_events = {event.name for span in finished_spans for event in span.events}
    assert {"plan.created", "step.started", "handoff.payload_validated", "step.completed"} <= span_events
    response_span = next(span for span in finished_spans if span.name == "response.generate")
    assert response_span.attributes["mcp.status"] == "SUCCESS"
    assert response_span.attributes["search.status"] == "SUCCESS"
    assert response_span.attributes["parse.status"] == "SUCCESS"
    child_spans = [span for span in finished_spans if span.name == "plan.step.execute"]
    assert {span.attributes["parent.invocation.id"] for span in child_spans} == {
        item.parent_invocation_id for item in state.child_correlations
    }
    restored = restore_framework_session(session.to_dict())
    assert load_execution_state(restored).draft == result.draft
    assert len(load_execution_state(restored).child_correlations) == 2
    second = await controller.execute(valid_request, session=restored, test_case_id="S1-HEALTHY-2")
    assert second.business_status == BusinessStatus.SUCCESS
    assert load_execution_state(restored).turn_number == 2
    assert load_execution_state(restored).plan.version == 2
    assert len(load_execution_state(restored).child_correlations) == 2
    assert len(second.draft.evidence_refs) == 3


@pytest.mark.anyio
@pytest.mark.parametrize("fixture", [
    "code-not-found.json", "code-index-missing.json", "code-permission.json",
    "code-business-invalid.json", "code-timeout.json", "code-protocol-invalid.json",
])
async def test_s2_failure_profiles_separate_status_layers(valid_request, fixture):
    controller = ProcurementController(RecordedCatalogAgent(), RecordedCodeAgent(fixture))
    session = AgentSession()
    result = await controller.execute(valid_request, session=session, test_case_id=f"S2-{fixture}")
    assert result.scenario_id == "S2"
    assert result.business_status != BusinessStatus.SUCCESS
    assert result.status is not None
    if fixture in {"code-not-found.json", "code-business-invalid.json"}:
        assert result.technical_status == TechnicalStatus.SUCCESS
    else:
        assert result.technical_status == TechnicalStatus.ERROR
    machine_status = load_execution_state(session).last_machine_response
    assert machine_status["http_status"] == result.status.http_status
    assert machine_status["mcp_status"] == result.status.mcp_status
    assert machine_status["search_status"] == result.status.search_status
    assert machine_status["parse_status"] == result.status.parse_status
    assert machine_status["business_status"] == result.status.business_status
    assert machine_status["outer_technical_status"] == result.technical_status
    assert machine_status["outer_business_status"] == result.business_status
    response_span = next(
        span for span in controller.telemetry.finished_spans()
        if span.name == "response.generate"
    )
    assert response_span.attributes["mcp.status"] == result.status.mcp_status
    assert response_span.attributes["search.status"] == result.status.search_status
    assert response_span.attributes["parse.status"] == result.status.parse_status
    assert response_span.attributes["business.status"] == result.business_status


@pytest.mark.anyio
async def test_s3_not_found_retries_replans_then_waits_for_user(valid_request):
    catalog = RecordedCatalogAgent("catalog-not-found.json")
    codes = RecordedCodeAgent()
    controller = ProcurementController(catalog, codes)
    session = AgentSession()
    result = await controller.execute(valid_request, session=session, test_case_id="S3-NOT-FOUND")
    assert result.scenario_id == "S3"
    assert result.business_status == BusinessStatus.WAITING_USER
    assert [item["name"] for item in result.trace["events"]] == [
        "step.started", "step.retry_scheduled", "step.started", "plan.replanned"
    ]
    assert len(catalog.calls) == 2
    assert not codes.calls
    assert [item.attempt for item in load_execution_state(session).child_correlations] == [1, 2]


@pytest.mark.anyio
async def test_s3_transient_catalog_not_found_recovers_on_real_retry(valid_request):
    not_found = RecordedCatalogAgent("catalog-not-found.json")
    healthy = RecordedCatalogAgent("catalog-healthy.json")
    calls = 0
    async def catalog_sequence(payload):
        nonlocal calls
        calls += 1
        return await (not_found(payload) if calls == 1 else healthy(payload))
    result = await ProcurementController(catalog_sequence, RecordedCodeAgent()).execute(
        valid_request, session=AgentSession(), test_case_id="S3-TRANSIENT"
    )
    assert result.business_status == BusinessStatus.SUCCESS
    assert calls == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("failure", "reason_code", "mcp_status", "retryable"),
    [
        (TimeoutError("synthetic timeout"), "child_transport_timeout", McpStatus.TIMEOUT, True),
        (PermissionError("synthetic denied"), "child_transport_permission_denied", McpStatus.ERROR, False),
        (RuntimeError("synthetic runtime"), "child_invocation_error", McpStatus.ERROR, False),
    ],
)
async def test_child_transport_exception_is_terminal_and_observable(
    valid_request, failure, reason_code, mcp_status, retryable,
):
    async def failing_child(_payload):
        raise failure

    session = AgentSession()
    controller = ProcurementController(failing_child, RecordedCodeAgent())
    result = await controller.execute(
        valid_request, session=session, test_case_id=f"CHILD-{reason_code}",
    )

    assert result.scenario_id == "S2"
    assert result.technical_status == TechnicalStatus.ERROR
    assert result.business_status == BusinessStatus.BLOCKED
    assert result.status.reason_code == reason_code
    assert result.status.mcp_status == mcp_status
    assert result.status.retryable is retryable
    state = load_execution_state(session)
    assert state.plan.status == PlanStatus.BLOCKED
    assert state.plan.steps[0].status == PlanStatus.BLOCKED
    assert state.last_machine_response["reason_code"] == reason_code
    assert not any(
        event.name == "step.retry_scheduled"
        for span in controller.telemetry.finished_spans()
        for event in span.events
    )
    response_span = next(
        span for span in controller.telemetry.finished_spans()
        if span.name == "response.generate"
    )
    assert response_span.attributes["technical.status"] == TechnicalStatus.ERROR
    assert response_span.attributes["mcp.status"] == mcp_status


@pytest.mark.anyio
async def test_non_retryable_catalog_rejection_does_not_emit_retry_scheduled(valid_request):
    async def rejected(payload):
        value = CatalogSearchInput.model_validate(payload)
        return CatalogSearchResult(
            correlation=value.correlation,
            status=OperationStatus(
                technical_status=TechnicalStatus.ERROR,
                mcp_status=McpStatus.ERROR,
                business_status=BusinessStatus.BLOCKED,
                failure_layer=FailureLayer.MCP,
                retryable=False,
                reason_code="catalog_transport_failed",
            ),
        )

    controller = ProcurementController(rejected, RecordedCodeAgent())
    result = await controller.execute(
        valid_request, session=AgentSession(), test_case_id="CATALOG-NO-RETRY",
    )

    assert result.scenario_id == "S2"
    assert not any(
        event.name == "step.retry_scheduled"
        for span in controller.telemetry.finished_spans()
        for event in span.events
    )


@pytest.mark.anyio
@pytest.mark.parametrize("failed_step", ["catalog", "code"])
async def test_inconsistent_child_success_status_is_rejected(valid_request, failed_step):
    healthy_catalog = RecordedCatalogAgent()
    healthy_code = RecordedCodeAgent()

    async def inconsistent_catalog(payload):
        result = await healthy_catalog(payload)
        result.status = result.status.model_copy(update={
            "technical_status": TechnicalStatus.ERROR,
            "mcp_status": McpStatus.TIMEOUT,
            "failure_layer": FailureLayer.MCP,
            "reason_code": "inconsistent_catalog_status",
        })
        return result

    async def inconsistent_code(payload):
        result = await healthy_code(payload)
        result.status = result.status.model_copy(update={
            "technical_status": TechnicalStatus.ERROR,
            "mcp_status": McpStatus.TIMEOUT,
            "failure_layer": FailureLayer.MCP,
            "reason_code": "inconsistent_code_status",
        })
        return result

    controller = ProcurementController(
        inconsistent_catalog if failed_step == "catalog" else healthy_catalog,
        inconsistent_code if failed_step == "code" else healthy_code,
    )
    session = AgentSession()
    result = await controller.execute(
        valid_request, session=session, test_case_id=f"INCONSISTENT-{failed_step}",
    )

    assert result.scenario_id == "S2"
    assert result.technical_status == TechnicalStatus.ERROR
    assert result.business_status == BusinessStatus.BLOCKED
    assert result.draft is None
    assert result.status.business_status == BusinessStatus.SUCCESS
    state = load_execution_state(session)
    assert state.plan.status == PlanStatus.BLOCKED
    assert state.last_machine_response["outer_business_status"] == "BLOCKED"
    failed_role = "catalog_search" if failed_step == "catalog" else "code_determination"
    failed_span = next(
        span for span in controller.telemetry.finished_spans()
        if span.name == "plan.step.execute" and span.attributes["agent.role"] == failed_role
    )
    failed_events = {event.name for event in failed_span.events}
    assert "result.rejected" in failed_events
    assert "step.completed" not in failed_events


@pytest.mark.anyio
async def test_requested_specification_mismatch_is_rejected_before_catalog_completion(valid_request):
    request = valid_request.model_copy(update={
        "constraints": valid_request.constraints.model_copy(update={
            "specifications": {"memory": "64GB"},
        }),
    })
    catalog = RecordedCatalogAgent()
    codes = RecordedCodeAgent()
    controller = ProcurementController(catalog, codes)
    session = AgentSession()
    result = await controller.execute(
        request, session=session, test_case_id="SPECIFICATION-MISMATCH",
    )

    assert result.scenario_id == "S1"
    assert result.technical_status == TechnicalStatus.SUCCESS
    assert result.business_status == BusinessStatus.VALIDATION_FAILED
    assert result.status.reason_code == "catalog_specification_mismatch"
    assert result.draft is None
    assert len(catalog.calls) == 1
    assert not codes.calls
    state = load_execution_state(session)
    assert state.plan.status == PlanStatus.BLOCKED
    assert not state.completed_step_keys
    assert [event["name"] for event in result.trace["events"]] == [
        "step.started", "plan.blocked",
    ]
    catalog_span = next(
        span for span in controller.telemetry.finished_spans()
        if span.name == "plan.step.execute"
    )
    rejected_event = next(
        event for event in catalog_span.events if event.name == "result.rejected"
    )
    assert rejected_event.attributes["business.status"] == "VALIDATION_FAILED"
    assert rejected_event.attributes["reason.code"] == "catalog_specification_mismatch"
    assert "step.completed" not in {event.name for event in catalog_span.events}


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("product_name", "改変商品名"),
        ("category", "altered-category"),
        ("unit_price", "1"),
        ("currency", "USD"),
        ("specifications", {"memory": "1GB"}),
    ],
)
async def test_catalog_candidate_values_must_match_evidence_snapshot(valid_request, field, value):
    catalog = RecordedCatalogAgent()

    async def mutated(payload):
        result = await catalog(payload)
        raw = result.model_dump(mode="json")
        raw["candidates"][0][field] = value
        return raw

    codes = RecordedCodeAgent()
    result = await ProcurementController(mutated, codes).execute(
        valid_request, session=AgentSession(), test_case_id=f"CATALOG-MUTATED-{field}",
    )

    assert result.scenario_id == "S4"
    assert result.business_status == BusinessStatus.BLOCKED
    assert result.status.parse_status == ParseStatus.SCHEMA_INVALID
    assert result.draft is None
    assert not codes.calls


@pytest.mark.anyio
async def test_budget_rejection_preserves_execution_events(valid_request):
    request = valid_request.model_copy(update={
        "constraints": valid_request.constraints.model_copy(update={
            "budget_limit": Decimal("100000"),
        }),
    })
    result = await ProcurementController(
        RecordedCatalogAgent(), RecordedCodeAgent(),
    ).execute(request, session=AgentSession(), test_case_id="BUDGET-REJECTED")

    assert result.business_status == BusinessStatus.VALIDATION_FAILED
    assert result.status.reason_code == "budget_limit_exceeded"
    assert result.trace["events"]
    assert result.trace["events"][-1]["name"] == "plan.blocked"
    assert [event["name"] for event in result.trace["events"]].count("step.completed") == 2


@pytest.mark.anyio
async def test_catalog_success_without_matching_evidence_is_rejected(valid_request):
    healthy = RecordedCatalogAgent()
    code = RecordedCodeAgent()
    async def ungrounded(payload):
        result = await healthy(payload)
        raw = result.model_dump(mode="json")
        raw["evidence"] = []
        return raw
    session = AgentSession()
    result = await ProcurementController(ungrounded, code).execute(
        valid_request, session=session, test_case_id="CATALOG-EVIDENCE-MISSING"
    )
    assert result.scenario_id == "S4"
    assert result.technical_status == TechnicalStatus.SUCCESS
    assert result.business_status == BusinessStatus.BLOCKED
    assert result.status.parse_status == "SCHEMA_INVALID"
    assert load_execution_state(session).plan.status == PlanStatus.BLOCKED
    assert load_execution_state(session).last_machine_response["reason_code"] == "child_output_schema_invalid"
    assert len(healthy.calls) == 1
    assert not code.calls


@pytest.mark.anyio
async def test_catalog_infrastructure_failure_after_not_found_retry_is_blocked(valid_request):
    not_found = RecordedCatalogAgent("catalog-not-found.json")
    calls = 0

    async def catalog_sequence(payload):
        nonlocal calls
        calls += 1
        if calls == 1:
            return await not_found(payload)
        value = CatalogSearchInput.model_validate(payload)
        return CatalogSearchResult(
            correlation=value.correlation,
            status=OperationStatus(
                http_status=200,
                technical_status=TechnicalStatus.ERROR,
                mcp_status=McpStatus.TIMEOUT,
                search_status=SearchStatus.NOT_RUN,
                parse_status=ParseStatus.NOT_RUN,
                business_status=BusinessStatus.BLOCKED,
                failure_layer=FailureLayer.MCP,
                retryable=True,
                reason_code="mcp_timeout",
            ),
        )

    result = await ProcurementController(catalog_sequence, RecordedCodeAgent()).execute(
        valid_request, session=AgentSession(), test_case_id="CATALOG-RETRY-INFRA",
    )
    assert result.scenario_id == "S2"
    assert result.technical_status == TechnicalStatus.ERROR
    assert result.business_status == BusinessStatus.BLOCKED
    assert "Toolbox/Search/parse/validation" in result.next_action
    assert calls == 2


@pytest.mark.anyio
async def test_code_success_requires_account_and_department_evidence():
    input_payload = json.loads(
        (Path(__file__).parents[1] / "fixtures/scenarios/s4-complete.json").read_text(encoding="utf-8")
    )
    healthy = await RecordedCodeAgent()(CodeDeterminationInput.model_validate(input_payload))
    payload = healthy.model_dump(mode="json")
    payload["evidence"] = [
        item for item in payload["evidence"] if item["record_type"] == "account_code"
    ]
    with pytest.raises(ValidationError, match="account and department evidence"):
        CodeDeterminationResult.model_validate(payload)


@pytest.mark.anyio
async def test_child_result_correlation_change_is_terminal_blocked(valid_request):
    healthy = RecordedCatalogAgent()

    async def forged_correlation(payload):
        result = await healthy(payload)
        raw = result.model_dump(mode="json")
        raw["correlation"]["test_case_id"] = "FORGED-CASE"
        return raw

    session = AgentSession()
    result = await ProcurementController(forged_correlation, RecordedCodeAgent()).execute(
        valid_request, session=session, test_case_id="CORRELATION-ORIGINAL",
    )
    assert result.technical_status == TechnicalStatus.SUCCESS
    assert result.business_status == BusinessStatus.BLOCKED
    assert result.status.failure_layer == FailureLayer.VALIDATION
    assert result.status.reason_code == "child_correlation_mismatch"
    state = load_execution_state(session)
    assert state.plan.status == PlanStatus.BLOCKED
    assert state.last_machine_response["outer_business_status"] == "BLOCKED"


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
