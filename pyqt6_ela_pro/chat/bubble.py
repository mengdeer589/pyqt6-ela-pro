"""
聊天消息气泡组件：用户 / 助手 / 系统三种角色。

助手消息按「步骤 + 内容分段」组织，与 ``ElaChatPart`` 时间线一一对应；宿主
改消息一律经 ``ElaChatView``，气泡上的内部协议只给 view / 分组卡调用。
"""

from __future__ import annotations

import html

from datetime import datetime
from typing import Optional

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

from .._colors import accent_text
from .._styles import ColorText, setTextColor
from ..ela_markdown_viewer import ElaMarkdownViewer
from ..ela_shimmer import ElaShimmer, ElaShimmerTemplateType
from ..widget_base import ElaThemeWidget
from ._theme import accent_color, base_color, blend, muted_color, text_color
from .bubble_misc import _BubbleMiscMixin
from .bubble_permission import _BubblePermissionMixin
from .bubble_stats import _BubbleStatsMixin
from .bubble_stream import _BubbleStreamMixin
from .bubble_reasoning import _BubbleReasoningMixin
from .bubble_detail import _BubbleDetailMixin
from .bubble_text import _BubbleTextMixin
from .bubble_tools import _BubbleToolsMixin

from .blocks import (
    AVATAR_DEFAULT_SHAPE,
    AVATAR_SIZE,
    AttachmentStrip,
    ElaChatAvatarSource,
    ElaChatRetryCard,
    ErrorCard,
    MessageActions,
    MessageHeader,
    MessageMeta,
    ThinkingRow,
    ToolGroupPanel,
    normalizeAvatarShape,
    toolDefaultOpen,
)
from .message import (
    ElaChatAttachment,
    ElaChatPart,
    ElaChatPartKindType,
    ElaChatPermission,
    ElaChatReasoningStyleType,
    ElaChatRoleType,
    ElaChatStatusType,
)
from .timeline import ChatPartTimeline

#: 气泡圆角半径（逐角：左上 / 右上 / 右下 / 左下；右下小角做“尾巴”）
_BUBBLE_RADII = (12.0, 12.0, 4.0, 12.0)
#: 气泡内边距（左、上、右、下）
_BUBBLE_PADDING = (12, 8, 12, 8)
#: 行外边距（左右、上下）
_ROW_MARGIN = (12, 2, 12, 2)
#: 头像与内容间距
_ROW_SPACING = 10
#: 助手消息底部「AI 生成」提示的默认文案
DISCLAIMER_TEXT = "内容由 AI 生成，仅供参考"
#: 底部「AI 生成」提示字号
_DISCLAIMER_PIXEL_SIZE = 12
#: 右键菜单行高（与 markdown viewer / 终端一致）
_CONTEXT_MENU_ITEM_HEIGHT = 28


class _SelectableLabel(QLabel):
    """可选中纯文本标签：右键菜单走库内 ``ElaMenu``（不用 Qt 原生菜单）。"""

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

    def backgroundColor(self) -> QColor:
        """获取气泡底色（文本高亮等取对比色用）。"""
        return QColor(self._bg)

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


class ElaChatBubble(
    _BubbleTextMixin,
    _BubbleReasoningMixin,
    _BubbleToolsMixin,
    _BubbleStreamMixin,
    _BubbleStatsMixin,
    _BubblePermissionMixin,
    _BubbleMiscMixin,
    _BubbleDetailMixin,
    ElaThemeWidget,
):
    """单条聊天消息气泡（用户 / 助手 / 系统；助手正文为 Markdown 源）。"""

    #: 助手消息流式结束（``endStream``）时发射
    streamFinished = pyqtSignal()
    #: 用户点击「复制」
    copyRequested = pyqtSignal()
    #: 用户点击「撤回」
    undoRequested = pyqtSignal()
    #: 用户点击「重新生成」
    regenerateRequested = pyqtSignal()
    #: 用户取消自动重试
    retryCancelled = pyqtSignal()
    #: 用户在错误卡上点击「重试」（同参数重发；view 转发成带 messageId 的 ``retryRequested``）
    retryRequested = pyqtSignal()
    #: 插入了待答复的工具审批（参数：``requestId``）；库不阻塞，宿主自行挂起后端
    permissionRequested = pyqtSignal(str)
    #: 审批已落定（参数：``requestId``、reply、answer、feedback）
    permissionReplied = pyqtSignal(str, str, str, str)
    #: 交互卡已就绪，请放进输入区上方的 dock（参数：卡片、partId）
    permissionDockRequested = pyqtSignal(object, str)
    #: 该 part 的审批已落定（参数：partId）—— dock 据此把当前卡撤下、接下一张
    permissionSettled = pyqtSignal(str)
    #: 用户点击附件 chip（参数：路径）
    attachmentClicked = pyqtSignal(str)
    #: 自定义动作被点击（参数：key）
    actionTriggered = pyqtSignal(str)
    #: 工具卡 / 分组卡展开收起（宿主可借此暂停贴底跟随）
    toolToggled = pyqtSignal()
    #: 新建了可滚动的正文 / 内联思考查看器（view 据此安装嵌套滚动过滤器）
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
        self._agent = ""
        self._model = ""
        self._model_variant = ""
        self._mentions: tuple = ()
        self._user_text = ""
        self._pending_delivery = ""
        self._pending_actions_added = False
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
        #: 尚未开段的纯空白分片（首个非空白分片到来时一起开段）
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
        #: TTFT 等待骨架（惰性创建的 ``ElaShimmer``；不属于任何 part）
        self._waiting_shimmer: Optional[ElaShimmer] = None
        self._waiting_placeholder_enabled = True
        self._timeline = ChatPartTimeline(self)
        #: 时间线密度 / 逐分段披露（由 view 或宿主设置）
        self._timeline_detail = None
        self._disclosure: dict = {}
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
        #: ``setParts`` 重放期间为 True：逐段 setStepStats 不重复摆徽标，收尾统一 apply 一次
        self._stats_batch = False
        #: 历史分段批量构建深度：回放期间暂缓布局 / 面板显示
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
        #: 已停靠底部行的步骤徽标 ``(partId, 原布局下标)``；停靠是独占的，
        #: 换停靠前要把旧徽标放回时间线
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
        self._retry_card = None
        self._attachments: Optional[AttachmentStrip] = None
        # -- 合成 / 压缩 / 审批分段 -----------------------------------------
        #: 审批分段 id -> 审批卡控件
        self._permission_cards: dict = {}
        #: 仍在 dock 里等待用户操作的交互卡（partId -> 卡片）；落定后清空
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
            # 内容列 + 附件条 + 底部行同进 _column：setContentMaxWidth 限的是这一列，
            # 只限 _content 时附件条与 footer 不受限，宽窗口下会往右伸出正文列
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

    def _ensure_waiting_shimmer(self) -> Optional[ElaShimmer]:
        """惰性创建等待首 token 的骨架（仅助手消息；不属于任何分段）。"""
        shimmer = self._waiting_shimmer
        if shimmer is not None:
            if is_deleted(shimmer):
                self._waiting_shimmer = None
            else:
                return shimmer
        if self._role != ElaChatRoleType.Assistant or self._content is None:
            return None
        if self._content_layout is None:
            return None
        shimmer = ElaShimmer(self._content)
        shimmer.setObjectName("ElaChatWaitingShimmer")
        shimmer.setAccessibleName("正在等待回答")
        shimmer.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        shimmer.setTemplate(ElaShimmerTemplateType.TextBlock)
        shimmer.setFixedHeight(72)
        shimmer.setMaximumWidth(520)
        shimmer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        index = self._content_layout.indexOf(self._parts_container)
        if index < 0:
            index = 0
        self._content_layout.insertWidget(index, shimmer)
        shimmer.hide()
        self._waiting_shimmer = shimmer
        return shimmer

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
        # 不挂 QGraphicsOpacityEffect：即使 opacity=0 且控件隐藏，效果器仍会让
        # 每个滚动帧走一次离屏渲染；显隐交给 setVisible + RetainSizeWhenHidden
        self._actions_effect = QGraphicsOpacityEffect(self._actions)
        self._actions_effect.setOpacity(0.0 if self._actions_hover_reveal else 1.0)
        # 隐藏时仍占位（否则悬停出现时消息区整体跳动）；必须用 RetainSizeWhenHidden
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

        流式回合期间整行隐藏，回合结束后出现；宿主也可往里加自定义控件。
        """
        return self._footer

    def setDisclaimer(self, text: str) -> None:
        """设置底部「内容由 AI 生成」提示文案（仅助手消息；空串等同隐藏）。

        立即作用于本条消息；批量改走 ``ElaChatView.setDisclaimer()``。
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
        """设置所属消息 id（由 ``ElaChatView`` 建气泡时写入；工具渲染器上下文要用）。"""
        self._message_id = int(messageId or 0)

    def messageId(self) -> int:
        """获取所属消息 id（未设置返回 0）。"""
        return self._message_id

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

    def setIdentity(
        self, agent: str = "", model: str = "", modelVariant: str = ""
    ) -> None:
        """设置历史消息的 agent / 模型 / 变体（空则不显示）。

        用户消息显示在头部副行，助手消息显示在底部 meta 行。
        """
        self._agent = str(agent or "")
        self._model = str(model or "")
        self._model_variant = str(modelVariant or "")
        self._sync_identity()

    def identity(self) -> tuple:
        """获取 ``(agent, model, modelVariant)`` 快照。"""
        return (self._agent, self._model, self._model_variant)

    def _identity_text(self) -> str:
        model = self._model
        if model and self._model_variant:
            model = f"{model} ({self._model_variant})"
        return "  ·  ".join(item for item in (self._agent, model) if item)

    def _sync_identity(self) -> None:
        text = self._identity_text()
        if self._role == ElaChatRoleType.User:
            self._header.setContext(text)
        else:
            self._meta.setContext(text)

    def setMentions(self, mentions) -> None:
        """设置用户文本里的 @ 引用区间并立即重绘高亮。"""
        self._mentions = tuple(mentions or ())
        if self._role == ElaChatRoleType.User:
            self._render_user_text()
            # RichText 标签是 HTML（含 span），气泡宽度必须按原文重算，否则会撑宽
            self._update_max_width()

    def mentions(self) -> tuple:
        """获取 @ 引用区间快照。"""
        return self._mentions

    def _render_user_text(self) -> None:
        """用户文本：有 mention 时用 RichText 分段着色，否则保持 PlainText。"""
        if self._label is None or self._role != ElaChatRoleType.User:
            return
        text = self._user_text
        spans = [
            item
            for item in self._mentions
            if getattr(item, "isValid", bool(item.end > item.start))
        ]
        if not spans:
            self._label.setTextFormat(Qt.TextFormat.PlainText)
            self._label.setText(text)
            return
        spans = sorted(spans, key=lambda item: item.start)
        color = accent_text(
            "primary",
            self._theme_mode,
            self._body.backgroundColor() if self._body is not None else None,
        ).name()
        pieces = []
        cursor = 0
        for item in spans:
            start = max(cursor, min(int(item.start), len(text)))
            end = max(start, min(int(item.end), len(text)))
            if start > cursor:
                pieces.append(html.escape(text[cursor:start]).replace("\n", "<br/>"))
            if end > start:
                pieces.append(
                    f'<span style="color:{color}; font-weight:600;">'
                    f"{html.escape(text[start:end]).replace(chr(10), '<br/>')}</span>"
                )
            cursor = end
        if cursor < len(text):
            pieces.append(html.escape(text[cursor:]).replace("\n", "<br/>"))
        self._label.setTextFormat(Qt.TextFormat.RichText)
        self._label.setText("".join(pieces))

    def setPendingDelivery(self, delivery: str = "") -> None:
        """标记用户消息为「待发送」（``steer`` 插话 / ``queue`` 排队）。

        空串 = 已送达 / 普通消息；清掉待发送动作并恢复正常头部状态。
        """
        self._pending_delivery = str(delivery or "")
        if self._pending_delivery:
            if not self._pending_actions_added:
                self._actions.addCustomAction(
                    "pending_queue",
                    icon=ElaIconType.IconName.ArrowDownToLine,
                    tooltip="移到队列",
                )
                self._actions.addCustomAction(
                    "pending_delete",
                    icon=ElaIconType.IconName.Xmark,
                    tooltip="删除这条待发送消息",
                )
                self._pending_actions_added = True
        elif self._pending_actions_added:
            for key in ("pending_queue", "pending_delete"):
                self._actions.removeItem(key)
            self._pending_actions_added = False
        self._sync_header_status()
        self._sync_footer()

    def pendingDelivery(self) -> str:
        """获取待发送投递方式（空 = 普通 / 已送达）。"""
        return self._pending_delivery

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

    def duration(self) -> float:
        """获取本轮耗时（毫秒）。"""
        return self._duration_ms

    def setRetry(self, attempt: int, message: str, nextAt: float = 0.0) -> None:
        """显示自动重试卡（仅助手消息；``nextAt`` 为 epoch 毫秒）。"""
        if self._role != ElaChatRoleType.Assistant:
            return
        card = self._retry_card
        if card is None:
            card = ElaChatRetryCard(self._content)
            card.retryRequested.connect(self.retryRequested)
            card.cancelRequested.connect(self._on_retry_cancelled)
            self._retry_card = card
            if self._content_layout is not None:
                self._content_layout.insertWidget(0, card)
        card.setRetry(attempt, message, nextAt)

    def clearRetry(self) -> None:
        """清除并隐藏自动重试卡。"""
        card = self._retry_card
        if card is not None:
            card.clear()

    def retryState(self) -> tuple:
        """获取 ``(attempt, message, nextAt)``；无重试返回 ``(0, '', 0.0)``。"""
        card = self._retry_card
        return card.retryState() if card is not None else (0, "", 0.0)

    def _on_retry_cancelled(self) -> None:
        self.clearRetry()
        self.retryCancelled.emit()

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

        纯读取：非流式消息没有正文段时不会凭空建一段（那会污染 ``parts``）；
        流式回合内仍按需建段，查看器是流式光标与占位的落点。
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

        限的是整列（正文 + 附件条 + 底部行），所以宽窗口下右边缘对齐。
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

        限 ``_column`` 而不是 ``_content``：附件条与底部行必须一起限。
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
        # 用户消息带 mention 时标签里是 HTML 源码；宽度按 ``_user_text`` 原文量。
        text = self._user_text or ""
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
        if self._role == ElaChatRoleType.User and self._label is not None:
            self._render_user_text()

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

    # -- 延迟渲染（批量加载） ----------------------------------------------

    # -- 视口外查看器挂起 --------------------------------------------------

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

    # -- 压缩段 -------------------------------------------------------------

    # -- 工具审批段 ---------------------------------------------------------

    def _reset_part_state(self) -> None:
        """清空全部分段、控件与步骤面板（:meth:`setParts` 的第一步）。

        工具面板必须一起清：只清 ``_parts`` 会让旧卡片留在界面上。
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
            # 待答复的审批 part 存的是 None；已挂起 / 已销毁的占位也要跳过，
            # 否则 None.setParent 会在 setParts 里抛 AttributeError
            if widget is None or is_deleted(widget):
                continue
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        # 占位控件已销毁，挂起标志必须一起复位；否则 viewersSuspended() 恒为 True，
        # 之后这条消息再也挂不起 / 恢复不了
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
        # 记录卡清 _part_widgets 就够了（上面的循环会销毁它们），但交互卡不在
        # 布局里（在 dock 上），必须单独收掉，否则 dock 会一直显示一张死卡
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

    # -- 正文段 ------------------------------------------------------------

    # -- 步骤 --------------------------------------------------------------

    # -- 思考层 ------------------------------------------------------------

    # -- 工具层（每步一个外层面板） ----------------------------------------

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
            # 错误卡的「重新生成」复用气泡既有通道（同一语义不开第二条路），
            # 「重试」是新通道
            self._error.retryRequested.connect(self.retryRequested.emit)
            self._error.regenerateRequested.connect(self.regenerateRequested.emit)
        return self._error

    def setError(self, message: str, errorType: str = "") -> None:
        """设置错误文本与类型（空文本隐藏卡片）。

        错误通常发生在流式中：先收尾未完成的分段，避免留下永久闪烁的光标。

        :param errorType: 错误类型，决定错误卡上点亮哪些动作
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

    # -- 流式与状态 --------------------------------------------------------
