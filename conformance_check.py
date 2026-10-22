#!/usr/bin/env python3
"""Validate .xtf and .xth files against the rules in docs/.

The checks here are the conformance sections of the two specifications, nothing
more. A pass means the file is structurally well formed; it says nothing about
whether the glyphs look right.

    python conformance_check.py font.xtf wall.xth
    python conformance_check.py --all path/to/folder
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

try:
    import numpy as np
except ImportError:  # pragma: no cover
    sys.exit("missing dependency: numpy. install with: pip install numpy")


def check_xtf(path: Path) -> bool:
    raw = path.read_bytes()
    results: list[tuple[str, bool]] = []

    if len(raw) < 0x40 or raw[:4] != b"XTF0":
        print(f"{path.name}: not an XTF file")
        return False

    n_ranges = struct.unpack_from("<I", raw, 0x14)[0]
    n_glyphs = struct.unpack_from("<I", raw, 0x18)[0]
    per = struct.unpack_from("<H", raw, 0x28)[0]
    data_start = struct.unpack_from("<I", raw, 0x24)[0]
    data_size = struct.unpack_from("<I", raw, 0x2C)[0]
    toc_end = struct.unpack_from("<I", raw, 0x38)[0]
    tail_len = struct.unpack_from("<I", raw, 0x3C)[0]
    pitch = raw[0x0A] - 1
    grid_h = raw[0x0B]
    # stride derives from 0x0a, not from the pitch: ceil(45 * 2 / 8) = 12
    stride = -(-raw[0x0A] * 2 // 8)

    results.append(("magic XTF0", raw[:4] == b"XTF0"))
    results.append(("bits per pixel == 2", raw[0x07] == 2))
    results.append(("interval table ends at 0x38", 0x40 + 16 * n_ranges == toc_end))
    results.append(("data_start is 512-aligned",
                    data_start == (0x40 + 16 * n_ranges + tail_len + 0x1FF) & ~0x1FF))

    cum = 0
    total = 0
    cum_ok = x16_ok = True
    for i in range(n_ranges):
        _, count, c, c16 = struct.unpack_from("<IIII", raw, 0x40 + i * 16)
        cum_ok &= (c == cum)
        x16_ok &= (c16 == (count << 16))
        cum += count
        total += count

    results.append(("glyph count == sum of ranges", total == n_glyphs))
    results.append(("cum_index is a running sum", cum_ok))
    results.append(("count_x16 == count << 16", x16_ok))
    results.append((f"per == 2 + gridH*stride ({per} == {2 + grid_h * stride})",
                    per == 1 + grid_h * stride + 1))
    results.append(("data size == glyphs * per", data_size == n_glyphs * per))
    results.append(("file length == data_start + data_size",
                    len(raw) == data_start + data_size))

    tail = raw[toc_end:toc_end + tail_len]
    results.append(("tail entries in 8..34", bool(tail) and all(8 <= v <= 34 for v in tail)))
    results.append(("record terminators are zero",
                    all(raw[data_start + i * per + per - 1] == 0
                        for i in range(0, n_glyphs, max(1, n_glyphs // 64)))))

    # no ink at or beyond the layout pitch: it would composite onto the next cell
    overflow = 0
    for idx in range(0, n_glyphs, max(1, n_glyphs // 64)):
        blob = raw[data_start + idx * per + 1: data_start + idx * per + 1 + grid_h * stride]
        grid = np.frombuffer(blob, np.uint8).reshape(grid_h, stride)
        px = np.zeros((grid_h, stride * 4), np.uint8)
        for k in range(4):
            px[:, k::4] = (grid >> (6 - 2 * k)) & 3
        if px[:, pitch:].any():
            overflow += 1
    results.append(("no ink at or past the pitch", overflow == 0))

    print(f"\nXTF  {path.name}   {n_ranges} ranges, {n_glyphs} glyphs, "
          f"gridH {grid_h}, pitch {pitch}, stride {stride}")
    for name, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    return all(ok for _, ok in results)


def check_xth(path: Path) -> bool:
    raw = path.read_bytes()
    if len(raw) < 22 or raw[:4] != b"XTH\0":
        print(f"\nXTH  {path.name}: not an XTH file")
        return False

    width, height, reserved0 = struct.unpack_from("<HHH", raw, 4)
    size, _timestamp, reserved1 = struct.unpack_from("<III", raw, 0x0A)
    results = [
        ("magic XTH0", raw[:4] == b"XTH\0"),
        ("reserved fields zero", reserved0 == 0 and reserved1 == 0),
        ("width multiple of 8", width % 8 == 0),
        (f"payload == 2*W*H/8 ({size:,})", size == 2 * width * height // 8),
        ("file length == 22 + payload", len(raw) == 22 + size),
    ]
    print(f"\nXTH  {path.name}   {width}x{height}")
    for name, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    return all(ok for _, ok in results)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate .xtf and .xth files.")
    parser.add_argument("files", nargs="*", type=Path, help="files to check")
    parser.add_argument("--all", type=Path, metavar="DIR",
                        help="check every .xtf and .xth under DIR")
    args = parser.parse_args(argv)

    targets = list(args.files)
    if args.all:
        targets += sorted(args.all.rglob("*.xtf")) + sorted(args.all.rglob("*.xth"))
    if not targets:
        parser.error("give files, or --all DIR")

    ok = True
    for path in targets:
        if not path.is_file():
            print(f"{path}: not found")
            ok = False
            continue
        if path.suffix.lower() == ".xtf":
            ok &= check_xtf(path)
        elif path.suffix.lower() == ".xth":
            ok &= check_xth(path)
        else:
            print(f"{path.name}: unknown extension")
            ok = False

    print("\n" + ("ALL PASS" if ok else "FAILURES PRESENT"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
