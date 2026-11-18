#!/usr/bin/env python3
"""求值一致性自动验收入口（命令行，辅助图形入口）。

做两件事：
  1. 运行 tests/ 下的全部一致性测试；
  2. 现场固定一次演示场景，用独立参照实现核对场景指纹与渲染差值，
     输出可直接对账的执行证据（可选 --evidence 落盘 JSON）。

用法:
  python3 tools/acceptance.py
  python3 tools/acceptance.py --evidence /tmp/scenepin-evidence.json
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import reference  # noqa: E402  独立参照实现
from scenepin.compare import render_delta  # noqa: E402
from scenepin.kernel import Kernel  # noqa: E402
from tools.make_demo_assets import make_demo  # noqa: E402


def run_tests():
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "tests"],
        cwd=ROOT, capture_output=True, text=True)
    sys.stdout.write(proc.stderr)
    return proc.returncode == 0


def gather_evidence(time_ms=800.0, plugins=None):
    """在临时工作区固定并出图，指纹/像素/差值均与独立参照核对。"""
    root = Path(tempfile.mkdtemp(prefix="scenepin-acceptance-"))
    try:
        (root / "scenes").mkdir(parents=True)
        demo = root / "scenes" / "demo"
        make_demo(demo, palette="v2", rev_text="SCENEPIN REV ACCEPT",
                  time_ms=time_ms, plugins=plugins)
        k = Kernel(root)
        pinned = k.pin("scenes/demo/scene.json")
        rev = pinned["revision"]
        results = k.render(rev)
        m = k.manifest(rev)

        for nid, res in results.items():
            assert res["status"] == "ok", (nid, res.get("error"))
        png_a = Path(results["node-a"]["output"]["file"]).read_bytes()
        png_b = Path(results["node-b"]["output"]["file"]).read_bytes()

        ref_fp = reference.fingerprint(m["entry"], m["assets"], m["settings"])
        assert pinned["fingerprint"] == ref_fp == results["node-a"]["fingerprint"] \
            == results["node-b"]["fingerprint"], "场景指纹与独立参照不一致"

        ref_px_a = reference.pixel_sha256(png_a)
        assert results["node-a"]["output"]["pixel_sha256"] == ref_px_a, "像素摘要与独立参照不一致"

        impl_delta = render_delta(png_a, png_b)
        ref_delta = reference.render_delta(png_a, png_b)
        assert impl_delta == ref_delta, "渲染差值与独立参照不一致"
        assert impl_delta["identical"], "同一清单两节点像素必须一致"

        # 同一场景写入默认配置不应改变指纹（正向用例）
        make_demo(demo, palette="v2", rev_text="SCENEPIN REV ACCEPT",
                  time_ms=0.0, plugins=None)
        rev_zero = k.pin("scenes/demo/scene.json")["revision"]
        assert k.manifest(rev_zero)["fingerprint"] != pinned["fingerprint"], \
            "动画时刻不同必须改变指纹"

        return {
            "revision": rev,
            "fingerprint": pinned["fingerprint"],
            "reference_fingerprint": ref_fp,
            "animation": m["settings"]["animation"],
            "plugins": m["settings"]["plugins"],
            "nodes": {nid: {"pixel_sha256": r["output"]["pixel_sha256"],
                            "pixel_sha256_reference": reference.pixel_sha256(
                                Path(r["output"]["file"]).read_bytes())}
                      for nid, r in results.items()},
            "delta_a_b": impl_delta,
            "delta_a_b_reference": ref_delta,
            "consistent": k.compare(rev)["consistent"],
            "asset_digests": [{"path": a["path"], "sha256": a["sha256"]}
                              for a in m["assets"]],
        }
    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", help="将执行证据写入该 JSON 路径")
    ap.add_argument("--skip-tests", action="store_true")
    args = ap.parse_args()

    ok = True
    if not args.skip_tests:
        print("== 运行一致性测试")
        ok = run_tests() and ok

    print("\n== 现场核对场景指纹与渲染差值（独立参照）")
    evidence = gather_evidence()
    print(f"  修订       {evidence['revision'][:16]}…")
    print(f"  场景指纹   {evidence['fingerprint'][:16]}…（与参照一致）")
    print(f"  资源摘要   {len(evidence['asset_digests'])} 项")
    print(f"  动画/插件  {evidence['animation']} ｜ {evidence['plugins']}")
    for nid, v in evidence["nodes"].items():
        print(f"  {nid} 像素 {v['pixel_sha256'][:16]}…（与参照一致）")
    d = evidence["delta_a_b"]
    print(f"  渲染差值   {d['pixels_differ']}/{d['pixels_total']} 像素不同，"
          f"最大通道差 {d['max_channel_delta']}")
    print(f"  跨节点一致 {'是' if evidence['consistent'] else '否'}")

    if args.evidence:
        Path(args.evidence).write_text(
            json.dumps(evidence, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n  执行证据已写入 {args.evidence}")

    if not ok:
        print("\n验收失败：测试未全部通过。")
        return 1
    print("\n验收通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
