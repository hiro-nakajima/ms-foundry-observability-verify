from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from procurement_agent.models import (
    AccountCode,
    Applicant,
    ApplicationDraft,
    CalculationResult,
    CatalogItem,
    DeliveryEstimate,
    Department,
    DraftAccount,
    DraftApplicant,
    DraftItem,
)
from procurement_agent.tools import LocalJsonAdapter


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def adapter() -> LocalJsonAdapter:
    return LocalJsonAdapter(ROOT / "data")


@pytest.fixture
def valid_draft(adapter: LocalJsonAdapter) -> ApplicationDraft:
    item = CatalogItem.model_validate(adapter.get_catalog_item("LAPTOP-DEV-14").result["item"])
    applicant = Applicant.model_validate(adapter.get_applicant("EMP-001").result["applicant"])
    department = Department.model_validate(
        adapter.lookup_department(applicant.department_code).result["department"]
    )
    account = AccountCode.model_validate(
        adapter.lookup_account_code(item.category, "開発").result["account_code"]
    )
    delivery = DeliveryEstimate.model_validate(
        adapter.estimate_delivery(item.product_code, 3, date(2026, 9, 30)).result["delivery"]
    )
    calculation = CalculationResult.model_validate(
        adapter.calculate_request(3, str(item.unit_price)).result["calculation"]
    )
    return ApplicationDraft(
        request_id="PR-DRAFT-0001",
        item=DraftItem(
            product_code=item.product_code,
            name=item.name,
            quantity=3,
            unit_price=item.unit_price,
            currency=item.currency,
        ),
        amount=calculation,
        delivery=delivery,
        applicant=DraftApplicant(
            employee_id=applicant.employee_id,
            name=applicant.name,
            department_code=department.department_code,
        ),
        account=DraftAccount(account_code=account.account_code, label=account.label),
        evidence_refs=[
            f"catalog:{item.product_code}:{adapter.data_version}",
            f"applicant:{applicant.employee_id}:{adapter.data_version}",
            f"department:{department.department_code}:{adapter.data_version}",
            f"account:{account.account_code}:{adapter.data_version}",
            f"delivery:{item.product_code}:{delivery.rule_id}:{adapter.data_version}",
        ],
    )
