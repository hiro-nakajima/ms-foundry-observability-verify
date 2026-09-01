"""Foundry Responses host for the single Hosted parent."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from agent_framework_foundry_hosting import ResponsesHostServer

from .hosted import FoundryRuntimeSettings, build_hosted_bundle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Procurement Agent v2 Responses host")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--smoke", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    os.environ.setdefault("AGENTSERVER_STATE_ROOT", str(Path("/tmp/foundry-procurement-agent-v2") if args.smoke else Path.cwd() / ".local_state/agentserver"))
    if args.smoke:
        print(json.dumps({
            "architecture_id": "procurement_application_v2",
            "agent": "procurement_parent_agent",
            "server": ResponsesHostServer.__name__,
            "protocol": "responses/v1",
            "azure_apply": False,
        }, sort_keys=True))
        return 0
    bundle = build_hosted_bundle(FoundryRuntimeSettings.from_env())
    ResponsesHostServer(bundle.parent).run(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
