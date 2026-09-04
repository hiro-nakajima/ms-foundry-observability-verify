#!/usr/bin/env python3
"""Run inside the App Service app container: MI/APIM streaming, not browser E2E.

Execute through authorized SSH; never copy a token, fake EasyAuth headers, or
add a public diagnostic API. Only synthetic inputs and projected results.
"""
from datetime import datetime, timezone
import json
import os
import re
import time

from azure.ai.projects import AIProjectClient
from azure.identity import ManagedIdentityCredential

ENDPOINT = "https://apim-procurement-stream-nkjm.azure-api.net/foundry/proj-default"
STEPS = {"intake", "catalog", "code", "merge_validate"}
STATES = {"started", "completed", "retry", "waiting_user", "blocked"}


def main():
    if not all(os.getenv(k) for k in ("IDENTITY_ENDPOINT", "IDENTITY_HEADER")):
        raise RuntimeError("App runtime MI unavailable; do not substitute CLI credentials")
    case = "CHAT-WEBMI-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    print(json.dumps({"case": case, "path": "app-container-mi-apim-not-browser", "endpoint": ENDPOINT}), flush=True)
    with ManagedIdentityCredential() as credential, AIProjectClient(
        endpoint=ENDPOINT, credential=credential, allow_preview=True,
    ) as project, project.get_openai_client(agent_name="procurement-parent-agent", max_retries=0, timeout=240) as client:
        conversation = client.conversations.create(metadata={"test.case.id": case, "synthetic": "true"})
        message, hashes = "ノートPCを購入したい", set()
        for turn in (1, 2, 3):
            started, pending, milestones, final = time.monotonic(), "", [], None
            with client.responses.create(conversation=conversation.id, input=message, stream=True,
                metadata={"test.case.id": case, "app.turn.number": str(turn)}) as stream:
                for event in stream:
                    if event.type == "response.output_text.delta":
                        pending += event.delta
                        while "\n" in pending:
                            line, pending = pending.split("\n", 1)
                            try:
                                item = json.loads(line.lstrip(","))
                                if item.get("step") in STEPS and item.get("state") in STATES:
                                    milestone = {"step": item["step"], "state": item["state"],
                                                 "seconds": round(time.monotonic() - started, 3)}
                                    milestones.append(milestone)
                                    print(json.dumps({"turn": turn, "progress": milestone}), flush=True)
                            except (ValueError, AttributeError):
                                pass
                    elif event.type == "response.completed":
                        final = event.response
                    elif event.type in {"response.failed", "response.incomplete", "error"}:
                        raise RuntimeError("Stream failure; response body withheld")
            if final is None:
                raise RuntimeError("No completed response")
            result = json.loads(final.output_text)
            candidates = [c["product_code"] for c in result.get("candidates", [])
                          if re.fullmatch(r"[A-Z0-9-]{1,80}", c.get("product_code", ""))]
            correlation = result.get("trace", {}).get("correlation", {})
            session_hash = correlation.get("framework_session_id_hash")
            if not isinstance(session_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", session_hash):
                raise RuntimeError("Framework correlation missing")
            hashes.add(session_hash)
            seconds = round(time.monotonic() - started, 3)
            layer = result.get("status") or {}
            safe = {"case": case, "turn": turn, "seconds": seconds,
                    "conversation_id": conversation.id, "response_id": final.id,
                    "framework_session_id_hash": session_hash,
                    "technical": result.get("technical_status"), "business": result.get("business_status"),
                    "status": {k: layer.get(k) for k in ("mcp_status", "search_status", "parse_status")},
                    "candidate_codes": candidates, "draft_present": bool(result.get("draft")),
                    "progress_count": len(milestones)}
            print(json.dumps(safe), flush=True)
            if not milestones or milestones[0]["seconds"] >= seconds or len(hashes) != 1:
                raise RuntimeError("Streaming or conversation acceptance failed")
            if turn == 1:
                if result.get("business_status") != "WAITING_USER" or not candidates:
                    raise RuntimeError("Candidate discovery failed")
                message = f"商品コード {candidates[0]} を選びます。"
            elif turn == 2:
                if result.get("business_status") != "WAITING_USER" or result.get("draft"):
                    raise RuntimeError("Selection-only turn should still request required details")
                message = "数量2台、用途は開発、申請ID REQ-SYNTH-APIM-001、申請者は架空 太郎、所属は開発部（架空部署）。予算上限40万円です。"
            elif result.get("business_status") != "SUCCESS" or not result.get("draft"):
                raise RuntimeError("Selected and completed intake did not succeed")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "http_status": getattr(exc, "status_code", None), "body": "withheld"}), flush=True)
        raise SystemExit(1)
