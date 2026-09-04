"""Build an allowlisted deployment ZIP without touching the supplied webapp.zip."""
import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    files = ["startup.sh", "requirements.txt", "backend/procurement.py",
             "backend/static/procurement.html", "backend/static/procurement.js", "backend/static/styles.css"]
    # Exclusive creation prevents overwriting user artifacts or a previous package.
    with ZipFile(args.output, "x", ZIP_DEFLATED) as archive:
        for name in files:
            archive.write(root / name, name)
    print(args.output)


if __name__ == "__main__":
    main()
