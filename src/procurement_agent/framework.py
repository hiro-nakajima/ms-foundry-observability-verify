"""Small no-network chat client used only for parent scaffolding and contract tests."""

from __future__ import annotations

import inspect
import json
from collections.abc import AsyncIterable, Callable, Mapping, Sequence
from typing import Any
from uuid import uuid4

from agent_framework import BaseChatClient, ChatResponse, ChatResponseUpdate, Message
from pydantic import BaseModel

Handler = Callable[[Sequence[Message], Mapping[str, Any]], Any]


class DeterministicChatClient(BaseChatClient):
    """Framework-compatible client; it does not model a child Prompt Agent."""

    OTEL_PROVIDER_NAME = "procurement-local-parent"

    def __init__(self, handler: Handler, *, client_name: str = "local-parent") -> None:
        super().__init__(additional_properties={"client_name": client_name})
        self.handler = handler
        self.calls: list[dict[str, Any]] = []

    async def _resolve(self, messages: Sequence[Message], options: Mapping[str, Any]) -> Any:
        value = self.handler(messages, options)
        return await value if inspect.isawaitable(value) else value

    @staticmethod
    def _text(value: Any) -> tuple[str, BaseModel | None]:
        if isinstance(value, BaseModel):
            return value.model_dump_json(), value
        if isinstance(value, str):
            return value, None
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str), None

    def _inner_get_response(self, *, messages, stream, options, **kwargs):
        self.calls.append({"message_count": len(messages), "response_format": getattr(options.get("response_format"), "__name__", None), "tool_count": len(options.get("tools") or []), "stream": stream})
        response_id = f"local-response-{uuid4()}"
        if not stream:
            async def response() -> ChatResponse:
                value = await self._resolve(messages, options)
                text, model = self._text(value)
                return ChatResponse(messages=[Message(role="assistant", contents=[text])], response_id=response_id, value=model, response_format=options.get("response_format"), finish_reason="stop")
            return response()

        async def updates() -> AsyncIterable[ChatResponseUpdate]:
            value = await self._resolve(messages, options)
            text, _ = self._text(value)
            yield ChatResponseUpdate(role="assistant", contents=[{"type": "text", "text": text}], response_id=response_id, finish_reason="stop")
        return self._build_response_stream(updates(), response_format=options.get("response_format"))


def local_parent_handler(messages: Sequence[Message], options: Mapping[str, Any]) -> str:
    return "購買申請Agent v2は起動済みです。Controllerへ構造化された依頼を送信してください。"
