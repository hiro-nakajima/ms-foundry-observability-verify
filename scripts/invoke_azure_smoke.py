#!/usr/bin/env python3
"""Synthetic deployment smoke through the real Hosted Responses endpoint.

This is not an App Service/EasyAuth E2E or the complete Core Matrix. Only parsed
business status and correlation are persisted; raw response items are withheld.
"""
from datetime import datetime, timezone
import json
import sys

from azure.ai.projects import AIProjectClient
from azure.identity import AzureCliCredential
from procurement_agent.models import ScenarioResult
from deploy_foundation import STATE, save
from deploy_foundry import ENDPOINT


def main():
    case = "S1-DIRECT-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    with AzureCliCredential() as credential, AIProjectClient(endpoint=ENDPOINT, credential=credential, allow_preview=True) as project:
        manifest = json.loads((STATE / "foundry-deployment.json").read_text())
        expected = manifest["procurement-parent-agent"]["version"]
        version = project.agents.get_version(agent_name="procurement-parent-agent", agent_version=expected)
        if version.status != "active":
            raise RuntimeError("Expected Hosted version is not active; invocation not started")
        with project.get_openai_client(agent_name="procurement-parent-agent", max_retries=0, timeout=240) as protocol:
            conversation = protocol.conversations.create(metadata={"test.case.id": case, "synthetic": "true"})
            save(STATE / f"{case}.json", {"case": case, "conversation_id": conversation.id,
                 "path": "direct-foundry-not-webapp", "status": "CREATED_NOT_INVOKED"})
            print(json.dumps({"phase": "conversation_created", "case": case, "conversation_id": conversation.id}), flush=True)
        with project.get_openai_client(agent_name="procurement-parent-agent", max_retries=0, timeout=240) as agent:
            response = agent.responses.create(conversation=conversation.id,
                input="架空の購買依頼です。申請ID REQ-SYNTH-001、申請者は架空 太郎、所属は開発部（架空部署）。開発用ノートPCを2台、用途は開発、予算上限40万円、必要メモリ32GBです。Catalogに存在する商品とコードだけを使って購買申請を作成してください。",
                metadata={"test.case.id": case, "app.turn.number": "1"})
            result = ScenarioResult.model_validate_json(response.output_text)
            summary = {"case": case, "path": "direct-foundry-not-webapp", "conversation_id": conversation.id,
                "response_id": response.id, "expected_agent_version": expected,
                "agent_session_id": (response.model_extra or {}).get("agent_session_id"),
                "technical": result.technical_status.value,
                "business": result.business_status.value, "status": result.status.model_dump(mode="json") if result.status else None,
                "correlation": result.trace.get("correlation"), "draft_present": result.draft is not None}
            save(STATE / f"{case}.json", summary)
            print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"error": type(error).__name__, "http_status": getattr(error, "status_code", None),
                          "code": getattr(error, "code", None), "body": "withheld"}))
        sys.exit(1)
