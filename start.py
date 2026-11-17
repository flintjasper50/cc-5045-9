#!/usr/bin/env python3
"""演示入口：初始化演示资产与两台模拟工作站，启动出图任务面板。

  python3 start.py [--port 8471] [--reset]

初始化内容（幂等，--reset 可重来）：
  - 生成 scenes/demo（v1 状态）、scenes/broken、scenes/broken_url
  - 固定 v1 并在 node-a/node-b 各渲染一次 → node-b 留下“旧缓存”
  - 在 node-b 工作目录放置同名旧贴图诱饵（不会被当作资源）
  - 修改源文件（换配色 + 文案）后固定 v2 并渲染
"""

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from scenepin.kernel import Kernel  # noqa: E402
from scenepin.server import serve  # noqa: E402
from tools.make_demo_assets import main as gen_assets, make_demo  # noqa: E402


def init_demo():
    scenes = ROOT / "scenes"
    if not (scenes / "demo" / "scene.json").exists():
        gen_assets()
    kernel = Kernel(ROOT)
    if kernel.store.list_revisions():
        return kernel
    rev1 = kernel.pin("scenes/demo/scene.json")["revision"]
    kernel.render(rev1)  # 两台节点各渲染一次 → node-b 获得 v1 旧缓存
    decoy = ROOT / "nodes" / "node-b" / "work" / "textures" / "checker.png"
    decoy.parent.mkdir(parents=True, exist_ok=True)
    decoy.write_bytes(b"DECOY: stale same-name texture, must never be used")
    make_demo(scenes / "demo", palette="v2", rev_text="SCENEPIN REV 2")  # 修改原文件
    rev2 = kernel.pin("scenes/demo/scene.json")["revision"]
    kernel.render(rev2)
    print(f"已固定两个修订: v1={rev1[:12]} v2={rev2[:12]}（node-b 预置 v1 旧缓存与同名诱饵）")
    return kernel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8471)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--reset", action="store_true", help="清空 store/nodes/scenes 后重新初始化")
    args = ap.parse_args()
    if args.reset:
        for d in ("store", "nodes", "scenes", ".verify"):
            shutil.rmtree(ROOT / d, ignore_errors=True)
    kernel = init_demo()
    serve(kernel, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
