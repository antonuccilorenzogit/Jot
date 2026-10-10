"""
Converts a PNG image to icon formats needed by PyInstaller:
  - assets/icon.ico  (Windows)
  - assets/icon.icns (macOS)

Usage:
    python scripts/make_icons.py <path_to_source.png>
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

try:
    from PIL import Image  # type: ignore[import-untyped]
except ImportError:
    import subprocess

    subprocess.run([sys.executable, "-m", "pip", "install", "Pillow"], check=True)
    from PIL import Image  # type: ignore[import-untyped]


ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]
ICNS_SIZES = {
    16: b"icp4",
    32: b"icp5",
    64: b"icp6",
    128: b"ic07",
    256: b"ic08",
    512: b"ic09",
    1024: b"ic10",
}


def make_ico(src: Image.Image, dest: Path) -> None:
    src.save(dest, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    print(f"[OK] {dest}")


def _png_bytes(img: Image.Image, size: int) -> bytes:
    """Return raw PNG bytes for the given square size."""
    import io

    frame = img.copy()
    frame.thumbnail((size, size), Image.LANCZOS)  # type: ignore[attr-defined]
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    offset = ((size - frame.width) // 2, (size - frame.height) // 2)
    canvas.paste(frame, offset, frame if frame.mode == "RGBA" else None)
    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


def make_icns(src: Image.Image, dest: Path) -> None:
    """Build a minimal ICNS file from PNG chunks (pure-Python, no macOS tools needed)."""
    chunks: list[bytes] = []
    for size, type_code in ICNS_SIZES.items():
        png_data = _png_bytes(src, size)
        chunk_len = 8 + len(png_data)
        chunks.append(type_code + struct.pack(">I", chunk_len) + png_data)

    body = b"".join(chunks)
    file_len = 8 + len(body)
    icns_data = b"icns" + struct.pack(">I", file_len) + body
    dest.write_bytes(icns_data)
    print(f"[OK] {dest}")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/make_icons.py <source.png>")
        sys.exit(1)

    src_path = Path(sys.argv[1])
    if not src_path.exists():
        print(f"File non trovato: {src_path}")
        sys.exit(1)

    ASSETS.mkdir(exist_ok=True)
    img = Image.open(src_path).convert("RGBA")

    make_ico(img, ASSETS / "icon.ico")
    make_icns(img, ASSETS / "icon.icns")
    print("Done. Files saved in assets/")


if __name__ == "__main__":
    main()
