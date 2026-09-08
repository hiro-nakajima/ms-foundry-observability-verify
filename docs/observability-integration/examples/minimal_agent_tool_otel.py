"""Migration example for agent-framework-core 1.16.0; no Azure calls on import.

plan(context, state): awaitable yielding validated steps (id, tool, payload).
execute(step, session, state): awaitable returning a validated business result.
apply_result(context, state, step, result): apply existing state/response rules;
return True when execution must stop (waiting for user, failure, completion).
These callbacks represent the destination sample's existing business logic.
"""
from contextlib import contextmanager
import json

from agent_framework import ContextProvider, FunctionInvocationContext
from opentelemetry import trace
from opentelemetry.trace import StatusCode


@contextmanager
def observed(name, **attributes):
    # Reuse the process provider configured by ResponsesHostServer.
    with trace.get_tracer("sample.procurement").start_as_current_span(
        name, attributes=attributes, record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield span
        except Exception as exc:
            span.set_attribute("error.type", type(exc).__name__)
            span.set_status(StatusCode.ERROR)
            raise


async def invoke_agent_tool(tool, payload, session):
    # payload must follow the called Agent's input contract.
    arguments = {"task": json.dumps(payload, ensure_ascii=False)}
    return await tool.invoke(
        arguments=arguments,
        context=FunctionInvocationContext(
            function=tool, arguments=arguments, session=session,
        ),
        skip_parsing=True,
    )


class ExampleExecutor(ContextProvider):
    """Adapt these boundaries into the existing Executor, not a second pipeline."""

    def __init__(self, *, plan, execute, apply_result):
        super().__init__("sample-executor")
        self.plan, self.execute, self.apply_result = plan, execute, apply_result

    async def before_run(self, *, agent, session, context, state):
        with observed("plan.create") as span:
            steps = await self.plan(context, state)
            span.set_attribute("plan.step.count", len(steps))

        for step in steps:
            with observed("plan.step.execute", **{
                "plan.step.id": step["id"],
                "execution.attempt": step.get("attempt", 1),
            }) as span:
                result = await self.execute(step, session, state)
                span.set_attribute("business.status", result["business_status"])
            if self.apply_result(context, state, step, result):
                break
