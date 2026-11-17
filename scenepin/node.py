"""模拟渲染工作站（节点）：按清单取数、校验、在封闭加载路径下出图。

节点只读两处：中心 CAS（按哈希取 blob）与本地缓存（按哈希命名）。
节点工作目录里的同名文件永远不会被当作资源使用——路径名不是资源身份。
"""

import hashlib
import os
import platform
import socket
import time
from datetime import datetime, timezone
from pathlib import Path

from .errors import NodeError, PinError
from .render import render_scene


def _utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class ManifestLoader:
    """闭合依赖集加载器：只允许读取清单内的逻辑路径，按钉死的哈希取内容。"""

    def __init__(self, manifest, cache_dir):
        self._map = {a["path"]: a["sha256"] for a in manifest["assets"]}
        self._cache = Path(cache_dir)

    def __call__(self, logical):
        h = self._map.get(logical)
        if h is None:
            raise PinError(
                f"加载路径越界: {logical!r} 不在任务清单内（闭合依赖集约束）",
                [{"file": logical, "where": "render-load"}])
        return (self._cache / h).read_bytes()


class Node:
    def __init__(self, node_id, root, store):
        self.id = node_id
        self.root = Path(root)
        self.cache = self.root / "cache"
        self.work = self.root / "work"
        self.out = self.root / "out"
        for d in (self.cache, self.work, self.out):
            d.mkdir(parents=True, exist_ok=True)
        self.store = store

    def _env(self, started, started_ts):
        return {
            "node": self.id,
            "host": socket.gethostname(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "pid": os.getpid(),
            "started": started,
            "finished": _utcnow(),
            "duration_ms": int((time.monotonic() - started_ts) * 1000),
        }

    def render(self, rev):
        started, started_ts = _utcnow(), time.monotonic()
        fetch_log, verify = [], []
        env = lambda: self._env(started, started_ts)  # noqa: E731
        try:
            manifest = self.store.load_revision(rev)
        except KeyError as exc:
            return {"node": self.id, "revision": rev, "status": "error",
                    "error": NodeError(str(exc)).to_dict(), "env": env()}
        try:
            blobs = {}
            for a in manifest["assets"]:
                h = a["sha256"]
                cpath = self.cache / h
                source = None
                if cpath.exists():
                    data = cpath.read_bytes()
                    if hashlib.sha256(data).hexdigest() == h:
                        source = "cache-hit"
                    else:
                        source = "cache-corrupt-refetch"
                if source is None or source == "cache-corrupt-refetch":
                    try:
                        data = self.store.get_blob(h)
                    except KeyError:
                        raise NodeError(
                            f"中心存储与节点缓存均缺少 blob {h[:12]}…，无法取得 {a['path']!r} 的钉死内容",
                            {"path": a["path"], "sha256": h, "revision": rev})
                    cpath.write_bytes(data)
                    source = source or "fetched"
                actual = hashlib.sha256(data).hexdigest()
                ok = actual == h
                blobs[a["path"]] = data
                fetch_log.append({"path": a["path"], "sha256": h, "source": source, "bytes": len(data)})
                verify.append({"path": a["path"], "role": a["role"], "expected": h,
                               "actual": actual, "source": source, "ok": ok})
                if not ok:
                    raise NodeError(f"资源校验失败: {a['path']!r} 内容哈希与清单不符",
                                    {"path": a["path"], "expected": h, "actual": actual})
            loader = ManifestLoader(manifest, self.cache)
            png = render_scene(manifest, loader)
            out_hash = hashlib.sha256(png).hexdigest()
            out_file = self.out / f"{rev}.png"
            out_file.write_bytes(png)
            return {"node": self.id, "revision": rev, "status": "ok",
                    "output": {"sha256": out_hash, "bytes": len(png),
                               "width": manifest["settings"]["render"]["width"],
                               "height": manifest["settings"]["render"]["height"],
                               "file": str(out_file)},
                    "assets": verify, "fetch": fetch_log, "env": env()}
        except (NodeError, PinError) as exc:
            # 失败节点保留可诊断原因：已完成的校验、取数日志与环境一并落账
            return {"node": self.id, "revision": rev, "status": "error",
                    "error": exc.to_dict(), "assets": verify, "fetch": fetch_log, "env": env()}
