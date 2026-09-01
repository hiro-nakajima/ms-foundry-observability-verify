from pathlib import Path

import pytest

from procurement_agent.models import ProcurementRequest, RequestConstraints


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def valid_request() -> ProcurementRequest:
    return ProcurementRequest(
        request_id="REQ-SYNTH-001",
        query="開発用ノートPC",
        quantity=2,
        applicant_name="架空 太郎",
        department_name="開発部（架空部署）",
        purpose="開発",
        constraints=RequestConstraints(budget_limit="400000", specifications={"memory": "32GB"}),
    )
