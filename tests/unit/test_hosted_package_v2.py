import subprocess
import sys
import zipfile

from scripts.package_hosted import package


def test_flat_hosted_zip_excludes_data_web_and_local_state(tmp_path):
    target = tmp_path / "hosted.zip"
    manifest = package(target)
    assert manifest["acrRequired"] is False
    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
        assert {"main.py", "requirements.txt", "requirements-lock.txt", "procurement_agent/hosted_app.py"} <= set(names)
        assert "procurement_agent/devui_app.py" not in names
        assert {"trace_pipeline/__init__.py", "trace_pipeline/detectors.py",
                "trace_pipeline/envelope.py", "trace_pipeline/stage_b.py"} <= set(names)
        assert all(name in {"main.py", "requirements.txt", "requirements-lock.txt"} or
                   name.startswith(("procurement_agent/", "trace_pipeline/"))
                   and name.endswith(".py") for name in names)
        archive.extractall(tmp_path / "extracted")
    result = subprocess.run([sys.executable, "main.py", "--smoke"], cwd=tmp_path / "extracted",
                            capture_output=True, text=True, check=True)
    assert '"azure_apply": false' in result.stdout
