from agent_framework import AgentSession

from procurement_agent.observability import TelemetryRecorder, sanitize_attributes
from procurement_agent.plan import StructuredPlanBuilder
from procurement_agent.session_state import initialize_execution_state, save_execution_state
from trace_pipeline.envelope import RunIdentity
from trace_pipeline.normalize import build_envelope


def test_v3_envelope_uses_framework_session_and_no_logical_pattern():
    session = AgentSession()
    state = initialize_execution_state(session, test_case_id="TRACE-V3")
    state.turn_number = 2
    state.plan = StructuredPlanBuilder().build(None)
    save_execution_state(session, state)
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


def test_content_on_requires_explicit_synthetic_environment():
    import pytest
    with pytest.raises(ValueError, match="explicitly synthetic"):
        TelemetryRecorder(content_profile="synthetic-content-on")


def test_secret_token_and_chain_of_thought_attributes_are_removed():
    result = sanitize_attributes({
        "test.case.id": "SYNTHETIC", "api_token": "forbidden",
        "client_secret": "forbidden", "chain_of_thought": "forbidden",
    })
    assert result == {"test.case.id": "SYNTHETIC"}
