from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest
from pydantic import BaseModel

from procurement_agent.conversation import merge_natural_request
from procurement_agent.framework import DeterministicChatClient
from procurement_agent.intake import (
    DepartmentCandidateResolver,
    LlmIntakeConfigurationError,
    LlmProcurementIntake,
    ProcurementRequestPatch,
    ProcurementTurnExtraction,
    RequestConstraintsPatch,
    SpecificationPatch,
    structured_output_options,
)
from procurement_agent.models import ProcurementRequest, RequestConstraints
from procurement_agent.observability import TelemetryRecorder


def telemetry() -> TelemetryRecorder:
    return TelemetryRecorder(synthetic_environment=True, record_raw_content=False)


def test_intake_schema_uses_basemodel_and_has_safe_empty_defaults() -> None:
    assert issubclass(ProcurementTurnExtraction, BaseModel)
    empty = ProcurementTurnExtraction()
    assert empty.intent == "UPDATE_REQUEST"
    assert empty.request_patch.model_dump(exclude_none=True, exclude_defaults=True) == {}


def test_intake_schema_uses_closed_basemodel_entries_for_specifications() -> None:
    schema = ProcurementTurnExtraction.model_json_schema()
    specification_schema = schema["$defs"]["RequestConstraintsPatch"]["properties"][
        "specifications"
    ]
    assert specification_schema["type"] == "array"
    assert specification_schema["items"]["$ref"].endswith("/SpecificationPatch")
    assert schema["$defs"]["SpecificationPatch"]["additionalProperties"] is False


def test_structured_output_options_bound_gpt5_reasoning_and_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AZURE_OPENAI_REASONING_EFFORT", "minimal")
    monkeypatch.setenv("AZURE_OPENAI_MAX_OUTPUT_TOKENS", "2048")
    options = structured_output_options(ProcurementTurnExtraction)
    assert options == {
        "response_format": ProcurementTurnExtraction,
        "tool_choice": "none",
        "tools": [],
        "reasoning": {"effort": "minimal"},
        "max_tokens": 2048,
    }


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("AZURE_OPENAI_REASONING_EFFORT", "extreme"),
        ("AZURE_OPENAI_MAX_OUTPUT_TOKENS", "0"),
    ],
)
def test_structured_output_options_reject_invalid_bounds(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(LlmIntakeConfigurationError):
        structured_output_options(ProcurementTurnExtraction)


def test_natural_request_merge_converts_specification_entries_to_domain_mapping() -> None:
    patch = ProcurementRequestPatch(
        query="開発用ノートPC",
        constraints=RequestConstraintsPatch(
            specifications=[
                SpecificationPatch(key="memory", value="32GB"),
                SpecificationPatch(key="storage", value="1TB SSD"),
            ]
        ),
    )
    request, _ = merge_natural_request(patch)
    assert request is not None
    assert request.constraints.specifications == {
        "memory": "32GB",
        "storage": "1TB SSD",
    }


def test_llm_intake_uses_basemodel_response_format_without_tools() -> None:
    def handler(messages, options):
        payload = json.loads(messages[-1].text)
        assert payload["current_user_input"] == "3台です"
        assert payload["confirmation_expected"] is False
        return ProcurementTurnExtraction(
            request_patch=ProcurementRequestPatch(quantity=3)
        )

    client = DeterministicChatClient(handler, client_name="intake-fixture")
    intake = LlmProcurementIntake(client, telemetry=telemetry())
    parsed = asyncio.run(
        intake.extract(
            "3台です",
            current_request=None,
            expected_fields=["quantity"],
        )
    )
    assert parsed.request_patch.quantity == 3
    assert client.calls[-1]["response_format"] == "ProcurementTurnExtraction"
    assert client.calls[-1]["tool_choice"] == "none"
    assert client.calls[-1]["tool_count"] == 0


def test_empty_llm_response_uses_default_patch() -> None:
    assert LlmProcurementIntake._parse_response(None, "") == ProcurementTurnExtraction()
    assert LlmProcurementIntake._parse_response(None, "   ") == ProcurementTurnExtraction()


def test_natural_request_merge_preserves_previous_turn_values() -> None:
    current = ProcurementRequest(
        request_id="REQ-NL-MERGE",
        query="開発用ノートPC",
        purpose="開発",
        constraints=RequestConstraints(specifications={"memory": "32GB"}),
    )
    patch = ProcurementRequestPatch.model_validate(
        {
            "quantity": 3,
            "applicant_name": "山田太郎",
            "constraints": {"requested_by": "2026-09-30"},
        }
    )
    request, _ = merge_natural_request(patch, current=current)
    assert request is not None
    assert request.request_id == "REQ-NL-MERGE"
    assert request.quantity == 3
    assert request.purpose == "開発"
    assert request.constraints.specifications == {"memory": "32GB"}
    assert request.constraints.requested_by == date(2026, 9, 30)


def test_department_resolver_returns_both_information_system_candidates(adapter) -> None:
    resolver = DepartmentCandidateResolver(adapter.departments)
    candidates = resolver.candidates("情報シス")
    assert [item["department_code"] for item in candidates] == [
        "DPT-IS-01",
        "DPT-IS-02",
    ]
    assert [item["department_code"] for item in resolver.candidates("1部")] == [
        "DPT-IS-01"
    ]


def test_natural_input_requires_an_llm_client() -> None:
    intake = LlmProcurementIntake(None, telemetry=telemetry())
    with pytest.raises(LlmIntakeConfigurationError):
        asyncio.run(
            intake.extract(
                "開発用ノートPC",
                current_request=None,
                expected_fields=["request.query"],
            )
        )


def test_intake_builds_azure_openai_client_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://synthetic.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_CHAT_MODEL", "synthetic-model-deployment")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "synthetic-test-key")
    intake = LlmProcurementIntake.from_environment(telemetry=telemetry())
    assert intake.client is not None
    assert type(intake.client).__name__ == "OpenAIChatClient"
