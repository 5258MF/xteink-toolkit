#!/usr/bin/env python3
"""ttf2bin: convert a TrueType/OpenType font into the XTEINK X3 ``.bin`` format.

Format summary (reverse engineered, see the project spec for the evidence):

    1 bit per pixel, no header, no magic.
    65536 fixed slots, indexed directly by Unicode codepoint (BMP).
    65536 x glyph_size bytes total, always.

    stride     = ceil(width / 8)          bytes per pixel row
    glyph_size = height * stride          bytes per glyph
    bits       = MSB first, left to right, top to bottom

The filename carries the layout width, and the reader uses it verbatim:

    <anything>.<W>x<H>.bin

``W`` is the advance the reader steps by, ``H`` is the line height. For a
528 px wide screen the reader fits ``floor(528 / W) - 1`` characters per line.
Examples: W=40 → 12 chars, W=43 or 44 → 11 chars.

Note that the stored row is byte aligned (``ceil(W/8)*8`` bits) while the layout
uses ``W``. W=43 and W=44 therefore store the same 48-bit rows, which is why
both give 11 characters per line.

Typical use:

    python ttf2bin.py MyFont.ttf -w 44 -h 52 --em 44
    python ttf2bin.py MyFont.ttf -w 43 -h 60 --em 46 --boost 1.15 -o out/MyFont.43x60.bin
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    from fontTools.ttLib import TTFont
except ImportError as exc:  # pragma: no cover
    sys.exit(f"missing dependency: {exc.name}. install with: pip install pillow numpy fonttools")


# Glyphs used to work out where the ink sits inside the cell. Any sample of
# common CJK characters works; these cover box shapes, diagonal strokes and
# characters with a full-width face.
PROBE = "国永东南西北中正口田目日月山水火木金土这回飞的一是了我不人在他有"


def load_codepoints(ttf_path: Path) -> list[int]:
    """Every codepoint the font maps, skipping control and format characters."""
    font = TTFont(str(ttf_path), fontNumber=0, lazy=True)
    codepoints: set[int] = set()
    for table in font["cmap"].tables:
        if table.isUnicode():
            codepoints.update(table.cmap)
    font.close()
    return sorted(cp for cp in codepoints
                  if cp >= 0x20 and not 0x7F <= cp <= 0x9F and cp <= 0xFFFF)


def placement(font: ImageFont.FreeTypeFont, width: int, height: int, em: int) -> tuple[int, int]:
    """Find the draw offset that centres the font's ink inside the cell.

    Font metrics alone are not reliable: different typefaces sit differently in
    the ascent/descent box. Measuring the actual ink and centring that gives a
    stable result across fonts.
    """
    ascent, descent = font.getmetrics()
    dx = max(0, (width - em) // 2)
    dy = (height - (ascent + descent)) // 2

    margin = 40
    x0 = x1 = y0 = y1 = None
    for ch in PROBE:
        img = Image.new("L", (width + margin * 2, height + margin * 2), 255)
        ImageDraw.Draw(img).text((margin + dx, margin + dy), ch, font=font, fill=0)
        ink = np.asarray(img) < 200
        if not ink.any():
            continue
        yy, xx = np.nonzero(ink)
        ax0, ax1 = int(xx.min()) - margin, int(xx.max()) - margin
        ay0, ay1 = int(yy.min()) - margin, int(yy.max()) - margin
        x0 = ax0 if x0 is None else min(x0, ax0)
        x1 = ax1 if x1 is None else max(x1, ax1)
        y0 = ay0 if y0 is None else min(y0, ay0)
        y1 = ay1 if y1 is None else max(y1, ay1)

    if x0 is not None:
        dx -= int(round((x0 + x1 - (width - 1)) / 2))
        dy -= int(round((y0 + y1 - (height - 1)) / 2))
    return dx, dy


def pack_glyph(ink: np.ndarray, width: int) -> bytes:
    """Pack a boolean height x width map into rows of ceil(width/8) bytes, MSB first."""
    height = ink.shape[0]
    stride = math.ceil(width / 8)
    out = bytearray(height * stride)
    for y in range(height):
        base = y * stride
        for x in np.flatnonzero(ink[y]):
            col = int(x)
            # parentheses matter: `base + col >> 3` would parse as `(base + col) >> 3`
            out[base + (col >> 3)] |= 0x80 >> (col & 7)
    return bytes(out)


def build(ttf: Path, width: int, height: int, em: int, threshold: float,
          boost: float, bold: int, out: Path, screen_width: int = 528) -> None:
    font = ImageFont.truetype(str(ttf), em)
    dx, dy = placement(font, width, height, em)

    stride = math.ceil(width / 8)
    glyph_size = height * stride
    total = 65536 * glyph_size

    print(f"  font      {ttf.name}")
    print(f"  cell      {width}x{height}   em {em}")
    print(f"  stride    {stride} B ({stride * 8} bit)   glyph {glyph_size} B")
    print(f"  offset    dx {dx}  dy {dy}")
    print(f"  threshold {threshold}   boost {boost}   bold {bold}")
    chars = max(1, screen_width // width - 1)
    print(f"  layout    W={width} -> {chars} chars/line on a {screen_width} px screen")
    print(f"  output    {total:,} B ({total / 1024 / 1024:.2f} MiB)")

    codepoints = load_codepoints(ttf)
    buffer = bytearray(total)
    drawn = 0
    empty = 0
    overhang = 0

    for index, cp in enumerate(codepoints):
        img = Image.new("L", (width, height), 255)
        try:
            ImageDraw.Draw(img).text((dx, dy), chr(cp), font=font, fill=0,
                                     stroke_width=bold, stroke_fill=0)
        except Exception:
            empty += 1
            continue
        coverage = (255.0 - np.asarray(img, dtype=np.float32)) / 255.0
        if boost != 1.0:
            coverage = np.clip(coverage * boost, 0.0, 1.0)
        ink = coverage >= threshold
        if not ink.any():
            empty += 1
            continue
        # a glyph wider than its cell loses its right edge; count how often
        cols = np.nonzero(ink.any(axis=0))[0]
        if len(cols) and cols.max() >= width - 1:
            overhang += 1
        offset = cp * glyph_size
        buffer[offset:offset + glyph_size] = pack_glyph(ink, width)
        drawn += 1
        if index and index % 4000 == 0:
            print(f"    {index}/{len(codepoints)} ...", flush=True)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(bytes(buffer))
    print(f"  done      {out}")
    print(f"  glyphs    {drawn} drawn, {empty} empty, {overhang} touch the right edge")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert a TTF/OTF font into an XTEINK X3 .bin font.",
        epilog="The output filename must keep the .<W>x<H>.bin shape; the reader "
               "parses the advance and line height out of it.",
    )
    parser.add_argument("ttf", type=Path, help="input font")
    parser.add_argument("-w", "--width", type=int, required=True,
                        help="layout advance in px, becomes W in the filename")
    parser.add_argument("-H", "--height", type=int, required=True,
                        help="line height in px, becomes H in the filename")
    parser.add_argument("--em", type=int, default=None,
                        help="render size in px (default: same as width)")
    parser.add_argument("--threshold", type=float, default=0.5,
                        help="ink coverage cutoff, 0..1 (default 0.5; 0.392 with "
                             "--boost 1.15 reproduces the shipped 43x60 sample)")
    parser.add_argument("--boost", type=float, default=1.0,
                        help="multiply coverage before thresholding (stem darkening)")
    parser.add_argument("--bold", type=int, default=0,
                        help="synthetic bold stroke width in px")
    parser.add_argument("--screen-width", type=int, default=528,
                        help="panel width used only to report chars/line (default 528, the X3)")
    parser.add_argument("-o", "--out", type=Path, default=None,
                        help="output path (default: <font stem>.<W>x<H>.bin)")
    args = parser.parse_args(argv)

    if not args.ttf.is_file():
        parser.error(f"no such font: {args.ttf}")
    if not 8 <= args.width <= 255:
        parser.error("width must be 8..255")
    if not 8 <= args.height <= 255:
        parser.error("height must be 8..255")
    if args.em is None:
        args.em = args.width
    if args.em < 4 or args.em > 255:
        parser.error("em must be 4..255")

    out = args.out or args.ttf.with_name(f"{args.ttf.stem}.{args.width}x{args.height}.bin")
    print("ttf2bin")
    build(args.ttf, args.width, args.height, args.em, args.threshold,
          args.boost, args.bold, out, args.screen_width)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
