"""场景格式解析、加载路径约束与依赖闭包解析。

受支持格式（白名单，其余一律拒绝）：
  场景  *.json        format == "scenepin.scene/1"
  模型  *.obj         子集 v/vt/vn/f/usemtl/mtllib/o/g/s，仅正索引，f 按扇形三角化
  材质  *.mtl         子集 newmtl/Kd/map_Kd（map_Kd 不带选项参数）
  纹理  *.png         8 位非隔行：灰度/RGB/灰度+Alpha/RGBA
  字体  *.font.json   format == "scenepin.font/1"，atlas 为 PNG 图集

加载路径约束与拒绝策略（固定期强制，渲染期由清单加载器二次强制）：
  - 仅允许相对场景根目录的 POSIX 相对路径；
  - 拒绝绝对路径、盘符路径、越出场景根的 ".."；
  - 拒绝一切 URL（http/https/file/ftp/data 等）——节点不得临时访问网络资源；
  - 拒绝白名单外的扩展名；
  - 渲染期只允许打开清单内路径，保证闭合依赖集。
"""

import json
import posixpath

from .errors import PinError

SCENE_FORMAT = "scenepin.scene/1"
FONT_FORMAT = "scenepin.font/1"

ROLE_EXTS = {
    "scene": (".json",),
    "model": (".obj",),
    "material": (".mtl",),
    "texture": (".png",),
    "font": (".font.json",),
    "font-atlas": (".png",),
}

POLICY = {
    "formats": {
        "scene": ["*.json (scenepin.scene/1)"],
        "model": ["*.obj (v/vt/vn/f/usemtl/mtllib，正索引)"],
        "material": ["*.mtl (newmtl/Kd/map_Kd)"],
        "texture": ["*.png (8 位非隔行)"],
        "font": ["*.font.json (scenepin.font/1) + PNG 图集"],
    },
    "reject": [
        "绝对路径 / 盘符路径",
        "越出场景根目录的 .. 引用",
        "任何 URL（http/https/file/ftp/data…），节点不得访问网络资源",
        "白名单外扩展名",
        "渲染期打开清单外路径（闭合依赖集约束）",
        "OBJ 负索引、带选项参数的 map_Kd、16 位/隔行/调色板 PNG",
    ],
}


def _ref(file, where):
    return {"file": file, "where": where}


def _ext_of(path):
    if path.endswith(".font.json"):
        return ".font.json"
    return posixpath.splitext(path)[1].lower()


def check_role_ext(logical, role, referrer, where):
    ext = _ext_of(logical)
    if ext not in ROLE_EXTS[role]:
        raise PinError(
            f"拒绝引用 {logical!r}：{role} 资源只允许 {ROLE_EXTS[role]}，实际为 {ext or '(无扩展名)'}",
            [_ref(referrer, where)])


def resolve_ref(referrer_dir, raw, referrer, where):
    """把 referrer 中的字符串引用解析为场景根下的规范逻辑路径；违规即拒绝。"""
    if not isinstance(raw, str) or not raw.strip():
        raise PinError("空引用路径", [_ref(referrer, where)])
    p = raw.replace("\\", "/")
    low = p.lower()
    if "://" in p or low.startswith(("http:", "https:", "file:", "ftp:", "data:")):
        raise PinError(
            f"拒绝外部 URL 引用 {raw!r}：节点不得临时访问网络资源，避免画面漂移",
            [_ref(referrer, where)])
    if p.startswith("/") or (len(p) > 1 and p[1] == ":"):
        raise PinError(f"拒绝绝对路径引用 {raw!r}", [_ref(referrer, where)])
    if "\x00" in p:
        raise PinError("引用含非法字符", [_ref(referrer, where)])
    joined = posixpath.normpath(posixpath.join(referrer_dir, p)) if referrer_dir else posixpath.normpath(p)
    if joined == ".." or joined.startswith("../"):
        raise PinError(f"引用 {raw!r} 越出场景根目录", [_ref(referrer, where)])
    return joined


# ---------------------------------------------------------------- OBJ / MTL

def parse_obj(text, logical):
    vs, vts, mtllibs, tris = [], [], [], []
    cur_mat = None

    def face_token(tok, n):
        parts = tok.split("/")
        try:
            vi = int(parts[0])
            ti = int(parts[1]) if len(parts) > 1 and parts[1] else None
        except ValueError:
            raise PinError(f"OBJ 面片索引无法解析: {tok!r}", [_ref(logical, f"line {n}")])
        if vi <= 0 or (ti is not None and ti <= 0):
            raise PinError(f"不支持 OBJ 负/零索引: {tok!r}（仅支持正索引）", [_ref(logical, f"line {n}")])
        return (vi, ti)

    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        op = parts[0]
        try:
            if op == "v":
                if len(parts) != 4:
                    raise ValueError
                vs.append((float(parts[1]), float(parts[2]), float(parts[3])))
            elif op == "vt":
                if len(parts) < 3:
                    raise ValueError
                vts.append((float(parts[1]), float(parts[2])))
            elif op == "vn":
                continue  # 法线自行按面计算
            elif op == "mtllib":
                if len(parts) != 2:
                    raise PinError("mtllib 需为单个相对路径", [_ref(logical, f"line {n}")])
                mtllibs.append((parts[1], n))
            elif op == "usemtl":
                if len(parts) != 2:
                    raise ValueError
                cur_mat = parts[1]
            elif op == "f":
                idx = [face_token(t, n) for t in parts[1:]]
                if len(idx) < 3:
                    raise PinError("面片顶点数不足", [_ref(logical, f"line {n}")])
                for k in range(1, len(idx) - 1):
                    tris.append((idx[0], idx[k], idx[k + 1], cur_mat))
            elif op in ("o", "g", "s"):
                continue
            # 其余语句忽略（mtllib/usemtl 之外不影响几何与依赖）
        except ValueError:
            raise PinError(f"OBJ 语句无法解析: {line!r}", [_ref(logical, f"line {n}")])
    for tri in tris:
        for vi, ti in tri[:3]:
            if vi > len(vs):
                raise PinError(f"OBJ 顶点索引越界: {vi} > {len(vs)}", [_ref(logical, "f")])
            if ti is not None and ti > len(vts):
                raise PinError(f"OBJ 纹理坐标索引越界: {ti} > {len(vts)}", [_ref(logical, "f")])
    return {"mtllibs": mtllibs, "verts": vs, "uvs": vts, "tris": tris}


def parse_mtl(text, logical):
    materials = {}
    cur = None
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        op = parts[0]
        if op == "newmtl":
            if len(parts) != 2:
                raise PinError("newmtl 需为单个材质名", [_ref(logical, f"line {n}")])
            cur = {"kd": (0.8, 0.8, 0.8), "map_kd": None}
            materials[parts[1]] = cur
        elif op == "Kd":
            if cur is None or len(parts) != 4:
                raise PinError("Kd 需跟随 newmtl 且为 3 个分量", [_ref(logical, f"line {n}")])
            try:
                cur["kd"] = (float(parts[1]), float(parts[2]), float(parts[3]))
            except ValueError:
                raise PinError(f"Kd 分量无法解析: {line!r}", [_ref(logical, f"line {n}")])
        elif op == "map_Kd":
            if cur is None:
                raise PinError("map_Kd 需跟随 newmtl", [_ref(logical, f"line {n}")])
            if len(parts) != 2:
                raise PinError("不支持带选项参数的 map_Kd，仅接受单个相对路径",
                               [_ref(logical, f"line {n}")])
            cur["map_kd"] = (parts[1], n)
        # Ka/Ks/Ke/Ns/d/Tr/illum 等忽略
    return {"materials": materials}


def parse_font(text, logical):
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PinError(f"字体文件 JSON 解析失败: {exc}", [_ref(logical, "font")])
    if doc.get("format") != FONT_FORMAT:
        raise PinError(f"字体 format 须为 {FONT_FORMAT!r}", [_ref(logical, "format")])
    atlas = doc.get("atlas")
    glyphs = doc.get("glyphs")
    lh = doc.get("line_height")
    if not isinstance(atlas, str) or not atlas:
        raise PinError("字体缺少 atlas 字段", [_ref(logical, "atlas")])
    if not isinstance(glyphs, dict) or not glyphs:
        raise PinError("字体缺少 glyphs 表", [_ref(logical, "glyphs")])
    if not isinstance(lh, (int, float)) or lh <= 0:
        raise PinError("字体 line_height 非法", [_ref(logical, "line_height")])
    for ch, g in glyphs.items():
        if not all(isinstance(g.get(k), (int, float)) for k in ("x", "y", "w", "h", "advance")):
            raise PinError(f"字形 {ch!r} 字段不完整", [_ref(logical, f"glyphs.{ch}")])
    return {"atlas": atlas, "glyphs": glyphs, "line_height": lh}


# ---------------------------------------------------------------- 场景 JSON

def _color(value, entry, where):
    if (not isinstance(value, str) or len(value) != 7 or not value.startswith("#")):
        raise PinError(f"颜色须为 #rrggbb: {value!r}", [_ref(entry, where)])
    try:
        int(value[1:], 16)
    except ValueError:
        raise PinError(f"颜色须为 #rrggbb: {value!r}", [_ref(entry, where)])
    return value.lower()


def _vec(value, n, entry, where):
    if (not isinstance(value, list) or len(value) != n
            or not all(isinstance(v, (int, float)) for v in value)):
        raise PinError(f"须为 {n} 维数值向量: {value!r}", [_ref(entry, where)])
    return [float(v) for v in value]


def parse_scene(text, entry):
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PinError(f"场景 JSON 解析失败: {exc}", [_ref(entry, "scene")])
    if doc.get("format") != SCENE_FORMAT:
        raise PinError(f"场景 format 须为 {SCENE_FORMAT!r}", [_ref(entry, "format")])
    r = doc.get("render") or {}
    w, h = r.get("width"), r.get("height")
    if not (isinstance(w, int) and isinstance(h, int) and 8 <= w <= 1024 and 8 <= h <= 1024):
        raise PinError("render.width/height 须为 8..1024 的整数", [_ref(entry, "render")])
    light = _vec(r.get("light", [0.5, 1.0, 0.35]), 3, entry, "render.light")
    render = {"width": w, "height": h,
              "background": _color(r.get("background", "#000000"), entry, "render.background"),
              "light": light}
    c = doc.get("camera") or {}
    camera = {"position": _vec(c.get("position"), 3, entry, "camera.position"),
              "look_at": _vec(c.get("look_at"), 3, entry, "camera.look_at"),
              "fov": float(c.get("fov", 45))}
    if not (1.0 < camera["fov"] < 179.0):
        raise PinError("camera.fov 须在 (1,179) 区间", [_ref(entry, "camera.fov")])
    models = []
    for i, m in enumerate(doc.get("models") or []):
        where = f"models[{i}]"
        if not isinstance(m, dict) or "path" not in m:
            raise PinError("模型项缺少 path", [_ref(entry, where)])
        models.append({"path": m["path"],
                       "position": _vec(m.get("position", [0, 0, 0]), 3, entry, where + ".position"),
                       "scale": float(m.get("scale", 1.0))})
    if not models:
        raise PinError("场景至少需要一个模型", [_ref(entry, "models")])
    overlays = []
    for i, o in enumerate(doc.get("overlays") or []):
        where = f"overlays[{i}]"
        if not isinstance(o, dict) or not isinstance(o.get("text"), str) or "font" not in o:
            raise PinError("叠加文字项需含 text 与 font", [_ref(entry, where)])
        overlays.append({"text": o["text"], "font": o["font"],
                         "position": _vec(o.get("position", [0, 0]), 2, entry, where + ".position"),
                         "size": float(o.get("size", 12)),
                         "color": _color(o.get("color", "#ffffff"), entry, where + ".color")})
    return {"name": doc.get("name") or "scene", "render": render, "camera": camera,
            "models": models, "overlays": overlays}


# ---------------------------------------------------------------- 依赖闭包

class SceneBundle:
    def __init__(self, root, entry, settings, deps):
        self.root = root          # 场景根目录（磁盘绝对路径）
        self.entry = entry        # 场景入口逻辑路径
        self.settings = settings  # 规范化后的渲染设置
        self.deps = deps          # 有序 dict: 逻辑路径 -> 角色


def resolve_scene(scene_path):
    """从场景入口出发解析全部外部引用，返回闭合依赖集合。

    任何缺失/违规引用都在此抛出 PinError，并携带引用来源链（文件 + 行号/JSON 指针），
    保证缺失依赖在渲染前被定位到引用来源。
    """
    scene_path = scene_path.resolve()
    root = scene_path.parent
    entry = scene_path.name
    deps = {}

    def add(logical, role):
        check_role_ext(logical, role, entry, "依赖收集")
        if logical not in deps:
            if not (root / logical).is_file():
                raise PinError(f"依赖缺失: {logical!r} 在场景根目录下不存在",
                               list(pending_chain) or [_ref(entry, "依赖收集")])
            deps[logical] = role

    pending_chain = []  # 当前引用来源（供缺失报错定位）

    if not scene_path.is_file():
        raise PinError(f"场景入口不存在: {entry}", [_ref(entry, "pin")])
    deps[entry] = "scene"
    settings = parse_scene(scene_path.read_text(encoding="utf-8"), entry)

    for i, m in enumerate(settings["models"]):
        where = f"models[{i}].path"
        obj_log = resolve_ref("", m["path"], entry, where)
        check_role_ext(obj_log, "model", entry, where)
        pending_chain = [_ref(entry, where)]
        add(obj_log, "model")
        m["path"] = obj_log
        obj = parse_obj((root / obj_log).read_text(encoding="utf-8"), obj_log)
        obj_dir = posixpath.dirname(obj_log)
        for mtl_ref, line in obj["mtllibs"]:
            mtl_log = resolve_ref(obj_dir, mtl_ref, obj_log, f"line {line}")
            check_role_ext(mtl_log, "material", obj_log, f"line {line}")
            pending_chain = [_ref(obj_log, f"line {line} (mtllib)")]
            add(mtl_log, "material")
            mtl = parse_mtl((root / mtl_log).read_text(encoding="utf-8"), mtl_log)
            mtl_dir = posixpath.dirname(mtl_log)
            for mat in mtl["materials"].values():
                if mat["map_kd"]:
                    tex_ref, tline = mat["map_kd"]
                    tex_log = resolve_ref(mtl_dir, tex_ref, mtl_log, f"line {tline}")
                    check_role_ext(tex_log, "texture", mtl_log, f"line {tline}")
                    pending_chain = [_ref(mtl_log, f"line {tline} (map_Kd)")]
                    add(tex_log, "texture")

    for i, o in enumerate(settings["overlays"]):
        where = f"overlays[{i}].font"
        font_log = resolve_ref("", o["font"], entry, where)
        check_role_ext(font_log, "font", entry, where)
        pending_chain = [_ref(entry, where)]
        add(font_log, "font")
        o["font"] = font_log
        font = parse_font((root / font_log).read_text(encoding="utf-8"), font_log)
        font_dir = posixpath.dirname(font_log)
        atlas_log = resolve_ref(font_dir, font["atlas"], font_log, "atlas")
        check_role_ext(atlas_log, "font-atlas", font_log, "atlas")
        pending_chain = [_ref(font_log, "atlas")]
        add(atlas_log, "font-atlas")

    return SceneBundle(root, entry, settings, deps)
