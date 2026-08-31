from __future__ import annotations

import asyncio
import os

import pytest
from agent_framework.openai import OpenAIChatClient
from azure.identity.aio import DefaultAzureCredential

from procurement_agent.intake import LlmProcurementIntake
from procurement_agent.observability import TelemetryRecorder


pytestmark = [
    pytest.mark.external,
    pytest.mark.skipif(
        os.getenv("PROCUREMENT_RUN_EXTERNAL_LLM") != "1",
        reason=(
            "set PROCUREMENT_RUN_EXTERNAL_LLM=1 with Azure OpenAI endpoint, "
            "model deployment, and DefaultAzureCredential configuration"
        ),
    ),
]


def test_azure_openai_structured_intake_smoke() -> None:
    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
    model = os.environ["AZURE_OPENAI_CHAT_MODEL"]

    async def run() -> None:
        credential = DefaultAzureCredential()
        client = OpenAIChatClient(
            model=model,
            azure_endpoint=endpoint,
            credential=credential,
        )
        telemetry = TelemetryRecorder(
            synthetic_environment=True,
            record_raw_content=False,
        )
        intake = LlmProcurementIntake(client, telemetry=telemetry)
        try:
            result = await intake.extract(
                "開発用ノートPCを3台購入したい",
                current_request=None,
                expected_fields=["request.query"],
            )
            assert result.intent == "UPDATE_REQUEST"
            assert result.request_patch.query is not None
            assert "ノートPC" in result.request_patch.query
            assert result.request_patch.quantity == 3
            assert [span.name for span in telemetry.finished_spans()] == [
                "agent.intake"
            ]
            assert telemetry.content_store == {}
        finally:
            await client.client.close()
            await credential.close()

    asyncio.run(run())
