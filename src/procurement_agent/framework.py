"""Microsoft Agent Framework bridges used by the local Hosted scaffold."""

from __future__ import annotations

import inspect
import json
from collections.abc import AsyncIterable, Callable, Mapping, Sequence
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from agent_framework import (
    AgentSession as FrameworkAgentSession,
    BaseChatClient,
    ChatResponse,
    ChatResponseUpdate,
    ContextProvider,
    Message,
    ResponseStream,
    SessionContext,
)

from .memory import AgentSession
from .models import AgentPlanResponse, LogicalPattern, ProcurementRequest
from .plan import StructuredPlanBuilder


Handler = Callable[[Sequence[Message], Mapping[str, Any]], Any]
LOCAL_RESPONSE_MARKER = "LOCAL_EXECUTION_RESPONSE::"
LOCAL_RESPONSE_END_MARKER = "::END_LOCAL_EXECUTION_RESPONSE"


class DeterministicChatClient(BaseChatClient):
    """A no-network client for Agent Framework integration and DevUI tests.

    It deliberately implements the same streaming path used by ``Agent.as_tool``.
    This is a local adapter, not a demo-only agent implementation: orchestration,
    tools, skill scripts, policy, session, and telemetry remain application-owned.
    """

    OTEL_PROVIDER_NAME = "procurement-local-deterministic"

    def __init__(self, handler: Handler, *, client_name: str) -> None:
        super().__init__(additional_properties={"client_name": client_name})
        self.handler = handler
        self.client_name = client_name
        self.calls: list[dict[str, Any]] = []

    async def _resolve(self, messages: Sequence[Message], options: Mapping[str, Any]) -> Any:
        result = self.handler(messages, options)
        if inspect.isawaitable(result):
            result = await result
        return result

    @staticmethod
    def _text_and_value(result: Any) -> tuple[str, BaseModel | None]:
        if isinstance(result, BaseModel):
            return result.model_dump_json(), result
        if isinstance(result, str):
            return result, None
        return json.dumps(result, ensure_ascii=False, sort_keys=True, default=str), None

    def _inner_get_response(
        self,
        *,
        messages: Sequence[Message],
        stream: bool,
        options: Mapping[str, Any],
        **kwargs: Any,
    ):
        self.calls.append(
            {
                "message_count": len(messages),
                "response_format": getattr(options.get("response_format"), "__name__", None),
                "tool_choice": options.get("tool_choice"),
                "tool_count": len(options.get("tools") or []),
                "stream": stream,
            }
        )
        response_id = f"local-response-{uuid4()}"
        if not stream:

            async def get_response() -> ChatResponse:
                result = await self._resolve(messages, options)
                text, value = self._text_and_value(result)
                return ChatResponse(
                    messages=[Message(role="assistant", contents=[text])],
                    response_id=response_id,
                    value=value,
                    response_format=options.get("response_format"),
                    finish_reason="stop",
                )

            return get_response()

        async def updates() -> AsyncIterable[ChatResponseUpdate]:
            result = await self._resolve(messages, options)
            text, _ = self._text_and_value(result)
            yield ChatResponseUpdate(
                role="assistant",
                contents=[{"type": "text", "text": text}],
                response_id=response_id,
                finish_reason="stop",
            )

        return self._build_response_stream(updates(), response_format=options.get("response_format"))


class StructuredPlannerHandler:
    """Produce the approved plan schema for the local no-network model client."""

    def __init__(self, pattern: LogicalPattern, *, return_empty: bool = False) -> None:
        self.pattern = pattern
        self.return_empty = return_empty

    def __call__(self, messages: Sequence[Message], options: Mapping[str, Any]) -> AgentPlanResponse:
        if options.get("response_format") is not AgentPlanResponse:
            raise ValueError("planner invocation must use AgentPlanResponse as response_format")
        if options.get("tool_choice") != "none" or options.get("tools"):
            raise ValueError("planner invocation must not combine structured output with tools")
        if self.return_empty:
            return AgentPlanResponse()
        request = ProcurementRequest.model_validate_json(messages[-1].text)
        plan = StructuredPlanBuilder().build(request, self.pattern)
        return AgentPlanResponse(
            goal=plan.goal,
            missing_required_fields=request.missing_required_fields(),
            steps=[
                {
                    "step_id": step.step_id,
                    "step_type": step.step_type,
                    "owner": step.owner,
                    "input_refs": step.input_refs,
                }
                for step in plan.steps
            ],
        )


def marker_response_handler(messages: Sequence[Message], options: Mapping[str, Any]) -> str:
    """Return the deterministic result injected by the serialized context provider."""

    instructions = options.get("instructions")
    instruction_values = instructions if isinstance(instructions, list) else [instructions]
    for value in reversed(instruction_values):
        if isinstance(value, str) and LOCAL_RESPONSE_MARKER in value:
            return value.split(LOCAL_RESPONSE_MARKER, 1)[1].split(LOCAL_RESPONSE_END_MARKER, 1)[0]
    for message in reversed(messages):
        if LOCAL_RESPONSE_MARKER in message.text:
            return message.text.split(LOCAL_RESPONSE_MARKER, 1)[1].split(
                LOCAL_RESPONSE_END_MARKER, 1
            )[0]
    return (
        "Local Hosted scaffold is ready. Submit one ProcurementRequest JSON object; "
        "natural-language model parsing requires a configured Foundry model client."
    )


class SerializedProcurementContextProvider(ContextProvider):
    """Persist the application-owned session inside Agent Framework session state.

    The provider owns no process-local conversation memory.  A hosted reconnect can
    restore the Framework ``AgentSession`` and then restore the procurement session
    from its JSON value.  Child agents do not receive this provider; they receive a
    ``ProcurementContextSnapshot`` through structured Agent Tool input instead.
    """

    STATE_KEY = "serialized_procurement_session"

    def __init__(self) -> None:
        super().__init__(source_id="procurement-execution-context")
        self._run_request: Callable[..., Any] | None = None

    def bind(self, run_request: Callable[..., Any]) -> None:
        self._run_request = run_request

    @staticmethod
    def _last_user_text(context: SessionContext) -> str:
        for message in reversed(context.input_messages):
            if str(message.role) in {"user", "Role.USER"}:
                return message.text
        return context.input_messages[-1].text if context.input_messages else ""

    async def before_run(
        self,
        *,
        agent: Any,
        session: FrameworkAgentSession,
        context: SessionContext,
        state: dict[str, Any],
    ) -> None:
        if self._run_request is None:
            return
        raw = self._last_user_text(context)
        try:
            request = ProcurementRequest.model_validate_json(raw)
        except ValidationError as exc:
            response = {
                "business_status": "INVALID_INPUT",
                "message": "ProcurementRequest JSON is required in local deterministic mode.",
                "schema_errors": exc.error_count(),
            }
            context.extend_instructions(
                self.source_id,
                LOCAL_RESPONSE_MARKER
                + json.dumps(response, ensure_ascii=False, sort_keys=True)
                + LOCAL_RESPONSE_END_MARKER,
            )
            return

        restored: AgentSession | None = None
        if serialized := state.get(self.STATE_KEY):
            restored = AgentSession.restore(serialized)
        same_request = bool(restored and restored.request == request)
        resume = bool(
            restored
            and restored.request
            and restored.request.request_id == request.request_id
            and restored.plan
            and (
                restored.plan.status.value == "WAITING_USER"
                or (restored.plan.status.value == "COMPLETED" and same_request)
            )
        )
        outcome = self._run_request(request, session=restored, resume=resume)
        if inspect.isawaitable(outcome):
            outcome = await outcome
        state[self.STATE_KEY] = outcome.session.serialize()
        state["last_status"] = outcome.status_summary
        context.extend_instructions(
            self.source_id,
            LOCAL_RESPONSE_MARKER + outcome.response_text + LOCAL_RESPONSE_END_MARKER,
        )

    async def after_run(
        self,
        *,
        agent: Any,
        session: FrameworkAgentSession,
        context: SessionContext,
        state: dict[str, Any],
    ) -> None:
        if context.response is not None:
            state["last_framework_response_id"] = context.response.response_id
