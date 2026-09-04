#!/usr/bin/env python3
"""Allowlisted flat source ZIP for Foundry remote_build, without ACR or data."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def package(destination: Path) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ("main.py", "requirements.txt", "requirements-lock.txt"):
            archive.write(ROOT / name, name)
        # Flatten the package next to main.py; no pip-install of the repository.
        for source in sorted((ROOT / "src/procurement_agent").glob("*.py")):
            archive.write(source, "procurement_agent/" + source.name)
        names = archive.namelist()
    return {"path": str(destination), "files": len(names),
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            "deploymentMode": "source_zip", "acrRequired": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    print(json.dumps(package(parser.parse_args().destination)))
