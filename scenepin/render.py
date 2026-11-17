"""确定性软件光栅渲染器：仅通过清单加载器取数，输出真实 PNG 像素。

渲染期再次执行加载路径约束：任何不在任务清单内的路径都会被加载器拒绝，
保证节点只使用清单钉死的内容（闭合依赖集）。
"""

import math
import posixpath

from .pngio import Image, decode_png, encode_png
from .scenefile import parse_font, parse_mtl, parse_obj, resolve_ref


def _hexrgb(s):
    return (int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16))


def _norm(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) or 1.0
    return (v[0] / n, v[1] / n, v[2] / n)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


class _Camera:
    def __init__(self, cfg, width, height):
        fwd = _norm([cfg["look_at"][i] - cfg["position"][i] for i in range(3)])
        right = _norm(_cross(fwd, (0.0, 1.0, 0.0)))
        up = _cross(right, fwd)
        self.pos = cfg["position"]
        self.right, self.up, self.fwd = right, up, fwd
        self.tan_half = math.tan(math.radians(cfg["fov"]) * 0.5)
        self.aspect = width / height
        self.w, self.h = width, height

    def project(self, p):
        d = (p[0] - self.pos[0], p[1] - self.pos[1], p[2] - self.pos[2])
        z = _dot(d, self.fwd)
        if z < 0.05:
            return None
        x = _dot(d, self.right) / (z * self.tan_half * self.aspect)
        y = _dot(d, self.up) / (z * self.tan_half)
        return ((x * 0.5 + 0.5) * self.w, (0.5 - y * 0.5) * self.h, z)


def _sample(tex, u, v):
    u -= math.floor(u)
    v -= math.floor(v)
    x = min(tex.width - 1, int(u * tex.width))
    y = min(tex.height - 1, int((1.0 - v) * tex.height))  # OBJ vt 原点在左下
    t = tex.texel(x, y)
    return t[0], t[1], t[2]


def _draw_tri(img, zbuf, p0, p1, p2, uv0, uv1, uv2, kd, tex, intensity):
    (x0, y0, z0), (x1, y1, z1), (x2, y2, z2) = p0, p1, p2
    den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
    if den == 0:
        return
    minx = max(0, int(math.floor(min(x0, x1, x2))))
    maxx = min(img.width - 1, int(math.ceil(max(x0, x1, x2))))
    miny = max(0, int(math.floor(min(y0, y1, y2))))
    maxy = min(img.height - 1, int(math.ceil(max(y0, y1, y2))))
    if minx > maxx or miny > maxy:
        return
    kr, kg, kb = kd
    data, w = img.data, img.width
    iz0, iz1, iz2 = 1.0 / z0, 1.0 / z1, 1.0 / z2
    for y in range(miny, maxy + 1):
        for x in range(minx, maxx + 1):
            w0 = ((y1 - y2) * (x - x2) + (x2 - x1) * (y - y2)) / den
            w1 = ((y2 - y0) * (x - x2) + (x0 - x2) * (y - y2)) / den
            w2 = 1.0 - w0 - w1
            if w0 < 0 or w1 < 0 or w2 < 0:
                continue
            iz = w0 * iz0 + w1 * iz1 + w2 * iz2
            if iz <= 0:
                continue
            z = 1.0 / iz
            idx = y * w + x
            if z >= zbuf[idx]:
                continue
            if tex is not None and uv0 is not None:
                u = (w0 * uv0[0] * iz0 + w1 * uv1[0] * iz1 + w2 * uv2[0] * iz2) * z
                v = (w0 * uv0[1] * iz0 + w1 * uv1[1] * iz1 + w2 * uv2[1] * iz2) * z
                tr, tg, tb = _sample(tex, u, v)
                r = tr * kr
                g = tg * kg
                b = tb * kb
            else:
                r, g, b = kr * 255.0, kg * 255.0, kb * 255.0
            zbuf[idx] = z
            i3 = idx * 3
            data[i3] = min(255, int(r * intensity))
            data[i3 + 1] = min(255, int(g * intensity))
            data[i3 + 2] = min(255, int(b * intensity))


def _render_model(load_blob, model, img, zbuf, cam, light):
    obj = parse_obj(load_blob(model["path"]).decode("utf-8"), model["path"])
    obj_dir = posixpath.dirname(model["path"])
    mats = {}
    for ref, line in obj["mtllibs"]:
        mtl_log = resolve_ref(obj_dir, ref, model["path"], f"line {line}")
        mtl = parse_mtl(load_blob(mtl_log).decode("utf-8"), mtl_log)
        mtl_dir = posixpath.dirname(mtl_log)
        for name, mat in mtl["materials"].items():
            tex = None
            if mat["map_kd"]:
                tex_log = resolve_ref(mtl_dir, mat["map_kd"][0], mtl_log, f"line {mat['map_kd'][1]}")
                tex = decode_png(load_blob(tex_log), tex_log)
            mats[name] = (mat["kd"], tex)
    s = model.get("scale", 1.0)
    t = model.get("position", [0.0, 0.0, 0.0])
    verts = [((v[0] * s) + t[0], (v[1] * s) + t[1], (v[2] * s) + t[2]) for v in obj["verts"]]
    uvs = obj["uvs"]
    for a, b, c, mat_name in obj["tris"]:
        pa = cam.project(verts[a[0] - 1])
        pb = cam.project(verts[b[0] - 1])
        pc = cam.project(verts[c[0] - 1])
        if pa is None or pb is None or pc is None:
            continue
        kd, tex = mats.get(mat_name, ((0.8, 0.8, 0.8), None))
        n = _norm(_cross(
            [verts[b[0] - 1][i] - verts[a[0] - 1][i] for i in range(3)],
            [verts[c[0] - 1][i] - verts[a[0] - 1][i] for i in range(3)]))
        intensity = 0.25 + 0.75 * abs(_dot(n, light))
        uv = lambda tok: uvs[tok[1] - 1] if tok[1] else None  # noqa: E731
        _draw_tri(img, zbuf, pa, pb, pc, uv(a), uv(b), uv(c), kd, tex, intensity)


def _render_overlay(load_blob, ov, img):
    font = parse_font(load_blob(ov["font"]).decode("utf-8"), ov["font"])
    atlas_log = resolve_ref(posixpath.dirname(ov["font"]), font["atlas"], ov["font"], "atlas")
    atlas = decode_png(load_blob(atlas_log), atlas_log)
    if atlas.channels != 4:
        from .errors import PinError
        raise PinError("字体图集须为 RGBA PNG", [{"file": atlas_log, "where": "atlas"}])
    scale = ov["size"] / font["line_height"]
    r, g, b = _hexrgb(ov["color"])
    cx = ov["position"][0]
    cy = ov["position"][1]
    glyphs = font["glyphs"]
    for ch in ov["text"]:
        gl = glyphs.get(ch) or glyphs.get(ch.upper()) or glyphs.get("?")
        if gl is None:
            cx += font["line_height"] * 0.5 * scale
            continue
        for j in range(int(gl["h"])):
            for i in range(int(gl["w"])):
                ai = ((int(gl["y"]) + j) * atlas.width + int(gl["x"]) + i) * 4
                if atlas.data[ai + 3] <= 127:
                    continue
                x0 = int(cx + i * scale)
                y0 = int(cy + j * scale)
                x1 = int(cx + (i + 1) * scale)
                y1 = int(cy + (j + 1) * scale)
                for yy in range(max(0, y0), min(img.height, y1)):
                    for xx in range(max(0, x0), min(img.width, x1)):
                        img.set_rgb(xx, yy, r, g, b)
        cx += gl["advance"] * scale


def render_scene(manifest, load_blob):
    """按清单设置出图，返回 PNG 字节。全程确定性，同清单必得同像素。"""
    st = manifest["settings"]
    r = st["render"]
    w, h = r["width"], r["height"]
    img = Image(w, h, 3)
    img.data[:] = bytes(_hexrgb(r["background"])) * (w * h)
    zbuf = [float("inf")] * (w * h)
    light = _norm(r["light"])
    cam = _Camera(st["camera"], w, h)
    for model in st["models"]:
        _render_model(load_blob, model, img, zbuf, cam, light)
    for ov in st.get("overlays", []):
        _render_overlay(load_blob, ov, img)
    return encode_png(img)
