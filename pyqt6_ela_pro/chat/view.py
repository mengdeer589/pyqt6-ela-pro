"""聊天消息列表视图：把气泡排布在滚动区中，提供消息增删改、流式渲染与虚拟化。

所有面向消息的方法以 ``messageId`` 作为**首位**参数。
"""

from __future__ import annotations

from collections import deque
from typing import Optional

from PyQt6.QtCore import (
    QElapsedTimer,
    QTimer,
    Qt,
    pyqtSignal,
)
from PyQt6.QtWidgets import (
    QAbstractScrollArea,
    QFrame,
    QVBoxLayout,
    QWidget,
)
from PyQt6ElaWidgetTools import (
    ElaScrollArea,
)

from ..tooltips import ElaToolTipPositionType, set_tooltip
from ..widget_base import ElaThemeWidget
from .blocks import (
    AVATAR_DEFAULT_SHAPE,
    toolDefaultOpen,
)
from .bubble import DISCLAIMER_TEXT, ElaChatBubble
from .view_appearance import _ViewAppearanceMixin
from .view_search import _ViewSearchMixin
from .view_timeline import _ViewTimelineMixin
from .view_messages import _ViewMessagesMixin
from .view_stream import _ViewStreamMixin
from .view_scroll import _ViewScrollMixin

from .view_parts import (
    ChatContent,
    EmptyState,
    JumpToBottomButton,
    NestedScrollGuard,
)
from .message import (
    ElaChatMessage,
    ElaChatReasoningStyleType,
)
from .session import ElaChatSessionStats
from .store import ChatMessageStore
from .virtualizer import ChatVirtualizer
from .view_metrics import (
    _MESSAGE_SPACING,
)

#: 滚动容器内容边距（左、上、右、下）
_CONTENT_MARGIN = (10, 12, 10, 12)
#: 交互 resize 延迟重排：停手多久后统一 reflow（毫秒）
_RESIZE_REFLOW_DELAY_MS = 120
#: 交互 resize 延迟重排的最小消息数（小会话保持实时 reflow）
_RESIZE_REFLOW_MIN_MESSAGES = 50
#: 交互 resize 延迟重排的最小分段数（少消息但工具卡 / 正文很多的会话同样要延迟）
_RESIZE_REFLOW_MIN_PARTS = 200
#: 批量恢复超过该消息数时，连气泡壳一起延迟（小会话直接建壳更简单）
_SHELL_VIRTUAL_MIN_MESSAGES = 80
#: 超过该消息数时用「spacer + 可见气泡」虚拟列表（不再为每条消息建占位控件）
_VIRTUAL_LIST_MIN_MESSAGES = 200
#: 视口外查看器挂起的最小消息数
_SUSPEND_MIN_MESSAGES = 80
#: 批量渐进渲染的时间片预算（毫秒）
_BATCH_RENDER_BUDGET_MS = 8
#: 批量加载时**先渲染**的最新消息条数（用户的视线通常停在底部）
_BATCH_EAGER_COUNT = 12
#: 首屏渲染的时间上限（毫秒）：超过就把剩余消息留给懒加载，先把画面放出来
_BATCH_EAGER_BUDGET_MS = 48
#: 助手消息阅读宽度（像素，0 表示不限；宿主可 setContentMaxWidth 收紧）
_CONTENT_MAX_WIDTH = 0


class ElaChatView(
    _ViewMessagesMixin,
    _ViewStreamMixin,
    _ViewScrollMixin,
    _ViewTimelineMixin,
    _ViewSearchMixin,
    _ViewAppearanceMixin,
    ElaThemeWidget,
):
    """聊天消息列表视图（可独立使用，也可由 ``ElaChatWidget`` 组装）。

    ``parts`` 是消息的唯一真源，``text`` / ``reasoning`` / ``tool_calls`` /
    ``stats`` 由 :meth:`ElaChatMessage.withParts` 派生；改内容请走宿主 API，
    别直接对 ``bubble`` 调内部协议（会绕过派生结算）。
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
    #: 插入了待答复的工具审批（参数：消息 id、``requestId``）；组件不阻塞，宿主自行挂起后端
    permissionRequested = pyqtSignal(int, str)
    #: 审批已落定（参数：消息 id、``requestId``、reply、answer、feedback）
    permissionReplied = pyqtSignal(int, str, str, str, str)
    #: 交互卡已就绪，请放进输入区 dock（参数：消息 id、partId、卡片）
    permissionDockRequested = pyqtSignal(int, str, object)
    #: 某条审批已落定（参数：消息 id、partId）—— dock 据此撤下当前卡、接下一张
    permissionSettled = pyqtSignal(int, str)
    #: 用户在错误卡 / 自动重试卡上点击「重试」（参数：消息 id）—— 同参数重发
    retryRequested = pyqtSignal(int)
    #: 用户取消自动重试（参数：消息 id）
    retryCancelled = pyqtSignal(int)
    #: 待发送消息上的动作（参数：消息 id、动作：queue / delete）
    pendingUserActionRequested = pyqtSignal(int, str)
    #: 用户点击附件 chip（参数：消息 id、路径）
    attachmentClicked = pyqtSignal(int, str)
    #: 空态建议被点击（参数：建议文本）
    suggestionClicked = pyqtSignal(str)
    #: 批量渐进渲染完成（``beginBatch`` / ``endBatch`` 队列排空）
    batchRenderFinished = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._store = ChatMessageStore()
        self._virtualizer = ChatVirtualizer(self)
        #: 壳虚拟化的前缀高度（messageId 顺序 / start 偏移），二分可见区间
        self._virtual_order: list = []
        self._virtual_prefix: list = []
        self._virtual_prefix_dirty = True
        #: 只有消息列表结构变化（增删 / 清空）才需重建 order / index，滚动时不必。
        self._virtual_order_dirty = True
        self._bubbles: dict = {}
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
        self._waiting_placeholder_enabled = True
        self._jump_threshold = None
        self._scroll_guards: list = []
        self._guards_by_message: dict = {}
        self._strict_ids = False
        #: 时间线密度（None = 默认）
        self._timeline_detail = None
        #: partId -> 展开覆盖（所有气泡共享同一份字典，物化时自动生效）
        self._disclosure: dict = {}
        #: messageId -> (attempt, message, nextAt)
        self._retry: dict = {}
        #: 运行态活动行（惰性创建）
        self._activity_row = None
        self._activity_text = ""
        #: 会话内搜索状态
        self._search_hits: list = []
        self._search_index = -1
        self._search_query = ""
        self._search_case = False
        self._search_bar = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._scroll = ElaScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # 显式设置一次：上游 V3.0 默认已是 AsNeeded，这里防回退并让意图就近可读。
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._content = ChatContent()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(*_CONTENT_MARGIN)
        self._content_layout.setSpacing(_MESSAGE_SPACING)
        self._empty = EmptyState(self._content)
        self._content_layout.addWidget(self._empty)
        self._content_layout.addStretch(1)
        self._scroll.setWidget(self._content)
        layout.addWidget(self._scroll)

        self._jump_button = JumpToBottomButton(self)
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
        self._resize_reflow_min_parts = _RESIZE_REFLOW_MIN_PARTS
        self._resize_reflow_delay = _RESIZE_REFLOW_DELAY_MS
        self._resize_width = 0
        self._resize_frozen_width = 0
        self._resize_reflow_timer = QTimer(self)
        self._resize_reflow_timer.setSingleShot(True)
        self._resize_reflow_timer.timeout.connect(self._release_resize_reflow)

        # -- 批量渐进渲染（历史加载先建骨架，按时间片渲染 Markdown） --------
        self._batch_depth = 0
        #: 批量加载时是否延迟建分段控件（True = 首屏外只存 parts 数据）
        self._virtual_parts_enabled = True
        #: 批量恢复大量消息时是否连气泡壳一起延迟（只留等高占位）
        self._virtual_shells_enabled = True
        self._virtual_shells_min = _SHELL_VIRTUAL_MIN_MESSAGES
        self._virtual_list_enabled = True
        self._virtual_list_min = _VIRTUAL_LIST_MIN_MESSAGES
        self._virtual_list_mode = False
        self._virtual_top_spacer: Optional[QWidget] = None
        self._virtual_bottom_spacer: Optional[QWidget] = None
        self._virtual_heights: dict = {}
        self._virtual_bubble_ids: list = []
        self._virtual_index: dict = {}
        self._virtual_refreshing = False
        self._virtual_pending_top: Optional[int] = None
        self._virtual_window_timer = QTimer(self)
        self._virtual_window_timer.setSingleShot(True)
        self._virtual_window_timer.timeout.connect(self._refresh_virtual_window)
        #: 只有占位、尚未建 bubble 的消息（messageId -> 占位控件）
        self._shell_placeholders: dict = {}
        #: 本次批量恢复是否启用了壳虚拟化（滚动时允许把远处气泡收回占位）
        self._shell_recycling = False
        self._render_queue: deque = deque()
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._process_render_queue)
        #: 首屏预算内没渲染完、留给「滚上去再渲染」的消息 id（升序）
        self._lazy_ids: list[int] = []
        #: 首屏已经渲染的消息条数（判定 _BATCH_EAGER_COUNT 预算）
        self._batch_eager_rendered = 0
        #: 懒加载分页标志（防止补偿滚动触发的 valueChanged 递归）
        self._loading_older = False
        #: 懒加载后待补偿的滚动锚点 ``(top, old_max)``，等 rangeChanged 再应用
        self._pending_anchor: Optional[tuple] = None
        self._lazy_timer = QTimer(self)
        self._lazy_timer.setSingleShot(True)
        self._lazy_timer.timeout.connect(self._load_older_page)

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

    def deleteLater(self) -> None:  # noqa: N802 (Qt 命名)
        """销毁前停掉全部子定时器：0ms 跟随定时器可能在 DeferredDelete 前触发。"""
        for timer in self.findChildren(QTimer):
            timer.stop()
        super().deleteLater()

    # -- 虚拟化 / 视口挂起（实现在 ``virtualizer.py``） -------------------

    def _disable_virtual_list(self) -> None:
        self._virtualizer._disable_virtual_list()

    def _virtual_height(self, messageId: int) -> int:
        return self._virtualizer._virtual_height(messageId)

    def _ensure_virtual_prefix(self) -> None:
        self._virtualizer._ensure_virtual_prefix()

    def _init_virtual_spacers(self) -> None:
        self._virtualizer._init_virtual_spacers()

    def _materialize_virtual_bubble(self, messageId: int) -> Optional[ElaChatBubble]:
        return self._virtualizer._materialize_virtual_bubble(messageId)

    def _dematerialize_virtual_bubble(self, messageId: int) -> None:
        self._virtualizer._dematerialize_virtual_bubble(messageId)

    def _scroll_to_virtual_message(self, messageId: int) -> bool:
        return self._virtualizer._scroll_to_virtual_message(messageId)

    def _refresh_virtual_window(self, at_bottom: bool = False) -> None:
        self._virtualizer._refresh_virtual_window(at_bottom)

    def _add_shell_placeholder(self, message: ElaChatMessage) -> QWidget:
        return self._virtualizer._add_shell_placeholder(message)

    def _refresh_shell_heights(self) -> None:
        self._virtualizer._refresh_shell_heights()

    def _materialize_shell(self, messageId: int) -> Optional[ElaChatBubble]:
        return self._virtualizer._materialize_shell(messageId)

    def _schedule_lazy_fill(self) -> None:
        self._virtualizer._schedule_lazy_fill()

    def _maybe_request_older(self) -> None:
        self._virtualizer._maybe_request_older()

    def _load_older_page(self) -> None:
        self._virtualizer._load_older_page()

    def _schedule_suspension_update(self) -> None:
        self._virtualizer._schedule_suspension_update()

    def _update_suspension(self) -> None:
        self._virtualizer._update_suspension()

    def _suspend_message_viewers(self, messageId: int) -> None:
        self._virtualizer._suspend_message_viewers(messageId)

    def _dematerialize_shell(self, messageId: int) -> bool:
        return self._virtualizer._dematerialize_shell(messageId)

    def _materialize_visible_placeholder(
        self, top: int, bottom: int, margin: float
    ) -> None:
        self._virtualizer._materialize_visible_placeholder(top, bottom, margin)

    def _restore_message_viewers(self, messageId: int) -> None:
        self._virtualizer._restore_message_viewers(messageId)

    def _restore_all_suspended(self) -> None:
        self._virtualizer._restore_all_suspended()

    # -- 查询 --------------------------------------------------------------

    @property
    def _messages(self) -> list[ElaChatMessage]:
        return self._store.items

    @property
    def _message_index(self) -> dict[int, ElaChatMessage]:
        return self._store.index

    @property
    def _height_meta_cache(self) -> dict[int, tuple]:
        return self._store.height_meta

    @property
    def _next_id(self) -> int:
        return self._store.next_id

    @_next_id.setter
    def _next_id(self, value: int) -> None:
        self._store.next_id = int(value)

    @property
    def _dirty_syncs(self) -> set[int]:
        return self._store.dirty

    def count(self) -> int:
        """消息条数。"""
        return self._store.count()

    def messages(self) -> list:
        """消息只读快照（``ElaChatMessage`` 列表）。"""
        self._flush_pending_syncs()
        return list(self._messages)

    def message(self, messageId: int) -> Optional[ElaChatMessage]:
        """按 id 查询消息快照（不存在返回 ``None``）。"""
        self._flush_pending_syncs()
        return self._message_index.get(messageId)

    def bubble(self, messageId: int) -> Optional[ElaChatBubble]:
        """按 id 获取消息气泡控件（不存在返回 ``None``）。"""
        return self._bubbles.get(messageId)

    def setVirtualPartsEnabled(self, on: bool = True) -> None:
        """批量加载时是否延迟建分段控件（默认开）；关闭时当场物化已延迟的消息。"""
        self._virtual_parts_enabled = bool(on)
        if not self._virtual_parts_enabled:
            for messageId in list(self._shell_placeholders):
                self._materialize_shell(messageId)
            for bubble in self._bubbles.values():
                if bubble.partsDeferred():
                    bubble.materializeParts()
                if bubble.partsWindowed():
                    bubble.expandParts()

    def virtualPartsEnabled(self) -> bool:
        """是否启用延迟分段物化。"""
        return self._virtual_parts_enabled

    def setShellVirtualizationEnabled(
        self, on: bool = True, minMessages: Optional[int] = None
    ) -> None:
        """批量恢复大量消息时是否连气泡壳一起延迟（默认开，阈值 80 条）。

        关闭后所有消息立即建 ``ElaChatBubble``，已延迟的占位消息当场物化。
        """
        self._virtual_shells_enabled = bool(on)
        if minMessages is not None:
            self._virtual_shells_min = max(0, int(minMessages))
        if not self._virtual_shells_enabled:
            if self._virtual_list_mode:
                self._disable_virtual_list()
            self._shell_recycling = False
            for messageId in list(self._shell_placeholders):
                self._materialize_shell(messageId)
        elif self._shell_placeholders and not self._virtual_list_mode:
            self._shell_recycling = True

    def setVirtualListEnabled(
        self, on: bool = True, minMessages: Optional[int] = None
    ) -> None:
        """超长历史是否启用 spacer 虚拟列表（默认 >200 条，非逐条占位）。

        关闭后已进入虚拟列表的会话会当场物化全部消息（重会话会慢，属显式选择）。
        """
        self._virtual_list_enabled = bool(on)
        if minMessages is not None:
            self._virtual_list_min = max(0, int(minMessages))
        if not self._virtual_list_enabled and self._virtual_list_mode:
            self._disable_virtual_list()

    def shellVirtualizationEnabled(self) -> bool:
        """是否启用气泡壳延迟物化。"""
        return self._virtual_shells_enabled

    def materializeMessage(self, messageId: int, flush: bool = True) -> bool:
        """物化指定消息的分段控件（虚拟化 / 延迟加载的显式入口）。

        :returns: 是否真的执行了物化或 Markdown 渲染
        """
        self._require_int_id(messageId, "materializeMessage")
        bubble = self._bubbles.get(messageId)
        if bubble is None:
            bubble = self._materialize_shell(messageId)
        if bubble is None:
            if self._strict_ids:
                raise KeyError(f"materializeMessage: 消息 {messageId} 不存在")
            return False
        changed = bubble.materializeParts()
        if flush:
            bubble.setRenderDeferred(False)
            changed = bubble.flushRender() or changed
        self._sync_parts(messageId)
        self._flush_pending_syncs()
        return changed

    def scrollToMessage(self, messageId: int) -> bool:
        """物化并滚动到指定消息；返回消息是否存在。"""
        self._require_int_id(messageId, "scrollToMessage")
        self.materializeMessage(messageId, flush=True)
        bubble = self._bubbles.get(messageId)
        if bubble is None:
            return False
        self._scroll.ensureWidgetVisible(bubble, 0, 0)
        return True

    # -- 严格 id 模式 --------------------------------------------------------

    def setStrictIds(self, on: bool) -> None:
        """严格模式：操作**不存在的消息**时抛 :class:`KeyError` 而非静默忽略。

        默认关闭（流式迟到事件属正常）；开发 / 调试期打开可暴露宿主传错 id。
        只影响公开 mutator，内部路径（滚动跟随 / 挂起 / 分段同步）继续静默。
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

    def _require_bubble(
        self, messageId: int, api: str = "", materialize: bool = True
    ) -> ElaChatBubble:
        """取气泡；非法 id 抛 :class:`TypeError`，严格模式下不存在抛 :class:`KeyError`。

        壳被延迟物化的消息会先 ``_materialize_shell``；``materialize=False``
        时留给调用方自行处理（如 ``removeMessage`` 不需要建壳）。
        """
        self._require_int_id(messageId, api)
        bubble = self._bubbles.get(messageId)
        if bubble is None and materialize and messageId in self._shell_placeholders:
            bubble = self._materialize_shell(messageId)
        if bubble is None and self._strict_ids:
            raise KeyError(
                f"{api or '该操作'}：消息 id {messageId!r} 不存在"
                f"（现有 id：{[m.id for m in self._messages][:20]}）"
            )
        return bubble

    def lastMessage(self) -> Optional[ElaChatMessage]:
        """最后一条消息快照（无消息返回 ``None``）。"""
        self._flush_pending_syncs()
        return self._messages[-1] if self._messages else None

    def sessionStats(self, limit: int = 0) -> ElaChatSessionStats:
        """会话级用量汇总（计数 / 当前上下文四路词元 / 使用率 / 累计成本 / 工具统计）。

        当前用量取最后一条有 tokens 的助手消息的最后一步（对齐 opencode
        ``getSessionContext``）；``total_tokens`` = 四路和，成本跨全部消息求和。

        :param limit: 模型上下文上限（词元）；``> 0`` 时才计算 ``usage_percent``
        :returns: :class:`ElaChatSessionStats` 快照
        """
        return ElaChatSessionStats.fromMessages(self.messages(), limit)

    def contentWidget(self) -> QWidget:
        """获取滚动区内容容器（高级用法）。"""
        return self._content

    # -- 增删改 ------------------------------------------------------------

    # -- 会话 bundle（导出 / 导入） ----------------------------------------

    # -- 批量渐进渲染 ------------------------------------------------------

    def beginBatch(self) -> None:
        """进入批量加载模式（可嵌套）。

        批量内新增的助手文本消息先建骨架、跳过快照同步与贴底跟随；``endBatch``
        后先渲染最新的 ``_BATCH_EAGER_COUNT`` 条，其余留给滚动懒加载。
        """
        self._batch_depth += 1
        if self._batch_depth == 1:
            self._scroll.viewport().setUpdatesEnabled(False)

    def endBatch(self) -> None:
        """结束批量加载：先渲染最新的一屏，其余留给滚动懒加载。"""
        if self._batch_depth <= 0:
            return
        self._batch_depth -= 1
        if self._batch_depth > 0:
            return
        if self._virtual_list_mode:
            self._init_virtual_spacers()
            self._refresh_virtual_window(at_bottom=True)
            self._finish_batch_render()
            return
        if self._render_queue:
            # 用户打开历史会话时停在底部：从最新一条往前渲染，首屏才有内容
            self._render_queue = deque(reversed(self._render_queue))
            self._batch_eager_rendered = 0
            self._render_timer.start(0)
        else:
            self._finish_batch_render()

    def isBatchActive(self) -> bool:
        """是否处于批量加载模式。"""
        return self._batch_depth > 0

    def _process_render_queue(self) -> None:
        """渲染队列中的消息（**从最新一条往前**，只渲染首屏附近的）。"""
        if not self._render_queue:
            self._finish_batch_render()
            return
        timer = QElapsedTimer()
        timer.start()
        while self._render_queue:
            if (
                self._batch_eager_rendered >= _BATCH_EAGER_COUNT
                or timer.elapsed() >= _BATCH_EAGER_BUDGET_MS
            ):
                break
            messageId = self._render_queue.popleft()
            bubble = self._materialize_shell(messageId)
            if bubble is None:
                continue
            bubble.materializeParts()
            bubble.setRenderDeferred(False)
            bubble.flushRender()
            self._sync_parts(messageId)
            self._batch_eager_rendered += 1
        if self._render_queue:
            # 剩下的都是更早的消息：保持升序交给懒加载（快照仍要标记同步）
            self._lazy_ids.extend(reversed(self._render_queue))
            for messageId in self._render_queue:
                self._sync_parts(messageId)
            self._render_queue.clear()
        self._finish_batch_render()

    def _finish_batch_render(self) -> None:
        """批量渲染收尾：恢复刷新、激活布局、贴底并通知宿主。"""
        self._scroll.viewport().setUpdatesEnabled(True)
        self._scroll.viewport().update()
        self._content_layout.activate()
        self._follow_bottom()
        self.batchRenderFinished.emit()
        self._schedule_suspension_update()
        self._schedule_lazy_fill()
        if self._virtual_list_mode:
            # 首次 spacer 高度要等 QScrollArea 重新算完内容尺寸后再刷一次
            self._virtual_window_timer.start(0)

    # -- 更早消息的懒加载 --------------------------------------------------

    # -- 视口外查看器挂起 --------------------------------------------------

    def setViewportSuspension(
        self, on: bool = True, minMessages: Optional[int] = None
    ) -> None:
        """设置视口外消息是否挂起重型查看器（默认开启）。

        挂起把离视口较远（上下各 2 屏）消息的 Markdown 查看器替换为等高透明
        占位控件（``parts`` / 快照数据不变）；流式与批量加载中的消息不挂起。

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

    # -- 步骤 --------------------------------------------------------------

    # -- 思考层 ------------------------------------------------------------

    # -- 工具层 ------------------------------------------------------------

    # -- 合成段 / 压缩段 / 审批段 -------------------------------------------

    # -- 附件 / 用量 / 错误 -------------------------------------------------

    def guardNestedScroll(self, widget: QWidget) -> Optional["NestedScrollGuard"]:
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
        guard = NestedScrollGuard(area)
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

    # -- 内部状态 ----------------------------------------------------------

    # -- 贴底与滚动 --------------------------------------------------------

    # -- 交互 resize 延迟重排 ----------------------------------------------

    # -- 滚动条 ------------------------------------------------------------

    # -- 外观 --------------------------------------------------------------
