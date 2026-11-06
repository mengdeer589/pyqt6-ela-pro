"""聊天输入区历史 / 草稿方法组。"""

from __future__ import annotations


class _InputHistoryMixin:
    def setHistory(self, history) -> None:
        """接入提示历史（``ElaChatPromptHistory`` 或 ``None``）。"""
        self._history = history

    def history(self):
        """获取提示历史对象。"""
        return self._history

    def draftState(self) -> dict:
        """获取当前草稿（文本 + 可序列化附件 + mentions）。"""
        attachments = []
        for item in self.attachments():
            attachments.append(
                {
                    "name": getattr(item, "name", ""),
                    "path": getattr(item, "path", ""),
                    "size": getattr(item, "size", 0),
                    "mime": getattr(item, "mime", ""),
                }
            )
        return {
            "text": self.text(),
            "attachments": attachments,
            "mentions": [item.toDict() for item in self.mentionSpans()],
        }

    def setDraftState(self, state) -> None:
        """恢复草稿（不可序列化的图片会退化成文件 chip）。"""
        if not isinstance(state, dict):
            return
        self.setText(str(state.get("text") or ""))
        attachments = state.get("attachments")
        if isinstance(attachments, list):
            self.setAttachments(attachments)
        self._mentions.clear()

    def _historyMode(self) -> str:  # noqa: N802
        return "shell" if self._shell_mode else "normal"

    def _applyHistoryEntry(self, entry) -> None:  # noqa: N802
        if not isinstance(entry, dict):
            return
        self._history_applying = True
        try:
            self._set_edit_text(str(entry.get("text") or ""))
            attachments = entry.get("attachments")
            if isinstance(attachments, list):
                self.setAttachments(attachments)
        finally:
            self._history_applying = False
