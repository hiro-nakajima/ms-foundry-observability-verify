from agent_framework import AgentSession, Message
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from procurement_agent.observability import TelemetryRecorder, sanitize_attributes
from procurement_agent.plan import StructuredPlanBuilder
from procurement_agent.session_state import initialize_execution_state, save_execution_state
from procurement_agent.models import (
    BusinessStatus, CatalogSearchResult, CorrelationContext, OperationStatus,
)
from trace_pipeline.envelope import RunIdentity
from trace_pipeline.normalize import build_envelope


def test_v3_envelope_uses_framework_session_and_no_logical_pattern():
    session = AgentSession()
    state = initialize_execution_state(session, test_case_id="TRACE-V3")
    state.turn_number = 2
    state.plan = StructuredPlanBuilder().build(None)
    state.catalog_result = CatalogSearchResult(
        correlation=CorrelationContext(
            test_case_id="TRACE-V3", framework_session_id=session.session_id,
            turn_number=2, plan_id=state.plan.plan_id, plan_version=1,
            step_id="catalog", attempt=1, remote_task_id="remote-task-1",
            parent_invocation_id="parent-invocation-1",
        ),
        status=OperationStatus(business_status=BusinessStatus.NOT_FOUND),
    )
    save_execution_state(session, state)
    session.state["messages"] = [Message(role="user", contents=["synthetic request"])]
    telemetry = TelemetryRecorder(content_profile="production-like-content-off")
    with telemetry.span("plan.create", {"test.case.id": "TRACE-V3"}):
        pass
    envelope = build_envelope(
        run=RunIdentity(run_id="run-1", case_id="TRACE-V3", agent_role="coordinator", agent_definition_name="procurement_parent_agent", agent_definition_version="1", implementation_kind="hosted_framework"),
        session=session, telemetry=telemetry,
        user_input=[{"sha256":"a"}], response={"sha256":"b"}, retrieved_contexts=[{"document_id":"d"}],
        system_prompt={"version":"1"}, tool_definitions=[{"name":"catalog_search_agent"}],
        tool_calls=[{"name":"catalog_search_agent"}], tool_output=[{"status":"SUCCESS"}],
    )
    payload = envelope.model_dump(mode="json")
    assert payload["schema_version"] == "3.0"
    assert payload["run"]["architecture_id"] == "procurement_application_v2"
    assert "logical_pattern" not in str(payload)
    assert payload["session"]["turn_number"] == 2
    assert payload["content_profile"] == "production-like-content-off"
    assert payload["conversation"][0]["role"] == "user"
    assert payload["conversation"][0]["length"] > 0
    assert "raw" not in payload["conversation"][0]
    assert payload["correlation"]["trace_id"]
    assert payload["correlation"]["span_id"]
    assert payload["correlation"]["parent_invocation_id"] == "parent-invocation-1"
    assert payload["correlation"]["remote_task_id"] == "remote-task-1"
    assert payload["correlation"]["child_invocations"][0]["step_id"] == "catalog"


def test_v3_envelope_scopes_reused_recorder_to_current_case():
    session = AgentSession()
    state = initialize_execution_state(session, test_case_id="TRACE-CASE-2")
    state.turn_number = 2
    state.plan = StructuredPlanBuilder().build(None)
    save_execution_state(session, state)
    telemetry = TelemetryRecorder()
    with telemetry.span("plan.create", {"test.case.id": "TRACE-CASE-1"}):
        pass
    with telemetry.span("plan.create", {"test.case.id": "TRACE-CASE-2"}) as current:
        pass

    envelope = build_envelope(
        run=RunIdentity(run_id="run-2", case_id="TRACE-CASE-2", agent_role="coordinator", agent_definition_name="procurement_parent_agent", agent_definition_version="1", implementation_kind="hosted_framework"),
        session=session, telemetry=telemetry,
        user_input=[], response={}, retrieved_contexts=[], system_prompt={},
        tool_definitions=[], tool_calls=[], tool_output=[],
    )

    assert len(envelope.agent_trace.spans) == 1
    assert envelope.agent_trace.spans[0]["attributes"]["test.case.id"] == "TRACE-CASE-2"
    assert envelope.correlation.trace_id == f"{current.context.trace_id:032x}"


def test_content_on_requires_explicit_synthetic_environment():
    import pytest
    with pytest.raises(ValueError, match="explicitly synthetic"):
        TelemetryRecorder(content_profile="synthetic-content-on")


def test_hosted_recorder_emits_to_supplied_runtime_provider():
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    telemetry = TelemetryRecorder(tracer_provider=provider)
    with telemetry.span("plan.create", {"test.case.id": "HOSTED-EXPORT"}):
        pass
    assert telemetry.uses_global_provider is True
    assert [item.name for item in exporter.get_finished_spans()] == ["plan.create"]


def test_secret_token_and_chain_of_thought_attributes_are_removed():
    result = sanitize_attributes({
        "test.case.id": "SYNTHETIC", "api_token": "forbidden",
        "client_secret": "forbidden", "chain_of_thought": "forbidden",
    })
    assert result == {"test.case.id": "SYNTHETIC"}
