from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    ROOT
    / "src"
    / "procurement_agent"
    / "skills"
    / "request-check"
    / "scripts"
    / "calculate_request.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("calculate_request_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_decimal_calculation_is_deterministic() -> None:
    result = _load_module().calculate_request(
        quantity=3,
        unit_price="180000",
        tax_rate="0.10",
        discount_rate="0",
        rounding_mode="ROUND_HALF_UP",
        rounding_unit="1",
    )
    assert result["subtotal"] == "540000"
    assert result["discount"] == "0"
    assert result["taxable_amount"] == "540000"
    assert result["tax"] == "54000"
    assert result["total"] == "594000"
    assert result["calculated_by"] == "request-check/scripts/calculate_request.py"


def test_round_half_up_is_explicit() -> None:
    result = _load_module().calculate_request(
        quantity=1,
        unit_price="5",
        tax_rate="0.10",
        rounding_mode="ROUND_HALF_UP",
        rounding_unit="1",
    )
    assert result["tax"] == "1"
    assert result["total"] == "6"


def test_negative_input_is_rejected() -> None:
    with pytest.raises(ValueError):
        _load_module().calculate_request(
            quantity=1,
            unit_price="-1",
            tax_rate="0.10",
        )


def test_script_cli_reads_and_writes_json() -> None:
    payload = {
        "quantity": 2,
        "unit_price": "100",
        "tax_rate": "0.10",
        "rounding_mode": "ROUND_HALF_UP",
        "rounding_unit": "1",
    }
    completed = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(completed.stdout)["total"] == "220"
