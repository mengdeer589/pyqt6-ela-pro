"""
聊天消息列表视图（``pyqt6_ela_pro.chat``）。

:class:`ElaChatView` 把 :class:`~pyqt6_ela_pro.chat.bubble.ElaChatBubble` 按顺序排布
在外层滚动区中，提供：

- 消息增删改与只读快照 ``messages()``（助手消息含步骤化 ``parts`` 时间线，派生
  ``text`` / ``reasoning`` / ``tool_calls`` / ``stats``）；
- 多步骤流式 API：``beginStep`` / ``beginText`` / ``appendText`` / ``endText``、
  思考（``beginReasoning`` / ``appendReasoning`` / ``endReasoning``）、工具调用
  （``addToolCall`` / ``setToolCallResult``，每步独立工具面板）、步骤用量
  （``setStepStats``）与错误（``setMessageError``）；
- 消息动作透传：``copyRequested`` / ``undoRequested`` / ``regenerateRequested`` /
  ``attachmentClicked``（均带消息 id）；
- 贴底自动跟随：用户上滚后暂停跟随并显示「回到底部」浮动按钮；
- 大消息量：交互 resize 延迟重排（``setResizeReflowDeferred``）、批量渐进渲染
  （``beginBatch`` / ``endBatch``）与视口外查看器挂起（``setViewportSuspension``）；
- 空态：标题 / 副标题 / 建议按钮列表。

**参数约定**：本层所有面向消息的方法以 ``messageId`` 作为**首位**参数。
"""

from __future__ import annotations

import time
from collections import Counter, deque
from dataclasses import replace
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import QElapsedTimer, QEvent, QObject, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QPalette
from PyQt6.QtWidgets import (
    QAbstractScrollArea,
    QFrame,
    QLabel,
    QScrollBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from PyQt6ElaWidgetTools import (
    ElaIconButton,
    ElaIconType,
    ElaScrollArea,
    ElaThemeType,
    eTheme,
)

from .._styles import setTextColor
from ..ela_button import ElaButton
from ..tooltips import ElaToolTipPositionType, set_tooltip
from ..widget_base import ElaThemeWidget
from ._theme import (
    muted_color,
    text_color,
)
from .blocks import (
    AVATAR_DEFAULT_SHAPE,
    ElaChatAvatarSource,
    normalizeAvatarShape,
    toolDefaultOpen,
)
from .bubble import DISCLAIMER_TEXT, ElaChatBubble
from .message import (
    ElaChatMessage,
    ElaChatPermission,
    ElaChatReasoningStyleType,
    ElaChatRoleType,
    ElaChatStats,
    ElaChatStatusType,
)
from .session import SESSION_SCHEMA_VERSION, ElaChatSessionInfo, ElaChatSessionStats

#: 判定「贴底」的容差（像素，对齐 opencode 的 10px）
_BOTTOM_MARGIN = 10
#: 「回到底部」按钮显示阈值下限（离底距离，像素）
_JUMP_MIN_DISTANCE = 400
#: 展开 / 收起工具卡后暂停贴底跟随的时长（毫秒）
_FOLLOW_HOLD_MS = 250
#: 滚动容器内容边距（左、上、右、下）
_CONTENT_MARGIN = (10, 12, 10, 12)
#: 消息间距（Editorial Agent 节奏：turn 之间更松弛）
_MESSAGE_SPACING = 20
#: 浮动按钮距右下角边距
_FLOAT_MARGIN = 16
#: 交互 resize 延迟重排：停手多久后统一 reflow（毫秒）
_RESIZE_REFLOW_DELAY_MS = 120
#: 交互 resize 延迟重排的最小消息数（小会话保持实时 reflow）
_RESIZE_REFLOW_MIN_MESSAGES = 50
#: 视口外查看器挂起的最小消息数
_SUSPEND_MIN_MESSAGES = 80
#: 挂起判定余量（视口高度的倍数，上下各留）
_SUSPEND_MARGIN_VIEWPORTS = 2.0
#: 挂起判定的合并间隔（毫秒）
_SUSPEND_INTERVAL_MS = 100
#: 批量渐进渲染的时间片预算（毫秒）
_BATCH_RENDER_BUDGET_MS = 8
#: 助手消息阅读宽度（像素，0 表示不限；宿主可 setContentMaxWidth 收紧）
_CONTENT_MAX_WIDTH = 0


def _with_created_at(message: ElaChatMessage, createdAt: float) -> ElaChatMessage:
    """替换快照的创建时间（恢复历史消息时保留原时间戳）。"""
    return replace(message, created_at=float(createdAt))


class _ChatContent(ElaThemeWidget):
    """消息区内容容器。

    显式使用 ``BasicPress`` 主题底色（浅色 ``#f7f7f7`` / 深色 ``#3a3a3a``，
    与头部、输入区一致）并开启 ``autoFillBackground``：
    宿主未切换 Qt 应用调色板时（Ela 框架只换 Ela 主题色），
    普通 QWidget 会沿用浅色调色板，导致暗色模式下消息区发白。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAutoFillBackground(True)
        self._min_height_cache: Optional[int] = None
        self._apply_theme()

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        super()._onThemeChanged(mode)
        self._apply_theme()

    def event(self, event) -> bool:  # noqa: N802 (Qt 命名)
        if event.type() == QEvent.Type.LayoutRequest:
            self._min_height_cache = None
        return super().event(event)

    def minimumSizeHint(self):  # noqa: N802 (Qt 命名)
        """高度不小于内容布局的最小高度（避免滚动区把消息挤扁导致抖动）。

        宽度不设下限，避免长代码块等撑出横向滚动；高度按布局失效事件缓存
        （``LayoutRequest`` 时失效），避免每次查询都遍历全部消息。
        """
        hint = super().minimumSizeHint()
        if self.layout() is not None:
            if self._min_height_cache is None:
                self._min_height_cache = self.layout().minimumSize().height()
            hint.setHeight(self._min_height_cache)
        hint.setWidth(0)
        return hint

    def _apply_theme(self) -> None:
        color = eTheme.getThemeColor(
            self._theme_mode, ElaThemeType.ThemeColor.BasicPress
        )
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, color)
        palette.setColor(QPalette.ColorRole.Base, color)
        self.setPalette(palette)
        self.update()


class _NestedScrollGuard(QObject):
    """嵌套滚动防脱离：嵌套滚动区到达边界时吞掉滚轮事件，避免外层脱离贴底。"""

    def __init__(self, area: QAbstractScrollArea, parent=None) -> None:
        super().__init__(parent or area)
        self._area = area

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt 命名)
        if event.type() == QEvent.Type.Wheel:
            bar = self._area.verticalScrollBar()
            if bar is not None and bar.isVisible():
                delta = event.angleDelta().y()
                if delta < 0 and bar.value() >= bar.maximum():
                    return True
                if delta > 0 and bar.value() <= bar.minimum():
                    return True
        return super().eventFilter(obj, event)


class _EmptyState(ElaThemeWidget):
    """空态：标题 + 副标题 + 建议按钮列表。"""

    suggestionClicked = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._title = "开始新的对话"
        self._subtitle = "输入问题，或从下面的建议开始。"
        self._suggestions: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 40, 16, 24)
        layout.setSpacing(8)
        layout.addStretch(1)

        self._title_label = QLabel(self)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setWordWrap(True)
        layout.addWidget(self._title_label)

        self._subtitle_label = QLabel(self)
        self._subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._subtitle_label.setWordWrap(True)
        layout.addWidget(self._subtitle_label)

        self._suggestions_box = QVBoxLayout()
        self._suggestions_box.setContentsMargins(0, 12, 0, 0)
        self._suggestions_box.setSpacing(8)
        layout.addLayout(self._suggestions_box)
        layout.addStretch(2)

        self._apply_theme()

    def setTitle(self, text: str) -> None:
        """设置空态标题。"""
        self._title = text or ""
        self._title_label.setText(self._title)

    def title(self) -> str:
        """获取空态标题。"""
        return self._title

    def setSubtitle(self, text: str) -> None:
        """设置空态副标题。"""
        self._subtitle = text or ""
        self._subtitle_label.setText(self._subtitle)

    def subtitle(self) -> str:
        """获取空态副标题。"""
        return self._subtitle

    def setSuggestions(self, suggestions: Optional[list]) -> None:
        """设置建议按钮列表（点击发出 ``suggestionClicked``）。"""
        while self._suggestions_box.count():
            item = self._suggestions_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._suggestions = [str(s) for s in (suggestions or []) if str(s).strip()]
        for text in self._suggestions:
            button = ElaButton(text, variant="outlined", parent=self)
            button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            button.clicked.connect(
                lambda _checked=False, value=text: self.suggestionClicked.emit(value)
            )
            self._suggestions_box.addWidget(button, 0, Qt.AlignmentFlag.AlignHCenter)
        self._suggestions_box.setEnabled(bool(self._suggestions))

    def suggestions(self) -> list:
        """获取建议列表。"""
        return list(self._suggestions)

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        super()._onThemeChanged(mode)
        self._apply_theme()

    def _apply_theme(self) -> None:
        mode = self._theme_mode
        setTextColor(self._title_label, text_color(mode))
        title_font = QFont(self._title_label.font())
        title_font.setPixelSize(19)
        title_font.setWeight(QFont.Weight.DemiBold)
        self._title_label.setFont(title_font)
        setTextColor(self._subtitle_label, muted_color(mode, 0.5))
        subtitle_font = QFont(self._subtitle_label.font())
        subtitle_font.setPixelSize(13)
        self._subtitle_label.setFont(subtitle_font)


class ElaChatView(ElaThemeWidget):
    """聊天消息列表视图（可独立使用，也可由 ``ElaChatWidget`` 组装）。

    **API 分三类（读代码前先分清）**

    1. **宿主 API** —— 建 / 改 / 读消息与外观：``addMessage`` /
       ``addMessageFromDict`` / ``restoreMessages`` / ``removeMessage`` /
       ``removeMessagesFrom`` / ``appendText`` / ``beginText`` / ``endText`` /
       ``beginReasoning`` / ``appendReasoning`` / ``endReasoning`` /
       ``addToolCall`` / ``setToolCallResult`` / ``setStepStats`` /
       ``setMessageTitle`` / ``setMessageTimestamp`` / ``setMessageDuration`` /
       ``setMessageError`` / ``setMessageAttachments`` / ``setReasoningStyle`` /
       ``setStatsMode`` / ``setToolGrouping`` / ``setAvatar*`` /
       ``setCopyNotificationEnabled`` / ``setContentMaxWidth`` / ``exportSession`` /
       ``importSession`` / ``messages`` / ``message`` / ``lastMessage`` / ``count``。
       所有方法 ``messageId`` **首位必填**（唯一一套约定，见 ``ElaChatWidget``）。
    2. **性能开关（内部 / 只在必要时用）**：``beginBatch`` / ``endBatch``
       （历史加载骨架 + 渐进渲染）、``setViewportSuspension``
       （视口外挂起重型查看器）、``setResizeReflowDeferred``
       （交互 resize 延迟重排）。它们是**渲染调度**，不是业务接口。
       **单条消息的延迟渲染开关（``setRenderDeferred`` / ``renderDeferred`` /
       ``flushRender`` / ``hasPendingRender``）只在
       :class:`~pyqt6_ela_pro.chat.bubble.ElaChatBubble` 上**，view 只在批量
       渐进渲染路径里内部调用（``_create_message`` / ``_process_render_queue``），
       宿主要逐条控制得经 ``bubble(messageId)`` 取。
    3. **内部协议（view ↔ bubble / 供组件内部使用）**：``bubble`` /
       ``contentWidget`` / ``guardNestedScroll`` / ``holdFollow`` /
       ``followHeld`` / ``jumpThreshold`` / ``isBatchActive`` 等，宿主一般不需要。

    底层一条不变量：``parts`` 是消息的唯一真源，``text`` / ``reasoning`` /
    ``tool_calls`` / ``stats`` 由 ``ElaChatMessage.withParts()`` 派生 ——
    改内容请走上面的宿主 API，别直接对 ``bubble`` 调内部协议（那样会绕过
    ``_sync_parts`` 的派生结算与 ``_dirty_syncs`` 防抖，数据与界面会分叉）。
    """

    #: 新增消息（参数：消息 id、角色）
    messageAdded = pyqtSignal(int, str)
    #: 消息内容更新（流式追加 / ``updateMessage`` 等）
    messageUpdated = pyqtSignal(int)
    #: 消息被移除
    messageRemoved = pyqtSignal(int)
    #: 消息流式结束（参数：消息 id、最终状态）
    messageStreamFinished = pyqtSignal(int, str)
    #: 消息动作（参数：消息 id、动作 key：copy / undo / regenerate / 自定义）
    messageActionTriggered = pyqtSignal(int, str)
    #: 用户点击「复制」（参数：消息 id）
    copyRequested = pyqtSignal(int)
    #: 用户点击「撤回」（参数：消息 id）
    undoRequested = pyqtSignal(int)
    #: 用户点击「重新生成」（参数：消息 id）
    regenerateRequested = pyqtSignal(int)
    #: 插入了待答复的工具审批（参数：消息 id、``requestId``）—— **组件不在
    #: 这里阻塞**，宿主收到后自行挂起后端
    permissionRequested = pyqtSignal(int, str)
    #: 审批已落定（参数：消息 id、``requestId``、reply、answer、feedback）
    permissionReplied = pyqtSignal(int, str, str, str, str)
    #: 交互卡已就绪，请放进输入区 dock（参数：消息 id、partId、卡片）
    #:
    #: **审批的交互发生在这里，不在时间线上** —— 摆在历史流里既窄又旧（提问正文
    #: 被压到折行、候选卡说明被页脚盖住），而用户此刻就在输入区附近。
    #: :class:`~pyqt6_ela_pro.chat.ElaChatWidget` 接到后调 ``setDockWidget``。
    permissionDockRequested = pyqtSignal(int, str, object)
    #: 某条审批已落定（参数：消息 id、partId）—— dock 据此撤下当前卡、接下一张
    permissionSettled = pyqtSignal(int, str)
    #: 用户在错误卡上点击「重试」（参数：消息 id）—— 同参数重发
    retryRequested = pyqtSignal(int)
    #: 用户点击附件 chip（参数：消息 id、路径）
    attachmentClicked = pyqtSignal(int, str)
    #: 空态建议被点击（参数：建议文本）
    suggestionClicked = pyqtSignal(str)
    #: 批量渐进渲染完成（``beginBatch`` / ``endBatch`` 队列排空）
    batchRenderFinished = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._messages: list[ElaChatMessage] = []
        self._bubbles: dict = {}
        self._next_id = 1
        self._stick = True
        self._avatar_visible = True
        self._avatar_shape = AVATAR_DEFAULT_SHAPE
        self._user_avatar = None
        self._assistant_avatar = None
        self._user_bubble_ratio = 0.72
        self._content_max_width = _CONTENT_MAX_WIDTH
        self._reasoning_style = ElaChatReasoningStyleType.Collapse
        self._tool_grouping = True
        self._tool_default_open = toolDefaultOpen
        self._stats_mode = "footer"
        self._disclaimer_text = DISCLAIMER_TEXT
        self._disclaimer_visible = True
        self._copy_notification_enabled = True
        self._jump_threshold = None
        self._scroll_guards: list = []
        self._guards_by_message: dict = {}
        self._dirty_syncs: set = set()
        self._strict_ids = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._scroll = ElaScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # 上游 V3.0 起 ElaScrollArea 构造默认就是 AsNeeded；这里显式设置一次，
        # 防上游回退、也让「垂直滚动条看得见、能拖动」的意图就近可读。
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._content = _ChatContent()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(*_CONTENT_MARGIN)
        self._content_layout.setSpacing(_MESSAGE_SPACING)
        self._empty = _EmptyState(self._content)
        self._content_layout.addWidget(self._empty)
        self._content_layout.addStretch(1)
        self._scroll.setWidget(self._content)
        layout.addWidget(self._scroll)

        self._jump_button = ElaIconButton(
            ElaIconType.IconName.ArrowDown, 14, 32, 28, self
        )
        self._jump_button.setBorderRadius(8)
        self._jump_button.setToolTip("回到底部")
        set_tooltip(self._jump_button, "回到底部", ElaToolTipPositionType.Top)
        self._jump_button.hide()
        self._jump_button.clicked.connect(self._on_jump_clicked)

        self._follow_timer = QTimer(self)
        self._follow_timer.setSingleShot(True)
        self._follow_timer.timeout.connect(self._scroll_to_bottom_if_sticky)

        self._follow_hold = False
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.timeout.connect(self._release_follow_hold)

        # -- 交互 resize 延迟重排（大消息量下拖动窗口不逐帧 reflow） --------
        self._resize_reflow_deferred = True
        self._resize_reflow_min = _RESIZE_REFLOW_MIN_MESSAGES
        self._resize_reflow_delay = _RESIZE_REFLOW_DELAY_MS
        self._resize_width = 0
        self._resize_frozen_width = 0
        self._resize_old_width = 0
        self._resize_reflow_timer = QTimer(self)
        self._resize_reflow_timer.setSingleShot(True)
        self._resize_reflow_timer.timeout.connect(self._release_resize_reflow)

        # -- 批量渐进渲染（历史加载先建骨架，按时间片渲染 Markdown） --------
        self._batch_depth = 0
        self._render_queue: deque = deque()
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._process_render_queue)

        # -- 视口外查看器挂起（大消息量下省内存与文本 reflow） --------------
        self._suspension_enabled = True
        self._suspension_min = _SUSPEND_MIN_MESSAGES
        self._suspended_ids: set = set()
        self._suspension_timer = QTimer(self)
        self._suspension_timer.setSingleShot(True)
        self._suspension_timer.timeout.connect(self._update_suspension)

        self._scroll.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        self._scroll.verticalScrollBar().rangeChanged.connect(self._on_range_changed)
        self._empty.suggestionClicked.connect(self.suggestionClicked)

    # -- 查询 --------------------------------------------------------------

    def count(self) -> int:
        """消息条数。"""
        return len(self._messages)

    def messages(self) -> list:
        """消息只读快照（``ElaChatMessage`` 列表）。"""
        self._flush_pending_syncs()
        return list(self._messages)

    def message(self, messageId: int) -> Optional[ElaChatMessage]:
        """按 id 查询消息快照（不存在返回 ``None``）。"""
        self._flush_pending_syncs()
        for message in self._messages:
            if message.id == messageId:
                return message
        return None

    def bubble(self, messageId: int) -> Optional[ElaChatBubble]:
        """按 id 获取消息气泡控件（不存在返回 ``None``）。"""
        return self._bubbles.get(messageId)

    # -- 严格 id 模式 --------------------------------------------------------

    def setStrictIds(self, on: bool) -> None:
        """严格模式：操作**不存在的消息**时抛 :class:`KeyError` 而非静默忽略。

        默认关闭 —— 流式场景下「迟到事件」是正常的（消息已被撤回 / 替换，后端还在发
        分片）。但这让**宿主传错 id** 完全隐形：``setToolCallResult(999, ...)`` 不报错
        不告警，「工具结果丢了」要到很久以后才被发现。

        **只影响公开 mutator**；内部路径（滚动跟随 / 视口挂起 / 分段同步）在消息消失时
        必须继续静默。建议在开发 / 调试期打开。
        """
        self._strict_ids = bool(on)

    def strictIds(self) -> bool:
        """是否处于严格 id 模式。"""
        return self._strict_ids

    @staticmethod
    def _require_int_id(messageId, api: str = "") -> None:
        """非 int 的 messageId 任何模式都抛 :class:`TypeError`（笔误必须显式失败）。"""
        if isinstance(messageId, bool) or not isinstance(messageId, int):
            raise TypeError(
                f"{api or '该操作'}：messageId 必须是 int，收到 {messageId!r}"
                f"（{type(messageId).__name__}）"
            )

    def _require_bubble(self, messageId: int, api: str = "") -> ElaChatBubble:
        """取气泡；非法 id **抛 TypeError**，严格模式下不存在抛 :class:`KeyError`。

        非严格模式下「id 不存在」等价于 ``self._bubbles.get(messageId)``。
        """
        self._require_int_id(messageId, api)
        bubble = self._bubbles.get(messageId)
        if bubble is None and self._strict_ids:
            raise KeyError(
                f"{api or '该操作'}：消息 id {messageId!r} 不存在"
                f"（现有 id：{sorted(self._bubbles)[:20]}）"
            )
        return bubble

    def lastMessage(self) -> Optional[ElaChatMessage]:
        """最后一条消息快照（无消息返回 ``None``）。"""
        self._flush_pending_syncs()
        return self._messages[-1] if self._messages else None

    def sessionStats(self, limit: int = 0) -> ElaChatSessionStats:
        """会话级用量汇总（计数 / 当前上下文四路词元 / 使用率 / 累计成本）。

        口径对齐 opencode ``getSessionContext``：**「当前用量」取最后一条有
        tokens 的助手消息的最后一步**（多步工具轮里就是最近一次 LLM 调用），
        ``total_tokens`` = 四路和；累计成本跨全部消息求和。

        这套数字可以直接喂输入区的上下文圆环::

            stats = view.sessionStats(WINDOW)
            chat.chatInput().setContextUsage(stats.total_tokens, WINDOW, stats.total_cost_usd)

        :param limit: 模型上下文上限（词元）；``> 0`` 时才计算 ``usage_percent``
        :returns: :class:`~pyqt6_ela_pro.chat.session.ElaChatSessionStats` 快照
        """
        return ElaChatSessionStats.fromMessages(self.messages(), limit)

    def contentWidget(self) -> QWidget:
        """获取滚动区内容容器（高级用法）。"""
        return self._content

    # -- 增删改 ------------------------------------------------------------

    def addMessage(
        self, role: str, text: str = "", messageId: Optional[int] = None
    ) -> int:
        """添加一条消息，返回消息 id。

        ``messageId`` 可由调用方指定（乐观 UI 先行渲染）。**该 id 已被占用时
        抛 :class:`ValueError`** —— 静默重号会让旧气泡既留在界面上又不在索引里
        （``removeMessage`` / ``clear()`` 都清不到），快照还出现两个同 id 消息
        （与 :meth:`addMessageFromDict` 同一口径）。客户端生成的幂等键请走
        ``ElaChatWidget.sendUserMessage``（那里做过重复发送对账）。
        """
        if messageId is not None and messageId in self._bubbles:
            raise ValueError(
                f"addMessage: 消息 id {messageId} 已被占用，请换一个 id 或改用既有消息"
            )
        return self._create_message(role, text, streaming=False, messageId=messageId)

    def beginMessage(self, role: str = ElaChatRoleType.Assistant) -> int:
        """开始一条流式消息（通常为助手），返回消息 id。"""
        return self._create_message(role, "", streaming=True)

    def addMessageFromDict(self, data, messageId: Optional[int] = None) -> int:
        """从 :meth:`ElaChatMessage.toDict` 的输出恢复一条消息，返回消息 id。

        存储模块的**读回**入口：与 :meth:`addMessage` 的区别是它会重建完整的
        分段时间线（思考 / 正文 / 工具 / 步骤用量）以及消息级字段（标题、
        时间、耗时、错误、附件），而不只是一个纯文本气泡。

        ``messageId`` 为 ``None`` 时沿用 ``data`` 里的 ``id``（跨重启保持稳定，
        分段 id 也一并保留）；若该 id 已被占用则**抛 ValueError 而不是静默
        重号** —— 静默重号会让两条消息共用一个 id，后一条按 id 永远取不到，
        宿主却以为恢复成功了。需要顺序追加、不在乎 id 的话用
        :meth:`restoreMessages`（它一律重新分配）。

        :raises ValueError: id 已被占用，或助手消息的分段无法重建
        """
        message = ElaChatMessage.fromDict(data)
        if messageId is None and message.id > 0:
            messageId = message.id
        if messageId is not None:
            if messageId in self._bubbles:
                raise ValueError(
                    f"addMessageFromDict: 消息 id {messageId} 已被占用，"
                    "请显式传入 messageId 或改用 restoreMessages"
                )
            if messageId >= self._next_id:
                self._next_id = messageId + 1
        if message.role == ElaChatRoleType.Assistant and message.parts:
            messageId = self._create_message(
                message.role,
                "",
                streaming=False,
                messageId=messageId,
                emitAdded=False,
            )
            if not self._bubbles[messageId].setParts(message.parts):
                raise ValueError("addMessageFromDict: 助手消息分段重建失败")
            self._apply_message_fields(messageId, message)
            self._sync_parts(messageId)
            self.messageAdded.emit(messageId, message.role)
            self._follow_bottom()
            return messageId
        # 用户 / 系统消息（或无分段的老数据）：走普通纯文本路径
        messageId = self._create_message(
            message.role,
            message.text,
            streaming=False,
            messageId=messageId,
            emitAdded=False,
        )
        self._apply_message_fields(messageId, message)
        self.messageAdded.emit(messageId, message.role)
        return messageId

    def _validate_preserve_ids(self, rows) -> None:
        """校验 ``preserveIds=True`` 的整批 id（重复 / 与现有消息撞号即抛）。

        **只读校验**：调用方（``restoreMessages`` / ``importSession``）必须在
        写入前调用 —— 尤其是 ``importSession(clear=True)``，先清空再校验会让
        坏 bundle 把当前会话整个清掉后才抛异常。
        """
        stored = [ElaChatMessage.fromDict(data).id for data in rows]
        stored = [messageId for messageId in stored if messageId > 0]
        counts = Counter(stored)
        bad = sorted(
            {messageId for messageId, count in counts.items() if count > 1}
            | {messageId for messageId in counts if messageId in self._bubbles}
        )
        if bad:
            raise ValueError(
                f"restoreMessages: id {bad} 在本批或现有消息中重复 / 已被占用"
                "（preserveIds=True 时请先去重或 clear，或改用默认重分配）"
            )

    def restoreMessages(self, items, preserveIds: bool = False) -> list:
        """批量恢复消息（存储模块的**读回**入口），返回恢复后的消息 id 列表。

        按给定顺序追加；``preserveIds=False``（默认）时消息 ``id`` 一律
        **重新分配** —— 历史数据里的 id 很可能与当前会话已有的冲突。
        ``preserveIds=True`` 时保留存储里的 id（跨重启稳定）；本批内部重号或
        与现有消息撞 id 时抛 :class:`ValueError`，且**先校验后写入、一条都不
        落**（不会留下半恢复状态）。

        整体包在 :meth:`beginBatch` / :meth:`endBatch` 之间，大批量加载走
        渐进渲染路径（骨架先建，Markdown 按时间片补齐）。
        """
        rows = list(items or ())
        if preserveIds:
            self._validate_preserve_ids(rows)
        restored = []
        self.beginBatch()
        try:
            for data in rows:
                message = ElaChatMessage.fromDict(data)
                messageId = message.id if preserveIds and message.id > 0 else None
                messageId = self._create_message(
                    message.role,
                    "" if message.parts else message.text,
                    streaming=False,
                    messageId=messageId,
                    hasParts=bool(message.parts),
                    emitAdded=False,
                )
                if message.role == ElaChatRoleType.Assistant and message.parts:
                    if not self._bubbles[messageId].setParts(message.parts):
                        continue
                    # 快照**当场结算**，只有 Markdown 渲染延迟（``setParts`` 在延迟
                    # 模式下只把分段登记成待渲染）。反过来会把「parts 为空」这件事
                    # 泄露给读路径：``messages()`` / ``exportSession`` 在渲染队列排空
                    # 之前拿到的都是空消息，导出会静默丢内容。
                    self._sync_parts(messageId)
                self._apply_message_fields(messageId, message)
                self.messageAdded.emit(messageId, message.role)
                restored.append(messageId)
        finally:
            self.endBatch()
        return restored

    def _apply_message_fields(self, messageId: int, message) -> None:
        """把消息级字段（标题 / 时间 / 耗时 / 错误 / 附件 / 创建时间）恢复到气泡与快照。

        必须走 **view 级**方法：``bubble.setDuration()`` 之类只改控件，不改
        ``_messages`` 里的快照 —— 那样恢复出来的消息 ``duration_ms`` / ``error``
        会是 0 / 空，而界面却显示着耗时，看着自相矛盾。
        """
        bubble = self._bubbles.get(messageId)
        if bubble is None:
            return
        if message.title:
            self.setMessageTitle(messageId, message.title)
        if message.timestamp:
            self.setMessageTimestamp(messageId, message.timestamp)
        if message.duration_ms:
            self.setMessageDuration(messageId, message.duration_ms)
        if message.error:
            self.setMessageError(messageId, message.error, message.error_type)
        if message.attachments:
            bubble.setAttachments(message.attachments)
            self._update_snapshot(
                messageId,
                lambda m, items=message.attachments: m.withAttachments(items),
            )
        if message.created_at:
            self._update_snapshot(
                messageId, lambda m, at=message.created_at: _with_created_at(m, at)
            )
        # 消息级状态也要还原：只信 parts 的派生字段而不还原 status，会把
        # 「被停止」「出错」的历史消息显示成 Done（错误文案为空时尤其隐蔽）。
        # 有错误文案时不覆盖 —— ``setMessageError`` 已把状态置为 Error，
        # 存储里的 ``status`` 可能还是上一轮的 Done。
        if message.status and not message.error:
            status = message.status
            if status == ElaChatStatusType.Streaming:
                # 生成中导出 / 崩在途的消息：分段已被 ``setParts`` 结算，状态也
                # 必须一起落定（与 journal 的 ``settleOpen`` 同口径）—— 否则
                # 底部行永久隐藏、挂起调度永远跳过它，且没有任何路径再收尾。
                status = ElaChatStatusType.Stopped
            bubble.setStatus(status)
            self._update_snapshot(
                messageId, lambda m, value=status: m.withStatus(value)
            )

    # -- 会话 bundle（导出 / 导入） ----------------------------------------

    def exportSession(self, session=None, extra=None) -> dict:
        """导出整会话快照（消息时间线 + 会话元数据 + 视图外观选项）。

        - ``messages``：``ElaChatMessage.toDict()`` 列表（权威数据是 ``parts``）；
        - ``session``：:class:`ElaChatSessionInfo`（或字典），
          ``message_count`` 按当前消息数重算；
        - ``view``：思考形态 / 用量模式 / 工具分组 / 头像可见 / 用户气泡宽度 /
          内容最大宽度（均为 JSON 安全值；头像来源与主题属宿主 / 全局设置，
          不在 bundle 内）；
        - ``extra``：宿主自定义 JSON 数据，原样带回（组件不解释）。

        输出可直接 ``json.dumps`` 落库；读回见 :meth:`importSession`。
        """
        if isinstance(session, ElaChatSessionInfo):
            info = session
        elif isinstance(session, dict):
            info = ElaChatSessionInfo.fromDict(session)
        elif session is None:
            info = ElaChatSessionInfo(id="")
        else:
            raise TypeError(
                "exportSession: session 必须是 ElaChatSessionInfo / dict / None"
            )
        if extra is not None and not isinstance(extra, dict):
            raise TypeError("exportSession: extra 必须是 dict 或 None")
        messages = self.messages()
        return {
            "schema": SESSION_SCHEMA_VERSION,
            "session": info.withMessageCount(len(messages)).toDict(),
            "view": {
                "reasoning_style": self._reasoning_style,
                "stats_mode": self._stats_mode,
                "tool_grouping": self._tool_grouping,
                "avatar_visible": self._avatar_visible,
                "user_bubble_ratio": self._user_bubble_ratio,
                "content_max_width": self._content_max_width,
            },
            "messages": [message.toDict() for message in messages],
            "extra": extra,
        }

    def importSession(self, bundle, clear: bool = True) -> int:
        """从 :meth:`exportSession` 的 bundle 恢复整会话，返回恢复的消息条数。

        - ``clear=True``（默认）：先校验（id 冲突即抛、**一条都不落**）再清空当前
          消息，**保留消息 id 与分段 id**（跨重启稳定）；``clear=False``：追加到
          现有消息之后，id 重新分配。
        - 视图外观选项在写入消息**之前**应用（思考形态决定分段控件建卡形态）；
          缺失 / 非法字段保持当前值不动。
        - 非 dict / ``messages`` 非列表抛 :class:`ValueError`；``messages`` 里
          的非字典行跳过（存储损坏行不应变成空消息）。
        - 会话元数据（标题 / 时间…）留在 bundle 里由宿主读取 —— 视图不持有
          会话状态；多话题切换见 ``ElaChatSessionInfo`` 的接口契约。

        注意：输入草稿与排队队列是 widget 状态，不在 bundle 内；多会话切换时
        宿主自行 ``chat.clearQueue()`` / 清空输入。
        """
        if not isinstance(bundle, dict):
            raise ValueError("importSession: bundle 必须是 dict")
        rows = bundle.get("messages", [])
        if not isinstance(rows, list):
            raise ValueError("importSession: bundle['messages'] 必须是列表")
        rows = [row for row in rows if isinstance(row, dict)]
        if clear:
            # 先校验后清空：坏 bundle（重复 id 等）不能把当前会话清掉再抛
            self._validate_preserve_ids(rows)
        self._apply_session_view(bundle.get("view"))
        if clear:
            self.clear()
        return len(self.restoreMessages(rows, preserveIds=clear))

    def _apply_session_view(self, options) -> None:
        """按 bundle 的 ``view`` 段恢复外观选项（缺失 / 非法字段不动）。"""
        if not isinstance(options, dict):
            return
        if options.get("reasoning_style") in ElaChatReasoningStyleType.All:
            self.setReasoningStyle(options["reasoning_style"])
        if options.get("stats_mode") in ("footer", "steps", "none"):
            self.setStatsMode(options["stats_mode"])
        grouping = options.get("tool_grouping")
        if isinstance(grouping, bool):
            self.setToolGrouping(grouping)
        visible = options.get("avatar_visible")
        if isinstance(visible, bool):
            self.setAvatarVisible(visible)
        ratio = options.get("user_bubble_ratio")
        if isinstance(ratio, (int, float)) and not isinstance(ratio, bool):
            self.setUserBubbleMaxWidth(float(ratio))
        width = options.get("content_max_width")
        if isinstance(width, int) and not isinstance(width, bool):
            self.setContentMaxWidth(width)

    def _create_message(
        self,
        role: str,
        text: str,
        streaming: bool,
        messageId: Optional[int] = None,
        *,
        hasParts: bool = False,
        emitAdded: bool = True,
    ) -> int:
        if role not in ElaChatRoleType.All:
            role = ElaChatRoleType.Assistant
        if messageId is None:
            messageId = self._next_id
            self._next_id += 1
        else:
            if isinstance(messageId, bool) or not isinstance(messageId, int):
                raise TypeError(
                    f"messageId 必须是 int，收到 {messageId!r}"
                    f"（{type(messageId).__name__}）"
                )
            if messageId in self._bubbles:
                raise ValueError(f"消息 id {messageId} 已被占用")
            if messageId >= self._next_id:
                # 外部 id 必须单调推进内部计数器，否则后续自动分配的 id 会撞车
                self._next_id = messageId + 1
        # **判据是「有没有正文可渲染」，不是「text 是不是空串」**：带 parts 的
        # 历史消息（``toDict`` / ``exportSession`` 产出的现代存档）正文在 parts
        # 里、``text`` 传的是空串，早先因此全部走了同步渲染 —— 批量加载几百条
        # 的主流路径反而绕开了时间片，主线程一次性渲染全部 Markdown。
        deferred = (
            self._batch_depth > 0
            and role == ElaChatRoleType.Assistant
            and bool(text or hasParts)
            and not streaming
        )
        bubble = ElaChatBubble(role, "" if deferred else text, self._content)
        bubble.setAvatarVisible(self._avatar_visible)
        bubble.setAvatarShape(self._avatar_shape)
        if role == ElaChatRoleType.User and self._user_avatar is not None:
            bubble.setAvatarImage(self._user_avatar)
        elif role == ElaChatRoleType.Assistant and self._assistant_avatar is not None:
            bubble.setAvatarImage(self._assistant_avatar)
        bubble.setMaxWidthRatio(self._user_bubble_ratio)
        bubble.setContentMaxWidth(self._content_max_width)
        bubble.setMessageId(messageId)
        bubble.setTimestamp(datetime.now().strftime("%H:%M:%S"))
        bubble.setReasoningStyle(self._reasoning_style)
        bubble.setToolGrouping(self._tool_grouping)
        bubble.setStatsMode(self._stats_mode)
        bubble.setToolDefaultOpen(self._tool_default_open)
        bubble.setDisclaimer(self._disclaimer_text)
        bubble.setDisclaimerVisible(self._disclaimer_visible)
        bubble.setCopyNotificationEnabled(self._copy_notification_enabled)
        if role == ElaChatRoleType.User and self._messages:
            # turn 间隔：用户消息前额外留白（对齐 opencode 的 24px 节奏）
            bubble.setTopSpacing(10)
        for area in bubble.nestedScrollAreas():
            self._guard_message_viewer(messageId, area)
        bubble.viewerCreated.connect(
            lambda widget, mid=messageId: self._guard_message_viewer(mid, widget)
        )
        if streaming:
            bubble.beginStream()
        bubble.streamFinished.connect(
            lambda _=None, mid=messageId: self._on_bubble_stream_finished(mid)
        )
        bubble.copyRequested.connect(
            lambda mid=messageId: self._on_bubble_action(mid, "copy")
        )
        bubble.undoRequested.connect(
            lambda mid=messageId: self._on_bubble_action(mid, "undo")
        )
        bubble.regenerateRequested.connect(
            lambda mid=messageId: self._on_bubble_action(mid, "regenerate")
        )
        bubble.retryRequested.connect(
            lambda mid=messageId: self.retryRequested.emit(mid)
        )
        bubble.permissionRequested.connect(
            lambda requestId, mid=messageId: self.permissionRequested.emit(
                mid, str(requestId)
            )
        )
        bubble.permissionReplied.connect(
            lambda requestId, reply, answer, feedback, mid=messageId: (
                self.permissionReplied.emit(
                    mid, str(requestId), str(reply), str(answer), str(feedback)
                )
            )
        )
        bubble.permissionDockRequested.connect(
            lambda card, partId, mid=messageId: self.permissionDockRequested.emit(
                mid, str(partId), card
            )
        )
        bubble.permissionSettled.connect(
            lambda partId, mid=messageId: self.permissionSettled.emit(mid, str(partId))
        )
        bubble.actionTriggered.connect(
            lambda key, mid=messageId: self._on_bubble_action(mid, str(key))
        )
        bubble.attachmentClicked.connect(
            lambda path, mid=messageId: self.attachmentClicked.emit(mid, str(path))
        )
        bubble.toolToggled.connect(self._on_tool_toggled)
        self._bubbles[messageId] = bubble
        self._content_layout.insertWidget(self._content_layout.count() - 1, bubble)
        status = ElaChatStatusType.Streaming if streaming else ElaChatStatusType.Done
        self._messages.append(
            ElaChatMessage(
                id=messageId,
                role=role,
                text=text,
                status=status,
                created_at=time.time(),
                timestamp=bubble.timestamp(),
            )
        )
        self._empty.setVisible(False)
        if deferred:
            # 批量加载：先建骨架，Markdown 由渲染队列按时间片补齐
            bubble.setRenderDeferred(True)
            bubble.setText(text)
            self._render_queue.append(messageId)
        else:
            self._sync_parts(messageId)
        if emitAdded:
            # 恢复路径（``addMessageFromDict`` / ``restoreMessages``）传
            # ``emitAdded=False``：它们要在字段 / 分段全部还原完之后再发一次，
            # 否则宿主在信号回调里读到的是「parts 为空、字段未恢复」的半成品。
            self.messageAdded.emit(messageId, role)
        self._follow_bottom()
        return messageId

    # -- 批量渐进渲染 ------------------------------------------------------

    def beginBatch(self) -> None:
        """进入批量加载模式（可嵌套）。

        批量内新增的助手文本消息先建骨架、跳过快照同步与贴底跟随，
        Markdown 渲染进入队列；``endBatch`` 后按 ``_BATCH_RENDER_BUDGET_MS``
        时间片渐进渲染，排空后发出 :attr:`batchRenderFinished`。
        """
        self._batch_depth += 1
        if self._batch_depth == 1:
            self._scroll.viewport().setUpdatesEnabled(False)

    def endBatch(self) -> None:
        """结束批量加载模式（嵌套深度归零时启动渲染队列）。"""
        if self._batch_depth <= 0:
            return
        self._batch_depth -= 1
        if self._batch_depth > 0:
            return
        if self._render_queue:
            self._render_timer.start(0)
        else:
            self._finish_batch_render()

    def isBatchActive(self) -> bool:
        """是否处于批量加载模式。"""
        return self._batch_depth > 0

    def _process_render_queue(self) -> None:
        """按时间片渲染队列中的消息（每片一个消息的待渲染查看器）。"""
        if not self._render_queue:
            self._finish_batch_render()
            return
        timer = QElapsedTimer()
        timer.start()
        while self._render_queue and timer.elapsed() < _BATCH_RENDER_BUDGET_MS:
            messageId = self._render_queue.popleft()
            bubble = self._bubbles.get(messageId)
            if bubble is None:
                continue
            bubble.setRenderDeferred(False)
            bubble.flushRender()
            self._sync_parts(messageId)
        if self._render_queue:
            self._render_timer.start(0)
        else:
            self._finish_batch_render()

    def _finish_batch_render(self) -> None:
        """批量渲染收尾：恢复刷新、激活布局、贴底并通知宿主。"""
        self._scroll.viewport().setUpdatesEnabled(True)
        self._scroll.viewport().update()
        self._content_layout.activate()
        self._follow_bottom()
        self.batchRenderFinished.emit()
        self._schedule_suspension_update()

    # -- 视口外查看器挂起 --------------------------------------------------

    def setViewportSuspension(
        self, on: bool = True, minMessages: Optional[int] = None
    ) -> None:
        """设置视口外消息是否挂起重型查看器（默认开启）。

        挂起把离视口较远（上下各 ``2`` 屏）消息的 Markdown 查看器替换为
        等高透明占位控件（``parts`` / 快照数据不变），滚动回来时重新渲染；
        流式消息与批量加载中的消息不挂起。消息数少于 ``minMessages``
        （缺省 80）时不做任何处理。

        :param on: 是否启用
        :param minMessages: 启用挂起的最小消息数（缺省 80）
        """
        self._suspension_enabled = bool(on)
        if minMessages is not None:
            self._suspension_min = max(0, int(minMessages))
        if not self._suspension_enabled:
            self._suspension_timer.stop()
            self._restore_all_suspended()
        else:
            self._schedule_suspension_update()

    def viewportSuspension(self) -> bool:
        """是否启用视口外查看器挂起。"""
        return self._suspension_enabled

    def _schedule_suspension_update(self) -> None:
        """合并短时间内的多次滚动 / 布局变化，按间隔更新挂起状态。"""
        if not self._suspension_enabled or self._suspension_timer.isActive():
            return
        self._suspension_timer.start(_SUSPEND_INTERVAL_MS)

    def _update_suspension(self) -> None:
        """按当前视口范围挂起 / 恢复消息查看器。"""
        if (
            not self._suspension_enabled
            or self.count() < self._suspension_min
            or not self.isVisible()
        ):
            self._restore_all_suspended()
            return
        if self._resize_frozen_width > 0:
            return  # 拖动 resize 期间几何未定，停手后统一更新
        bar = self._scroll.verticalScrollBar()
        top = bar.value()
        viewport = self._scroll.viewport().height()
        bottom = top + viewport
        margin = viewport * _SUSPEND_MARGIN_VIEWPORTS
        # **先快照全部几何，再统一应用**：挂起 / 恢复会改变兄弟气泡的 y（内容变矮 /
        # 变高），边判边改会让后面几条基于过期坐标判定 —— 表现为状态来回震荡、
        # 「最远那条」偶发没被挂起（计时相关，难复现）。
        snapshot = []
        for messageId, bubble in self._bubbles.items():
            if bubble.role() != ElaChatRoleType.Assistant or bubble.renderDeferred():
                continue
            if bubble.isStreaming():
                continue
            snapshot.append((messageId, bubble.y(), bubble.height()))
        for messageId, y, height in snapshot:
            in_range = (y + height >= top - margin) and (y <= bottom + margin)
            suspended = messageId in self._suspended_ids
            if in_range and suspended:
                self._restore_message_viewers(messageId)
            elif not in_range and not suspended:
                self._suspend_message_viewers(messageId)

    def _suspend_message_viewers(self, messageId: int) -> None:
        bubble = self._bubbles.get(messageId)
        if bubble is None or bubble.viewersSuspended():
            return
        bubble.setViewersSuspended(True)
        if not bubble.viewersSuspended():
            return
        self._suspended_ids.add(messageId)
        self._drop_message_guards(messageId)

    def _restore_message_viewers(self, messageId: int) -> None:
        bubble = self._bubbles.get(messageId)
        self._suspended_ids.discard(messageId)
        if bubble is None:
            return
        bar = self._scroll.verticalScrollBar()
        top = bar.value()
        before = bubble.height()
        bubble.setViewersSuspended(False)
        self._content_layout.activate()
        if self._stick:
            self._scroll_to_bottom()
            return
        after = bubble.height()
        if after != before and bubble.y() + after <= top:
            # 恢复点在视口上方：补偿高度差，保持阅读位置稳定
            bar.setValue(top + (after - before))

    def _restore_all_suspended(self) -> None:
        for messageId in list(self._suspended_ids):
            self._restore_message_viewers(messageId)

    def appendText(self, messageId: int, chunk: str) -> None:
        """向指定消息追加流式正文（助手消息为 Markdown）。"""
        bubble = self._require_bubble(messageId, "appendText")
        if bubble is None or not chunk:
            return
        bubble.appendText(chunk)
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)
        self._follow_bottom()

    def beginText(self, messageId: int) -> Optional[str]:
        """开始指定消息的新正文段，返回分段 id（非助手消息返回 ``None``）。"""
        bubble = self._require_bubble(messageId, "beginText")
        if bubble is None:
            return None
        partId = bubble.beginText()
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)
        self._follow_bottom()
        return partId

    def endText(self, messageId: int) -> None:
        """结束指定消息的当前正文段（停止流式光标）。"""
        bubble = self._require_bubble(messageId, "endText")
        if bubble is None:
            return
        bubble.endText()
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)

    def updateMessage(self, messageId: int, text: str) -> None:
        """整体替换消息文本。"""
        bubble = self._require_bubble(messageId, "updateMessage")
        if bubble is None:
            return
        bubble.setText(text)
        if bubble.role() == ElaChatRoleType.Assistant:
            self._sync_parts(messageId)
        else:
            self._update_snapshot(messageId, lambda message: message.withText(text))
        self.messageUpdated.emit(messageId)
        self._follow_bottom()

    def endMessage(self, messageId: int, status: str = ElaChatStatusType.Done) -> None:
        """结束指定消息的流式生成。"""
        bubble = self._require_bubble(messageId, "endMessage")
        if bubble is None:
            return
        bubble.endStream(status)

    def removeMessage(self, messageId: int) -> None:
        """移除指定消息（非 int id 抛 ``TypeError``；严格模式下不存在抛 ``KeyError``）。"""
        # 删消息前必须先作废未答复审批：交互卡在 dock 上，气泡删了卡还活着，
        # 用户点一下就会走进已销毁对象（0xC0000409）。widget.removeMessage
        # 早已这么做，这里补上让 view 层直接调用同样安全。
        bubble = self._require_bubble(messageId, "removeMessage")
        if bubble is None:
            return
        bubble.cancelPendingPermissions()
        self._detach_message(messageId)
        self._messages = [m for m in self._messages if m.id != messageId]
        if not self._messages:
            self._empty.setVisible(True)
        self.messageRemoved.emit(messageId)
        self._update_jump_button()

    def removeMessagesFrom(self, messageId: int) -> list:
        """批量移除 id >= ``messageId`` 的全部消息（撤回 / 重新生成用）。

        单趟过滤消息列表，避免逐条删除造成的 O(n²) 列表重建；
        被移除的每条仍按原语义发出 ``messageRemoved``。

        :returns: 被移除的消息 id 列表（按原顺序）
        """
        self._require_int_id(messageId, "removeMessagesFrom")
        removed = [m.id for m in self._messages if m.id >= messageId]
        if not removed:
            return []
        removed_set = set(removed)
        # 两趟：先作废全部待答复审批，再摘气泡。取消会同步发 ``permissionSettled``
        # 触发 dock promote —— 边取消边摘会让 promote 取到「马上要被删」的气泡
        # 里的交互卡，摘完就成死卡。
        for mid in removed:
            bubble = self._bubbles.get(mid)
            if bubble is not None:
                bubble.cancelPendingPermissions()
        for mid in removed:
            self._detach_message(mid)
        self._messages = [m for m in self._messages if m.id not in removed_set]
        if not self._messages:
            self._empty.setVisible(True)
        self._update_jump_button()
        for mid in removed:
            self.messageRemoved.emit(mid)
        return removed

    def clear(self) -> None:
        """清空全部消息（恢复空态）。"""
        # 同 removeMessagesFrom：先作废全部待答复审批（两趟），避免 promote
        # 拿到马上要被销毁的气泡里的交互卡。
        bubbles = list(self._bubbles.values())
        for bubble in bubbles:
            bubble.cancelPendingPermissions()
        for bubble in bubbles:
            bubble.setParent(None)
            bubble.deleteLater()
        self._bubbles.clear()
        self._messages.clear()
        self._dirty_syncs.clear()
        self._render_queue.clear()
        self._render_timer.stop()
        # **渐进渲染被打断时必须自己收尾**：``beginBatch`` 关掉了视口刷新，而恢复
        # 只在 ``_finish_batch_render`` 里。这里把队列清空、计时器停掉，那次
        # ``endBatch`` 之后再没人会走到那个函数 —— 视口就永久不再重绘（连空态和
        # 之后新增的消息都不显示）。``_batch_depth > 0`` 时不用管：``endBatch``
        # 归零时队列已空，会走 ``_finish_batch_render``。
        if self._batch_depth <= 0 and not self._scroll.viewport().updatesEnabled():
            self._scroll.viewport().setUpdatesEnabled(True)
            self._scroll.viewport().update()
            self._content_layout.activate()
        self._suspended_ids.clear()
        self._suspension_timer.stop()
        for guards in self._guards_by_message.values():
            for guard in guards:
                try:
                    self._scroll_guards.remove(guard)
                except ValueError:
                    pass
        self._guards_by_message.clear()
        self._empty.setVisible(True)
        self._update_jump_button()

    def _detach_message(self, messageId: int) -> bool:
        """摘除单条消息的气泡与相关引用；返回消息是否存在。"""
        bubble = self._bubbles.pop(messageId, None)
        if bubble is None:
            return False
        bubble.setParent(None)
        bubble.deleteLater()
        self._dirty_syncs.discard(messageId)
        self._suspended_ids.discard(messageId)
        for guard in self._guards_by_message.pop(messageId, ()):
            try:
                self._scroll_guards.remove(guard)
            except ValueError:
                pass
        return True

    # -- 步骤 --------------------------------------------------------------

    def beginStep(self, messageId: int) -> Optional[int]:
        """开始指定助手消息的新步骤，返回步骤序号。

        仅推进步骤序号（分段未变），仍发出 ``messageUpdated`` 便于宿主
        统一观察消息变化。
        """
        bubble = self._require_bubble(messageId, "beginStep")
        if bubble is None:
            return None
        step = bubble.beginStep()
        self.messageUpdated.emit(messageId)
        return step

    # -- 思考层 ------------------------------------------------------------

    def beginReasoning(self, messageId: int) -> None:
        """开始指定消息的思考阶段（展开「思考中」）。"""
        bubble = self._require_bubble(messageId, "beginReasoning")
        if bubble is None:
            return
        bubble.beginReasoning()
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)
        self._follow_bottom()

    def appendReasoning(self, messageId: int, chunk: str) -> None:
        """向指定消息追加思考文本（流式）。"""
        bubble = self._require_bubble(messageId, "appendReasoning")
        if bubble is None or not chunk:
            return
        bubble.appendReasoning(chunk)
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)
        self._follow_bottom()

    def endReasoning(self, messageId: int, durationMs: Optional[float] = None) -> None:
        """结束指定消息的思考阶段（显示耗时并收起）。"""
        bubble = self._require_bubble(messageId, "endReasoning")
        if bubble is None:
            return
        bubble.endReasoning(durationMs)
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)

    def setReasoning(
        self,
        messageId: int,
        text: str,
        durationMs: Optional[float] = None,
    ) -> None:
        """整体设置指定消息的思考内容。"""
        bubble = self._require_bubble(messageId, "setReasoning")
        if bubble is None:
            return
        bubble.setReasoning(text, durationMs)
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)

    # -- 工具层 ------------------------------------------------------------

    def addToolCall(
        self,
        messageId: int,
        name: str,
        arguments: str = "",
        toolCallId: Optional[str] = None,
    ) -> Optional[str]:
        """为指定消息添加工具调用卡片，返回调用 id。"""
        bubble = self._require_bubble(messageId, "addToolCall")
        if bubble is None:
            return None
        callId = bubble.addToolCall(name, arguments, toolCallId)
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)
        self._follow_bottom()
        return callId

    def setToolCallResult(
        self,
        messageId: int,
        toolCallId: str,
        result: str,
        ok: bool = True,
    ) -> None:
        """更新指定工具调用的结果。"""
        bubble = self._require_bubble(messageId, "setToolCallResult")
        if bubble is None:
            return
        bubble.setToolCallResult(toolCallId, result, ok=ok)
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)

    def toolCalls(self, messageId: int) -> list:
        """获取指定消息的工具调用快照列表。"""
        self._require_int_id(messageId, "toolCalls")
        bubble = self._bubbles.get(messageId)
        return bubble.toolCalls() if bubble is not None else []

    def clearToolCalls(self, messageId: int) -> None:
        """清空指定消息的工具调用卡片。"""
        bubble = self._require_bubble(messageId, "clearToolCalls")
        if bubble is None:
            return
        bubble.clearToolCalls()
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)

    # -- 合成段 / 压缩段 / 审批段 -------------------------------------------

    def addSteerNotice(self, messageId: int, text: str) -> str:
        """在指定消息内追加一条插话回执，返回分段 id。

        插话（steer）= 生成中把新指令**送进正在跑的这一轮**，而不是排队等
        它跑完。回执留在同一条助手消息内（``↳ <text>``），不插用户气泡。
        """
        bubble = self._require_bubble(messageId, "addSteerNotice")
        if bubble is None:
            return ""
        partId = bubble.addSteerNotice(text)
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)
        return partId

    def beginCompaction(self, messageId: int, reason: str = "auto") -> str:
        """标记一次上下文压缩开始，返回分段 id。

        **库不实现压缩算法**（摘要 / 收缩循环 / 词元估算都在 provider 侧），
        只在时间线上如实表达「这里发生过压缩」并接住摘要。

        ``reason`` 只进 journal 原始事件（诊断用），时间线卡片不展示它。
        """
        bubble = self._require_bubble(messageId, "beginCompaction")
        if bubble is None:
            return ""
        partId = bubble.beginCompaction(reason)
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)
        return partId

    def appendCompactionSummary(self, messageId: int, partId: str, chunk: str) -> None:
        """追加压缩摘要（流式）。"""
        bubble = self._bubbles.get(messageId)
        if bubble is None or not partId or not chunk:
            return
        bubble.appendCompactionSummary(partId, chunk)
        self._dirty_syncs.add(messageId)
        self.messageUpdated.emit(messageId)

    def endCompaction(
        self,
        messageId: int,
        partId: str,
        status: str = ElaChatStatusType.Done,
        historyCount: int = 0,
    ) -> None:
        """结束压缩并落定摘要。"""
        bubble = self._require_bubble(messageId, "endCompaction")
        if bubble is None:
            return
        bubble.endCompaction(partId, status, historyCount)
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)

    def beginPermission(self, messageId: int, request) -> str:
        """在指定消息内插入一张工具审批卡，返回分段 id。

        **只画卡 + 发 ``permissionRequested``，绝不阻塞** —— 在 Qt 里挂起等
        用户点按钮会卡死事件循环。宿主拿到信号后自行挂起后端，用户点完卡片
        后组件发 ``permissionReplied``。「始终允许」的规则也归宿主持久化。

        :param request: :class:`~pyqt6_ela_pro.chat.message.ElaChatPermission`
            或等价的 ``dict``（会被 ``fromDict`` 转换）
        """
        bubble = self._require_bubble(messageId, "beginPermission")
        if bubble is None:
            return ""
        if isinstance(request, dict):
            request = ElaChatPermission.fromDict(request)
        if request is None:
            return ""
        partId = bubble.beginPermission(request)
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)
        return partId

    def resolvePermission(
        self,
        messageId: int,
        requestId: str,
        reply: str,
        answer: str = "",
        feedback: str = "",
    ) -> bool:
        """以编程方式落定一次审批（对应卡片按钮）；找不到返回 ``False``。"""
        bubble = self._require_bubble(messageId, "resolvePermission")
        if bubble is None:
            return False
        ok = bubble.resolvePermission(requestId, reply, answer, feedback)
        if ok:
            self._sync_parts(messageId)
            self.messageUpdated.emit(messageId)
        return ok

    def pendingPermissions(self, messageId: int) -> list:
        """获取指定消息仍在等待用户回复的审批请求。"""
        self._require_int_id(messageId, "pendingPermissions")
        bubble = self._bubbles.get(messageId)
        return bubble.pendingPermissions() if bubble is not None else []

    def permissionCard(self, messageId: int, requestId: str):
        """取审批卡控件（宿主可改文案 / 挂事件；不存在返回 ``None``）。"""
        self._require_int_id(messageId, "permissionCard")
        bubble = self._bubbles.get(messageId)
        return bubble.permissionCard(requestId) if bubble is not None else None

    def permissionAnswers(self, messageId: int, requestId: str) -> dict:
        """取问答型审批的答案（``{key: [label, ...]}``；未答的 key 不在字典里）。

        批准型、或该请求不存在 / 已落定无答案时返回**空字典**。

        与 ``permissionReplied.answer`` 的区别：那条信号给的是**已编码**的 JSON 串
        （单选塌缩成标量），这里给的是**未塌缩**的原始分组形式 —— 宿主在
        「等用户答完、还没点提交」的中间态想知道当前进度时用它（用户答到一半
        可能切走、关窗口，这时候连信号都没发过）。

        **优先读 dock 上的交互卡**（等待期），落定后才退回时间线上的记录卡
        （那时记录卡已无交互态，答案只能从已落定的载荷里取）。
        """
        self._require_int_id(messageId, "permissionAnswers")
        card = self.interactivePermissionCard(messageId, requestId)
        if card is not None:
            return card.answers()
        permission = self._permission_of(messageId, requestId)
        if permission is None:
            return {}
        settled = permission.parsedAnswer()
        return {
            question.key: (list(value) if isinstance(value, list) else [value])
            for question in permission.questions
            if (value := settled.get(question.key)) is not None
        }

    def interactivePermissionCard(self, messageId: int, requestId: str):
        """取**仍在 dock 里等待用户操作**的交互卡（不在 dock 阶段返回 ``None``）。"""
        self._require_int_id(messageId, "interactivePermissionCard")
        bubble = self._bubbles.get(messageId)
        if bubble is None:
            return None
        for partId, permission in bubble.pendingPermissionParts():
            if permission.request_id == requestId:
                return bubble.interactivePermissionCard(partId)
        return None

    def _permission_of(self, messageId: int, requestId: str):
        """按 ``requestId`` 取审批载荷快照（不存在返回 ``None``）。"""
        bubble = self._bubbles.get(messageId)
        if bubble is None:
            return None
        for part in bubble.parts():
            if part.permission is not None and part.permission.request_id == requestId:
                return part.permission
        return None

    # -- 附件 / 用量 / 错误 -------------------------------------------------

    def setMessageAttachments(self, messageId: int, attachments) -> None:
        """整体替换指定消息的附件。"""
        bubble = self._require_bubble(messageId, "setMessageAttachments")
        if bubble is None:
            return
        bubble.setAttachments(attachments)
        self._update_snapshot(
            messageId, lambda m: m.withAttachments(bubble.attachments())
        )
        self.messageUpdated.emit(messageId)
        self._follow_bottom()

    def addMessageAttachment(
        self, messageId: int, name: str, path: str = "", size: int = 0
    ) -> None:
        """为指定消息追加一个附件。"""
        bubble = self._require_bubble(messageId, "addMessageAttachment")
        if bubble is None:
            return
        bubble.addAttachment(name, path, size)
        self._update_snapshot(
            messageId, lambda m: m.withAttachments(bubble.attachments())
        )
        self.messageUpdated.emit(messageId)

    def setStepStats(self, messageId: int, stats: Optional[ElaChatStats]) -> None:
        """设置指定消息当前步骤的用量统计（``None`` 移除徽标）。"""
        bubble = self._require_bubble(messageId, "setStepStats")
        if bubble is None:
            return
        bubble.setStepStats(stats)
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)

    def setMessageDuration(self, messageId: int, durationMs: float) -> None:
        """设置指定消息的总耗时（显示在底部 meta 层，同时发出 ``messageUpdated``）。"""
        bubble = self._require_bubble(messageId, "setMessageDuration")
        if bubble is None:
            return
        bubble.setDuration(durationMs)
        self._update_snapshot(messageId, lambda m: m.withDuration(durationMs))
        self.messageUpdated.emit(messageId)

    def setReasoningStyle(self, style: str) -> None:
        """设置思考展示形态（``"collapse"`` / ``"inline"``）。

        对已有消息立即生效（思考段原位重建，内容不丢），新消息沿用。
        """
        self._reasoning_style = (
            style
            if style in ElaChatReasoningStyleType.All
            else ElaChatReasoningStyleType.Collapse
        )
        for bubble in self._bubbles.values():
            bubble.setReasoningStyle(self._reasoning_style)

    def reasoningStyle(self) -> str:
        """获取思考展示形态。"""
        return self._reasoning_style

    def setToolGrouping(self, on: bool) -> None:
        """设置是否把连续上下文工具合并为分组卡（含已存在消息）。"""
        self._tool_grouping = bool(on)
        for bubble in self._bubbles.values():
            bubble.setToolGrouping(self._tool_grouping)

    def toolGrouping(self) -> bool:
        """是否启用上下文工具分组。"""
        return self._tool_grouping

    def setDisclaimer(self, text: str) -> None:
        """设置助手消息底部的「内容由 AI 生成」提示文案（含已存在消息）。

        默认 ``"内容由 AI 生成，仅供参考"``，跟在复制 / 重新生成按钮后面；
        空串等同隐藏。整行底部（含本提示）在流式回合期间不显示，回合结束后
        才出现 —— 与操作按钮、用量徽标同一套显隐规则。
        """
        self._disclaimer_text = str(text or "")
        self._disclaimer_visible = bool(self._disclaimer_text)
        for bubble in self._bubbles.values():
            bubble.setDisclaimer(self._disclaimer_text)
            bubble.setDisclaimerVisible(self._disclaimer_visible)

    def disclaimer(self) -> str:
        """获取「内容由 AI 生成」提示文案。"""
        return self._disclaimer_text

    def setDisclaimerVisible(self, on: bool) -> None:
        """显示 / 隐藏助手消息底部的「AI 生成」提示（含已存在消息，文案保留）。"""
        self._disclaimer_visible = bool(on)
        for bubble in self._bubbles.values():
            bubble.setDisclaimerVisible(self._disclaimer_visible)

    def disclaimerVisible(self) -> bool:
        """「AI 生成」提示是否可见。"""
        return self._disclaimer_visible

    def setCopyNotificationEnabled(self, on: bool) -> None:
        """设置点击消息底部「复制」后是否弹 ``ElaMessageBar`` 成功提示。

        默认开；与其它展示形态 setter 一致，**立即作用于已有消息**。这是应用
        偏好（与「AI 生成」提示同口径），**不进** ``exportSession`` 的视图段。
        """
        self._copy_notification_enabled = bool(on)
        for bubble in self._bubbles.values():
            bubble.setCopyNotificationEnabled(self._copy_notification_enabled)

    def copyNotificationEnabled(self) -> bool:
        """复制后是否弹成功提示。"""
        return self._copy_notification_enabled

    def setToolDefaultOpen(self, policy) -> None:
        """注入「哪些工具卡默认展开」的策略（对新旧消息统一生效）。

        ``policy(toolName, arguments, ok) -> bool``。这是**按视图**设置的入口
        —— 气泡是内部对象，宿主拿到的通常是 view，所以策略必须能在 view 上
        设一次、覆盖全部消息（含后续新增）。

        只影响**之后新建**的卡片：已存在的卡片不会被弹开，用户手动折叠的状态
        得以保留（策略存在气泡上，改策略不触碰任何已有卡片）。

        库默认见 :func:`~pyqt6_ela_pro.chat.blocks.toolDefaultOpen`，编码 agent
        场景可用 :func:`~pyqt6_ela_pro.chat.blocks.toolDefaultOpenCoding`。

        :param policy: 可调用对象；传 ``None`` 恢复库默认
        """
        self._tool_default_open = policy if callable(policy) else toolDefaultOpen
        for bubble in self._bubbles.values():
            bubble.setToolDefaultOpen(self._tool_default_open)

    def toolDefaultOpenPolicy(self):
        """获取当前工具卡展开策略（可调用对象）。"""
        return self._tool_default_open

    def setStatsMode(self, mode: str) -> None:
        """设置用量徽标展示模式（``"footer"`` / ``"steps"`` / ``"none"``）。

        对已有消息立即生效（默认 ``"footer"``：每条助手消息只显示底部
        一个整轮汇总徽标）。``"steps"`` 恢复每步各自显示（调试用），
        ``"none"`` 完全不显示（耗时回退到底部 meta 文本）。
        """
        self._stats_mode = mode if mode in ("footer", "steps", "none") else "footer"
        for bubble in self._bubbles.values():
            bubble.setStatsMode(self._stats_mode)

    def statsMode(self) -> str:
        """获取用量徽标展示模式。"""
        return self._stats_mode

    def guardNestedScroll(self, widget: QWidget) -> Optional["_NestedScrollGuard"]:
        """为嵌套滚动区安装防脱离过滤器（到达边界时不再带动外层）。

        接受 ``QAbstractScrollArea`` 或提供 ``textBrowser()`` 的查看器；
        返回过滤器对象（由视图持有引用，无需手动保存）。
        """
        area = None
        if isinstance(widget, QAbstractScrollArea):
            area = widget
        else:
            getter = getattr(widget, "textBrowser", None)
            if callable(getter):
                candidate = getter()
                if isinstance(candidate, QAbstractScrollArea):
                    area = candidate
        if area is None:
            return None
        guard = _NestedScrollGuard(area)
        area.viewport().installEventFilter(guard)
        self._scroll_guards.append(guard)
        return guard

    def _guard_message_viewer(self, messageId: int, viewer: QWidget) -> None:
        """为指定消息内的查看器安装 guard，并登记归属便于随消息回收。"""
        guard = self.guardNestedScroll(viewer)
        if guard is None:
            return
        self._guards_by_message.setdefault(messageId, []).append(guard)

    def _drop_message_guards(self, messageId: int) -> None:
        """移除指定消息已登记的嵌套滚动 guard（查看器挂起 / 重建前调用）。"""
        for guard in self._guards_by_message.pop(messageId, ()):
            try:
                self._scroll_guards.remove(guard)
            except ValueError:
                pass

    def setMessageError(
        self, messageId: int, message: str, errorType: str = ""
    ) -> None:
        """设置指定消息的错误文本与类型。

        :param message: 面向用户的错误文本（空串清除错误）
        :param errorType: 错误类型（``"RateLimit"`` / ...）。**单独存字段而不是
            拼进 ``message``** —— 拼进去类型就丢了，错误卡无法判断该不该给
            「重试」按钮，宿主也拿不到结构化信息。
        """
        bubble = self._require_bubble(messageId, "setMessageError")
        if bubble is None:
            return
        bubble.setError(message, errorType)
        # setError 会收尾未完成分段（正文 / 思考 / 工具分组），同步快照
        self._sync_parts(messageId)
        self._update_snapshot(
            messageId, lambda m: m.withError(message, errorType=errorType)
        )
        if message:
            self._update_snapshot(
                messageId, lambda m: m.withStatus(ElaChatStatusType.Error)
            )
        self.messageUpdated.emit(messageId)

    def messageError(self, messageId: int) -> tuple:
        """获取指定消息的 ``(错误文本, 错误类型)``（无错误返回 ``("", "")``）。"""
        message = self.message(messageId)
        if message is None:
            return ("", "")
        return (message.error, message.error_type)

    def clearMessageError(self, messageId: int) -> None:
        """清除指定消息的错误（发出 ``messageUpdated``）。

        「重试」前必须先调它 —— 否则上一轮的错误卡会**留在界面上**，而新的
        流式内容正在同一条消息里生成，看起来像同时既有错误又在输出。

        消息状态为 ``Error`` 时一并落成 ``Stopped``（保留「失败的尝试」记录）：
        错误文案已清空却留着 ``Error`` 状态，导出 / 恢复出来的是「出错但没
        错误」的自相矛盾数据。
        """
        bubble = self._require_bubble(messageId, "clearMessageError")
        if bubble is None:
            return
        error, error_type = self.messageError(messageId)
        if not (error or error_type):
            return
        bubble.clearError()
        # 显式传空串清类型：withError 的 errorType=None 语义是「保持原值」
        self._update_snapshot(messageId, lambda m: m.withError("", errorType=""))
        message = self.message(messageId)
        if message is not None and message.status == ElaChatStatusType.Error:
            bubble.setStatus(ElaChatStatusType.Stopped)
            self._update_snapshot(
                messageId,
                lambda m: m.withStatus(ElaChatStatusType.Stopped),
            )
        self.messageUpdated.emit(messageId)

    def setMessageTitle(self, messageId: int, title: str) -> None:
        """设置指定消息的头部名称 / 模型名（发出 ``messageUpdated``）。"""
        bubble = self._require_bubble(messageId, "setMessageTitle")
        if bubble is None:
            return
        bubble.setTitle(title)
        self._update_snapshot(messageId, lambda m: m.withTitle(title))
        self.messageUpdated.emit(messageId)

    def setMessageTimestamp(self, messageId: int, timestamp: str) -> None:
        """设置指定消息的头部时间文本（发出 ``messageUpdated``）。"""
        bubble = self._require_bubble(messageId, "setMessageTimestamp")
        if bubble is None:
            return
        bubble.setTimestamp(timestamp)
        self._update_snapshot(messageId, lambda m: m.withTimestamp(timestamp))
        self.messageUpdated.emit(messageId)

    # -- 内部状态 ----------------------------------------------------------

    def _update_snapshot(self, messageId: int, updater) -> None:
        for index, message in enumerate(self._messages):
            if message.id == messageId:
                self._messages[index] = updater(message)
                return

    def _sync_parts(self, messageId: int) -> None:
        """标记助手消息的分段快照待同步（读取时统一结算）。

        真正的 ``withParts`` 重算推迟到 ``messages()`` / ``message()`` /
        ``lastMessage()`` 读取前；宿主不读快照时零开销（每次写入只有一次 ``set.add``）。

        快照里的 ``text`` 只含**已落定**内容（``part.text`` 的语义），所以流式期间读到
        空串、回合结束才是完整正文 —— 要实时预览请读 ``bubble(messageId).text()``。
        """
        bubble = self._bubbles.get(messageId)
        if bubble is None or bubble.role() != ElaChatRoleType.Assistant:
            return
        self._dirty_syncs.add(messageId)

    def _flush_pending_syncs(self) -> None:
        """结算全部待同步的分段快照。"""
        if not self._dirty_syncs:
            return
        dirty = self._dirty_syncs
        self._dirty_syncs = set()
        for messageId in dirty:
            bubble = self._bubbles.get(messageId)
            if bubble is None or bubble.role() != ElaChatRoleType.Assistant:
                continue
            parts = bubble.parts()
            self._update_snapshot(messageId, lambda m, value=parts: m.withParts(value))

    def _on_bubble_stream_finished(self, messageId: int) -> None:
        bubble = self._bubbles.get(messageId)
        status = bubble.status() if bubble is not None else ElaChatStatusType.Done
        # endStream 会同步结束正文段（分段状态 Done），需一并同步到快照，
        # 否则消息态为 done 而 parts 里仍残留 streaming。
        self._sync_parts(messageId)
        self._update_snapshot(messageId, lambda m: m.withStatus(status))
        self.messageStreamFinished.emit(messageId, status)
        self._follow_bottom()

    def _on_bubble_action(self, messageId: int, action: str) -> None:
        self.messageActionTriggered.emit(messageId, action)
        if action == "copy":
            self.copyRequested.emit(messageId)
        elif action == "undo":
            self.undoRequested.emit(messageId)
        elif action == "regenerate":
            self.regenerateRequested.emit(messageId)

    # -- 贴底与滚动 --------------------------------------------------------

    def _atBottom(self) -> bool:
        bar = self._scroll.verticalScrollBar()
        return bar.value() >= bar.maximum() - _BOTTOM_MARGIN

    def _on_scrolled(self, _value: int) -> None:
        self._stick = self._atBottom()
        self._update_jump_button()
        self._schedule_suspension_update()

    def _on_jump_clicked(self) -> None:
        self.scrollToBottom()

    def _update_jump_button(self) -> None:
        visible = bool(self._messages) and self._distance_from_bottom() > (
            self._jump_distance()
        )
        self._jump_button.setVisible(visible)
        if visible:
            self._position_jump_button()

    def _distance_from_bottom(self) -> int:
        bar = self._scroll.verticalScrollBar()
        return int(bar.maximum() - bar.value())

    def _jump_distance(self) -> int:
        if self._jump_threshold is not None:
            return int(self._jump_threshold)
        return max(_JUMP_MIN_DISTANCE, self._scroll.viewport().height())

    def setJumpThreshold(self, distance: int) -> None:
        """设置「回到底部」显示阈值（像素；``None`` 恢复默认动态阈值）。"""
        self._jump_threshold = None if distance is None else max(0, int(distance))
        self._update_jump_button()

    def jumpThreshold(self) -> Optional[int]:
        """获取「回到底部」显示阈值（``None`` 表示默认动态阈值）。"""
        return self._jump_threshold

    def _position_jump_button(self) -> None:
        margin = _FLOAT_MARGIN
        self._jump_button.move(
            max(0, self.width() - self._jump_button.width() - margin),
            max(0, self.height() - self._jump_button.height() - margin),
        )

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        # 冻结值要用「resize 前的内容宽」：super().resizeEvent() 之后布局已把内容拉到
        # 新视口宽（super() 之前读 viewport()/_content 同样是新宽），只有事件自带的旧
        # 控件宽可用于推算（减去框架 / 滚动条占位）。
        self._resize_old_width = event.oldSize().width()
        super().resizeEvent(event)
        self._position_jump_button()
        self._on_view_resized(event.size().width())

    def showEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().showEvent(event)
        self._schedule_suspension_update()

    # -- 交互 resize 延迟重排 ----------------------------------------------

    def setResizeReflowDeferred(
        self,
        on: bool = True,
        minMessages: Optional[int] = None,
        delayMs: Optional[int] = None,
    ) -> None:
        """设置交互 resize 是否延迟重排（默认开启）。

        拖动窗口期间把消息内容宽度冻结在起始宽度，避免全部 Markdown
        查看器逐帧文本 reflow；停手 ``delayMs`` 毫秒后统一按新宽度重排
        （贴底时自动回到最新消息）。

        :param on: 是否启用
        :param minMessages: 触发延迟重排的最小消息数（缺省 50，小会话实时重排）
        :param delayMs: 停手后统一重排的延迟（毫秒，缺省 120）
        """
        self._resize_reflow_deferred = bool(on)
        if minMessages is not None:
            self._resize_reflow_min = max(0, int(minMessages))
        if delayMs is not None:
            self._resize_reflow_delay = max(0, int(delayMs))
        if not self._resize_reflow_deferred:
            self._resize_reflow_timer.stop()
            self._release_resize_reflow()

    def resizeReflowDeferred(self) -> bool:
        """是否启用交互 resize 延迟重排。"""
        return self._resize_reflow_deferred

    def _on_view_resized(self, width: int) -> None:
        """视图尺寸变化：拖动期间冻结内容宽度，停手后统一重排。"""
        if not self._resize_reflow_deferred:
            return
        if self.count() < self._resize_reflow_min or width <= 0:
            return
        if width == self._resize_width and not self._resize_reflow_timer.isActive():
            return  # 仅高度变化，无需 reflow
        if not self._resize_reflow_timer.isActive():
            chrome = self.width() - self._scroll.viewport().width()
            frozen = (
                self._resize_old_width - max(0, chrome)
                if self._resize_old_width > 0
                else self._content.width()
            )
            if frozen > 0:
                self._resize_frozen_width = frozen
                self._content.setFixedWidth(frozen)
        self._resize_width = width
        self._resize_reflow_timer.start(self._resize_reflow_delay)

    def _release_resize_reflow(self) -> None:
        """解除宽度冻结并按新宽度一次性重排。"""
        if self._resize_frozen_width <= 0:
            return
        self._resize_frozen_width = 0
        self._content.setMinimumWidth(0)
        self._content.setMaximumWidth(16777215)
        self._content.updateGeometry()
        self._content_layout.activate()
        # 冻结期间内容宽度可能已与视口脱节（ElaScrollBar 占 10px，出现/消失会改变视口
        # 宽度），而 setWidgetResizable 只在滚动区自身 resize 时才重算 —— 不显式拉回，
        # 内容会溢出视口被右侧裁掉。
        self._sync_content_width()
        if self._stick:
            self._scroll_to_bottom()
        self._update_jump_button()
        self._schedule_suspension_update()

    def _sync_content_width(self) -> None:
        """把内容宽度对齐视口（滚动区自身不 resize 时需要显式调用）。"""
        viewport_width = self._scroll.viewport().width()
        if viewport_width > 0 and self._content.width() != viewport_width:
            self._content.resize(viewport_width, self._content.height())

    def _follow_bottom(self) -> None:
        """内容变化后跟随底部（用户已上滚 / 批量加载中不打扰）。"""
        if self._batch_depth > 0:
            return
        if self._stick and not self._follow_hold and not self._follow_timer.isActive():
            self._follow_timer.start(0)

    def _scroll_to_bottom_if_sticky(self) -> None:
        if not self._stick or self._follow_hold:
            self._update_jump_button()
            return
        self._scroll_to_bottom()

    def _on_range_changed(self, _minimum: int, _maximum: int) -> None:
        """滚动范围变化（Markdown / 工具卡展开等异步重排）时保持贴底。

        正在展开 / 收起工具卡时消费本次变化并延长暂停窗口（视口不动，避免跳动）；
        其余情况（流式输出、异步渲染）贴底时只对齐一次，不轮询。
        """
        if self._follow_hold:
            self._hold_timer.start(_FOLLOW_HOLD_MS)
            return
        if self._stick:
            self._scroll_to_bottom()
        self._schedule_suspension_update()

    def holdFollow(self, hold: bool = True) -> None:
        """暂停 / 恢复贴底跟随（展开收起工具卡等交互期间使用）。

        ``hold=True`` 后 ``_FOLLOW_HOLD_MS`` 毫秒自动恢复，期间滚动范围变化
        不会带动视口，避免消息区跳动。
        """
        self._follow_hold = bool(hold)
        if self._follow_hold:
            self._hold_timer.start(_FOLLOW_HOLD_MS)
        else:
            self._hold_timer.stop()

    def followHeld(self) -> bool:
        """当前是否处于贴底跟随暂停状态。"""
        return self._follow_hold

    def _release_follow_hold(self) -> None:
        self._follow_hold = False

    def _on_tool_toggled(self) -> None:
        """工具卡展开 / 收起：暂停跟随，保持视口位置不变。"""
        self.holdFollow(True)

    def _scroll_to_bottom(self) -> None:
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def scrollToBottom(self) -> None:
        """滚动到底部并恢复自动跟随。"""
        self._stick = True
        self._scroll_to_bottom()
        self._update_jump_button()

    def setStickToBottom(self, on: bool) -> None:
        """设置是否自动跟随底部。"""
        self._stick = bool(on)
        if self._stick:
            self.scrollToBottom()

    def stickToBottom(self) -> bool:
        """是否处于自动跟随底部状态。"""
        return self._stick

    # -- 滚动条 ------------------------------------------------------------

    def setScrollBarPolicy(self, policy) -> None:
        """设置垂直滚动条策略（默认 :attr:`Qt.ScrollBarPolicy.ScrollBarAsNeeded`）。

        :param policy: ``Qt.ScrollBarPolicy`` 成员。``ScrollBarAsNeeded``
            仅在内容溢出时显示（默认）；``ScrollBarAlwaysOn`` 常显；
            ``ScrollBarAlwaysOff`` 彻底隐藏 —— 注意此时只能滚轮 / 键盘滚动，
            没有可拖动的把手。

        滚动条本身是 ``ElaScrollBar``（Ela 自绘：静止 2.4px 细柄，悬停展开
        成 6px 带上下箭头），可拖动、点击绝对定位。手动拖动会把
        :meth:`stickToBottom` 置 ``False``（复用既有的 ``valueChanged`` 逻辑）。
        """
        self._scroll.setVerticalScrollBarPolicy(policy)
        # ElaScrollBar 静止占 10px：策略变化会让视口宽度变化，内容要跟着拉回
        self._sync_content_width()
        self._update_jump_button()

    def scrollBarPolicy(self):
        """获取垂直滚动条策略（:meth:`setScrollBarPolicy` 的逆操作）。"""
        return self._scroll.verticalScrollBarPolicy()

    def scrollBar(self) -> QScrollBar:
        """获取垂直滚动条控件（``ElaScrollBar``）。

        用于宿主做策略之外的调节，例如 ``setIsAnimation(True)`` 让内容增长
        时范围平滑过渡、``setSpeedLimit(...)`` 改滚轮步进上限。
        """
        return self._scroll.verticalScrollBar()

    # -- 外观 --------------------------------------------------------------

    def setAvatarVisible(self, on: bool) -> None:
        """显示/隐藏全部头像（含后续新增消息）。"""
        self._avatar_visible = bool(on)
        for bubble in self._bubbles.values():
            bubble.setAvatarVisible(self._avatar_visible)

    def avatarVisible(self) -> bool:
        """头像是否可见。"""
        return self._avatar_visible

    def setAvatarShape(self, shape: str) -> None:
        """设置头像形状（对已有消息与后续消息生效）。

        - ``"circle"``（默认）：正圆；
        - ``"rounded"``：圆角方形；
        - ``"square"``：直角方形。

        非法值回落为默认形状。
        """
        self._avatar_shape = normalizeAvatarShape(shape)
        for bubble in self._bubbles.values():
            bubble.setAvatarShape(self._avatar_shape)

    def avatarShape(self) -> str:
        """获取头像形状。"""
        return self._avatar_shape

    def setUserAvatar(self, source: ElaChatAvatarSource) -> None:
        """设置用户消息头像（含已存在消息与后续消息）。

        :param source: SVG 数据 / SVG 或位图文件路径 / ``bytes`` /
            ``QPixmap`` / ``QImage`` / ``QIcon``；``None`` 清除并回退内置图标
        """
        self._user_avatar = source
        for bubble in self._bubbles.values():
            if bubble.role() == ElaChatRoleType.User:
                bubble.setAvatarImage(source)

    def userAvatar(self) -> Optional[ElaChatAvatarSource]:
        """获取用户头像来源（未设置返回 ``None``）。"""
        return self._user_avatar

    def setAssistantAvatar(self, source: ElaChatAvatarSource) -> None:
        """设置助手消息头像（含已存在消息与后续消息）。

        :param source: SVG 数据 / SVG 或位图文件路径 / ``bytes`` /
            ``QPixmap`` / ``QImage`` / ``QIcon``；``None`` 清除并回退内置图标
        """
        self._assistant_avatar = source
        for bubble in self._bubbles.values():
            if bubble.role() == ElaChatRoleType.Assistant:
                bubble.setAvatarImage(source)

    def assistantAvatar(self) -> Optional[ElaChatAvatarSource]:
        """获取助手头像来源（未设置返回 ``None``）。"""
        return self._assistant_avatar

    def setUserBubbleMaxWidth(self, ratio: float) -> None:
        """设置用户气泡最大宽度比例（含后续新增消息）。"""
        self._user_bubble_ratio = max(0.1, min(1.0, float(ratio)))
        for bubble in self._bubbles.values():
            if bubble.role() == ElaChatRoleType.User:
                bubble.setMaxWidthRatio(self._user_bubble_ratio)

    def userBubbleMaxWidth(self) -> float:
        """获取用户气泡最大宽度比例。"""
        return self._user_bubble_ratio

    def setContentMaxWidth(self, width: int) -> None:
        """设置助手消息内容最大宽度（像素，``0`` 表示不限，默认不限）。

        宽窗口下可用它限制行长（如 ``860``）；对已有与后续消息立即生效
        （用户 / 系统消息不受影响）。

        **限的是整列**：``_column`` 容器同时装正文、附件条与底部行，
        ``_apply_content_max_width()`` 限 ``_column`` 而非只有正文 ——
        只限正文的话宽窗口下底部行会往右伸出去，右边缘就参差不齐了。
        """
        self._content_max_width = max(0, int(width))
        for bubble in self._bubbles.values():
            if bubble.role() == ElaChatRoleType.Assistant:
                bubble.setContentMaxWidth(self._content_max_width)

    def contentMaxWidth(self) -> int:
        """获取助手消息内容最大宽度（``0`` 表示不限）。"""
        return self._content_max_width

    def setEmptyTitle(self, text: str) -> None:
        """设置空态标题。"""
        self._empty.setTitle(text)

    def emptyTitle(self) -> str:
        """获取空态标题。"""
        return self._empty.title()

    def setEmptySubtitle(self, text: str) -> None:
        """设置空态副标题。"""
        self._empty.setSubtitle(text)

    def emptySubtitle(self) -> str:
        """获取空态副标题。"""
        return self._empty.subtitle()

    def setSuggestions(self, suggestions: Optional[list]) -> None:
        """设置空态建议按钮列表。"""
        self._empty.setSuggestions(suggestions)

    def suggestions(self) -> list:
        """获取空态建议列表。"""
        return self._empty.suggestions()
