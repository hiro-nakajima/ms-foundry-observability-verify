import pytest

from scripts.export_trace_evidence import FIELDS, build_query


def test_build_query_uses_exact_trace_id_and_allowlist():
    trace_id = "c876a5a2b4997bb2f44aaffb76829f7b"
    query = build_query(trace_id)

    assert f"OperationId == '{trace_id}'" in query
    assert "Properties['test.case.id']" in query
    assert "project-away" not in query
    assert "user.id" not in query
    assert "app.authenticated.display_name" not in query
    assert "user.id" not in FIELDS
    assert "app.validation.boundary.synthetic_payload" in query
    assert "boundary_channel == 'property'" in query
    assert "boundary_channel == 'message'" in query
    assert "column_ifexists('Message', '')" in query
    assert "boundary_payload" not in FIELDS
    assert "boundary_channel" in FIELDS
    assert "boundary_stored_chars" in FIELDS
    assert "boundary_first_truncated_position" in FIELDS


@pytest.mark.parametrize("trace_id", ["", "xyz", "A" * 32, "0" * 31, "0' or true"])
def test_build_query_rejects_non_trace_ids(trace_id):
    with pytest.raises(ValueError):
        build_query(trace_id)
