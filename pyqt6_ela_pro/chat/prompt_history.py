"""提示历史（按 normal / shell 两份，纯数据、无 IO）。"""

from __future__ import annotations

from typing import Optional

DEFAULT_HISTORY_LIMIT = 50


class ElaChatPromptHistory:
    """提示历史：``add`` 入栈，``previous`` / ``next`` 在当前草稿之间游走。"""

    def __init__(self, limit: int = DEFAULT_HISTORY_LIMIT) -> None:
        self._limit = max(1, int(limit))
        self._entries = {"normal": [], "shell": []}
        self._index = {"normal": -1, "shell": -1}
        self._draft = {"normal": "", "shell": ""}

    def add(
        self,
        text: str,
        attachments=None,
        mentions=None,
        mode: str = "normal",
    ) -> None:
        """记录一条提示（空文本且无附件时忽略）。"""
        text = str(text or "")
        attachments = list(attachments or ())
        if not text.strip() and not attachments:
            return
        bucket = self._entries.setdefault(mode, [])
        bucket.append(
            {
                "text": text,
                "attachments": attachments,
                "mentions": list(mentions or ()),
            }
        )
        if len(bucket) > self._limit:
            del bucket[: len(bucket) - self._limit]
        self.reset(mode)

    def previous(self, mode: str = "normal", draft: str = "") -> Optional[dict]:
        """上一条历史（首次调用时记住当前草稿）；没有更早返回 ``None``。"""
        bucket = self._entries.get(mode, [])
        if not bucket:
            return None
        index = self._index.get(mode, -1)
        if index < 0:
            self._draft[mode] = str(draft or "")
            index = len(bucket)
        if index <= 0:
            index = 0
            self._index[mode] = 0
            return dict(bucket[0])
        index -= 1
        self._index[mode] = index
        return dict(bucket[index])

    def next(self, mode: str = "normal") -> Optional[dict]:
        """下一条历史；越过最新一条返回当前草稿，再往下返回 ``None``。"""
        bucket = self._entries.get(mode, [])
        index = self._index.get(mode, -1)
        if index < 0:
            return None
        index += 1
        if index >= len(bucket):
            self._index[mode] = -1
            return {
                "text": self._draft.get(mode, ""),
                "attachments": [],
                "mentions": [],
                "draft": True,
            }
        self._index[mode] = index
        return dict(bucket[index])

    def items(self, mode: str = "normal") -> list:
        """历史快照（旧 -> 新）。"""
        return [dict(item) for item in self._entries.get(mode, [])]

    def reset(self, mode: Optional[str] = None) -> None:
        """复位游标（``None`` 复位两份）。"""
        for key in list(self._index) if mode is None else [mode]:
            self._index[key] = -1
            self._draft[key] = ""

    def clear(self, mode: Optional[str] = None) -> None:
        """清空历史。"""
        for key in list(self._entries) if mode is None else [mode]:
            self._entries[key] = []
            self._index[key] = -1
            self._draft[key] = ""

    def toDict(self) -> dict:
        """转为纯 JSON 字典。"""
        return {
            key: [dict(item) for item in value] for key, value in self._entries.items()
        }

    @classmethod
    def fromDict(
        cls, data, limit: int = DEFAULT_HISTORY_LIMIT
    ) -> "ElaChatPromptHistory":
        """从字典还原（容错）。"""
        history = cls(limit)
        if not isinstance(data, dict):
            return history
        for mode in ("normal", "shell"):
            rows = data.get(mode)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, dict) and str(row.get("text") or "").strip():
                    history._entries[mode].append(
                        {
                            "text": str(row.get("text") or ""),
                            "attachments": list(row.get("attachments") or ()),
                            "mentions": list(row.get("mentions") or ()),
                        }
                    )
        return history


__all__ = ["DEFAULT_HISTORY_LIMIT", "ElaChatPromptHistory"]
