"""Local Responses host scaffold using the same Agent Factory as DevUI."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from agent_framework_foundry_hosting import ResponsesHostServer

from .hosted import build_local_hosted_bundle
from .models import GovernanceMode, LogicalPattern


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local Foundry Responses host scaffold")
    parser.add_argument(
        "--pattern",
        choices=["HA-S", "HA-M"],
        default=os.getenv("PROCUREMENT_LOGICAL_PATTERN", "HA-S"),
    )
    parser.add_argument("--governance", choices=["shadow", "enforce"], default="shadow")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--smoke", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    bundle = build_local_hosted_bundle(
        LogicalPattern(args.pattern), governance_mode=GovernanceMode(args.governance)
    )
    default_state_root = (
        Path("/tmp/foundry-procurement-agentserver-smoke")
        if args.smoke
        else Path.cwd() / ".local_state" / "agentserver"
    )
    os.environ.setdefault("AGENTSERVER_STATE_ROOT", str(default_state_root))
    if args.smoke:
        print(
            json.dumps(
                {
                    "pattern": bundle.pattern.value,
                    "agent": bundle.coordinator.name,
                    "server": ResponsesHostServer.__name__,
                    "protocol": "responses/v1",
                    "azure_apply": False,
                },
                sort_keys=True,
            )
        )
        return 0
    server = ResponsesHostServer(bundle.coordinator)
    server.run(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
