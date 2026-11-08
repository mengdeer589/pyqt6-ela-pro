"""聊天输入区补全 / 命令 / 选择器方法组。"""

from __future__ import annotations

import re
from typing import Callable, Optional

from .._internal import safe_connect
from .message import ElaChatMention
from .selector import ElaChatSelector
from .suggestions import ElaChatSuggestion

_MENTION_RE = re.compile(r"(?:^|\s)@([^\s@]*)$")
_COMMAND_RE = re.compile(r"(?:^|\s)/([^\s/]*)$")
_MENTION_TAIL = (
    r"(?![0-9A-Za-z_@"
    r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    r"\U00020000-\U0002ee5f\U0002f800-\U0002fa1f])"
)


class _InputCompletionMixin:
    def setMentionProvider(self, provider: Optional[Callable[[str], list]]) -> None:
        """设置 ``@`` 引用候选提供者（``provider(query) -> list``）。"""
        self._mention_provider = provider

    def setCommandProvider(self, provider: Optional[Callable[[str], list]]) -> None:
        """设置 ``/`` 命令候选提供者（``provider(query) -> list``）。"""
        self._command_provider = provider

    def setCommandSubmitMode(self, mode: str) -> None:
        """设置 ``/`` 命令的提交方式。
        ``"send"``（默认）走 ``submitted`` / ``submittedFull``；``"signal"`` 只发
        ``commandSubmitted(text)`` 且不落消息（客户端命令）。
        """
        if mode not in ("send", "signal"):
            raise ValueError("setCommandSubmitMode: mode 必须是 'send' 或 'signal'")
        self._command_submit_mode = mode

    def commandSubmitMode(self) -> str:
        """获取命令提交方式。"""
        return self._command_submit_mode

    def openMentionPopup(self) -> None:
        """主动打开 ``@`` 引用补全（``+`` 菜单入口）。"""
        if self._mention_provider is None:
            return
        items = self._mention_provider("") or []
        if not items:
            return
        self._popup_kind = "mention"
        self._popup.open(items)

    def openCommandPopup(self) -> None:
        """主动打开 ``/`` 命令补全。"""
        if self._command_provider is None:
            return
        items = self._command_provider("") or []
        if not items:
            return
        self._popup_kind = "command"
        self._popup.open(items)

    def _update_popup(self) -> None:
        text = self._edit.toPlainText()
        command = _COMMAND_RE.search(text)
        if command and self._command_provider is not None:
            items = self._command_provider(command.group(1)) or []
            if items:
                self._popup_kind = "command"
                self._popup.open(items)
                return
        mention = _MENTION_RE.search(text)
        if mention and self._mention_provider is not None:
            items = self._mention_provider(mention.group(1)) or []
            if items:
                self._popup_kind = "mention"
                self._popup.open(items)
                return
        self._close_popup()

    def _close_popup(self) -> None:
        self._popup_kind = ""
        self._popup.close()

    def _on_suggestion_activated(self, item: ElaChatSuggestion) -> None:
        text = self._edit.toPlainText()
        if self._popup_kind == "command":
            match = _COMMAND_RE.search(text)
            token = item.insert_text or f"/{item.label.lstrip('/')} "
            if match:
                start = match.start(1) - 1
                self._set_edit_text(text[:start] + token + text[match.end(1) :])
            else:
                self._set_edit_text(self._join_token(text, token))
            self.commandSelected.emit(item.id or item.label)
            self._popup_kind = ""
            return
        token = item.insert_text or f"@{item.label} "
        match = _MENTION_RE.search(text)
        if match:
            start = match.start(1) - 1
            self._set_edit_text(text[:start] + token + text[match.end(1) :])
        else:
            self._set_edit_text(self._join_token(text, token))
        self._mentions.append((item.id, token, getattr(item, "kind", "")))
        self.mentionSelected.emit(item.id, item.label)
        self._popup_kind = ""

    @staticmethod
    def _join_token(text: str, token: str) -> str:
        """把补全 token 接到文本末尾（无词边界时先补一个空格）。"""
        if text and not text[-1].isspace():
            return f"{text} {token}"
        return text + token

    def _set_edit_text(self, text: str) -> None:
        self._edit.setPlainText(text)
        cursor = self._edit.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._edit.setTextCursor(cursor)
        self._edit.setFocus()

    def mentions(self) -> list:
        """当前仍存在于文本中的 ``@`` 引用 id 列表。
        必须做词边界匹配：``token in text`` 会把改过的 ``"@Album"`` 仍判成
        ``"@Al "`` 还在。
        """
        text = self._edit.toPlainText()
        if not text:
            return []
        out = []
        for entry in self._mentions:
            mid, token = entry[0], entry[1]
            bare = token.strip()
            if not bare:
                continue
            if re.search(r"(?:^|\s)" + re.escape(bare) + _MENTION_TAIL, text):
                out.append(mid)
        return out

    def mentionSpans(self, text: Optional[str] = None) -> list:
        """当前文本里仍有效的 ``@`` 引用区间（``ElaChatMention`` 列表）。

        偏移按 Python ``str`` 下标计；同一 token 多次出现只取第一处。
        ``text`` 用于提交前按 **strip 后**的文本计算区间；缺省读编辑器原文。
        """
        text = self._edit.toPlainText() if text is None else str(text)
        if not text:
            return []
        result = []
        for entry in self._mentions:
            token = entry[1]
            kind = entry[2] if len(entry) > 2 else ""
            bare = token.strip()
            if not bare:
                continue
            pattern = re.compile(r"(?:^|\s)(" + re.escape(bare) + ")" + _MENTION_TAIL)
            match = pattern.search(text)
            if match is None:
                continue
            start = match.start(1)
            result.append(
                ElaChatMention(
                    start=start,
                    end=start + len(bare),
                    kind=kind,
                    id=str(entry[0] or ""),
                )
            )
        return result

    def setMentions(self, mentions) -> None:
        """按当前文本恢复 ``@`` 引用条目（接受 ``ElaChatMention`` / dict）。"""
        text = self._edit.toPlainText()
        entries = []
        for item in mentions or ():
            mention = (
                item
                if isinstance(item, ElaChatMention)
                else ElaChatMention.fromDict(item)
            )
            if mention is None or not mention.isValid:
                continue
            token = text[mention.start : mention.end]
            if not token:
                continue
            entries.append((mention.id, token, mention.kind))
        self._mentions = entries

    def clearMentions(self) -> None:
        """清空引用记录。"""
        self._mentions.clear()

    def addSelector(
        self,
        key: str,
        title: str,
        items=None,
        current: str = "",
    ) -> ElaChatSelector:
        """在发送键之前添加一个下拉选择器，返回控件句柄。"""
        selector_key = str(key or "")
        if not selector_key:
            raise ValueError("addSelector: key 不能为空")
        if selector_key in self._selectors:
            raise ValueError(f"addSelector: selector {selector_key!r} 已存在")
        selector = ElaChatSelector(title, items or [], current, self._surface)
        safe_connect(
            selector,
            "selectionChanged",
            lambda itemId, k=selector_key: self.selectorChanged.emit(k, itemId),
            "input.selector",
            receiver=selector,
        )
        self._toolbar.insertWidget(
            self._button, selector, key=f"selector:{selector_key}"
        )
        self._selectors[selector_key] = selector
        return selector

    def setSelectorItems(self, key: str, items, current: Optional[str] = None) -> bool:
        """替换某个选择器的选项（不存在返回 ``False``）。"""
        selector = self._selectors.get(str(key or ""))
        if selector is None:
            return False
        selector.setItems(items, current)
        return True

    def removeSelector(self, key: str) -> bool:
        """移除选择器（销毁控件）。"""
        selector_key = str(key or "")
        selector = self._selectors.pop(selector_key, None)
        if selector is None:
            return False
        self._toolbar.removeItem(selector)
        selector.deleteLater()
        return True

    def selector(self, key: str) -> Optional[ElaChatSelector]:
        """获取选择器句柄。"""
        return self._selectors.get(str(key or ""))

    def selectors(self) -> dict:
        """获取全部选择器（副本）。"""
        return dict(self._selectors)

    def selectorValue(self, key: str) -> str:
        """获取某个选择器的当前 id（不存在返回空串）。"""
        selector = self._selectors.get(str(key or ""))
        return selector.current() if selector is not None else ""
