from __future__ import annotations

import pytest

from procurement_agent.observability import TelemetryRecorder


def test_parent_child_spans_and_state_event_are_recorded() -> None:
    telemetry = TelemetryRecorder()
    with telemetry.span("agent.invoke", {"poc.run.id": "run-1"}) as root:
        telemetry.add_event(root, "plan_created", {"poc.plan.version": 1})
        with telemetry.span("plan.create", {"poc.plan.id": "plan-1"}):
            pass
    spans = {span.name: span for span in telemetry.finished_spans()}
    assert spans["plan.create"].parent.span_id == spans["agent.invoke"].context.span_id
    assert spans["agent.invoke"].events[0].name == "plan_created"


def test_raw_or_sensitive_attributes_are_removed() -> None:
    telemetry = TelemetryRecorder()
    with telemetry.span(
        "tool.search_catalog",
        {
            "poc.tool.input_hash": "safe-hash",
            "poc.user_input": "must-not-appear",
            "poc.secret": "must-not-appear",
        },
    ):
        pass
    attributes = dict(telemetry.finished_spans()[0].attributes)
    assert attributes == {"poc.tool.input_hash": "safe-hash"}


def test_production_equivalent_content_is_hash_and_ref_only() -> None:
    telemetry = TelemetryRecorder(synthetic_environment=False, record_raw_content=False)
    protected = telemetry.protect_content("user", "synthetic request")
    assert protected["raw_recorded"] is False
    assert telemetry.content_store == {}
    assert protected["ref"].startswith("protected:user:")


def test_raw_content_requires_synthetic_environment() -> None:
    with pytest.raises(ValueError):
        TelemetryRecorder(synthetic_environment=False, record_raw_content=True)
    telemetry = TelemetryRecorder(synthetic_environment=True, record_raw_content=True)
    protected = telemetry.protect_content("user", "synthetic request")
    assert telemetry.content_store[protected["ref"]] == "synthetic request"
