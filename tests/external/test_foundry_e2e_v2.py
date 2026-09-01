import os
import pytest


@pytest.mark.external
@pytest.mark.skipif(
    not (os.getenv("FOUNDRY_PROJECT_ENDPOINT") and os.getenv("PROCUREMENT_PARENT_MODEL_DEPLOYMENT") and os.getenv("RUN_AZURE_E2E") == "1"),
    reason="Azure apply/deployed credentials were not approved or supplied; local recorded MCP contracts cover the offline boundary",
)
def test_deployed_foundry_core_matrix_requires_explicit_gate():
    pytest.fail("Set RUN_AZURE_E2E=1 only after the Azure apply gate and implement the approved resource IDs in the run manifest")
