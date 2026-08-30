from __future__ import annotations

import json
from pathlib import Path

from trace_pipeline.completeness import trace_completeness
from trace_pipeline.envelope import TraceEvaluationEnvelope


ROOT = Path(__file__).resolve().parents[2]


def _load(path: Path) -> TraceEvaluationEnvelope:
    return TraceEvaluationEnvelope.model_validate(json.loads(path.read_text(encoding="utf-8")))


def test_positive_fixture_has_all_nine_trace_fields() -> None:
    envelope = _load(ROOT / "trace_fixtures" / "positive" / "healthy.json")
    result = trace_completeness(envelope)
    assert result["complete"] is True
    assert result["score"] == 1.0


def test_negative_fixture_identifies_missing_tool_output() -> None:
    envelope = _load(
        ROOT / "trace_fixtures" / "negative" / "missing_tool_output.json"
    )
    result = trace_completeness(envelope)
    assert result["complete"] is False
    assert result["missing"] == ["tool_output"]
    assert result["score"] == 8 / 9
