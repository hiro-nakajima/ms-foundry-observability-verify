"""Progress is emitted by executing providers, while Framework owns history."""

import asyncio
import json

from agent_framework import Agent, AgentSession, ContextProvider, InMemoryHistoryProvider
import pytest

from procurement_agent.framework import DeterministicChatClient
from procurement_agent.models import BusinessStatus, ScenarioResult, TechnicalStatus
from procurement_agent.observability import request_correlation
from procurement_agent.progress import ProgressMiddleware, STATE_LABELS, STEP_LABELS, publish


@pytest.fixture(autouse=True)
def web_machine_contract():
    token = request_correlation.set({'app.client.contract': 'web-json-v1'})
    try:
        yield
    finally:
        request_correlation.reset(token)


def _result(case_id):
    return ScenarioResult(
        scenario_id="S1", test_case_id=case_id,
        technical_status=TechnicalStatus.SUCCESS,
        business_status=BusinessStatus.SUCCESS,
    )


def _progress(step, state):
    return {"step": step, "state": state, "message": f"{STEP_LABELS[step]}：{STATE_LABELS[state]}"}


class _WaitingProvider(ContextProvider):
    def __init__(self, steps):
        super().__init__("progress-test-provider")
        self.steps = steps
        self.gates = {key: asyncio.Event() for key in steps}
        self.entered = {key: asyncio.Event() for key in steps}
        self.cancelled = {key: asyncio.Event() for key in steps}
        self.completed = set()

    async def before_run(self, *, agent, session, context, state):
        key = context.input_messages[-1].text
        publish(self.steps[key], "started")
        self.entered[key].set()
        try:
            await self.gates[key].wait()
        except asyncio.CancelledError:
            self.cancelled[key].set()
            raise
        self.completed.add(key)
        publish(self.steps[key], "completed")


def _agent(provider):
    history = InMemoryHistoryProvider("progress-test-history")
    agent = Agent(
        DeterministicChatClient(lambda messages, _options: _result(messages[-1].text)),
        context_providers=[history, provider],
        middleware=[ProgressMiddleware()],
    )
    return agent, history


@pytest.mark.anyio
async def test_started_progress_arrives_while_provider_is_still_waiting():
    provider = _WaitingProvider({"S1-STREAM": "intake"})
    agent, _ = _agent(provider)
    stream = agent.run("S1-STREAM", session=agent.create_session(), stream=True)

    opening = await asyncio.wait_for(anext(stream), 2)
    started = await asyncio.wait_for(anext(stream), 2)
    assert opening.text == '{"progress":[\n'
    assert json.loads(started.text) == _progress("intake", "started")
    assert provider.entered["S1-STREAM"].is_set()
    assert not provider.completed
    provider.gates["S1-STREAM"].set()

    response = await asyncio.wait_for(stream.get_final_response(), 2)
    result = ScenarioResult.model_validate_json(response.text)
    assert result.test_case_id == "S1-STREAM"
    assert result.business_status == BusinessStatus.SUCCESS
    assert result.progress == [
        _progress("intake", "started"),
        _progress("intake", "completed"),
    ]
    assert len(response.messages) == 1
    assert response.text.count('"progress"') == 1
    assert len({update.message_id for update in stream.updates}) == 1


@pytest.mark.anyio
async def test_stream_finalizes_history_and_preserves_session_restore():
    provider = _WaitingProvider({"S1-HISTORY": "catalog"})
    provider.gates["S1-HISTORY"].set()
    agent, history = _agent(provider)
    session = agent.create_session()
    stream = agent.run("S1-HISTORY", session=session, stream=True)
    response = await asyncio.wait_for(stream.get_final_response(), 2)
    result = ScenarioResult.model_validate_json(response.text)

    restored = AgentSession.from_dict(session.to_dict())
    messages = await history.get_messages(
        restored.session_id, state=restored.state[history.source_id],
    )
    assert restored.session_id == session.session_id
    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[0].text == "S1-HISTORY"
    stored = ScenarioResult.model_validate_json(messages[1].text)
    assert stored == result.model_copy(update={"progress": []})
    assert provider.completed == {"S1-HISTORY"}
    # Repeated final access must not execute the provider or duplicate history.
    assert await stream.get_final_response() is response
    assert len(await history.get_messages(
        session.session_id, state=session.state[history.source_id],
    )) == 2


@pytest.mark.anyio
async def test_concurrent_runs_keep_progress_in_their_own_session():
    provider = _WaitingProvider({"S1-CATALOG": "catalog", "S1-CODE": "code"})
    agent, history = _agent(provider)
    sessions = {key: agent.create_session() for key in provider.steps}
    streams = {
        key: agent.run(key, session=session, stream=True)
        for key, session in sessions.items()
    }
    pending = {
        key: asyncio.create_task(stream.get_final_response())
        for key, stream in streams.items()
    }
    try:
        for entered in provider.entered.values():
            await asyncio.wait_for(entered.wait(), 2)
        assert not any(task.done() for task in pending.values())
        provider.gates["S1-CODE"].set()
        code_response = await asyncio.wait_for(pending["S1-CODE"], 2)
        assert not pending["S1-CATALOG"].done()
        provider.gates["S1-CATALOG"].set()
        catalog_response = await asyncio.wait_for(pending["S1-CATALOG"], 2)
        for key, response in (("S1-CATALOG", catalog_response), ("S1-CODE", code_response)):
            result = ScenarioResult.model_validate_json(response.text)
            assert result.test_case_id == key
            assert result.progress == [
                _progress(provider.steps[key], "started"),
                _progress(provider.steps[key], "completed"),
            ]
            session = sessions[key]
            messages = await history.get_messages(
                session.session_id, state=session.state[history.source_id],
            )
            assert messages[0].text == key
    finally:
        for task in pending.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending.values(), return_exceptions=True)


@pytest.mark.anyio
async def test_pending_pull_cancellation_reaches_waiting_provider():
    provider = _WaitingProvider({"S1-CANCEL": "intake"})
    agent, _ = _agent(provider)
    stream = agent.run("S1-CANCEL", session=agent.create_session(), stream=True)
    await asyncio.wait_for(anext(stream), 2)
    await asyncio.wait_for(anext(stream), 2)
    pull = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    pull.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pull
    await asyncio.wait_for(provider.cancelled["S1-CANCEL"].wait(), 2)
    assert not provider.completed


@pytest.mark.anyio
async def test_non_streaming_keeps_original_result_and_history():
    provider = _WaitingProvider({"S1-NONSTREAM": "intake"})
    provider.gates["S1-NONSTREAM"].set()
    agent, history = _agent(provider)
    session = agent.create_session()
    response = await asyncio.wait_for(agent.run("S1-NONSTREAM", session=session), 2)
    assert ScenarioResult.model_validate_json(response.text) == _result("S1-NONSTREAM")
    messages = await history.get_messages(
        session.session_id, state=session.state[history.source_id],
    )
    assert len(messages) == 2
