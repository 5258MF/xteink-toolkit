# XTH Wallpaper Container — Format Specification

Version 1.0 · applies to `.xth` files consumed by XTEINK X3 firmware V6.4.x

---

## 1. Scope

This document specifies the binary layout of the `.xth` wallpaper container: a
2-bit greyscale, full-panel image format used by the XTEINK X3 e-reader.

`.xth` files are read as plaintext from the SD card. They are not encrypted and
not bound to a device key. A separate container, `.xtge`, is device-bound and is
out of scope here.

---

## 2. Conventions

- All multi-byte integers are **little endian**.
- `u16`, `u32` denote unsigned 16- and 32-bit integers.
- Offsets are byte offsets from the start of the file.
- The key words MUST, MUST NOT, SHOULD, and MAY are used as in RFC 2119.
- "Panel" means the 528 × 792, 4-level greyscale display of the target device.

---

## 3. File Layout

```
offset      size        content
0x00        22          header
0x16        52272       plane A
0x16+52272  52272       plane B
```

Total length is `22 + 2 × (W × H / 8)`.

For the standard panel, `528 × 792 / 8 = 52,272` and the total is **104,566**
bytes.

---

## 4. Header

22 bytes.

| Offset | Type | Meaning | Constraint |
|---|---|---|---|
| `0x00` | char[4] | Magic | MUST be `XTH\0` |
| `0x04` | u16 | Width `W` | MUST be a multiple of 8; 528 for the standard panel |
| `0x06` | u16 | Height `H` | 792 for the standard panel |
| `0x08` | u16 | Reserved | MUST be 0 |
| `0x0a` | u32 | Payload size | MUST equal `2 × W × H / 8` |
| `0x0e` | u32 | Timestamp | Unix seconds; the reader does not validate it |
| `0x12` | u32 | Reserved | MUST be 0 |

```c
#pragma pack(push, 1)
typedef struct {
    char     magic[4];      /* "XTH\0"          */
    uint16_t width;         /* 528              */
    uint16_t height;        /* 792              */
    uint16_t reserved0;     /* 0                */
    uint32_t payload_size;  /* 2 * W * H / 8    */
    uint32_t timestamp;     /* unix seconds     */
    uint32_t reserved1;     /* 0                */
} XthHeader;                /* sizeof == 22     */
#pragma pack(pop)
```

`0x08` is a `uint16`, not a `uint32`. Reading it as 32 bits yields a 24-byte
header and desynchronises every subsequent field.

---

## 5. Pixel Planes

The payload is two independent 1-bit planes of `W × H / 8` bytes each.

### 5.1 Plane encoding

Each plane is a bitmap where one bit corresponds to one pixel. Bits are packed
with the most significant bit first.

Two transformations apply, and both are mandatory:

1. **Column major.** The plane is stored as `W` runs of `H` bits. The first `H`
   bits form image column 0, the next `H` bits form column 1, and so on.
2. **Horizontal mirror.** The stored image is left-right reversed relative to
   the displayed image.

Reading a plane therefore requires an unpack, a reshape to `(W, H)`, a transpose,
and a horizontal flip:

```python
bits   = np.unpackbits(np.frombuffer(plane_bytes, dtype=np.uint8))
pixels = bits.reshape(W, H).T[:, ::-1]          # shape (H, W), values 0/1
```

Writing is the inverse:

```python
plane_bytes = np.packbits(pixels[:, ::-1].T.ravel().astype(np.uint8)).tobytes()
```

Treating the plane as row-major produces a repeatedly tiled and torn image. The
mirror is the panel's scan order, not an artifact of the encoder.

### 5.2 Level composition

Plane A carries the low bit, plane B the high bit:

```
level = (B << 1) | A
```

| A | B | level | Appearance |
|---|---|---|---|
| 0 | 0 | 0 | paper |
| 1 | 0 | 1 | light grey |
| 0 | 1 | 2 | dark grey |
| 1 | 1 | 3 | ink |

Measured panel reflectances: level 0 = 1.000, level 1 = 0.578, level 2 = 0.132,
level 3 = 0.000. Level 2 is only 13 % as bright as paper, so a dithered pattern
alternating levels 0 and 3 reads as mid-grey while levels 1 and 2 are used
sparingly.

---

## 6. Tone Mapping

The file stores *ink*, not *luminance*. Two complementary scales are involved and
they are easy to confuse:

```
luminance  q   : 0 = black,   3 = white
ink        = 3 - q
```

A source pixel that is black MUST end up as `level 3`. Writing `q` directly
inverts the image: black renders as paper and white renders as ink.

A writer reduces 8-bit grey to four levels, optionally with dithering. Measured
on the target panel with an identical test image:

| Method | On-device result | Recommendation |
|---|---|---|
| Floyd-Steinberg error diffusion | Smooth transitions; a 16-step ramp resolves as 16 distinct steps | SHOULD be used |
| Ordered Bayer 8 × 8 | Reads as nearly undithered | Not recommended |
| No dithering | Four flat bands | Acceptable for line art and diagrams only |

Error diffusion is preferred because it distributes quantisation error so that
local dot density encodes intermediate tones; ordered dithering produces a fixed
pattern that the panel's limited reflectance range does not resolve.

---

## 7. Construction

```
1.  Load the source image as 8-bit greyscale, compositing any alpha channel
    onto white.
2.  Scale and position it to exactly W × H.
3.  Reduce to four luminance levels. Default: serpentine Floyd-Steinberg.
4.  Convert luminance to ink:  ink = 3 - q
5.  Split the ink levels into two planes:  A = ink & 1,  B = (ink >> 1) & 1
6.  Pack each plane column-major and horizontally mirrored, MSB first.
7.  Emit the 22-byte header followed by plane A then plane B.
8.  Assert total length == 22 + 2 × (W × H / 8).
```

Steps 3 through 6 are order-sensitive. Dithering after the inversion, or packing
before the mirror, both produce a file that decodes to a wrong image without any
structural violation.

---

## 8. Conformance

A file is conforming if and only if all of the following hold.

1. Bytes 0..3 are `XTH\0`.
2. `0x08` and `0x12` are zero.
3. `W` at `0x04` is a multiple of 8.
4. `0x0a` equals `2 × W × H / 8`.
5. File length equals `22 + 0x0a`.

---

## 9. Test Vectors

A file produced by this project's writer from a source image cropped to fill the
panel.

```
name        x3_wall_violet.xth
sha256      03d4663be6e75b9f486d9a912b81a7303570eedf950ffdac475a5575b62ff2a4
size        104,566

header (22 bytes, hex)
  58 54 48 00 10 02 18 03 00 00 60 98 01 00 40 c4 d8 6a 00 00 00 00

fields
  0x00  "XTH\0"
  0x04  528            W
  0x06  792            H
  0x08  0              reserved
  0x0a  104544         = 2 * 528 * 792 / 8
  0x0e  1792590912     unix seconds
  0x12  0              reserved

derived
  header size   22
  plane size    52,272
  stride        66 bytes per column run = ceil(528 / 8)
```

Level histogram after decoding: 0 → 51.6 %, 1 → 23.3 %, 2 → 23.0 %, 3 → 2.1 %.

---

## Appendix A — Reference implementation

| File | Purpose |
|---|---|
| `img2xth.py` | Writer: any image to `.xth` |

```bash
python img2xth.py art.png                    # 528 x 792, Floyd-Steinberg
python img2xth.py art.png --dither bayer     # ordered
python img2xth.py art.png --width 480 --height 800
```

`--width` and `--height` change the header fields and the payload size
accordingly. Only the 528 × 792 configuration has been verified on hardware.

---

## Appendix B — Decoding reference

```python
import struct
import numpy as np

def read_xth(path):
    raw = open(path, "rb").read()
    assert raw[:4] == b"XTH\0"
    w, h, r0 = struct.unpack_from("<HHH", raw, 4)
    size, ts, r1 = struct.unpack_from("<III", raw, 0x0a)
    assert r0 == 0 and r1 == 0
    assert size == 2 * w * h // 8
    assert len(raw) == 22 + size

    def plane(buf):
        bits = np.unpackbits(np.frombuffer(buf, np.uint8))
        return bits.reshape(w, h).T[:, ::-1]

    p = w * h // 8
    a = plane(raw[22:22 + p])
    b = plane(raw[22 + p:22 + 2 * p])
    return w, h, ts, (b.astype(np.uint8) << 1) | a
```
