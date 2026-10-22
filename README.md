# xteink-toolkit

**English** | [简体中文](README.zh-CN.md)

Font and wallpaper converters for the **XTEINK X3** e-reader. 528 × 792, 259 ppi,
4-level greyscale (SSD1677).

Three standalone command line tools that generate the three container formats this
device reads, from scratch:

| Tool | Input | Output | Purpose |
|---|---|---|---|
| `ttf2bin.py` | TTF/OTF | `.bin` | 1-bit fonts, no header, 65536 fixed slots |
| `ttf2xtf.py` | TTF/OTF | `.xtf` | 2-bit fonts, 64-byte header, interval index |
| `img2xth.py` | any image | `.xth` | 2-bit full-screen wallpapers, 4-level dithered |

None of these formats is documented by the vendor. All three were reverse
engineered; the evidence and derivation live in
[`docs/XTF_FORMAT_SPEC.md`](docs/XTF_FORMAT_SPEC.md) and
[`docs/XTH_WALLPAPER_FORMAT.md`](docs/XTH_WALLPAPER_FORMAT.md).

---

## Install

```bash
pip install pillow numpy fonttools
```

Python 3.9+. The three scripts are independent. No shared module.

---

## Quick start

```bash
# font -> xtf: 12 chars/row, 60 px rows, 46 px type cropped to 43 px
python ttf2xtf.py MyFont.ttf --em 46 --pitch-em 44 --grid-h 60 --face-width 43

# font -> bin: 43x60 cell, 46 px type
python ttf2bin.py MyFont.ttf -w 43 -H 60 --em 46

# image -> wallpaper
python img2xth.py photo.jpg
```

Copy the results to the SD card: fonts into `Pushed Fonts/`, wallpapers into
`Pushed Images/`.

---

## `ttf2bin.py`

| Flag | Default | Meaning |
|---|---|---|
| `-w, --width` | required | Layout advance in px, written into the filename |
| `-H, --height` | required | Row height in px, written into the filename |
| `--em` | same as width | Render size |
| `--threshold` | 0.5 | Ink coverage cutoff, 0..1 |
| `--boost` | 1.0 | Multiply coverage before thresholding (stem darkening) |
| `--bold` | 0 | Synthetic bold stroke width in px |
| `--screen-width` | 528 | Panel width, used only to report chars/line |

```
stride     = ceil(W / 8)          bytes per pixel row
glyph_size = H * stride           bytes per glyph
total      = 65536 * glyph_size   fixed slot count, no header
bit order  left to right, MSB first within each byte
```

**Chars per line is governed by `W`**, measured rule `floor(528 / W) - 1`:

| W | 528/W | Chars per line |
|---|---|---|
| 40 | 13.2 | **12** |
| 43 | 12.3 | 11 |
| 44 | 12.0 | 11 |

W=43 and W=44 both give 11 characters: stored rows are byte aligned
(`ceil(W/8) * 8 = 48` bits), so both hold the same bitmap width. To fit 12
characters into 528 px, `W` must be ≤ 40.

`.bin` is 1 bit, **no antialiasing**, by format design. Grey edges require `.xtf`.

---

## `ttf2xtf.py`

| Flag | Default | Meaning |
|---|---|---|
| `--em` | 44 | Render size. Affects drawing only, **not written to the header** |
| `--pitch-em` | same as em | Layout advance, written as header `0x0a = pitch+1`. **Decides chars/line** |
| `--grid-h` | skeleton value | Row height |
| `--face-width` | pitch−1 | Crop the face to this width |
| `--skeleton` | `skeletons/skel_g52.bin` | Source of header / interval table / tail |
| `--cuts` | `64,128,192` | 2-bit quantisation cut points |
| `--boost` | 1.0 | Multiply coverage before quantising |

### Two different ems

```
pitch-em  ->  header 0x0a = pitch+1, decides chars per line
              (empirical: chars ≈ 57 - 0x0a)
em        ->  drawing size only, not stored in the header
```

You can pair a 44 px advance with 46 px type to get large glyphs at 12 chars/row.
The face then exceeds the advance, so something has to give:

| face-width | Result |
|---|---|
| `pitch - 1` | 1 px gap between characters, face cropped |
| `pitch` | No gap, neighbouring glyphs touch |

**Crop, don't resample.** Squeezing 45 px into 43 px thins every stroke by 4.4%
and side radicals visibly lose weight. Cropping keeps stroke weight and only
trims the right edge.

**Crop from column 0.** The left edge of a probe set is not a safe origin; 28
common characters may report their leftmost ink at column 3, while a character
like 钧 starts at column 0. Cropping from 3 slices the first stroke off the
radical.

### Chars per line

Governed by `0x0a`:

| `0x0a` | Chars per line | Status |
|---|---|---|
| 45 | 12 | verified |
| 46 | 11? | **unverified** |
| 47 | 10 | verified |

The middle value can only be settled on hardware; don't trust the formula alone.

---

## `img2xth.py`

| Flag | Default | Meaning |
|---|---|---|
| `--dither` | `fs` | `fs` / `bayer` / `none` |
| `--fit` | `cover` | `cover` crop-to-fill / `contain` letterbox / `stretch` |
| `--width` / `--height` | 528 / 792 | Output size, written into the header |
| `--timestamp` | now | Unix seconds for the header field |

```
22-byte header: magic "XTH\0" + width + height + reserved + payload size
                + timestamp + reserved
Two 1-bit planes, 52,272 bytes each
level = (planeB << 1) | planeA     0 = paper white, 3 = ink black
```

**Planes are stored column-major**. 792 consecutive bits form one image column,
and the stored image is horizontally mirrored. Decoding needs
`bits.reshape(w, h).T[:, ::-1]`, and encoding does the reverse. The mirror is not
a bug: it is the panel's scan order. Skip it and the wallpaper comes out flipped.

**Dithering, measured on the actual panel** with the same test image:

| Algorithm | On-device result | Recommendation |
|---|---|---|
| **Floyd-Steinberg** | Smooth transitions; a 16-step ramp reads as 16 distinct steps | **Default; use this** |
| Bayer 8×8 | Reads as nearly undithered | Not recommended |
| None | Collapses to four flat bands | Line art and diagrams only |

---

## Skeletons

`ttf2xtf.py` needs a 17,920-byte skeleton containing only:

```
0x0000..0x003F   64 B     header
0x0040..0x448F   17,488 B interval table
0x4490..0x44EE   95 B     tail table
0x44EF..0x45FF   padding
```

Everything after that is glyph data the tool generates itself. Rebuilding from
the skeleton instead of a complete vendor font produces a byte-identical file,
`SHA256 2E2E42D4...FFD04308B`, verified.

A skeleton is still required because three header fields have no known formula
and must be inherited.

- `0x0d`, `0x0e`: purpose unknown
- `0x30..0x37`: 8 bytes, differs between samples, purpose unknown

The rest (`0x0a`, `0x0b`, `0x0c`, `0x14`, `0x18`, `0x24`, `0x28`, `0x2c`, `0x38`,
`0x3c`) is recomputed by the tool.

`skel_g52.bin` comes from a 40 pt sample (gridH 52), `skel_g59.bin` from a 46 pt
sample (gridH 59). Both contain metadata only, no glyph outlines. The 95-byte tail
table is also recorded byte for byte in `docs/XTF_FORMAT_SPEC.md` §11.3, so in a
pinch the skeleton file isn't strictly necessary either.

**The character set comes from the skeleton.** The tool emits one record per one
of the skeleton's 19,909 codepoints; codepoints missing from your font are left
blank.

---

## Compatibility

**These tools are verified on the XTEINK X3 only** (528 × 792, 4-level greyscale). The firmware
contains only `xteink.cn` and `X3-CH` style strings, with no trace of any other model,
so there is currently no evidence either way for other devices.

The three formats do not depend on the device equally:

| Format | Screen size in header? | Portability |
|---|---|---|
| `.bin` | No — size lives in the **filename** | Most portable, pure W×H |
| `.xtf` | **No** — only em / gridH / cellW | Structurally unbound, but chars/line is empirical |
| `.xth` | **Yes** — width/height fields | Header has room for other sizes |

What is genuinely device-bound is the **panel width**, and it shows up in two places:

```bash
# chars/line report only, does not change output bytes
python ttf2bin.py font.ttf -w 40 -H 60 --screen-width 528

# wallpaper size, written into the .xth header
python img2xth.py art.png --width 480 --height 800
```

Wallpapers at a non-528 width print a warning: the size goes into the header, but
it has **not been tested on hardware**. If you get it working on another XTEINK
model, please open an issue with the model and firmware version.

`ttf2xtf` has no `--screen-width` on purpose: its chars/line formula
`57 - 0x0a` was fitted at 528 px and does not survive a different width.

---

## Limitations

- `.bin` is 1 bit only; antialiasing is impossible in that format.
- `.xtf` chars/line has only two verified points (45 → 12, 47 → 10); 46 is untested.
- `.xtf` interval tables cannot yet be generated from a font `cmap`; they follow the skeleton.
- Skeleton coverage is CJK + Latin; no emoji or supplementary planes.
- `ttf2bin` rendering cannot be matched byte for byte against arbitrary existing
  `.bin` files, because there is no vendor sample to reverse the parameters from, so the
  defaults are simply a working set.
- `img2xth` uses a pure-Python Floyd-Steinberg loop; 528×792 takes a few seconds.

---

## Verification

| Tool | Method | Result |
|---|---|---|
| `ttf2xtf` | Rebuild a hardware-tested font, compare SHA256 | **identical** |
| `ttf2bin` | Rebuild with the same parameters, compare renders | glyphs match, edges differ slightly with threshold |
| `img2xth` | Encode, decode per spec, compare level histogram | **round-trip exact**, 104,566 bytes |

`.xtf` has deterministic proof; `.bin` is visually consistent; `.xth` is
round-trip consistent.

A standalone validator implements the conformance sections of both specs:

```bash
python conformance_check.py --all .
python conformance_check.py font.xtf wall.xth
```

It checks 13 structural rules for `.xtf` (header consistency, interval table
sums, record size, terminators, and that no ink sits at or past the layout pitch)
and 5 for `.xth`. It reports structure only. Whether the glyphs or image look
right is a separate question.

---

## License

MIT. See [LICENSE](LICENSE).

Fonts and images remain the property of their respective owners. This project only
converts formats and ships no fonts or artwork.
