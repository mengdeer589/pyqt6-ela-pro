"""聊天组件到输入区的宿主 API 桥接方法组。"""

from __future__ import annotations


class _WidgetInputApiMixin:
    def setMentionProvider(self, provider) -> None:
        """设置 ``@`` 引用候选提供者（``provider(query) -> list``）。"""
        self._input.setMentionProvider(provider)

    def mentions(self) -> list:
        """当前输入中仍有效的 ``@`` 引用 id 列表。"""
        return self._input.mentions()

    def mentionSpans(self) -> list:
        """当前文本里的 ``@`` 引用区间（``ElaChatMention`` 列表）。"""
        return self._input.mentionSpans()

    def setCommandProvider(self, provider) -> None:
        """设置 ``/`` 命令候选提供者（``provider(query) -> list``）。"""
        self._input.setCommandProvider(provider)

    def setCommandSubmitMode(self, mode: str) -> None:
        """设置 ``/`` 命令提交方式（``send`` / ``signal``）。"""
        self._input.setCommandSubmitMode(mode)

    def commandSubmitMode(self) -> str:
        """获取命令提交方式。"""
        return self._input.commandSubmitMode()

    def addSelector(self, key: str, title: str, items=None, current: str = ""):
        """在输入区发送键之前添加下拉选择器。"""
        return self._input.addSelector(key, title, items, current)

    def setSelectorItems(self, key: str, items, current=None) -> bool:
        """替换某个选择器的选项。"""
        return self._input.setSelectorItems(key, items, current)

    def selector(self, key: str):
        """获取选择器句柄。"""
        return self._input.selector(key)

    def selectorValue(self, key: str) -> str:
        """获取某个选择器的当前 id。"""
        return self._input.selectorValue(key)

    def setShellMode(self, on: bool) -> None:
        """进入 / 退出输入区 shell 模式。"""
        self._input.setShellMode(on)

    def shellMode(self) -> bool:
        """是否处于 shell 模式。"""
        return self._input.shellMode()

    def setHistory(self, history) -> None:
        """接入提示历史（``ElaChatPromptHistory`` 或 ``None``）。"""
        self._input.setHistory(history)

    def history(self):
        """获取提示历史对象。"""
        return self._input.history()

    def draftState(self) -> dict:
        """获取输入草稿快照。"""
        return self._input.draftState()

    def setDraftState(self, state) -> None:
        """恢复输入草稿。"""
        self._input.setDraftState(state)

    def setPlaceholderText(self, text: str) -> None:
        """设置输入框占位文案。"""
        self._input.setPlaceholderText(text)

    def placeholderText(self) -> str:
        """获取输入框占位文案。"""
        return self._input.placeholderText()
