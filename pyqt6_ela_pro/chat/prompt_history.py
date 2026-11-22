"""提示历史（按 normal / shell 两份，纯数据、无 IO）。"""

from __future__ import annotations

from typing import Optional

from .message import ElaChatAttachment, ElaChatMention

DEFAULT_HISTORY_LIMIT = 50


def _entry(text, attachments=None, mentions=None) -> dict:
    """把一次提示归一成纯 JSON 条目（附件 / mentions 都落成字典）。"""
    items = []
    for item in attachments or ():
        items.append(ElaChatAttachment.coerce(item).toDict())
    spans = []
    for item in mentions or ():
        value = (
            item if isinstance(item, ElaChatMention) else ElaChatMention.fromDict(item)
        )
        if value is not None and value.isValid:
            spans.append(value.toDict())
    return {"text": str(text or ""), "attachments": items, "mentions": spans}


def _copy(value: dict) -> dict:
    return {
        "text": str(value.get("text") or ""),
        "attachments": [dict(item) for item in value.get("attachments") or ()],
        "mentions": [dict(item) for item in value.get("mentions") or ()],
    }


class ElaChatPromptHistory:
    """提示历史：``add`` 入栈，``previous`` / ``next`` 在当前草稿之间游走。"""

    def __init__(self, limit: int = DEFAULT_HISTORY_LIMIT) -> None:
        self._limit = max(1, int(limit))
        self._entries = {"normal": [], "shell": []}
        self._index = {"normal": -1, "shell": -1}
        self._draft = {"normal": _entry(""), "shell": _entry("")}

    def add(
        self,
        text: str,
        attachments=None,
        mentions=None,
        mode: str = "normal",
    ) -> None:
        """记录一条提示（空文本且无附件时忽略）。"""
        entry = _entry(text, attachments, mentions)
        if not entry["text"].strip() and not entry["attachments"]:
            return
        bucket = self._entries.setdefault(mode, [])
        bucket.append(entry)
        if len(bucket) > self._limit:
            del bucket[: len(bucket) - self._limit]
        self.reset(mode)

    def previous(self, mode: str = "normal", draft="") -> Optional[dict]:
        """上一条历史（首次调用时记住当前草稿）；没有更早返回 ``None``。"""
        bucket = self._entries.get(mode, [])
        if not bucket:
            return None
        index = self._index.get(mode, -1)
        if index < 0:
            self._draft[mode] = (
                _copy(draft) if isinstance(draft, dict) else _entry(draft)
            )
            index = len(bucket)
        if index <= 0:
            index = 0
            self._index[mode] = 0
            return _copy(bucket[0])
        index -= 1
        self._index[mode] = index
        return _copy(bucket[index])

    def next(self, mode: str = "normal") -> Optional[dict]:
        """下一条历史；越过最新一条返回当前草稿，再往下返回 ``None``。"""
        bucket = self._entries.get(mode, [])
        index = self._index.get(mode, -1)
        if index < 0:
            return None
        index += 1
        if index >= len(bucket):
            self._index[mode] = -1
            return {**_copy(self._draft.get(mode, _entry(""))), "draft": True}
        self._index[mode] = index
        return _copy(bucket[index])

    def items(self, mode: str = "normal") -> list:
        """历史快照（旧 -> 新）。"""
        return [_copy(item) for item in self._entries.get(mode, [])]

    def reset(self, mode: Optional[str] = None) -> None:
        """复位游标（``None`` 复位两份）。"""
        for key in list(self._index) if mode is None else [mode]:
            self._index[key] = -1
            self._draft[key] = _entry("")

    def clear(self, mode: Optional[str] = None) -> None:
        """清空历史。"""
        for key in list(self._entries) if mode is None else [mode]:
            self._entries[key] = []
            self._index[key] = -1
            self._draft[key] = _entry("")

    def toDict(self) -> dict:
        """转为纯 JSON 字典。"""
        return {
            key: [_copy(item) for item in value] for key, value in self._entries.items()
        }

    @classmethod
    def fromDict(
        cls, data, limit: int = DEFAULT_HISTORY_LIMIT
    ) -> "ElaChatPromptHistory":
        """从字典还原（容错）。"""
        history = cls(limit)
        if not isinstance(data, dict):
            return history
        for mode, rows in data.items():
            if not isinstance(mode, str) or not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                history.add(
                    row.get("text") or "",
                    row.get("attachments"),
                    row.get("mentions"),
                    mode,
                )
        return history


__all__ = ["DEFAULT_HISTORY_LIMIT", "ElaChatPromptHistory"]
