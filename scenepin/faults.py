"""受控错误注入（仅测试使用）。

通过 SCENEPIN_FAULT 选择一种错误行为，用来证明求值一致性测试确实能
让场景指纹与渲染差值暴露坏结果，而不是只比较版本字符串。

  swap-asset          固定期改用节点工作目录中的同名资源（路径名当身份）
  default-config      固定期忽略场景给出的插件参数，改用内置默认值
  zero-time           渲染期忽略动画时刻（固定为 0）
  no-verify           节点接受未校验的缓存内容
  omit-asset-digest   场景指纹只覆盖路径、不覆盖内容摘要

未设置或未知取值时行为完全正常。
"""

import os

FAULTS = (
    "swap-asset",
    "default-config",
    "zero-time",
    "no-verify",
    "omit-asset-digest",
)


def active():
    return os.environ.get("SCENEPIN_FAULT", "").strip()


def enabled(name):
    return active() == name
