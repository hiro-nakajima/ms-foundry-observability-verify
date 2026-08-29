"""Allowlisted Agent Framework skill script execution.

The runner is intentionally small and deny-by-default.  It accepts JSON values,
writes them to the script's standard input, and parses one JSON result from
standard output.  No shell is involved and no arbitrary path can be selected by
the model.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ALLOWED_REQUEST_CHECK_SCRIPTS = frozenset({"calculate_request.py", "validate_request.py"})


class SkillScriptExecutionError(RuntimeError):
    """Raised when an allowlisted script cannot produce a valid JSON result."""


class AllowlistedSkillScriptRunner:
    """Run only the two reviewed request-check scripts without a shell."""

    def __init__(self, scripts_dir: str | Path, *, timeout_seconds: float = 5.0) -> None:
        self.scripts_dir = Path(scripts_dir).resolve()
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _normalize_args(args: dict[str, Any] | list[str] | None) -> dict[str, Any]:
        if args is None:
            return {}
        if isinstance(args, dict):
            return dict(args)
        if len(args) == 1:
            try:
                parsed = json.loads(args[0])
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                return parsed
        normalized: dict[str, Any] = {}
        for value in args:
            if "=" not in value:
                raise ValueError("script list arguments must be one JSON object or key=value pairs")
            key, raw = value.split("=", 1)
            if not key:
                raise ValueError("script argument name must not be empty")
            try:
                normalized[key] = json.loads(raw)
            except json.JSONDecodeError:
                normalized[key] = raw
        return normalized

    def execute(self, script_name: str, args: dict[str, Any] | list[str] | None) -> dict[str, Any]:
        if script_name not in ALLOWED_REQUEST_CHECK_SCRIPTS:
            raise PermissionError(f"skill script is not allowlisted: {script_name}")
        script_path = (self.scripts_dir / script_name).resolve()
        if script_path.parent != self.scripts_dir or not script_path.is_file():
            raise PermissionError(f"skill script escaped the reviewed directory: {script_name}")
        payload = self._normalize_args(args)
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
        }
        try:
            completed = subprocess.run(
                [sys.executable, str(script_path)],
                input=json.dumps(payload, ensure_ascii=False),
                text=True,
                capture_output=True,
                check=False,
                cwd=self.scripts_dir,
                env=environment,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise SkillScriptExecutionError(f"skill script timed out: {script_name}") from exc
        if completed.returncode != 0:
            stderr = completed.stderr.strip()[-500:]
            raise SkillScriptExecutionError(
                f"skill script failed ({completed.returncode}): {script_name}: {stderr}"
            )
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise SkillScriptExecutionError(f"skill script returned invalid JSON: {script_name}") from exc
        if not isinstance(result, dict):
            raise SkillScriptExecutionError(f"skill script result must be an object: {script_name}")
        return result

    def __call__(self, skill: Any, script: Any, args: dict[str, Any] | list[str] | None = None) -> Any:
        script_path = Path(script.full_path).resolve()
        if script_path.parent != self.scripts_dir:
            raise PermissionError("skill script is outside the reviewed request-check directory")
        return self.execute(script_path.name, args)


def build_request_check_skills_provider(skills_root: str | Path):
    """Build the official Agent Framework provider with the reviewed runner.

    Import is local so domain-only consumers can install the core package
    without the optional ``hosted`` dependency.
    """

    from agent_framework import SkillsProvider

    root = Path(skills_root).resolve()
    scripts_dir = root / "request-check" / "scripts"
    runner = AllowlistedSkillScriptRunner(scripts_dir)

    def script_filter(skill_name: str, relative_path: str) -> bool:
        return skill_name == "request-check" and relative_path in {
            "scripts/calculate_request.py",
            "scripts/validate_request.py",
        }

    provider = SkillsProvider.from_paths(
        root,
        script_runner=runner,
        script_filter=script_filter,
        disable_load_skill_approval=True,
        disable_read_skill_resource_approval=True,
        disable_run_skill_script_approval=True,
        source_id="procurement-request-check-skills",
    )
    return provider, runner
