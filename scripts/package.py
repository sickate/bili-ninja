"""Package every extension asset, including toolbar icons, at the ZIP root."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
with ZipFile(ROOT / "bili-ninja.zip", "w", ZIP_DEFLATED) as archive:
    for path in sorted((ROOT / "extension").rglob("*")):
        if path.is_file() and not any(part.startswith(".") for part in path.relative_to(ROOT / "extension").parts):
            archive.write(path, path.relative_to(ROOT / "extension"))
print(f"Created bili-ninja.zip ({(ROOT / 'bili-ninja.zip').stat().st_size} bytes)")
