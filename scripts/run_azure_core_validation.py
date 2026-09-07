#!/usr/bin/env python3
"""Run the approved Stage B injections and S1/S5 controls on Hosted Azure."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import sys

from azure.ai.projects import AIProjectClient
from azure.identity import AzureCliCredential

from procurement_agent.models import ScenarioResult
from procurement_agent.observability import sha256
from deploy_foundation import STATE, save
from deploy_foundry import ENDPOINT


PROFILES = (
    "TV-02", "TV-03", "SD-03", "SD-05", "MA-04", "MA-05",
    "S1-HEALTHY", "S5-HEALTHY",
)
TRACE_ID = re.compile(r"^[0-9a-f]{32}$")


def _safe_result(
    *, profile: str, case: str, conversation_id: str, response: object,
    result: ScenarioResult, expected_version: str,
) -> dict[str, object]:
    validation = result.trace.get("validation") or {}
    correlation = result.trace.get("correlation") or {}
    trace_id = result.trace.get("trace_id")
    detections = validation.get("detections") or []
    return {
        "profile": profile,
        "case": case,
        "foundry_conversation_id": conversation_id,
        "foundry_response_id": getattr(response, "id", None),
        "service_agent_session_id_hash": (
            sha256(str(service_session)) if (
                service_session := (getattr(response, "model_extra", None) or {}).get(
                    "agent_session_id"
                )
            ) else None
        ),
        "framework_session_id_hash": correlation.get("framework_session_id_hash"),
        "turn_number": correlation.get("app.turn.number"),
        "expected_agent_version": expected_version,
        "trace_id": trace_id if isinstance(trace_id, str) and TRACE_ID.fullmatch(trace_id) else None,
        "technical": result.technical_status.value,
        "business": result.business_status.value,
        "injection_requested": result.injection_requested,
        "injection_activated": result.injection_activated,
        "validation_outcome": validation.get("actual_label"),
        "detection_count": len(detections),
        "detection_outcomes": [item.get("outcome") for item in detections],
        "missing_trace_fields": sorted({
            field for item in detections for field in item.get("missing_trace_fields", [])
        }),
        "status": result.status.model_dump(mode="json") if result.status else None,
    }


def _passed(profile: str, result: dict[str, object]) -> bool:
    if not result["trace_id"] or result["missing_trace_fields"]:
        return False
    if profile.endswith("HEALTHY"):
        return (
            result["validation_outcome"] == "NOT_DETECTED"
            and result["detection_count"] == 14
            and set(result["detection_outcomes"]) == {"NOT_DETECTED"}
            and result["injection_requested"] is None
            and result["injection_activated"] is False
        )
    return (
        result["validation_outcome"] == "DETECTED"
        and result["detection_outcomes"] == ["DETECTED"]
        and result["injection_requested"] == profile
        and result["injection_activated"] is True
    )


def main() -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    output = STATE / f"azure-core-validation-{stamp}.json"
    manifest = json.loads((STATE / "foundry-deployment.json").read_text())
    expected = str(manifest["procurement-parent-agent"]["version"])
    report: dict[str, object] = {
        "run_id": f"AZURE-CORE-{stamp}",
        "path": "direct-foundry-hosted-synthetic-validation",
        "expected_agent_version": expected,
        "results": [],
    }
    save(output, report)

    with AzureCliCredential() as credential, AIProjectClient(
        endpoint=ENDPOINT, credential=credential, allow_preview=True,
    ) as project:
        version = project.agents.get_version(
            agent_name="procurement-parent-agent", agent_version=expected,
        )
        if not str(version.status).lower().endswith("active"):
            raise RuntimeError("Expected Hosted version is not active; validation not started")
        with project.get_openai_client(
            agent_name="procurement-parent-agent", max_retries=0, timeout=360,
        ) as client:
            for profile in PROFILES:
                case = f"AZURE-CORE-{profile}-{stamp}"
                try:
                    conversation = client.conversations.create(metadata={
                        "test.case.id": case,
                        "synthetic": "true",
                    })
                    response = client.responses.create(
                        conversation=conversation.id,
                        input="Run the approved synthetic Azure Core validation profile.",
                        metadata={
                            "test.case.id": case,
                            "app.turn.number": "1",
                            "app.client.contract": "web-json-v1",
                            "synthetic": "true",
                            "app.validation.contract": "stage-b-v1",
                            "app.validation.profile": profile,
                        },
                    )
                    parsed = ScenarioResult.model_validate_json(response.output_text)
                    item = _safe_result(
                        profile=profile,
                        case=case,
                        conversation_id=conversation.id,
                        response=response,
                        result=parsed,
                        expected_version=expected,
                    )
                    item["passed"] = _passed(profile, item)
                except Exception as error:
                    item = {
                        "profile": profile,
                        "case": case,
                        "passed": False,
                        "error_type": type(error).__name__,
                        "http_status": getattr(error, "status_code", None),
                        "body": "withheld",
                    }
                report["results"].append(item)
                save(output, report)
                print(json.dumps(item, ensure_ascii=False), flush=True)

    report["passed"] = all(item.get("passed") for item in report["results"])
    save(output, report)
    print(json.dumps({
        "run_id": report["run_id"], "passed": report["passed"],
        "output": str(output),
    }), flush=True)
    if not report["passed"]:
        raise RuntimeError("One or more Azure Core validation cases failed")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({
            "error": type(error).__name__,
            "http_status": getattr(error, "status_code", None),
            "body": "withheld",
        }), file=sys.stderr)
        raise SystemExit(1)
