#!/usr/bin/env python3
"""Generate same-panel physical-index cards and a small MonoFast baseline."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
PORTRAIT = (480, 720)
NATIVE = (720, 480)
PANEL_IDENTITY = {
    "panel": "HINK-T037A02-A1 / EPD037A02",
    "controller": "JD7601",
    "nativeSize": list(NATIVE),
    "viewSize": list(PORTRAIT),
    "view": "portrait, flex cable down; top-left dot is the orientation reference",
}
FORMATS = {"ColorQual": 2, "ColorFast": 3, "MonoFast": 1}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def js_array(source: str, name: str) -> list:
    """Read numeric array literals only; never evaluate JavaScript."""
    match = re.search(r"\bvar\s+" + re.escape(name) + r"\s*=\s*(\[.*?\]);", source, re.S)
    if not match:
        raise ValueError(f"Numeric array {name} not found in current Web source")
    literal = re.sub(r"//[^\n]*|/\*.*?\*/", "", match.group(1), flags=re.S)
    return ast.literal_eval(literal)


def load_profiles() -> tuple[dict, dict]:
    path = ROOT / "tools/ForFilm/js/convert.js"
    raw = path.read_bytes()
    source = raw.decode("utf-8-sig")
    fast = re.search(r"colorFast55\s*:\s*\{.*?candidateIndexes\s*:\s*(\[.*?\])", source, re.S)
    if not fast:
        raise ValueError("ColorFast current candidate list not found")
    profiles = {
        "ColorQual": {"palette": js_array(source, "CF_PALETTE_QUAL"),
                      "candidates": js_array(source, "CF_QUAL_CANDIDATE_INDEXES"),
                      "white": 15, "dark": 3},
        "ColorFast": {"palette": js_array(source, "CF_PALETTE_FAST"),
                      "candidates": ast.literal_eval(fast.group(1)),
                      "white": 21, "dark": 0},
    }
    for profile in profiles.values():
        palette = profile["palette"]
        if len(palette) != 64 or any(len(rgb) != 3 or any(type(c) is not int or not 0 <= c <= 255 for c in rgb) for rgb in palette):
            raise ValueError("Expected 64 RGB byte triplets in Web palette")
        candidates = profile["candidates"]
        if not candidates or len(set(candidates)) != len(candidates) or any(type(i) is not int or not 0 <= i < 64 for i in candidates):
            raise ValueError("Invalid Web candidate indexes")
    return profiles, {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(raw),
                      "arrays": ["CF_PALETTE_QUAL", "CF_PALETTE_FAST"],
                      "colorMeaning": "Current Web RGB estimates, not measurements of this physical panel"}


def native_image(portrait: Image.Image) -> Image.Image:
    """(px,py) -> native (719-py,px), shared by 8bpp and 1bpp."""
    if portrait.size != PORTRAIT:
        raise ValueError(f"Expected portrait canvas {PORTRAIT}")
    return portrait.transpose(Image.Transpose.ROTATE_270)


def frame_body(portrait: Image.Image, format_code: int) -> bytes:
    native = native_image(portrait)
    if format_code in (2, 3):
        if portrait.mode != "P" or max(portrait.getdata()) > 63:
            raise ValueError("8bpp requires physical indexes 0..63")
        return native.tobytes()
    if format_code != 1 or portrait.mode != "L":
        raise ValueError("MonoFast requires L canvas with 0 black / 255 white")
    # Pillow mode 1 is MSB-first, 1=white. Invert to film's MSB-first 1=black.
    return bytes(value ^ 0xFF for value in native.convert("1", dither=Image.Dither.NONE).tobytes())


def film_bytes(frames: list[Image.Image], format_code: int) -> bytes:
    if not 1 <= len(frames) <= 48 or format_code not in (1, 2, 3):
        raise ValueError("Use 1..48 frames and an existing v2 format")
    body = b"".join(frame_body(frame, format_code) for frame in frames)
    # Match Web animation builder: native W/H, unused v2 ColorCount/table zero.
    header = struct.pack("<IHHBBH20x", len(body), *NATIVE, 0, format_code, len(frames))
    return header + body


def font(size: int) -> ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


def orientation_marker(draw: ImageDraw.ImageDraw, dark: int, white: int) -> None:
    draw.rectangle((5, 5, 43, 43), fill=white)
    draw.ellipse((9, 9, 25, 25), fill=dark)
    draw.line((31, 9, 31, 34, 40, 34), fill=dark, width=3)


def color_card(name: str, profile: dict, first: int, count: int) -> Image.Image:
    image = Image.new("P", PORTRAIT, profile["white"])
    image.putpalette([channel for rgb in profile["palette"] for channel in rgb] + [0] * (768 - 64 * 3))
    draw = ImageDraw.Draw(image)
    dark, white = profile["dark"], profile["white"]
    orientation_marker(draw, dark, white)
    draw.text((53, 8), f"{name}  0x{first:02X}-0x{first + count - 1:02X}", fill=dark, font=font(21))
    draw.text((12, 52), "64 CODES != 64 VALID COLORS", fill=dark, font=font(19))
    draw.text((12, 77), "X = outside current Web candidates", fill=dark, font=font(16))
    cols = 8 if count == 64 else 4
    rows = (count + cols - 1) // cols
    cell_w, cell_h = 456 // cols, 560 // rows
    for offset in range(count):
        index = first + offset
        x, y = 12 + (offset % cols) * cell_w, 105 + (offset // cols) * cell_h
        draw.rectangle((x + 2, y + 2, x + cell_w - 3, y + cell_h - 25), fill=index)
        excluded = index not in profile["candidates"]
        if excluded:
            # Preserve raw-code area around a visible X on the actual panel too.
            draw.line((x + 9, y + 8, x + cell_w - 10, y + cell_h - 32), fill=white, width=5)
            draw.line((x + cell_w - 10, y + 8, x + 9, y + cell_h - 32), fill=dark, width=3)
        draw.text((x + 3, y + cell_h - 23), f"{index:02X}{' X' if excluded else ''}", fill=dark, font=font(17))
    draw.text((12, 677), "RGB PREVIEW ESTIMATE / NOT PANEL MEASUREMENT", fill=dark, font=font(13))
    draw.text((12, 698), "TOP-LEFT DOT / FLEX DOWN", fill=dark, font=font(15))
    return image


def mono_frames(count: int) -> list[Image.Image]:
    result = []
    for number in range(count):
        image = Image.new("L", PORTRAIT, 255)
        draw = ImageDraw.Draw(image)
        orientation_marker(draw, 0, 255)
        draw.text((53, 12), f"MONO {number + 1:02}/{count:02}  1=BLACK", fill=0, font=font(23))
        draw.text((12, 65), "Moving block + inverted checker", fill=0, font=font(22))
        draw.rectangle((12, 112, 467, 330), outline=0, width=2)
        x = 20 + round(number * 348 / (count - 1))
        draw.rectangle((x, 145, x + 90, 295), fill=0)
        for row in range(8):
            for col in range(10):
                if (row + col + number) % 2 == 0:
                    left, top = 20 + col * 44, 365 + row * 36
                    draw.rectangle((left, top, left + 43, top + 35), fill=0)
        draw.text((12, 678), "Transitions: WW / WB / BW / BB", fill=0, font=font(21))
        draw.text((12, 705), "TOP-LEFT DOT / FLEX DOWN", fill=0, font=font(13))
        result.append(image)
    return result


def write_asset(path: Path, data: bytes) -> dict:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)
    return {"path": path.name, "bytes": len(data), "sha256": sha256(data)}


def write_png(path: Path, image: Image.Image) -> dict:
    import io
    stream = io.BytesIO()
    image.convert("RGB").save(stream, format="PNG")
    return write_asset(path, stream.getvalue())


def generate(output: Path, codes_per_page: int = 32, frames: int = 12) -> dict:
    profiles, source = load_profiles()
    output.mkdir(parents=True, exist_ok=True)
    assets = []
    for name, profile in profiles.items():
        for first in range(0, 64, codes_per_page):
            image = color_card(name, profile, first, codes_per_page)
            stem = f"{name.lower()}-codes-{first:02x}-{first + codes_per_page - 1:02x}"
            record = write_asset(output / (stem + ".film"), film_bytes([image], FORMATS[name]))
            record.update({"kind": "physical-index-card", "format": FORMATS[name], "formatName": name,
                           "frameCount": 1, "nativeSize": list(NATIVE), "viewSize": list(PORTRAIT),
                           "codeRange": [first, first + codes_per_page - 1],
                           "preview": write_png(output / (stem + ".png"), image)})
            assets.append(record)
    mono = mono_frames(frames)
    record = write_asset(output / "monofast-baseline.film", film_bytes(mono, 1))
    record.update({"kind": "transition-baseline", "format": 1, "formatName": "MonoFast",
                   "frameCount": frames, "nativeSize": list(NATIVE), "viewSize": list(PORTRAIT),
                   "frameBodySha256": [sha256(frame_body(image, 1)) for image in mono],
                   "previews": [write_png(output / f"monofast-{i:02}.png", image) for i, image in enumerate(mono)]})
    assets.append(record)
    manifest = {"schemaVersion": 1, "panelIdentity": PANEL_IDENTITY,
                "orientation": {"portraitToNative": "(px,py) -> (719-py,px)",
                                "headerWidth": 720, "headerHeight": 480,
                                "monoBitOrder": "MSB-first; 1=black, 0=white"},
                "paletteSource": source,
                "profiles": {name: {"candidateIndexes": p["candidates"], "encodedIndexes": list(range(64)),
                                    "previewRGB": p["palette"]} for name, p in profiles.items()},
                "measurementStatus": "Generated fixtures only. RGB preview estimates are not measurements of this physical panel.",
                "baselineNote": "Cold-start first frame and warmed-up differential frames are separate baselines; film carries no timing/FPS.",
                "assets": assets}
    write_asset(output / "manifest.json", (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".output/panel-lab", help="Default: repository .output/panel-lab (gitignored)")
    parser.add_argument("--codes-per-page", type=int, choices=(16, 32, 64), default=32)
    parser.add_argument("--frames", type=int, default=12, help="MonoFast frame count, 2..48 (default 12)")
    args = parser.parse_args()
    if not 2 <= args.frames <= 48:
        parser.error("--frames must be 2..48")
    try:
        manifest = generate(args.output, args.codes_per_page, args.frames)
    except (OSError, ValueError, SyntaxError) as error:
        parser.exit(1, f"panel-lab: {error}\n")
    print(f"Generated {len(manifest['assets'])} films and PNG previews in {args.output.resolve()}")
    print("RGB previews are estimates, not measurements of this physical panel. See manifest.json.")


if __name__ == "__main__":
    main()
