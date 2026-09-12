"""Build an allowlisted deployment ZIP without touching the supplied webapp.zip."""
import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--vendor", type=Path, help="Prebuilt Linux/Python 3.13 site-packages; disable Oryx build for this ZIP")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    files = ["startup.sh", "requirements.txt", "backend/server.py",
             "backend/procurement_flow.py", "backend/telemetry.py",
             "backend/auth.py", "backend/foundry_client.py",
             "backend/static/index.html", "backend/static/app.js", "backend/static/styles.css"]
    # Exclusive creation prevents overwriting user artifacts or a previous package.
    with ZipFile(args.output, "x", ZIP_DEFLATED) as archive:
        for name in files:
            archive.write(root / name, name)
        if args.vendor:
            for source in sorted(args.vendor.rglob("*")):
                if source.is_file() and "__pycache__" not in source.parts and source.suffix != ".pyc":
                    archive.write(source, ".python_packages/lib/site-packages/" + source.relative_to(args.vendor).as_posix())
    print(args.output)


if __name__ == "__main__":
    main()
