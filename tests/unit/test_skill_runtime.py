from __future__ import annotations

from pathlib import Path

import pytest

from procurement_agent.skills_runtime import AllowlistedSkillScriptRunner


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "src" / "procurement_agent" / "skills" / "request-check" / "scripts"


def test_allowlisted_runner_executes_decimal_script_as_json() -> None:
    runner = AllowlistedSkillScriptRunner(SCRIPTS)
    result = runner.execute(
        "calculate_request.py",
        {
            "quantity": 3,
            "unit_price": "180000",
            "tax_rate": "0.10",
            "rounding_mode": "ROUND_HALF_UP",
            "rounding_unit": "1",
        },
    )
    assert result["total"] == "594000"
    assert result["calculated_by"] == "request-check/scripts/calculate_request.py"


def test_runner_accepts_one_json_list_argument_for_framework_compatibility() -> None:
    runner = AllowlistedSkillScriptRunner(SCRIPTS)
    result = runner.execute(
        "calculate_request.py",
        [
            '{"quantity":1,"unit_price":"5","tax_rate":"0.10",'
            '"rounding_mode":"ROUND_HALF_UP","rounding_unit":"1"}'
        ],
    )
    assert result["total"] == "6"


def test_runner_denies_unreviewed_script() -> None:
    runner = AllowlistedSkillScriptRunner(SCRIPTS)
    with pytest.raises(PermissionError):
        runner.execute("not-reviewed.py", {})
