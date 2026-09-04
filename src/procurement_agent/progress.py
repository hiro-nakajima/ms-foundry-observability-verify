"""Stream public execution milestones, never model reasoning or raw tool output."""
from __future__ import annotations

import asyncio
from contextlib import suppress
from contextvars import ContextVar
import json
from uuid import uuid4

from agent_framework import AgentMiddleware, AgentResponse, AgentResponseUpdate, Content, ResponseStream

from .models import ScenarioResult
from .observability import current_request_attributes

_sink: ContextVar[asyncio.Queue | None] = ContextVar('procurement_progress', default=None)
STEPS = {'intake', 'catalog', 'code', 'merge_validate'}
STATES = {'started', 'completed', 'retry', 'waiting_user', 'blocked'}
STEP_LABELS = {
    'intake': '依頼内容の整理・実行計画',
    'catalog': '商品の検索・仕様照合',
    'code': '勘定科目・部署コードの照会',
    'merge_validate': '申請案・予算の検証',
}
STATE_LABELS = {
    'started': '開始しました',
    'completed': '完了しました',
    'retry': '再試行します',
    'waiting_user': '回答をお待ちしています',
    'blocked': '停止しました',
}


def publish(step: str, state: str) -> None:
    queue = _sink.get()
    if queue is not None and step in STEPS and state in STATES:
        queue.put_nowait({
            'step': step,
            'state': state,
            'message': f'{STEP_LABELS[step]}：{STATE_LABELS[state]}',
        })


class ProgressMiddleware(AgentMiddleware):
    async def process(self, context, call_next):
        # The Web App opts into the machine envelope used for safe status and
        # progress projection. Playground and other callers receive the normal
        # natural-language stream from the Hosted Agent.
        if (not context.stream
                or current_request_attributes().get('app.client.contract') != 'web-json-v1'):
            await call_next()
            return

        async def updates():
            queue = asyncio.Queue()
            message_id = 'progress-' + str(uuid4())

            async def produce():
                token = _sink.set(queue)
                try:
                    async with asyncio.timeout(180):
                        await call_next()
                        inner = context.result
                        # Finalize the original stream, including Framework history/session hooks.
                        result = await inner.get_final_response()
                        parsed = ScenarioResult.model_validate_json(result.text)
                        queue.put_nowait(parsed)
                except Exception as exc:
                    queue.put_nowait(RuntimeError('Procurement execution failed: ' + type(exc).__name__))
                finally:
                    _sink.reset(token)

            producer = asyncio.create_task(produce())
            def delta(text):
                return AgentResponseUpdate(role='assistant', message_id=message_id, contents=[Content.from_text(text)])
            try:
                yield delta('{"progress":[\n')
                separator = ''
                while True:
                    item = await queue.get()
                    if isinstance(item, Exception):
                        raise item
                    if isinstance(item, ScenarioResult):
                        body = item.model_dump_json(exclude={'progress'})
                        yield delta('],\n' + body[1:])
                        break
                    yield delta(separator + json.dumps(item) + '\n')
                    separator = ','
            finally:
                producer.cancel()
                with suppress(asyncio.CancelledError):
                    await producer

        context.result = ResponseStream(updates(), finalizer=AgentResponse.from_updates)
