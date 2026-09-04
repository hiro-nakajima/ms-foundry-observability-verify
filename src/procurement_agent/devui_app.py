"""Agent Framework DevUI entry point for the single revised architecture."""

from __future__ import annotations

import argparse
import json

from agent_framework.devui import serve

from .hosted import FoundryRuntimeSettings, build_hosted_bundle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Procurement Agent v2 DevUI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--smoke", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.smoke:
        print(json.dumps({
            "architecture_id": "procurement_application_v2",
            "parent": "procurement_parent_agent",
            "child_proxies": ["catalog_search_agent", "code_determination_agent"],
            "child_implementation_in_container": False,
            "history_provider": {"source_id": "procurement-history", "load_messages": True},
            "propagate_session": False,
            "azure_apply": False,
        }, sort_keys=True))
        return 0
    bundle = build_hosted_bundle(FoundryRuntimeSettings.from_env())
    serve(entities=[bundle.parent], host=args.host, port=args.port, auto_open=False, instrumentation_enabled=True, auth_enabled=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
