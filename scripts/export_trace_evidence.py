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
)
QUERY = r"""
union withsource=table_name AppRequests, AppDependencies, AppTraces, AppExceptions
| where OperationId == '{trace_id}'
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
    parse_status=tostring(Properties['parse.status'])
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
