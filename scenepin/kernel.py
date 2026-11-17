"""场景固定内核：固定场景为不可变清单、驱动节点出图、沉淀结果与失败。"""

import json
from datetime import datetime, timezone
from pathlib import Path

from .errors import PinError
from .node import Node
from .scenefile import POLICY, resolve_scene
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
        assets = []
        for logical, role in bundle.deps.items():
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
        rev, created = self.store.save_revision(manifest)
        return {"revision": rev, "created_new": created, "name": manifest["name"],
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

    def state(self):
        revs = []
        for m in self.store.list_revisions():
            rev = m["revision"]
            res = {}
            for nid, r in self.results.get(rev, {}).items():
                item = {"status": r["status"]}
                if r["status"] == "ok":
                    item["out"] = r["output"]["sha256"][:12]
                else:
                    item["error"] = r["error"]["message"]
                res[nid] = item
            revs.append({"revision": rev, "short": rev[:12], "name": m["name"],
                         "created": m["created"], "entry": m["entry"],
                         "assets": len(m["assets"]),
                         "bytes": sum(a["size"] for a in m["assets"]),
                         "results": res})
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
