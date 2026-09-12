#!/usr/bin/env python3
"""Allowlisted flat source ZIP for Foundry remote_build, without ACR or data."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
HOSTED_ROOT = ROOT / "src/hosted-agent"


def package(destination: Path) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ("main.py", "requirements.txt", "requirements-lock.txt"):
            archive.write(HOSTED_ROOT / name, name)
        # Flatten the package next to main.py; no pip-install of the repository.
        for source in sorted((HOSTED_ROOT / "procurement_agent").glob("*.py")):
            if source.name == "devui_app.py":  # Local-only UI; App Service is packaged separately.
                continue
            archive.write(source, "procurement_agent/" + source.name)
        # Stage B runs inside the Hosted boundary. Include only its detector and
        # harness package; local fixtures and report tooling stay outside the ZIP.
        for name in ("__init__.py", "detectors.py", "envelope.py", "stage_b.py"):
            source = HOSTED_ROOT / "trace_pipeline" / name
            archive.write(source, "trace_pipeline/" + name)
        names = archive.namelist()
    return {"path": str(destination), "files": len(names),
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            "deploymentMode": "source_zip", "acrRequired": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    print(json.dumps(package(parser.parse_args().destination)))
