"""
聊天组件组装（``pyqt6_ela_pro.chat``）。

:class:`ElaChatWidget` = :class:`ElaChatView` + :class:`ElaChatInput`
（工具栏常驻「新建话题 / 上传 / 清空上下文」，清空走 :class:`ElaConfirmDialog`
二次确认）。

**分工（重要）**：本层只管**输入区 + 回合编排**，对外只有这几类：

- 回合：``beginAssistantMessage()`` / ``endAssistantMessage(status=...)`` /
  ``stopGeneration()`` / ``setMessageError()``；
- 提交与排队：``sendUserMessage()`` / ``enqueueMessage()`` / ``sendNextQueued()`` /
  ``sendQueuedNow()`` / ``editQueuedMessage()`` / ``dequeueMessage()`` /
  ``clearQueue()`` / ``setQueueEnabled()``；
- 消息搬运：``addMessage()``（工厂）/ ``removeMessage()`` / ``undoMessage()`` /
  ``undoLastUserMessage()`` / ``regenerateFrom()``；
- 输入区与 dock：``chatInput()`` / ``toolBar()`` / ``inputDock()`` /
  ``setDockWidget()`` / ``clearDock()`` / ``queueDock()`` /
  ``setPlaceholderText()`` / ``setUserName()`` / ``setAssistantName()`` /
  ``setMentionProvider()``；
- 会话标记：``setCurrentSessionId()`` / ``currentSessionId()``（多话题见下）。

**消息内容（正文 / 思考 / 工具 / 分段 / 用量 / 外观）一律在
:class:`ElaChatView` 上**（经 ``chatView()`` 调用）：``appendText()`` /
``addToolCall()`` / ``setStepStats()`` / ``beginBatch()`` /
``setReasoningStyle()`` … 本层**不再转发**它们 —— 两套同名签名混用会把本该是
消息 id 的值落到别的参数上，界面看着正常、数据是错的
（``tests/regression/test_chat_api_contract.py`` 机器守着这条边界）。

**参数约定**：view 层方法的 ``messageId`` 一律**首位必填**；本层残留的少量消息
方法（``setMessageError`` / ``removeMessage``）沿用**末位可选**（缺省 = 当前流式
消息）。

**多话题**：组件是单话题视图。多话题按「一话题一 widget」放大（``ElaTabBar`` +
``QStackedWidget``，见 ``example/chat_session_page.py``）；本层只用
``setCurrentSessionId()/currentSessionId()`` 记一个纯标记 —— **会话列表归宿主**。

典型用法::

    chat = ElaChatWidget(parent)
    binder = ElaChatStreamBinder(chat, worker=my_worker)   # 后端事件 → 组件
    # 有附件就接 Full 变体（多带一份 attachments；重新生成时同样要带上）
    chat.messageSubmittedFull.connect(
        lambda text, attachments: binder.startTurn(text, attachments=attachments)
    )
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Optional
from uuid import uuid4

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from .._ownership import ElaWidgetOwnershipType
from ..ela_confirm_dialog import ElaConfirmDialog
from ..widget_base import ElaThemeWidget
from .blocks import MessageActions
from .docks import ElaChatInputDock, ElaChatPermissionDock, ElaChatQueueDock
from .input import ElaChatInput
from .message import (
    ElaChatMessage,
    ElaChatRoleType,
    ElaChatStatusType,
)
from .toolbar import ElaChatToolBar
from .view import ElaChatView


class ElaChatWidget(ElaThemeWidget):
    """ChatGPT 风格聊天组件（消息列表 + 可扩展输入区）。

    **分工（务必读）**
    ------------------
    本层只管**输入区 + 回合编排**：提交 / 停止 / 撤回 / 重生 / 排队 / dock /
    会话标记。**消息内容**（正文、思考、工具、分段、用量、外观）一律经
    :meth:`chatView` 在 :class:`ElaChatView` 上操作，``messageId`` 在那一层是
    **首位必填**：

    .. code-block:: python

        view = chat.chatView()
        view.appendText(mid, chunk)                     # view 层：messageId 首位必填
        chat.setMessageError("出错了", messageId=mid)    # 本层残留：末位可选

    历史上本层「转发」过 54 个同名方法（把 ``messageId`` 从首位挪到末位）。
    两套签名混用时，本该是消息 id 的值会落到别的参数上 —— 界面看着正常、数据是错的，
    因此**转发层已整体删除**。``tests/regression/test_chat_api_contract.py`` 机器
    守着这条边界：本层不得再长出同名转发方法，view 层 ``messageId`` 必须首位。

    多话题：组件是单话题视图，按「**一话题一 widget**」放大（``ElaTabBar`` +
    ``QStackedWidget``，见 ``example/chat_session_page.py``）；本层只用
    :meth:`setCurrentSessionId` 记一个纯标记，**会话列表由宿主维护**
    （话题的新建 / 归档 / 恢复 / 标签顺序都是宿主的事）。
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
    #: 点击「清空上下文」按钮且**确实有待清内容**时发出（**确认弹框之前**；随后
    #: 组件仍会走默认的「ElaConfirmDialog 确认 → clear()」链路，宿主可在此做
    #: 埋点 / 同步上下文）。空会话直接返回：不弹框、也不发本信号
    clearRequested = pyqtSignal()
    #: 点击「新建话题」按钮（组件不做任何处理，宿主据此开新会话 / 话题）
    newTopicRequested = pyqtSignal()
    #: 点击输入区工具栏的上下文占用圆环（组件不做任何行为，宿主据此弹详情面板等）
    contextUsageClicked = pyqtSignal()
    #: 会话被清空（消息 + 队列 + 生成态）——宿主在此重置**自己的后端会话**
    #: （``worker.reset()``）：后端上下文只有宿主知道，组件清不到
    cleared = pyqtSignal()
    #: 消息动作（参数：消息 id、动作 key）
    messageActionTriggered = pyqtSignal(int, str)
    #: 用户点击「复制」（参数：消息 id）
    copyRequested = pyqtSignal(int)
    #: 用户点击「撤回」（参数：消息 id）
    undoRequested = pyqtSignal(int)
    #: 用户点击「重新生成」（参数：消息 id）
    regenerateRequested = pyqtSignal(int)
    #: 用户在错误卡上点击「重试」（参数：消息 id）—— **同参数重发**，
    #: 与 ``regenerateRequested``（换采样重来）是两件事
    retryRequested = pyqtSignal(int)
    #: 插入了待答复的工具审批（参数：消息 id、``requestId``）—— **组件不在
    #: 这里阻塞**，宿主收到后自行挂起后端（Qt 里阻塞会卡死事件循环）
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
    #: 一条插话到了投递时机（参数：``{id, text, attachments, messageId}``）——
    #: **组件不发送后端请求**，宿主接这个信号把 ``text`` 送进正在跑的那一轮
    steerReady = pyqtSignal(object)
    #: ``@`` 引用被选中（参数：引用 id、展示文本）
    mentionSelected = pyqtSignal(str, str)
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
        self._auto_send_queue = True
        #: 待送插话（steer）；与 ``_queue`` 分开，投递时机完全不同
        self._steer: list = []
        self._steer_enabled = True
        #: 已经为该消息发过 ``generationFinished`` 的 id 集合：一个回合只允许
        #: 一次收尾信号（``_endActiveStream`` 与后续 ``binder.finish`` 都会走到
        #: 收尾）。消息被删 / 清空时同步剪掉，避免 id 复用时被误判成「已收尾」。
        self._finished_generation: set = set()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._view = ElaChatView(self)
        layout.addWidget(self._view, 1)
        self._input_dock = ElaChatInputDock(self)
        layout.addWidget(self._input_dock)
        # 审批交互卡的专用 dock（不占用输入区）
        self._permission_dock = ElaChatPermissionDock(self)
        layout.addWidget(self._permission_dock)
        self._queue_dock = ElaChatQueueDock(self)
        layout.addWidget(self._queue_dock)
        self._input = ElaChatInput(self)
        layout.addWidget(self._input)
        #: 当前占据审批 dock 的 partId（空 = dock 上没有审批卡）
        self._permission_dock_part = ""

        self._view.suggestionClicked.connect(self.suggestionClicked)
        self._view.messageUpdated.connect(self.messageUpdated)
        self._view.copyRequested.connect(self.copyRequested)
        self._view.undoRequested.connect(self.undoRequested)
        self._view.regenerateRequested.connect(self.regenerateRequested)
        self._view.retryRequested.connect(self.retryRequested)
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
        self._input.imagePasted.connect(self.imagePasted)
        self._input.filesAdded.connect(self.filesAdded)
        self._input.clearRequested.connect(self._on_clear_requested)
        self._input.newTopicRequested.connect(self.newTopicRequested)
        self._input.contextUsageClicked.connect(self.contextUsageClicked)
        self._input_dock.changed.connect(self._on_input_dock_changed)
        self._queue_dock.sendRequested.connect(self.sendQueuedNow)
        self._queue_dock.editRequested.connect(self.editQueuedMessage)
        self._queue_dock.removeRequested.connect(self.dequeueMessage)

        # 整块组件都是放置点：拖文件到消息区（含空态 / 排队 dock）也照样进附件
        self.setAcceptDrops(True)

    # -- 拖放（组件任意位置 → 输入区附件） ---------------------------------

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

    # -- 便捷访问 ----------------------------------------------------------

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

        :param ownership: 释放策略，默认 ``Borrowed`` —— ``clearDock()`` 只把控件
            ``setParent(None)`` 交还调用方，**不删除**。要让本组件负责销毁请传
            :attr:`~pyqt6_ela_pro.ElaWidgetOwnershipType.Owned`。
        :returns: 是否挂载成功。
        """
        return self._input_dock.setWidget(widget, replace=replace, ownership=ownership)

    def clearDock(self) -> None:
        """清空**输入区替换 dock**（宿主自用的 :meth:`setDockWidget` 那一套）。

        **不碰审批 dock** —— 审批卡的生命周期由「落定 / 取消 / 删消息」自己驱动，
        宿主手动清输入 dock 不该顺手把用户的审批问句擦掉。要连审批 dock 一起清，
        用 :meth:`clear`（清会话）或直接 :meth:`cancelPendingPermissions`。
        """
        self._input_dock.clear()

    def clearPermissionDock(self) -> None:  # noqa: N802
        """撤下审批 dock 上的交互卡（**不改变审批状态**）。"""
        self._permission_dock_part = ""
        self._permission_dock.clear()

    def _on_input_dock_changed(self, has_content: bool) -> None:
        self._input.setEnabled(not self._input_dock.replacesInput())

    # -- 审批 dock（交互在输入区上方，记录在时间线上） -----------------------

    def _on_permission_dock_requested(self, messageId: int, partId: str, card) -> None:
        """把交互卡放进审批 dock。

        **不禁用输入区** —— 审批不是「顶替输入区」（那是宿主自用的
        :meth:`setDockWidget`），等待期间用户照样能打字。

        dock 上已经有卡时**不顶掉**：用户可能正在答先前那张（草稿都打了一半），
        换一张等于把答案白打一遍。改成排队计数，等前一张落定后由
        :meth:`_promote_next_permission` 按时间线顺序接上。

        判据是 dock **实体上有没有卡**而不是私有影子字段 —— 宿主直接
        ``permissionDock().setCard(None)`` 撤卡的路径不会同步影子字段。
        """
        if self._permission_dock_part and self._permission_dock.card() is not None:
            self._permission_dock.setQueued(self._permission_dock.queued() + 1)
            return
        self._permission_dock_part = str(partId)
        self._permission_dock.setCard(card)

    def _on_permission_settled(self, messageId: int, partId: str) -> None:
        """有审批落定 -> 撤下 dock 上的卡，再把**下一张**待答的顶上来。

        dock 一次只放一张。后到的审批不会把先来的顶掉（用户可能正在答先前那张），
        而是排队等位 —— 落定后按时间线顺序依次呈现。

        **补位不只在「落定的正是当前卡」时发生**：``clearPermissionDock`` /
        宿主直接撤卡后影子字段为空、dock 上也没卡，此时任何一次落定都要重新
        promote，否则剩下的 pending 卡既看不见也点不到（宿主的后端会死等一个
        无法给出的答复）。用户正在答 A（dock 有卡）时 B 落定则不动 A。
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
        """把最早那张还没答的审批放进 dock（没有就清空 dock）。

        **全时间线取最早**：审批卡被 :meth:`clearPermissionDock` 撤下后 part 仍是
        pending，按「已落定消息之后」过滤会让它永远回不到 dock。卡缺失 / 已销毁时
        由气泡按 pending 载荷重建（见 ``ensureInteractivePermissionCard``）。
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

    # -- 发送与流式 --------------------------------------------------------

    def sendUserMessage(
        self,
        text: str,
        attachments=None,
        messageId: Optional[int] = None,
    ) -> Optional[int]:
        """添加用户消息并进入生成状态；返回消息 id（空文本返回 ``None``）。

        ``messageId`` 为幂等键：传入且该消息仍存在时直接返回既有 id，
        **不重复建消息、不重复发 ``messageSubmitted``**。用于消除
        「双击 / 回车+按钮竞态 / 网络超时后重试 / 乐观 UI 对账」导致的
        重复发送（对齐 opencode 的 client-supplied prompt id，见
        ``core/session/input.ts``）。消息被 ``undoMessage`` 移除后，
        同一 id 可以重新发送 —— 那是有意的重发。

        若已有助手消息在流式生成（如排队 dock 的「立即发送」），先把当前
        流式消息按 ``Stopped`` 收尾并发出 ``stopRequested``，保证同一时刻
        只有一个活跃流，避免旧回合分片串入新消息。
        """
        text = (text or "").strip()
        if not text:
            return None
        if messageId is not None:
            existing = self._view.message(messageId)
            if existing is not None:
                return existing.id
        if self._streaming_id is not None:
            # 先就地收尾旧流再通知宿主：宿主可能在 stopRequested 槽里同步
            # 走完 binder.finish(turn)，其末尾会续发排队消息 —— 不压住就会把
            # 队首消息抢在新消息之前发出（顺序错乱，且队首回合立刻被截断）。
            self._endActiveStream(ElaChatStatusType.Stopped)
            with self._autoSendPaused():
                self.stopRequested.emit()
        if messageId is None:
            messageId = self._view.addMessage(ElaChatRoleType.User, text)
        else:
            # 外部 id 且尚不存在：用该 id 建消息（乐观 UI 先行渲染的路径）
            messageId = self._view.addMessage(
                ElaChatRoleType.User, text, messageId=messageId
            )
        if self._user_title:
            self._view.setMessageTitle(messageId, self._user_title)
        if attachments:
            self._view.setMessageAttachments(messageId, attachments)
        self.setGenerating(True)
        self.messageSubmitted.emit(text)
        self.messageSubmittedFull.emit(text, list(attachments or []))
        return messageId

    def _on_input_submitted(self, text: str, attachments: list) -> None:
        if self._generating and self._queue_enabled:
            self.enqueueMessage(text, attachments)
            return
        self.sendUserMessage(text, attachments)

    @contextmanager
    def _autoSendPaused(self):  # noqa: N802 (与 Qt 命名一致)
        """临时关掉 ``autoSendQueue``（``clear`` / 换流期间）。

        宿主在 ``stopRequested`` 槽里会同步走完收尾（``binder.finish`` →
        ``endAssistantMessage``），而后者末尾**无条件**排下一条排队消息。放在
        「换流」与「清空会话」里，这一步等于：用户点 B 的「立即发送」，A 被抢在
        B 前面发了出去（还立刻被 B 截断）；用户点清空，排队消息已经被送进后端
        才被抹掉（白跑一轮）。照抄 ``binder.abortTurn`` 的处理方式。
        """
        autoSend = self._auto_send_queue
        self._auto_send_queue = False
        try:
            yield
        finally:
            self._auto_send_queue = autoSend

    # -- 排队（follow-up） -------------------------------------------------

    def setQueueEnabled(self, on: bool) -> None:
        """设置生成中提交是否进入排队（默认开启）。"""
        self._queue_enabled = bool(on)
        self._input.setQueueEnabled(self._queue_enabled)

    def queueEnabled(self) -> bool:
        """生成中提交是否进入排队。"""
        return self._queue_enabled

    def enqueueMessage(
        self,
        text: str,
        attachments=None,
        messageId: Optional[int] = None,
    ) -> Optional[str]:
        """把消息加入排队 dock；返回排队 id（空文本返回 ``None``）。

        ``messageId`` 为幂等键：同 id 重复入队只保留一条（消除双击 / 竞态）。
        """
        text = (text or "").strip()
        if not text:
            return None
        if messageId is not None:
            for item in self._queue:
                if item.get("messageId") == messageId:
                    return item["id"]
        queueId = uuid4().hex[:12]
        self._queue.append(
            {
                "id": queueId,
                "text": text,
                "attachments": list(attachments or []),
                "messageId": messageId,
            }
        )
        self._sync_queue()
        return queueId

    def queuedMessages(self) -> list:
        """排队消息快照列表。"""
        return [dict(item) for item in self._queue]

    def queueCount(self) -> int:
        """排队消息条数。"""
        return len(self._queue)

    def dequeueMessage(self, queueId: str) -> bool:
        """移除指定排队消息。"""
        for index, item in enumerate(self._queue):
            if item["id"] == queueId:
                self._queue.pop(index)
                self._sync_queue()
                return True
        return False

    def sendQueuedNow(self, queueId: str) -> bool:
        """立即发送指定排队消息（出队并作为新消息提交）。

        **只发被点的那一条**：其余排队消息保持排队（等本回合结束后自动续发）——
        在途流的收尾链（``stopRequested`` → 宿主 ``binder.finish``）末尾本来会
        排下一条排队消息，这条路径上必须压住，否则队首会抢在前面发出去并立刻
        被这条截断。
        """
        for index, item in enumerate(self._queue):
            if item["id"] != queueId:
                continue
            self._queue.pop(index)
            self._sync_queue()
            self.sendUserMessage(
                item["text"], item["attachments"], item.get("messageId")
            )
            return True
        return False

    def editQueuedMessage(self, queueId: str) -> bool:
        """把排队消息回填到输入框（出队）。"""
        for index, item in enumerate(self._queue):
            if item["id"] != queueId:
                continue
            self._queue.pop(index)
            self._sync_queue()
            self._input.setText(item["text"])
            if item["attachments"]:
                self._input.setAttachments(item["attachments"])
            self._input.textEdit().setFocus()
            return True
        return False

    def clearQueue(self) -> None:
        """清空排队消息。"""
        if not self._queue:
            return
        self._queue.clear()
        self._sync_queue()

    # -- steer（生成中插话）------------------------------------------------

    def steerMessage(
        self,
        text: str,
        attachments=None,
        messageId: Optional[str] = None,
    ) -> Optional[str]:
        """生成中**插话**：把新指令送进正在跑的这一轮，而不是排队等它跑完。

        对齐 opencode 的 ``Delivery = "steer" | "queue"``（``schema/session-inbox.ts``），
        那边的 prompt **默认就是 steer**：在下一个 step 安全边界打断并插入。
        agent 场景下「等这一轮跑完再发下一句」体验很差 —— 模型可能跑十几次
        工具调用，用户想纠偏却只能干等。

        插话在 :meth:`ElaChatStreamBinder.beginRound` 之后（也就是 ``beginStep``
        这个天然安全边界）由 binder 触发 :meth:`drainSteer` 送进后端，并在
        同一条助手消息里留一行 ``↳`` 回执。**组件不负责把文本送进后端** ——
        那是宿主的事（组件不知道后端是什么）。

        :returns: steer id（空文本返回 ``None``）
        """
        text = (text or "").strip()
        if not text:
            return None
        if messageId is not None:
            for item in self._steer:
                if item.get("messageId") == messageId:
                    return item["id"]
        steerId = uuid4().hex[:12]
        self._steer.append(
            {
                "id": steerId,
                "text": text,
                "attachments": list(attachments or []),
                "messageId": messageId,
            }
        )
        self.steerChanged.emit(self.steerMessages())
        return steerId

    def steerMessages(self) -> list:
        """待送插话快照列表。"""
        return [dict(item) for item in self._steer]

    def steerCount(self) -> int:
        """待送插话条数。"""
        return len(self._steer)

    def dequeueSteer(self, steerId: str) -> bool:
        """丢弃指定插话（用户改主意了）。"""
        for index, item in enumerate(self._steer):
            if item["id"] == steerId:
                self._steer.pop(index)
                self.steerChanged.emit(self.steerMessages())
                return True
        return False

    def clearSteer(self) -> None:
        """清空待送插话。"""
        if not self._steer:
            return
        self._steer.clear()
        self.steerChanged.emit(self.steerMessages())

    def setSteerEnabled(self, on: bool) -> None:
        """是否在 step 边界自动投递插话（默认开）。

        关掉后插话只堆积，宿主得自己调 :meth:`drainSteer`。
        """
        self._steer_enabled = bool(on)

    def steerEnabled(self) -> bool:
        """是否在 step 边界自动投递插话。"""
        return self._steer_enabled

    def drainSteer(self) -> Optional[dict]:
        """取出并投递**一条**待送插话；没有则返回 ``None``。

        投递 = 在当前流式消息里留一行回执 + 发 :attr:`steerReady`。
        **组件不发送任何后端请求** —— 宿主接 :attr:`steerReady` 自行把文本
        送进正在跑的那一轮。

        一次只投一条：opencode 的投递词汇表规定「在空闲边界按 steer 优先、
        其余一次只投一条」，避免把用户的三句话一次性糊给模型。
        """
        if not self._steer:
            return None
        item = self._steer.pop(0)
        self.steerChanged.emit(self.steerMessages())
        messageId = self.streamingMessageId() or self._streaming_id
        if messageId is not None:
            self._view.addSteerNotice(messageId, item["text"])
        payload = dict(item)
        payload["messageId"] = messageId
        self.steerReady.emit(payload)
        return payload

    def _hasClearableContent(self) -> bool:
        """会话是否有东西可清（消息 / 排队消息 / 生成中）——「清空」的前提。"""
        return bool(self._view.count() or self._queue or self._generating)

    def _on_clear_requested(self) -> None:
        # 空会话直接返回：不弹框，也不发 clearRequested —— 宿主拿它做「等待确认」
        # 之类的提示 / 埋点，发了却什么都不弹，提示就永远挂在那儿
        if not self._hasClearableContent():
            return
        # 先发公共信号通知宿主，再走默认「弹框确认 → 清空」链路
        self.clearRequested.emit()
        self.requestClear()

    def requestClear(self) -> None:
        """「清空上下文」入口：先弹 :class:`ElaConfirmDialog` 确认再 :meth:`clear`。

        会话是**不可撤销**的（清掉就没了），所以按钮点击先弹框确认，避免误触
        丢失历史。确认后走标准 :meth:`clear` 链路并发出 ``cleared``。空会话
        直接返回（不弹框、不发 ``clearRequested``）。

        锚点是**输入区**而不是整个聊天组件（对齐 ``example`` 里的用法：锚点
        必须是一个具体控件）—— 输入区贴在窗口底部，弹框放它下方会算到屏幕
        外，故用 ``position="top"`` 摆在输入卡片上方（放不下时弹框自身会翻边
        / 夹回工作区，见 :meth:`ElaConfirmDialog._positionDialog`）。
        """
        if not self._hasClearableContent():
            return  # 已经是空会话，无需确认
        confirmed = ElaConfirmDialog.show(
            self._input,
            "清空上下文",
            "确定要清空当前对话吗？此操作不可撤销。",
            position="top",
        )
        if confirmed:
            self.clear()

    # -- 会话级动作（widget 独有职责，不是 view 的转发）---------------------
    #
    # 下面三个方法看着只调一次 view，但它们各自还维护 **widget 独占的状态**
    # （排队队列 / generating 标志 / cleared 信号），view 层没有这些概念 ——
    # 所以它们留在本层，而不是被当作转发层删掉。

    def clear(self) -> None:
        """清空整个会话：中止生成 -> 停流 -> 清队列 -> 清消息 -> 发 ``cleared``。

        顺序要紧：先 ``stopRequested`` 让宿主有机会 cancel 后端，再停流，
        否则后端还在往已清空的消息里发分片。**整段都关掉 ``autoSendQueue``**：
        宿主的收尾（``binder.finish``）会同步排下一条排队消息，不关的话这条
        消息会被送进后端、随即又被清掉 —— 白跑一轮，界面还看不出发生过什么。

        只清**组件侧**（界面 / 队列 / 生成态）：后端会话历史归宿主，宿主接
        ``cleared`` 后自行 ``worker.reset()`` —— 少了这步界面是空的、模型
        却还带着清空前的上下文。
        """
        with self._autoSendPaused():
            if self._generating or self._streaming_id is not None:
                self.stopGeneration()
            self._streaming_id = None
            self.setGenerating(False)
            self.clearQueue()
            # 插话属于**被中止的那一轮**：留着会在新会话的下一个 step 边界
            # 被自动投递（旧指令静默重放给模型），必须一起清
            self.clearSteer()
            self._finished_generation.clear()
            # 会话没了，两个 dock 都要清（审批卡对应的消息已经不存在）
            self.clearDock()
            self.clearPermissionDock()
            self._view.clear()
        self.cleared.emit()

    def setMessageError(
        self, message: str, messageId: Optional[int] = None, errorType: str = ""
    ) -> None:
        """给消息设置错误文本与类型；若是当前流式消息则同时结束生成状态。

        错误回合已经结束，``generating`` 必须随之落下 —— 否则状态栏一直停在
        「生成中」，且 ``autoSendQueue`` 永远排不出下一条。

        这是 widget 保留的三个「不是转发」的方法之一（另两个是 ``clear`` /
        ``removeMessage``）：它维护 widget 独占的 ``generating`` 状态。
        """
        target = self._streaming_id if messageId is None else messageId
        if target is None:
            return
        self._view.setMessageError(target, message, errorType)
        if message and target == self._streaming_id:
            self._finishErrorTurn(target, ElaChatStatusType.Error)

    def removeMessage(self, messageId: int) -> None:
        """移除指定消息；若是当前流式消息则先结束生成状态。"""
        if messageId == self._streaming_id:
            self._streaming_id = None
            self.setGenerating(False)
        # 删消息前必须先 abort 该消息里的未答复审批，否则 dock 上会留下一张
        # 指向已不存在消息的死卡（用户点了没有任何回音）。
        bubble = self._view.bubble(messageId)
        if bubble is not None:
            bubble.cancelPendingPermissions()
        self._finished_generation.discard(messageId)
        self._view.removeMessage(messageId)

    def _sync_queue(self) -> None:
        self._queue_dock.setMessages(self._queue)
        self.queueChanged.emit(self.queuedMessages())

    def beginAssistantMessage(self) -> int:
        """开始一条助手流式消息；返回消息 id。

        防御：若已有消息在流式生成（宿主直接调用且未先结束），先把上一条
        按 ``Stopped`` 收尾（不发 ``stopRequested``、不触发排队续发），
        保证同一时刻只有一个活跃流。
        """
        if self._streaming_id is not None:
            self._endActiveStream(ElaChatStatusType.Stopped)
        messageId = self._view.beginMessage(ElaChatRoleType.Assistant)
        if self._assistant_title:
            self._view.setMessageTitle(messageId, self._assistant_title)
        self._streaming_id = messageId
        self.setGenerating(True)
        self.generationStarted.emit(messageId)
        return messageId

    # -- 多步骤 API --------------------------------------------------------

    def stepCount(self, messageId: Optional[int] = None) -> int:
        """获取指定消息（默认最后一条）的步骤数。"""
        target = self._resolve_message_id(messageId)
        if target is None:
            return 0
        message = self._view.message(target)
        return message.stepCount if message is not None else 0

    def toolPanels(self, messageId: Optional[int] = None) -> list:
        """获取指定消息（默认最后一条）的各步骤工具面板。"""
        target = self._resolve_message_id(messageId)
        bubble = self._view.bubble(target) if target is not None else None
        return bubble.toolPanels() if bubble is not None else []

    def endAssistantMessage(
        self,
        messageId: Optional[int] = None,
        status: str = ElaChatStatusType.Done,
    ) -> Optional[int]:
        """结束助手消息（默认当前流式消息）；返回消息 id。

        先发 ``generationFinished``（宿主可更新状态栏）；若开启
        ``autoSendQueue``（默认），随后自动发送队首排队消息。

        **幂等**：消息已被 ``stopGeneration`` / ``_endActiveStream`` 收尾过时，
        只补状态与排队续发，不再重复 ``endMessage`` / ``generationFinished``
        （一次回合一次收尾信号）。
        """
        target = self._streaming_id if messageId is None else messageId
        if target is None:
            self.setGenerating(False)
            if self._auto_send_queue:
                self.sendNextQueued()
            return None
        message = self._view.message(target)
        if (
            message is not None
            and message.status == ElaChatStatusType.Error
            and status == ElaChatStatusType.Done
        ):
            # 已出错的消息不被缺省的「完成」覆盖：按实际状态补发收尾信号
            return self._finishErrorTurn(target, ElaChatStatusType.Error)
        if message is not None and message.isStreaming:
            self._view.endMessage(target, status)
        if target == self._streaming_id:
            self._streaming_id = None
        self.setGenerating(False)
        self._emit_generation_finished(target, status)
        if self._auto_send_queue:
            self.sendNextQueued()
        return target

    def _emit_generation_finished(self, target: int, status: str) -> None:
        """发 ``generationFinished``（**同一条消息只发一次**）。

        ``_endActiveStream``（停止 / 换流）与随后的 ``binder.finish`` 都会走到
        收尾，不去重宿主会收到两次；消息被删除时调用方负责剪掉记录。
        """
        if target in self._finished_generation:
            return
        self._finished_generation.add(target)
        self.generationFinished.emit(target, status)

    def _finishErrorTurn(self, target: int, status: str) -> int:
        """错误回合的收尾：落 generating、发 ``generationFinished``、排空队列。

        ``setMessageError`` 与 ``endAssistantMessage`` 都要走这里 —— 错误回合
        已经结束，但**仍然要发** ``generationFinished`` 并排空队列，否则
        ``autoSendQueue`` 永远发不出下一条、宿主状态栏一直停在「生成中」。
        """
        if target == self._streaming_id:
            self._streaming_id = None
        self.setGenerating(False)
        self._emit_generation_finished(target, status)
        if self._auto_send_queue:
            self.sendNextQueued()
        return target

    def _endActiveStream(self, status: str) -> Optional[int]:
        """结束当前流式消息（不发 ``stopRequested``、不触发排队续发）。

        供 :meth:`sendUserMessage` / :meth:`beginAssistantMessage` 在开始
        新流前收尾旧流使用；返回被结束的消息 id（无流式消息返回 ``None``）。
        """
        target = self._streaming_id
        if target is None:
            return None
        self._streaming_id = None
        message = self._view.message(target)
        if message is not None and message.status == ElaChatStatusType.Error:
            # 错误来自 ``view.setMessageError``（widget 并不知道）：不能再用
            # 缺省的 ``Stopped`` 覆盖，收尾信号与文案都按实际状态走
            status = ElaChatStatusType.Error
        if message is None or message.isStreaming:
            self._view.endMessage(target, status)
        self.setGenerating(False)
        self._emit_generation_finished(target, status)
        return target

    # -- 输入区扩展（补全） ------------------------------------------------

    def setMentionProvider(self, provider) -> None:
        """设置 ``@`` 引用候选提供者（``provider(query) -> list``）。"""
        self._input.setMentionProvider(provider)

    def mentions(self) -> list:
        """当前输入中仍有效的 ``@`` 引用 id 列表。"""
        return self._input.mentions()

    def streamingMessageId(self) -> Optional[int]:
        """当前正在流式生成的消息 id；无则 ``None``。

        与 :meth:`isGenerating` 相互独立：``setMessageError`` /
        ``removeMessage`` / ``undoMessage`` 等会把 ``_generating`` 置 False 但
        仍可能留下未收尾的流式消息，宿主（如 ``ElaChatStreamBinder.finish``）
        需要据此判断是否还要收尾。
        """
        return self._streaming_id

    def _resolve_message_id(self, messageId: Optional[int]) -> Optional[int]:
        if messageId is not None:
            return messageId
        if self._streaming_id is not None:
            return self._streaming_id
        last = self._view.lastMessage()
        return last.id if last is not None else None

    def stopGeneration(self) -> None:
        """请求停止生成：就地收尾当前流式消息，再发 ``stopRequested``。"""
        if not self._generating and self._streaming_id is None:
            return
        # 先就地收尾旧流再通知宿主：stopRequested 的宿主槽往往会
        # cancel() + finish()，而 finish() 之后会自动 sendNextQueued() ->
        # beginAssistantMessage()，此时 _streaming_id 已指向**新**消息。
        # 原先「先 emit 再 endAssistantMessage(self._streaming_id)」的顺序会把
        # 刚自动发出的续发回合立刻置成 stopped。
        target = self._endActiveStream(ElaChatStatusType.Stopped)
        if target is None:
            self.setGenerating(False)
        self.stopRequested.emit()

    def setGenerating(self, on: bool) -> None:
        """设置生成状态（输入区按钮在发送/停止间切换）。"""
        self._generating = bool(on)
        self._input.setGenerating(self._generating)

    def isGenerating(self) -> bool:
        """是否正在生成。"""
        return self._generating

    # -- 消息管理 ----------------------------------------------------------

    def addMessage(self, role: str, text: str = "") -> int:
        """添加一条普通消息（用户 / 助手 / 系统）；返回消息 id。"""
        messageId = self._view.addMessage(role, text)
        if role == ElaChatRoleType.User and self._user_title:
            self._view.setMessageTitle(messageId, self._user_title)
        elif role == ElaChatRoleType.Assistant and self._assistant_title:
            self._view.setMessageTitle(messageId, self._assistant_title)
        return messageId

    # -- 存储接入（读写对称：不接存储就不用碰 chatView） --------------------

    def undoMessage(self, messageId: int) -> Optional[ElaChatMessage]:
        """撤回消息：删除该条及其后全部消息，并把原文 / 附件回填输入框。

        **只对用户消息生效**（撤回 = 收回自己发的那条）：目标不是用户消息
        （助手回答 / 系统消息）或不存在时返回 ``None`` 且不做任何改动 ——
        否则会把 AI 的回复删掉、再把它的文本回填进输入框。要删回答用
        ``chatView().removeMessage(id)``，重发回答用 :meth:`regenerateFrom`。

        :param messageId: 被撤回的**用户**消息 id（通常为触发撤回按钮的消息）
        :returns: 被撤回的目标消息快照（不存在 / 非用户消息返回 ``None``）；
            宿主可据此中止后端流并回滚自身会话历史
        """
        target = self._view.message(messageId)
        if target is None or not target.isUser:
            return None
        if self._streaming_id is not None and self._streaming_id >= messageId:
            self._streaming_id = None
            self.setGenerating(False)
        self._view.removeMessagesFrom(messageId)
        self._finished_generation = {
            item for item in self._finished_generation if item < messageId
        }
        self._input.setText(target.text)
        self._input.setAttachments(target.attachments)
        return target

    def undoLastUserMessage(self) -> Optional[ElaChatMessage]:
        """撤回**最后一条用户消息**：删除该条及其后全部消息，并把原文 / 附件
        回填输入框。

        这是「撤回最后一条消息」的正确入口：自己从时间线末尾往前找最近一条
        用户消息（跳过其后的助手回答 / 系统消息）。直接对 ``messages()[-1]``
        （多半是助手回答）调 :meth:`undoMessage` 会被拒绝（返回 ``None``），
        而不是删掉 AI 的回复。

        :returns: 被撤回的用户消息快照；没有用户消息时返回 ``None`` 且不做改动
        """
        target = None
        for message in self._view.messages():
            if message.isUser:
                target = message
        if target is None:
            return None
        return self.undoMessage(target.id)

    def regenerateFrom(self, messageId: int) -> Optional[ElaChatMessage]:
        """重新生成准备：删除该回答及其后消息，返回其之前的用户消息快照
        （宿主随后 ``beginAssistantMessage()`` 并重跑后端）；找不到前置用户消息时
        不删除任何消息并返回 ``None``。
        """
        userMessage = None
        for message in self._view.messages():
            if message.id >= messageId:
                break
            if message.isUser:
                userMessage = message
        if userMessage is None:
            return None
        if self._streaming_id is not None and self._streaming_id >= messageId:
            self._streaming_id = None
            self.setGenerating(False)
        self._view.removeMessagesFrom(messageId)
        self._finished_generation = {
            item for item in self._finished_generation if item < messageId
        }
        return userMessage

    def retryMessage(self, messageId: int) -> Optional[ElaChatMessage]:
        """重试准备：清掉该回答的错误（状态落成 ``Stopped``，保留失败记录），
        **保留消息位置**。

        与 :meth:`regenerateFrom` 的区别是本方法**不删消息** —— 「重试」是
        同参数重发：失败的那条助手消息保留在时间线上（错误清空、状态落成
        ``Stopped``，作为失败记录），宿主拿到返回的提问快照后调
        ``beginAssistantMessage()`` **新建**一条回答。删掉旧消息重建会让
        「重试」看起来像「重新生成」，也会打断用户正在读的上下文。

        :param messageId: 被重试的助手消息 id
        :returns: 提问的用户消息快照；找不到前置用户消息时返回 ``None``
            （此时**不做任何改动**，让宿主自己决定）
        """
        userMessage = None
        for message in self._view.messages():
            if message.id >= messageId:
                break
            if message.isUser:
                userMessage = message
        if userMessage is None:
            return None
        if self._streaming_id == messageId:
            self._streaming_id = None
            self.setGenerating(False)
        self._view.clearMessageError(messageId)
        return userMessage

    def sendNextQueued(self) -> bool:
        """发送队首排队消息（空闲且有排队时）；返回是否已发送。"""
        if self.isGenerating():
            return False
        queued = self.queuedMessages()
        if not queued:
            return False
        self.sendQueuedNow(queued[0]["id"])
        return True

    def setAutoSendQueue(self, on: bool = True) -> None:
        """设置回合结束后是否自动发送队首排队消息（默认开启）。"""
        self._auto_send_queue = bool(on)

    def autoSendQueue(self) -> bool:
        """回合结束后是否自动发送队首排队消息。"""
        return self._auto_send_queue

    # -- 会话标记（多话题：列表归宿主，这里只记「本页属于哪个话题」） --------

    def setCurrentSessionId(self, sessionId: str) -> None:
        """设置当前会话（话题）id，便于宿主把本组件对回自己的列表条目。

        **纯标记**：组件不做任何切换动作（不清消息、不建会话、不碰后端）——
        多话题按「一话题一 widget」放大，切页由宿主用 ``QStackedWidget`` /
        ``ElaTabBar`` 完成，见 ``example/chat_session_page.py``。
        id 变化时发出 ``sessionChanged``；同值重复设置不重复发。
        """
        sessionId = sessionId or ""
        if sessionId == self._current_session_id:
            return
        self._current_session_id = sessionId
        self.sessionChanged.emit(sessionId)

    def currentSessionId(self) -> str:
        """获取当前会话（话题）id（未设置返回空串）。"""
        return self._current_session_id

    # -- 外观与空态 --------------------------------------------------------

    def setPlaceholderText(self, text: str) -> None:
        """设置输入框占位文案。"""
        self._input.setPlaceholderText(text)

    def placeholderText(self) -> str:
        """获取输入框占位文案。"""
        return self._input.placeholderText()
