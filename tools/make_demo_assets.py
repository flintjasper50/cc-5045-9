"""生成演示场景资产：纹理、字体图集、OBJ/MTL 模型、场景 JSON。

v1 / v2 两套配色用于演示“修改原文件后已提交任务仍保持原状态”。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scenepin.pngio import Image, encode_png  # noqa: E402

FONT_5X7 = {
    "A": [".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "B": ["####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."],
    "C": [".####", "#....", "#....", "#....", "#....", "#....", ".####"],
    "D": ["####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."],
    "E": ["#####", "#....", "#....", "####.", "#....", "#....", "#####"],
    "F": ["#####", "#....", "#....", "####.", "#....", "#....", "#...."],
    "G": [".####", "#....", "#....", "#.###", "#...#", "#...#", ".###."],
    "H": ["#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "I": ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "#####"],
    "J": ["..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."],
    "K": ["#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"],
    "L": ["#....", "#....", "#....", "#....", "#....", "#....", "#####"],
    "M": ["#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"],
    "N": ["#...#", "##..#", "##..#", "#.#.#", "#..##", "#..##", "#...#"],
    "O": [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "P": ["####.", "#...#", "#...#", "####.", "#....", "#....", "#...."],
    "Q": [".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"],
    "R": ["####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"],
    "S": [".####", "#....", "#....", ".###.", "....#", "....#", "####."],
    "T": ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."],
    "U": ["#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "V": ["#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."],
    "W": ["#...#", "#...#", "#...#", "#.#.#", "#.#.#", "##.##", "#...#"],
    "X": ["#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"],
    "Y": ["#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."],
    "Z": ["#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"],
    "0": [".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."],
    "1": ["..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."],
    "2": [".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"],
    "3": ["#####", "...#.", "..#..", "...#.", "....#", "#...#", ".###."],
    "4": ["...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."],
    "5": ["#####", "#....", "####.", "....#", "....#", "#...#", ".###."],
    "6": ["..##.", ".#...", "#....", "####.", "#...#", "#...#", ".###."],
    "7": ["#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."],
    "8": [".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."],
    "9": [".###.", "#...#", "#...#", ".####", "....#", "...#.", ".##.."],
    " ": [".....", ".....", ".....", ".....", ".....", ".....", "....."],
    ".": [".....", ".....", ".....", ".....", ".....", ".##..", ".##.."],
    "-": [".....", ".....", ".....", "#####", ".....", ".....", "....."],
    ":": [".....", ".##..", ".##..", ".....", ".##..", ".##..", "....."],
    "/": ["....#", "....#", "...#.", "..#..", ".#...", "#....", "#...."],
    "_": [".....", ".....", ".....", ".....", ".....", ".....", "#####"],
    "?": [".###.", "#...#", "....#", "...#.", "..#..", ".....", "..#.."],
}

PALETTES = {
    "v1": {"checker": ((232, 234, 238), (58, 64, 74)),
           "gradient": ((46, 102, 190), (120, 200, 235))},
    "v2": {"checker": ((240, 228, 200), (146, 64, 44)),
           "gradient": ((190, 90, 46), (250, 210, 120))},
}


def write_textures(tex_dir, palette):
    tex_dir.mkdir(parents=True, exist_ok=True)
    c1, c2 = PALETTES[palette]["checker"]
    img = Image(64, 64, 3)
    for y in range(64):
        for x in range(64):
            img.set_rgb(x, y, *(c1 if (x // 8 + y // 8) % 2 == 0 else c2))
    (tex_dir / "checker.png").write_bytes(encode_png(img))
    g1, g2 = PALETTES[palette]["gradient"]
    img = Image(64, 64, 3)
    for y in range(64):
        t = y / 63.0
        row = [int(g1[i] + (g2[i] - g1[i]) * t) for i in range(3)]
        for x in range(64):
            img.set_rgb(x, y, *row)
    (tex_dir / "gradient.png").write_bytes(encode_png(img))


def write_font(font_dir):
    font_dir.mkdir(parents=True, exist_ok=True)
    chars = sorted(FONT_5X7)
    cols, cw, ch = 16, 8, 10
    rows = (len(chars) + cols - 1) // cols
    atlas = Image(cols * cw, rows * ch, 4)
    glyphs = {}
    for idx, c in enumerate(chars):
        gx, gy = (idx % cols) * cw + 1, (idx // cols) * ch + 1
        for j, row in enumerate(FONT_5X7[c]):
            for i, bit in enumerate(row):
                if bit == "#":
                    p = ((gy + j) * atlas.width + gx + i) * 4
                    atlas.data[p:p + 4] = b"\xff\xff\xff\xff"
        glyphs[c] = {"x": gx, "y": gy, "w": 5, "h": 7, "advance": 6}
    (font_dir / "ui_atlas.png").write_bytes(encode_png(atlas))
    font = {"format": "scenepin.font/1", "atlas": "ui_atlas.png",
            "line_height": 9, "glyphs": glyphs}
    (font_dir / "ui.font.json").write_text(json.dumps(font, ensure_ascii=False), encoding="utf-8")


CUBE_OBJ = """# 单位立方体（边长 1.2，中心在原点）
mtllib cube.mtl
usemtl cube_mat
v -0.6 -0.6 -0.6
v  0.6 -0.6 -0.6
v  0.6  0.6 -0.6
v -0.6  0.6 -0.6
v -0.6 -0.6  0.6
v  0.6 -0.6  0.6
v  0.6  0.6  0.6
v -0.6  0.6  0.6
vt 0 0
vt 1 0
vt 1 1
vt 0 1
f 1/1 2/2 3/3
f 1/1 3/3 4/4
f 6/1 5/2 8/3
f 6/1 8/3 7/4
f 2/1 6/2 7/3
f 2/1 7/3 3/4
f 5/1 1/2 4/3
f 5/1 4/3 8/4
f 4/1 3/2 7/3
f 4/1 7/3 8/4
f 5/1 6/2 2/3
f 5/1 2/3 1/4
"""

PYRAMID_OBJ = """# 四棱锥（底面 y=0，顶点 y=1.4）
mtllib pyramid.mtl
usemtl pyramid_mat
v -0.7 0.0 -0.7
v  0.7 0.0 -0.7
v  0.7 0.0  0.7
v -0.7 0.0  0.7
v  0.0 1.4  0.0
vt 0 0
vt 1 0
vt 1 1
vt 0 1
vt 0.5 0.5
f 1/1 4/4 3/3
f 1/1 3/3 2/2
f 1/1 2/2 5/5
f 2/1 3/2 5/5
f 3/1 4/2 5/5
f 4/1 1/2 5/5
"""

GROUND_OBJ = """# 地面（y=0，8x8，纹理平铺 4x4）
mtllib ground.mtl
usemtl ground_mat
v -4 0 -4
v  4 0 -4
v  4 0  4
v -4 0  4
vt 0 0
vt 4 0
vt 4 4
vt 0 4
f 1/1 2/2 3/3
f 1/1 3/3 4/4
"""

MTLS = {
    "cube.mtl": "newmtl cube_mat\nKd 1.0 1.0 1.0\nmap_Kd ../textures/checker.png\n",
    "pyramid.mtl": "newmtl pyramid_mat\nKd 1.0 1.0 1.0\nmap_Kd ../textures/gradient.png\n",
    "ground.mtl": "newmtl ground_mat\nKd 0.9 0.9 0.95\nmap_Kd ../textures/checker.png\n",
}

MODELS = {"cube.obj": CUBE_OBJ, "pyramid.obj": PYRAMID_OBJ, "ground.obj": GROUND_OBJ}


def write_models(model_dir):
    model_dir.mkdir(parents=True, exist_ok=True)
    for name, text in {**MODELS, **MTLS}.items():
        (model_dir / name).write_text(text, encoding="utf-8")


def write_scene(scene_dir, rev_text, time_ms=0.0, plugins=None):
    scene = {
        "format": "scenepin.scene/1",
        "name": "demo",
        "render": {"width": 400, "height": 300, "background": "#18202e",
                   "light": [0.5, 1.0, 0.35]},
        "camera": {"position": [3.4, 2.6, 4.4], "look_at": [0, 0.35, 0], "fov": 45},
        "animation": {"time_ms": time_ms, "fps": 24},
        "models": [
            {"path": "models/ground.obj", "position": [0, 0, 0], "scale": 1.0},
            {"path": "models/cube.obj", "position": [0.9, 0.6, 0.2], "scale": 1.0,
             "spin": 90.0},
            {"path": "models/pyramid.obj", "position": [-1.5, 0, -0.6], "scale": 1.0},
        ],
        "overlays": [
            {"text": rev_text, "font": "fonts/ui.font.json",
             "position": [12, 12], "size": 14, "color": "#ffd166"},
        ],
    }
    if plugins:
        scene["plugins"] = plugins
    (scene_dir / "scene.json").write_text(
        json.dumps(scene, ensure_ascii=False, indent=1), encoding="utf-8")


def make_demo(demo_dir, palette="v1", rev_text="SCENEPIN REV 1", time_ms=0.0, plugins=None):
    demo_dir = Path(demo_dir)
    write_textures(demo_dir / "textures", palette)
    write_font(demo_dir / "fonts")
    write_models(demo_dir / "models")
    write_scene(demo_dir, rev_text, time_ms=time_ms, plugins=plugins)


def make_broken(root):
    """缺失间接依赖的场景：scene → wreck.obj → wreck.mtl → ghost.png（不存在）。"""
    d = Path(root) / "models"
    d.mkdir(parents=True, exist_ok=True)
    (d / "wreck.obj").write_text(
        "mtllib wreck.mtl\nusemtl wreck_mat\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n",
        encoding="utf-8")
    (d / "wreck.mtl").write_text(
        "newmtl wreck_mat\nKd 1 0 0\nmap_Kd ../textures/ghost.png\n", encoding="utf-8")
    scene = {"format": "scenepin.scene/1", "name": "broken",
             "render": {"width": 64, "height": 64, "background": "#000000",
                        "light": [0, 1, 0]},
             "camera": {"position": [0, 0, 3], "look_at": [0, 0, 0], "fov": 45},
             "models": [{"path": "models/wreck.obj"}],
             "overlays": []}
    (Path(root) / "scene.json").write_text(json.dumps(scene), encoding="utf-8")


def make_broken_url(root):
    """含外部 URL 引用的场景：应按拒绝策略在固定期被拒。"""
    d = Path(root)
    d.mkdir(parents=True, exist_ok=True)
    scene = {"format": "scenepin.scene/1", "name": "broken-url",
             "render": {"width": 64, "height": 64, "background": "#000000",
                        "light": [0, 1, 0]},
             "camera": {"position": [0, 0, 3], "look_at": [0, 0, 0], "fov": 45},
             "models": [{"path": "https://assets.example.invalid/cube.obj"}],
             "overlays": []}
    (d / "scene.json").write_text(json.dumps(scene), encoding="utf-8")


def main():
    root = Path(__file__).resolve().parents[1] / "scenes"
    make_demo(root / "demo", palette="v1", rev_text="SCENEPIN REV 1")
    make_broken(root / "broken")
    make_broken_url(root / "broken_url")
    print(f"演示资产已生成于 {root}")


if __name__ == "__main__":
    main()
