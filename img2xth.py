#!/usr/bin/env python3
"""img2xth — convert any image into the XTEINK X3 ``.xth`` wallpaper format.

Format summary (reverse engineered, see the project's XTH_WALLPAPER_FORMAT.md):

    22-byte header, little endian:
        char     magic[4]      "XTH\\0"
        uint16   width         528
        uint16   height        792
        uint16   reserved      0
        uint32   payload_size  104544       (= 528*792/8 * 2)
        uint32   timestamp     unix seconds
        uint32   reserved      0

    Then two 1-bit planes, 52,272 bytes each, indexed by level bit:
        level = (planeB << 1) | planeA      0 = paper white, 3 = ink black

    Each plane is stored **column major**: 792 consecutive bits form one image
    column, MSB first, and the stored image is horizontally mirrored. Decoding:

        bits.reshape(w, h).T[:, ::-1]

    That mirror is not a bug in the data, it is the panel's scan order. Writing a
    plane without it produces a mirrored wallpaper.

Tone handling is easy to get backwards. There are two complementary scales:

    q     = luminance level, 0 = black   .. 3 = white
    ink   = (levels-1) - q,  0 = paper   .. 3 = ink

The file stores `ink`, so a dark source pixel ends up as level 3.

Typical use:

    python img2xth.py photo.jpg
    python img2xth.py art.png -o wall.xth --dither fs
    python img2xth.py chart.png --dither none --fit contain

Floyd-Steinberg is the recommended dither: on the actual panel it reproduces the
full 16 steps of a test ramp, while ordered Bayer reads as almost undithered and
none collapses to four flat bands. Use `none` only for line art and diagrams.
"""
from __future__ import annotations

import argparse
import struct
import sys
import time
from pathlib import Path

try:
    import numpy as np
    from PIL import Image
except ImportError as exc:  # pragma: no cover
    sys.exit(f"missing dependency: {exc.name}. install with: pip install pillow numpy")


DEFAULT_W, DEFAULT_H = 528, 792   # X3 panel; override with --width/--height
HEADER_SIZE = 22
LEVELS = 4


def load_gray(path: Path, fit: str, w: int, h: int) -> np.ndarray:
    """Load an image as 8-bit grey, alpha composited on white, sized to w x h."""
    image = Image.open(path)
    if image.mode in ("RGBA", "LA", "P") or (image.mode == "P" and "transparency" in image.info):
        image = image.convert("RGBA")
        background = Image.new("RGBA", image.size, (255, 255, 255, 255))
        image = Image.alpha_composite(background, image)
    image = image.convert("L")

    if image.size == (w, h):
        return np.asarray(image, dtype=np.uint8)

    source_w, source_h = image.size
    if fit == "stretch":
        image = image.resize((w, h), Image.LANCZOS)
    elif fit == "contain":
        scale = min(w / source_w, h / source_h)
        size = (max(1, int(source_w * scale + 0.5)), max(1, int(source_h * scale + 0.5)))
        resized = image.resize(size, Image.LANCZOS)
        canvas = Image.new("L", (w, h), 255)
        canvas.paste(resized, ((w - size[0]) // 2, (h - size[1]) // 2))
        image = canvas
    else:  # cover
        scale = max(w / source_w, h / source_h)
        size = (max(1, int(source_w * scale + 0.5)), max(1, int(source_h * scale + 0.5)))
        image = image.resize(size, Image.LANCZOS)
        left = (image.width - w) // 2
        top = (image.height - h) // 2
        image = image.crop((left, top, left + w, top + h))
    return np.asarray(image, dtype=np.uint8)


def quantise(gray: np.ndarray) -> np.ndarray:
    """Plain 4-level rounding, no dither. Fine for line art, banded on photos."""
    return np.clip(np.round(gray.astype(np.float32) / 255.0 * (LEVELS - 1)),
                   0, LEVELS - 1).astype(np.uint8)


def dither_floyd_steinberg(gray: np.ndarray) -> np.ndarray:
    """Serpentine Floyd-Steinberg error diffusion. The one that works on this panel."""
    acc = gray.astype(np.float32) / 255.0 * (LEVELS - 1)
    height, width = acc.shape
    out = np.zeros((height, width), dtype=np.uint8)
    for y in range(height):
        forward = (y % 2 == 0)
        xs = range(width) if forward else range(width - 1, -1, -1)
        step = 1 if forward else -1
        for x in xs:
            old = acc[y, x]
            new = float(np.clip(np.round(old), 0, LEVELS - 1))
            out[y, x] = int(new)
            error = old - new
            if 0 <= x + step < width:
                acc[y, x + step] += error * 7 / 16
            if y + 1 < height:
                if 0 <= x - step < width:
                    acc[y + 1, x - step] += error * 3 / 16
                acc[y + 1, x] += error * 5 / 16
                if 0 <= x + step < width:
                    acc[y + 1, x + step] += error * 1 / 16
    return out


def dither_bayer(gray: np.ndarray, order: int = 3) -> np.ndarray:
    """Ordered 8x8 Bayer. Reads as nearly undithered on this panel."""
    matrix = np.array([[0]], dtype=np.float32)
    for _ in range(order):
        matrix = np.block([[4 * matrix, 4 * matrix + 2],
                           [4 * matrix + 3, 4 * matrix + 1]])
    threshold = (matrix + 0.5) / (4 ** order)
    height, width = gray.shape
    tile = np.tile(threshold, (height // threshold.shape[0] + 1,
                               width // threshold.shape[1] + 1))[:height, :width]
    norm = gray.astype(np.float32) / 255.0 * (LEVELS - 1)
    base = np.floor(norm)
    quantised = np.where(norm - base > tile, base + 1, base)
    return np.clip(quantised, 0, LEVELS - 1).astype(np.uint8)


def pack_plane(bitmap: np.ndarray) -> bytes:
    """Column-major, horizontally mirrored, MSB first — the panel's scan order."""
    return np.packbits(bitmap[:, ::-1].T.ravel().astype(np.uint8)).tobytes()


def build(src: Path, out: Path, dither: str, fit: str, timestamp: int | None,
          w: int, h: int) -> None:
    plane_size = w * h // 8
    if w * h % 8:
        raise SystemExit(f"{w}x{h} is not a whole number of bytes")
    gray = load_gray(src, fit, w, h)
    print(f"  source    {src.name}  ->  {w}x{h} ({fit})")

    if dither == "fs":
        q = dither_floyd_steinberg(gray)
    elif dither == "bayer":
        q = dither_bayer(gray)
    else:
        q = quantise(gray)

    ink = (LEVELS - 1) - q          # q is luminance, the file stores ink
    plane_a = ink & 1
    plane_b = (ink >> 1) & 1

    payload_a = pack_plane(plane_a)
    payload_b = pack_plane(plane_b)
    if len(payload_a) != plane_size or len(payload_b) != plane_size:
        raise SystemExit(f"plane size mismatch: {len(payload_a)} / {len(payload_b)} "
                         f"!= {plane_size}")

    ts = int(time.time()) if timestamp is None else timestamp
    header = struct.pack("<4sHHHIII", b"XTH\x00", w, h, 0, plane_size * 2, ts, 0)
    if len(header) != HEADER_SIZE:
        raise SystemExit(f"header size {len(header)} != {HEADER_SIZE}")

    blob = header + payload_a + payload_b
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(blob)

    values, counts = np.unique(ink, return_counts=True)
    spread = "  ".join(f"{v}:{c / ink.size * 100:.1f}%" for v, c in zip(values, counts))
    print(f"  dither    {dither}")
    print(f"  ink level {spread}")
    print(f"  timestamp {ts}")
    print(f"  done      {out}  {len(blob):,} B")
    if len(blob) != HEADER_SIZE + plane_size * 2:
        raise SystemExit("size self-check failed")
    if (w, h) != (DEFAULT_W, DEFAULT_H):
        print(f"  note      {w}x{h} is not the X3 panel size ({DEFAULT_W}x{DEFAULT_H}); "
              f"the header carries it, but this has not been tested on hardware")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert an image into an XTEINK X3 .xth wallpaper.",
        epilog="Floyd-Steinberg is recommended; ordered Bayer barely helps on "
               "this panel and no dithering collapses photos to four bands.",
    )
    parser.add_argument("image", type=Path, help="input image (any format Pillow reads)")
    parser.add_argument("-o", "--out", type=Path, default=None,
                        help="output path (default: <image stem>.xth)")
    parser.add_argument("--dither", choices=("fs", "bayer", "none"), default="fs",
                        help="dithering method (default fs)")
    parser.add_argument("--fit", choices=("cover", "contain", "stretch"), default="cover",
                        help="how to fit a non-matching image (default cover: crop to fill)")
    parser.add_argument("--width", type=int, default=DEFAULT_W,
                        help=f"output width in px (default {DEFAULT_W}, the X3 panel)")
    parser.add_argument("--height", type=int, default=DEFAULT_H,
                        help=f"output height in px (default {DEFAULT_H}, the X3 panel)")
    parser.add_argument("--timestamp", type=int, default=None,
                        help="unix seconds for the header field (default: now)")
    args = parser.parse_args(argv)

    if not args.image.is_file():
        parser.error(f"no such image: {args.image}")
    if not 8 <= args.width <= 4096 or not 8 <= args.height <= 4096:
        parser.error("width and height must be 8..4096")

    out = args.out or args.image.with_suffix(".xth")
    print("img2xth")
    build(args.image, out, args.dither, args.fit, args.timestamp,
          args.width, args.height)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
