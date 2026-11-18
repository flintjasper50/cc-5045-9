"""测试辅助：在临时工作区构造冻结场景。"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.make_demo_assets import make_demo  # noqa: E402


def setup_demo(root, **kwargs):
    demo = Path(root) / "scenes" / "demo"
    make_demo(demo, **kwargs)
    return demo


def rewrite_scene(demo_dir, mutate):
    p = Path(demo_dir) / "scene.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    mutate(doc)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return p
