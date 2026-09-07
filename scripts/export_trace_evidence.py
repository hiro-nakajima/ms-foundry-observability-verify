#!/usr/bin/env python3
"""Export one Application Insights trace as allowlisted JSONL evidence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess


TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
FIELDS = (
    "timestamp", "table_name", "trace_id", "span_id", "parent_span_id", "name",
    "app_role_name", "success", "result_code", "test_case_id", "conversation_id",
    "response_id", "remote_task_id", "framework_session_id_hash", "turn_number",
    "plan_id", "plan_step_id", "execution_attempt", "agent_definition_id",
    "agent_definition_version", "toolbox_name", "search_index_name",
    "technical_status", "business_status", "mcp_status", "search_status", "parse_status",
    "validation_profile", "validation_outcome", "injection_requested",
    "injection_activated", "validation_scenario_id", "validation_expected_label",
    "validation_trace_complete", "detector_version", "evidence_ref_count",
    "system_prompt_sha256", "tool_definitions_sha256",
    "boundary_profile", "boundary_sent_chars", "boundary_sent_utf8_bytes",
    "boundary_sent_sha256", "boundary_channel", "boundary_stored_chars",
    "boundary_stored_utf8_bytes",
    "boundary_stored_sha256", "boundary_truncated", "boundary_first_truncated_position",
)
QUERY = r"""
union withsource=table_name AppRequests, AppDependencies, AppTraces, AppExceptions
| where OperationId == '{trace_id}'
| extend boundary_channel=tostring(Properties['app.validation.boundary.channel'])
| extend boundary_payload=case(
    boundary_channel == 'property', tostring(Properties['app.validation.boundary.synthetic_payload']),
    boundary_channel == 'message', tostring(column_ifexists('Message', '')),
    '')
| project
    timestamp=TimeGenerated,
    table_name,
    trace_id=OperationId,
    span_id=column_ifexists('Id', ''),
    parent_span_id=column_ifexists('ParentId', ''),
    name=column_ifexists('Name', ''),
    app_role_name=AppRoleName,
    success=tostring(column_ifexists('Success', '')),
    result_code=tostring(column_ifexists('ResultCode', '')),
    test_case_id=tostring(Properties['test.case.id']),
    conversation_id=tostring(Properties['gen_ai.conversation.id']),
    response_id=tostring(Properties['gen_ai.response.id']),
    remote_task_id=tostring(Properties['remote.task.id']),
    framework_session_id_hash=tostring(Properties['app.session.id.hash']),
    turn_number=tostring(Properties['app.turn.number']),
    plan_id=tostring(Properties['plan.id']),
    plan_step_id=tostring(Properties['plan.step.id']),
    execution_attempt=tostring(Properties['execution.attempt']),
    agent_definition_id=tostring(Properties['agent.definition.id']),
    agent_definition_version=tostring(Properties['agent.definition.version']),
    toolbox_name=tostring(Properties['toolbox.name']),
    search_index_name=tostring(Properties['search.index.name']),
    technical_status=tostring(Properties['technical.status']),
    business_status=tostring(Properties['business.status']),
    mcp_status=tostring(Properties['mcp.status']),
    search_status=tostring(Properties['search.status']),
    parse_status=tostring(Properties['parse.status']),
    validation_profile=tostring(Properties['app.validation.profile']),
    validation_outcome=tostring(Properties['app.validation.outcome']),
    injection_requested=tostring(Properties['app.validation.injection_requested']),
    injection_activated=tostring(Properties['app.validation.injection_activated']),
    validation_scenario_id=tostring(Properties['app.validation.scenario_id']),
    validation_expected_label=tostring(Properties['app.validation.expected_label']),
    validation_trace_complete=tostring(Properties['app.validation.trace_complete']),
    detector_version=tostring(Properties['app.validation.detector_version']),
    evidence_ref_count=tostring(Properties['app.validation.evidence_ref_count']),
    system_prompt_sha256=tostring(Properties['app.validation.system_prompt.sha256']),
    tool_definitions_sha256=tostring(Properties['app.validation.tool_definitions.sha256']),
    boundary_profile=tostring(Properties['app.validation.boundary.profile']),
    boundary_sent_chars=tolong(Properties['app.validation.boundary.sent_chars']),
    boundary_sent_utf8_bytes=tolong(Properties['app.validation.boundary.sent_utf8_bytes']),
    boundary_sent_sha256=tostring(Properties['app.validation.boundary.sent_sha256']),
    boundary_channel,
    boundary_stored_chars=iif(isempty(boundary_payload), long(null), strlen(boundary_payload)),
    boundary_stored_utf8_bytes=iif(isempty(boundary_payload), long(null), string_size(boundary_payload)),
    boundary_stored_sha256=iif(isempty(boundary_payload), '', hash_sha256(boundary_payload)),
    boundary_truncated=iif(isempty(boundary_payload), bool(null), strlen(boundary_payload) < tolong(Properties['app.validation.boundary.sent_chars'])),
    boundary_first_truncated_position=iif(strlen(boundary_payload) < tolong(Properties['app.validation.boundary.sent_chars']), strlen(boundary_payload), long(null))
| order by timestamp asc, table_name asc, span_id asc
""".strip()


def build_query(trace_id: str) -> str:
    if not TRACE_ID.fullmatch(trace_id):
        raise ValueError("trace-id must be 32 lowercase hexadecimal characters")
    return QUERY.format(trace_id=trace_id)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, help="Log Analytics workspace GUID")
    parser.add_argument("--trace-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    command = [
        "az", "monitor", "log-analytics", "query",
        "--workspace", args.workspace,
        "--analytics-query", build_query(args.trace_id),
        "--output", "json",
    ]
    completed = subprocess.run(
        command, check=True, capture_output=True, text=True, env=os.environ.copy(),
    )
    rows = json.loads(completed.stdout)
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("No telemetry rows found for the exact trace ID")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    allowlisted_rows = [{key: row.get(key, "") for key in FIELDS} for row in rows]
    args.output.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in allowlisted_rows),
        encoding="utf-8",
    )
    print(json.dumps({"trace_id": args.trace_id, "rows": len(rows), "output": str(args.output)}))


if __name__ == "__main__":
    main()
