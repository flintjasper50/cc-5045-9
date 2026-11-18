"""独立参照实现（仅供测试使用，故意不导入 scenepin 的实现）。

期望值必须独立推导，不能复用被测代码：
  - 场景指纹：按公开规格独立规范化并取 sha256
  - 像素摘要：独立解码 PNG、独立拼接像素字节
  - 渲染差值：独立逐像素比较

这些函数是“参照物”，与被测实现共享的只有规格本身。
"""

import hashlib
import json
import struct
import zlib


# ---------------------------------------------------------------- 指纹

def _canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def fingerprint(entry, assets, settings):
    deps = [a for a in assets if a["role"] != "scene"]
    rows = sorted(
        ({"path": a["path"], "role": a["role"], "sha256": a["sha256"], "size": a["size"]}
         for a in deps),
        key=lambda a: a["path"])
    body = {"format": "scenepin.fingerprint/1", "entry": entry,
            "assets": rows, "settings": settings}
    return hashlib.sha256(_canonical(body)).hexdigest()


def normalize_settings(doc):
    """按场景格式规格独立规范化，用于推导期望指纹。"""
    r = doc.get("render") or {}
    c = doc.get("camera") or {}
    settings = {
        "name": doc.get("name") or "scene",
        "render": {
            "width": r["width"],
            "height": r["height"],
            "background": (r.get("background", "#000000")).lower(),
            "light": [float(v) for v in r.get("light", [0.5, 1.0, 0.35])],
        },
        "camera": {
            "position": [float(v) for v in c["position"]],
            "look_at": [float(v) for v in c["look_at"]],
            "fov": float(c.get("fov", 45)),
        },
        "models": [{
            "path": m["path"],
            "position": [float(v) for v in m.get("position", [0, 0, 0])],
            "scale": float(m.get("scale", 1.0)),
            "spin": float(m.get("spin", 0.0)),
        } for m in doc["models"]],
        "overlays": [{
            "text": o["text"],
            "font": o["font"],
            "position": [float(v) for v in o.get("position", [0, 0])],
            "size": float(o.get("size", 12)),
            "color": (o.get("color", "#ffffff")).lower(),
        } for o in doc.get("overlays") or []],
        "animation": {
            "time_ms": float((doc.get("animation") or {}).get("time_ms", 0.0)),
            "fps": float((doc.get("animation") or {}).get("fps", 24)),
        },
        "plugins": {
            "exposure": {"gain": float(((doc.get("plugins") or {}).get("exposure") or {})
                                       .get("gain", 1.0))},
            "vignette": {"strength": float(((doc.get("plugins") or {}).get("vignette") or {})
                                           .get("strength", 0.0))},
            "tint": {"color": (((doc.get("plugins") or {}).get("tint") or {})
                               .get("color", "#ffffff")).lower(),
                     "amount": float(((doc.get("plugins") or {}).get("tint") or {})
                                     .get("amount", 0.0))},
        },
    }
    return settings


# ---------------------------------------------------------------- PNG 解码

def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def decode_png(data):
    """独立的最小 PNG 解码器：8 位非隔行，返回 (w, h, channels, bytes)。"""
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    pos = 8
    idat = b""
    width = height = bitdepth = ctype = interlace = None
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        tag = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            width, height, bitdepth, ctype, _c, _f, interlace = struct.unpack(
                ">IIBBBBB", payload)
        elif tag == b"IDAT":
            idat += payload
        elif tag == b"IEND":
            break
    assert bitdepth == 8 and interlace == 0, "unsupported PNG variant"
    ch = {0: 1, 2: 3, 4: 2, 6: 4}[ctype]
    raw = zlib.decompress(idat)
    stride = width * ch
    out = bytearray()
    prev = bytearray(stride)
    p = 0
    for _y in range(height):
        f = raw[p]
        p += 1
        line = bytearray(raw[p:p + stride])
        p += stride
        if f == 1:
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 0xFF
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif f == 3:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif f == 4:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                c = prev[i - ch] if i >= ch else 0
                line[i] = (line[i] + _paeth(a, prev[i], c)) & 0xFF
        else:
            assert f == 0, f"unknown filter {f}"
        out += line
        prev = line
    if ch == 1:
        rgb = bytearray()
        for g in out:
            rgb += bytes((g, g, g))
        return width, height, 3, bytes(rgb)
    if ch == 2:
        rgba = bytearray()
        for i in range(0, len(out), 2):
            g, a = out[i], out[i + 1]
            rgba += bytes((g, g, g, a))
        return width, height, 4, bytes(rgba)
    return width, height, ch, bytes(out)


def pixel_sha256(png_bytes):
    w, h, ch, pixels = decode_png(png_bytes)
    hh = hashlib.sha256()
    hh.update(f"{w}x{h}x{ch}:".encode("ascii"))
    hh.update(pixels)
    return hh.hexdigest()


def render_delta(png_a, png_b):
    wa, ha, ca, pa = decode_png(png_a)
    wb, hb, cb, pb = decode_png(png_b)
    same_shape = (wa, ha, ca) == (wb, hb, cb)
    total = min(wa, wb) * min(ha, hb)
    channels = min(ca, cb)
    differ = 0
    max_delta = 0
    sum_delta = 0
    if same_shape:
        for i in range(0, total * channels, channels):
            d = 0
            for c in range(channels):
                dd = abs(pa[i + c] - pb[i + c])
                d += dd
                max_delta = max(max_delta, dd)
            if d:
                differ += 1
                sum_delta += d
    else:
        differ = total
    return {"width": min(wa, wb), "height": min(ha, hb), "channels": channels,
            "same_shape": same_shape, "pixels_total": total,
            "pixels_differ": differ,
            "differ_ratio": (differ / total) if total else 0.0,
            "max_channel_delta": max_delta, "sum_channel_delta": sum_delta,
            "identical": same_shape and differ == 0}
