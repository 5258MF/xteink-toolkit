# `.xtf` 字体容器格式规范（v3）

> 目标设备：XTEINK / 阅星曈 X3（ESP32-C3，528×792，259 PPI，SSD1677，4 级灰）
> 样本：官方 40 / 43 / 46 号三份。40 与 46 有完整文件（header、区间表、tail、字形），43 只拿到 header。
> 验证方式：按本文生成的 40 号与 46 号文件，**header + 区间表 + tail 与官方逐字节 0 差异**。

---

## 0. 这份文档解决什么

`.xtf` 的坑不在结构，在**几个"看起来能算、实际不能算"的字段**。v1/v2 在这上面栽了三次，症状分别是乱码、半截、字间碎片。本文把哪些能推、哪些必须抄，逐条写死。

**动手前先读 §9。**

---

## 1. 总布局

```
偏移            内容                      长度
0x0000          文件头                    64 B
0x0040          区间表                    16 B × N
toc_end         tail 表                   L 字节（0x3c 字段给出，样本恒 95）
...             零填充至 512 对齐
data_start      字形数据                  per × 字形数

toc_end    = 0x40 + 16 × N
data_start = (toc_end + 0x1FF) & ~0x1FF
```

唯一硬校验：

```
文件大小 == data_start + per × 字形数
```

三份样本全部通过：

| | 40 号 | 43 号 | 46 号 |
|---|---|---|---|
| 文件大小 | 11,445,686 | 12,540,681 | 14,153,310 |
| 区间数 N | 1093 | 1093 | 1093 |
| 字形数 | 19,909 | 19,909 | 19,909 |
| per | 574 | 629 | 710 |
| toc_end | 0x4490 | 0x4490 | 0x4490 |
| data_start | 0x4600 | 0x4600 | 0x4600 |

---

## 2. 文件头（0x00–0x3F）

小端。三份官方样本并列：

| 偏移 | 类型 | 40 号 | 43 号 | 46 号 | 含义 | 能否推算 |
|---|---|---|---|---|---|---|
| 0x00 | 4 B | `58 54 46 30` | 同 | 同 | 魔数 `"XTF0"` | 固定 |
| 0x04 | u8 | 1 | 1 | 1 | 主版本 | 固定 |
| 0x05 | u8 | 5 | 5 | 5 | 次版本 | 固定 |
| 0x06 | u8 | 0x40 | 0x40 | 0x40 | 未确认 | **照抄 0x40** |
| 0x07 | u8 | 2 | 2 | 2 | 位深 2 bit/px | 固定 |
| 0x08 | u16 | 3 | 3 | 3 | 未确认 | 照抄 3 |
| 0x0a | u8 | 41 | 44 | 47 | 宽度基准 | **= em + 1** ✓ |
| 0x0b | u8 | 52 | 57 | 59 | **字格高 gridH** | **不可推算**（§7.2） |
| 0x0c | u8 | 40 | 43 | 46 | **em** | 你定的字号 |
| 0x0d | u8 | 41 | 58 | 46 | faceH | **不可推算**（§7.3） |
| 0x0e | u16 | 19 | 35 | 21 | 未确认 | **不可推算**（§7.3） |
| 0x10 | u16 | 40 | 43 | 45 | header advance | 不可推算，见 §5.1 |
| 0x12 | i16 | -12 | -14 | -14 | descender | 不可推算 |
| 0x14 | u32 | 1093 | 1093 | 1093 | **区间数 N** | = 区间表行数 |
| 0x18 | u32 | 19909 | 19909 | 19909 | **字形总数** | = Σ count |
| 0x1c | u32 | 64 | 64 | 64 | 未确认 | 照抄 64 |
| 0x20 | 5 B | 00 | 00 | 00 | 预留 | 0 |
| 0x25 | u8 | 0x46 | ? | 0x46 | 未确认 | 照抄 0x46 |
| 0x26 | u16 | 0 | 0 | 0 | 预留 | 0 |
| 0x28 | u16 | 574 | 629 | 710 | **每字形字节数 per** | `1 + gridH×stride + 1` ✓ |
| 0x2c | u32 | 11,427,766 | 12,522,761 | 14,135,390 | **字形数据大小** | `字形数 × per` ✓ |
| 0x30 | 8 B | `a9 1e …` | ? | `07 6e …` | 疑似哈希 | 置 0 不影响加载 |
| 0x38 | u32 | 0x4490 | 0x4490 | 0x4490 | **toc_end** | `0x40 + 16N` ✓ |
| 0x3c | u32 | 95 | 95 | 95 | **tail 表长度** | 样本恒 95 |

**✓ 标记的四条是可以在任意字号下重算的**：`0x0a`、`0x28`、`0x2c`、`0x38`。
其余尺寸相关字段（`0x0b 0x0d 0x0e 0x10 0x12` 和 tail 内容）**没有跨字号成立的公式**，必须从同字号的官方文件取。

---

## 3. 区间表（0x0040 起）

每项 16 字节：

```c
struct XtfInterval {
    uint32_t first;      // 起始码位
    uint32_t count;      // 本区间字形数
    uint32_t cum_index;  // 前面所有 count 之和
    uint32_t count_x16;  // count << 16
};
```

约束（三份样本全部满足）：

- 按 `first` 升序，互不重叠
- `cum[i] == Σ count[0..i-1]`
- 末项 `cum + count == 0x18` 字段
- `count_x16 == count << 16`

三份样本的区间表**完全相同**（1093 行、19,909 字、同样的码位），因为它描述的是字符集而不是字形几何：

```
first  count  cum     count_x16
0      1      0       65536
13     1      1       65536
32     95     2       6225920      ← ASCII 0x20–0x7E
160    608    97      39845888
902    28     705     1835008      ← 希腊文
931    333    733     21823488     ← 西里尔
```

码位 → 字形下标：

```python
def cp_to_index(cp):
    for first, count, cum, _ in intervals:
        if first <= cp < first + count:
            return cum + (cp - first)
    return None          # 不在表内 → 交给系统字体回退
```

---

## 4. tail 表（toc_end 起，L 字节）

**这是整个格式最容易踩的坑。** v1 把它当成零填充，v2 以为它固定不变，两次都错。

### 4.1 事实

- 位置：紧接区间表
- 长度：`0x3c` 字段，两份完整样本都是 **95**
- 之后零填充到 `data_start`
- **内容随 gridH 变**

两份样本：

```
40 号（gridH 52）：sum 1782, min 8, max 30
0e 0b 0d 18 14 1b 14 08 0c 0c 0e 16 0b 0f 09 10
15 13 15 14 14 13 13 13 13 13 0a 0b 12 13 12 12
17 17 1b 17 18 1b 18 18 1a 11 1c 19 12 1e 18 17
17 16 17 15 1a 16 15 1b 1a 18 15 0d 0f 0d 10 12
0a 12 10 10 12 0e 12 12 11 0a 14 11 0d 1e 15 0e
12 11 11 0f 10 14 0f 19 12 16 12 0d 09 0d 15

46 号（gridH 59）：sum 2022, min 9, max 34
10 0c 0f 1c 16 1f 16 09 0e 0e 10 19 0c 11 0a 12
17 16 17 16 17 16 16 16 16 16 0b 0d 15 15 15 14
1a 1a 1e 1a 1b 1e 1b 1b 1d 13 20 1c 14 22 1c 1a
1a 19 1a 18 1e 19 18 1f 1d 1b 18 0e 11 0f 12 15
0c 14 12 12 15 10 15 15 13 0c 16 14 0e 22 18 10
14 14 13 11 12 17 11 1c 14 1a 14 0f 0b 0e 18
```

### 4.2 缩放关系

`2022 / 1782 = 1.135`，`59 / 52 = 1.135`，两个比例相同 → **tail 是一组绝对像素量，按行高等比缩放**。

但**不要用插值去造别的行高**。逐项验证：

| 位置 | 40 号值 | ×59/52 | 46 号实际值 | 是否吻合 |
|---|---|---|---|---|
| 0 | 14 | 15.88 | 16 | ✔ |
| 1 | 11 | 12.48 | 12 | ✔ |
| 2 | 13 | 14.75 | 15 | ✔ |
| 3 | 24 | 27.23 | 28 | ✘ 差 0.77 |

个别项有偏差，说明它不是简单的 `round(a × k)`。

### 4.3 结论

**tail 必须从 gridH 相同的官方文件取，不能置 0，不能插值。**

实测后果：

| 用法 | 结果 |
|---|---|
| 40 号的 tail + gridH 52 | 正常 |
| 40 号的 tail + gridH 57 | 字形撕裂、字间碎片 |
| 零填充 tail + gridH 60 | 乱码、字形被切半 |

拿不到同字号样本时，只能用 40 号（52 高）或 46 号（59 高）这两种几何。

---

## 5. 字形记录（数据区，每项 per 字节）

```
+0                1 B    advance（单字节）
+1                位图   gridH × stride
+1 + gridH*stride 1 B    padding，填 0
```

### 5.1 advance 是逐字的

`+0` 这个字节**每个字形可以不同**。官方 46 号抽样 86 个汉字：min 46、max 47、mean 46.30。

header 的 `0x10` 只是默认值（40→40、43→43、46→45），实际排版以记录里的字节为准。

**做法**：取字体自身的 advance（`glyph.advance.x / 64` 四舍五入），封顶 255。不要整份写死一个数——写死会把字距和字形宽度解耦，出现字挤在一起或中间多条灰缝。

### 5.2 位图几何

```
stride = ceil(0x0a × 2 / 8)       # 0x0a = em + 1
cellW  = stride × 4
per    = 1 + gridH × stride + 1
```

三份样本验证：

| | 40 | 43 | 46 |
|---|---|---|---|
| em | 40 | 43 | 46 |
| 0x0a | 41 | 44 | 47 |
| stride = ceil(0x0a×2/8) | 11 | 11 | 12 |
| cellW = stride×4 | 44 | 44 | 48 |
| gridH | 52 | 57 | 59 |
| per = 1+gridH×stride+1 | 574 | 629 | 710 |

**cellW 不是固定值，也不是 `em+4`。** 它由 `0x0a` 推出；40 号恰好 em+4=44，43 号是 em+1=44，46 号是 em+2=48，三种都不重样，只有 `ceil((em+1)×2/8)×4` 一路成立。

解析时反推：

```python
stride = (per - 2) // gridH
cellW  = stride * 4
```

### 5.3 像素解包

每字节 4 像素，**MSB first**：

```python
def unpack_row(row):
    px = []
    for b in row:
        px += [(b >> 6) & 3, (b >> 4) & 3, (b >> 2) & 3, b & 3]
    return px[:cellW]
```

等级 → 反射率（实测面板）：

| 等级 | 反射率 |
|---|---|
| 0 | 1.000 |
| 1 | 0.578 |
| 2 | 0.132 |
| 3 | 0.000 |

等级 2 只有理想值的 40%，暗端天然压缩，别指望四档均匀。

### 5.4 字形在格子里的位置

官方 46 号（cell 48×59）实测 86 个汉字：

```
bbox left    min 0   max 14  mean 5.94
bbox right   min 39  max 47  mean 46.02
bbox width   min 27  max 48  mean 41.08
```

**左边缘平均留 6 px**，不是贴着 0。如果自己摆字形，按墨迹居中会偏左约 3 px，上一字右侧的淡灰边缘就会压到下一字起点，视觉上是字间多出碎屑。

定位建议（实测可用）：先按 `ImageDraw.text` + 探针字墨迹居中（§8 `placement`），再把 `dx` 右移 3 px。

---

## 6. 生成流程（模板克隆法）

**核心原则：拿同字号的官方文件当字节模板，只改必然变的字段和字形数据。**

```python
import struct
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import numpy as np

TEMPLATE = Path("46_官方样本.xtf")     # 同字号的官方文件
SRC      = Path("MyFont.ttf")
OUT      = Path("out.xtf")

EM      = 46
GRID_H  = 59          # 照抄模板
CELL_W  = ((EM + 1) * 2 + 7) // 8 * 4
STRIDE  = CELL_W // 4
PER     = 1 + GRID_H * STRIDE + 1
DESC    = -14         # 照抄模板
ADV_DEF = 45          # 照抄模板 0x10
FACE_H  = 46          # 照抄模板 0x0d
FIELD_0E = 21         # 照抄模板 0x0e
CUT     = (64, 128, 192)
PROBE   = "国永东南西北中正口田目日月山水火木金土这回飞"


def template_parts():
    raw = TEMPLATE.read_bytes()
    n   = struct.unpack_from("<I", raw, 0x14)[0]
    toc = struct.unpack_from("<I", raw, 0x38)[0]
    tl  = struct.unpack_from("<I", raw, 0x3c)[0]
    cps = []
    for k in range(n):
        o = 0x40 + k * 16
        first, count = struct.unpack_from("<II", raw, o)
        cps.extend(range(first, first + count))
    return raw[:0x40], raw[0x40:toc], raw[toc:toc + tl], toc, cps


def placement(font_path, em, cell_w, cell_h):
    font = ImageFont.truetype(str(font_path), em)
    asc, desc = font.getmetrics()
    dy = (cell_h - (asc + desc)) // 2
    dx = max(0, (cell_w - em) // 2)
    m = 40
    x0 = x1 = y0 = y1 = None
    for ch in PROBE:
        img = Image.new("L", (cell_w + m * 2, cell_h + m * 2), 255)
        ImageDraw.Draw(img).text((m + dx, m + dy), ch, font=font, fill=0)
        a = np.asarray(img) < 200
        if not a.any():
            continue
        yy, xx = np.nonzero(a)
        ax0, ax1 = xx.min() - m, xx.max() - m
        ay0, ay1 = yy.min() - m, yy.max() - m
        x0 = ax0 if x0 is None else min(x0, ax0)
        x1 = ax1 if x1 is None else max(x1, ax1)
        y0 = ay0 if y0 is None else min(y0, ay0)
        y1 = ay1 if y1 is None else max(y1, ay1)
    if x0 is not None:
        dx -= round((x0 + x1 - (cell_w - 1)) / 2)
        dy -= round((y0 + y1 - (cell_h - 1)) / 2)
    return font, dx + 3, dy       # +3 见 §5.4


def quantise(cov):
    lv = np.zeros(cov.shape, np.uint8)
    lv[cov >= CUT[0] / 255.0] = 1
    lv[cov >= CUT[1] / 255.0] = 2
    lv[cov >= CUT[2] / 255.0] = 3
    return lv


def pack(cell):
    h = cell.shape[0]
    out = bytearray(h * STRIDE)
    for y in range(h):
        row = cell[y]
        for b in range(STRIDE):
            x = b * 4
            out[y * STRIDE + b] = ((int(row[x]) << 6) | (int(row[x + 1]) << 4)
                                   | (int(row[x + 2]) << 2) | int(row[x + 3]))
    return bytes(out)


def build():
    hdr0, table, tail, toc, cps = template_parts()
    font, dx, dy = placement(SRC, EM, CELL_W, GRID_H)
    m = 40
    blank = np.zeros((GRID_H, CELL_W), np.uint8)
    recs = []
    for cp in cps:
        try:
            img = Image.new("L", (CELL_W + m * 2, GRID_H + m * 2), 255)
            ImageDraw.Draw(img).text((m + dx, m + dy), chr(cp), font=font, fill=0)
            a = np.asarray(img, np.float32)[m:m + GRID_H, m:m + CELL_W]
            cell = quantise((255.0 - a) / 255.0)
            adv = round(font.getlength(chr(cp))) or EM     # 逐字 advance
        except Exception:
            cell, adv = blank, EM
        recs.append(struct.pack("<B", min(adv, 255)) + pack(cell) + b"\x00")

    data_start = (toc + 0x1FF) & ~0x1FF
    hdr = bytearray(hdr0)
    hdr[0x0a] = EM + 1
    hdr[0x0b] = GRID_H
    hdr[0x0c] = EM
    hdr[0x0d] = FACE_H
    struct.pack_into("<H", hdr, 0x0e, FIELD_0E)
    struct.pack_into("<H", hdr, 0x10, ADV_DEF)
    struct.pack_into("<h", hdr, 0x12, DESC)
    struct.pack_into("<I", hdr, 0x14, len(table) // 16)
    struct.pack_into("<I", hdr, 0x18, len(cps))
    struct.pack_into("<H", hdr, 0x28, PER)
    struct.pack_into("<I", hdr, 0x2c, len(cps) * PER)
    struct.pack_into("<I", hdr, 0x38, toc)
    struct.pack_into("<I", hdr, 0x3c, len(tail))

    body = b"".join(recs)
    pad = b"\x00" * (data_start - toc - len(tail))
    blob = bytes(hdr) + table + tail + pad + body
    OUT.write_bytes(blob)
    assert len(blob) == data_start + len(cps) * PER
    print(f"{OUT.name} {len(blob):,} B  per={PER}")


build()
```

**必须从模板抄的**：`0x06 0x08 0x0d 0x0e 0x10 0x12 0x1c 0x25 0x30..0x37` 以及 **tail 全部字节**。
**可以自己算的**：`0x0a 0x0b 0x0c 0x14 0x18 0x28 0x2c 0x38 0x3c`。

---

## 7. 不可推算项

### 7.1 结论表

| 字段 | 40 | 43 | 46 | 能否推出 |
|---|---|---|---|---|
| gridH | 52 | 57 | 59 | ✘（52/40=1.30，59/46=1.283） |
| faceH | 41 | 58 | 46 | ✘（无规律） |
| `0x0e` | 19 | 35 | 21 | ✘ |
| `0x10` | 40 | 43 | 45 | ✘ |
| descender | -12 | -14 | -14 | ✘（45/43 都是 -14） |
| tail 内容 | 1782 | ? | 2022 | ✘（只能取同 gridH 的） |

### 7.2 gridH

`round(em × 1.29)` 在三个样本上分别得到 52、56、59，与实测 52、57、59 差 0~1。**不要用公式，抄样本。**

### 7.3 faceH 与 0x0e

- 40 号：faceH 41 = em+1，`0x0e` 19
- 43 号：faceH 58 = gridH+1，`0x0e` 35
- 46 号：faceH 46 = em，`0x0e` 21

三条互不相容，含义不明。**照抄同字号样本，不要按任何公式填。**

### 7.4 0x25 与 0x30..0x37

`0x25` 两份都是 0x46；`0x30..0x37` 是 8 字节，两份完全不同（`a9 1e 5a af 8f df 46 a5` / `07 6e 7a 45 dc 96 99 60`），疑似哈希。置 0 不影响加载（实测）。

### 7.5 每行字数：跟 `0x0a` 走，但公式未知

> **勘误**：本节早期版本断言"每行字数由 cellW 决定"。**这个结论是错的**，反例很直接——

| 文件 | `0x0a` | `0x0c` | gridH | cellW | per | 实测每行 |
|---|---|---|---|---|---|---|
| `hy44` | 45 | 44 | 52 | **48** | 626 | **12** |
| `fz44` | 45 | 44 | 52 | **48** | 626 | **12** |
| `46c` | 47 | 46 | 59 | **48** | 710 | **10** |

三个文件 cellW 全是 48，字数却是 12 和 10。cellW 不是决定因素。

**已确认的事实**

1. `0x10`（默认 advance）和字形记录里的逐字 advance **都不参与排版**——把它们从 46 改成 43，行内字数毫无变化。
2. `0x0a` 与字数强相关：`45 → 12 字`，`47 → 10 字`，是唯一的单调相关字段。
3. 简单除法不成立：`528/44 = 12` 对得上 `hy44`，但 `528/46 = 11.48` 对不上 `46c` 的 10 字。

**能用的经验公式（两点线性外推，不是机制）**

```
每行字数 ≈ 57 - 0x0a
```

45 → 12、47 → 10 都吻合。但它是拟合，不是推导。**`0x0a = 46` 时究竟是 11 还是 10，必须上机实测，不能按公式断言。**

**调整字数的正确做法**

只改 `0x0a`，**不要动** `0x0c`（真实 em）和字形渲染尺寸。这样字号不变，只有行内字数变。

```
0x0a = 45  →  12 字（实测）
0x0a = 46  →  11 字？  （未实测，待验证）
0x0a = 47  →  10 字（实测）
```

**`.bin` 是完全另一套规则**，见 §10——它靠文件名里的 W 和字节对齐，与 `0x0a` 无关。

### 7.6 字面宽度、裁切与压缩

排版步进（每字占多少屏幕像素）和存储格（`cellW`）是两回事，可用宽度如下：

```
排版步进 = 0x0a - 1              # 0x0a=45 → 44 px
每行字数 = 57 - 0x0a             # 经验式，见 §7.5
字面可用宽度 = 排版步进 - 1      # 留 1 px 字间缝 → 43 px
```

**字面超过可用宽度时，只有两种处理方式，效果完全不同：**

| 方式 | 做法 | 笔画宽度 | 结果 |
|---|---|---|---|
| **压缩** | 把 45 px 重采样到 43 px | **变细 4.4%** | 偏旁、细笔画明显变瘦 |
| **裁切** | 保留左 43 px，丢掉右边 2 px | **不变** | 笔画原样，只损失最右边缘 |

`.bin` 的做法是**裁切**。曾经用了压缩，被用户直接指出来："金字旁的撇缺了一点点"——那就是笔画被压细的证据。

**裁切起点的坑（务必读）**

裁切起点**不能用测试字集的并集边界**。曾经用 28 个字的并集左边界 `3` 当起点，结果：

```
PROBE 28 字并集左边界 = 3
'钧' 实际左边界       = 0    ← 撇的起笔在最左
```

于是列 0、1、2 被切掉，正好是金字旁的撇；而右边 46、47 本来是空的却没利用。**方向裁反了。**

正确做法：

```
从第 0 列开始裁，取 0..(W-1)，丢掉最右的差额
放置起点用 0（不是官方的 1），否则整体右移会顶到排版权边界，字间变成零缝
```

**验证方法**：生成后读回字形墨迹列，确认左边界落在 0~2 之间（不是 3 以上），且右边界 ≤ 排版步进 - 1。

### 7.7 灰度量化与面板反射率

实测这块屏四级灰阶的反射率：

```
level 0 (白) = 1.000
level 1      = 0.578
level 2      = 0.132     ← 只比黑亮 13%
level 3 (黑) = 0.000
```

官方切点 `64 / 128 / 192`（8-bit 覆盖度）。问题在于 **`128` 只要覆盖率 50% 就判成级别 2**，而级别 2 实际只有 13% 亮度——一个本该半透明、几乎看不见的抗锯齿边缘像素，被画成一个实心暗点。

**症状**：笔画边缘、字与字之间出现零星灰点，且改字形几何无效。

**处理**：提高切点到 `96 / 160 / 224`。灰 2 像素从 2.1% 降到 1.0%，边缘干净；代价是黑像素 5.1% → 4.6%，笔画略细。

**判断依据**：如果灰点只出现在笔画边缘、且连通域扫描（面积 ≤3、不含纯黑）能找到，就是量化问题；如果扫描结果是 0，那灰点来自几何（相邻字挤压），不要动量化。

### 7.8 tail 的表征

95 个 8–34 的整数，和随 gridH 等比变化。可能和"每 N 个字形的行高统计"有关（19909 / 1782 ≈ 11.2），未证实。**只知道：必须原样复制。**

实测比例：40pt（gridH 52）总和 1782，46pt（gridH 59）总和 2022，比值 `2022/1782 = 1.135`，恰好等于 `59/52 = 1.135`。所以它确实随 gridH 缩放，但**不能按项插值**——必须从同 gridH 的官方文件整表复制。找不到同高度官方文件时，用最近高度的表并接受风险（gridH 60 配 gridH 52 的表，实测显示正常）。


---

## 8. 验证清单

```python
import struct
from pathlib import Path


def verify(path):
    b = Path(path).read_bytes()
    assert b[:4] == b"XTF0", "magic"
    em      = b[0x0c]
    b0a     = b[0x0a]
    gridH   = b[0x0b]
    n_int   = struct.unpack_from("<I", b, 0x14)[0]
    n_gly   = struct.unpack_from("<I", b, 0x18)[0]
    per     = struct.unpack_from("<H", b, 0x28)[0]
    dsize   = struct.unpack_from("<I", b, 0x2c)[0]
    toc     = struct.unpack_from("<I", b, 0x38)[0]
    tl      = struct.unpack_from("<I", b, 0x3c)[0]
    start   = (toc + 0x1FF) & ~0x1FF

    assert b0a == em + 1,                       "0x0a 应为 em+1"
    assert toc == 0x40 + n_int * 16,            "toc_end 与区间数不符"
    assert per == 2 + gridH * ((per - 2) // gridH), "per 与 gridH 不整除"
    assert (per - 2) // gridH == -(-(b0a * 2) // 8), "stride 与 0x0a 矛盾"
    assert dsize == n_gly * per,                "0x2c 应为 字形数×per"
    assert start + n_gly * per == len(b),       "总长校验失败"
    assert tl > 0 and any(b[toc:toc + tl]),     "tail 表为空"

    cum = 0
    for k in range(n_int):
        f, c, cm, c16 = struct.unpack_from("<IIII", b, 0x40 + k * 16)
        assert cm == cum,       f"row {k} cum"
        assert c16 == c << 16,  f"row {k} count_x16"
        cum += c
    assert cum == n_gly, "区间累加 ≠ 字形总数"
    print(f"OK em={em} gridH={gridH} cellW={((per-2)//gridH)*4} per={per} "
          f"ranges={n_int} glyphs={n_gly} tail={tl} size={len(b):,}")
```

再抽三个汉字，解出来看 bbox 是否落在格内、笔画是否完整：

```python
# 解 U+6C38 U+56FD U+4EBA，打印 ASCII 或存 PNG
```

---

## 9. 踩坑清单（按后果排序）

1. **tail 表置 0 或用了别的 gridH 的 tail** → 乱码 / 字形撕裂 / 字间碎片。必须同 gridH 原件复制，见 §4。
2. **cellW 按 `em+4` 或固定 44 推** → 正确公式是 `ceil((em+1)×2/8)×4`，三个样本只有这一条一路成立。
3. **把 cellW 当排版宽度** → 错。cellW 同为 48 的文件既有 12 字也有 10 字，见 §7.5 勘误。排版跟 `0x0a` 走。
4. **裁切起点用测试字集的并集边界** → 会切掉个别字的起笔。`PROBE` 并集左边界是 `3`，而「钧」从第 `0` 列就起笔，结果列 0/1/2 被切，正是金字旁的撇。**必须从第 0 列开始裁。**
5. **用重采样压缩字面宽度**（45 → 43） → 笔画整体变细 4.4%，偏旁看着缺肉。应该**裁切**（丢最右 2 px，笔画宽度不变），不要压缩，见 §7.6。
6. **裁切后把放置列写成 1** → 字整体右移 1 px，右边缘顶到排版权边界，字间变成零缝，相邻字边角粘成一片。裁切版放 `0`。
7. **字形按墨迹居中** → 整体偏左约 3 px，上一字的淡灰边缘压到下一字，见 §5.4。居中后右移 3 px。
8. **量化切点直接沿用官方 `64/128/192`** → 级别 2 实际只有 13% 亮度，抗锯齿边缘被放成实心暗点，看着像字缝里的脏点。必要时提到 `96/160/224`，见 §7.7。
9. **advance 全写死同一个数** → 字距与字形宽度解耦，出现挤字或灰缝。要用逐字 advance，见 §5.1。
10. **`0x2c` 写成"数据大小 + 4096"** → 应为 `字形数 × per`。
11. **用 FreeType 基线直接摆字形** → 和 `ImageDraw.text` 的结果差 1–2 px，和 `.bin` 时代输出对不上。
12. **把 `.bin` 的阈值 0.392 搬到 `.xtf`** → 4 级灰用 64/128/192。
13. **拿合成加粗（syn9/syn12/syn27）当原版** → 笔画被推方，4 级灰下放大成"不像这个字体"。用形状归一化 IoU 验证：同族 > 0.6，异族约 0.35。

**排查顺序建议**：灰点/碎片 → 先做连通域扫描（面积 ≤3、不含纯黑）。扫到就是量化（第 8 条），扫不到就是几何挤压（第 5、6 条）。字形缺笔 → 查裁切起点（第 4 条）。字小 → 先量字面面积，再量墨迹覆盖率，两者分开看。

---

## 10. 与 `.bin` 的关系

| | `.bin` | `.xtf` |
|---|---|---|
| 位深 | 1 bit | 2 bit |
| 头 | 无 | 64 B |
| 索引 | `codepoint × glyph_size` | 区间表 → `cum_index` |
| 槽数 | 65536 固定 | 实际字形数 |
| 抗锯齿 | 无（格式决定） | 有，`XTF_AA` 波形 |
| 每行字数 | `floor(528 / W) - 1` | `57 - 0x0a`（经验式） |

### 10.1 `.bin` 的每行字数

文件名里的 `W` 直接就是排版步进，规则实测为：

```
每行字数 = floor(528 / W) - 1
```

三个实测点全部吻合：

| W | `528/W` | 取整 | −1 | 实测 |
|---|---|---|---|---|
| 40 | 13.2 | 13 | **12** | 12 |
| 43 | 12.3 | 12 | **11** | 11 |
| 44 | 12.0 | 12 | **11** | 11 |

那个 `-1` 是固件预留的一个字宽边距。因此 `.bin` 要 12 字，`W` 必须 ≤ 40；`W = 40` 是最宽的解（41 就掉回 11 字），而且 40 是 8 的倍数，`stride = 5 字节 = 40 px`，一个 bit 都不浪费。

**这直接决定了 `.bin` 和 `.xtf` 的差距**：同样是 12 字，`.xtf` 每字能用到 43~44 px，`.bin` 只能用到 40 px，还两侧各留 24 px 空白。这就是"`.bin` 同一行字看起来更小、空隙更大"的根源。

### 10.2 两者的取舍

`.xtf` 是原生 2 bit，和帧缓冲位深一致，可以整块拷贝；`.bin` 要逐位展开成 2 bit 才能上屏。实测 `.xtf` 翻页更快，尽管单字读的字节更多——省下的是位展开循环，不是 IO。

---

## 11. 构建骨架：不需要完整官方字体

**结论先说**：生成 `.xtf` 只需要官方文件的**前 17,920 字节**，也就是 `0x0000..0x45FF`。那之后全是字形数据，而我们本来就要自己渲染覆盖。

```
0x0000..0x003F   64 B     header
0x0040..0x448F   17,488 B 区间表（1093 行 × 16 B）
0x4490..0x44EE   95 B     tail 表
0x44EF..0x45FF   padding  补零到 0x4600
────────────────────────────────────
合计 17,920 B  = 原文件的 0.16%
```

### 11.1 验证

用骨架替代 10.9 MB 的官方字体重新生成，输出与原来逐字节相同：

```
reference  hy46_汉仪跃晰褚楷12.xtf : 2E2E42D499206FFA7BE43917A22D033D2A4B828522B0CA482CE2024FFD04308B
skeleton   build                    : 2E2E42D499206FFA7BE43917A22D033D2A4B828522B0CA482CE2024FFD04308B
```

`SHA256` 一致，说明骨架携带的信息是充分的，完整官方字体里没有任何别的东西被用到。

### 11.2 现有的两个骨架

| 文件 | 来源 | gridH | 大小 |
|---|---|---|---|
| `fonts/skeleton/skel_g52.bin` | 官方 40pt | 52 | 17,920 B |
| `fonts/skeleton/skel_g59.bin` | 官方 46pt | 59 | 17,920 B |

生成器把 `TEMPLATE` 指向骨架即可，代码不需要任何改动——它本来只读 header、区间表和 tail。

### 11.3 tail 表的完整内容

95 字节。语义仍未确定（见 §7.8），但**内容可以原样内联，这样连骨架文件都不是必需的**。

`skel_g52.bin`（官方 40pt，gridH 52，总和 1782，取值 8..30）：

```
0e 0b 0d 18 14 1b 14 08 0c 0c 0e 16 0b 0f 09 10 15 13 15 14 14 13
13 13 13 13 0a 0b 12 13 12 12 17 17 1b 17 18 1b 18 18 1a 11 1c 19 12
1e 18 17 17 16 17 15 1a 16 15 1b 1a 18 15 0d 0f 0d 10 12 0a 12 10 10
12 0e 12 12 11 0a 14 11 0d 1e 15 0e 12 11 11 0f 10 14 0f 19 12 16 12
0d 09 0d 15
```

`skel_g59.bin`（官方 46pt，gridH 59，总和 2022，取值 9..34）：

```
10 0c 0f 1c 16 1f 16 09 0e 0e 10 19 0c 11 0a 12 17 16 17 16 17 16
16 16 16 16 0b 0d 15 15 15 14 1a 1a 1e 1a 1b 1e 1b 1b 1d 13 20 1c 14
22 1c 1a 1a 19 1a 18 1e 19 18 1f 1d 1b 18 0e 11 0f 12 15 0c 14 12 12
15 10 15 15 13 0c 16 14 0e 22 18 10 14 14 13 11 12 17 11 1c 14 1a 14
0f 0b 0e 18
```

两套总和之比 `2022 / 1782 = 1.135`，与 gridH 之比 `59 / 52 = 1.135` 相同，印证了 §4.2 的缩放关系。

### 11.4 区间表怎么办

区间表记录 `(起始码位, 连续个数, 累积字形索引)`，1093 行。它可以从字体的 `cmap` 重新生成：

```
取字体所有 Unicode 码位 → 排序 → 合并连续段 → 每段写 (first, count, cum_index)
```

本项目一直是从骨架整表复制，没有走过重新生成这条路。**如果哪天需要支持不同的字符集，才需要实现它**；只要字符集不变，抄骨架更省事也零风险。

### 11.5 提取骨架的方法

```python
raw = Path("官方字体.xtf").read_bytes()
Path("skel.bin").write_bytes(raw[:0x4600])     # 到 data_start 为止，含 padding
```

`data_start` 不一定是 `0x4600`，用公式算：`(toc_end + 0x1FF) & ~0x1FF`。本项目三个官方样本都落在 `0x4600`，因为区间表行数相同（1093）。

---

## 附录：参考实现

| 脚本 | 作用 |
|---|---|
| `_probe/x3fw/xtf_hy46crop43c.py` | **当前主力生成器**：em46 + 12 字 + 行高 60 + 裁切 43 px |
| `_probe/x3fw/binbuild.py` | `.bin` 生成器（1-bit，可指定 em/阈值/boost） |
| `_probe/x3fw/binfrombin2.py` | 把已有 `.bin` 重排到新的 W/H，可保持长宽比 |
| `_probe/x3fw/dump_xtf.py` | 打印 header 与 tail |
| `_probe/x3fw/cmp_40_46.py` | 两份官方样本逐字段对照 |
| `_probe/x3fw/edge_probe.py` | 量字形 bbox 与 advance 的关系 |
| `_probe/x3fw/bin_vs_xtf.py` | 解码 `.bin` 与 `.xtf` 逐像素比对 |
| `_probe/x3fw/xtf_identify.py` | 反查某 `.xtf` 用了哪个字体 |
| `_probe/x3fw/_speckscan.py` | 全字库扫描孤立碎点（量化问题诊断） |
| `_probe/x3fw/_breakcheck.py` | 压缩前后笔画连通块对比（判断压缩是否伤字） |
| `_probe/x3fw/xtf_skeleton.py` | 从官方字体提取 17.9 KB 构建骨架（见 §11） |

---

*结论全部经三份官方样本交叉验证；标"不可推算"的项没有跨字号公式，只有单点观测值。**完整官方字体已不再需要**——用 §11 的 17.9 KB 骨架即可重建，`SHA256` 已验证一致；tail 表的字节内容也已在 §11.3 内联，最极端情况下连骨架都不必保留。*
