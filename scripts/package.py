"""Package only extension assets at the ZIP root with reproducible metadata."""
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
with ZipFile(ROOT / "bili-ninja.zip", "w", ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted((ROOT / "extension").rglob("*")):
        relative = path.relative_to(ROOT / "extension")
        if path.is_file() and not any(part.startswith(".") for part in relative.parts):
            info = ZipInfo(relative.as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, path.read_bytes(), compress_type=ZIP_DEFLATED, compresslevel=9)
print(f"Created bili-ninja.zip ({(ROOT / 'bili-ninja.zip').stat().st_size} bytes)")
