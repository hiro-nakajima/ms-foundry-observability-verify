import json
from pathlib import Path

import pytest

from trace_pipeline.detectors import DetectionOutcome, PATTERN_IDS, TraceFacts, detect, evaluate_all, summarize


ROOT = Path(__file__).parents[2]


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", load(ROOT / "trace_fixtures/stage_a/positive/all-patterns.json"))
def test_stage_a_positive_detects_all_14(case):
    assert detect(case["pattern_id"], case["facts"]).outcome == DetectionOutcome.DETECTED


@pytest.mark.parametrize("case", load(ROOT / "trace_fixtures/stage_a/negative/all-patterns.json"))
def test_stage_a_negative_rejects_false_positives(case):
    assert detect(case["pattern_id"], case["facts"]).outcome == DetectionOutcome.NOT_DETECTED


@pytest.mark.parametrize("case", load(ROOT / "trace_fixtures/stage_b/core-matrix.json"))
def test_stage_b_six_injections_keep_outer_status_success(case):
    facts = TraceFacts.model_validate(case["facts"])
    assert facts.technical_status == "SUCCESS"
    result = detect(case["pattern_id"], facts, injection_requested=True, injection_activated=True)
    assert result.outcome == DetectionOutcome.DETECTED


@pytest.mark.parametrize("scenario", ["S1", "S5"])
def test_healthy_controls_do_not_trigger_any_detector(scenario):
    results = evaluate_all(TraceFacts(case_id=f"{scenario}-HEALTHY"))
    assert len(results) == len(PATTERN_IDS) == 14
    assert {item.outcome for item in results} == {DetectionOutcome.NOT_DETECTED}


def test_injection_missed_is_not_semantic_fail():
    result = detect("TV-02", TraceFacts(case_id="MISSED"), injection_requested=True, injection_activated=False)
    assert result.outcome == DetectionOutcome.INJECTION_MISSED
    summary = summarize([result])
    assert summary["semantic"]["DETECTED"] == 0
    assert summary["operational"]["INJECTION_MISSED"] == 1


def test_incomplete_trace_is_not_semantic_pass_or_fail():
    facts = TraceFacts(case_id="INCOMPLETE", present_fields=["plan"])
    result = detect("TV-02", facts, injection_requested=True, injection_activated=True)
    assert result.outcome == DetectionOutcome.UNEVALUABLE_TRACE_INCOMPLETE
    summary = summarize([result])
    assert summary["semantic"] == {"DETECTED": 0, "NOT_DETECTED": 0}
    assert summary["operational"]["UNEVALUABLE_TRACE_INCOMPLETE"] == 1
