"""场景指纹：钉死内容（依赖摘要 + 规范化设置 + 入口）的独立摘要。

指纹不依赖修订版本字符串、固定时间、节点环境或文件系统路径：
同样的依赖内容与设置在任何工作站上都应得到同样的指纹。
"""

import hashlib
import json

from . import faults

FINGERPRINT_FORMAT = "scenepin.fingerprint/1"


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def compute(entry, assets, settings):
    # 场景入口自身的字节不作为身份：其语义已由规范化 settings 完整表达，
    # 因此仅重排 JSON / 显式写出默认值不会改变指纹。
    deps = [a for a in assets if a["role"] != "scene"]
    if faults.enabled("omit-asset-digest"):
        rows = [{"path": a["path"]} for a in deps]
    else:
        rows = [{"path": a["path"], "role": a["role"],
                 "sha256": a["sha256"], "size": a["size"]} for a in deps]
    rows.sort(key=lambda a: a["path"])
    body = {"format": FINGERPRINT_FORMAT, "entry": entry,
            "assets": rows, "settings": settings}
    return hashlib.sha256(canonical(body)).hexdigest()


def of_manifest(manifest):
    return compute(manifest["entry"], manifest["assets"], manifest["settings"])
