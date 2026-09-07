#!/usr/bin/env python3
"""Run the five approved S5 content-boundary profiles on Hosted Azure v27."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import re
import sys

from azure.ai.projects import AIProjectClient
from azure.identity import AzureCliCredential

from procurement_agent.azure_validation import S5_BOUNDARY_CHARS
from procurement_agent.models import ScenarioResult
from procurement_agent.observability import sha256
from deploy_foundation import STATE, save
from deploy_foundry import ENDPOINT


EXPECTED_AGENT_VERSION = "27"
PROFILES = (
    "S5-SMALL", "S5-HEALTHY", "S5-32768", "S5-65536", "S5-OVER",
)
TRACE_ID = re.compile(r"^[0-9a-f]{32}$")


def _safe_result(
    *, profile: str, case: str, conversation_id: str, response: object,
    result: ScenarioResult,
) -> dict[str, object]:
    validation = result.trace.get("validation") or {}
    correlation = result.trace.get("correlation") or {}
    trace_id = result.trace.get("trace_id")
    detections = validation.get("detections") or []
    boundary = validation.get("content_boundary") or {}
    service_session = (getattr(response, "model_extra", None) or {}).get(
        "agent_session_id",
    )
    return {
        "profile": profile,
        "case": case,
        "foundry_conversation_id": conversation_id,
        "foundry_response_id": getattr(response, "id", None),
        "service_agent_session_id_hash": (
            sha256(str(service_session)) if service_session else None
        ),
        "framework_session_id_hash": correlation.get("framework_session_id_hash"),
        "turn_number": correlation.get("app.turn.number"),
        "expected_agent_version": EXPECTED_AGENT_VERSION,
        "trace_id": (
            trace_id
            if isinstance(trace_id, str) and TRACE_ID.fullmatch(trace_id)
            else None
        ),
        "technical": result.technical_status.value,
        "business": result.business_status.value,
        "validation_outcome": validation.get("actual_label"),
        "validation_trace_complete": validation.get("trace_complete"),
        "detection_count": len(detections),
        "detection_outcomes": [item.get("outcome") for item in detections],
        "missing_trace_fields": sorted({
            field
            for item in detections
            for field in item.get("missing_trace_fields", [])
        }),
        "content_boundary": {
            "profile": boundary.get("profile"),
            "sent_chars": boundary.get("sent_chars"),
            "sent_utf8_bytes": boundary.get("sent_utf8_bytes"),
            "sent_sha256": boundary.get("sent_sha256"),
        },
        "status": result.status.model_dump(mode="json") if result.status else None,
    }


def _passed(profile: str, result: dict[str, object]) -> bool:
    expected_chars = S5_BOUNDARY_CHARS[profile]
    boundary = result["content_boundary"]
    assert isinstance(boundary, dict)
    return bool(
        result["trace_id"]
        and not result["missing_trace_fields"]
        and result["validation_trace_complete"] is True
        and result["validation_outcome"] == "NOT_DETECTED"
        and result["detection_count"] == 14
        and set(result["detection_outcomes"]) == {"NOT_DETECTED"}
        and boundary == {
            "profile": profile,
            "sent_chars": expected_chars,
            "sent_utf8_bytes": expected_chars,
            "sent_sha256": sha256("X" * expected_chars),
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile", action="append", choices=PROFILES,
        help="Run one fixed profile; repeat for more. Default: all five.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    selected_profiles = tuple(build_parser().parse_args(argv).profile or PROFILES)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    output = STATE / f"s5-boundary-validation-{stamp}.json"
    manifest = json.loads((STATE / "foundry-deployment.json").read_text())
    deployed = str(manifest["procurement-parent-agent"]["version"])
    if deployed != EXPECTED_AGENT_VERSION:
        raise RuntimeError("Local deployment manifest is not the approved Hosted v27")
    report: dict[str, object] = {
        "run_id": f"AZURE-CORE-S5-BOUNDARY-{stamp}",
        "path": "direct-foundry-hosted-synthetic-validation",
        "expected_agent_version": EXPECTED_AGENT_VERSION,
        "results": [],
    }
    save(output, report)

    with AzureCliCredential() as credential, AIProjectClient(
        endpoint=ENDPOINT, credential=credential, allow_preview=True,
    ) as project:
        version = project.agents.get_version(
            agent_name="procurement-parent-agent",
            agent_version=EXPECTED_AGENT_VERSION,
        )
        if not str(version.status).lower().endswith("active"):
            raise RuntimeError("Approved Hosted v27 is not active; validation not started")
        with project.get_openai_client(
            agent_name="procurement-parent-agent", max_retries=0, timeout=360,
        ) as client:
            for profile in selected_profiles:
                case = f"AZURE-CORE-{profile}-{stamp}"
                try:
                    conversation = client.conversations.create(metadata={
                        "test.case.id": case,
                        "synthetic": "true",
                    })
                    response = client.responses.create(
                        conversation=conversation.id,
                        input="Run the approved synthetic S5 boundary profile.",
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
        "run_id": report["run_id"],
        "passed": report["passed"],
        "output": str(output),
    }), flush=True)
    if not report["passed"]:
        raise RuntimeError("One or more S5 boundary cases failed")


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
