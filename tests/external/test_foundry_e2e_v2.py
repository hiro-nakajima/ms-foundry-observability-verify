import os
import pytest


@pytest.mark.external
@pytest.mark.skipif(
    not (os.getenv("FOUNDRY_PROJECT_ENDPOINT") and os.getenv("PROCUREMENT_PARENT_MODEL_DEPLOYMENT") and os.getenv("RUN_AZURE_E2E") == "1"),
    reason="Azure Core E2E requires an explicit deployment and credential gate",
)
def test_deployed_foundry_core_matrix():
    from scripts.run_azure_core_validation import main
    main()
