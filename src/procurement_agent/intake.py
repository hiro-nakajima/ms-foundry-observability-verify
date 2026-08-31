"""LLM structured-output boundary for natural-language procurement turns."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Iterable
from typing import Any, Literal

from agent_framework import BaseChatClient, Message
from pydantic import BaseModel, ConfigDict, Field

from .models import Department, ProcurementRequest
from .observability import TelemetryRecorder


class SpecificationPatch(BaseModel):
    """One explicitly stated product constraint at the LLM boundary.

    OpenAI strict structured outputs don't support an arbitrary
    ``dict[str, str]`` schema.  A list of closed BaseModel entries keeps the
    response schema machine-readable and is converted to the domain mapping
    only after validation.
    """

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1)
    value: str = Field(min_length=1)


class RequestConstraintsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_by: str | None = None
    budget_limit: str | None = None
    specifications: list[SpecificationPatch] = Field(default_factory=list)


class ProcurementRequestPatch(BaseModel):
    """Values explicitly stated in one user turn; omitted values remain null."""

    model_config = ConfigDict(extra="forbid")

    request_id: str | None = None
    query: str | None = None
    quantity: int | None = Field(default=None, gt=0)
    applicant_name: str | None = None
    department_name: str | None = None
    purpose: str | None = None
    constraints: RequestConstraintsPatch = Field(default_factory=RequestConstraintsPatch)


class ProcurementTurnExtraction(BaseModel):
    """The only Pydantic response_format accepted at the intake LLM boundary."""

    model_config = ConfigDict(extra="forbid")

    intent: Literal["UPDATE_REQUEST", "CONFIRM"] = "UPDATE_REQUEST"
    request_patch: ProcurementRequestPatch = Field(
        default_factory=ProcurementRequestPatch
    )


class LlmIntakeConfigurationError(RuntimeError):
    pass


_REASONING_EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh"}


def structured_output_options(response_format: type[BaseModel]) -> dict[str, Any]:
    """Build bounded options shared by intake and planning LLM calls."""

    options: dict[str, Any] = {
        "response_format": response_format,
        "tool_choice": "none",
        "tools": [],
    }
    reasoning_effort = os.getenv("AZURE_OPENAI_REASONING_EFFORT", "").strip()
    if reasoning_effort:
        if reasoning_effort not in _REASONING_EFFORTS:
            raise LlmIntakeConfigurationError(
                "AZURE_OPENAI_REASONING_EFFORT must be one of: "
                + ", ".join(sorted(_REASONING_EFFORTS))
            )
        options["reasoning"] = {"effort": reasoning_effort}
    max_tokens = os.getenv("AZURE_OPENAI_MAX_OUTPUT_TOKENS", "").strip()
    if max_tokens:
        try:
            parsed_max_tokens = int(max_tokens)
        except ValueError as exc:
            raise LlmIntakeConfigurationError(
                "AZURE_OPENAI_MAX_OUTPUT_TOKENS must be a positive integer"
            ) from exc
        if parsed_max_tokens <= 0:
            raise LlmIntakeConfigurationError(
                "AZURE_OPENAI_MAX_OUTPUT_TOKENS must be a positive integer"
            )
        options["max_tokens"] = parsed_max_tokens
    return options


def structured_output_timeout_seconds() -> float:
    configured = os.getenv("AZURE_OPENAI_TIMEOUT_SECONDS", "90").strip()
    try:
        timeout = float(configured)
    except ValueError as exc:
        raise LlmIntakeConfigurationError(
            "AZURE_OPENAI_TIMEOUT_SECONDS must be a positive number"
        ) from exc
    if timeout <= 0:
        raise LlmIntakeConfigurationError(
            "AZURE_OPENAI_TIMEOUT_SECONDS must be a positive number"
        )
    return timeout


INTAKE_INSTRUCTIONS = """
You extract one procurement conversation turn into ProcurementTurnExtraction.
Return only the Pydantic structured output. Do not reveal chain-of-thought.

Rules:
- Extract only facts explicitly stated in current_user_input.
- Never infer or invent a product code, price, account code, delivery estimate, tax, or total.
- Do not copy values from current_request into request_patch unless the user states them again.
- Use intent CONFIRM only when confirmation_expected is true and the user explicitly confirms the displayed application.
- A short answer may fill expected_fields[0], using its conversational context.
- For a department selection, use only a name or department_code from department_options.
- If the turn is empty, unrelated, or ambiguous, leave fields null and use UPDATE_REQUEST.
- requested_by must be a full YYYY-MM-DD date. Do not infer a missing year.
""".strip()


class LlmProcurementIntake:
    """Stateless LLM parser with one BaseModel response per user turn."""

    response_format: type[ProcurementTurnExtraction] = ProcurementTurnExtraction

    def __init__(
        self,
        client: BaseChatClient | None,
        *,
        telemetry: TelemetryRecorder,
    ) -> None:
        self.client = client
        self.telemetry = telemetry

    @classmethod
    def from_environment(
        cls,
        *,
        telemetry: TelemetryRecorder,
        client: BaseChatClient | None = None,
    ) -> "LlmProcurementIntake":
        if client is not None:
            return cls(client, telemetry=telemetry)

        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
        model = os.getenv("AZURE_OPENAI_CHAT_MODEL", "").strip()
        if not endpoint or not model:
            return cls(None, telemetry=telemetry)

        from agent_framework.openai import OpenAIChatClient

        api_key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
        api_version = os.getenv("AZURE_OPENAI_API_VERSION", "").strip() or None
        if api_key:
            llm_client = OpenAIChatClient(
                model=model,
                azure_endpoint=endpoint,
                api_key=api_key,
                api_version=api_version,
            )
        else:
            from azure.identity.aio import DefaultAzureCredential

            llm_client = OpenAIChatClient(
                model=model,
                azure_endpoint=endpoint,
                credential=DefaultAzureCredential(),
                api_version=api_version,
            )
        return cls(llm_client, telemetry=telemetry)

    async def extract(
        self,
        text: str,
        *,
        current_request: ProcurementRequest | None,
        expected_fields: Iterable[str],
        department_options: Iterable[dict[str, str]] = (),
        confirmation_expected: bool = False,
    ) -> ProcurementTurnExtraction:
        if self.client is None:
            raise LlmIntakeConfigurationError(
                "Natural-language input requires AZURE_OPENAI_ENDPOINT and "
                "AZURE_OPENAI_CHAT_MODEL (plus Azure identity or AZURE_OPENAI_API_KEY)."
            )

        input_payload = {
            "current_user_input": text,
            "expected_fields": list(expected_fields),
            "current_request": (
                current_request.model_dump(mode="json") if current_request else None
            ),
            "department_options": list(department_options),
            "confirmation_expected": confirmation_expected,
        }
        with self.telemetry.span(
            "agent.intake",
            {
                "poc.intake.kind": "llm_structured_output",
                "poc.intake.response_format": self.response_format.__name__,
            },
        ) as span:
            async with asyncio.timeout(structured_output_timeout_seconds()):
                response = await self.client.get_response(
                    [
                        Message(role="system", contents=[INTAKE_INSTRUCTIONS]),
                        Message(
                            role="user",
                            contents=[
                                json.dumps(
                                    input_payload,
                                    ensure_ascii=False,
                                    sort_keys=True,
                                    default=str,
                                )
                            ],
                        ),
                    ],
                    options=structured_output_options(self.response_format),
                )
            parsed = self._parse_response(response.value, response.text)
            span.set_attribute(
                "poc.intake.empty_patch",
                not bool(
                    parsed.request_patch.model_dump(
                        exclude_none=True,
                        exclude_defaults=True,
                    )
                ),
            )
            return parsed

    @classmethod
    def _parse_response(cls, value: Any, text: str) -> ProcurementTurnExtraction:
        if isinstance(value, ProcurementTurnExtraction):
            return value
        if isinstance(value, BaseModel):
            return ProcurementTurnExtraction.model_validate(value.model_dump())
        if isinstance(value, dict):
            return ProcurementTurnExtraction.model_validate(value)
        if text.strip():
            return ProcurementTurnExtraction.model_validate_json(text)
        return ProcurementTurnExtraction()


class DepartmentCandidateResolver:
    """Structured Synthetic Data matcher; it never selects among multiple matches."""

    def __init__(self, departments: Iterable[Department]) -> None:
        self.departments = list(departments)

    @staticmethod
    def _base_name(value: str) -> str:
        return value.split("（", 1)[0].split("(", 1)[0].strip()

    def candidates(self, identifier: str) -> list[dict[str, str]]:
        value = identifier.casefold().strip()
        exact: list[Department] = []
        partial: list[Department] = []
        for department in self.departments:
            base_name = self._base_name(department.name)
            if value in {
                department.department_code.casefold(),
                department.name.casefold(),
                base_name.casefold(),
            }:
                exact.append(department)
            elif value and value in base_name.casefold():
                partial.append(department)
        return [
            {"department_code": item.department_code, "name": item.name}
            for item in (exact or partial)
        ]
