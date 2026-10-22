#!/usr/bin/env python3
"""ttf2xtf: convert a TrueType/OpenType font into the XTEINK X3 ``.xtf`` format.

Format summary (reverse engineered, see the project spec for the evidence):

    64-byte header, magic "XTF0", little endian.
    0x40 .. toc_end        interval table, 16 bytes per row:
                           u32 first codepoint, u32 count, u32 cumulative index,
                           u32 unused
    toc_end .. +tail_len   95-byte tail table (must be copied verbatim)
    .. data_start          zero padding
    data_start ..          glyph records, `per` bytes each:
                           1 byte advance, then the bitmap, then 1 zero byte

    stride     = ceil((pitch_em + 1) * 2 / 8)     # 2 bits per pixel
    cell_width = stride * 4                        # one byte holds 4 pixels
    per        = 1 + stride * grid_h + 1
    data_start = (toc_end + 0x1FF) & ~0x1FF        # 512-aligned

Two different EMs exist and they do different jobs:

    pitch_em  -> header 0x0a = pitch_em + 1, and 0x0c also follows it normally
                 This is what decides how many characters fit per line.
                 The reader fits roughly (57 - 0x0a) characters on a 528 px
                 screen: 0x0a=45 -> 12 chars, 0x0a=47 -> 10 chars.
    render_em -> header 0x0c, the size the glyphs are actually drawn at.

You can make pitch_em smaller than render_em to get big type at a narrow
advance, but then the face is wider than the advance and something has to give:

    face_width = pitch_em - 1   -> 1 px gap between characters, face is cropped
    face_width = pitch_em       -> no gap, neighbouring glyphs touch

Cropping is used here, never resampling: squeezing 45 px into 43 px thins every
stroke by 4.4% and the loss is obvious on side radicals. Cropping keeps stroke
weight and only trims the right edge.

Crop origin is column 0, not the probe set's left edge. A 28-glyph probe can
report its leftmost ink at column 3 while a real character such as 钧 starts at
column 0 -- cropping from 3 slices the first stroke off the radical.

Typical use:

    # 12 chars per line, 60 px rows, 46 px type cropped to 43 px
    python ttf2xtf.py MyFont.ttf --em 46 --pitch-em 44 --grid-h 60 --face-width 43

    # plain 44 pt, 12 chars, 52 px rows
    python ttf2xtf.py MyFont.ttf --em 44 --pitch-em 44 --grid-h 52
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    from fontTools.ttLib import TTFont
except ImportError as exc:  # pragma: no cover
    sys.exit(f"missing dependency: {exc.name}. install with: pip install pillow numpy fonttools")


MAGIC = b"XTF0"
HEADER_SIZE = 0x40
TAIL_TABLE_LEN = 95

# These fields have no known formula. They are inherited from the skeleton so
# the reader sees a header shape it has already accepted before.
INHERIT_FIELDS = (0x04, 0x08, 0x0D, 0x0E, 0x30)  # 0x30 is 8 bytes

PROBE = "国永东南西北中正口田目日月山水火木金土这回飞"

DEFAULT_SKELETON = Path(__file__).resolve().parent / "skeletons" / "skel_g52.bin"


class Skeleton:
    """Header bytes, interval table and tail table lifted from a shipped font."""

    def __init__(self, path: Path) -> None:
        raw = path.read_bytes()
        if raw[:4] != MAGIC:
            raise ValueError(f"{path} is not an XTF file")
        self.raw = raw
        self.header = bytearray(raw[:HEADER_SIZE])
        self.toc_end = struct.unpack_from("<I", raw, 0x38)[0]
        self.tail_len = struct.unpack_from("<I", raw, 0x3C)[0]
        if self.tail_len != TAIL_TABLE_LEN:
            raise ValueError(f"{path}: unexpected tail length {self.tail_len}")
        self.table = raw[HEADER_SIZE:self.toc_end]
        self.tail = raw[self.toc_end:self.toc_end + self.tail_len]
        self.codepoints = self._parse_table()
        self.path = path

    def _parse_table(self) -> list[int]:
        count = struct.unpack_from("<I", self.header, 0x14)[0]
        codepoints: list[int] = []
        for row in range(count):
            off = row * 16
            first, length = struct.unpack_from("<II", self.table, off)
            codepoints.extend(range(first, first + length))
        return codepoints


def load_codepoints(ttf_path: Path) -> set[int]:
    font = TTFont(str(ttf_path), fontNumber=0, lazy=True)
    codepoints: set[int] = set()
    for table in font["cmap"].tables:
        if table.isUnicode():
            codepoints.update(table.cmap)
    font.close()
    return codepoints


def quantise(coverage: np.ndarray, cuts: tuple[int, int, int],
             boost: float) -> np.ndarray:
    """Map 8-bit coverage to the 2-bit levels the panel understands.

    The shipped files use 64/128/192. Raising the cuts removes faint
    antialias fringes that would otherwise show up as isolated grey specks,
    at the cost of slightly thinner strokes.
    """
    if boost != 1.0:
        coverage = np.clip(coverage * boost, 0.0, 1.0)
    levels = np.zeros(coverage.shape, np.uint8)
    levels[coverage >= cuts[0] / 255.0] = 1
    levels[coverage >= cuts[1] / 255.0] = 2
    levels[coverage >= cuts[2] / 255.0] = 3
    return levels


def pack_cell(cell: np.ndarray) -> bytes:
    """Pack a grid_h x cell_width 2-bit map, four pixels per byte, MSB first."""
    grid_h, width = cell.shape
    stride = width // 4
    out = bytearray(grid_h * stride)
    for y in range(grid_h):
        row = cell[y]
        base = y * stride
        for b in range(stride):
            x = b * 4
            out[base + b] = ((int(row[x]) << 6) | (int(row[x + 1]) << 4)
                             | (int(row[x + 2]) << 2) | int(row[x + 3]))
    return bytes(out)


def build(ttf: Path, em: int, pitch_em: int, grid_h: int, face_width: int,
          skeleton_path: Path, cuts: tuple[int, int, int], boost: float,
          out: Path) -> None:
    skeleton = Skeleton(skeleton_path)

    stride = -(-(pitch_em + 1) * 2 // 8)
    cell_width = stride * 4
    per = 1 + stride * grid_h + 1
    data_start = (skeleton.toc_end + 0x1FF) & ~0x1FF

    if face_width > cell_width:
        raise SystemExit(f"face-width {face_width} exceeds cell width {cell_width}")
    if face_width > pitch_em:
        print(f"  warning: face-width {face_width} > pitch {pitch_em}; "
              f"characters will overlap by {face_width - pitch_em} px")

    codepoints = skeleton.codepoints
    have = load_codepoints(ttf)
    missing = [cp for cp in codepoints if cp not in have]

    font = ImageFont.truetype(str(ttf), em)
    ascent, descent = font.getmetrics()
    dy0 = (grid_h - (ascent + descent)) // 2
    dx0 = max(0, (cell_width - em) // 2)

    # vertical extent of the face, measured on the probe set
    margin = 40
    gy0 = gy1 = None
    for ch in PROBE:
        img = Image.new("L", (cell_width + margin * 2, grid_h + margin * 2), 255)
        ImageDraw.Draw(img).text((margin + dx0, margin + dy0), ch, font=font, fill=0)
        ink = np.asarray(img) < 200
        if not ink.any():
            continue
        yy, _ = np.nonzero(ink)
        a, b = int(yy.min()) - margin, int(yy.max()) - margin
        gy0 = a if gy0 is None else min(gy0, a)
        gy1 = b if gy1 is None else max(gy1, b)
    if gy0 is None:
        raise SystemExit("probe set rendered nothing; check the font")
    face_h = gy1 - gy0 + 1
    y_off = (grid_h - face_h) // 2

    chars = max(1, 57 - (pitch_em + 1))
    print(f"  font       {ttf.name}")
    print(f"  skeleton   {skeleton_path.name}  toc_end 0x{skeleton.toc_end:x}  "
          f"tail {skeleton.tail_len} B")
    print(f"  pitch      {pitch_em} px  (0x0a={pitch_em + 1})  -> about {chars} chars/line")
    print(f"  render     em {em} px  (0x0c={em})   face {face_width} px wide, cropped")
    print(f"  cell       {cell_width}x{grid_h}  stride {stride} B  per {per} B")
    print(f"  layout     y {y_off}..{y_off + face_h - 1}   crop x 0..{face_width - 1}"
          f"   right margin {cell_width - face_width} px")
    print(f"  gap        {pitch_em - face_width} px between characters")
    print(f"  data at    0x{data_start:x}   glyphs {len(codepoints)}")
    if missing:
        print(f"  note       {len(missing)} codepoints absent from the font "
              f"(first: U+{missing[0]:04X}) - left blank")

    # Per-record advance byte. The shipped files write a constant here, and the
    # reader does not use it for layout, so inherit it rather than invent one.
    advance = struct.unpack_from("<H", skeleton.header, 0x10)[0]

    records: list[bytes] = []
    histogram = np.zeros(4, np.int64)
    blank_cell = np.zeros((grid_h, cell_width), np.uint8)

    for index, cp in enumerate(codepoints):
        cell = blank_cell
        if cp in have:
            img = Image.new("L", (cell_width + margin * 2, grid_h + margin * 2), 255)
            ImageDraw.Draw(img).text((margin + dx0, margin + dy0), chr(cp),
                                     font=font, fill=0)
            coverage = (255.0 - np.asarray(img, dtype=np.float32)) / 255.0
            # crop from column 0: a probe-set left edge is not a safe origin
            sub = coverage[margin + gy0:margin + gy1 + 1, margin:margin + face_width]
            if sub.max() > 0.01:
                cell = np.zeros((grid_h, cell_width), np.uint8)
                cell[y_off:y_off + face_h, 0:face_width] = quantise(sub, cuts, boost)
        histogram += np.bincount(cell.ravel(), minlength=4)
        records.append(struct.pack("<B", advance & 0xFF) + pack_cell(cell) + b"\x00")
        if index and index % 4000 == 0:
            print(f"    {index}/{len(codepoints)} ...", flush=True)

    # Only the fields that describe THIS build are rewritten. Everything else
    # (0x04, 0x08, 0x0d, 0x0e, 0x10, 0x12, 0x1c, 0x30..0x37) stays as the
    # skeleton had it -- those either have no known formula or are already
    # known-good for this reader.
    header = bytearray(skeleton.header)
    header[0x0A] = pitch_em + 1        # layout em, decides chars per line
    header[0x0B] = grid_h
    header[0x0C] = pitch_em            # NB: the layout em, not the render em
    struct.pack_into("<I", header, 0x14, len(skeleton.table) // 16)
    struct.pack_into("<I", header, 0x18, len(codepoints))
    struct.pack_into("<I", header, 0x24, data_start)
    struct.pack_into("<H", header, 0x28, per)
    struct.pack_into("<I", header, 0x2C, len(records) * per)
    struct.pack_into("<I", header, 0x38, skeleton.toc_end)
    struct.pack_into("<I", header, 0x3C, skeleton.tail_len)

    body = b"".join(records)
    padding = b"\x00" * (data_start - skeleton.toc_end - skeleton.tail_len)
    blob = bytes(header) + skeleton.table + skeleton.tail + padding + body

    expected = data_start + len(codepoints) * per
    if len(blob) != expected:
        raise SystemExit(f"size mismatch: wrote {len(blob):,}, expected {expected:,}")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(blob)
    total = histogram.sum()
    print(f"  done       {out}")
    print(f"  size       {len(blob):,} B  (self-check OK)")
    print(f"  levels     white {histogram[0] / total * 100:.1f}%  "
          f"1 {histogram[1] / total * 100:.1f}%  "
          f"2 {histogram[2] / total * 100:.1f}%  "
          f"3 {histogram[3] / total * 100:.1f}%")


def parse_cuts(text: str) -> tuple[int, int, int]:
    parts = [int(p) for p in text.split(",")]
    if len(parts) != 3 or not all(0 <= p <= 255 for p in parts) or parts != sorted(parts):
        raise argparse.ArgumentTypeError("expected three ascending values 0..255, e.g. 64,128,192")
    return parts[0], parts[1], parts[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert a TTF/OTF font into an XTEINK X3 .xtf font.",
        epilog="Watch the reported chars/line: it is derived from --pitch-em and "
               "the reader's own packing rules.",
    )
    parser.add_argument("ttf", type=Path, help="input font")
    parser.add_argument("--em", type=int, default=44,
                        help="render size in px, written to 0x0c (default 44)")
    parser.add_argument("--pitch-em", type=int, default=None,
                        help="advance in px, written to 0x0a as pitch+1 "
                             "(default: same as --em)")
    parser.add_argument("--grid-h", type=int, default=None,
                        help="row height in px (default: the skeleton's own value)")
    parser.add_argument("--face-width", type=int, default=None,
                        help="crop the face to this many px (default: pitch-1, "
                             "which leaves a 1 px gap between characters)")
    parser.add_argument("--skeleton", type=Path, default=DEFAULT_SKELETON,
                        help=f"header/table/tail donor (default: {DEFAULT_SKELETON.name})")
    parser.add_argument("--cuts", type=parse_cuts, default=(64, 128, 192),
                        help="2-bit quantisation cuts (default 64,128,192; "
                             "96,160,224 removes faint edge specks)")
    parser.add_argument("--boost", type=float, default=1.0,
                        help="multiply coverage before quantising (stem darkening)")
    parser.add_argument("-o", "--out", type=Path, default=None,
                        help="output path (default: <font stem>.xtf)")
    args = parser.parse_args(argv)

    if not args.ttf.is_file():
        parser.error(f"no such font: {args.ttf}")
    if not args.skeleton.is_file():
        parser.error(f"no such skeleton: {args.skeleton}")

    pitch_em = args.pitch_em if args.pitch_em is not None else args.em
    skeleton = Skeleton(args.skeleton)
    grid_h = args.grid_h if args.grid_h is not None else skeleton.header[0x0B]
    face_width = args.face_width if args.face_width is not None else pitch_em - 1

    if not 8 <= args.em <= 200:
        parser.error("em must be 8..200")
    if not 8 <= pitch_em <= 200:
        parser.error("pitch-em must be 8..200")
    if not 8 <= grid_h <= 200:
        parser.error("grid-h must be 8..200")
    if face_width < 4 or face_width > 200:
        parser.error("face-width must be 4..200")

    out = args.out or args.ttf.with_name(f"{args.ttf.stem}.xtf")
    print("ttf2xtf")
    build(args.ttf, args.em, pitch_em, grid_h, face_width, args.skeleton,
          args.cuts, args.boost, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
