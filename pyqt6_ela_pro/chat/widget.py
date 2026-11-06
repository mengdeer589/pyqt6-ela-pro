"""
聊天组件组装：:class:`ElaChatWidget` = :class:`ElaChatView` + :class:`ElaChatInput`。

本层只管输入区与回合编排；消息内容一律经 ``chatView()`` 在 view 层操作。
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QImage, QKeySequence, QShortcut
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from .._ownership import ElaWidgetOwnershipType
from ..widget_base import ElaThemeWidget
from .blocks import MessageActions
from .docks import ElaChatInputDock, ElaChatPermissionDock, ElaChatQueueDock
from .input import ElaChatInput
from .message import (
    ElaChatRoleType,
)
from .toolbar import ElaChatToolBar
from .view import ElaChatView
from .widget_input_api import _WidgetInputApiMixin
from .widget_queue import _WidgetQueueMixin
from .widget_steer import _WidgetSteerMixin
from .widget_turn import _WidgetTurnMixin


class ElaChatWidget(
    _WidgetQueueMixin,
    _WidgetSteerMixin,
    _WidgetTurnMixin,
    _WidgetInputApiMixin,
    ElaThemeWidget,
):
    """ChatGPT 风格聊天组件（消息列表 + 可扩展输入区）。
    本层只管输入区与回合编排；消息内容（正文 / 思考 / 工具 / 分段 / 用量 / 外观）
    经 :meth:`chatView` 在 :class:`ElaChatView` 上操作，``messageId`` 首位必填。
    """

    #: 用户提交了消息（参数：文本）
    messageSubmitted = pyqtSignal(str)
    #: 用户提交了消息（参数：文本、附件快照列表）
    messageSubmittedFull = pyqtSignal(str, list)
    #: 用户请求停止生成（宿主应中止自己的数据流）
    stopRequested = pyqtSignal()
    #: 助手消息开始（参数：消息 id）
    generationStarted = pyqtSignal(int)
    #: 助手消息结束（参数：消息 id、最终状态）
    generationFinished = pyqtSignal(int, str)
    #: 消息内容更新（流式追加 / 标题 / 耗时等，参数：消息 id）
    messageUpdated = pyqtSignal(int)
    #: 空态建议被点击（参数：建议文本）
    suggestionClicked = pyqtSignal(str)
    #: 点击「清空上下文」且确实有待清内容时发出（**确认弹框发出前触发**；空会话不弹框也不发）
    clearRequested = pyqtSignal()
    #: 点击「新建话题」按钮（组件不做任何处理，宿主据此开新会话 / 话题）
    newTopicRequested = pyqtSignal()
    #: 点击输入区工具栏的上下文占用圆环（组件不做任何行为，宿主据此弹详情面板等）
    contextUsageClicked = pyqtSignal()
    #: 会话被清空（消息 + 队列 + 生成态）；宿主在此重置自己的后端会话
    cleared = pyqtSignal()
    #: 消息动作（参数：消息 id、动作 key）
    messageActionTriggered = pyqtSignal(int, str)
    #: 用户点击「复制」（参数：消息 id）
    copyRequested = pyqtSignal(int)
    #: 用户点击「撤回」（参数：消息 id）
    undoRequested = pyqtSignal(int)
    #: 用户点击「重新生成」（参数：消息 id）
    regenerateRequested = pyqtSignal(int)
    #: 用户在错误卡上点击「重试」（参数：消息 id）—— 同参数重发，不删消息
    retryRequested = pyqtSignal(int)
    #: 用户取消自动重试（参数：消息 id）
    retryCancelled = pyqtSignal(int)
    #: 待发送消息动作（参数：消息 id、动作）
    pendingUserActionRequested = pyqtSignal(int, str)
    #: 插入了待答复的工具审批（参数：消息 id、``requestId``）；组件不在此阻塞
    permissionRequested = pyqtSignal(int, str)
    #: 审批已落定（参数：消息 id、``requestId``、reply、answer、feedback）
    permissionReplied = pyqtSignal(int, str, str, str, str)
    #: 用户点击附件 chip（参数：消息 id、路径）
    attachmentClicked = pyqtSignal(int, str)
    #: 附件列表变化（参数：待发附件快照列表）
    attachmentsChanged = pyqtSignal(list)
    #: 排队消息变化（参数：排队快照列表）
    queueChanged = pyqtSignal(list)
    #: 待送插话变化（参数：插话快照列表）
    steerChanged = pyqtSignal(list)
    #: 一条插话到了投递时机（参数：``{id, text, attachments, messageId}``）；组件不发送后端请求
    steerReady = pyqtSignal(object)
    #: ``@`` 引用被选中（参数：引用 id、展示文本）
    mentionSelected = pyqtSignal(str, str)
    #: ``/`` 命令被选中（参数：命令名）
    commandSelected = pyqtSignal(str)
    #: ``/`` 命令被提交（``setCommandSubmitMode("signal")`` 时）
    commandSubmitted = pyqtSignal(str)
    #: 输入区下拉选择器变化（参数：key、item id）
    selectorChanged = pyqtSignal(str, str)
    #: shell 模式提交（参数：命令行文本）
    shellSubmitted = pyqtSignal(str)
    #: 输入草稿变化（防抖）
    draftChanged = pyqtSignal(dict)
    #: 剪贴板图片被粘贴（参数：``QImage``）
    imagePasted = pyqtSignal(QImage)
    #: 文件进入输入区（拖放到组件任意位置 / 粘贴「复制的文件」；参数：本地文件路径列表）
    filesAdded = pyqtSignal(list)
    #: 当前会话切换（参数：会话 id）——会话列表 UI 预留
    sessionChanged = pyqtSignal(str)
    #: 批量渐进渲染完成（``beginBatch`` / ``endBatch`` 队列排空）
    batchRenderFinished = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._generating = False
        self._streaming_id: Optional[int] = None
        self._user_title = ""
        self._assistant_title = ""
        #: 当前话题 id（纯标记，见 setCurrentSessionId）
        self._current_session_id = ""
        self._queue_enabled = True
        self._queue: list = []
        self._queue_history: list = []
        self._auto_send_queue = True
        #: 待送插话（steer）；与 ``_queue`` 分开，投递时机完全不同
        self._steer: list = []
        self._steer_enabled = True
        #: 已发过 ``generationFinished`` 的消息 id：一个回合只允许一次收尾信号
        self._finished_generation: set = set()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._view = ElaChatView(self)
        layout.addWidget(self._view, 1)
        self._input_dock = ElaChatInputDock(self)
        layout.addWidget(self._input_dock, 0, Qt.AlignmentFlag.AlignHCenter)
        # 审批交互卡的专用 dock（不占用输入区）
        self._permission_dock = ElaChatPermissionDock(self)
        layout.addWidget(self._permission_dock, 0, Qt.AlignmentFlag.AlignHCenter)
        self._queue_dock = ElaChatQueueDock(self)
        layout.addWidget(self._queue_dock, 0, Qt.AlignmentFlag.AlignHCenter)
        self._input = ElaChatInput(self)
        layout.addWidget(self._input, 0, Qt.AlignmentFlag.AlignHCenter)
        self._composer_widgets = (
            self._input_dock,
            self._permission_dock,
            self._queue_dock,
            self._input,
        )
        self._sync_composer_width()
        #: 当前占据审批 dock 的 partId（空 = dock 上没有审批卡）
        self._permission_dock_part = ""

        self._view.suggestionClicked.connect(self.suggestionClicked)
        self._view.messageUpdated.connect(self.messageUpdated)
        self._view.copyRequested.connect(self.copyRequested)
        self._view.undoRequested.connect(self.undoRequested)
        self._view.regenerateRequested.connect(self.regenerateRequested)
        self._view.retryRequested.connect(self.retryRequested)
        self._view.retryCancelled.connect(self.retryCancelled)
        self._view.pendingUserActionRequested.connect(self._on_pending_user_action)
        self._view.permissionRequested.connect(self.permissionRequested)
        self._view.permissionReplied.connect(self.permissionReplied)
        # 审批的交互卡 -> 输入区 dock；落定后撤下并接上下一张待答的
        self._view.permissionDockRequested.connect(self._on_permission_dock_requested)
        self._view.permissionSettled.connect(self._on_permission_settled)
        self._view.attachmentClicked.connect(self.attachmentClicked)
        self._view.messageActionTriggered.connect(self.messageActionTriggered)
        self._view.batchRenderFinished.connect(self.batchRenderFinished)
        self._input.submittedFull.connect(self._on_input_submitted)
        self._input.stopRequested.connect(self.stopGeneration)
        self._input.attachmentsChanged.connect(self.attachmentsChanged)
        self._input.mentionSelected.connect(self.mentionSelected)
        self._input.commandSelected.connect(self.commandSelected)
        self._input.commandSubmitted.connect(self.commandSubmitted)
        self._input.selectorChanged.connect(self.selectorChanged)
        self._input.shellSubmitted.connect(self.shellSubmitted)
        self._input.draftChanged.connect(self.draftChanged)
        self._input.alternateSubmitted.connect(self._on_alternate_submitted)
        self._input.imagePasted.connect(self.imagePasted)
        self._input.filesAdded.connect(self.filesAdded)
        self._input.clearRequested.connect(self._on_clear_requested)
        self._input.newTopicRequested.connect(self.newTopicRequested)
        self._input.contextUsageClicked.connect(self.contextUsageClicked)
        self._input_dock.changed.connect(self._on_input_dock_changed)
        self._queue_dock.sendRequested.connect(self.sendQueuedNow)
        self._queue_dock.editRequested.connect(self.editQueuedMessage)
        self._queue_dock.removeRequested.connect(self.dequeueMessage)
        self._queue_dock.reorderRequested.connect(self.moveQueued)
        self._queue_dock.steerRequested.connect(self.steerQueued)
        self._queue_dock.undoRequested.connect(self.undoQueueChange)

        # Ctrl+F：打开会话内搜索（焦点在子控件时也生效）
        self._search_shortcut = QShortcut(QKeySequence.StandardKey.Find, self)
        self._search_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._search_shortcut.activated.connect(self._view.showSearchBar)

        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if self._input.acceptsMime(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if self._input.acceptsMime(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if not self._input.attachMime(event.mimeData()):
            super().dropEvent(event)
            return
        event.acceptProposedAction()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        self._sync_composer_width()

    def _sync_composer_width(self) -> None:
        """输入区 / dock 与阅读列同宽并居中（ChatGPT 式版心）。"""
        available = max(120, self.width() - 20)
        max_width = self._view.contentMaxWidth() if hasattr(self, "_view") else 0
        width = available if max_width <= 0 else min(max_width, available)
        for widget in getattr(self, "_composer_widgets", ()):
            if widget.minimumWidth() == width and widget.maximumWidth() == width:
                continue
            widget.setFixedWidth(width)

    def chatView(self) -> ElaChatView:
        """获取消息列表视图。"""
        return self._view

    def chatInput(self) -> ElaChatInput:
        """获取输入区。"""
        return self._input

    def inputDock(self) -> ElaChatInputDock:
        """获取输入区替换 dock（宿主自用的「顶替输入区」场景）。"""
        return self._input_dock

    def permissionDock(self) -> ElaChatPermissionDock:
        """获取审批 / 提问的交互 dock（**输入区上方，输入区照常可用**）。"""
        return self._permission_dock

    def queueDock(self) -> ElaChatQueueDock:
        """获取排队消息 dock。"""
        return self._queue_dock

    def setDockWidget(
        self,
        widget: Optional[QWidget],
        replace: bool = True,
        *,
        ownership=ElaWidgetOwnershipType.Borrowed,
    ) -> bool:
        """在输入区上方显示 dock 内容（``replace=True`` 时输入区不可用）。

        :param ownership: 释放策略，默认 ``Borrowed``——``clearDock()`` 只把控件
            ``setParent(None)`` 交还调用方、不删除；要让本组件负责销毁请传 ``Owned``
        :returns: 是否挂载成功
        """
        return self._input_dock.setWidget(widget, replace=replace, ownership=ownership)

    def clearDock(self) -> None:
        """清空**输入区替换 dock**（宿主自用的 :meth:`setDockWidget` 那一套）。

        不碰审批 dock：审批卡的生命周期由「落定 / 取消 / 删消息」自己驱动。
        """
        self._input_dock.clear()

    def clearPermissionDock(self) -> None:  # noqa: N802
        """撤下审批 dock 上的交互卡（**不改变审批状态**）。"""
        self._permission_dock_part = ""
        self._permission_dock.clear()

    def _on_input_dock_changed(self, has_content: bool) -> None:
        self._input.setEnabled(not self._input_dock.replacesInput())

    def _on_permission_dock_requested(self, messageId: int, partId: str, card) -> None:
        """把交互卡放进审批 dock（不禁用输入区）。
        已有卡时不顶掉（用户可能正答到一半），改为排队计数，落定后再补位。判据是
        dock 实体上有没有卡：宿主直接 ``setCard(None)`` 撤卡不会同步影子字段。
        """
        if self._permission_dock_part and self._permission_dock.card() is not None:
            self._permission_dock.setQueued(self._permission_dock.queued() + 1)
            return
        self._permission_dock_part = str(partId)
        self._permission_dock.setCard(card)

    def _on_permission_settled(self, messageId: int, partId: str) -> None:
        """有审批落定 -> 撤下 dock 上的卡，再把下一张待答的顶上来。
        补位不只在「落定的正是当前卡」时发生：宿主撤卡后 dock 与影子字段都为空，
        任何一次落定都要重新 promote，否则剩余 pending 卡既看不见也点不到。
        """
        if (
            self._permission_dock_part != str(partId)
            and self._permission_dock_part
            and self._permission_dock.card() is not None
        ):
            return
        self._permission_dock_part = ""
        self._promote_next_permission()

    def _promote_next_permission(self) -> None:
        """把时间线上最早那张未答的审批放进 dock（没有就清空 dock）。
        必须全时间线取最早：卡被撤下后 part 仍是 pending，按「已落定消息之后」
        过滤会让它永远回不到 dock。
        """
        pending = []
        for message in self._view.messages():
            bubble = self._view.bubble(message.id)
            if bubble is None:
                continue
            for partId, _permission in bubble.pendingPermissionParts():
                card = bubble.ensureInteractivePermissionCard(partId)
                if card is not None:
                    pending.append((partId, card))
        if not pending:
            self._permission_dock.clear()
            self._permission_dock_part = ""
            return
        partId, card = pending[0]
        self._permission_dock_part = partId
        self._permission_dock.setCard(card)
        self._permission_dock.setQueued(len(pending) - 1)

    def pendingPermissionCards(self) -> list:
        """当前所有仍在 dock 里等用户操作的审批卡（宿主调试用）。"""
        cards = []
        for message in self._view.messages():
            bubble = self._view.bubble(message.id)
            if bubble is None:
                continue
            for partId, _permission in bubble.pendingPermissionParts():
                card = bubble.interactivePermissionCard(partId)
                if card is not None:
                    cards.append(card)
        return cards

    def toolBar(self) -> ElaChatToolBar:
        """获取输入区工具栏（添加自定义工具按钮）。"""
        return self._input.toolBar()

    def actions(self, messageId: int) -> Optional[MessageActions]:
        """获取指定消息的底部操作栏（不存在返回 ``None``）。"""
        bubble = self._view.bubble(messageId)
        return bubble.actions() if bubble is not None else None

    def setUserName(self, name: str) -> None:
        """设置用户消息头部显示名（含已存在消息）。"""
        self._user_title = name or ""
        for message in self._view.messages():
            if message.role == ElaChatRoleType.User:
                self._view.setMessageTitle(message.id, self._user_title)

    def userName(self) -> str:
        """获取用户消息头部显示名。"""
        return self._user_title

    def setAssistantName(self, name: str) -> None:
        """设置助手消息头部显示名 / 模型名（含已存在消息）。"""
        self._assistant_title = name or ""
        for message in self._view.messages():
            if message.role == ElaChatRoleType.Assistant:
                self._view.setMessageTitle(message.id, self._assistant_title)

    def assistantName(self) -> str:
        """获取助手消息头部显示名 / 模型名。"""
        return self._assistant_title

    # 这几个方法各自维护 widget 独占状态（排队队列 / generating 标志 / cleared
    # 信号），view 层没有这些概念。

    def setCurrentSessionId(self, sessionId: str) -> None:
        """设置当前会话（话题）id，便于宿主把本组件对回自己的列表条目。

        纯标记：不做任何切换动作；id 变化时发 ``sessionChanged``，同值不重复发。
        """
        sessionId = sessionId or ""
        if sessionId == self._current_session_id:
            return
        self._current_session_id = sessionId
        self.sessionChanged.emit(sessionId)

    def currentSessionId(self) -> str:
        """获取当前会话（话题）id（未设置返回空串）。"""
        return self._current_session_id
