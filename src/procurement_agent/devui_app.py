"""Agent Framework DevUI entry point for HA-S and HA-M."""

from __future__ import annotations

import argparse
import json

from agent_framework_devui import serve

from .hosted import build_local_hosted_bundle
from .models import GovernanceMode, LogicalPattern


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Synthetic procurement Agent Framework DevUI")
    parser.add_argument("--pattern", choices=["HA-S", "HA-M"], default="HA-S")
    parser.add_argument("--governance", choices=["shadow", "enforce"], default="shadow")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--smoke", action="store_true", help="Build the real factory and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    bundle = build_local_hosted_bundle(
        LogicalPattern(args.pattern), governance_mode=GovernanceMode(args.governance)
    )
    if args.smoke:
        print(
            json.dumps(
                {
                    "pattern": bundle.pattern.value,
                    "entity": bundle.coordinator.name,
                    "agent_tools": [
                        tool.name
                        for tool in (bundle.procurement_tool, bundle.drafting_tool)
                        if tool is not None
                    ],
                    "session_source_of_truth": "Coordinator AgentSession",
                    "propagate_session": False,
                    "status_fields": [
                        "plan_id",
                        "plan_status",
                        "current_step",
                        "completed_steps",
                        "delegations",
                        "governance_decisions",
                        "trace_id",
                        "warnings",
                        "session_resumed",
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    serve(
        entities=[bundle.coordinator],
        host=args.host,
        port=args.port,
        auto_open=False,
        instrumentation_enabled=True,
        auth_enabled=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
