"""纯标准库 PNG 编解码（8 位、非隔行）。

读取支持灰度/RGB/灰度+Alpha/RGBA，统一规整为 RGB 或 RGBA。
其它变体（16 位、隔行、调色板）按拒绝策略报错。
"""

import struct
import zlib

from .errors import PinError

SIG = b"\x89PNG\r\n\x1a\n"


class Image:
    __slots__ = ("width", "height", "channels", "data")

    def __init__(self, width, height, channels, data=None):
        self.width = width
        self.height = height
        self.channels = channels
        self.data = data if data is not None else bytearray(width * height * channels)

    def set_rgb(self, x, y, r, g, b):
        i = (y * self.width + x) * self.channels
        self.data[i] = r
        self.data[i + 1] = g
        self.data[i + 2] = b

    def texel(self, x, y):
        i = (y * self.width + x) * self.channels
        return self.data[i:i + self.channels]


def _chunk(tag, payload):
    return (struct.pack(">I", len(payload)) + tag + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))


def encode_png(img):
    ctype = {3: 2, 4: 6}[img.channels]
    ihdr = struct.pack(">IIBBBBB", img.width, img.height, 8, ctype, 0, 0, 0)
    stride = img.width * img.channels
    raw = bytearray()
    for y in range(img.height):
        raw.append(0)
        raw += img.data[y * stride:(y + 1) * stride]
    return SIG + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + _chunk(b"IEND", b"")


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def decode_png(data, where=""):
    def fail(msg):
        raise PinError(msg, [{"file": where, "where": "PNG 解码"}])

    if data[:8] != SIG:
        fail("不是有效的 PNG 文件")
    pos = 8
    idat = bytearray()
    width = height = bitdepth = ctype = interlace = None
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        tag = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            width, height, bitdepth, ctype, _comp, _filt, interlace = struct.unpack(">IIBBBBB", payload)
        elif tag == b"IDAT":
            idat += payload
        elif tag == b"IEND":
            break
    if width is None:
        fail("PNG 缺少 IHDR")
    if bitdepth != 8:
        fail(f"不支持的 PNG 位深 {bitdepth}（仅支持 8 位）")
    if interlace != 0:
        fail("不支持隔行扫描 PNG")
    src_ch = {0: 1, 2: 3, 4: 2, 6: 4}.get(ctype)
    if src_ch is None:
        fail(f"不支持的 PNG 颜色类型 {ctype}（调色板等变体被拒绝）")
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as exc:
        fail(f"PNG 数据解压失败: {exc}")
    stride = width * src_ch
    img = Image(width, height, src_ch)
    prev = bytearray(stride)
    p = 0
    for y in range(height):
        f = raw[p]
        p += 1
        line = bytearray(raw[p:p + stride])
        p += stride
        if f == 1:
            for i in range(src_ch, stride):
                line[i] = (line[i] + line[i - src_ch]) & 0xFF
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif f == 3:
            for i in range(stride):
                a = line[i - src_ch] if i >= src_ch else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif f == 4:
            for i in range(stride):
                a = line[i - src_ch] if i >= src_ch else 0
                c = prev[i - src_ch] if i >= src_ch else 0
                line[i] = (line[i] + _paeth(a, prev[i], c)) & 0xFF
        elif f != 0:
            fail(f"未知 PNG 过滤器 {f}")
        img.data[y * stride:(y + 1) * stride] = line
        prev = line
    if src_ch == 1:  # 灰度 → RGB
        out = Image(width, height, 3)
        for i in range(width * height):
            g = img.data[i]
            out.data[i * 3:i * 3 + 3] = bytes((g, g, g))
        return out
    if src_ch == 2:  # 灰度+Alpha → RGBA
        out = Image(width, height, 4)
        for i in range(width * height):
            g, a = img.data[i * 2], img.data[i * 2 + 1]
            out.data[i * 4:i * 4 + 4] = bytes((g, g, g, a))
        return out
    return img
