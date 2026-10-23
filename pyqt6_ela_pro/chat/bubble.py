"""
聊天消息气泡组件（``pyqt6_ela_pro.chat``）。

:class:`ElaChatBubble` 的助手消息按「步骤 + 内容分段」组织，与
:class:`~pyqt6_ela_pro.chat.message.ElaChatPart` 时间线一一对应：

1. **头部层** :class:`~pyqt6_ela_pro.chat.blocks.MessageHeader`
   （头像 + 名称 / 模型 + 时间 / 状态；用户消息右对齐镜像）；
2. **内容层**：``_parts_container`` 内按加入顺序排列全部分段——
   思考段（:class:`~pyqt6_ela_pro.chat.blocks.ReasoningBlock` 或内联查看器，
   行首为 :class:`~pyqt6_ela_pro.chat.blocks.ThinkingRow`）、
   正文段（可多个嵌入模式 ``ElaMarkdownViewer``）、
   每步工具面板（:class:`~pyqt6_ela_pro.chat.blocks.ToolGroupPanel`，
   内含 :class:`~pyqt6_ela_pro.chat.blocks.ToolCallCard` /
   :class:`~pyqt6_ela_pro.chat.blocks.ContextToolGroupCard`）、
   步骤用量徽标（:class:`~pyqt6_ela_pro.chat.blocks.StatsBadge`，
    展示模式见 :meth:`ElaChatBubble.setStatsMode`）；
3. **附件层** :class:`~pyqt6_ela_pro.chat.blocks.AttachmentStrip`（chips）；
4. **底部层** :class:`~pyqt6_ela_pro.chat.blocks.MessageActions`
   （复制 / 撤回 / 重新生成 + 自定义动作）与
   :class:`~pyqt6_ela_pro.chat.blocks.MessageMeta`（整轮耗时）。

用户消息为圆角气泡 + 可选中纯文本，系统消息为居中弱化文本。
主题切换实时换肤（颜色经 ``eTheme`` 语义令牌混合派生）。

**API 分两类（改代码前先分清）**

- **宿主 API**（改动某条消息的对外形态 / 取子控件）：
  ``text()`` / ``parts()`` / ``markdownViewer()`` / ``inlineReasoningViewer()`` /
  ``statsBadge()`` / ``toolPanels()`` / ``toolPanel()`` / ``actions()`` /
  ``footer()`` / ``meta()`` / ``header()`` / ``attachments()`` /
  ``setAvatarShape()`` / ``setActionsHoverReveal()`` / ``error()`` /
  ``setTopSpacing()`` 等；
- **view ↔ bubble 内部协议**（其余 ``beginText`` / ``appendText`` /
  ``addToolCall`` / ``setParts`` / ``setStatus`` / ``setStepStats`` /
  ``setRenderDeferred`` / ``setViewersSuspended`` / ``stampNow`` …）：
  **只在 view / 分组卡内部调用**。宿主要改某条消息，请走
  ``ElaChatView.<method>(messageId, ...)`` —— 直接对气泡调内部协议会绕过
  view 的 ``_sync_parts`` 派生结算与 ``_dirty_syncs`` 防抖，数据与界面分叉。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from .._internal import execElaMenu, is_deleted
from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QContextMenuEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from PyQt6ElaWidgetTools import ElaIconType, ElaMenu, ElaText, ElaThemeType

from .._styles import ColorText, setTextColor
from ..ela_markdown_viewer import ElaMarkdownViewer
from ..widget_base import ElaThemeWidget
from ._theme import accent_color, base_color, blend, muted_color, text_color
from .blocks import (
    AVATAR_DEFAULT_SHAPE,
    AVATAR_SIZE,
    CONTEXT_TOOLS,
    SHELL_TOOLS,
    AttachmentStrip,
    CompactionSeparator,
    ContextToolGroupCard,
    ElaChatAvatarSource,
    ErrorCard,
    MessageActions,
    MessageHeader,
    MessageMeta,
    PermissionCard,
    PermissionRecord,
    ReasoningBlock,
    StatsBadge,
    SteerNotice,
    ThinkingRow,
    ToolCallCard,
    ToolGroupPanel,
    _HeadingScanner,
    normalizeAvatarShape,
    toolDefaultOpen,
    toolSubtitleParts,
)
from .message import (
    ElaChatAttachment,
    ElaChatPart,
    ElaChatPartKindType,
    ElaChatPermission,
    ElaChatPermissionStatusType,
    ElaChatReasoningStyleType,
    ElaChatRoleType,
    ElaChatStats,
    ElaChatStatusType,
    ElaChatToolCall,
    ElaChatToolStatusType,
)
from .renderers import toolRendererGroupable, toolRendererSubtitle
from .timeline import ChatPartTimeline

#: 气泡圆角半径（逐角：左上 / 右上 / 右下 / 左下；右下小角做“尾巴”）
_BUBBLE_RADII = (12.0, 12.0, 4.0, 12.0)
#: 气泡内边距（左、上、右、下）
_BUBBLE_PADDING = (12, 8, 12, 8)
#: 行外边距（左右、上下）
_ROW_MARGIN = (12, 2, 12, 2)
#: 头像与内容间距
_ROW_SPACING = 10
#: 助手流式占位文案
_STREAMING_PLACEHOLDER = "正在生成…"
#: 助手消息底部「AI 生成」提示的默认文案
DISCLAIMER_TEXT = "内容由 AI 生成，仅供参考"
#: 底部「AI 生成」提示字号
_DISCLAIMER_PIXEL_SIZE = 12
#: 单条消息超过该步骤数时，物化只展开末尾若干步（历史超长回合）
#: 超长消息物化时保留的末尾步骤数（用户通常停在最新一步）
#: 用量徽标展示模式（底部整轮汇总 / 每步各自显示 / 完全不显示）
_STATS_MODES = ("footer", "steps", "none")
#: 状态对应的头部提示文本（``Queued`` 为展示态：流式开始后、首个模型输出前）
_STATUS_TEXTS = {
    ElaChatStatusType.Queued: "排队中…",
    ElaChatStatusType.Streaming: "生成中…",
    ElaChatStatusType.Stopped: "已停止",
    ElaChatStatusType.Error: "出错",
}
#: 右键菜单行高（与 markdown viewer / 终端一致）
_CONTEXT_MENU_ITEM_HEIGHT = 28


class _SelectableLabel(QLabel):
    """可选中纯文本标签：右键菜单走库内 ``ElaMenu``。

    ``QLabel`` 在 ``TextSelectableByMouse`` 下自带 Qt 原生右键菜单（Copy /
    Select All），与本库外观不一致，所以整体接管。
    """

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        execElaMenu(self._build_context_menu(), event.globalPos())
        event.accept()

    def _build_context_menu(self) -> ElaMenu:
        """构建右键菜单（Ela 风格：图标 + 统一行高）。"""
        menu = ElaMenu(self)
        menu.setMenuItemHeight(_CONTEXT_MENU_ITEM_HEIGHT)
        copy = menu.addElaIconAction(ElaIconType.IconName.Copy, "复制")
        copy.setEnabled(self.hasSelectedText())
        copy.triggered.connect(self._copy_selection)
        select_all = menu.addElaIconAction(ElaIconType.IconName.BorderAll, "全选")
        select_all.triggered.connect(self._select_all)
        return menu

    def _copy_selection(self) -> None:
        text = self.selectedText()
        if text:
            # Qt 的选区用 U+2029 表示换行，剪贴板里要还原成 \n（对齐原生菜单）
            QApplication.clipboard().setText(text.replace("\u2029", "\n"))

    def _select_all(self) -> None:
        # Qt 文本位置按 UTF-16 码元计（emoji 占 2 个），不能直接用 len(text)
        self.setSelection(0, len(self.text().encode("utf-16-le")) // 2)


class _BubbleBody(QWidget):
    """圆角气泡底板（用户消息，逐角圆角 + 深色描边）。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._bg = QColor()
        self._border = QColor()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def setBackground(self, color: QColor) -> None:
        """设置气泡底色。"""
        self._bg = QColor(color)
        self.update()

    def setBorder(self, color: QColor) -> None:
        """设置气泡描边色（透明表示不描边）。"""
        self._border = QColor(color)
        self.update()

    @staticmethod
    def _rounded_path(rect: QRectF) -> QPainterPath:
        """逐角圆角路径（``QPainterPath.addRoundedRect`` 不支持逐角半径）。"""
        top_left, top_right, bottom_right, bottom_left = _BUBBLE_RADII
        path = QPainterPath()
        path.moveTo(rect.left() + top_left, rect.top())
        path.lineTo(rect.right() - top_right, rect.top())
        path.arcTo(
            rect.right() - 2 * top_right,
            rect.top(),
            2 * top_right,
            2 * top_right,
            90.0,
            -90.0,
        )
        path.lineTo(rect.right(), rect.bottom() - bottom_right)
        path.arcTo(
            rect.right() - 2 * bottom_right,
            rect.bottom() - 2 * bottom_right,
            2 * bottom_right,
            2 * bottom_right,
            0.0,
            -90.0,
        )
        path.lineTo(rect.left() + bottom_left, rect.bottom())
        path.arcTo(
            rect.left(),
            rect.bottom() - 2 * bottom_left,
            2 * bottom_left,
            2 * bottom_left,
            270.0,
            -90.0,
        )
        path.lineTo(rect.left(), rect.top() + top_left)
        path.arcTo(rect.left(), rect.top(), 2 * top_left, 2 * top_left, 180.0, -90.0)
        path.closeSubpath()
        return path

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt 命名)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect().adjusted(0, 0, -1, -1))
        path = self._rounded_path(rect)
        painter.fillPath(path, self._bg)
        if self._border.alpha() > 0:
            pen = QPen(self._border)
            pen.setWidthF(1.0)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        painter.end()


class ElaChatBubble(ElaThemeWidget):
    """单条聊天消息气泡（用户 / 助手 / 系统三种角色，分层富消息；助手消息正文是
    Markdown 源）。
    """

    #: 助手消息流式结束（``endStream``）时发射
    streamFinished = pyqtSignal()
    #: 用户点击「复制」
    copyRequested = pyqtSignal()
    #: 用户点击「撤回」
    undoRequested = pyqtSignal()
    #: 用户点击「重新生成」
    regenerateRequested = pyqtSignal()
    #: 用户在错误卡上点击「重试」（同参数重发；由 view 转发成带 messageId 的
    #: ``retryRequested``）
    retryRequested = pyqtSignal()
    #: 插入了待答复的工具审批（参数：``requestId``）
    #:
    #: **库不在这里阻塞**：宿主收到后自行挂起后端（Qt 里挂起等用户点按钮会
    #: 卡死事件循环），用户点完卡片后组件发 ``permissionReplied``。
    permissionRequested = pyqtSignal(str)
    #: 审批已落定（参数：``requestId``、reply、answer、feedback）
    permissionReplied = pyqtSignal(str, str, str, str)
    #: **交互卡已就绪，请放进输入区上方的 dock**（参数：卡片、partId）
    #:
    #: 气泡不知道 dock 的存在（dock 挂在 :class:`ElaChatWidget` 上），所以用
    #: 信号把「这张卡该去哪儿」交出去。时间线上不摆交互卡 —— 审批是当前这一步
    #: 的事，摆在历史流里既窄又旧（提问被压到折行、候选卡说明被页脚盖住）。
    permissionDockRequested = pyqtSignal(object, str)
    #: 该 part 的审批已落定（参数：partId）—— dock 据此把当前卡撤下、接下一张
    permissionSettled = pyqtSignal(str)
    #: 用户点击附件 chip（参数：路径）
    attachmentClicked = pyqtSignal(str)
    #: 自定义动作被点击（参数：key）
    actionTriggered = pyqtSignal(str)
    #: 工具卡 / 分组卡展开收起（宿主可借此暂停贴底跟随）
    toolToggled = pyqtSignal()
    #: 新建了可滚动的正文 / 内联思考查看器（参数：查看器控件；
    #: ``ElaChatView`` 借此按需安装嵌套滚动过滤器）
    viewerCreated = pyqtSignal(QWidget)

    def __init__(
        self,
        role: str = ElaChatRoleType.Assistant,
        text: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._role = role if role in ElaChatRoleType.All else ElaChatRoleType.Assistant
        self._status = ElaChatStatusType.Done
        self._max_width_ratio = 0.72
        self._avatar_visible = True
        self._avatar_shape = AVATAR_DEFAULT_SHAPE
        self._title = ""
        self._timestamp = ""
        self._duration_ms = 0.0
        self._reasoning_style = ElaChatReasoningStyleType.Collapse
        self._actions_hover_reveal = True
        self._label: Optional[QLabel] = None
        self._body: Optional[_BubbleBody] = None
        self._content: Optional[QWidget] = None
        self._content_layout: Optional[QVBoxLayout] = None
        # -- 内容分段（助手消息按步骤有序排列） --------------------------
        self._parts: list = []
        self._part_widgets: dict = {}
        self._text_buffers: dict = {}
        #: 尚未开段的纯空白分片（首个非空白分片到来时一起开段；见 appendText）
        self._pending_text_lead: list = []
        self._heading_scanners: dict = {}
        self._text_width_cache: Optional[tuple] = None
        self._render_deferred = False
        self._pending_renders: dict = {}
        self._viewers_suspended = False
        self._suspended_viewers: dict = {}
        self._content_max_width = 0
        self._parts_container: Optional[QWidget] = None
        self._parts_layout: Optional[QVBoxLayout] = None
        self._timeline = ChatPartTimeline(self)
        #: 分段是否只存数据、尚未建控件（批量加载时按需物化）
        self._parts_deferred = False
        #: 超长消息只物化了末尾若干步（其余步骤折叠在「展开全部」按钮后）
        self._parts_windowed = False
        self._window_button = None
        self._deferred_placeholder: Optional[QWidget] = None
        self._step_index = 1
        self._current_reasoning_id: Optional[str] = None
        self._current_text_id: Optional[str] = None
        self._current_stats_id: Optional[str] = None
        #: 所属消息 id（由 ``ElaChatView`` 建气泡时写入；工具渲染器上下文要用）
        self._message_id = 0
        self._stats_mode = "footer"
        #: ``setParts`` 重放期间为 True：逐段 setStepStats 不重复摆徽标，
        #: 由 setParts 收尾统一 apply 一次（bug #17）。
        self._stats_batch = False
        #: 历史分段批量构建深度：回放期间暂缓布局 / 面板显示（bug #17）
        self._bulk_build = 0
        #: 回放期间待统一 show / 刷新摘要的工具面板
        self._bulk_panels: set = set()
        self._stream_ended = False
        self._generation_started = True
        #: 底部「AI 生成」提示（仅助手消息；文本 / 显隐见 setDisclaimer）
        self._disclaimer_text = DISCLAIMER_TEXT
        self._disclaimer_visible = True
        #: 点击「复制」后是否弹「已复制到剪贴板」提示（由 view 建卡时下推）
        self._copy_notification_enabled = True
        self._disclaimer: Optional[ElaText] = None
        self._stats_host: Optional[QWidget] = None
        self._stats_layout: Optional[QHBoxLayout] = None
        #: 已停靠底部行的步骤徽标 ``(partId, 原布局下标)``。停靠是**独占**的：
        #: 换停靠前要把旧徽标放回时间线，否则恢复/重放会把中间徽标全堆进 footer。
        self._docked_stats: Optional[tuple] = None
        self._thinking_row: Optional[ThinkingRow] = None
        # -- 工具（每步一个外层面板） ------------------------------------
        self._panels: list = []
        self._panel_steps: dict = {}
        self._current_tool_panel: Optional[ToolGroupPanel] = None
        self._panel_calls: dict = {}
        self._tool_cards: dict = {}
        self._group_card = None
        self._tool_grouping = True
        #: 「哪些工具卡默认展开」的策略（可注入，见 setToolDefaultOpen）
        self._tool_open_policy = toolDefaultOpen
        self._error: Optional[ErrorCard] = None
        self._attachments: Optional[AttachmentStrip] = None
        # -- 合成 / 压缩 / 审批分段 -----------------------------------------
        #: 审批分段 id -> 审批卡控件
        self._permission_cards: dict = {}
        #: 仍在 dock 里等待用户操作的**交互卡**（partId -> 卡片）；落定后清空
        self._interactive_cards: dict = {}
        self._header = MessageHeader(self._role, self)
        self._meta = MessageMeta(self)
        self._actions = MessageActions(self)
        #: 底部行容器（操作按钮 + 用量 + 耗时），流式期间整行隐藏，见 _sync_footer
        self._footer: Optional[QWidget] = None
        #: 内容列容器（正文 + 附件条 + 底部行），``setContentMaxWidth`` 限的是它
        self._column: Optional[QWidget] = None

        self._build_layout()
        self._setup_actions()
        if text:
            self.setText(text)
        self.setStatus(self._status)
        self._apply_theme()

    # -- 构建 --------------------------------------------------------------

    def _build_layout(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(*_ROW_MARGIN)
        root.setSpacing(2)

        # 头部层
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(_ROW_SPACING)
        self._header.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        if self._role == ElaChatRoleType.User:
            header_row.addStretch(1)
            header_row.addWidget(self._header)
        else:
            header_row.addWidget(self._header)
            header_row.addStretch(1)
        root.addLayout(header_row)

        if self._role == ElaChatRoleType.System:
            self._header.hide()
            root.addWidget(self._build_system_body())
        else:
            # **内容列 + 附件条 + 底部行同进 ``_column``**：``setContentMaxWidth``
            # 限的是这一列。原先只限 ``_content``，附件条和底部行是它的兄弟节点
            # 不受限，宽窗口下 footer 比正文列宽，往右伸出去 —— 视觉上「偏左」。
            # 收进同一容器后右边缘自然对齐；不限宽时行为完全不变。
            self._column = QWidget(self)
            column_layout = QVBoxLayout(self._column)
            column_layout.setContentsMargins(0, 0, 0, 0)
            column_layout.setSpacing(2)
            column_layout.addLayout(self._build_body_row())
            self._attachments_host = QWidget(self._column)
            host_layout = QVBoxLayout(self._attachments_host)
            host_layout.setContentsMargins(0, 0, 0, 0)
            host_layout.setSpacing(0)
            self._attachments_host.hide()
            column_layout.addWidget(self._attachments_host)
            self._footer = QWidget(self._column)
            footer_holder = QVBoxLayout(self._footer)
            footer_holder.setContentsMargins(0, 0, 0, 0)
            footer_holder.setSpacing(0)
            footer_holder.addLayout(self._build_footer_row())
            column_layout.addWidget(self._footer)
            root.addWidget(self._column)
        self._header.setAvatarVisible(self._avatar_visible)
        self._header.setAvatarShape(self._avatar_shape)

    def _build_system_body(self) -> QWidget:
        holder = QWidget(self)
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addStretch(1)
        self._label = _SelectableLabel(holder)
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._label.setWordWrap(True)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._label.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(self._label)
        layout.addStretch(1)
        return holder

    def _build_body_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(_ROW_SPACING)

        self._content = QWidget(self)
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(6)

        if self._role == ElaChatRoleType.User:
            self._body = _BubbleBody(self._content)
            body_layout = QVBoxLayout(self._body)
            body_layout.setContentsMargins(*_BUBBLE_PADDING)
            body_layout.setSpacing(0)
            self._label = _SelectableLabel(self._body)
            self._label.setTextFormat(Qt.TextFormat.PlainText)
            self._label.setWordWrap(True)
            self._label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            body_layout.addWidget(self._label)
            self._content_layout.addWidget(self._body, 0, Qt.AlignmentFlag.AlignRight)
            row.addStretch(1)
            row.addWidget(self._content)
        else:
            self._parts_container = QWidget(self._content)
            self._parts_layout = QVBoxLayout(self._parts_container)
            self._parts_layout.setContentsMargins(0, 0, 0, 0)
            self._parts_layout.setSpacing(6)
            self._content_layout.addWidget(self._parts_container)
            row.addWidget(self._content, 1)
        return row

    def _build_footer_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        if self._role == ElaChatRoleType.User:
            row.addStretch(1)
            row.addWidget(self._meta)
            row.addWidget(self._actions)
        else:
            # 助手消息：底部行 = 操作按钮 + 「内容由 AI 生成」提示 +
            # （回合结束时停靠的最后一步用量）+ 耗时
            self._stats_host = QWidget(self)
            self._stats_layout = QHBoxLayout(self._stats_host)
            self._stats_layout.setContentsMargins(0, 0, 0, 0)
            self._stats_layout.setSpacing(4)
            self._disclaimer = ColorText(self._disclaimer_text, self)
            self._disclaimer.setTextPixelSize(_DISCLAIMER_PIXEL_SIZE)
            self._disclaimer.setWordWrap(False)
            self._disclaimer.setVisible(self._disclaimer_visible)
            row.addWidget(self._actions)
            row.addWidget(self._disclaimer)
            row.addStretch(1)
            row.addWidget(self._stats_host)
            row.addWidget(self._meta)
        return row

    def _setup_actions(self) -> None:
        if self._role == ElaChatRoleType.System:
            self._actions.hide()
            return
        self._actions.addCopyAction()
        if self._role == ElaChatRoleType.User:
            self._actions.addUndoAction()
        else:
            self._actions.addRegenerateAction()
        self._actions.copyRequested.connect(self._on_copy)
        self._actions.undoRequested.connect(self.undoRequested)
        self._actions.regenerateRequested.connect(self.regenerateRequested)
        self._actions.actionTriggered.connect(self.actionTriggered)
        # **不挂 QGraphicsOpacityEffect**：即使 opacity=0、控件隐藏，效果器仍会让
        # 每个滚动帧走一次离屏渲染（实测占聊天滚动 ~20%）。显隐交给
        # setVisible + RetainSizeWhenHidden；这个对象只保留透明度读数供
        # setActionsHoverReveal 的既有契约使用。
        self._actions_effect = QGraphicsOpacityEffect(self._actions)
        self._actions_effect.setOpacity(0.0 if self._actions_hover_reveal else 1.0)
        # 隐藏时仍占位（否则悬停出现时消息区整体跳动）。**必须用
        # RetainSizeWhenHidden**：仅靠 ``QGraphicsOpacityEffect(opacity=0)``
        # 保留占位时，动作栏每个滚动帧仍要整块离屏渲染一次（Win7 上很贵）。
        policy = self._actions.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self._actions.setSizePolicy(policy)
        self._set_actions_revealed(not self._actions_hover_reveal)

    def _on_copy(self) -> None:
        QApplication.clipboard().setText(self.text())
        self.copyRequested.emit()
        if self._copy_notification_enabled:
            self.alert(
                "已复制到剪贴板",
                level="success",
                title="",
                duration=1200,
                parent=self.window(),
            )

    def setCopyNotificationEnabled(self, on: bool) -> None:
        """设置点击「复制」后是否弹 ``ElaMessageBar`` 成功提示（默认开）。"""
        self._copy_notification_enabled = bool(on)

    def copyNotificationEnabled(self) -> bool:
        """复制后是否弹成功提示。"""
        return self._copy_notification_enabled

    # -- hover 显现 --------------------------------------------------------

    def setActionsHoverReveal(self, on: bool) -> None:
        """设置操作按钮是否仅在悬停时显示（对齐 opencode）。"""
        self._actions_hover_reveal = bool(on)
        if self._role == ElaChatRoleType.System:
            return
        self._set_actions_revealed(not self._actions_hover_reveal or self.underMouse())

    def actionsHoverReveal(self) -> bool:
        """操作按钮是否仅在悬停时显示。"""
        return self._actions_hover_reveal

    def _set_actions_revealed(self, on: bool) -> None:
        """显示 / 隐藏操作栏（保留占位，消息区不跳动）。"""
        on = bool(on) or not self._actions_hover_reveal
        self._actions_effect.setOpacity(1.0 if on else 0.0)
        self._actions.setMouseTransparent(not on)
        # 隐藏时连绘制也停掉：QGraphicsOpacityEffect(0) 仍会走离屏渲染。
        self._actions.setVisible(on)

    def enterEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().enterEvent(event)
        if self._actions_hover_reveal and self._role != ElaChatRoleType.System:
            self._set_actions_revealed(True)

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().leaveEvent(event)
        if self._actions_hover_reveal and self._role != ElaChatRoleType.System:
            self._set_actions_revealed(False)

    # -- 头部与外观 --------------------------------------------------------

    def actions(self) -> MessageActions:
        """获取底部操作栏（可添加自定义动作按钮）。"""
        return self._actions

    def footer(self) -> Optional[QWidget]:
        """获取底部行容器（操作按钮 + AI 提示 + 用量徽标 + 耗时）。

        流式回合期间整行隐藏（见 :meth:`_sync_footer`），回合结束后出现；宿主
        也可用它整体接管底部行（自定义控件加进去即可）。
        """
        return self._footer

    def setDisclaimer(self, text: str) -> None:
        """设置底部「内容由 AI 生成」提示文案（仅助手消息；空串等同隐藏）。

        与其它外观 setter 一样**立即作用于本条消息**；气泡级改单条，
        批量改走 ``ElaChatView.setDisclaimer()``。
        """
        self._disclaimer_text = str(text or "")
        self._disclaimer_visible = bool(self._disclaimer_text)
        if self._disclaimer is not None:
            self._disclaimer.setText(self._disclaimer_text)
            self._disclaimer.setVisible(self._disclaimer_visible)

    def disclaimer(self) -> str:
        """获取底部「AI 生成」提示文案（未设置返回空串）。"""
        return self._disclaimer_text

    def setDisclaimerVisible(self, on: bool) -> None:
        """显示 / 隐藏底部「AI 生成」提示（文案保留，非助手消息恒不显示）。"""
        self._disclaimer_visible = bool(on)
        if self._disclaimer is not None:
            self._disclaimer.setVisible(self._disclaimer_visible)

    def disclaimerVisible(self) -> bool:
        """底部「AI 生成」提示是否可见。"""
        return self._disclaimer is not None and self._disclaimer.isVisibleTo(self)

    def header(self) -> MessageHeader:
        """获取头部层控件。"""
        return self._header

    def setMessageId(self, messageId: int) -> None:
        """设置所属消息 id（由 ``ElaChatView`` 建气泡时写入）。

        传给工具渲染器上下文（:attr:`ToolRenderContext.messageId`），
        渲染器可据此回调宿主做「跳到这条消息」之类的事。
        """
        self._message_id = int(messageId or 0)

    def messageId(self) -> int:
        """获取所属消息 id（未设置返回 0）。"""
        return self._message_id

    def statsBadge(self) -> Optional[StatsBadge]:
        """获取当前展示的用量徽标（无则返回 ``None``）。

        ``"footer"`` / ``"steps"`` 模式返回最后一个步骤的徽标；``"none"``
        模式恒为 ``None``（耗时回退到底部 meta 文本）。
        """
        if self._stats_mode == "none":
            return None
        for part in reversed(self._parts):
            if part.kind != ElaChatPartKindType.Stats:
                continue
            widget = self._part_widgets.get(part.id)
            if isinstance(widget, StatsBadge):
                return widget
        return None

    def setStatsMode(self, mode: str) -> None:
        """设置用量徽标展示模式（立即生效）。

        - ``"footer"``（默认）：只显示一个徽标（最新步骤位置），内容为
          整轮汇总（各步求和）；回合结束时停靠到底部行；
        - ``"steps"``：每步各自一个徽标（服务端原值，不汇总）——调试用；
        - ``"none"``：不显示徽标，端到端耗时回退到底部 meta 文本。

        非法值回落为 ``"footer"``。每步原始用量始终保留在 ``parts`` 中。
        """
        self._stats_mode = mode if mode in _STATS_MODES else "footer"
        self._apply_stats_mode()
        self._sync_stats_duration()

    def statsMode(self) -> str:
        """获取用量徽标展示模式。"""
        return self._stats_mode

    def _apply_stats_mode(self) -> None:
        """按当前模式显隐 / 刷新各步骤用量徽标（不改变 ``parts`` 原始数据）。

        流式回合内**一律不摆徽标**：用量是逐步累计的，中途的数字既不是最终值，又会
        在「工具调用 → 下一步」的过程中反复跳动（默认 ``"footer"`` 那一行更是还在
        长的整轮汇总）。回合结束（状态离开 ``Streaming``）后按模式展示：``"footer"``
        整轮汇总停靠到底部行，``"steps"`` 每步各自一行，``"none"`` 不显示。

        历史恢复时 ``setStepStats`` 只存数据、不建控件；这里按模式**按需**建
        ``StatsBadge``（footer 每条消息只建最后一个），避免 500 个徽标里 449 个
        最终不可见却仍付创建 / 布局成本（bug #17）。
        """
        stats_parts = [
            part
            for part in self._parts
            if part.kind == ElaChatPartKindType.Stats and part.stats is not None
        ]
        if not stats_parts:
            return
        if self._stats_mode == "none" or self._status == ElaChatStatusType.Streaming:
            for part in stats_parts:
                widget = self._part_widgets.get(part.id)
                if isinstance(widget, StatsBadge) and not is_deleted(widget):
                    widget.hide()
            return
        if self._stats_mode == "footer":
            visible_parts = stats_parts[-1:]
        else:
            visible_parts = stats_parts
        visible_ids = {part.id for part in visible_parts}
        for part in stats_parts:
            if part.id in visible_ids:
                continue
            widget = self._part_widgets.get(part.id)
            if isinstance(widget, StatsBadge) and not is_deleted(widget):
                widget.hide()
        for part in visible_parts:
            badge = self._ensure_stats_badge(part)
            badge.show()
        if self._stats_mode == "footer":
            last_part = stats_parts[-1]
            last_badge = self._ensure_stats_badge(last_part)
            merged = ElaChatStats.merge(part.stats for part in stats_parts)
            last_badge.setStats(merged if merged is not None else last_part.stats)
        else:
            for part in stats_parts:
                self._ensure_stats_badge(part).setStats(part.stats)
        # 判据是**消息状态**，不是 ``_stream_ended``：``setParts()`` 恢复 /
        # ``setStatus(Done)`` 静态收尾都不经过 ``endStream`` —— 拿历史标志当
        # 「回合已结束」会把恢复出来的整轮汇总徽标留在时间线里，与实时渲染不一致。
        if self._status != ElaChatStatusType.Streaming:
            self._dock_step_stats_to_footer()

    def _ensure_stats_badge(self, part: ElaChatPart) -> StatsBadge:
        """按需创建 / 复用某个用量分段的徽标（历史恢复延迟建控件）。"""
        widget = self._part_widgets.get(part.id)
        if isinstance(widget, StatsBadge) and not is_deleted(widget):
            return widget
        badge = StatsBadge(self._parts_container or self._content or self)
        self._part_widgets[part.id] = badge
        if self._parts_layout is not None:
            self._parts_layout.insertWidget(self._part_layout_index(part.id), badge)
        else:
            badge.setParent(self._parts_container or self._content or self)
        return badge

    def attachmentStrip(self) -> AttachmentStrip:
        """获取附件层控件（按需创建，位于正文与底部操作之间）。"""
        if self._attachments is None:
            host = getattr(self, "_attachments_host", None)
            parent = host if host is not None else (self._content or self)
            self._attachments = AttachmentStrip(parent)
            if self._role == ElaChatRoleType.User:
                self._attachments.setAlignment(Qt.AlignmentFlag.AlignRight)
            self._attachments.attachmentClicked.connect(self.attachmentClicked)
            layout = parent.layout()
            if layout is not None:
                if self._role == ElaChatRoleType.User:
                    layout.addWidget(self._attachments, 0, Qt.AlignmentFlag.AlignRight)
                else:
                    layout.addWidget(self._attachments)
            if host is not None:
                host.show()
        return self._attachments

    def setTitle(self, text: str) -> None:
        """设置头部名称 / 模型名。"""
        self._title = text or ""
        self._header.setTitle(self._title)

    def title(self) -> str:
        """获取头部名称 / 模型名。"""
        return self._title

    def setTimestamp(self, text: str) -> None:
        """设置头部时间文本（空则不显示）。"""
        self._timestamp = text or ""
        self._header.setTimestamp(self._timestamp)

    def timestamp(self) -> str:
        """获取头部时间文本。"""
        return self._timestamp

    def stampNow(self) -> None:
        """把时间设置为当前时刻（``HH:MM:SS``）。"""
        self.setTimestamp(datetime.now().strftime("%H:%M:%S"))

    def setDuration(self, durationMs: float) -> None:
        """设置本轮端到端耗时（毫秒）。

        有步骤用量徽标时写入其悬浮提示（与首字延时相邻显示），
        无徽标时回退为底部 meta 可见文本。
        """
        self._duration_ms = float(durationMs or 0.0)
        self._sync_stats_duration()

    def _sync_stats_duration(self) -> None:
        """把端到端耗时同步到最后一个用量徽标的悬浮提示。"""
        badge = self.statsBadge()
        if badge is None:
            self._meta.setDuration(self._duration_ms)
            return
        badge.setMessageDuration(self._duration_ms)
        self._meta.setDuration(0)

    def duration(self) -> float:
        """获取本轮耗时（毫秒）。"""
        return self._duration_ms

    def meta(self) -> MessageMeta:
        """获取底部 meta 控件。"""
        return self._meta

    def setTopSpacing(self, px: int) -> None:
        """设置消息顶部额外留白（turn 间隔节奏）。"""
        margins = self.layout().contentsMargins()
        self.layout().setContentsMargins(
            margins.left(), int(px), margins.right(), margins.bottom()
        )

    def nestedScrollAreas(self) -> list:
        """返回消息内部的嵌套滚动区（供视图安装防脱离过滤器）。"""
        areas = []
        for widget in list(self._part_widgets.values()):
            getter = getattr(widget, "textBrowser", None)
            if callable(getter):
                browser = getter()
                if browser is not None:
                    areas.append(browser)
        return areas

    def markdownViewer(self) -> Optional[ElaMarkdownViewer]:
        """获取当前正文段的 Markdown 查看器（非助手 / 无正文段返回 ``None``）。

        **纯读取**：非流式消息没有正文段时不会凭空建一段（那会污染 ``parts``
        与序列化结果）。流式回合内仍按需建段 —— 查看器是流式光标与占位的落点。
        """
        if self._role != ElaChatRoleType.Assistant:
            return None
        partId = self._current_text_id or self._last_text_part_id()
        if partId is None:
            if self._status != ElaChatStatusType.Streaming:
                return None
            partId = self.beginText()
        widget = self._part_widgets.get(partId)
        return widget if isinstance(widget, ElaMarkdownViewer) else None

    def textViewers(self) -> list:
        """获取全部正文段查看器（按加入顺序）。"""
        return [
            self._part_widgets[part.id]
            for part in self._parts
            if part.kind == ElaChatPartKindType.Text
            and isinstance(self._part_widgets.get(part.id), ElaMarkdownViewer)
        ]

    def setAvatarVisible(self, on: bool) -> None:
        """显示/隐藏头像（气泡可用宽度随之变化，需重新算最大宽度）。"""
        self._avatar_visible = bool(on)
        self._header.setAvatarVisible(self._avatar_visible)
        self._update_max_width()

    def avatarVisible(self) -> bool:
        """头像是否可见。"""
        return self._avatar_visible

    def setAvatarShape(self, shape: str) -> None:
        """设置头像形状（``"circle"`` 默认 / ``"rounded"`` / ``"square"``）。"""
        self._avatar_shape = normalizeAvatarShape(shape)
        self._header.setAvatarShape(self._avatar_shape)

    def avatarShape(self) -> str:
        """获取头像形状。"""
        return self._avatar_shape

    def setAvatarIcon(self, iconName: ElaIconType.IconName) -> None:
        """设置头像图标（``ElaIconType`` 成员）。"""
        self._header.setAvatarIcon(iconName)

    def setAvatarImage(self, source: ElaChatAvatarSource) -> None:
        """设置自定义头像（SVG 数据 / 文件路径 / ``QPixmap`` / ``QImage``）；
        ``None`` 清除并回退到内置图标。
        """
        self._header.setAvatarImage(source)

    def avatarImage(self) -> Optional[QPixmap]:
        """获取自定义头像图（未设置返回 ``None``）。"""
        return self._header.avatarImage()

    def setMaxWidthRatio(self, ratio: float) -> None:
        """设置气泡最大宽度占控件宽度的比例（仅用户消息，0.1-1.0）。"""
        self._max_width_ratio = max(0.1, min(1.0, float(ratio)))
        self._update_max_width()

    def maxWidthRatio(self) -> float:
        """获取气泡最大宽度比例。"""
        return self._max_width_ratio

    def setContentMaxWidth(self, width: int) -> None:
        """设置消息内容最大宽度（像素，``0`` 表示不限；仅助手消息）。

        Typora 式阅读宽度（默认 860px）。限的是**整列**（正文分段 + 附件条 +
        底部操作栏 / 用量行），所以宽窗口下这几层的右边缘是对齐的。
        """
        if self._role != ElaChatRoleType.Assistant:
            return
        self._content_max_width = max(0, int(width))
        self._apply_content_max_width()

    def contentMaxWidth(self) -> int:
        """获取消息内容最大宽度（``0`` 表示不限）。"""
        return self._content_max_width

    def _apply_content_max_width(self) -> None:
        """把阅读宽度应用到内容列（用户 / 系统消息不受影响）。

        限 ``_column`` 而不是 ``_content``：见 :meth:`_build_layout` 的注释 ——
        附件条与底部行必须跟着一起限，否则宽窗口下 footer 会伸出正文列。
        """
        if self._column is None or self._role != ElaChatRoleType.Assistant:
            return
        if self._content_max_width > 0:
            self._column.setMaximumWidth(self._content_max_width)
        else:
            self._column.setMaximumWidth(16777215)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        self._update_max_width()

    def _update_max_width(self) -> None:
        if self._body is None:
            return
        # 头像隐藏时不占宽度，否则气泡会比可用空间窄一截
        avatar_width = (AVATAR_SIZE + _ROW_SPACING) if self._avatar_visible else 0
        available = self.width() - _ROW_MARGIN[0] - _ROW_MARGIN[2] - avatar_width
        if available <= 0:
            return
        max_body = max(80, int(available * self._max_width_ratio))
        self._body.setMaximumWidth(max_body)
        if self._attachments is not None:
            self._attachments.syncWidth(available)
        if self._label is None:
            return
        padding = _BUBBLE_PADDING[0] + _BUBBLE_PADDING[2]
        content_max = max(60, max_body - padding)
        # 短文本贴合内容宽度，长文本在最大宽度内换行（避免过窄的气泡）
        label_width = min(content_max, max(60, self._text_width() + 2))
        self._label.setMaximumWidth(label_width)
        self._body.setFixedWidth(label_width + padding)

    def _text_width(self) -> int:
        """按最长行估算正文文本的单行像素宽度（按文本缓存）。"""
        if self._label is None:
            return 0
        text = self._label.text() or ""
        if self._text_width_cache is not None and self._text_width_cache[0] == text:
            return self._text_width_cache[1]
        fm = self._label.fontMetrics()
        lines = text.splitlines() or [""]
        width = max(fm.horizontalAdvance(line) for line in lines)
        self._text_width_cache = (text, width)
        return width

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        super()._onThemeChanged(mode)
        self._apply_theme()

    def _apply_theme(self) -> None:
        mode = self._theme_mode
        base = base_color(mode)
        text = text_color(mode)
        accent = accent_color(mode)
        self._text_width_cache = None
        for widget in self._part_widgets.values():
            if isinstance(widget, ElaMarkdownViewer) and not is_deleted(widget):
                # 嵌入查看器的显式底色是快照，换主题要跟着刷新
                widget.setViewportBackground(base)
        if self._body is not None:
            self._body.setBackground(blend(base, accent, 0.16))
            # 深色模式加 1px 描边，避免浅色气泡在深底上"糊"成一片
            if base.lightness() < 128:
                self._body.setBorder(blend(base, accent, 0.34))
            else:
                self._body.setBorder(QColor(0, 0, 0, 0))
        if self._label is not None:
            if self._role == ElaChatRoleType.System:
                setTextColor(self._label, muted_color(mode, 0.45))
            else:
                setTextColor(self._label, text)
        if self._disclaimer is not None:
            self._disclaimer.setTextColor(muted_color(mode, 0.55))

    # -- 内容 --------------------------------------------------------------

    def _find_part(self, partId: Optional[str]) -> Optional[ElaChatPart]:
        return self._timeline._find_part(partId)

    def _parts_of_kind(self, kind: str) -> list:
        return self._timeline._parts_of_kind(kind)

    def _append_part(self, part: ElaChatPart, widget: Optional[QWidget]) -> None:
        self._timeline._append_part(part, widget)

    def _move_step_stats_to_end(self, step: int) -> None:
        self._timeline._move_step_stats_to_end(step)

    def _replace_part(self, partId: str, part: ElaChatPart) -> None:
        self._timeline._replace_part(partId, part)

    def _remove_parts(self, kinds) -> None:
        self._timeline._remove_parts(kinds)

    def _drop_part(self, partId: str) -> None:
        self._timeline._drop_part(partId)

    def _step_empty(self) -> bool:
        return self._timeline._step_empty()

    def _last_text_part_id(self) -> Optional[str]:
        return self._timeline._last_text_part_id()

    def text(self) -> str:
        """获取消息文本（助手消息为全部分段正文的拼接）。"""
        return self._timeline.text()

    def parts(self) -> tuple:
        """获取内容分段快照（按加入顺序，构成消息时间线）。"""
        return self._timeline.parts()

    def partText(self, part) -> str:
        """某个分段的当前可见全文 = 落定文本 + 在途缓冲。"""
        return self._timeline.partText(part)

    def setParts(self, parts) -> bool:
        """用一份分段快照重建整条时间线（从存储恢复用）。"""
        return self._timeline.setParts(parts)

    def setPartsDeferred(self, parts) -> bool:
        """只保存分段数据、延迟物化控件（批量加载用）。"""
        return self._timeline.setPartsDeferred(parts)

    def materializeParts(self) -> bool:
        """把延迟保存的分段物化成控件。"""
        return self._timeline.materializeParts()

    def _setPartsWindowed(self, parts, groups) -> bool:
        return self._timeline._setPartsWindowed(parts, groups)

    def expandParts(self) -> bool:
        """展开超长消息被折叠的早期步骤。"""
        return self._timeline.expandParts()

    def partsWindowed(self) -> bool:
        return self._timeline.partsWindowed()

    def partsDeferred(self) -> bool:
        return self._timeline.partsDeferred()

    def _ensure_parts_materialized(self) -> None:
        self._timeline._ensure_parts_materialized()

    def estimatedPartsHeight(self) -> int:
        return self._timeline.estimatedPartsHeight()

    def _restore_one_part(self, part) -> None:
        self._timeline._restore_one_part(part)

    def _restore_compaction(self, part) -> None:
        self._timeline._restore_compaction(part)

    def _restore_permission(self, partId: str, request: ElaChatPermission) -> None:
        self._timeline._restore_permission(partId, request)

    def compactionParts(self) -> list:
        return self._timeline.compactionParts()

    def role(self) -> str:
        """获取消息角色。"""
        return self._role

    def hasPendingText(self) -> bool:
        """是否存在尚未落定的流式分片。"""
        return bool(self._text_buffers)

    def _buffer_chunk(self, partId: str, chunk: str) -> None:
        """把流式分片放入该分段的文本缓冲（落定时才并入 ``part.text``）。"""
        self._text_buffers.setdefault(partId, []).append(chunk)

    def _write_chunk(self, partId: str, chunk: str) -> None:
        """写入一个文本分片：流式时入缓冲，非流式时**直接落定**。

        「在途」只存在于流式回合内。往一条**已结束**的消息追加文本时若也走
        缓冲，就再也没有 ``endText()`` 来结算它，``part.text`` 永远是空的 ——
        界面上看得到（查看器自己持有文本），但对序列化 / 存储完全不可见。
        所以按消息状态分流。
        """
        if self._status == ElaChatStatusType.Streaming:
            self._buffer_chunk(partId, chunk)
            return
        part = self._find_part(partId)
        if part is not None:
            self._replace_part(partId, part.withText((part.text or "") + chunk))

    def _materialize_part(self, partId: str) -> None:
        """把指定分段的缓冲分片并入 ``part.text``（**写**操作）。"""
        chunks = self._text_buffers.pop(partId, None)
        if not chunks:
            return
        part = self._find_part(partId)
        if part is not None:
            self._replace_part(partId, part.withText(part.text + "".join(chunks)))

    def _materialize_all(self) -> None:
        """物化全部分段的文本缓冲（**写**操作）。

        只在**写路径**调用 —— 需要把真实文本灌进新建 / 重建的控件，或在分段
        结束时落定。**读路径一律不许调用**：``parts()`` / ``text()`` /
        ``reasoning()`` 必须保持纯读取，否则 ``part.text`` 的值会取决于
        「有没有被读过」，可序列化的落定语义就废了。
        """
        for partId in list(self._text_buffers):
            self._materialize_part(partId)

    def _discard_part_state(self, partId: str) -> None:
        """清理分段的缓冲与扫描器（分段被替换 / 移除时调用）。"""
        self._text_buffers.pop(partId, None)
        self._heading_scanners.pop(partId, None)
        self._pending_renders.pop(partId, None)

    # -- 延迟渲染（批量加载） ----------------------------------------------

    def setRenderDeferred(self, on: bool) -> None:
        """设置是否延迟 Markdown 渲染（批量加载历史时先建骨架）。

        延迟期间正文 / 内联思考只记录待渲染分段，查看器保持空内容；
        由 :meth:`flushRender` 统一渲染（视图批量队列调用）。
        """
        self._render_deferred = bool(on)

    def renderDeferred(self) -> bool:
        """是否处于延迟渲染状态。"""
        return self._render_deferred

    def hasPendingRender(self) -> bool:
        """是否有等待渲染的查看器。"""
        return bool(self._pending_renders)

    def flushRender(self) -> bool:
        """渲染全部待渲染查看器；返回是否执行了渲染。"""
        if not self._pending_renders:
            return False
        pending = dict(self._pending_renders)
        self._pending_renders.clear()
        # 写路径：新建的查看器要拿到真实文本才能填内容
        self._materialize_all()
        for partId in pending:
            part = self._find_part(partId)
            widget = self._part_widgets.get(partId)
            if part is None or not isinstance(widget, ElaMarkdownViewer):
                continue
            if (
                part.kind == ElaChatPartKindType.Reasoning
                and part.status == ElaChatStatusType.Streaming
            ):
                widget.beginStream()
                widget.appendMarkdown(part.text)
            else:
                widget.setMarkdown(part.text)
        return True

    def _write_viewer_text(self, partId: str, widget: QWidget, text: str) -> None:
        """把文本写入查看器；延迟渲染模式下仅登记待渲染。"""
        if not isinstance(widget, ElaMarkdownViewer):
            return
        if self._render_deferred:
            if text:
                self._pending_renders[partId] = True
            return
        widget.setMarkdown(text or "")

    def _defer_viewer_append(self, partId: str, widget: QWidget) -> bool:
        """追加路径的延迟闸门：延迟期间只登记待渲染。

        ``setParts``（存储恢复）是**重放**增量 API 走完的，正文与思考分片最终都
        落在 :meth:`appendText` / ``appendReasoning`` 的 ``appendMarkdown`` 上 ——
        那两处若不看 ``_render_deferred``，批量加载几百条 parts 消息就照样在主线程
        同步渲染全部 Markdown，渐进渲染形同虚设。

        :returns: ``True`` = 已登记待渲染，调用方不要再写查看器。
        """
        if not self._render_deferred or not isinstance(widget, ElaMarkdownViewer):
            return False
        if self._find_part(partId) is None:
            return False
        self._pending_renders[partId] = True
        return True

    # -- 视口外查看器挂起 --------------------------------------------------

    def setViewersSuspended(self, on: bool) -> None:
        """挂起 / 恢复全部 Markdown 查看器（视口外消息省内存与 reflow）。

        挂起时用等高透明占位控件替换查看器（布局高度不变，``parts`` 数据
        不变）；恢复时按分段内容重新渲染。流式中的分段不会被挂起。
        """
        on = bool(on)
        if on == self._viewers_suspended:
            return
        if on:
            self._suspend_viewers()
        else:
            self._restore_viewers()

    def viewersSuspended(self) -> bool:
        """查看器是否处于挂起状态。"""
        return self._viewers_suspended

    def hasExpandedSections(self) -> bool:
        """是否有用户展开中的折叠块 / 思考块 / 工具面板。

        壳回收会销毁这些控件（展开态不属 ``parts`` 数据），因此调用方应跳过
        这类消息，避免用户滚回来时发现手动展开的内容又收起了。
        """
        for card in self._tool_cards.values():
            if card is not None and not is_deleted(card) and card.isOpened():
                return True
        for panel in self._panels:
            if panel is not None and not is_deleted(panel) and panel.isOpened():
                return True
        for part in self._parts:
            if part.kind != ElaChatPartKindType.Reasoning:
                continue
            widget = self._part_widgets.get(part.id)
            if isinstance(widget, ReasoningBlock) and widget.isOpened():
                return True
        return False

    def _suspend_viewers(self) -> None:
        layout = self._parts_layout
        for part in self._parts:
            if part.status == ElaChatStatusType.Streaming:
                continue
            widget = self._part_widgets.get(part.id)
            if not isinstance(widget, ElaMarkdownViewer):
                continue
            height = max(1, widget.height())
            self._suspended_viewers[part.id] = height
            placeholder = QWidget(self._parts_container or self._content or self)
            placeholder.setFixedHeight(height)
            placeholder.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
            )
            index = layout.indexOf(widget) if layout is not None else -1
            self._part_widgets[part.id] = placeholder
            if layout is not None:
                layout.removeWidget(widget)
                if index >= 0:
                    layout.insertWidget(index, placeholder)
                else:
                    layout.addWidget(placeholder)
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        self._viewers_suspended = bool(self._suspended_viewers)

    def _restore_viewers(self) -> None:
        if not self._suspended_viewers:
            self._viewers_suspended = False
            return
        # 写路径：重建的查看器要拿到真实文本
        self._materialize_all()
        layout = self._parts_layout
        for partId, _height in list(self._suspended_viewers.items()):
            part = self._find_part(partId)
            placeholder = self._part_widgets.get(partId)
            if part is None:
                self._suspended_viewers.pop(partId, None)
                # 占位控件对应的分段已不存在：一并收掉，别留在布局里
                if placeholder is not None and not is_deleted(placeholder):
                    self._part_widgets.pop(partId, None)
                    placeholder.hide()
                    placeholder.setParent(None)
                    placeholder.deleteLater()
                continue
            if part.kind == ElaChatPartKindType.Reasoning:
                widget = self._create_reasoning_widget()
                # 用与「形态切换重建」同一套灌数据逻辑：内联（查看器）与
                # 折叠（ReasoningBlock）两种形态都要恢复文本与耗时
                self._populate_reasoning_widget(widget, part)
            else:
                widget = self._create_text_viewer()
                if part.status == ElaChatStatusType.Streaming:
                    widget.beginStream()
                    widget.appendMarkdown(part.text)
                else:
                    widget.setMarkdown(part.text)
            index = (
                layout.indexOf(placeholder)
                if layout is not None and placeholder is not None
                else -1
            )
            self._part_widgets[partId] = widget
            if layout is not None:
                if placeholder is not None:
                    layout.removeWidget(placeholder)
                if index >= 0:
                    layout.insertWidget(index, widget)
                else:
                    layout.addWidget(widget)
            if placeholder is not None:
                placeholder.hide()
                placeholder.setParent(None)
                placeholder.deleteLater()
            self._suspended_viewers.pop(partId, None)
        self._viewers_suspended = False

    @staticmethod
    def _stepGroups(parts) -> list:
        """按 ``part.step`` 分组（保持原顺序）。"""
        groups = []
        current = []
        last_step = None
        for part in parts or ():
            step = max(1, int(getattr(part, "step", 1) or 1))
            if step != last_step:
                if current:
                    groups.append(current)
                current = []
                last_step = step
            current.append(part)
        if current:
            groups.append(current)
        return groups

    # -- 合成上下文段（steer 插话回执） -------------------------------------

    def addSteerNotice(self, text: str, partId: Optional[str] = None) -> str:
        """追加一条插话回执，返回分段 id。

        **刻意不插一条用户消息** —— 助手消息正在流式输出，中途插一条用户
        气泡视觉上很怪。回执行留在同一条助手消息内，语义是「插话已送达」。
        """
        self._ensure_parts_materialized()
        self._mark_generation_started()
        partId = partId or uuid4().hex[:12]
        widget = SteerNotice(self._parts_container or self._content or self)
        widget.setText(text or "")
        part = ElaChatPart(
            id=partId,
            kind=ElaChatPartKindType.Synthetic,
            text=text or "",
            status=ElaChatStatusType.Done,
            step=self._step_index,
        )
        self._append_part(part, widget)
        return partId

    # -- 压缩段 -------------------------------------------------------------

    def beginCompaction(
        self, reason: str = "auto", partId: Optional[str] = None
    ) -> str:
        """开始一次上下文压缩，返回分段 id。

        **库不实现压缩算法** —— 摘要怎么来、压哪段、什么时候压都由宿主决定
        （依赖 provider 侧的能力）。本方法只在时间线上如实表达「这里发生过
        一次压缩」，并把摘要接上。

        ``reason`` **只进 journal 原始事件**（宿主诊断用），时间线卡片不展示它。
        """
        self._ensure_parts_materialized()
        self._mark_generation_started()
        partId = partId or uuid4().hex[:12]
        widget = CompactionSeparator(self._parts_container or self._content or self)
        widget.setCompactionStatus(ElaChatStatusType.Streaming)
        part = ElaChatPart(
            id=partId,
            kind=ElaChatPartKindType.Compaction,
            status=ElaChatStatusType.Streaming,
            step=self._step_index,
        )
        self._append_part(part, widget)
        return partId

    def appendCompactionSummary(self, partId: str, chunk: str) -> None:
        """追加压缩摘要（流式）。"""
        if not partId or not chunk:
            return
        part = self._find_part(partId)
        if part is None or part.kind != ElaChatPartKindType.Compaction:
            return
        self._replace_part(partId, part.withText(part.text + chunk))
        widget = self._part_widgets.get(partId)
        if isinstance(widget, CompactionSeparator):
            widget.setSummary(part.text + chunk)

    def endCompaction(
        self, partId: str, status: str = ElaChatStatusType.Done, historyCount: int = 0
    ) -> None:
        """结束压缩（``status`` 非 Done 时视为失败，摘要就地落定）。"""
        if not partId:
            return
        part = self._find_part(partId)
        if part is None or part.kind != ElaChatPartKindType.Compaction:
            return
        self._materialize_part(partId)
        self._replace_part(partId, part.withStatus(status))
        widget = self._part_widgets.get(partId)
        if isinstance(widget, CompactionSeparator):
            widget.setSummary(part.text)
            widget.setHistoryCount(historyCount)
            widget.setCompactionStatus(status)

    # -- 工具审批段 ---------------------------------------------------------

    def beginPermission(
        self, request: ElaChatPermission, partId: Optional[str] = None
    ) -> str:
        """登记一次工具审批 / 提问，返回分段 id。

        **交互卡不放在时间线上，而是交给输入区上方的 dock**
        （:attr:`permissionDockRequested` -> :meth:`ElaChatWidget.setDockWidget`）。
        理由：审批是**当前这一步**要用户做的事，摆在历史流里既窄又旧（提问正文
        会被压到折行、候选卡说明被页脚盖住），而且用户正在输入区附近，交互就该
        在那儿。opencode 的 ``session-question-dock`` 就是这个位置。

        时间线上此刻**只登记数据**（``_append_part(part, None)``），等用户答完再
        补一张「记录卡」—— 交互是大控件、记录是小控件，两者的排版需求完全不同，
        所以**不复用同一个 widget**，而是用已落定的 payload 新建一张。

        **只画卡 + 发 ``permissionRequested``，不阻塞。** 在 Qt 里挂起等用户
        点按钮会卡死事件循环；宿主拿到信号后自行决定怎么挂起后端。

        进来的 ``request`` 已经是**落定态**时（宿主重放后端历史、或自己判定完再补
        登记）直接落成时间线上的记录卡：不进 dock、不发 ``permissionRequested``。
        """
        self._ensure_parts_materialized()
        self._mark_generation_started()
        partId = partId or uuid4().hex[:12]
        part = ElaChatPart(
            id=partId,
            kind=ElaChatPartKindType.Permission,
            status=(
                ElaChatStatusType.Streaming
                if request.isPending
                else ElaChatStatusType.Done
            ),
            permission=request,
            step=self._step_index,
        )
        self._append_part(part, None)
        if not request.isPending:
            # 进来的就已经是**落定态**（宿主重放后端历史、或者自己判定完再补登记）
            # —— 直接落成记录卡：不进 dock、不发 ``permissionRequested``。
            # 硬塞进 dock 会得到一张没有按钮的空卡（``_sync_all`` 把动作区和页脚
            # 都藏了），用户看着一个空壳，既不能答也不能关。
            self._settle_permission_card(partId, request)
            return partId
        card = self._create_interactive_card(partId, request)
        self.permissionRequested.emit(str(request.request_id))
        self.permissionDockRequested.emit(card, partId)
        return partId

    def _create_interactive_card(self, partId: str, request: ElaChatPermission):
        """建交互卡并登记（``beginPermission`` 与 ``ensureInteractivePermissionCard`` 共用）。"""
        card = PermissionCard()
        card.replied.connect(
            lambda reply, answer, feedback, pid=partId: self._on_permission_replied(
                pid, reply, answer, feedback
            )
        )
        card.setPermission(request)
        self._interactive_cards[partId] = card
        return card

    def _on_permission_replied(
        self, partId: str, reply: str, answer: str, feedback: str
    ) -> None:
        # 卡片可能活得比气泡久（它被 dock 借用展示），用户点击时气泡可能已经
        # deleteLater 生效 —— 此时碰任何 C++ 成员都会抛 RuntimeError 穿出 Qt
        # 信号槽 = 0xC0000409。删除路径会先 cancelPendingPermissions，这里是兜底。
        if is_deleted(self):
            return
        part = self._find_part(partId)
        if part is None or part.permission is None:
            return
        settled = part.permission.withStatus(reply, answer, feedback)
        self._replace_part(
            partId, part.withPermission(settled).withStatus(ElaChatStatusType.Done)
        )
        self._settle_permission_card(partId, settled)
        self.permissionSettled.emit(partId)
        self.permissionReplied.emit(
            str(settled.request_id), str(reply), str(answer), str(feedback)
        )

    def _settle_permission_card(self, partId: str, settled: ElaChatPermission) -> None:
        """落定：把交互卡收掉，并在时间线的**原位**补一张记录卡。

        必须插回原位而不是 ``addWidget`` 追加 —— 审批之后往往还会来工具调用 /
        正文段，追加会让记录跑到整条消息的最末尾，顺序就错了。
        """
        if is_deleted(self):
            return
        interactive = self._interactive_cards.pop(partId, None)
        if interactive is not None and not is_deleted(interactive):
            interactive.setPermission(settled)  # 让 dock 里那张也显示最终态
            interactive.deleteLater()
        record = self._permission_cards.get(partId)
        if record is not None and not is_deleted(record):
            return  # 已有记录（例如重复落定），不重复建
        record = PermissionRecord(settled)
        self._permission_cards[partId] = record
        self._part_widgets[partId] = record
        if self._parts_layout is not None:
            self._parts_layout.insertWidget(self._part_layout_index(partId), record)
        else:
            record.setParent(self._parts_container or self._content or self)
        record.show()

    def _part_layout_index(self, partId: str) -> int:
        """该 part 在时间线布局里应处的位置。

        取「目标 part 之后第一个真正在 ``_parts_layout`` 里的控件下标」——
        不能按「前面有几个带控件的 part」数：上下文工具分组时 N 个 tool part
        共用同一张分组卡会被重复计数，已停靠底部行的用量徽标也不在时间轴里。
        """
        layout = self._parts_layout
        if layout is None:
            return 0
        found = False
        for part in self._parts:
            if part.id == partId:
                found = True
                continue
            if not found:
                continue
            widget = self._part_widgets.get(part.id)
            if widget is None or is_deleted(widget):
                continue
            index = layout.indexOf(widget)
            if index >= 0:
                return index
        return layout.count()

    def interactivePermissionCard(self, partId: str) -> Optional[PermissionCard]:
        """取仍在 dock 里等待用户操作的交互卡（非 dock 阶段 / 已销毁返回 ``None``）。"""
        card = self._interactive_cards.get(partId)
        if card is None or is_deleted(card):
            return None
        return card

    def ensureInteractivePermissionCard(self, partId: str) -> Optional[PermissionCard]:
        """取交互卡；缺失 / 已被销毁时按 part 的 pending 载荷**重建**。

        dock 撤卡（``clearPermissionDock``）等路径会让卡片先于审批落定被删，
        而 part 仍是 pending —— 重建保证「下一次 promote 顶上来」时还有卡可用，
        且不会把已释放的包装器塞回 dock。
        """
        card = self.interactivePermissionCard(partId)
        if card is not None:
            return card
        part = self._find_part(partId)
        if part is None or part.permission is None or not part.permission.isPending:
            return None
        return self._create_interactive_card(partId, part.permission)

    def resolvePermission(
        self, requestId: str, reply: str, answer: str = "", feedback: str = ""
    ) -> bool:
        """以编程方式落定一次审批（对应卡片按钮）；找不到 / 已落定返回 ``False``。

        已落定的请求**不再改写**（用户的原答案与已发出的信号都不能被二次调用
        覆盖）—— 与 :meth:`cancelPendingPermissions` 的 ``isPending`` 口径一致。
        """
        for part in self._parts:
            if (
                part.kind == ElaChatPartKindType.Permission
                and part.permission is not None
                and part.permission.request_id == requestId
            ):
                if not part.permission.isPending:
                    return False
                self._on_permission_replied(part.id, reply, answer, feedback)
                return True
        return False

    def permissionCard(self, requestId: str) -> Optional[PermissionCard]:
        """按 ``requestId`` 取时间线上的**记录卡**（不存在返回 ``None``）。

        等待用户操作期间的交互卡在 dock 里，不在这里 —— 用
        :meth:`interactivePermissionCard` + partId 取。
        """
        for part in self._parts:
            if (
                part.kind == ElaChatPartKindType.Permission
                and part.permission is not None
                and part.permission.request_id == requestId
            ):
                return self._permission_cards.get(part.id)
        return None

    def pendingPermissions(self) -> list:
        """获取全部**仍在等待用户回复**的审批请求快照。"""
        return [
            part.permission
            for part in self._parts
            if part.kind == ElaChatPartKindType.Permission
            and part.permission is not None
            and part.permission.isPending
        ]

    def pendingPermissionParts(self) -> list:
        """按时间线顺序返回 ``(partId, permission)``（仅仍待答复的）。

        dock 一次只能显示一张卡；这个列表让 :class:`ElaChatWidget` 在当前那张
        落定后**接着把下一张顶上**，而不是把其余的晾在一边点不到。
        """
        return [
            (part.id, part.permission)
            for part in self._parts
            if part.kind == ElaChatPartKindType.Permission
            and part.permission is not None
            and part.permission.isPending
        ]

    def cancelPendingPermissions(self, reason: str = "") -> None:
        """把所有未答复的审批作废（清话题 / 删消息 / 中止回合时必须先调）。

        否则界面上会留下永远点不动、也等不到回复的死卡，用户只能重启。
        这也是 opencode 漏掉的一环：它的 ``Permission.assert`` 在回合中止
        路径上只 ``pending.delete`` 而**不发事件**，客户端要靠重新 sync 才
        清得掉（``permission.ts:254-258``）。
        """
        for part in list(self._parts):
            if (
                part.kind == ElaChatPartKindType.Permission
                and part.permission is not None
                and part.permission.isPending
            ):
                self._on_permission_replied(
                    part.id,
                    ElaChatPermissionStatusType.Cancelled,
                    "",
                    reason or "",
                )

    def _reset_part_state(self) -> None:
        """清空全部分段、控件与步骤面板（:meth:`setParts` 的第一步）。

        工具面板必须一起清：``ToolGroupPanel`` 是真实控件，只清 ``_parts``
        会让旧卡片留在界面上，而新卡片又叠在同一面板里。
        """
        self._current_text_id = None
        self._current_reasoning_id = None
        self._current_stats_id = None
        self._current_tool_panel = None
        self._parts_deferred = False
        self._parts_windowed = False
        self._window_button = None
        self._deferred_placeholder = None
        self._pending_text_lead.clear()
        for partId in [part.id for part in self._parts]:
            self._discard_part_state(partId)
            self._suspended_viewers.pop(partId, None)
        for widget in self._part_widgets.values():
            # 待答复的审批 part 没有控件（``_append_part(part, None)``）会存成
            # ``None``；已挂起 / 已销毁的占位控件也可能在这里。都要跳过 ——
            # 否则 ``None.setParent`` 会在 setParts 里抛 AttributeError。
            if widget is None or is_deleted(widget):
                continue
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        # 占位控件已被销毁，挂起标志必须一起复位；否则 ``viewersSuspended()``
        # 恒为 True，之后同名调用直接早退，这条消息再也挂不起 / 恢复不了。
        self._suspended_viewers.clear()
        self._viewers_suspended = False
        self._parts = []
        self._part_widgets = {}
        self._tool_cards = {}
        self._panel_calls = {}
        self._panel_steps = {}
        self._group_card = None
        self._docked_stats = None
        self._thinking_row = None
        # 审批：记录卡清 `_part_widgets` 就够了（上面的循环会销毁它们），
        # 但**交互卡不在布局里**（在 dock 上），必须单独收掉，否则 dock 会一直
        # 显示一张已经没人再答的卡。
        for card in self._interactive_cards.values():
            if not is_deleted(card):
                card.hide()
                card.setParent(None)
                card.deleteLater()
        self._interactive_cards = {}
        self._permission_cards = {}
        for panel in self._panels:
            panel.hide()
            panel.setParent(None)
            panel.deleteLater()
        self._panels = []
        self._bulk_panels.clear()
        if self._parts_layout is not None:
            while self._parts_layout.count():
                item = self._parts_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.hide()
                    widget.setParent(None)
                    widget.deleteLater()

    def _begin_bulk_build(self) -> None:
        """进入历史分段批量构建：暂缓布局与面板显示（可嵌套）。"""
        self._bulk_build += 1
        if self._bulk_build != 1:
            return
        if self._parts_container is not None:
            self._parts_container.setUpdatesEnabled(False)
        if self._parts_layout is not None:
            self._parts_layout.setEnabled(False)

    def _end_bulk_build(self) -> None:
        """结束批量构建：统一刷面板、恢复布局并激活一次。"""
        if self._bulk_build <= 0:
            return
        self._bulk_build -= 1
        if self._bulk_build > 0:
            return
        for panel in list(self._bulk_panels):
            if not is_deleted(panel):
                self._sync_tool_panel(panel)
                panel.show()
        self._bulk_panels.clear()
        if self._parts_layout is not None:
            self._parts_layout.setEnabled(True)
        if self._parts_container is not None:
            self._parts_container.setUpdatesEnabled(True)
            self._parts_container.update()
        if self._parts_layout is not None:
            self._parts_layout.activate()
        self.updateGeometry()

    def setText(self, text: str) -> None:
        """设置消息文本（助手消息整体替换当前正文段并走 Markdown 渲染）。"""
        if self._role != ElaChatRoleType.Assistant:
            if self._label is not None:
                self._label.setText(text)
                self._update_max_width()
            return
        self._ensure_parts_materialized()
        # 整体替换：还没开段的空白分片属于旧内容，一起丢弃
        self._pending_text_lead.clear()
        if text:
            self._mark_generation_started()
        # 多段正文（多步骤）时 setText 是**整体替换**：先清掉已有正文段，
        # 否则 ``updateMessage(mid, "C")`` 会得到 "A" + "C" 的拼接，而 view 的
        # 文档承诺「整体替换消息文本」。
        if (
            text
            and sum(1 for item in self._parts if item.kind == ElaChatPartKindType.Text)
            > 1
        ):
            self._remove_parts({ElaChatPartKindType.Text})
            self._current_text_id = None
        partId = self._current_text_id or self._last_text_part_id()
        if partId is None:
            if not text:
                return  # 空文本不建空分段（会污染 parts 与导出结果）
            self.beginText()
            partId = self._current_text_id
        self._discard_part_state(partId)
        part = self._find_part(partId)
        if part is not None:
            self._replace_part(partId, part.withText(text or ""))
        widget = self._part_widgets.get(partId)
        self._write_viewer_text(partId, widget, text or "")

    def appendText(self, chunk: str) -> None:
        """追加文本（助手消息追加到当前正文段，用户消息追加到气泡）。

        **纯空白分片不开正文段**：模型常先吐 ``"\\n\\n"`` 再吐正文，直接开段会
        在时间线上留一个空 text part（污染 ``parts`` / 导出），还把「空回答」
        误判成有正文。所以没有打开正文段时先把空白攒进 ``_pending_text_lead``，
        等首个非空白分片一起开段 —— 中段的空白（``"hello" + " " + "world"``）
        不走这条路，照常保留。
        """
        if not chunk:
            return
        if self._role != ElaChatRoleType.Assistant:
            if self._label is not None:
                self._label.setText(self._label.text() + chunk)
                self._update_max_width()
            return
        if self._current_text_id is None:
            if not chunk.strip():
                self._pending_text_lead.append(chunk)
                return
            lead = "".join(self._pending_text_lead)
            self._pending_text_lead.clear()
            self.beginText()
            chunk = lead + chunk
        partId = self._current_text_id
        if self._find_part(partId) is None:
            return
        self._mark_generation_started()
        self._write_chunk(partId, chunk)
        widget = self._part_widgets.get(partId)
        if isinstance(widget, ElaMarkdownViewer) and not self._defer_viewer_append(
            partId, widget
        ):
            widget.appendMarkdown(chunk)

    # -- 正文段 ------------------------------------------------------------

    def _create_text_viewer(self) -> ElaMarkdownViewer:
        viewer = ElaMarkdownViewer(self._parts_container or self._content or self)
        viewer.setEmbeddedMode(True)
        # 文末段落下边距不计入高度：正文与后续分段的视觉间距与其它分段一致
        viewer.setEmbeddedTrimBottom(True)
        viewer.setBorderRadius(0)
        # 不透明底色（与消息区同色）：嵌入查看器默认透明，Win7 上会走慢速
        # 重绘路径（见「下游项目反馈bug.md」§4）
        viewer.setViewportBackground(base_color(self._theme_mode))
        viewer.setStickToBottom(False)
        if self._status == ElaChatStatusType.Streaming:
            viewer.setPlaceholderText(_STREAMING_PLACEHOLDER)
        self.viewerCreated.emit(viewer)
        return viewer

    def _restore_text_part(self, partId: str, text: str) -> None:
        """历史恢复正文段：一次性 ``setMarkdown``，不走流式缓冲（bug #17）。"""
        if self._current_text_id is not None:
            self.endText()
        viewer = self._create_text_viewer()
        viewer.setMarkdown(text or "")
        part = ElaChatPart(
            id=partId,
            kind=ElaChatPartKindType.Text,
            status=ElaChatStatusType.Done,
            text=text or "",
            step=self._step_index,
        )
        self._append_part(part, viewer)
        self._current_text_id = None

    def beginText(self, partId: Optional[str] = None) -> Optional[str]:
        """开始一个新的正文段，返回分段 id（非助手消息返回 ``None``）。

        ``partId`` 可由调用方指定（从存储恢复时保留原分段 id，使
        ``messageId`` / ``partId`` 在重启后保持稳定），缺省自动生成。
        """
        if self._role != ElaChatRoleType.Assistant:
            return None
        self._ensure_parts_materialized()
        if self._current_text_id is not None:
            self.endText()
        partId = partId or uuid4().hex[:12]
        status = (
            ElaChatStatusType.Streaming
            if self._status == ElaChatStatusType.Streaming
            else ElaChatStatusType.Done
        )
        part = ElaChatPart(
            id=partId,
            kind=ElaChatPartKindType.Text,
            status=status,
            step=self._step_index,
        )
        self._append_part(part, self._create_text_viewer())
        self._current_text_id = partId
        return partId

    def endText(self) -> None:
        """结束当前正文段（停止流式光标，并把缓冲落成定稿文本）。"""
        # 没开段的空白分片不算内容，收尾时丢弃
        self._pending_text_lead.clear()
        partId = self._current_text_id
        if partId is None:
            return
        self._current_text_id = None
        widget = self._part_widgets.get(partId)
        if isinstance(widget, ElaMarkdownViewer):
            if widget.isStreaming():
                widget.endStream()
            widget.setPlaceholderText("")
        # 段结束即落定：把缓冲并入 part.text，使 part.text 自足、可序列化，
        # 且与读取时机无关（对齐 opencode「`.ended` 携带全量并覆盖」）。
        # 此前只在 parts() 被读时才物化，导致流结束后仍可能残留未落定缓冲。
        self._materialize_part(partId)
        part = self._find_part(partId)
        if part is not None:
            self._replace_part(partId, part.withStatus(ElaChatStatusType.Done))

    # -- 步骤 --------------------------------------------------------------

    def beginStep(self) -> int:
        """开始新步骤：结束当前正文段与工具分组（空步骤不递增）。"""
        if self._role != ElaChatRoleType.Assistant:
            return self._step_index
        if self._step_empty():
            return self._step_index
        self.endText()
        self._finish_tool_group()
        # 思考段也要收尾：此前只把 _current_reasoning_id 置 None 而不
        # endReasoning()，宿主若不显式调用 endReasoning（binder 会调，
        # 手写宿主未必），ReasoningBlock 会永远停在「思考中」转圈，
        # 对应 part 的 status 也冻在 streaming。
        self.endReasoning()
        if self._thinking_row is not None:
            self._thinking_row.end()
        self._step_index += 1
        self._current_text_id = None
        self._current_reasoning_id = None
        self._current_stats_id = None
        self._current_tool_panel = None
        return self._step_index

    def stepIndex(self) -> int:
        """获取当前步骤序号（从 1 开始）。"""
        return self._step_index

    # -- 思考层 ------------------------------------------------------------

    def setReasoningStyle(self, style: str) -> None:
        """设置思考展示形态：``"collapse"``（可折叠块，默认）/ ``"inline"``。

        对已有思考段**原位重建**（内容 / 耗时 / 流式状态保留，不丢数据），
        与 ``setToolGrouping`` / ``setStatsMode`` 一致：立即生效。
        """
        style = (
            style
            if style in ElaChatReasoningStyleType.All
            else ElaChatReasoningStyleType.Collapse
        )
        if style == self._reasoning_style:
            return
        self._reasoning_style = style
        self._rebuild_reasoning_widgets()

    def _rebuild_reasoning_widgets(self) -> None:
        """按当前形态重建全部思考分段控件（分段数据保持不变）。"""
        # 写路径：重建的控件要拿到真实文本
        self._materialize_all()
        layout = self._parts_layout
        streaming_id = None
        for part in list(self._parts):
            if part.kind != ElaChatPartKindType.Reasoning:
                continue
            if part.id in self._suspended_viewers:
                continue  # 挂起中：保留等高占位，恢复时按新形态重建
            old = self._part_widgets.get(part.id)
            index = (
                layout.indexOf(old) if layout is not None and old is not None else -1
            )
            self._discard_part_state(part.id)
            widget = self._create_reasoning_widget()
            self._populate_reasoning_widget(widget, part)
            self._part_widgets[part.id] = widget
            if layout is not None:
                if old is not None:
                    layout.removeWidget(old)
                if index >= 0:
                    layout.insertWidget(index, widget)
                else:
                    layout.addWidget(widget)
            if old is not None:
                old.hide()
                old.setParent(None)
                old.deleteLater()
            if part.status == ElaChatStatusType.Streaming:
                streaming_id = part.id
        self._current_reasoning_id = streaming_id
        if streaming_id is not None:
            widget = self._part_widgets.get(streaming_id)
            if isinstance(widget, ElaMarkdownViewer):
                self._move_thinking_row(widget)
                self._thinking_row.begin()
                scanner = self._heading_scanners.get(streaming_id)
                if scanner is not None:
                    self._thinking_row.setHeading(scanner.result())
            elif self._thinking_row is not None:
                self._thinking_row.end()
        elif self._thinking_row is not None:
            self._thinking_row.end()

    def _populate_reasoning_widget(self, widget: QWidget, part: ElaChatPart) -> None:
        """把思考分段数据灌入重建后的控件（含流式状态）。"""
        streaming = part.status == ElaChatStatusType.Streaming
        if isinstance(widget, ReasoningBlock):
            widget.setText(part.text)
            if streaming:
                widget.setTitle("思考中")
                widget.setBusy(True)
                widget.setOpened(True)
            else:
                widget.end(part.duration_ms)
        elif isinstance(widget, ElaMarkdownViewer):
            if streaming:
                widget.beginStream()
                widget.appendMarkdown(part.text)
                scanner = _HeadingScanner()
                scanner.push(part.text)
                self._heading_scanners[part.id] = scanner
            else:
                self._write_viewer_text(part.id, widget, part.text)

    def reasoningStyle(self) -> str:
        """获取思考展示形态。"""
        return self._reasoning_style

    def _create_reasoning_widget(self) -> QWidget:
        parent = self._parts_container or self._content or self
        if self._reasoning_style == ElaChatReasoningStyleType.Inline:
            viewer = ElaMarkdownViewer(parent)
            viewer.setEmbeddedMode(True)
            viewer.setEmbeddedTrimBottom(True)
            viewer.setBorderRadius(0)
            # 同 _create_text_viewer：嵌入查看器用不透明底色避开 Win7 慢路径
            viewer.setViewportBackground(base_color(self._theme_mode))
            viewer.setStickToBottom(False)
            viewer.setMarkdown("")
            self.viewerCreated.emit(viewer)
            return viewer
        return ReasoningBlock(parent=parent)

    def _ensure_reasoning_part(self, partId: Optional[str] = None) -> str:
        if self._current_reasoning_id is not None and partId is None:
            return self._current_reasoning_id
        partId = partId or uuid4().hex[:12]
        part = ElaChatPart(
            id=partId,
            kind=ElaChatPartKindType.Reasoning,
            status=ElaChatStatusType.Streaming,
            step=self._step_index,
        )
        widget = self._create_reasoning_widget()
        self._append_part(part, widget)
        self._current_reasoning_id = partId
        if isinstance(widget, ElaMarkdownViewer):
            # 内联形态才需要状态行；折叠块标题/进度环已自足，避免内容重复
            self._move_thinking_row(widget)
        return partId

    def _move_thinking_row(self, before: QWidget) -> None:
        """把思考行移动到指定控件之前（跟随当前流式推理段）。"""
        if self._parts_layout is None:
            return
        row = self.thinkingRow()
        # 先摘自身再取目标下标：``removeWidget`` 会让其后的控件整体前移，
        # 用摘除前的下标插入会落到目标之后（内联形态下思考行被顶到正文下方）
        self._parts_layout.removeWidget(row)
        index = self._parts_layout.indexOf(before)
        if index < 0:
            index = self._parts_layout.count()
        self._parts_layout.insertWidget(index, row)

    def thinkingRow(self) -> ThinkingRow:
        """获取思考行（按需创建，位于当前推理段之前）。"""
        if self._thinking_row is None:
            self._thinking_row = ThinkingRow(
                self._parts_container or self._content or self
            )
        return self._thinking_row

    def reasoningBlock(self) -> ReasoningBlock:
        """获取当前折叠式思考块（``collapse`` 形态）。

        已有思考段返回其控件；**流式回合内**没有段时按需创建。非流式且不存在
        思考段时抛 ``RuntimeError`` —— 「取控件」的读取操作不应凭空追加分段、
        污染 ``parts`` 与序列化结果。
        """
        if self._reasoning_style != ElaChatReasoningStyleType.Collapse:
            raise RuntimeError("inline 形态请使用 inlineReasoningViewer()")
        partId = self._current_reasoning_id
        if partId is None:
            for part in reversed(self._parts):
                widget = self._part_widgets.get(part.id)
                if part.kind == ElaChatPartKindType.Reasoning and isinstance(
                    widget, ReasoningBlock
                ):
                    return widget
            if self._status != ElaChatStatusType.Streaming:
                raise RuntimeError("当前没有思考段（非流式读取不会凭空创建）")
        partId = self._ensure_reasoning_part()
        return self._part_widgets.get(partId)

    def inlineReasoningViewer(self) -> ElaMarkdownViewer:
        """获取当前内联思考查看器（需先 ``setReasoningStyle(Inline)``）。

        与 :meth:`reasoningBlock` 同一契约：**读取不改配置、不凭空建分段**；
        形态不对或非流式且没有思考段时抛 ``RuntimeError``。
        """
        if self._reasoning_style != ElaChatReasoningStyleType.Inline:
            raise RuntimeError("当前不是 inline 形态，请先 setReasoningStyle()")
        partId = self._current_reasoning_id
        if partId is None:
            for part in reversed(self._parts):
                widget = self._part_widgets.get(part.id)
                if part.kind == ElaChatPartKindType.Reasoning and isinstance(
                    widget, ElaMarkdownViewer
                ):
                    return widget
            if self._status != ElaChatStatusType.Streaming:
                raise RuntimeError("当前没有思考段（非流式读取不会凭空创建）")
        partId = self._ensure_reasoning_part()
        return self._part_widgets.get(partId)

    def setReasoning(self, text: str, durationMs: Optional[float] = None) -> None:
        """整体设置当前思考段内容（可选耗时，结束后自动收起）。

        与 :meth:`setText` 同为「整体替换」：先收尾在途思考段（缓冲落定、控件
        收起），再复用**当前步骤**已有的思考段，没有才新建。重复调用不会留下
        永久转圈的孤儿段，也不会把两次内容拼起来。
        """
        if self._role != ElaChatRoleType.Assistant:
            return
        # 先收尾在途段：不落定缓冲就换段，旧段文本只存在于缓冲里 —— 界面上
        # 看得到、导出 ``parts`` 却是空的（数据丢失），且折叠块永远停在「思考中」。
        self.endReasoning()
        partId = self._current_step_reasoning_id()
        if partId is None:
            partId = self._ensure_reasoning_part()
        text = text or ""
        if text:
            self._mark_generation_started()
        self._discard_part_state(partId)
        widget = self._part_widgets.get(partId)
        if isinstance(widget, ReasoningBlock):
            widget.setText(text)
            if durationMs:
                widget.end(durationMs)
            else:
                widget.setOpened(bool(text))
        elif isinstance(widget, ElaMarkdownViewer):
            self._write_viewer_text(partId, widget, text)
            if self._thinking_row is not None:
                self._thinking_row.setHeading(_HeadingScanner().push(text))
        part = self._find_part(partId)
        if part is not None:
            updated = (
                part.withText(text)
                .withStatus(ElaChatStatusType.Done)
                .withDuration(float(durationMs) if durationMs else 0.0)
            )
            self._replace_part(partId, updated)
        # 「整体设置」不是流式开始：之后 appendReasoning 应新起一段，而不是往
        # 这个已落定段里继续追加。
        self._current_reasoning_id = None

    def reasoning(self) -> str:
        """获取全部思考文本（无思考内容返回空串）。

        与 :meth:`text` 同为纯读取：流式期间含在途分片，但不写回 ``part.text``。
        """
        return "".join(
            self.partText(part)
            for part in self._parts
            if part.kind == ElaChatPartKindType.Reasoning
        )

    def _current_step_reasoning_id(self) -> Optional[str]:
        """当前步骤已有的思考分段 id（无则返回 ``None``）。"""
        for part in reversed(self._parts):
            if part.step != self._step_index:
                return None
            if part.kind == ElaChatPartKindType.Reasoning:
                return part.id
        return None

    def beginReasoning(self, partId: Optional[str] = None) -> None:
        """开始思考（折叠块展示「思考中」；内联形态附状态行）。

        同一步骤内重复开始思考时**复用已有思考块**继续追加，避免后到的
        思考内容插到正文之后造成「思考与正文混排」。

        ``partId`` 由 :meth:`setParts` 传入时**强制新建**分段（不再复用同
        步骤已有块），用于从存储恢复时保留原分段 id。
        """
        if self._role != ElaChatRoleType.Assistant:
            return
        self._ensure_parts_materialized()
        if partId is not None:
            new_id = self._ensure_reasoning_part(partId)
            widget = self._part_widgets.get(new_id)
            if isinstance(widget, ReasoningBlock):
                widget.begin()
            elif isinstance(widget, ElaMarkdownViewer):
                self._move_thinking_row(widget)
                self.thinkingRow().begin()
                widget.setMarkdown("")
            return
        self._current_reasoning_id = None
        existing = self._current_step_reasoning_id()
        if existing is not None:
            self._current_reasoning_id = existing
            widget = self._part_widgets.get(existing)
            if isinstance(widget, ReasoningBlock):
                widget.setTitle("思考中")
                widget.setBusy(True)
                widget.setOpened(True)
            elif isinstance(widget, ElaMarkdownViewer):
                self._move_thinking_row(widget)
                self.thinkingRow().begin()
            return
        partId = self._ensure_reasoning_part()
        widget = self._part_widgets.get(partId)
        if isinstance(widget, ReasoningBlock):
            widget.begin()
        elif isinstance(widget, ElaMarkdownViewer):
            self.thinkingRow().begin()
            widget.setMarkdown("")

    def appendReasoning(self, chunk: str) -> None:
        """追加思考文本（流式）。

        文本先入缓冲（读取时物化）；内联形态的标题由增量扫描器维护，
        不再逐分片全量正则扫描。
        """
        if not chunk:
            return
        if self._current_reasoning_id is None:
            self.beginReasoning()
        partId = self._current_reasoning_id
        if self._find_part(partId) is None:
            return
        self._mark_generation_started()
        self._write_chunk(partId, chunk)
        widget = self._part_widgets.get(partId)
        if isinstance(widget, ReasoningBlock):
            widget.appendText(chunk)
        elif isinstance(widget, ElaMarkdownViewer):
            scanner = self._heading_scanners.get(partId)
            if scanner is None:
                scanner = _HeadingScanner()
                self._heading_scanners[partId] = scanner
            self.thinkingRow().setHeading(scanner.push(chunk))
            if not self._defer_viewer_append(partId, widget):
                widget.appendMarkdown(chunk)

    def endReasoning(self, durationMs: Optional[float] = None) -> None:
        """结束当前思考段（折叠块收起并显示耗时；内联形态隐藏状态行）。"""
        partId = self._current_reasoning_id
        if partId is None:
            if self._thinking_row is not None:
                self._thinking_row.end()
            return
        self._current_reasoning_id = None
        widget = self._part_widgets.get(partId)
        if isinstance(widget, ReasoningBlock):
            widget.end(durationMs)
        elif isinstance(widget, ElaMarkdownViewer):
            # 内联形态：必须结束查看器自身的流式状态，否则光标定时器
            # 会一直保留（思考完成后仍不停闪烁）。
            if widget.isStreaming():
                widget.endStream()
            if self._thinking_row is not None:
                self._thinking_row.end()
        # 同 endText：段结束即落定，缓冲并入 part.text
        self._materialize_part(partId)
        part = self._find_part(partId)
        if part is not None:
            updated = part.withStatus(ElaChatStatusType.Done)
            if durationMs:
                # 同一步骤内多次「开始/结束」思考时累计耗时
                updated = updated.withDuration(part.duration_ms + float(durationMs))
            self._replace_part(partId, updated)

    # -- 工具层（每步一个外层面板） ----------------------------------------

    def _ensure_tools(self) -> ToolGroupPanel:
        """确保当前步骤存在工具面板（无则创建），返回该面板。"""
        if self._current_tool_panel is None:
            panel = ToolGroupPanel(self._parts_container or self._content or self)
            panel.toggled.connect(self._on_tool_card_toggled)
            self._panels.append(panel)
            self._panel_steps[id(panel)] = self._step_index
            self._panel_calls[id(panel)] = set()
            if self._parts_layout is not None:
                self._parts_layout.addWidget(panel)
            self._current_tool_panel = panel
        return self._current_tool_panel

    def toolPanel(self) -> Optional[ToolGroupPanel]:
        """获取当前步骤的工具面板（无工具时返回 ``None``）。"""
        if self._current_tool_panel is not None:
            return self._current_tool_panel
        return self._panels[-1] if self._panels else None

    def toolPanels(self) -> list:
        """获取全部步骤的工具面板（按创建顺序）。"""
        return list(self._panels)

    def _panel_for_call(self, callId: str) -> Optional[ToolGroupPanel]:
        for panel in self._panels:
            if callId in self._panel_calls.get(id(panel), ()):
                return panel
        return self._current_tool_panel

    def setToolGrouping(self, on: bool) -> None:
        """设置是否把连续上下文工具（read/glob/grep/list）合并为分组卡。"""
        self._tool_grouping = bool(on)

    def setToolDefaultOpen(self, policy) -> None:
        """注入「哪些工具卡默认展开」的策略。

        ``policy(toolName, arguments, ok) -> bool``，仅在**新建**工具卡时被调用；
        已存在的卡片不受影响（否则会把用户手动折叠的卡片弹开）。

        为什么做成可注入的纯函数而不是硬编码：「shell 要不要默认展开」「纯删除
        要不要折叠」都是**宿主的产品决策**，与工具语义强相关。库默认只保留一条
        与领域无关且普遍正确的规则（失败时展开），其余交给宿主。编码 agent 场景
        可直接用 :func:`~pyqt6_ela_pro.chat.blocks.toolDefaultOpenCoding`。

        :param policy: 可调用对象；传 ``None`` 恢复库默认
        """
        self._tool_open_policy = policy if callable(policy) else toolDefaultOpen

    def _tool_default_open(self, name: str, arguments, ok: bool) -> bool:
        """按当前策略求「默认展开」；宿主策略抛异常时回落库默认。"""
        try:
            return bool(self._tool_open_policy(name, arguments, ok))
        except Exception:
            return bool(toolDefaultOpen(name, arguments, ok))

    def toolGrouping(self) -> bool:
        """是否启用上下文工具分组。"""
        return self._tool_grouping

    def addToolCall(
        self,
        name: str,
        arguments: str = "",
        toolCallId: Optional[str] = None,
        *,
        tool_call: Optional[ElaChatToolCall] = None,
    ) -> str:
        """添加一个工具调用，返回调用 id（上下文工具自动归组）。

        ``tool_call`` 由恢复路径传入**已完成**的快照：卡片构造时就带上结果与
        最终状态，省掉「先建卡再 setResult」的第二次头部同步。
        """
        if self._role != ElaChatRoleType.Assistant:
            return ""
        self._ensure_parts_materialized()
        self._mark_generation_started()
        callId = (
            toolCallId
            or (tool_call.id if tool_call is not None else "")
            or uuid4().hex[:12]
        )
        if toolCallId and toolCallId in self._tool_cards:
            # 同一调用 id 重复上报（参数分片等）：更新参数不追加重复分段
            card = self._tool_cards[toolCallId]
            if isinstance(card, ContextToolGroupCard):
                card.updateArguments(toolCallId, arguments or "")
            else:
                card.setArguments(arguments or "")
            part = self._find_part(toolCallId)
            if part is not None:
                self._replace_part(
                    toolCallId, part.withToolCall(card.toolCall(toolCallId))
                )
            return toolCallId
        call = tool_call or ElaChatToolCall(
            id=callId, name=name, arguments=arguments or ""
        )
        name = call.name
        arguments = call.arguments
        panel = self._ensure_tools()
        container = panel.toolContainer()
        key = (name or "").lower()
        is_context = key in CONTEXT_TOOLS
        failed = call.status == ElaChatToolStatusType.Error
        # 宿主给上下文工具注册了渲染器 -> 默认退出分组：分组卡只画一行汇总
        # 摘要，会把渲染器整个绕过（那宿主注册它就毫无意义）。
        groupable = toolRendererGroupable(name)
        if is_context and not groupable:
            self._finish_tool_group()
        if is_context and self._tool_grouping and groupable:
            if self._group_card is None:
                # 分组卡同样走展开策略：策略问的是「这次探索要不要默认摊开」，
                # 上下文工具合并后单卡就是整个分组的代表，只对单调用问一次、
                # 却不管分组，会让同一策略在两条路径上表现不一致。
                self._group_card = ContextToolGroupCard(
                    container,
                    defaultOpen=self._tool_default_open(name, arguments, not failed),
                )
                self._group_card.toggled.connect(self._on_tool_card_toggled)
                panel.toolLayout().addWidget(self._group_card)
            self._group_card.addToolCall(call)
            card = self._group_card
        else:
            card = ToolCallCard(
                parent=container,
                tool_call=call,
                # shell 类工具的 pending 期间允许展开（命令与输出是多行文本）；
                # 清单与默认展开策略共用 blocks.SHELL_TOOLS，别各写一份。
                allowOpenWhilePending=key in SHELL_TOOLS,
                # 建卡时结果还没到，ok 传 True（不是失败）；失败展开由
                # ToolCallCard.setResult(ok=False) 单独处理。传 False 会被
                # 策略读成「已失败」-> 每张卡都自动展开。
                defaultOpen=self._tool_default_open(
                    call.name, call.arguments, not failed
                ),
            )
            card.setMessageId(self._message_id)
            card.toggled.connect(self._on_tool_card_toggled)
            panel.toolLayout().addWidget(card)
        self._tool_cards[callId] = card
        self._panel_calls[id(panel)].add(callId)
        self._parts.append(
            ElaChatPart(
                id=callId,
                kind=ElaChatPartKindType.Tool,
                status=(
                    ElaChatStatusType.Done
                    if call.status in ElaChatToolStatusType.Settled
                    else ElaChatStatusType.Streaming
                ),
                tool_call=call,
                step=self._step_index,
            )
        )
        self._part_widgets[callId] = card
        self._move_step_stats_to_end(self._step_index)
        if self._bulk_build:
            # 回放期间只登记；收尾统一 show + 刷新摘要，避免每个工具都触发
            # 一次面板 show / 全量 parts 扫描（bug #17）。
            self._bulk_panels.add(panel)
        else:
            panel.show()
            self._sync_tool_panel(panel)
        return callId

    def _on_tool_card_toggled(self, _checked: bool = False) -> None:
        self.toolToggled.emit()

    def _finish_tool_group(self) -> None:
        if self._group_card is not None:
            self._group_card.finish()
            self._group_card = None

    def _toolPanelSummary(self, calls) -> str:
        """折叠面板的一行摘要：单调用显示「工具 · 关键参数」，多调用显示名称计数。"""
        calls = [call for call in calls if call is not None]
        if not calls:
            return ""
        if len(calls) == 1:
            call = calls[0]
            name = call.name or "工具"
            subtitle = ""
            try:
                _key, subtitle = toolRendererSubtitle(name, call.arguments)
                if not subtitle:
                    _key, subtitle = toolSubtitleParts(call.arguments)
            except Exception:
                subtitle = ""
            subtitle = " ".join(str(subtitle or "").split())
            if len(subtitle) > 72:
                subtitle = subtitle[:71] + "…"
            text = f"{name} · {subtitle}" if subtitle else name
            if call.status == ElaChatToolStatusType.Error:
                text += " · 失败"
            return text
        counts = {}
        order = []
        failed = 0
        for call in calls:
            name = call.name or "工具"
            if name not in counts:
                order.append(name)
                counts[name] = 0
            counts[name] += 1
            if call.status == ElaChatToolStatusType.Error:
                failed += 1
        parts = [
            f"{name}×{counts[name]}" if counts[name] > 1 else name for name in order[:4]
        ]
        if len(order) > 4:
            parts.append("…")
        if failed:
            parts.append(f"失败{failed}")
        return " · ".join(parts)

    def _sync_tool_panel(self, panel: Optional[ToolGroupPanel] = None) -> None:
        """按分段状态刷新指定面板（缺省当前面板）的标题与运行指示。"""
        panel = panel or self._current_tool_panel
        if panel is None:
            return
        step = self._panel_steps.get(id(panel), self._step_index)
        calls = [
            part.tool_call
            for part in self._parts
            if part.kind == ElaChatPartKindType.Tool
            and part.step == step
            and part.tool_call is not None
        ]
        total = len(calls)
        done = sum(1 for call in calls if call.status in ElaChatToolStatusType.Settled)
        key = (
            total,
            tuple(call.id for call in calls),
            sum(1 for call in calls if call.status == ElaChatToolStatusType.Error),
        )
        if key == getattr(panel, "_summary_key", None):
            # 结果落定（running -> done）不改摘要，跳过参数 JSON 解析
            panel.setCounts(done, total)
        else:
            panel._summary_key = key
            panel.setCounts(done, total, summary=self._toolPanelSummary(calls))

    def setToolCallResult(self, toolCallId: str, result: str, ok: bool = True) -> None:
        """更新指定工具调用的结果。"""
        if self._parts_deferred or (
            self._parts_windowed and toolCallId not in self._tool_cards
        ):
            part = self._find_part(toolCallId)
            if part is not None and part.tool_call is not None:
                status = (
                    ElaChatToolStatusType.Done if ok else ElaChatToolStatusType.Error
                )
                call = part.tool_call.withResult(result or "", status)
                self._replace_part(toolCallId, part.withToolCall(call))
            return
        card = self._tool_cards.get(toolCallId)
        if card is None:
            return
        card.updateResult(toolCallId, result, ok=ok)
        part = self._find_part(toolCallId)
        if part is not None:
            self._replace_part(toolCallId, part.withToolCall(card.toolCall(toolCallId)))
        self._sync_tool_panel(self._panel_for_call(toolCallId))

    def toolCall(self, toolCallId: str) -> Optional[ElaChatToolCall]:
        """按 id 获取工具调用快照。"""
        card = self._tool_cards.get(toolCallId)
        if card is not None:
            return card.toolCall(toolCallId)
        part = self._find_part(toolCallId)
        return part.tool_call if part is not None else None

    def toolCalls(self) -> list:
        """获取全部工具调用快照（按添加顺序）。"""
        return [
            part.tool_call
            for part in self._parts
            if part.kind == ElaChatPartKindType.Tool and part.tool_call is not None
        ]

    def toolCallCount(self) -> int:
        """工具调用数量。"""
        return sum(1 for part in self._parts if part.kind == ElaChatPartKindType.Tool)

    def clearToolCalls(self) -> None:
        """移除全部工具调用卡片与各步骤外层面板。"""
        self._remove_parts({ElaChatPartKindType.Tool})
        self._tool_cards.clear()
        self._group_card = None
        self._panel_calls.clear()
        for panel in self._panels:
            panel.hide()
            panel.setParent(None)
            panel.deleteLater()
        self._panels = []
        self._panel_steps.clear()
        self._current_tool_panel = None

    # -- 附件层 ------------------------------------------------------------

    def setAttachments(self, attachments) -> None:
        """整体替换附件（用户消息常见）。"""
        self.attachmentStrip().setAttachments(attachments)

    def addAttachment(
        self, name: str, path: str = "", size: int = 0
    ) -> ElaChatAttachment:
        """添加一个附件并返回快照。"""
        return self.attachmentStrip().addAttachment(name, path, size)

    def attachments(self) -> list:
        """获取附件快照列表。"""
        if self._attachments is None:
            return []
        return self._attachments.attachments()

    def clearAttachments(self) -> None:
        """清空附件。"""
        if self._attachments is not None:
            self._attachments.clear()

    # -- 错误与用量 --------------------------------------------------------

    def errorCard(self) -> ErrorCard:
        """获取错误卡片（按需创建）。"""
        if self._error is None:
            self._error = ErrorCard(self._content or self)
            if self._content_layout is not None:
                self._content_layout.addWidget(self._error)
            # 错误卡的两个动作直接复用气泡既有的「重新生成」通道（同一个
            # 语义不值得开第二条路），「重试」是新通道。
            self._error.retryRequested.connect(self.retryRequested.emit)
            self._error.regenerateRequested.connect(self.regenerateRequested.emit)
        return self._error

    def setError(self, message: str, errorType: str = "") -> None:
        """设置错误文本与类型（空文本隐藏卡片）。

        错误通常发生在流式过程中：先收尾未完成的分段（正文查看器 /
        思考光标 / 工具分组），避免留下永久闪烁的光标与未结束的流。

        :param errorType: 错误类型，决定错误卡上点亮哪些动作
            （见 :data:`~pyqt6_ela_pro.chat.blocks.RETRYABLE_ERROR_TYPES`）
        """
        if message:
            self._abortStream(ElaChatStatusType.Error)
        self.errorCard().setMessage(message, errorType)
        if message:
            self.setStatus(ElaChatStatusType.Error)

    def error(self) -> str:
        """获取错误文本。"""
        return self._error.message() if self._error is not None else ""

    def errorType(self) -> str:
        """获取错误类型（未设置返回空串）。"""
        return self._error.errorType() if self._error is not None else ""

    def clearError(self) -> None:
        """清除错误卡片。"""
        if self._error is not None:
            self._error.setMessage("")

    def setStepStats(
        self, stats: Optional[ElaChatStats], partId: Optional[str] = None
    ) -> None:
        """设置当前步骤的用量统计（``None`` 移除当前步骤记录）。

        每步原始用量记录为 ``parts`` 中的 ``Stats`` 分段（数据不汇总）；
        界面展示由 :meth:`setStatsMode` 决定——默认 ``"footer"`` 只显示
        一个整轮汇总徽标（各步求和）。

        ``partId`` 由 :meth:`setParts` 传入时保留原分段 id（存储恢复）。
        """
        if self._role != ElaChatRoleType.Assistant:
            return
        self._ensure_parts_materialized()
        if partId is not None:
            # 恢复路径：明确指定分段 id，不再复用当前步骤的用量段
            self._current_stats_id = partId
        if stats is None:
            if self._current_stats_id is not None:
                partId = self._current_stats_id
                self._current_stats_id = None
                self._drop_part(partId)
                if not self._stats_batch:
                    self._apply_stats_mode()
                    self._sync_stats_duration()
            return
        part = self._find_part(self._current_stats_id)
        if part is None:
            partId = partId or uuid4().hex[:12]
            badge = None
            if not self._stats_batch:
                # 历史回放期只登记数据；最终可见的徽标由 _apply_stats_mode
                # 按需创建（footer 只建最后一个），避免隐藏徽标的创建成本。
                badge = StatsBadge(self._parts_container or self._content or self)
                badge._setStats(stats, deferShow=False)
            self._append_part(
                ElaChatPart(
                    id=partId,
                    kind=ElaChatPartKindType.Stats,
                    status=ElaChatStatusType.Done,
                    stats=stats,
                    step=self._step_index,
                ),
                badge,
            )
            self._current_stats_id = partId
        else:
            self._replace_part(self._current_stats_id, part.withStats(stats))
            widget = self._part_widgets.get(self._current_stats_id)
            if isinstance(widget, StatsBadge):
                widget.setStats(stats)
        if self._stats_batch:
            return
        self._apply_stats_mode()
        self._sync_stats_duration()

    def stats(self) -> Optional[ElaChatStats]:
        """获取整轮用量汇总（各步求和；无记录返回 ``None``）。"""
        return ElaChatStats.merge(
            part.stats
            for part in self._parts
            if part.kind == ElaChatPartKindType.Stats and part.stats is not None
        )

    # -- 流式与状态 --------------------------------------------------------

    def beginStream(self) -> None:
        """开始流式生成（仅助手消息；正文段在首次追加时按需创建）。

        先进入「排队中」（等待模型首个输出，即 TTFT 阶段）；收到首个正文 /
        思考分片或工具调用后自动转「生成中」（见 :meth:`_mark_generation_started`）。
        """
        if self._role != ElaChatRoleType.Assistant:
            return
        self._status = ElaChatStatusType.Streaming
        self._stream_ended = False
        self._generation_started = False
        widget = self._part_widgets.get(self._current_text_id)
        if isinstance(widget, ElaMarkdownViewer):
            widget.setPlaceholderText(_STREAMING_PLACEHOLDER)
        self.setStatus(ElaChatStatusType.Streaming)

    def endStream(self, status: str = ElaChatStatusType.Done) -> None:
        """结束流式生成（仅助手消息）。"""
        if self._role != ElaChatRoleType.Assistant:
            return
        self._abortStream(status)
        self._stream_ended = True
        self._generation_started = True
        self._dock_step_stats_to_footer()
        self.setStatus(status)
        self.streamFinished.emit()

    def _abortStream(self, status: str = ElaChatStatusType.Stopped) -> None:
        """收尾仍在流式的分段（正文 / 思考 / 工具调用 / 工具分组）。

        供 :meth:`endStream` 与错误路径（:meth:`setError`）复用：结束当前
        正文段、关闭内联思考查看器的流式光标、结算所有未完成的工具调用，
        并把上下文工具分组卡从「正在探索」收为「已探索」。

        工具调用必须一并结算：回合结束后它们永远不会再收到结果，不结算就
        会留下永久转圈的忙碌环（对齐 opencode ``failUnsettledTools``）。

        未答复的**审批**同样要作废：回合都结束了，那次请求不可能再有回复，
        留着就是一张永远点不动的死卡（opencode 在这条路径上只删服务端
        记录、不发事件，客户端要靠重新 sync 才清得掉）。
        """
        self.endText()
        self.endReasoning()
        self._settle_open_tools(status)
        self._finish_tool_group()
        self.cancelPendingPermissions()

    def _settle_open_tools(self, status: str) -> None:
        """把仍处于 pending / running 的工具调用落到终态。

        错误回合落 ``Error``（确实没拿到结果），其余（用户停止 / 消息被替换）
        落 ``Aborted`` —— 区分二者是因为「被用户停止」不是失败。

        以 **part 数据**为准遍历而不是 ``_tool_cards``：上下文工具在分组开启时
        映射到 ``ContextToolGroupCard``（无单调用状态），而 part 始终是权威。
        """
        settled = (
            ElaChatToolStatusType.Error
            if status == ElaChatStatusType.Error
            else ElaChatToolStatusType.Aborted
        )
        part_status = (
            ElaChatStatusType.Error
            if status == ElaChatStatusType.Error
            else ElaChatStatusType.Done
        )
        for part in self._parts:
            if part.kind != ElaChatPartKindType.Tool or part.tool_call is None:
                continue
            if part.tool_call.status in ElaChatToolStatusType.Settled:
                continue
            call = part.tool_call.withStatus(settled)
            self._replace_part(part.id, part.withStatus(part_status).withToolCall(call))
            card = self._tool_cards.get(part.id)
            if card is not None and hasattr(card, "setStatus"):
                card.setStatus(settled)
        for panel in self.toolPanels():
            self._sync_tool_panel(panel)
        # 通用清扫：回合结束后不允许残留 streaming 的 part。
        # 已结算的工具 part（Done/Error）与 stats part 自身仍带 Streaming，
        # 逐个 kind 处理很容易漏，这里统一兜底（对齐「无永转圈」不变量）。
        for part in self._parts:
            if part.status == ElaChatStatusType.Streaming:
                self._replace_part(part.id, part.withStatus(part_status))
                if part.kind == ElaChatPartKindType.Compaction:
                    # 压缩卡的状态只由 setCompactionStatus 驱动，不同步就会
                    # 永久停在「压缩中…」而 part 已经落定
                    widget = self._part_widgets.get(part.id)
                    if isinstance(widget, CompactionSeparator):
                        widget.setCompactionStatus(part_status)

    def _dock_step_stats_to_footer(self) -> None:
        """把展示中的用量徽标停靠到底部行（与操作按钮 / 耗时同一水平布局）。

        ``"steps"`` 模式下中间步骤徽标仍留在各自步骤末尾；``"none"``
        模式不显示徽标，直接跳过。停靠是**独占**的：换停靠前先把上一枚放回
        时间线的原下标 —— 重放时每一步徽标都会走到这里一次，不归位就会全堆进
        footer，与实时渲染不一致。
        """
        if self._stats_layout is None or self._stats_mode == "none":
            return
        target = None
        for part in reversed(self._parts):
            if part.kind == ElaChatPartKindType.Stats:
                target = part.id
                break
        if target is None:
            return
        widget = self._part_widgets.get(target)
        if widget is None or is_deleted(widget):
            return
        if widget.parentWidget() is self._stats_host:
            return
        self._undock_step_stats(target)
        index = (
            self._parts_layout.indexOf(widget) if self._parts_layout is not None else -1
        )
        if self._parts_layout is not None:
            self._parts_layout.removeWidget(widget)
        else:
            widget.setParent(self._stats_host)
        self._stats_layout.addWidget(widget)
        self._docked_stats = (target, index)

    def _undock_step_stats(self, nextTarget: Optional[str] = None) -> None:
        """把已停靠的徽标放回时间线（``nextTarget`` 是自己时不摘）。"""
        docked = self._docked_stats
        self._docked_stats = None
        if docked is None:
            return
        partId, index = docked
        if partId == nextTarget:
            return
        widget = self._part_widgets.get(partId)
        if widget is None or is_deleted(widget):
            return
        if widget.parentWidget() is not self._stats_host:
            return
        self._stats_layout.removeWidget(widget)
        if self._parts_layout is None:
            return
        if not any(part.id == partId for part in self._parts):
            return
        if index < 0 or index > self._parts_layout.count():
            self._parts_layout.addWidget(widget)
        else:
            self._parts_layout.insertWidget(index, widget)

    def isStreaming(self) -> bool:
        """是否正在流式生成。"""
        return self._status == ElaChatStatusType.Streaming

    def status(self) -> str:
        """获取消息状态（见 :class:`~pyqt6_ela_pro.chat.message.ElaChatStatusType`）。"""
        return self._status

    def setStatus(self, status: str) -> None:
        """设置消息状态（同步头部状态提示、底部行与用量徽标的显隐）。

        状态是**字符串枚举**（:class:`ElaChatStatusType`），非法值一律回落
        ``Done`` —— 直接写进去会让头部提示取不到文案、底部行按
        ``!= Streaming`` 放行，状态机被静默污染（``"Done"`` 这种大小写笔误
        很难在界面上一眼看出来）。``ElaChatStatusType.All`` 之外的展示态
        （如 ``Queued``）不进 ``_status``，只由头部按 ``Streaming`` 派生。
        """
        self._status = (
            status if status in ElaChatStatusType.All else ElaChatStatusType.Done
        )
        self._sync_header_status()
        self._sync_footer()
        if self._status != ElaChatStatusType.Streaming:
            # 流式期间徽标被收起（见 _apply_stats_mode），回合结束再按模式摆出来
            self._apply_stats_mode()

    def _sync_footer(self) -> None:
        """底部行（复制 / 重新生成 / 用量 / 耗时）只在回合有结果之后出现。

        生成中（含头部展示的「排队中」）整行不摆：回答还没写完，操作按钮与用量都
        是半截数据 —— 重新生成点了会丢掉用户已经看到的内容（``regenerateFrom`` 删该
        条及其后所有消息），复制到的也只是半句话；用量 / 耗时更是要等回合收尾才结算。
        回合结束（``Done`` / ``Stopped`` / ``Error``）后整行一起出现。
        """
        if self._footer is None:
            return
        self._footer.setVisible(
            not self._parts_deferred and self._status != ElaChatStatusType.Streaming
        )

    def _sync_header_status(self) -> None:
        """按状态与「是否已收到首个模型输出」刷新头部提示。

        ``Streaming`` 分两阶段展示：等待首个输出（TTFT）时显示
        ``Queued``（"排队中…"），收到正文 / 思考 / 工具调用后转
        ``Streaming``（"生成中…"）。``Queued`` 只是展示态，气泡与分段的
        ``_status`` 始终是 ``Streaming``（持久化 / journal 语义不变）。
        """
        if self._status == ElaChatStatusType.Streaming and not self._generation_started:
            self._header.setStatusText(
                _STATUS_TEXTS[ElaChatStatusType.Queued], ElaChatStatusType.Queued
            )
            return
        self._header.setStatusText(_STATUS_TEXTS.get(self._status, ""), self._status)

    def _mark_generation_started(self) -> None:
        """收到首个模型输出：``排队中`` → ``生成中``（幂等，仅流式回合内生效）。"""
        if self._generation_started:
            return
        self._generation_started = True
        if self._status == ElaChatStatusType.Streaming:
            self._sync_header_status()
