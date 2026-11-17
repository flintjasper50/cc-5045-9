"""无界面验证：同一提交跨节点一致、源文件修改后已提交任务不变、
同名旧贴图不生效、缺失依赖在渲染前定位到引用来源、节点失败保留诊断。

用法: python3 tools/verify.py
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scenepin.errors import PinError  # noqa: E402
from scenepin.kernel import Kernel  # noqa: E402
from tools.make_demo_assets import make_demo, make_broken  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / ".verify"
CHECKER = "textures/checker.png"

PASS = []


def ok(msg):
    PASS.append(msg)
    print(f"  PASS  {msg}")


def main():
    if ROOT.exists():
        shutil.rmtree(ROOT)
    (ROOT / "scenes").mkdir(parents=True)
    make_demo(ROOT / "scenes" / "demo", palette="v1", rev_text="SCENEPIN REV 1")
    make_broken(ROOT / "scenes" / "broken")
    kernel = Kernel(ROOT)

    print("== 1. 固定 v1 并在两台节点出图（node-b 工作目录预置同名旧贴图）")
    rev1 = kernel.pin("scenes/demo/scene.json")["revision"]
    decoy = ROOT / "nodes" / "node-b" / "work" / CHECKER
    decoy.parent.mkdir(parents=True, exist_ok=True)
    decoy.write_bytes(b"DECOY: same file name, different content, must be ignored")
    r1 = kernel.render(rev1)
    h_a = r1["node-a"]["output"]["sha256"]
    h_b = r1["node-b"]["output"]["sha256"]
    assert r1["node-a"]["status"] == r1["node-b"]["status"] == "ok"
    assert h_a == h_b, "两节点输出哈希必须一致"
    ok(f"同一提交两节点输出一致 sha256={h_a[:16]}…（同名旧贴图未生效）")

    print("== 2. 修改源文件（换配色 + 文案），固定 v2")
    make_demo(ROOT / "scenes" / "demo", palette="v2", rev_text="SCENEPIN REV 2")
    rev2 = kernel.pin("scenes/demo/scene.json")["revision"]
    assert rev2 != rev1, "内容变化必须产生新修订"
    r2 = kernel.render(rev2)
    h2_a = r2["node-a"]["output"]["sha256"]
    h2_b = r2["node-b"]["output"]["sha256"]
    assert h2_a == h2_b and h2_a != h_a
    ok(f"v2 两节点一致 sha256={h2_a[:16]}… 且与 v1 不同")

    print("== 3. node-b 预置旧缓存：v2 的新纹理必须回源取数，未变资源命中缓存")
    fetch = {f["path"]: f["source"] for f in r2["node-b"]["fetch"]}
    assert fetch[CHECKER] == "fetched", fetch
    assert fetch["models/cube.obj"] == "cache-hit", fetch
    ok(f"node-b 旧缓存不顶用：{CHECKER}={fetch[CHECKER]}，cube.obj={fetch['models/cube.obj']}")

    print("== 4. 源文件已改，但已提交的 v1 仍保持原状态")
    r1b = kernel.render(rev1)
    assert r1b["node-a"]["output"]["sha256"] == h_a
    assert r1b["node-b"]["output"]["sha256"] == h_a
    fetch1 = {f["path"]: f["source"] for f in r1b["node-b"]["fetch"]}
    assert fetch1[CHECKER] == "cache-hit", fetch1
    ok(f"v1 重渲染输出不变 sha256={h_a[:16]}…（旧内容全部缓存命中）")

    print("== 5. 缺失依赖在渲染前定位到引用来源")
    try:
        kernel.pin("scenes/broken/scene.json")
        raise AssertionError("缺失依赖必须导致固定失败")
    except PinError as exc:
        chain = " → ".join(f"{c['file']}@{c['where']}" for c in exc.chain)
        assert "ghost.png" in exc.message and "wreck.mtl" in chain, (exc.message, chain)
        ok(f"固定被拒：{exc.message} ｜ 引用来源 {chain}")

    print("== 6. 中心存储缺 blob 时，节点失败并保留可诊断原因")
    blob = kernel.store.get_blob(next(a["sha256"] for a in kernel.manifest(rev2)["assets"]
                                      if a["path"] == CHECKER))
    h = next(a["sha256"] for a in kernel.manifest(rev2)["assets"] if a["path"] == CHECKER)
    (ROOT / "store" / "cas" / h[:2] / h).unlink()
    for nid in ("node-a", "node-b"):
        (ROOT / "nodes" / nid / "cache" / h).unlink(missing_ok=True)
    r6 = kernel.render(rev2, node_ids=["node-a"])
    assert r6["node-a"]["status"] == "error"
    detail = r6["node-a"]["error"]["detail"]
    assert detail["path"] == CHECKER and detail["sha256"] == h
    ok(f"node-a 失败原因可诊断：{r6['node-a']['error']['message']}")
    kernel.store.put_blob(blob)  # 恢复

    print(f"\n全部 {len(PASS)} 项验证通过。")


if __name__ == "__main__":
    main()
