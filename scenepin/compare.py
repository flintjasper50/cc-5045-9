"""真实像素核验：像素摘要与逐像素渲染差值。

比较输出时解码 PNG 得到像素，而不是比较版本字符串或 PNG 文件哈希；
PNG 字节受压缩库版本影响，像素摘要才是跨环境的稳定身份。
"""

import hashlib

from .pngio import decode_png


def pixel_sha256(img):
    h = hashlib.sha256()
    h.update(f"{img.width}x{img.height}x{img.channels}:".encode("ascii"))
    h.update(bytes(img.data))
    return h.hexdigest()


def pixel_sha256_of_png(data):
    return pixel_sha256(decode_png(data))


def render_delta(png_a, png_b):
    """逐像素比较两张 PNG，返回可核对的数量型证据。"""
    a = decode_png(png_a)
    b = decode_png(png_b)
    same_shape = (a.width == b.width and a.height == b.height
                  and a.channels == b.channels)
    width, height = min(a.width, b.width), min(a.height, b.height)
    channels = min(a.channels, b.channels)
    pixels_total = width * height
    pixels_differ = 0
    max_channel_delta = 0
    sum_channel_delta = 0
    if same_shape:
        da, db = a.data, b.data
        for i in range(0, width * height * channels, channels):
            diff = 0
            for c in range(channels):
                d = abs(da[i + c] - db[i + c])
                diff += d
                if d > max_channel_delta:
                    max_channel_delta = d
            if diff:
                pixels_differ += 1
                sum_channel_delta += diff
    else:
        pixels_differ = pixels_total
    return {
        "width": width,
        "height": height,
        "channels": channels,
        "same_shape": same_shape,
        "pixels_total": pixels_total,
        "pixels_differ": pixels_differ,
        "differ_ratio": (pixels_differ / pixels_total) if pixels_total else 0.0,
        "max_channel_delta": max_channel_delta,
        "sum_channel_delta": sum_channel_delta,
        "identical": same_shape and pixels_differ == 0,
    }
