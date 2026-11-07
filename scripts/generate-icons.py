"""Draw the tiny toolbar icons without any third-party image libraries."""
from pathlib import Path
import struct
import zlib

ROOT = Path(__file__).resolve().parents[1] / "extension" / "icons"
ROOT.mkdir(parents=True, exist_ok=True)


def color_at(x, y, background):
    cx = min(max(x, .26), .74)
    cy = min(max(y, .26), .74)
    if (x - cx) ** 2 + (y - cy) ** 2 > .18 ** 2:
        return None
    if abs(y - .5) <= .19 and .40 <= x <= .40 + .27 * (1 - abs(y - .5) / .19):
        return (255, 255, 255)
    return background


def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


for state, background in [("active", (251, 90, 140)), ("inactive", (143, 151, 165))]:
    for size in [16, 32, 48, 128]:
        rows = bytearray()
        for y in range(size):
            rows.append(0)
            for x in range(size):
                samples = [color_at((x + (sx + .5) / 4) / size, (y + (sy + .5) / 4) / size, background)
                           for sy in range(4) for sx in range(4)]
                filled = [s for s in samples if s]
                rows.extend([round(sum(s[c] for s in filled) / len(filled)) for c in range(3)] + [round(len(filled) * 255 / 16)]
                            if filled else [0, 0, 0, 0])
        header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
        png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")
        (ROOT / f"{state}-{size}.png").write_bytes(png)
