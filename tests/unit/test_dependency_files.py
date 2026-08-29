from __future__ import annotations

import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


ROOT = Path(__file__).resolve().parents[2]


def _requirements(path: Path) -> dict[str, Requirement]:
    parsed: dict[str, Requirement] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        requirement = Requirement(line)
        parsed[canonicalize_name(requirement.name)] = requirement
    return parsed


def test_requirements_txt_matches_wheel_runtime_metadata() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    metadata = {
        canonicalize_name(requirement.name): requirement
        for requirement in map(Requirement, project["dependencies"])
    }
    runtime = _requirements(ROOT / "requirements.txt")

    assert set(runtime) == set(metadata)
    for name, requirement in runtime.items():
        assert str(requirement.specifier) == str(metadata[name].specifier)
        assert requirement.extras == metadata[name].extras


def test_lock_constrains_every_direct_dependency_and_test_dependency() -> None:
    lock = _requirements(ROOT / "requirements-lock.txt")
    requested = _requirements(ROOT / "requirements.txt") | _requirements(
        ROOT / "requirements-dev.txt"
    )

    for name, requirement in requested.items():
        assert name in lock
        assert str(requirement.specifier) == str(lock[name].specifier)


def test_python_runtime_targets_foundry_source_deployment() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert project["requires-python"] == ">=3.13,<3.15"
    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.13"
    assert not (ROOT / "uv.lock").exists()
