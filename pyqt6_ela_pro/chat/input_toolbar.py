"""聊天输入区工具栏 / 上下文占用方法组。"""

from __future__ import annotations

from .input_parts import _ContextUsageRing
from .message import _as_float, _as_int
from .selector import ElaChatSelector
from .toolbar import ElaChatToolBar, ElaChatToolButton


class _InputToolbarMixin:
    def setShellMode(self, on: bool) -> None:
        """进入 / 退出 shell 模式（等宽字体、Esc 退出、提交走 ``shellSubmitted``）。"""
        on = bool(on)
        if on == self._shell_mode:
            return
        self._shell_mode = on
        if on:
            self._add_file_visible_before_shell = self.addFileVisible()
            self._add_file_button.setVisible(False)
            for selector in self._toolbar.findChildren(ElaChatSelector):
                selector.setVisible(False)
            self._attachments.setVisible(False)
            self._edit.setFont(self._shell_font)
            self._edit.setPlaceholderText("输入命令…")
            self._close_popup()
        else:
            self._edit.setFont(self._normal_font)
            self._edit.setPlaceholderText(self._default_placeholder)
            self._add_file_button.setVisible(self._add_file_visible_before_shell)
            for selector in self._toolbar.findChildren(ElaChatSelector):
                selector.setVisible(True)
            self._attachments.setVisible(bool(self.attachments()))
        self._sync_height()
        self._edit.setFocus()

    def shellMode(self) -> bool:
        """是否处于 shell 模式。"""
        return self._shell_mode

    def toolBar(self) -> ElaChatToolBar:
        """获取工具栏（用于添加自定义工具按钮 / 控件）。"""
        return self._toolbar

    def addFileButton(self) -> ElaChatToolButton:
        """获取内置「添加文件」按钮句柄。"""
        return self._add_file_button

    def setAddFileVisible(self, on: bool) -> None:
        """显示 / 隐藏内置「添加文件」按钮。"""
        self._add_file_button.setVisible(bool(on))

    def addFileVisible(self) -> bool:
        """内置「添加文件」按钮是否可见（``isHidden`` 判据，父链未显示时也准确）。"""
        return not self._add_file_button.isHidden()

    def clearButton(self) -> ElaChatToolButton:
        """获取内置「清空上下文」按钮句柄。"""
        return self._clear_button

    def setClearVisible(self, on: bool) -> None:
        """显示 / 隐藏内置「清空上下文」按钮（默认显示）。"""
        self._clear_button.setVisible(bool(on))

    def clearVisible(self) -> bool:
        """内置「清空上下文」按钮是否可见（``isHidden`` 判据）。"""
        return not self._clear_button.isHidden()

    def setContextUsage(
        self, used: int = 0, window: int = 0, costUsd: float = 0.0
    ) -> None:
        """设置上下文窗口占用（底部工具栏圆环；``window <= 0`` 按 0% 显示）。

        数据完全由宿主提供，库不推断，也不进 ``ElaChatStats``（那是各步求和）。

        :param used: 已占用词元
        :param window: 模型上下文窗口词元；``0`` / 非法值按 0% 显示
        :param costUsd: 会话累计花费（美元），进 hover 详情；``0`` 不显示该行
        """
        self._usage_used = max(0, _as_int(used))
        self._usage_window = max(0, _as_int(window))
        self._usage_cost = _as_float(costUsd)
        self._usage_ring.setUsage(
            self._usage_used, self._usage_window, self._usage_cost
        )

    def contextUsage(self) -> tuple:
        """获取 ``(已用, 窗口, 花费美元)``（未设置时窗口为 0）。"""
        return (self._usage_used, self._usage_window, self._usage_cost)

    def contextUsagePercent(self) -> int:
        """上下文占用百分比（窗口未知返回 0）。"""
        return self._usage_ring.percent()

    def contextUsageWidget(self) -> "_ContextUsageRing":
        """获取上下文占用圆环控件（宿主可改边长 / 挂事件）。"""
        return self._usage_ring

    def setContextUsageVisible(self, on: bool) -> None:
        """显示 / 隐藏内置「上下文占用圆环」（默认显示，与旁边按钮一致）。"""
        self._usage_ring.setVisible(bool(on))

    def contextUsageVisible(self) -> bool:
        """内置圆环是否可见（``isHidden`` 判据，父链未显示时也准确）。"""
        return not self._usage_ring.isHidden()

    def newTopicButton(self) -> ElaChatToolButton:
        """获取内置「新建话题」按钮句柄。"""
        return self._new_topic_button

    def setNewTopicVisible(self, on: bool) -> None:
        """显示 / 隐藏内置「新建话题」按钮（默认显示）。"""
        self._new_topic_button.setVisible(bool(on))

    def newTopicVisible(self) -> bool:
        """内置「新建话题」按钮是否可见（``isHidden`` 判据）。"""
        return not self._new_topic_button.isHidden()

    def _on_clear_clicked(self) -> None:
        # 只发请求：清空涉及「中止生成 → 清队列 → 清消息」，归 widget 层
        self.clearRequested.emit()

    def _on_new_topic_clicked(self) -> None:
        # 组件只管发信号：话题 / 会话由宿主创建（会话列表 UI 属宿主职责）
        self.newTopicRequested.emit()
