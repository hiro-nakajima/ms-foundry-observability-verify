"""Recorded MCP/Toolbox contract used for local validation without Azure writes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .models import (
    BusinessStatus,
    FailureLayer,
    McpStatus,
    OperationStatus,
    ParseStatus,
    SearchStatus,
    TechnicalStatus,
)


class McpContractError(ValueError):
    pass


class StrictContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class McpExchange(StrictContractModel):
    method: Literal["initialize", "tools/list", "tools/call"]
    request: dict[str, Any] = Field(default_factory=dict)
    response: dict[str, Any] | None = None
    transport_error: Literal["timeout"] | None = None


class RecordedMcpTranscript(StrictContractModel):
    schema_version: Literal["1.0"] = "1.0"
    fixture_id: str
    toolbox_name: Literal["catalog-search-toolbox", "code-master-toolbox"]
    index_name: Literal["procurement-catalog-v1", "procurement-code-master-v1"]
    failure_profile: str
    exchanges: list[McpExchange] = Field(min_length=1)


def load_transcript(path: str | Path) -> RecordedMcpTranscript:
    try:
        return RecordedMcpTranscript.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValidationError, json.JSONDecodeError) as exc:
        raise McpContractError(f"invalid MCP transcript: {path}") from exc


def _error_status(
    *, mcp: McpStatus, search: SearchStatus, parse: ParseStatus, layer: FailureLayer,
    reason: str, retryable: bool = False,
) -> OperationStatus:
    return OperationStatus(
        http_status=200,
        technical_status=TechnicalStatus.ERROR,
        mcp_status=mcp,
        search_status=search,
        parse_status=parse,
        business_status=BusinessStatus.BLOCKED,
        failure_layer=layer,
        reason_code=reason,
        retryable=retryable,
    )


def classify_transcript(transcript: RecordedMcpTranscript) -> OperationStatus:
    methods = [item.method for item in transcript.exchanges]
    if methods[:3] != ["initialize", "tools/list", "tools/call"]:
        return _error_status(
            mcp=McpStatus.PROTOCOL_ERROR, search=SearchStatus.NOT_RUN,
            parse=ParseStatus.NOT_RUN, layer=FailureLayer.MCP,
            reason="mcp_sequence_invalid",
        )
    call = transcript.exchanges[2]
    if call.transport_error == "timeout":
        return _error_status(
            mcp=McpStatus.TIMEOUT, search=SearchStatus.NOT_RUN,
            parse=ParseStatus.NOT_RUN, layer=FailureLayer.MCP,
            reason="mcp_timeout", retryable=True,
        )
    response = call.response
    if not isinstance(response, dict) or "result" not in response:
        return _error_status(
            mcp=McpStatus.PROTOCOL_ERROR, search=SearchStatus.NOT_RUN,
            parse=ParseStatus.INVALID_JSON, layer=FailureLayer.MCP,
            reason="mcp_protocol_invalid",
        )
    result = response["result"]
    if not isinstance(result, dict):
        return _error_status(
            mcp=McpStatus.SUCCESS, search=SearchStatus.NOT_RUN,
            parse=ParseStatus.SCHEMA_INVALID, layer=FailureLayer.PARSE,
            reason="result_schema_invalid",
        )
    error_code = result.get("error_code")
    if error_code == "index_missing":
        return _error_status(
            mcp=McpStatus.SUCCESS, search=SearchStatus.INDEX_MISSING,
            parse=ParseStatus.SUCCESS, layer=FailureLayer.SEARCH,
            reason="index_missing",
        )
    if error_code == "permission":
        return _error_status(
            mcp=McpStatus.SUCCESS, search=SearchStatus.PERMISSION_DENIED,
            parse=ParseStatus.SUCCESS, layer=FailureLayer.SEARCH,
            reason="search_permission_denied",
        )
    documents = result.get("documents")
    if not isinstance(documents, list):
        return _error_status(
            mcp=McpStatus.SUCCESS, search=SearchStatus.SUCCESS,
            parse=ParseStatus.SCHEMA_INVALID, layer=FailureLayer.PARSE,
            reason="documents_schema_invalid",
        )
    if not documents:
        return OperationStatus(
            technical_status=TechnicalStatus.SUCCESS,
            mcp_status=McpStatus.SUCCESS,
            search_status=SearchStatus.NOT_FOUND,
            parse_status=ParseStatus.SUCCESS,
            business_status=BusinessStatus.NOT_FOUND,
            failure_layer=FailureLayer.NONE,
            reason_code="not_found",
        )
    if result.get("business_valid") is False:
        return OperationStatus(
            technical_status=TechnicalStatus.SUCCESS,
            mcp_status=McpStatus.SUCCESS,
            search_status=SearchStatus.SUCCESS,
            parse_status=ParseStatus.SUCCESS,
            business_status=BusinessStatus.VALIDATION_FAILED,
            failure_layer=FailureLayer.VALIDATION,
            reason_code="business_invalid",
        )
    return OperationStatus(
        technical_status=TechnicalStatus.SUCCESS,
        mcp_status=McpStatus.SUCCESS,
        search_status=SearchStatus.SUCCESS,
        parse_status=ParseStatus.SUCCESS,
        business_status=BusinessStatus.SUCCESS,
    )


def result_documents(transcript: RecordedMcpTranscript) -> list[dict[str, Any]]:
    status = classify_transcript(transcript)
    if status.business_status != BusinessStatus.SUCCESS:
        return []
    result = transcript.exchanges[2].response["result"]  # type: ignore[index]
    return list(result["documents"])
