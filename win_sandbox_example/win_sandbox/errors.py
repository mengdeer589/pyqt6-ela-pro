"""策略拒绝异常：给模型和用户都能看懂的理由。"""

from __future__ import annotations


class PolicyDenied(Exception):
    """路径 / 操作被沙箱策略拒绝。

    ``to_message()`` 是给模型看的：说明哪个工具、哪个路径、为什么被拒、
    下一步可以怎么做。不要让模型只看到 ``ValueError: ...``。
    """

    def __init__(
        self,
        tool: str,
        path: str,
        reason: str,
        suggestion: str = "",
    ) -> None:
        self.tool = tool
        self.path = path
        self.reason = reason
        self.suggestion = suggestion
        super().__init__(self.to_message())

    def to_message(self) -> str:
        text = f"[denied] {self.tool}: {self.path} ({self.reason})"
        if self.suggestion:
            text += f"\n{self.suggestion}"
        return text

    def __str__(self) -> str:
        return self.to_message()
