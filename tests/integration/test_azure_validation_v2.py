import json
from types import SimpleNamespace

import pytest
from agent_framework import AgentSession

from procurement_agent.azure_validation import (
    INJECTION_PROFILES, S5_BOUNDARY_CHARS, run_azure_validation,
    validation_request,
)
from procurement_agent.observability import TelemetryRecorder, sha256
from scripts.run_s5_boundary_validation import _safe_result
from tests.fixtures.fake_agents import RecordedCatalogAgent, RecordedCodeAgent


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("profile", "catalog_fixture", "code_fixture", "expected"),
    [
        ("TV-02", "catalog-healthy.json", "code-not-found.json", "DETECTED"),
        ("TV-03", "catalog-healthy.json", "code-business-invalid.json", "DETECTED"),
        ("SD-03", "catalog-not-found.json", "code-healthy.json", "DETECTED"),
        ("SD-05", "catalog-not-found.json", "code-healthy.json", "DETECTED"),
        ("MA-04", "catalog-healthy.json", "code-healthy.json", "DETECTED"),
        ("MA-05", "catalog-healthy.json", "code-healthy.json", "DETECTED"),
        ("S1-HEALTHY", "catalog-healthy.json", "code-healthy.json", "NOT_DETECTED"),
        ("S5-HEALTHY", "catalog-healthy.json", "code-healthy.json", "NOT_DETECTED"),
        ("S5-SMALL", "catalog-healthy.json", "code-healthy.json", "NOT_DETECTED"),
        ("S5-32768", "catalog-healthy.json", "code-healthy.json", "NOT_DETECTED"),
        ("S5-65536", "catalog-healthy.json", "code-healthy.json", "NOT_DETECTED"),
        ("S5-OVER", "catalog-healthy.json", "code-healthy.json", "NOT_DETECTED"),
    ],
)
async def test_gated_azure_validation_contract(
    profile, catalog_fixture, code_fixture, expected,
):
    telemetry = TelemetryRecorder()
    case = f"AZURE-CORE-{profile}"
    with telemetry.tracer.start_as_current_span("invoke_agent"):
        result = await run_azure_validation(
            profile,
            catalog_invoker=RecordedCatalogAgent(catalog_fixture),
            code_invoker=RecordedCodeAgent(code_fixture),
            session=AgentSession(),
            test_case_id=case,
            telemetry=telemetry,
            system_prompt="synthetic system prompt",
            tool_definitions=[{"name": "catalog"}, {"name": "code"}],
        )

    validation = result.trace["validation"]
    assert validation["profile"] == profile
    assert validation["expected_label"] == expected
    assert validation["actual_label"] == expected
    assert validation["trace_complete"] is True
    assert validation["detector_version"] == "1.0"
    assert "raw" not in validation["configuration"]["system_prompt"]
    assert "raw" not in validation["configuration"]["tool_definitions"]
    evaluation_spans = [
        span for span in telemetry.finished_spans()
        if span.name == "semantic.evaluate"
    ]
    assert len(evaluation_spans) == 1
    evaluation_span = evaluation_spans[0]
    assert evaluation_span.attributes["app.validation.outcome"] == expected
    assert not any(
        span.name == "content.boundary.measure"
        for span in telemetry.finished_spans()
    )
    if profile in S5_BOUNDARY_CHARS:
        expected_chars = S5_BOUNDARY_CHARS[profile]
        assert validation["content_boundary"] == {
            "profile": profile,
            "sent_chars": expected_chars,
            "sent_utf8_bytes": expected_chars,
            "sent_sha256": sha256("X" * expected_chars),
        }
        assert "raw" not in validation["content_boundary"]
        assert "synthetic_payload" not in validation["content_boundary"]
        boundary = evaluation_span.attributes
        assert boundary["app.validation.boundary.profile"] == profile
        assert boundary["app.validation.boundary.synthetic"] is True
        assert boundary["app.validation.boundary.sent_chars"] == expected_chars
        assert boundary["app.validation.boundary.sent_utf8_bytes"] == expected_chars
        assert boundary["app.validation.boundary.sent_sha256"] == sha256("X" * expected_chars)
        assert [event.name for event in evaluation_span.events] == [
            "evaluation.completed", "content.boundary.property", "X" * expected_chars,
        ]
        property_event = evaluation_span.events[1]
        message_event = evaluation_span.events[2]
        assert property_event.attributes["app.validation.boundary.channel"] == "property"
        assert property_event.attributes[
            "app.validation.boundary.synthetic_payload"
        ] == "X" * expected_chars
        assert message_event.attributes["app.validation.boundary.channel"] == "message"
        assert "app.validation.boundary.synthetic_payload" not in message_event.attributes
        assert not any("payload" in key for key in evaluation_span.attributes)
        safe = _safe_result(
            profile=profile,
            case=case,
            conversation_id="conv_synthetic",
            response=SimpleNamespace(
                id="resp_synthetic",
                model_extra={"agent_session_id": "session_synthetic"},
            ),
            result=result,
        )
        serialized_safe = json.dumps(safe, ensure_ascii=False)
        assert "synthetic_payload" not in serialized_safe
        assert "X" * min(expected_chars, 128) not in serialized_safe
        assert safe["content_boundary"] == validation["content_boundary"]
    else:
        assert "content_boundary" not in validation
        assert [event.name for event in evaluation_span.events] == ["evaluation.completed"]
        assert not any(
            key.startswith("app.validation.boundary.")
            for key in evaluation_span.attributes
        )
    if profile not in INJECTION_PROFILES:
        assert len(validation["detections"]) == 14
        assert {item["outcome"] for item in validation["detections"]} == {"NOT_DETECTED"}
        assert result.injection_requested is None
        assert result.injection_activated is False
    else:
        assert len(validation["detections"]) == 1
        assert validation["detections"][0]["outcome"] == "DETECTED"
        assert result.injection_requested == profile
        assert result.injection_activated is True


def test_s5_boundary_profiles_have_fixed_lengths_and_no_arbitrary_size_parameter():
    assert S5_BOUNDARY_CHARS == {
        "S5-SMALL": 128,
        "S5-HEALTHY": 8192,
        "S5-32768": 32768,
        "S5-65536": 65536,
        "S5-OVER": 65537,
    }
    for profile, expected in S5_BOUNDARY_CHARS.items():
        assert len(validation_request(profile, f"AZURE-CORE-{profile}").memo) == expected
    with pytest.raises(ValueError, match="not allowlisted"):
        validation_request("S5-1234", "AZURE-CORE-S5-1234")
    with pytest.raises(TypeError):
        S5_BOUNDARY_CHARS["S5-1234"] = 1234
