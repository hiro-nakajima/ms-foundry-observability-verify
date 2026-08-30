"""Logical procurement tool port and deterministic local JSON adapter."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from importlib.resources import files
from importlib.resources.abc import Traversable
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol
from uuid import uuid4

from pydantic import TypeAdapter

from .models import (
    AccountCode,
    Applicant,
    ApplicationDraft,
    BusinessStatus,
    CalculationResult,
    CatalogItem,
    DeliveryEstimate,
    Department,
    TechnicalStatus,
    ToolResponse,
    ValidationResult,
)


DATA_FILENAMES = (
    "catalog.json",
    "account_codes.json",
    "departments.json",
    "delivery_rules.json",
    "applicants.json",
    "tax_rules.json",
)
REPOSITORY_DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def default_data_resource() -> Traversable:
    """Resolve packaged data first and the repository source of truth as fallback."""

    packaged = files("procurement_agent").joinpath("data")
    if packaged.is_dir():
        return packaged
    if REPOSITORY_DATA_DIR.is_dir():
        return REPOSITORY_DATA_DIR
    raise FileNotFoundError("procurement synthetic data resource is unavailable")


class ProcurementToolPort(Protocol):
    """Stable logical contract implemented by local, Functions, MCP, or Search adapters."""

    def search_catalog(self, query: str, *, limit: int = 5) -> ToolResponse: ...

    def get_catalog_item(self, product_code: str) -> ToolResponse: ...

    def lookup_account_code(self, category: str, purpose: str) -> ToolResponse: ...

    def lookup_department(self, identifier: str) -> ToolResponse: ...

    def get_applicant(self, identifier: str) -> ToolResponse: ...

    def estimate_delivery(
        self, product_code: str, quantity: int, requested_by: date | None
    ) -> ToolResponse: ...

    def calculate_request(
        self, quantity: int, unit_price: str, *, discount_rate: str = "0"
    ) -> ToolResponse: ...

    def validate_application(self, draft: ApplicationDraft) -> ToolResponse: ...


class DataContractError(ValueError):
    pass


class LocalJsonAdapter:
    """Deterministic adapter whose source of truth is the versioned JSON data directory."""

    def __init__(
        self,
        data_dir: str | Path | Traversable,
        *,
        as_of_date: date = date(2026, 8, 28),
    ) -> None:
        self.data_dir = Path(data_dir) if isinstance(data_dir, str) else data_dir
        self.as_of_date = as_of_date
        documents = {name: self._load_document(name) for name in DATA_FILENAMES}
        versions = {document["data_version"] for document in documents.values()}
        if len(versions) != 1:
            raise DataContractError(f"all JSON documents must share one data_version: {versions}")
        self.data_version = versions.pop()
        self.catalog = TypeAdapter(list[CatalogItem]).validate_python(documents["catalog.json"]["records"])
        self.account_codes = TypeAdapter(list[AccountCode]).validate_python(
            documents["account_codes.json"]["records"]
        )
        self.departments = TypeAdapter(list[Department]).validate_python(
            documents["departments.json"]["records"]
        )
        self.applicants = TypeAdapter(list[Applicant]).validate_python(
            documents["applicants.json"]["records"]
        )
        self.delivery_rules = documents["delivery_rules.json"]["records"]
        self.tax_rules = documents["tax_rules.json"]["records"]
        self._calculation_module = self._load_skill_module("calculate_request.py")
        self._validation_module = self._load_skill_module("validate_request.py")

    def _load_document(self, filename: str) -> dict[str, Any]:
        path = self.data_dir.joinpath(filename)
        document = json.loads(path.read_text(encoding="utf-8"))
        required = {"schema_version", "data_version", "synthetic", "records"}
        missing = required - document.keys()
        if missing:
            raise DataContractError(f"{filename} missing fields: {sorted(missing)}")
        if document["synthetic"] is not True:
            raise DataContractError(f"{filename} must be explicitly synthetic")
        if not isinstance(document["records"], list) or not document["records"]:
            raise DataContractError(f"{filename} records must be a non-empty list")
        return document

    @staticmethod
    def _load_skill_module(script_name: str) -> ModuleType:
        script_path = Path(__file__).parent / "skills" / "request-check" / "scripts" / script_name
        module_name = f"procurement_skill_{script_path.stem}_{hashlib.sha256(str(script_path).encode()).hexdigest()[:8]}"
        spec = importlib.util.spec_from_file_location(module_name, script_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load skill script {script_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _response(
        self,
        *,
        business_status: BusinessStatus,
        result: dict[str, Any] | None = None,
        evidence_refs: list[str] | None = None,
        warnings: list[str] | None = None,
    ) -> ToolResponse:
        return ToolResponse(
            call_id=f"tool-{uuid4()}",
            http_status=200,
            technical_status=TechnicalStatus.SUCCESS,
            business_status=business_status,
            data_version=self.data_version,
            result=result or {},
            evidence_refs=evidence_refs or [],
            warnings=warnings or [],
        )

    def search_catalog(self, query: str, *, limit: int = 5) -> ToolResponse:
        normalized = query.casefold().strip()
        if not normalized:
            return self._response(
                business_status=BusinessStatus.INVALID_INPUT,
                warnings=["query is required"],
            )
        candidates: list[dict[str, Any]] = []
        for item in self.catalog:
            if not (item.valid_from <= self.as_of_date <= item.valid_to):
                continue
            product_code_hit = 1 if normalized == item.product_code.casefold() else 0
            keyword_hits = sum(1 for keyword in item.keywords if keyword.casefold() in normalized)
            name_hit = 1 if normalized in item.name.casefold() else 0
            category_hit = 1 if item.category.casefold() in normalized else 0
            score = (
                product_code_hit * 100
                + keyword_hits * 10
                + name_hit * 5
                + category_hit * 3
            )
            if score:
                candidates.append({"score": score, "item": item.model_dump(mode="json")})
        candidates.sort(key=lambda row: (-row["score"], row["item"]["product_code"]))
        selected = candidates[:limit]
        if not selected:
            return self._response(business_status=BusinessStatus.NOT_FOUND)
        evidence = [f"catalog:{row['item']['product_code']}:{self.data_version}" for row in selected]
        return self._response(
            business_status=BusinessStatus.SUCCESS,
            result={"candidates": selected},
            evidence_refs=evidence,
        )

    def get_catalog_item(self, product_code: str) -> ToolResponse:
        for item in self.catalog:
            if (
                item.product_code == product_code
                and item.valid_from <= self.as_of_date <= item.valid_to
            ):
                evidence = f"catalog:{item.product_code}:{self.data_version}"
                return self._response(
                    business_status=BusinessStatus.SUCCESS,
                    result={"item": item.model_dump(mode="json")},
                    evidence_refs=[evidence],
                )
        return self._response(business_status=BusinessStatus.NOT_FOUND)

    def lookup_account_code(self, category: str, purpose: str) -> ToolResponse:
        purpose_folded = purpose.casefold()
        for account in self.account_codes:
            if not (account.valid_from <= self.as_of_date <= account.valid_to):
                continue
            category_match = category in account.categories
            purpose_match = any(value.casefold() in purpose_folded for value in account.purposes)
            if category_match and purpose_match:
                evidence = f"account:{account.account_code}:{self.data_version}"
                return self._response(
                    business_status=BusinessStatus.SUCCESS,
                    result={"account_code": account.model_dump(mode="json")},
                    evidence_refs=[evidence],
                )
        return self._response(business_status=BusinessStatus.NOT_FOUND)

    def lookup_department(self, identifier: str) -> ToolResponse:
        value = identifier.casefold().strip()
        if not value:
            return self._response(
                business_status=BusinessStatus.INVALID_INPUT,
                warnings=["department identifier is required"],
            )
        active_departments = [
            department
            for department in self.departments
            if department.valid_from <= self.as_of_date <= department.valid_to
        ]
        exact = [
            department
            for department in active_departments
            if department.department_code.casefold() == value
            or department.name.casefold() == value
        ]
        partial = [
            department
            for department in active_departments
            if value in department.name.casefold()
        ]
        matches = exact or partial
        if len(matches) > 1:
            evidence = [
                f"department:{department.department_code}:{self.data_version}"
                for department in matches
            ]
            return self._response(
                business_status=BusinessStatus.CLARIFICATION_REQUIRED,
                result={
                    "clarification": {
                        "field": "department_name",
                        "required_input_refs": ["request.department_name"],
                        "prompt": "部門コードまたは正式な部門名を指定してください。",
                        "options": [
                            {
                                "department_code": department.department_code,
                                "name": department.name,
                            }
                            for department in matches
                        ],
                    }
                },
                evidence_refs=evidence,
                warnings=["department identifier is ambiguous"],
            )
        if matches:
            department = matches[0]
            evidence = f"department:{department.department_code}:{self.data_version}"
            return self._response(
                business_status=BusinessStatus.SUCCESS,
                result={"department": department.model_dump(mode="json")},
                evidence_refs=[evidence],
            )
        return self._response(business_status=BusinessStatus.NOT_FOUND)

    def get_applicant(self, identifier: str) -> ToolResponse:
        value = identifier.casefold().strip()
        if not value:
            return self._response(
                business_status=BusinessStatus.INVALID_INPUT,
                warnings=["applicant identifier is required"],
            )
        exact = [
            applicant
            for applicant in self.applicants
            if applicant.employee_id.casefold() == value
            or applicant.name.casefold() == value
        ]
        partial = [
            applicant
            for applicant in self.applicants
            if value in applicant.name.casefold()
        ]
        matches = exact or partial
        if len(matches) > 1:
            evidence = [
                f"applicant:{applicant.employee_id}:{self.data_version}"
                for applicant in matches
            ]
            return self._response(
                business_status=BusinessStatus.CLARIFICATION_REQUIRED,
                result={
                    "clarification": {
                        "field": "applicant_name",
                        "required_input_refs": ["request.applicant_name"],
                        "prompt": "社員IDまたは一意な氏名を指定してください。",
                        "options": [
                            {
                                "employee_id": applicant.employee_id,
                                "name": applicant.name,
                            }
                            for applicant in matches
                        ],
                    }
                },
                evidence_refs=evidence,
                warnings=["applicant identifier is ambiguous"],
            )
        if matches:
            applicant = matches[0]
            status = BusinessStatus.SUCCESS if applicant.active else BusinessStatus.BLOCKED
            evidence = f"applicant:{applicant.employee_id}:{self.data_version}"
            return self._response(
                business_status=status,
                result={"applicant": applicant.model_dump(mode="json")},
                evidence_refs=[evidence],
            )
        return self._response(business_status=BusinessStatus.NOT_FOUND)

    def estimate_delivery(
        self, product_code: str, quantity: int, requested_by: date | None
    ) -> ToolResponse:
        item_response = self.get_catalog_item(product_code)
        if item_response.business_status != BusinessStatus.SUCCESS:
            return self._response(business_status=BusinessStatus.NOT_FOUND)
        if quantity <= 0:
            return self._response(
                business_status=BusinessStatus.INVALID_INPUT,
                warnings=["quantity must be positive"],
            )
        item = CatalogItem.model_validate(item_response.result["item"])
        in_stock = quantity <= item.stock
        condition = "quantity_lte_stock" if in_stock else "quantity_gt_stock"
        rule = next(
            (
                rule
                for rule in self.delivery_rules
                if rule["condition"] == condition
            ),
            None,
        )
        if rule is None:
            return self._response(
                business_status=BusinessStatus.NOT_FOUND,
                warnings=[f"delivery rule not found for condition: {condition}"],
            )
        estimated_on = self.as_of_date + timedelta(days=item.lead_time_days + rule["additional_days"])
        meets_request = requested_by is None or estimated_on <= requested_by
        warnings = [] if in_stock else ["requested quantity exceeds current stock"]
        if not meets_request:
            warnings.append("requested delivery date cannot be met")
        estimate = DeliveryEstimate(
            product_code=product_code,
            quantity=quantity,
            requested_by=requested_by,
            estimated_on=estimated_on,
            meets_request=meets_request,
            rule_id=rule["rule_id"],
            warnings=warnings,
        )
        evidence = f"delivery:{product_code}:{rule['rule_id']}:{self.data_version}"
        status = BusinessStatus.SUCCESS if in_stock else BusinessStatus.INSUFFICIENT_STOCK
        return self._response(
            business_status=status,
            result={"delivery": estimate.model_dump(mode="json")},
            evidence_refs=[evidence],
            warnings=warnings,
        )

    def calculate_request(
        self, quantity: int, unit_price: str, *, discount_rate: str = "0"
    ) -> ToolResponse:
        active_rules = self.active_tax_rules()
        if not active_rules:
            return self._response(
                business_status=BusinessStatus.NOT_FOUND,
                warnings=[f"no active tax rule for {self.as_of_date.isoformat()}"],
            )
        if len(active_rules) > 1:
            return self._response(
                business_status=BusinessStatus.BLOCKED,
                warnings=[
                    f"multiple active tax rules for {self.as_of_date.isoformat()}"
                ],
            )
        active_rule = active_rules[0]
        try:
            raw_result = self._calculation_module.calculate_request(
                quantity=quantity,
                unit_price=unit_price,
                tax_rate=active_rule["tax_rate"],
                discount_rate=discount_rate,
                rounding_mode=active_rule["rounding_mode"],
                rounding_unit=active_rule["rounding_unit"],
            )
            result = CalculationResult.model_validate(raw_result)
        except (ValueError, ArithmeticError) as exc:
            return self._response(
                business_status=BusinessStatus.INVALID_INPUT,
                warnings=[str(exc)],
            )
        evidence = f"tax:{active_rule['rule_id']}:{self.data_version}"
        return self._response(
            business_status=BusinessStatus.SUCCESS,
            result={"calculation": result.model_dump(mode="json")},
            evidence_refs=[evidence],
        )

    def active_tax_rules(self) -> list[dict[str, Any]]:
        return [
            rule
            for rule in self.tax_rules
            if date.fromisoformat(rule["valid_from"])
            <= self.as_of_date
            <= date.fromisoformat(rule["valid_to"])
        ]

    def validate_application(self, draft: ApplicationDraft) -> ToolResponse:
        validation_data = self._validation_module.validate_request(draft.model_dump(mode="json"))
        validation = ValidationResult.model_validate(validation_data)
        status = BusinessStatus.SUCCESS if validation.valid else BusinessStatus.VALIDATION_FAILED
        return self._response(
            business_status=status,
            result={"validation": validation.model_dump(mode="json")},
            evidence_refs=validation.evidence_refs,
            warnings=validation.violations,
        )
