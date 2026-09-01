import json
from pathlib import Path
import subprocess
import sys

import yaml

from scripts.prepare_search_documents import build_documents, write_outputs
from scripts.validate_deployment_assets import validate as validate_deployment_assets


ROOT = Path(__file__).parents[2]


def test_synthetic_data_versions_and_department_level_contract():
    files = ["catalog.json", "account_codes.json", "departments.json", "applicants.json", "delivery_rules.json", "tax_rules.json"]
    values = [json.loads((ROOT / "data" / name).read_text(encoding="utf-8")) for name in files]
    assert {value["data_version"] for value in values} == {"2026-09-01.1"}
    assert all(value["synthetic"] for value in values)
    assert len(values[0]["records"]) == 10
    for department in values[2]["records"]:
        assert set(department) >= {"department_code", "department_name"}
        assert not {"section_code", "team_code", "unit_code"} & set(department)


def test_search_documents_are_deterministic_and_grounded():
    first = build_documents()
    second = build_documents()
    assert first == second
    catalog, codes, manifest = first
    source_codes = {item["product_code"] for item in json.loads((ROOT / "data/catalog.json").read_text(encoding="utf-8"))["records"]}
    assert {item["product_code"] for item in catalog} == source_codes
    assert len(catalog) == 10
    assert manifest["catalog_document_count"] == 10
    assert all(item["source_version"] == manifest["source_version"] for item in catalog + codes)


def test_search_upload_batches_have_data_plane_action(tmp_path):
    write_outputs(tmp_path)
    for name in ("catalog-upload-batch.json", "code-upload-batch.json"):
        batch = json.loads((tmp_path / name).read_text(encoding="utf-8"))
        assert batch["value"]
        assert {item["@search.action"] for item in batch["value"]} == {"upload"}


def test_prompt_agents_connect_only_their_owned_toolbox():
    expected = {
        "catalog-search-agent.yaml": ["catalog-search-toolbox"],
        "code-determination-agent.yaml": ["code-master-toolbox"],
    }
    for name, toolboxes in expected.items():
        definition = yaml.safe_load((ROOT / "infra/foundry/agents" / name).read_text(encoding="utf-8"))
        assert definition["kind"] == "prompt"
        assert definition["toolboxes"] == toolboxes
    manifest = json.loads((ROOT / "infra/foundry/agents/manifest.json").read_text(encoding="utf-8"))
    assert manifest["container_includes_child_implementations"] is False


def test_deployment_assets_have_separated_rbac_and_no_child_implementation():
    result = validate_deployment_assets()
    assert result["rbac_identities"] == ["runtime", "index_manager", "document_ingestor"]
    assert result["azure_apply_performed"] is False


def test_azure_yaml_uses_official_split_service_hosts_and_reserved_env_rules():
    definition = yaml.safe_load((ROOT / "azure.yaml").read_text(encoding="utf-8"))
    hosts = {name: service["host"] for name, service in definition["services"].items()}
    assert hosts["ai-project"] == "azure.ai.project"
    assert hosts["catalog-search-toolbox"] == "azure.ai.toolbox"
    assert hosts["code-master-toolbox"] == "azure.ai.toolbox"
    assert hosts["procurement-parent"] == "azure.ai.agent"
    assert definition["services"]["procurement-parent"]["kind"] == "hosted"
    env = definition["services"]["procurement-parent"]["env"]
    assert not any(name.startswith("FOUNDRY_") for name in env)


def test_runtime_dependency_pins_are_consistent():
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    lock = (ROOT / "requirements-lock.txt").read_text(encoding="utf-8")
    for pin in ("agent-framework-core==1.16.0", "agent-framework-foundry==1.11.0", "agent-framework-foundry-hosting==1.0.0b260827"):
        assert pin in project and pin in requirements and pin in lock
    for pin in ("azure-ai-inference==1.0.0b9", "azure-ai-projects==2.3.0", "azure-storage-blob==12.30.1"):
        assert pin in lock


def test_smoke_entrypoints_do_not_require_credentials():
    for module in ("procurement_agent.devui_app", "procurement_agent.hosted_app"):
        completed = subprocess.run([sys.executable, "-m", module, "--smoke"], cwd=ROOT, capture_output=True, text=True, check=True)
        output = json.loads(completed.stdout)
        assert output["architecture_id"] == "procurement_application_v2"
        assert output["azure_apply"] is False
