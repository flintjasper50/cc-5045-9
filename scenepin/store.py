"""内容寻址存储（CAS）与不可变修订清单存储。"""

import hashlib
import json
from pathlib import Path


def sha256_of(data):
    return hashlib.sha256(data).hexdigest()


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.cas = self.root / "cas"
        self.revs = self.root / "revisions"
        self.cas.mkdir(parents=True, exist_ok=True)
        self.revs.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ CAS
    def _blob_path(self, h):
        return self.cas / h[:2] / h

    def put_blob(self, data):
        h = sha256_of(data)
        p = self._blob_path(h)
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(p)  # 原子落盘，内容寻址天然幂等
        return h

    def has_blob(self, h):
        return self._blob_path(h).exists()

    def get_blob(self, h):
        p = self._blob_path(h)
        if not p.exists():
            raise KeyError(h)
        return p.read_bytes()

    # ------------------------------------------------------------ 修订清单
    @staticmethod
    def revision_id(manifest):
        key = {"assets": [(a["path"], a["sha256"]) for a in manifest["assets"]],
               "settings": manifest["settings"]}
        return sha256_of(canonical(key))

    def save_revision(self, manifest):
        rev = self.revision_id(manifest)
        manifest["revision"] = rev
        p = self.revs / f"{rev}.json"
        created = not p.exists()
        if created:
            p.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        return rev, created

    def load_revision(self, rev):
        p = self.revs / f"{rev}.json"
        if not p.exists():
            raise KeyError(f"未知修订 {rev}")
        return json.loads(p.read_text(encoding="utf-8"))

    def list_revisions(self):
        out = []
        for p in sorted(self.revs.glob("*.json")):
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        out.sort(key=lambda m: m.get("created", ""))
        return out
