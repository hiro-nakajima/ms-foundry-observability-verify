from agent_framework import Agent, AgentSession, InMemoryHistoryProvider

from procurement_agent.session_state import (
    EXECUTION_STATE_KEY,
    ProcurementExecutionState,
    SessionRequiredError,
    SessionStateSchemaError,
    initialize_execution_state,
    load_execution_state,
    restore_framework_session,
    save_execution_state,
)


def test_explicit_history_provider_and_framework_session_are_sources_of_truth() -> None:
    provider = InMemoryHistoryProvider("procurement-history", load_messages=True)
    agent = Agent(client=object(), context_providers=[provider])
    session = agent.create_session()
    state = initialize_execution_state(session, test_case_id="S1-HISTORY")
    state.turn_number = 2
    save_execution_state(session, state)

    restored = restore_framework_session(session.to_dict())

    assert isinstance(restored, AgentSession)
    assert load_execution_state(restored).turn_number == 2
    assert [item.source_id for item in agent.context_providers] == ["procurement-history"]
    assert agent.context_providers[0].load_messages is True


def test_execution_state_is_a_json_compatible_dict_not_nested_session_json() -> None:
    session = AgentSession()
    initialize_execution_state(session)

    assert isinstance(session.state[EXECUTION_STATE_KEY], dict)
    assert "serialized_procurement_session" not in session.state
    ProcurementExecutionState.model_validate(session.state[EXECUTION_STATE_KEY])


def test_missing_session_fails_closed() -> None:
    try:
        load_execution_state(None)
    except SessionRequiredError as exc:
        assert "session is required" in str(exc)
    else:
        raise AssertionError("missing session must fail closed")


def test_schema_version_mismatch_fails_closed() -> None:
    session = AgentSession()
    session.state[EXECUTION_STATE_KEY] = {"schema_version": "1.0"}

    try:
        load_execution_state(session)
    except SessionStateSchemaError:
        pass
    else:
        raise AssertionError("invalid state must fail closed")
