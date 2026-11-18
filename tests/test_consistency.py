"""求值一致性测试：场景指纹、动画时刻、插件参数、跨工作站渲染差值。

期望值全部由 tests/reference.py 独立推导（独立解码 PNG、独立规范化设置、
独立计算指纹），不复用 scenepin 的实现，也不比对版本字符串。

运行:
  python3 -m unittest discover -s tests -v
  python3 tests/test_consistency.py          # 等价入口
"""

import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import reference  # noqa: E402  (tests/ 在 sys.path 中）
from support import rewrite_scene, setup_demo  # noqa: E402

from scenepin import faults  # noqa: E402
from scenepin.compare import render_delta as impl_delta  # noqa: E402
from scenepin.errors import PinError  # noqa: E402
from scenepin.kernel import Kernel  # noqa: E402


@contextmanager
def sandbox(**demo_kwargs):
    tmp = tempfile.mkdtemp(prefix="scenepin-consistency-")
    root = Path(tmp)
    (root / "scenes").mkdir(parents=True)
    setup_demo(root, **demo_kwargs)
    try:
        yield root, Path(root) / "scenes" / "demo"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


@contextmanager
def fault(name):
    with mock.patch.dict(os.environ, {"SCENEPIN_FAULT": name}):
        yield


def scene_doc(demo_dir):
    return json.loads((Path(demo_dir) / "scene.json").read_text(encoding="utf-8"))


def expected_fingerprint(demo_dir, manifest):
    """从磁盘场景 + 清单依赖内容独立推导指纹（不复用 scenepin.fingerprint）。"""
    demo_dir = Path(demo_dir)
    doc = scene_doc(demo_dir)
    settings = reference.normalize_settings(doc)
    # 规范化设置里，模型/字体被改写为解析后的逻辑路径
    for i, m in enumerate(settings["models"]):
        m["path"] = manifest["settings"]["models"][i]["path"]
    for i, o in enumerate(settings["overlays"]):
        o["font"] = manifest["settings"]["overlays"][i]["font"]
    assets = []
    for a in manifest["assets"]:
        data = (demo_dir / a["path"]).read_bytes()
        import hashlib
        sha = hashlib.sha256(data).hexdigest()
        assets.append({"path": a["path"], "role": a["role"],
                       "sha256": sha, "size": len(data)})
    return reference.fingerprint(manifest["entry"], assets, settings)


class TestReferenceIsIndependent(unittest.TestCase):
    """参照实现必须真正独立地在字节层面工作。"""

    def test_reference_decodes_render_without_scenepin_decoder(self):
        with sandbox() as (root, demo):
            k = Kernel(root)
            rev = k.pin("scenes/demo/scene.json")["revision"]
            res = k.render(rev)["node-a"]
            png = Path(res["output"]["file"]).read_bytes()
            w, h, ch, pixels = reference.decode_png(png)
            self.assertEqual((w, h, ch), (400, 300, 3))
            self.assertEqual(len(pixels), w * h * ch)


class TestFingerprint(unittest.TestCase):
    def test_fingerprint_matches_independent_reference(self):
        with sandbox() as (root, demo):
            k = Kernel(root)
            rev = k.pin("scenes/demo/scene.json")["revision"]
            m = k.manifest(rev)
            self.assertEqual(m["fingerprint"], expected_fingerprint(demo, m))

    def test_fingerprint_not_derived_from_revision_string(self):
        with sandbox() as (root, _demo):
            k = Kernel(root)
            rev = k.pin("scenes/demo/scene.json")["revision"]
            m = k.manifest(rev)
            # 指纹是内容摘要，与修订 id 不应相等（不同规范化维度）
            self.assertNotEqual(m["fingerprint"], rev)

    def test_fingerprint_stable_across_workstations(self):
        with sandbox() as (root, demo):
            k = Kernel(root)
            rev = k.pin("scenes/demo/scene.json")["revision"]
            k.render(rev)
            a, b = k.result(rev, "node-a"), k.result(rev, "node-b")
            self.assertEqual(a["fingerprint"], b["fingerprint"])
            self.assertEqual(a["fingerprint"], expected_fingerprint(demo, k.manifest(rev)))

    def test_same_name_different_content_changes_fingerprint(self):
        with sandbox() as (root, demo):
            k = Kernel(root)
            rev1 = k.pin("scenes/demo/scene.json")["revision"]
            fp1 = k.manifest(rev1)["fingerprint"]
            # 只替换 textures/checker.png 的内容，路径完全不变
            setup_demo(root, palette="v2", rev_text="SCENEPIN REV 1")
            # 恢复同文案，仅纹理不同，保证除资源内容外其余一致
            rewrite_scene(demo, lambda d: None)
            rev2 = k.pin("scenes/demo/scene.json")["revision"]
            fp2 = k.manifest(rev2)["fingerprint"]
            self.assertNotEqual(fp1, fp2, "同名换件必须改变场景指纹")
            self.assertEqual(fp2, expected_fingerprint(demo, k.manifest(rev2)))

    def test_animation_and_plugins_feed_fingerprint(self):
        with sandbox() as (root, demo):
            k = Kernel(root)
            rev1 = k.pin("scenes/demo/scene.json")["revision"]
            fp1 = k.manifest(rev1)["fingerprint"]
            rewrite_scene(demo, lambda d: d.update(
                animation={"time_ms": 500.0, "fps": 24}))
            rev2 = k.pin("scenes/demo/scene.json")["revision"]
            fp2 = k.manifest(rev2)["fingerprint"]
            self.assertNotEqual(fp1, fp2)
            rewrite_scene(demo, lambda d: d.update(plugins={"exposure": {"gain": 1.5}}))
            rev3 = k.pin("scenes/demo/scene.json")["revision"]
            fp3 = k.manifest(rev3)["fingerprint"]
            self.assertNotEqual(fp2, fp3)
            self.assertEqual(fp3, expected_fingerprint(demo, k.manifest(rev3)))

    def test_default_config_resolved_into_manifest(self):
        with sandbox() as (root, demo):
            # 场景显式给出参数
            rewrite_scene(demo, lambda d: d.update(
                animation={"time_ms": 750.0, "fps": 30},
                plugins={"exposure": {"gain": 1.25}, "vignette": {"strength": 0.4}}))
            k = Kernel(root)
            rev = k.pin("scenes/demo/scene.json")["revision"]
            m = k.manifest(rev)
            self.assertEqual(m["settings"]["animation"], {"time_ms": 750.0, "fps": 30.0})
            self.assertEqual(m["settings"]["plugins"]["exposure"]["gain"], 1.25)
            self.assertEqual(m["settings"]["plugins"]["vignette"]["strength"], 0.4)
            # 未给出的插件参数补默认值，而不是留空
            self.assertEqual(m["settings"]["plugins"]["tint"],
                             {"color": "#ffffff", "amount": 0.0})


class TestRenderDelta(unittest.TestCase):
    def test_delta_zero_for_same_revision_across_workstations(self):
        with sandbox() as (root, _demo):
            k = Kernel(root)
            rev = k.pin("scenes/demo/scene.json")["revision"]
            k.render(rev)
            pa = Path(k.result(rev, "node-a")["output"]["file"]).read_bytes()
            pb = Path(k.result(rev, "node-b")["output"]["file"]).read_bytes()
            impl = impl_delta(pa, pb)
            ref = reference.render_delta(pa, pb)
            self.assertTrue(impl["identical"])
            self.assertEqual(impl["pixels_differ"], 0)
            self.assertEqual(impl, ref)

    def test_delta_matches_reference_on_known_difference(self):
        with sandbox() as (root, demo):
            k = Kernel(root)
            rev = k.pin("scenes/demo/scene.json")["revision"]
            png_v1 = Path(k.render(rev)["node-a"]["output"]["file"]).read_bytes()
            setup_demo(root, palette="v2", rev_text="SCENEPIN REV 2")
            rev2 = k.pin("scenes/demo/scene.json")["revision"]
            png_v2 = Path(k.render(rev2)["node-a"]["output"]["file"]).read_bytes()
            impl = impl_delta(png_v1, png_v2)
            ref = reference.render_delta(png_v1, png_v2)
            self.assertEqual(impl, ref)
            self.assertFalse(impl["identical"])
            self.assertGreater(impl["pixels_differ"], 0)
            self.assertEqual(impl["pixels_total"], 400 * 300)

    def test_pixel_digest_matches_reference(self):
        with sandbox() as (root, _demo):
            k = Kernel(root)
            rev = k.pin("scenes/demo/scene.json")["revision"]
            res = k.render(rev)["node-a"]
            png = Path(res["output"]["file"]).read_bytes()
            self.assertEqual(res["output"]["pixel_sha256"], reference.pixel_sha256(png))


class TestAnimationAndPluginsAffectPixels(unittest.TestCase):
    def _render_png(self, root, demo):
        k = Kernel(root)
        rev = k.pin("scenes/demo/scene.json")["revision"]
        res = k.render(rev)["node-a"]
        self.assertEqual(res["status"], "ok", res.get("error"))
        self.assertEqual(res["used"]["animation"],
                         k.manifest(rev)["settings"]["animation"])
        return Path(res["output"]["file"]).read_bytes(), k.manifest(rev)

    def test_animation_time_changes_pixels(self):
        with sandbox() as (root, demo):
            base, _ = self._render_png(root, demo)
            rewrite_scene(demo, lambda d: d.update(
                animation={"time_ms": 1000.0, "fps": 24}))
            moved, m = self._render_png(root, demo)
            self.assertEqual(m["settings"]["animation"]["time_ms"], 1000.0)
            delta = reference.render_delta(base, moved)
            self.assertFalse(delta["identical"], "动画时刻必须影响画面")
            self.assertGreater(delta["pixels_differ"], 0)

    def test_plugin_params_change_pixels(self):
        with sandbox() as (root, demo):
            base, _ = self._render_png(root, demo)
            rewrite_scene(demo, lambda d: d.update(
                plugins={"exposure": {"gain": 1.8}}))
            brighter, m = self._render_png(root, demo)
            self.assertEqual(m["settings"]["plugins"]["exposure"]["gain"], 1.8)
            delta = reference.render_delta(base, brighter)
            self.assertFalse(delta["identical"], "插件参数必须影响画面")

    def test_explicit_defaults_equal_implicit_defaults(self):
        """显式写出默认值必须与缺省完全等价（不得以默认值遮错）。"""
        with sandbox() as (root, demo):
            implicit, m1 = self._render_png(root, demo)
            rewrite_scene(demo, lambda d: d.update(
                animation={"time_ms": 0.0, "fps": 24},
                plugins={"exposure": {"gain": 1.0}, "vignette": {"strength": 0.0},
                         "tint": {"color": "#ffffff", "amount": 0.0}}))
            explicit, m2 = self._render_png(root, demo)
            self.assertEqual(m1["fingerprint"], m2["fingerprint"])
            self.assertTrue(reference.render_delta(implicit, explicit)["identical"])


class TestControlledFaultsAreCaught(unittest.TestCase):
    """对场景固定引入受控错误，断言测试能暴露坏结果。"""

    def test_swap_asset_fault_breaks_fingerprint_and_pixels(self):
        with sandbox() as (root, demo):
            k = Kernel(root)
            rev = k.pin("scenes/demo/scene.json")["revision"]
            clean = k.render(rev)
            clean_fp = k.manifest(rev)["fingerprint"]
            clean_png = Path(clean["node-a"]["output"]["file"]).read_bytes()
            # 在 node-b 工作目录放同名旧贴图（有效 PNG，但内容不同），
            # 并用注入让固定期错误地把路径名当资源身份
            decoy = root / "nodes" / "node-b" / "work" / "textures" / "checker.png"
            decoy.parent.mkdir(parents=True, exist_ok=True)
            from scenepin.pngio import Image, encode_png
            img = Image(64, 64, 3)
            img.data[:] = bytes((200, 30, 30)) * (64 * 64)
            decoy.write_bytes(encode_png(img))
            with fault("swap-asset"):
                rev_bad = k.pin("scenes/demo/scene.json")["revision"]
                bad = k.render(rev_bad)
            self.assertEqual(bad["node-a"]["status"], "ok", bad.get("error"))
            self.assertNotEqual(k.manifest(rev_bad)["fingerprint"], clean_fp,
                                "同名换件必须改变场景指纹")
            bad_png = Path(bad["node-a"]["output"]["file"]).read_bytes()
            self.assertFalse(reference.render_delta(clean_png, bad_png)["identical"],
                             "同名换件必须改变渲染像素")

    def test_default_config_fault_ignores_scene_params(self):
        with sandbox() as (root, demo):
            rewrite_scene(demo, lambda d: d.update(
                animation={"time_ms": 900.0, "fps": 24},
                plugins={"exposure": {"gain": 2.0}}))
            k = Kernel(root)
            with fault("default-config"):
                rev_bad = k.pin("scenes/demo/scene.json")["revision"]
                bad = k.render(rev_bad)
            m = k.manifest(rev_bad)
            self.assertEqual(m["settings"]["animation"]["time_ms"], 0.0,
                             "注入应抹掉场景动画时刻")
            self.assertEqual(m["settings"]["plugins"]["exposure"]["gain"], 1.0)
            # 正常固定同场景应得到不同指纹与不同像素
            rev_ok = k.pin("scenes/demo/scene.json")["revision"]
            ok = k.render(rev_ok)
            self.assertNotEqual(m["fingerprint"], k.manifest(rev_ok)["fingerprint"])
            self.assertFalse(reference.render_delta(
                Path(bad["node-a"]["output"]["file"]).read_bytes(),
                Path(ok["node-a"]["output"]["file"]).read_bytes())["identical"],
                "忽略参数必须造成渲染差值")

    def test_zero_time_fault_changes_pixels_only(self):
        with sandbox() as (root, demo):
            rewrite_scene(demo, lambda d: d.update(
                animation={"time_ms": 1500.0, "fps": 24}))
            k = Kernel(root)
            rev = k.pin("scenes/demo/scene.json")["revision"]
            normal = k.render(rev)
            normal_png = Path(normal["node-a"]["output"]["file"]).read_bytes()
            with fault("zero-time"):
                zeroed = k.render(rev)
            zeroed_png = Path(zeroed["node-a"]["output"]["file"]).read_bytes()
            # 指纹相同（清单未变），但像素必须不同——不能只比版本字符串
            self.assertEqual(normal["node-a"]["fingerprint"],
                             zeroed["node-a"]["fingerprint"])
            self.assertNotEqual(normal["node-a"]["output"]["pixel_sha256"],
                                zeroed["node-a"]["output"]["pixel_sha256"])
            delta = reference.render_delta(normal_png, zeroed_png)
            self.assertGreater(delta["pixels_differ"], 0)

    def test_no_verify_fault_accepts_corrupt_cache(self):
        with sandbox() as (root, _demo):
            k = Kernel(root)
            rev = k.pin("scenes/demo/scene.json")["revision"]
            normal = k.render(rev)  # 填充缓存
            self.assertEqual(normal["node-a"]["status"], "ok", normal["node-a"].get("error"))
            manifest = k.manifest(rev)
            idx = next(i for i, a in enumerate(manifest["assets"])
                       if a["path"] == "textures/checker.png")
            checker = manifest["assets"][idx]
            cache = root / "nodes" / "node-a" / "cache" / checker["sha256"]

            # 用“合法 PNG、错误内容”污染缓存：跳过校验时画面会被悄悄换掉
            from scenepin.pngio import Image, encode_png
            img = Image(64, 64, 3)
            img.data[:] = bytes((10, 250, 10)) * (64 * 64)
            poisoned = encode_png(img)
            cache.write_bytes(poisoned)

            refetch = k.render(rev, node_ids=["node-a"])
            self.assertEqual(refetch["node-a"]["status"], "ok")
            self.assertEqual(refetch["node-a"]["assets"][idx]["source"],
                             "cache-corrupt-refetch")
            self.assertEqual(refetch["node-a"]["output"]["pixel_sha256"],
                             normal["node-a"]["output"]["pixel_sha256"],
                             "正常路径应回源并得到原像素")
            normal_png = Path(refetch["node-a"]["output"]["file"]).read_bytes()

            cache.write_bytes(poisoned)
            with fault("no-verify"):
                bad = k.render(rev, node_ids=["node-a"])
            self.assertEqual(bad["node-a"]["status"], "ok")
            self.assertEqual(bad["node-a"]["assets"][idx]["source"], "cache-hit")
            self.assertNotEqual(bad["node-a"]["assets"][idx]["actual"], checker["sha256"],
                                "记录中实际摘要仍与期望不符")
            bad_png = Path(bad["node-a"]["output"]["file"]).read_bytes()
            delta = reference.render_delta(normal_png, bad_png)
            self.assertGreater(delta["pixels_differ"], 0,
                               "跳过校验必须以真实像素差值暴露")

    def test_omit_digest_fault_breaks_fingerprint_identity(self):
        with sandbox() as (root, demo):
            k = Kernel(root)
            fp_v1 = k.pin("scenes/demo/scene.json").__getitem__("fingerprint")
            with fault("omit-asset-digest"):
                fp_omitted = k.pin("scenes/demo/scene.json")["fingerprint"]
            self.assertNotEqual(fp_v1, fp_omitted,
                                "忽略内容摘要的指纹与正常指纹必须不同")
            # 同名换件在忽略摘要时指纹不再变化（正是坏行为）
            setup_demo(root, palette="v2", rev_text="SCENEPIN REV 1")
            with fault("omit-asset-digest"):
                fp_swapped = k.pin("scenes/demo/scene.json")["fingerprint"]
            self.assertEqual(fp_omitted, fp_swapped,
                             "该注入应无法识别同名换件，测试据此判定实现缺陷")


class TestCrossWorkstation(unittest.TestCase):
    def test_compare_reports_consistent_when_identical(self):
        with sandbox() as (root, _demo):
            k = Kernel(root)
            rev = k.pin("scenes/demo/scene.json")["revision"]
            k.render(rev)
            cmp = k.compare(rev)
            self.assertTrue(cmp["consistent"], cmp["problems"])
            self.assertEqual(len(cmp["fingerprints"]), 2)
            self.assertEqual(len(set(cmp["pixel_sha256"].values())), 1)

    def test_compare_flags_missing_evidence_not_default(self):
        with sandbox() as (root, _demo):
            k = Kernel(root)
            rev = k.pin("scenes/demo/scene.json")["revision"]
            k.render(rev)
            # 抹掉 node-b 的像素摘要，模拟坏结果；不得被当作一致
            k.results[rev]["node-b"]["output"].pop("pixel_sha256")
            cmp = k.compare(rev)
            self.assertFalse(cmp["consistent"])
            self.assertTrue(any("像素" in p for p in cmp["problems"]))


class TestSceneParameterValidation(unittest.TestCase):
    def test_unknown_plugin_rejected(self):
        with sandbox() as (root, demo):
            rewrite_scene(demo, lambda d: d.update(plugins={"bloom": {"radius": 1}}))
            with self.assertRaises(PinError) as ctx:
                Kernel(root).pin("scenes/demo/scene.json")
            self.assertIn("bloom", ctx.exception.message)

    def test_out_of_range_plugin_rejected(self):
        with sandbox() as (root, demo):
            rewrite_scene(demo, lambda d: d.update(
                plugins={"vignette": {"strength": 5.0}}))
            with self.assertRaises(PinError):
                Kernel(root).pin("scenes/demo/scene.json")

    def test_negative_animation_time_rejected(self):
        with sandbox() as (root, demo):
            rewrite_scene(demo, lambda d: d.update(
                animation={"time_ms": -1.0, "fps": 24}))
            with self.assertRaises(PinError):
                Kernel(root).pin("scenes/demo/scene.json")

    def test_unknown_plugin_param_rejected(self):
        with sandbox() as (root, demo):
            rewrite_scene(demo, lambda d: d.update(
                plugins={"exposure": {"gain": 1.0, "curve": 2.0}}))
            with self.assertRaises(PinError):
                Kernel(root).pin("scenes/demo/scene.json")


class TestUnchangedBehaviour(unittest.TestCase):
    """改动范围内不得破坏原有固定/出图语义。"""

    def test_same_content_reuses_revision_and_render(self):
        with sandbox() as (root, _demo):
            k = Kernel(root)
            p1 = k.pin("scenes/demo/scene.json")
            p2 = k.pin("scenes/demo/scene.json")
            self.assertEqual(p1["revision"], p2["revision"])
            self.assertFalse(p2["created_new"])
            self.assertEqual(p1["fingerprint"], p2["fingerprint"])

    def test_source_edit_does_not_change_pinned_revision_pixels(self):
        with sandbox() as (root, demo):
            k = Kernel(root)
            rev = k.pin("scenes/demo/scene.json")["revision"]
            before = Path(k.render(rev)["node-a"]["output"]["file"]).read_bytes()
            setup_demo(root, palette="v2", rev_text="SCENEPIN REV 9")
            after = Path(k.render(rev)["node-a"]["output"]["file"]).read_bytes()
            self.assertTrue(reference.render_delta(before, after)["identical"],
                            "源文件改动不得影响已固定修订")

    def test_fault_default_is_noop(self):
        self.assertEqual(faults.active(), "")
        self.assertFalse(faults.enabled("swap-asset"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
