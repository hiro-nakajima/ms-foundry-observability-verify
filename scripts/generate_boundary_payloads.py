#!/usr/bin/env python3
"""Generate S5 synthetic boundary payloads; no Azure calls are made."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


SIZES = (128, 8191, 8192, 8193, 32767, 32768, 32769, 65535, 65536, 65537)


def build_payloads() -> list[dict[str, object]]:
    return [{"case_id": f"S5-LEN-{size}", "length": size, "payload": "X" * size} for size in SIZES]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(build_payloads(), ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
