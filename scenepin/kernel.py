"""场景固定内核：固定场景为不可变清单、驱动节点出图、沉淀结果与失败。"""

import json
from datetime import datetime, timezone
from pathlib import Path

from . import faults, fingerprint
from .errors import PinError
from .node import Node
from .scenefile import ANIMATION_DEFAULTS, PLUGIN_DEFAULTS, POLICY, resolve_scene
from .store import Store


class Kernel:
    def __init__(self, root):
        self.root = Path(root)
        self.store = Store(self.root / "store")
        self.nodes = [Node("node-a", self.root / "nodes" / "node-a", self.store),
                      Node("node-b", self.root / "nodes" / "node-b", self.store)]
        self.results_file = self.root / "store" / "results.json"
        self.results = {}
        if self.results_file.exists():
            self.results = json.loads(self.results_file.read_text(encoding="utf-8"))

    # ------------------------------------------------------------ 固定
    def pin(self, scene_rel):
        scene_abs = (self.root / scene_rel).resolve()
        if not str(scene_abs).startswith(str(self.root.resolve())):
            raise PinError("场景路径越出工作区", [{"file": scene_rel, "where": "pin"}])
        bundle = resolve_scene(scene_abs)  # 依赖闭包 + 加载路径约束（缺失在此定位来源）
        if faults.enabled("default-config"):
            bundle.settings["animation"] = dict(ANIMATION_DEFAULTS)
            bundle.settings["plugins"] = {k: dict(v) for k, v in PLUGIN_DEFAULTS.items()}
        decoy_dir = self.root / "nodes" / "node-b" / "work"
        assets = []
        for logical, role in bundle.deps.items():
            if faults.enabled("swap-asset"):
                # 故意用节点工作目录的同名文件顶替真实资源（错误示范，仅测试）。
                decoy = decoy_dir / logical
                data = decoy.read_bytes() if decoy.is_file() else (bundle.root / logical).read_bytes()
            else:
                data = (bundle.root / logical).read_bytes()
            h = self.store.put_blob(data)
            assets.append({"path": logical, "role": role, "sha256": h, "size": len(data)})
        manifest = {
            "format": "scenepin.manifest/1",
            "name": bundle.settings["name"],
            "entry": bundle.entry,
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "assets": assets,
            "settings": bundle.settings,
        }
        manifest["fingerprint"] = fingerprint.of_manifest(manifest)
        rev, created = self.store.save_revision(manifest)
        return {"revision": rev, "created_new": created, "name": manifest["name"],
                "fingerprint": manifest["fingerprint"],
                "assets": len(assets), "bytes": sum(a["size"] for a in assets)}

    # ------------------------------------------------------------ 出图
    def render(self, rev, node_ids=None):
        try:
            self.store.load_revision(rev)
        except KeyError:
            raise PinError(f"未知修订 {rev}", [{"file": rev, "where": "render"}])
        out = {}
        for node in self.nodes:
            if node_ids and node.id not in node_ids:
                continue
            result = node.render(rev)
            out[node.id] = result
            self.results.setdefault(rev, {})[node.id] = result  # 失败也反馈回场景固定
        self._save_results()
        return out

    def _save_results(self):
        self.results_file.write_text(
            json.dumps(self.results, ensure_ascii=False, indent=1), encoding="utf-8")

    # ------------------------------------------------------------ 状态
    def list_scenes(self):
        base = self.root / "scenes"
        if not base.exists():
            return []
        out = []
        for p in sorted(base.rglob("*.json")):
            if p.name.endswith(".font.json"):
                continue
            out.append(str(p.relative_to(self.root)))
        return out

    def compare(self, rev):
        """跨节点核对：场景指纹必须一致、像素必须一致，否则给出差值证据。"""
        results = self.results.get(rev, {})
        ok = {nid: r for nid, r in results.items() if r.get("status") == "ok"}
        fingerprints = {nid: r.get("fingerprint") for nid, r in ok.items()}
        pixels = {nid: (r.get("output") or {}).get("pixel_sha256") for nid, r in ok.items()}
        problems = []
        if len(fingerprints) < 2:
            problems.append("可用节点结果不足两台，无法核对跨工作站一致性")
        # 缺失指纹/像素是坏结果，不得用默认值掩盖
        missing = sorted(nid for nid, v in fingerprints.items() if not v)
        missing += sorted(nid for nid, v in pixels.items() if not v)
        if missing:
            problems.append("节点结果缺少场景指纹或像素摘要: " + ", ".join(sorted(set(missing))))
        known = [v for v in fingerprints.values() if v]
        if len(set(known)) > 1:
            problems.append("场景指纹在节点间不一致")
        known_px = [v for v in pixels.values() if v]
        if len(set(known_px)) > 1:
            problems.append("像素摘要在节点间不一致")
        return {"revision": rev,
                "nodes": sorted(results),
                "fingerprints": fingerprints,
                "pixel_sha256": pixels,
                "consistent": not problems,
                "problems": problems}

    def state(self):
        revs = []
        for m in self.store.list_revisions():
            rev = m["revision"]
            res = {}
            for nid, r in self.results.get(rev, {}).items():
                item = {"status": r["status"]}
                if r["status"] == "ok":
                    item["out"] = r["output"]["sha256"][:12]
                    item["pixel"] = r["output"].get("pixel_sha256", "")[:12]
                else:
                    item["error"] = r["error"]["message"]
                res[nid] = item
            cmp = self.compare(rev)
            revs.append({"revision": rev, "short": rev[:12], "name": m["name"],
                         "fingerprint": m.get("fingerprint") or fingerprint.of_manifest(m),
                         "created": m["created"], "entry": m["entry"],
                         "animation": m["settings"].get("animation"),
                         "plugins": m["settings"].get("plugins"),
                         "assets": len(m["assets"]),
                         "bytes": sum(a["size"] for a in m["assets"]),
                         "results": res,
                         "consistent": cmp["consistent"],
                         "problems": cmp["problems"]})
        return {"nodes": [n.id for n in self.nodes], "scenes": self.list_scenes(),
                "revisions": revs, "policy": POLICY}

    def manifest(self, rev):
        return self.store.load_revision(rev)

    def result(self, rev, node_id):
        return self.results.get(rev, {}).get(node_id)

    def image_file(self, rev, node_id):
        r = self.result(rev, node_id)
        if r and r["status"] == "ok":
            p = Path(r["output"]["file"])
            if p.exists():
                return p
        return None
