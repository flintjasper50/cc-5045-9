"""统一错误类型：固定期错误携带引用链，节点错误携带可诊断细节。"""


class PinError(Exception):
    """场景固定（解析/校验/加载路径约束）失败。

    chain: [{"file": 逻辑路径, "where": "models[0].path" 或 "line 12"}, ...]
    用于把缺失依赖或违规引用定位到引用来源。
    """

    def __init__(self, message, chain=None):
        super().__init__(message)
        self.message = message
        self.chain = list(chain or [])

    def to_dict(self):
        return {"kind": "pin", "message": self.message, "chain": self.chain}


class NodeError(Exception):
    """节点执行失败（取数、校验、渲染）。detail 为可诊断上下文。"""

    def __init__(self, message, detail=None):
        super().__init__(message)
        self.message = message
        self.detail = dict(detail or {})

    def to_dict(self):
        return {"kind": "node", "message": self.message, "detail": self.detail}
