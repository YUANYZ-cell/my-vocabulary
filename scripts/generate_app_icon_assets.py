from __future__ import annotations

import argparse
import io
import struct
from pathlib import Path

import cairosvg
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
SVG_PATH = ROOT / "app" / "assets" / "app-icon.svg"
ICON_DIRECTORY = ROOT / "app" / "assets" / "icons"

# Windows 11 taskbar targets at 100%, 125%, 150%, 200%, 250%, 300%, and 400%,
# plus common title-bar, shortcut, and shell sizes.
ICO_SIZES = (16, 20, 24, 30, 32, 36, 40, 48, 60, 64, 72, 96, 128, 256)
COMPACT_SIZES = tuple(size for size in ICO_SIZES if size <= 96)

# Microsoft Edge PWA app-icon scales (44px base) plus installability sources.
PWA_SIZES = (44, 55, 66, 88, 176, 192, 512)
PNG_SIZES = tuple(sorted(set(ICO_SIZES) | set(PWA_SIZES)))


def render_png(svg: bytes, size: int) -> bytes:
    rendered = cairosvg.svg2png(
        bytestring=svg,
        output_width=size,
        output_height=size,
    )
    with Image.open(io.BytesIO(rendered)) as image:
        output = io.BytesIO()
        image.convert("RGBA").save(output, format="PNG", optimize=True)
        return output.getvalue()


def render_compact_png(size: int) -> bytes:
    """Draw the small icon on its native pixel grid instead of shrinking the 512px art."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    inset = max(1, round(size * 0.04))
    radius = max(3, round(size * 0.22))
    draw.rounded_rectangle(
        (inset, inset, size - inset - 1, size - inset - 1),
        radius=radius,
        fill="#174d3b",
    )

    left = round(size * 0.18)
    right = size - left - 1
    top = round(size * 0.25)
    bottom = round(size * 0.76)
    middle = size // 2
    fold = max(2, round(size * 0.06))
    page_bottom = bottom - fold
    draw.polygon(
        ((left, top), (middle - fold, top), (middle, top + fold),
         (middle, bottom), (middle - fold, page_bottom), (left, page_bottom)),
        fill="#fffdf7",
    )
    draw.polygon(
        ((middle, top + fold), (middle + fold, top), (right, top),
         (right, page_bottom), (middle + fold, page_bottom), (middle, bottom)),
        fill="#cfe6dc" if size <= 20 else "#dcebe3",
    )
    if size <= 20:
        draw.line((middle, top + fold, middle, bottom - 1), fill="#174d3b", width=1)

    # Literal decoration is intentionally omitted below 48px; at tiny sizes the
    # open-book silhouette is the defining detail and must remain uncluttered.
    if size >= 48:
        ribbon_width = max(2, round(size * 0.07))
        ribbon_left = right - round(size * 0.18)
        ribbon_bottom = top + round(size * 0.30)
        draw.polygon(
            ((ribbon_left, top), (ribbon_left + ribbon_width, top),
             (ribbon_left + ribbon_width, ribbon_bottom),
             (ribbon_left + ribbon_width // 2, ribbon_bottom - fold),
             (ribbon_left, ribbon_bottom)),
            fill="#db684d",
        )

    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Windows and PWA icon assets.")
    parser.add_argument("--check", action="store_true", help="verify generated assets without rewriting")
    args = parser.parse_args()

    svg = SVG_PATH.read_bytes()
    rendered = {
        size: render_compact_png(size) if size in COMPACT_SIZES else render_png(svg, size)
        for size in PNG_SIZES
    }
    ico_frames = [(size, rendered[size]) for size in ICO_SIZES]

    expected_files = {
        ICON_DIRECTORY / f"app-icon-{size}.png": payload
        for size, payload in rendered.items()
    }
    temporary_ico = io.BytesIO()
    header_size = 6 + 16 * len(ico_frames)
    offset = header_size
    entries = []
    payloads = []
    for size, payload in ico_frames:
        dimension = 0 if size == 256 else size
        entries.append(struct.pack("<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(payload), offset))
        payloads.append(payload)
        offset += len(payload)
    ico_payload = struct.pack("<HHH", 0, 1, len(ico_frames)) + b"".join(entries) + b"".join(payloads)
    expected_files.update(
        {
            ROOT / "app" / "assets" / "app-icon.ico": ico_payload,
            ROOT / "app" / "assets" / "app-icon-v5.ico": ico_payload,
            ROOT / "app" / "assets" / "favicon-v5.ico": ico_payload,
        }
    )

    if args.check:
        mismatches = [str(path.relative_to(ROOT)) for path, payload in expected_files.items() if not path.is_file() or path.read_bytes() != payload]
        if mismatches:
            raise SystemExit("Icon assets are stale or missing: " + ", ".join(mismatches))
        print(f"Verified {len(expected_files)} generated icon assets.")
        return

    ICON_DIRECTORY.mkdir(parents=True, exist_ok=True)
    for path, payload in expected_files.items():
        path.write_bytes(payload)
    print(f"Generated {len(expected_files)} icon assets from {SVG_PATH.relative_to(ROOT)}.")


if __name__ == "__main__":
    main()
