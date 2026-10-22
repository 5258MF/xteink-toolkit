# XTF Font Container: Format Specification

Version 1.0 · applies to `.xtf` files consumed by XTEINK X3 firmware V6.4.x

---

## 1. Scope

This document specifies the binary layout of the `.xtf` font container: a 2-bit
greyscale, randomly addressable glyph store used by the XTEINK X3 e-reader.

It defines every field, its legal values, and the constraints that a conforming
file must satisfy. It does not specify how glyph outlines are rasterised; a
renderer's choice of antialiasing affects appearance, not conformance.

Fields whose purpose could not be determined are marked **opaque** and carry a
requirement to copy them from a known-good file. They are not optional.

---

## 2. Conventions

- All multi-byte integers are **little endian**.
- `u8`, `u16`, `u32`, `i16` denote unsigned 8/16/32-bit and signed 16-bit integers.
- Offsets are byte offsets from the start of the file.
- "Sample" refers to a `.xtf` produced by the vendor's own toolchain.
- The key words MUST, MUST NOT, SHOULD, and MAY are used as in RFC 2119.

---

## 3. File Layout

```
offset                    size          content
0x0000                    64            header
0x0040                    16 × N        interval table
0x0040 + 16N              L             tail table
...                       pad           zero fill up to data_start
data_start                G × P         glyph records
```

| Symbol | Definition |
|---|---|
| `N` | number of interval rows, header `0x14` |
| `G` | number of glyph records, header `0x18` |
| `L` | tail table length, header `0x3c` (95 in all samples) |
| `P` | bytes per glyph record, header `0x28` |
| `data_start` | `(0x40 + 16N + L + 0x1FF) & ~0x1FF`, header `0x24` |

The file length MUST equal `data_start + G × P`.

`data_start` is 512-byte aligned. All samples land on `0x4600` because they share
`N = 1093` and `L = 95`.

---

## 4. Header

### 4.1 Fields

Offsets are absolute; sizes in bytes. Values shown are from three samples
identified by nominal type size.

| Offset | Type | 40 pt | 43 pt | 46 pt | Meaning | Recomputable |
|---|---|---|---|---|---|---|
| `0x00` | char[4] | `XTF0` | `XTF0` | `XTF0` | Magic | constant |
| `0x04` | u8 | 1 | 1 | 1 | Major version | constant |
| `0x05` | u8 | 5 | 5 | 5 | Minor version | constant |
| `0x06` | u8 | 0x40 | 0x40 | 0x40 | **opaque** | copy |
| `0x07` | u8 | 2 | 2 | 2 | Bits per pixel | constant 2 |
| `0x08` | u16 | 3 | 3 | 3 | **opaque** | copy |
| `0x0a` | u8 | 41 | 44 | 47 | Layout em + 1 | `em_pitch + 1` |
| `0x0b` | u8 | 52 | 57 | 59 | Grid height `gridH` | see §4.2 |
| `0x0c` | u8 | 40 | 43 | 46 | Render em | see §4.2 |
| `0x0d` | u8 | 41 | 58 | 46 | **opaque** | copy |
| `0x0e` | u16 | 19 | 35 | 21 | **opaque** | copy |
| `0x10` | u16 | 40 | 43 | 45 | Default advance | copy |
| `0x12` | i16 | −12 | −14 | −14 | Descender | copy |
| `0x14` | u32 | 1093 | 1093 | 1093 | Interval count `N` | `len(table)/16` |
| `0x18` | u32 | 19909 | 19909 | 19909 | Glyph count `G` | `Σ count` |
| `0x1c` | u32 | 64 | 64 | 64 | Header size | constant 64 |
| `0x20` | bytes[5] | 0 | 0 | 0 | Reserved | zero |
| `0x25` | u8 | 0x46 | — | 0x46 | **opaque** | copy |
| `0x26` | u16 | 0 | 0 | 0 | Reserved | zero |
| `0x28` | u16 | 574 | 629 | 710 | Bytes per record `P` | `1 + gridH × stride + 1` |
| `0x2a` | u16 | 0 | 0 | 0 | Reserved | zero |
| `0x2c` | u32 | 11427766 | 12522761 | 14135390 | Glyph data size | `G × P` |
| `0x30` | bytes[8] | varies | varies | varies | **opaque**, suspected hash | copy |
| `0x38` | u32 | 0x4490 | 0x4490 | 0x4490 | Offset of tail table | `0x40 + 16N` |
| `0x3c` | u32 | 95 | 95 | 95 | Tail table length `L` | sample constant |

### 4.2 Recomputable geometry

Three quantities are derived and have no relationship to any sample:

```
stride = ceil(0x0a × 2 / 8)        bytes per pixel row
cellW  = stride × 4                 pixels per stored cell
P      = 1 + gridH × stride + 1     bytes per glyph record
```

`gridH` and the render `em` are independent inputs. `gridH` is the row pitch;
`em` is the drawing size. A renderer MAY draw at an em larger than the layout
pitch, in which case the glyph face exceeds its advance; see §8.3.

`0x0b` and `0x0c` do NOT have a cross-size formula. Values from samples:
`(40 pt → 52/40)`, `(43 pt → 57/43)`, `(46 pt → 59/46)`. For an arbitrary
combination, choose `gridH` from the layout requirement and write the intended
render em; both fields are authoritative inputs to the reader, not derived
values.

### 4.3 Opaque fields

The fields at `0x06`, `0x08`, `0x0d`, `0x0e`, `0x10`, `0x12`, `0x25`, and
`0x30..0x37` have no known derivation. Their values differ between samples in
ways that do not correlate with any geometric parameter:

| Field | 40 pt | 43 pt | 46 pt |
|---|---|---|---|
| `0x0d` | 41 | 58 | 46 |
| `0x0e` | 19 | 35 | 21 |
| `0x10` | 40 | 43 | 45 |

An implementation MUST copy these bytes from a file produced by the vendor
toolchain. Writing zeros is known to work for `0x30..0x37` but is not
guaranteed for the others.

---

## 5. Interval Table

Starts at `0x40`, `N` rows of 16 bytes.

```c
struct XtfInterval {
    uint32_t first;      // first codepoint in this range
    uint32_t count;      // number of consecutive codepoints
    uint32_t cum_index;  // sum of all preceding counts
    uint32_t count_x16;  // count << 16
};
```

Constraints, satisfied by all samples:

1. Rows MUST be sorted ascending by `first` and MUST NOT overlap.
2. `cum_index[i]` MUST equal `Σ count[0..i-1]`.
3. `cum_index[N-1] + count[N-1]` MUST equal the glyph count at `0x18`.
4. `count_x16` MUST equal `count << 16`.

The table describes a character set, not glyph geometry, so samples that share a
character set share an identical table. Codepoint to record index:

```
index(cp) = cum_index[i] + (cp - first[i])   where first[i] ≤ cp < first[i] + count[i]
```

A codepoint absent from the table is not present in the font and MUST be
resolved by the reader's fallback mechanism.

Term meaning: the record occupies `data_start + index × P`.

---

## 6. Tail Table

Stored at `toc_end = 0x38`, length `L = 0x3c`, which is 95 in every sample. Not
zero padding: the reader parses it.

Contents are 95 bytes in the range 8..34, and the values scale with `gridH`:

| Sample | `gridH` | sum of bytes | min | max |
|---|---|---|---|---|
| 40 pt | 52 | 1782 | 8 | 30 |
| 46 pt | 59 | 2022 | 9 | 34 |

`2022 / 1782 = 1.135` and `59 / 52 = 1.135`. The scaling is proportional to
`gridH`, but individual entries are not interpolatable. The mapping from one
`gridH` to another is not a fixed multiplier per byte.

Requirement: an implementation MUST copy the 95 bytes verbatim from a sample.
Any `gridH` mismatch changes the reader's row layout. Substituting a table from
a nearby `gridH` is permitted only when no exact match exists.

Both known tables are recorded in Appendix B.

---

## 7. Glyph Records

### 7.1 Structure

`G` records of `P` bytes each, starting at `data_start`, ordered by
`cum_index`. A record is:

```c
struct XtfGlyph {
    uint8_t  advance;              // 1 byte, ignored by layout (§8.1)
    uint8_t  bitmap[gridH × stride];
    uint8_t  terminator;           // 1 byte, always 0x00
};
```

`P = 2 + gridH × stride`.

`advance` is stored per glyph but does not affect layout. Samples write a
constant equal to header `0x10`; an implementation SHOULD do the same.

`terminator` MUST be `0x00`.

### 7.2 Pixel encoding

Each byte holds four horizontally adjacent pixels, most significant pair first:

```
pixel[4b + k] = (byte >> (6 - 2k)) & 0b11      k = 0..3
```

Rows are stored top to bottom, `stride` bytes per row. Columns beyond
`cellW = stride × 4` are unused; for a `cellW` of 48 and an `em_pitch` of 44,
columns 44..47 lie outside the advance and MUST be zero (see §8.3).

Level semantics:

| Level | Meaning |
|---|---|
| 0 | paper (no ink) |
| 1 | light |
| 2 | dark |
| 3 | full ink |

### 7.3 Placement

The bitmap is positioned inside the `gridH × cellW` cell by the writer. Two
properties matter for appearance:

1. **Vertical centring.** The ink bounding box SHOULD be centred within
   `gridH`, not positioned by font ascent/descent. Metrics vary between
   typefaces and produce a visible baseline offset otherwise.
2. **Horizontal origin.** The ink SHOULD start at column 0 unless a specific
   left margin is being reproduced. A left margin derived from a small test
   string is unsafe: a 28-glyph probe may report its leftmost ink at column 3
   while characters such as 钧 begin at column 0, and cropping at 3 removes the
   first stroke of the radical.

---

## 8. Layout Model

### 8.1 Advance and pitch

The reader steps by `advance_pitch = 0x0a - 1` pixels per character. Neither the
header advance at `0x10` nor the per-record `advance` byte affects this.

### 8.2 Characters per line

Observed on a 528 px panel:

| `0x0a` | `advance_pitch` | Chars per line |
|---|---|---|
| 45 | 44 | 12 |
| 46 | 45 | **not measured** |
| 47 | 46 | 10 |

The relation `chars ≈ 57 - 0x0a` fits both measured points but is an empirical
fit, not a derivation. Simple division does not hold: `528 / 44 = 12` matches
the first point, while `528 / 46 = 11.48` does not give 10.

An implementation MUST NOT rely on a computed value for an unmeasured `0x0a`.

### 8.3 Face width budget

The stored cell width `cellW` is `stride × 4`, which is generally larger than
`advance_pitch`. A face wider than the pitch overlaps its neighbour.

```
pitch                 44      (from 0x0a = 45)
usable face width     43      pitch - 1, leaving a 1 px gap
cellW                 48      storage only, not a layout quantity
```

When a render em produces a face wider than the usable width, two options exist
and they are not equivalent:

| Method | Stroke weight | Effect |
|---|---|---|
| Resampling to the target width | reduced by the scale factor | side radicals lose weight |
| Cropping to the target width | unchanged | right edge is truncated |

Cropping preserves stroke weight and SHOULD be preferred. Columns at or beyond
`advance_pitch` MUST be zero, or the excess will be composited onto the
following glyph.

---

## 9. Quantisation

The reader stores two bits per pixel; a renderer must reduce 8-bit coverage to
four levels. Cut points used by the vendor toolchain:

```
level 1 if coverage ≥ 64/255
level 2 if coverage ≥ 128/255
level 3 if coverage ≥ 192/255
```

Measured panel reflectances for the four levels:

| Level | Relative reflectance |
|---|---|
| 0 | 1.000 |
| 1 | 0.578 |
| 2 | 0.132 |
| 3 | 0.000 |

Level 2 is only 13 % as bright as paper, so a cut point of 128/255 maps a 50 %
coverage pixel (a barely visible antialias fringe) onto a near-black level.
Raising the cuts to `96/160/224` reduces isolated fringe pixels at the cost of
slightly thinner strokes. An implementation MAY expose the cuts as a parameter.

---

## 10. Construction

A conforming writer produces a file as follows.

```
1.  Choose em_render, em_pitch, gridH, face_width.
2.  stride   = ceil((em_pitch + 1) * 2 / 8)
    cellW    = stride * 4
    P        = 1 + gridH * stride + 1
3.  Obtain a skeleton: header, interval table, tail table.
    Verify tail length is 95 and N matches the table length.
4.  data_start = (0x40 + 16N + L + 0x1FF) & ~0x1FF
5.  For each codepoint in the interval table:
      - render the glyph at em_render
      - centre the ink vertically within gridH
      - crop to face_width from column 0
      - quantise to four levels
      - zero every column at or beyond em_pitch
      - emit advance, packed bitmap, terminator
6.  Rewrite header fields 0x0a, 0x0b, 0x0c, 0x14, 0x18, 0x24, 0x28, 0x2c,
    0x38, 0x3c. Copy all other fields from the skeleton.
7.  Concatenate header, table, tail, zero padding, records.
8.  Assert file length == data_start + G * P.
```

Step 6 is the only place where the layout and the skeleton interact. Fields not
listed there MUST be left as the skeleton had them.

---

## 11. Conformance

A file is conforming if and only if all of the following hold.

1. Bytes 0..3 are `XTF0`.
2. `0x07 == 2`.
3. `0x14` equals the number of 16-byte rows before `0x38`.
4. `0x18` equals `Σ count` over the interval table.
5. `cum_index` is a running sum and the final range ends at `0x18`.
6. `count_x16 == count << 16` for every row.
7. `0x28 == 2 + 0x0b × stride`, where `stride = ceil(0x0a × 2 / 8)`.
8. `0x2c == 0x18 × 0x28`.
9. `0x24 == (0x40 + 16 × 0x14 + 0x3c + 0x1FF) & ~0x1FF`.
10. `0x3c` bytes follow `0x38` and all lie in 8..34.
11. File length equals `0x24 + 0x2c`.
12. Every record terminator is `0x00`.
13. No pixel at a column ≥ `0x0a - 1` is non-zero.

---

## 12. Test Vectors

A reference file produced by this project's writer, verified on hardware. It
reproduces the previously hardware-tested build byte for byte.

```
name          hy46.xtf
sha256        2E2E42D499206FFA7BE43917A22D033D2A4B828522B0CA482CE2024FFD04308B
size          14,392,218

em_render     46
em_pitch      44
gridH         60
face_width    43

header (first 64 bytes, hex)

```
0x00  58 54 46 30 01 05 40 02 03 00 2d 3c 2c 29 13 00
0x10  28 00 f4 ff 45 04 00 00 c5 4d 00 00 40 00 00 00
0x20  00 00 00 00 00 46 00 00 d2 02 00 00 9a 55 db 00
0x30  a9 1e 5a af 8f df 46 a5 90 44 00 00 5f 00 00 00
```

field values

| Offset | Value | Derivation |
|---|---|---|
| `0x0a` | 45 | `em_pitch + 1` |
| `0x0b` | 60 | `gridH` |
| `0x0c` | 44 | layout em |
| `0x0d` | 41 | opaque, copied |
| `0x0e` | 19 | opaque, copied |
| `0x10` | 40 | copied |
| `0x12` | −12 | copied |
| `0x14` | 1093 | `N` |
| `0x18` | 19909 | `G` |
| `0x1c` | 64 | constant |
| `0x24` | 17920 (`0x4600`) | `data_start` |
| `0x28` | 722 | `2 + 60 × 12` |
| `0x2c` | 14374298 (`0xdb559a`) | `19909 × 722` |
| `0x30` | `a9 1e 5a af 8f df 46 a5` | opaque, copied |
| `0x38` | 17552 (`0x4490`) | `toc_end` |
| `0x3c` | 95 | `L` |

cross-checks

```
0x18 × 0x28 = 19909 × 722 = 14,374,298  = 0x2c        ✓
0x24 + 0x2c = 17920 + 14374298 = 14,392,218 = length  ✓
```

Level distribution over the whole file: level 0 93.1 %, level 1 0.9 %,
level 2 0.9 %, level 3 5.0 %.

---

## Appendix A — Reference implementation

| File | Purpose |
|---|---|
| `ttf2xtf.py` | Writer: TTF/OTF to `.xtf` |
| `skeletons/skel_g52.bin` | Header + table + tail, `gridH` 52 |
| `skeletons/skel_g59.bin` | Header + table + tail, `gridH` 59 |

A skeleton is the first `data_start` bytes of a sample: header, interval table,
tail table, and padding. It carries no glyph outlines. Rebuilding from a
skeleton instead of a complete sample produces an identical file, which is how
the writer was validated.

---

## Appendix B — Tail tables

95 bytes each, hexadecimal.

`gridH` 52 — sum 1782, range 8..30:

```
0e 0b 0d 18 14 1b 14 08 0c 0c 0e 16 0b 0f 09 10 15 13 15 14 14 13
13 13 13 13 0a 0b 12 13 12 12 17 17 1b 17 18 1b 18 18 1a 11 1c 19 12
1e 18 17 17 16 17 15 1a 16 15 1b 1a 18 15 0d 0f 0d 10 12 0a 12 10 10
12 0e 12 12 11 0a 14 11 0d 1e 15 0e 12 11 11 0f 10 14 0f 19 12 16 12
0d 09 0d 15
```

`gridH` 59 — sum 2022, range 9..34:

```
10 0c 0f 1c 16 1f 16 09 0e 0e 10 19 0c 11 0a 12 17 16 17 16 17 16
16 16 16 16 0b 0d 15 15 15 14 1a 1a 1e 1a 1b 1e 1b 1b 1d 13 20 1c 14
22 1c 1a 1a 19 1a 18 1e 19 18 1f 1d 1b 18 0e 11 0f 12 15 0c 14 12 12
15 10 15 15 13 0c 16 14 0e 22 18 10 14 14 13 11 12 17 11 1c 14 1a 14
0f 0b 0e 18
```
