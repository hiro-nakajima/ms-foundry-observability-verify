"""Synthetic-only Azure Core validation inside the Hosted parent boundary."""

from __future__ import annotations

import json
from types import MappingProxyType
from typing import Any, Final, Literal

from agent_framework import AgentSession

from trace_pipeline.detectors import DetectionOutcome, detect, evaluate_all
from trace_pipeline.stage_b import (
    StageBHealthyControlHarness,
    StageBInjectionHarness,
    derive_trace_facts,
)

from .models import ProcurementRequest, RequestConstraints, ScenarioResult
from .observability import TelemetryRecorder, sanitize_attributes


ValidationProfile = Literal[
    "TV-02", "TV-03", "SD-03", "SD-05", "MA-04", "MA-05",
    "S1-HEALTHY", "S5-HEALTHY", "S5-SMALL", "S5-32768", "S5-65536",
    "S5-OVER",
]
INJECTION_PROFILES: Final = frozenset({
    "TV-02", "TV-03", "SD-03", "SD-05", "MA-04", "MA-05",
})
S5_BOUNDARY_CHARS: Final = MappingProxyType({
    "S5-SMALL": 128,
    "S5-HEALTHY": 8192,
    "S5-32768": 32768,
    "S5-65536": 65536,
    "S5-OVER": 65537,
})
VALIDATION_PROFILES: Final = frozenset({
    *INJECTION_PROFILES, "S1-HEALTHY", *S5_BOUNDARY_CHARS,
})


def validation_request(profile: ValidationProfile, test_case_id: str) -> ProcurementRequest:
    """Build one synthetic request; no repository or employee data is accepted."""
    if profile not in VALIDATION_PROFILES:
        raise ValueError("validation profile is not allowlisted")
    if profile.startswith("SD-"):
        query, department = "存在しない量子端末", "開発部（架空部署）"
    elif profile.startswith("TV-"):
        query, department = "開発用ノートPC", "未登録部門（Stage B）"
    else:
        query, department = "開発用ノートPC", "開発部（架空部署）"
    memo = (
        "X" * S5_BOUNDARY_CHARS[profile]
        if profile in S5_BOUNDARY_CHARS
        else "Azure Core synthetic validation"
    )
    return ProcurementRequest(
        request_id=test_case_id,
        query=query,
        quantity=2,
        applicant_name="架空 検証者",
        department_name=department,
        memo=memo,
        constraints=RequestConstraints(
            budget_limit="400000", specifications={"memory": "32GB"},
        ),
    )


async def run_azure_validation(
    profile: ValidationProfile,
    *,
    catalog_invoker: Any,
    code_invoker: Any,
    session: AgentSession,
    test_case_id: str,
    telemetry: TelemetryRecorder,
    system_prompt: str,
    tool_definitions: list[dict[str, str]],
) -> ScenarioResult:
    """Execute a gated profile through real remote Prompt Agent invokers."""
    request = validation_request(profile, test_case_id)
    boundary_evidence = None
    if profile in S5_BOUNDARY_CHARS:
        encoded = request.memo.encode("utf-8")
        boundary_evidence = {
            "profile": profile,
            "sent_chars": len(request.memo),
            "sent_utf8_bytes": len(encoded),
            "sent_sha256": telemetry.protect_content(
                "s5_boundary", request.memo,
            )["sha256"],
        }
    if profile in INJECTION_PROFILES:
        artifact = await StageBInjectionHarness(
            profile,
            catalog_invoker=catalog_invoker,
            code_invoker=code_invoker,
            telemetry=telemetry,
        ).run(request, session=session, test_case_id=test_case_id)
        scenario_id = {"TV": "S2", "SD": "S3", "MA": "S4"}[profile[:2]]
    else:
        scenario_id = profile[:2]
        artifact = await StageBHealthyControlHarness(
            scenario_id,
            catalog_invoker=catalog_invoker,
            code_invoker=code_invoker,
            telemetry=telemetry,
        ).run(request, session=session, test_case_id=test_case_id)

    # Content-off still proves that the actual runtime configuration existed.
    # Only hashes and lengths, never prompts, schemas, or user content, are emitted.
    prompt_evidence = telemetry.protect_content("system_prompt", system_prompt)
    tools_evidence = telemetry.protect_content(
        "tool_definitions", json.dumps(tool_definitions, ensure_ascii=False, sort_keys=True),
    )
    artifact.system_prompt = prompt_evidence
    artifact.tool_definitions = [tools_evidence]
    facts = derive_trace_facts(artifact)
    if profile in INJECTION_PROFILES:
        detections = [detect(
            profile,
            facts,
            injection_requested=True,
            injection_activated=artifact.injection_activated,
        )]
    else:
        detections = evaluate_all(facts)

    outcomes = [item.outcome.value for item in detections]
    overall = (
        DetectionOutcome.DETECTED.value
        if profile in INJECTION_PROFILES and outcomes == [DetectionOutcome.DETECTED.value]
        else DetectionOutcome.NOT_DETECTED.value
        if profile not in INJECTION_PROFILES and set(outcomes) == {DetectionOutcome.NOT_DETECTED.value}
        else outcomes[0] if len(set(outcomes)) == 1 else "MIXED"
    )
    missing = sorted({field for item in detections for field in item.missing_trace_fields})
    expected = (
        DetectionOutcome.DETECTED.value
        if profile in INJECTION_PROFILES else DetectionOutcome.NOT_DETECTED.value
    )
    evidence_refs = sorted({
        str(item.get("evidence_id")) for item in artifact.retrieved_contexts
        if item.get("evidence_id")
    })
    validation = {
        "contract": "stage-b-v1",
        "profile": profile,
        "scenario_id": scenario_id,
        "failure_pattern_id": profile if profile in INJECTION_PROFILES else None,
        "expected_label": expected,
        "actual_label": overall,
        "injection_requested": profile in INJECTION_PROFILES,
        "injection_activated": artifact.injection_activated,
        "trace_complete": not missing,
        "evidence_refs": evidence_refs,
        "detector_version": "1.0",
        "facts": facts.model_dump(mode="json"),
        "detections": [item.model_dump(mode="json") for item in detections],
        "configuration": {"system_prompt": prompt_evidence, "tool_definitions": tools_evidence},
    }
    if boundary_evidence is not None:
        validation["content_boundary"] = boundary_evidence
    attributes = sanitize_attributes({
        "app.validation.contract": "stage-b-v1",
        "app.validation.profile": profile,
        "app.validation.outcome": overall,
        "app.validation.injection_requested": profile in INJECTION_PROFILES,
        "app.validation.injection_activated": artifact.injection_activated,
        "app.validation.missing_trace_fields": missing,
        "app.validation.system_prompt.sha256": prompt_evidence["sha256"],
        "app.validation.tool_definitions.sha256": tools_evidence["sha256"],
        "app.validation.scenario_id": scenario_id,
        "app.validation.expected_label": expected,
        "app.validation.trace_complete": not missing,
        "app.validation.detector_version": "1.0",
        "app.validation.evidence_ref_count": len(evidence_refs),
        **({
            "app.validation.boundary.profile": boundary_evidence["profile"],
            "app.validation.boundary.synthetic": True,
            "app.validation.boundary.sent_chars": boundary_evidence["sent_chars"],
            "app.validation.boundary.sent_utf8_bytes": boundary_evidence["sent_utf8_bytes"],
            "app.validation.boundary.sent_sha256": boundary_evidence["sent_sha256"],
        } if boundary_evidence is not None else {}),
    })
    with telemetry.span("semantic.evaluate", attributes) as evaluation_span:
        telemetry.event(evaluation_span, "evaluation.completed", attributes)
        if boundary_evidence is not None:
            boundary_event_attributes = {
                key: value for key, value in attributes.items()
                if key.startswith("app.validation.boundary.")
            }
            # Synthetic-only fixed X payload. Never use user input, prompts, tool
            # output, PII, or CoT in either boundary-measurement channel.
            telemetry.event(evaluation_span, "content.boundary.property", {
                **boundary_event_attributes,
                "app.validation.boundary.channel": "property",
                "app.validation.boundary.synthetic_payload": request.memo,
            })
            telemetry.event(evaluation_span, request.memo, {
                **boundary_event_attributes,
                "app.validation.boundary.channel": "message",
            })
        span_context = evaluation_span.get_span_context()

    result_trace = {**artifact.result.trace, "validation": validation}
    if span_context.is_valid:
        result_trace.update({
            "trace_id": f"{span_context.trace_id:032x}",
            "span_id": f"{span_context.span_id:016x}",
        })
    return artifact.result.model_copy(update={
        "scenario_id": scenario_id,
        "test_case_id": test_case_id,
        "trace": result_trace,
        "injection_requested": profile if profile in INJECTION_PROFILES else None,
        "injection_activated": artifact.injection_activated,
    })
