"""
聊天输入区组件：补全浮层 + 输入卡片（附件条 / 编辑框 / 工具栏）。

``Enter`` 发送、``Shift+Enter`` 换行；大段粘贴自动转附件；IME 组合期间回车
不会误发送。附件快照见 :meth:`ElaChatInput.attachments`。
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import warnings
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import (
    QBuffer,
    QByteArray,
    QIODevice,
    QRectF,
    QSize,
    QTimer,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from PyQt6ElaWidgetTools import (
    ElaIconType,
    ElaPlainTextEdit,
    ElaThemeType,
)

from .._internal import system_cjk_font_family
from .._styles import editBorderlessStyle
from .._theme import ElaStatusRoleType, statusColor
from ..ela_button import ElaButton
from ..tooltips import ElaToolTipPositionType, set_tooltip
from ..widget_base import ElaThemeWidget
from ._mime import localFiles, mimeImage
from ._pricing import formatCost
from ._theme import (
    accent_color,
    base_color,
    blend,
    card_border_color,
    card_color,
    muted_color,
    text_color,
)
from .blocks import AttachmentStrip
from .message import ElaChatMention, _as_float, _as_int
from .selector import ElaChatSelector
from .suggestions import ElaChatSuggestion, SuggestionPopup
from .toolbar import ElaChatToolBar, ElaChatToolButton

#: 输入区外边距（左、上、右、下）
_OUTER_MARGIN = (12, 6, 12, 12)
#: 行间距
_ROW_SPACING = 6
#: 默认最小行数（空输入时的可见高度）
_DEFAULT_MIN_LINES = 3
#: 默认最大行数
_DEFAULT_MAX_LINES = 8
#: 大段粘贴阈值（字符 / 行数）
_LARGE_PASTE_CHARS = 8000
_LARGE_PASTE_LINES = 120
#: ``@`` 引用匹配
_MENTION_RE = re.compile(r"(?:^|\s)@([^\s@]*)$")
#: ``/`` 命令匹配（行首或空白后；命令名不允许再出现 ``/``）
_COMMAND_RE = re.compile(r"(?:^|\s)/([^\s/]*)$")
#: mention 尾部断言：token 之后不能再跟词字符（含 CJK 与 ``@``，避免 "@Al@Al" 误判）
_MENTION_TAIL = (
    r"(?![0-9A-Za-z_@"
    r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    r"\U00020000-\U0002ee5f\U0002f800-\U0002fa1f])"
)
#: 发送 / 停止图标按钮边长
_SEND_BUTTON_SIZE = 32
#: 上下文占用圆环边长（像素）
_USAGE_RING_SIZE = 22
#: 上下文占用进入警示 / 危险配色的百分比阈值
_USAGE_WARN_PERCENT = 60
_USAGE_DANGER_PERCENT = 85
#: 输入卡片圆角半径
_INPUT_CARD_RADIUS = 10
#: 输入卡片内边距（左、上、右、下）
_INPUT_CARD_PADDING = (12, 10, 12, 6)
#: 输入卡片层间距（附件条 / 编辑框 / 工具栏之间）
_INPUT_CARD_SPACING = 4


class _ChatPlainTextEdit(ElaPlainTextEdit):
    """输入编辑器：内容自增高 + 粘贴 / 拖入转附件。

    自增高走 ``sizeHint()``；``textChanged`` 槽里只 ``updateGeometry()``，绝不
    在槽内改几何（重入布局 = 0xC0000409 静默终止）。文件 / 图片经
    :meth:`insertFromMimeData` 转附件（粘贴与拖入同一钩子），大段文本发
    :attr:`largeTextPasted` 交给 :class:`ElaChatInput` 落盘。
    """

    #: 剪贴板图片被粘贴 / 图片被拖入（参数：``QImage``）
    imagePasted = pyqtSignal(QImage)
    #: 本地文件被粘贴 / 拖入（参数：本地文件路径列表）
    filesAdded = pyqtSignal(list)
    #: 大段文本被粘贴 / 拖入（参数：文本）；编辑器不写盘，由 :class:`ElaChatInput` 落临时文件
    largeTextPasted = pyqtSignal(str)
    #: 输入法组合文本变化（参数：preedit 串）
    preeditChanged = pyqtSignal(str)
    #: 焦点变化（参数：是否聚焦）
    focusChanged = pyqtSignal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._min_lines = 1
        self._max_lines = 8
        self._key_handler = None
        # 高度跟着 sizeHint 走（Fixed）；宽度仍由卡片布局拉伸
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def setKeyHandler(self, handler) -> None:  # noqa: N802
        """注入按键处理器（``handler(event) -> bool``，``True`` = 已消费）。

        刻意不用事件过滤器：给会被随行销毁的子控件 ``installEventFilter(parent)``
        在父窗口树整体析构时会踩 0xC0000409。
        """
        self._key_handler = handler

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if self._key_handler is not None and self._key_handler(event):
            event.accept()
            return
        super().keyPressEvent(event)

    def inputMethodEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self.preeditChanged.emit(event.preeditString())
        super().inputMethodEvent(event)

    def focusInEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().focusInEvent(event)
        self.focusChanged.emit(True)

    def focusOutEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().focusOutEvent(event)
        self.focusChanged.emit(False)

    def setLineBudget(self, minLines: int, maxLines: int) -> None:  # noqa: N802
        """设置可见行数预算（超过 ``maxLines`` 后内部滚动）。"""
        self._min_lines = max(1, _as_int(minLines, 1))
        self._max_lines = max(self._min_lines, _as_int(maxLines, self._min_lines))
        self.updateGeometry()

    def _content_height(self) -> int:
        """按当前宽度与内容算像素高度（夹在行数预算内）。"""
        document = self.document()
        width = self.viewport().width()
        if width > 0:
            document.setTextWidth(width)
        line = QFontMetrics(self.font()).lineSpacing()
        min_height = line * self._min_lines
        max_height = line * self._max_lines
        height = 0.0
        block = document.begin()
        while block.isValid():
            height += self.blockBoundingRect(block).height()
            if height >= max_height:
                # 已超上限：sizeHint 会被布局反复询问，不必再数后面的块
                break
            block = block.next()
        return int(min(max(height, min_height), max_height))

    def sizeHint(self) -> QSize:  # noqa: N802
        hint = super().sizeHint()
        return QSize(hint.width(), self._content_height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        hint = super().minimumSizeHint()
        return QSize(hint.width(), self._content_height())

    def canInsertFromMimeData(self, source) -> bool:  # noqa: N802 (Qt 命名)
        return True

    def insertFromMimeData(self, source) -> None:  # noqa: N802 (Qt 命名)
        files = localFiles(source)
        if files:
            self.filesAdded.emit(files)
            return
        image = mimeImage(source)
        if image is not None:
            self.imagePasted.emit(image)
            return
        text = source.text() if source.hasText() else ""
        if text and (
            len(text) >= _LARGE_PASTE_CHARS or text.count("\n") >= _LARGE_PASTE_LINES
        ):
            # 大段粘贴**不塞进编辑框**：转附件（宿主按文件路径读内容）。
            # 编辑器自己不写盘（分层），落盘在 ElaChatInput 里做。
            self.largeTextPasted.emit(text)
            return
        super().insertFromMimeData(source)


class _InputSurface(ElaThemeWidget):
    """输入卡片：包裹附件条 / 编辑框 / 工具栏，自绘圆角边框与聚焦态。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._focused = False
        self._bg = QColor()
        self._border = QColor()
        self._apply_theme()

    def setFocused(self, on: bool) -> None:
        """设置聚焦态（聚焦时边框换强调色）。"""
        on = bool(on)
        if on == self._focused:
            return
        self._focused = on
        self._apply_theme()

    def focused(self) -> bool:
        """是否处于聚焦态。"""
        return self._focused

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        super()._onThemeChanged(mode)
        self._apply_theme()

    def _apply_theme(self) -> None:
        mode = self._theme_mode
        self._bg = card_color(mode)
        self._border = accent_color(mode) if self._focused else card_border_color(mode)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt 命名)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, _INPUT_CARD_RADIUS, _INPUT_CARD_RADIUS)
        painter.fillPath(path, self._bg)
        pen = QPen(self._border)
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.end()


def _shortTokens(value) -> str:
    """词元数缩写（``187431`` -> ``187.4k``，对齐 opencode 的 compact 记法）。"""
    try:
        number = float(value or 0)
    except (TypeError, ValueError, OverflowError):
        return "0"
    if number < 0:
        number = 0.0
    if number < 1000:
        return str(int(number))
    if number < 1_000_000:
        return f"{number / 1000:.1f}k"
    return f"{number / 1_000_000:.1f}M"


class _ContextUsageRing(ElaThemeWidget):
    """上下文窗口占用指示器（工具栏小圆环 + hover 详情）。

    自绘而非 ``ElaProgressRing``：后者的环色硬编码在 C++ 侧，而「占用越高越
    变色」正是本控件的全部价值。三档配色：< 60% 弱化、60~85% 警示、> 85% 危险。
    默认常驻（无数据画空底环），可点击，带 hover / press 状态层。
    """

    #: 点击圆环（宿主据此弹上下文详情面板等；组件自身不做行为）
    clicked = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._used = 0
        self._window = 0
        self._cost_usd = 0.0
        self._hover = False
        self._pressed = False
        self.setFixedSize(_USAGE_RING_SIZE, _USAGE_RING_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName("上下文占用")
        # 刻意不在这里 hide()：它是工具栏默认组件，无数据时画空底环

    # -- 数据 --------------------------------------------------------------

    def setUsage(self, used: int, window: int, costUsd: float = 0.0) -> None:
        """设置占用（``window <= 0`` 按 0% 显示；控件默认常驻、不再因此隐藏）。"""
        try:
            self._used = max(0, int(used or 0))
            self._window = max(0, int(window or 0))
            self._cost_usd = float(costUsd or 0.0)
        except (TypeError, ValueError, OverflowError):
            self._used = self._window = 0
            self._cost_usd = 0.0
        self._sync()

    def usage(self) -> tuple:
        """获取 ``(已用, 窗口, 花费美元)``。"""
        return (self._used, self._window, self._cost_usd)

    def percent(self) -> int:
        """占用百分比（窗口未知返回 0）。"""
        if self._window <= 0:
            return 0
        return max(0, min(100, round(self._used * 100 / self._window)))

    def level(self) -> int:
        """档位：``0`` 正常 / ``1`` 警示 / ``2`` 危险。"""
        percent = self.percent()
        if percent >= _USAGE_DANGER_PERCENT:
            return 2
        if percent >= _USAGE_WARN_PERCENT:
            return 1
        return 0

    def tooltipText(self) -> str:
        """hover 详情文案（花费 / 百分比 / 词元总数 / 危险提示）。"""
        lines = []
        if self._cost_usd > 0:
            lines.append(f"花费 {formatCost(self._cost_usd)}")
        if self._window > 0:
            lines.append(
                f"上下文 {self.percent()}%"
                f"（{_shortTokens(self._used)} / {_shortTokens(self._window)}）"
            )
        elif self._used > 0:
            lines.append(f"上下文 {_shortTokens(self._used)} 词元")
        else:
            lines.append("上下文占用：暂无数据")
        if self.level() == 2:
            lines.append("上下文接近上限，建议压缩历史")
        return "\n".join(lines)

    # -- 交互（当按钮用） --------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.button() == Qt.MouseButton.LeftButton and self._pressed:
            self._pressed = False
            self.update()
            # 只在圆环内松开才算点击（拖出取消，与普通按钮一致）
            if self.rect().contains(event.position().toPoint()):
                self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self._hover = False
        self._pressed = False
        self.update()
        super().leaveEvent(event)

    # -- 内部 --------------------------------------------------------------

    def _sync(self) -> None:
        # 显隐只由 setContextUsageVisible 控制；输入区贴窗口底部 → tooltip 朝上弹
        set_tooltip(self, self.tooltipText(), ElaToolTipPositionType.Top)
        self.update()

    def _arc_color(self):
        mode = self._theme_mode
        base = accent_color(mode)
        level = self.level()
        if level == 2:
            return statusColor(mode, ElaStatusRoleType.Error)
        if level == 1:
            return blend(base, statusColor(mode, ElaStatusRoleType.Warning), 0.75)
        # 低占用刻意弱化：它是「状态」不是「主角」，不该抢注意力
        return blend(muted_color(mode, 0.5), base, 0.35)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        inset = 2.5
        track = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        width = 2.0
        mode = self._theme_mode
        # 按钮式状态层：hover 8% / press 12%（与 ElaButton 同一套比例）
        if self._hover or self._pressed:
            ratio = 0.12 if self._pressed else 0.08
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(blend(base_color(mode), text_color(mode), ratio))
            painter.drawEllipse(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        # 底环：与值环同粗细的浅色圆环，让「还剩多少」可读
        painter.setPen(QPen(blend(base_color(mode), text_color(mode), 0.16), width))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(track)
        # 值环：从 12 点顺时针（对齐 opencode ProgressCircle 的 stroke-dashoffset）
        percent = self.percent()
        if percent > 0:
            painter.setPen(QPen(self._arc_color(), width))
            painter.drawArc(
                track,
                90 * 16,
                -int(round(percent * 360 / 100)) * 16,
            )
        painter.end()

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        super()._onThemeChanged(mode)
        self.update()


class ElaChatInput(ElaThemeWidget):
    """聊天输入区（补全 + 附件 + 编辑框 + 可扩展工具栏）。"""

    #: 用户提交（参数：去除首尾空白后的文本）
    submitted = pyqtSignal(str)
    #: 用户提交（参数：文本、附件快照列表 ``ElaChatAttachment``）
    submittedFull = pyqtSignal(str, list)
    #: 生成中点击「停止」
    stopRequested = pyqtSignal()
    #: 输入内容变化（参数：当前文本）
    textChanged = pyqtSignal(str)
    #: 附件列表变化（参数：``ElaChatAttachment`` 列表）
    attachmentsChanged = pyqtSignal(list)
    #: 本地文件进入输入区（拖放 / 粘贴「复制的文件」/ 大段文本转附件；已加入附件）
    filesAdded = pyqtSignal(list)
    #: 点击「添加文件」按钮
    addFileRequested = pyqtSignal()
    #: 剪贴板图片被粘贴（参数：``QImage``；已自动加入附件）
    imagePasted = pyqtSignal(QImage)
    #: ``@`` 引用被选中（参数：引用 id、展示文本）
    mentionSelected = pyqtSignal(str, str)
    #: ``/`` 命令被选中（参数：命令名）
    commandSelected = pyqtSignal(str)
    #: 提交了一个 ``/`` 命令（``setCommandSubmitMode("signal")`` 时）
    commandSubmitted = pyqtSignal(str)
    #: 下拉选择器变化（参数：选择器 key、item id）
    selectorChanged = pyqtSignal(str, str)
    #: shell 模式提交（参数：命令行文本）
    shellSubmitted = pyqtSignal(str)
    #: 草稿变化（防抖；参数：``draftState()`` 快照）
    draftChanged = pyqtSignal(dict)
    #: 备选投递（``Ctrl+Enter``：生成中走插话，否则普通发送）
    alternateSubmitted = pyqtSignal(str, list)
    #: 点击「清空上下文」（**尚未执行清空**，宿主或组件弹确认后自行处理）
    clearRequested = pyqtSignal()
    #: 点击「新建话题」（组件不做任何处理，宿主据此开新会话 / 话题）
    newTopicRequested = pyqtSignal()
    #: 点击工具栏的上下文占用圆环（组件不做任何行为，宿主据此弹详情面板等）
    contextUsageClicked = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._generating = False
        self._queue_enabled = True
        self._send_on_enter = True
        self._preedit = ""
        self._min_lines = _DEFAULT_MIN_LINES
        self._max_lines = _DEFAULT_MAX_LINES
        self._send_text = "发送"
        self._stop_text = "停止"
        self._file_picker: Optional[Callable[[], list]] = None
        self._mention_provider: Optional[Callable[[str], list]] = None
        self._command_provider: Optional[Callable[[str], list]] = None
        self._command_submit_mode = "send"
        self._popup_kind = ""
        self._mentions: list = []
        self._selectors: dict = {}
        self._shell_mode = False
        self._add_file_visible_before_shell = True
        self._history = None
        self._history_applying = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*_OUTER_MARGIN)
        layout.setSpacing(_ROW_SPACING)

        # 层 0：补全浮层（悬浮在输入卡片上方）
        self._popup = SuggestionPopup(self)
        self._popup.suggestionActivated.connect(self._on_suggestion_activated)
        layout.addWidget(self._popup)

        # 层 1：输入卡片（附件条 / 编辑框 / 工具栏都在卡片内，对齐 opencode）
        self._surface = _InputSurface(self)
        surface_layout = QVBoxLayout(self._surface)
        surface_layout.setContentsMargins(*_INPUT_CARD_PADDING)
        surface_layout.setSpacing(_INPUT_CARD_SPACING)
        layout.addWidget(self._surface)

        # 卡片内 ①：附件条
        self._attachments = AttachmentStrip(self._surface)
        self._attachments.setVisible(False)
        self._attachments.changed.connect(self._on_attachments_changed)
        surface_layout.addWidget(self._attachments)

        # 卡片内 ②：编辑框（无边框，边框 / 底色 / 聚焦态由卡片统一接管）
        self._edit = _ChatPlainTextEdit(self._surface)
        # 编辑框无边框：边框 / 底色 / 聚焦态由 _InputSurface 统一接管
        self._edit.setStyle(editBorderlessStyle())
        self._edit.setFrameShape(QFrame.Shape.NoFrame)
        self._default_placeholder = "输入消息，Enter 发送，Shift+Enter 换行"
        self._edit.setPlaceholderText(self._default_placeholder)
        self._edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._edit.setTabChangesFocus(True)
        # 编辑框自己处理拖放：文本走 Qt 原生，文件 / 图片经 insertFromMimeData 转附件
        self._edit.setAcceptDrops(True)
        # 按键走编辑框自己的 keyPressEvent → 注入的处理器（不装事件过滤器，
        # 见 _ChatPlainTextEdit.setKeyHandler）；组合 / 焦点走信号。
        self._edit.setKeyHandler(self._handle_edit_key)
        self._edit.preeditChanged.connect(self._on_preedit_changed)
        self._edit.focusChanged.connect(self._on_edit_focus_changed)
        self._edit.textChanged.connect(self._on_text_changed)
        self._edit.imagePasted.connect(self._on_image_pasted)
        self._edit.filesAdded.connect(self._on_files_added)
        self._edit.largeTextPasted.connect(self._on_large_text_pasted)
        self._normal_font = QFont(self._edit.font())
        self._shell_font = QFont(self._normal_font)
        cjk = system_cjk_font_family()
        self._shell_font.setFamilies(
            [cjk] if cjk else ["Consolas", "Cascadia Mono", "Courier New"]
        )
        self._shell_font.setStyleHint(QFont.StyleHint.Monospace)
        self._draft_timer = QTimer(self)
        self._draft_timer.setSingleShot(True)
        self._draft_timer.setInterval(300)
        self._draft_timer.timeout.connect(
            lambda: self.draftChanged.emit(self.draftState())
        )
        surface_layout.addWidget(self._edit)

        # 卡片内 ③：工具栏（左：新建话题 / 添加文件 / 清空上下文 + 自定义；右：发送 / 停止）
        self._toolbar = ElaChatToolBar(self._surface)
        # 新建话题：组件只发信号，会话 / 话题由宿主创建（对齐「清空上下文」的分工）
        self._new_topic_button = self._toolbar.addButton(
            icon=ElaIconType.IconName.CommentPlus,
            tooltip="新建话题",
            key="new_topic",
            callback=self._on_new_topic_clicked,
        )
        self._add_file_button = self._toolbar.addButton(
            icon=ElaIconType.IconName.Paperclip,
            tooltip="添加文件 (Ctrl+U)",
            key="add_file",
            callback=self._on_add_file_clicked,
        )
        # 清空上下文：输入区常驻的会话级动作（唯一入口，确认弹框见 requestClear）
        self._clear_button = self._toolbar.addButton(
            icon=ElaIconType.IconName.Broom,
            tooltip="清空上下文",
            key="clear",
            callback=self._on_clear_clicked,
        )
        # 上下文占用圆环：与「清空上下文」同排的默认组件；数据由宿主经
        # ``chatInput().setContextUsage(used, window, costUsd)`` 提供
        self._usage_ring = _ContextUsageRing(self._surface)
        self._toolbar.addWidget(self._usage_ring, zone="leading", key="usage")
        self._usage_ring.clicked.connect(self.contextUsageClicked)
        self._usage_used = 0
        self._usage_window = 0
        self._usage_cost = 0.0
        self._toolbar.addSeparator(zone="trailing")
        self._button = ElaButton(
            icon=ElaIconType.IconName.ArrowUp,
            iconSize=16,
            variant="solid",
            color="primary",
            parent=self,
        )
        self._button.setFixedSize(_SEND_BUTTON_SIZE, _SEND_BUTTON_SIZE)
        self._button.setBorderRadius(6)
        self._button.clicked.connect(self._on_button_clicked)
        #: 已写入按钮的图标枚举 —— ``QIcon`` 无值相等语义，每次比较都会重建图标
        self._button_icon = ElaIconType.IconName.ArrowUp
        # 工具栏控件不抢焦点：点按钮时编辑框保持聚焦（卡片维持强调色边框）
        for control in (
            self._add_file_button,
            self._clear_button,
            self._new_topic_button,
            self._button,
        ):
            control.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._toolbar.addWidget(self._button, zone="trailing")
        surface_layout.addWidget(self._toolbar)

        self.setAcceptDrops(True)
        self._sync_height()
        self._sync_button()

    # -- 补全 --------------------------------------------------------------

    def popup(self) -> SuggestionPopup:
        """获取补全浮层控件。"""
        return self._popup

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

    def setShellMode(self, on: bool) -> None:
        """进入 / 退出 shell 模式（等宽字体、Esc 退出、提交走 ``shellSubmitted``）。"""
        on = bool(on)
        if on == self._shell_mode:
            return
        self._shell_mode = on
        if on:
            self._add_file_visible_before_shell = self.addFileVisible()
            self._add_file_button.setVisible(False)
            for selector in self._selectors.values():
                selector.setVisible(False)
            self._attachments.setVisible(False)
            self._edit.setFont(self._shell_font)
            self._edit.setPlaceholderText("输入命令…")
            self._close_popup()
        else:
            self._edit.setFont(self._normal_font)
            self._edit.setPlaceholderText(self._default_placeholder)
            self._add_file_button.setVisible(self._add_file_visible_before_shell)
            for selector in self._selectors.values():
                selector.setVisible(True)
            self._attachments.setVisible(bool(self.attachments()))
        self._sync_height()
        self._edit.setFocus()

    def shellMode(self) -> bool:
        """是否处于 shell 模式。"""
        return self._shell_mode

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
                self._set_edit_text(text + token)
            self.commandSelected.emit(item.id or item.label)
            self._popup_kind = ""
            return
        token = item.insert_text or f"@{item.label} "
        match = _MENTION_RE.search(text)
        if match:
            start = match.start(1) - 1
            self._set_edit_text(text[:start] + token + text[match.end(1) :])
        else:
            self._set_edit_text(text + token)
        self._mentions.append((item.id, token, getattr(item, "kind", "")))
        self.mentionSelected.emit(item.id, item.label)
        self._popup_kind = ""

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

    def mentionSpans(self) -> list:
        """当前文本里仍有效的 ``@`` 引用区间（``ElaChatMention`` 列表）。

        偏移按 Python ``str`` 下标计；同一 token 多次出现只取第一处。
        """
        text = self._edit.toPlainText()
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
            result.append(ElaChatMention(start=start, end=start + len(bare), kind=kind))
        return result

    def clearMentions(self) -> None:
        """清空引用记录。"""
        self._mentions.clear()

    # -- 历史 / 草稿 -------------------------------------------------------

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

    # -- 下拉选择器 --------------------------------------------------------

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
        selector.selectionChanged.connect(
            lambda itemId, k=selector_key: self.selectorChanged.emit(k, itemId)
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

    # -- 工具栏 ------------------------------------------------------------

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

    # -- 上下文占用 --------------------------------------------------------

    def setContextUsage(
        self, used: int = 0, window: int = 0, costUsd: float = 0.0
    ) -> None:
        """设置上下文窗口占用（底部工具栏圆环；``window <= 0`` 按 0% 显示）。

        数据完全由宿主提供，库不推断；也不进 ``ElaChatStats``（那个是各步求和，
        占用是当前值）。没有数据时画空底环。

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

    def setFilePicker(self, picker: Optional[Callable[[], list]]) -> None:
        """自定义文件选择器（返回本地路径列表；``None`` 恢复默认对话框）。"""
        self._file_picker = picker

    def _on_add_file_clicked(self) -> None:
        picker = self._file_picker or self._default_file_picker
        paths = picker() or []
        if paths:
            self.addAttachments(paths)
        self.addFileRequested.emit()

    def _default_file_picker(self) -> list:
        files, _ = QFileDialog.getOpenFileNames(self, "选择文件")
        return [path for path in files if path]

    def _on_clear_clicked(self) -> None:
        # 只发请求：清空涉及「中止生成 → 清队列 → 清消息」，归 widget 层
        self.clearRequested.emit()

    def _on_new_topic_clicked(self) -> None:
        # 组件只管发信号：话题 / 会话由宿主创建（会话列表 UI 属宿主职责）
        self.newTopicRequested.emit()

    # -- 附件 --------------------------------------------------------------

    def attachmentStrip(self) -> AttachmentStrip:
        """获取附件条控件。"""
        return self._attachments

    def attachments(self) -> list:
        """待发附件快照列表（``ElaChatAttachment``）。"""
        return self._attachments.attachments()

    def attachmentPaths(self) -> list:
        """待发附件的本地路径列表（按添加顺序，便于直接读文件）。

        仅含带路径的文件附件；剪贴板图片等无路径项被排除（其内容仍在
        :meth:`attachments` 快照中，可通过 ``isImage`` / ``name`` 识别）。
        """
        return [item.path for item in self._attachments.attachments() if item.path]

    def attachmentCount(self) -> int:
        """待发附件数量。"""
        return self._attachments.count()

    def addAttachments(self, paths) -> list:
        """按本地路径批量添加附件，返回新增的快照列表。"""
        items = []
        for path in paths or []:
            if not isinstance(path, str) or not path:
                continue
            name = os.path.basename(path) or path
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            items.append({"name": name, "path": path, "size": size})
        return self._attachments.addAttachments(items)

    def addAttachment(self, name: str, path: str = "", size: int = 0):
        """添加一个附件（可直接给展示名 / 路径 / 大小）。"""
        return self._attachments.addAttachment(name, path, size)

    def setAttachments(self, attachments) -> None:
        """整体替换附件列表（接受 ``ElaChatAttachment`` 或字典）。"""
        self._attachments.setAttachments(attachments)

    def removeAttachment(self, index: int) -> None:
        """按下标移除附件。"""
        self._attachments.removeAttachment(index)

    def clearAttachments(self) -> None:
        """清空附件。"""
        self._attachments.clear()

    def _on_attachments_changed(self, attachments: list) -> None:
        self._draft_timer.start()
        self.attachmentsChanged.emit(attachments)

    def _on_image_pasted(self, image: QImage) -> bool:
        digest = self._image_digest(image)
        name = f"粘贴的图片-{datetime.now().strftime('%H%M%S')}.png"
        if self._attachments.addPastedImage(image, name, digest) is None:
            return False
        self.imagePasted.emit(image)
        return True

    def _on_files_added(self, paths: list) -> None:
        self._add_files(paths)

    def _on_large_text_pasted(self, text: str) -> None:
        """大段粘贴转附件：写临时文件并进附件条（失败回退为直接插入）。

        与 ``_add_files`` 同一条管线 → ``filesAdded`` 照常发出；同内容同 digest
        恒同路径，附件条按路径自然去重。
        """
        path = self._write_paste_file(text)
        if path is None:
            # 写盘失败（权限 / 磁盘满）：**不能静默丢内容** —— 回退成
            # 旧行为（文本直接进编辑框）并告警一次
            self._edit.insertPlainText(text)
            warnings.warn(
                "大段粘贴转附件失败（临时文件不可写），已回退为直接插入文本",
                RuntimeWarning,
                stacklevel=2,
            )
            return
        self._add_files([path])

    @staticmethod
    def _write_paste_file(text: str) -> Optional[str]:
        """把粘贴文本写成临时文件，返回路径；失败返回 ``None``。

        文件名带内容摘要（同内容同路径 → 天然幂等）；文件生命周期与会话无关。
        """
        try:
            digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
            directory = Path(tempfile.gettempdir()) / "pyqt6_ela_pro_paste"
            directory.mkdir(exist_ok=True)
            path = directory / f"粘贴文本-{digest}.txt"
            path.write_text(text, encoding="utf-8")
            return str(path)
        except OSError:
            return None

    def _add_files(self, paths: list) -> bool:
        """本地文件进附件条 + 发 ``filesAdded``（拖放与粘贴共用一条路径）。

        信号只带实际新增的路径：重复项被去重后不再发出。
        """
        added = self.addAttachments(paths)
        if not added:
            return False
        self.filesAdded.emit([item.path for item in added if item.path])
        return True

    @staticmethod
    def _image_digest(image: QImage) -> str:
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        buffer.close()
        return hashlib.sha1(bytes(data)).hexdigest()

    # -- 文本 --------------------------------------------------------------

    def text(self) -> str:
        """获取输入文本。"""
        return self._edit.toPlainText()

    def setText(self, text: str) -> None:
        """设置输入文本（光标移到末尾）。"""
        self._set_edit_text(text or "")

    def clear(self) -> None:
        """清空输入。"""
        self._edit.clear()

    def setPlaceholderText(self, text: str) -> None:
        """设置占位文案。"""
        self._default_placeholder = text or ""
        self._edit.setPlaceholderText(self._default_placeholder)

    def placeholderText(self) -> str:
        """获取占位文案。"""
        return self._edit.placeholderText()

    def textEdit(self) -> ElaPlainTextEdit:
        """获取内部 ``ElaPlainTextEdit``（高级用法）。"""
        return self._edit

    def inputSurface(self) -> QWidget:
        """获取输入卡片容器（附件条 / 编辑框 / 工具栏都在它内部）。"""
        return self._surface

    # -- 发送 / 停止 -------------------------------------------------------

    def setQueueEnabled(self, on: bool) -> None:
        """设置生成中是否允许提交（交由宿主排队）。"""
        self._queue_enabled = bool(on)
        self._sync_button()

    def queueEnabled(self) -> bool:
        """生成中是否允许提交。"""
        return self._queue_enabled

    def submit(self) -> bool:
        """提交当前输入（空文本忽略）；返回是否已提交。

        同时发出 ``submitted`` 与 ``submittedFull``，并清空输入与附件。
        """
        text = self._edit.toPlainText().strip()
        if not text:
            return False
        if self._generating and not self._queue_enabled:
            return False
        attachments = self.attachments()
        if self._history is not None:
            self._history.add(
                text,
                attachments,
                self.mentionSpans(),
                self._historyMode(),
            )
        if self._shell_mode:
            self.shellSubmitted.emit(text)
            self._edit.clear()
            self._attachments.clear()
            self.clearMentions()
            self._close_popup()
            return True
        if (
            self._command_submit_mode == "signal"
            and self._command_provider is not None
            and text.startswith("/")
        ):
            self.commandSubmitted.emit(text)
            self._edit.clear()
            self._attachments.clear()
            self.clearMentions()
            self._close_popup()
            return True
        self.submitted.emit(text)
        self.submittedFull.emit(text, attachments)
        self._edit.clear()
        self._attachments.clear()
        self.clearMentions()
        self._close_popup()
        return True

    def _on_button_clicked(self) -> None:
        if self._generating and not self._edit.toPlainText().strip():
            self.stopRequested.emit()
            return
        self.submit()

    def setGenerating(self, on: bool) -> None:
        """设置生成状态：草稿为空时按钮切换为「停止」。"""
        on = bool(on)
        if on == self._generating:
            return
        self._generating = on
        self._sync_button()

    def isGenerating(self) -> bool:
        """是否处于生成状态。"""
        return self._generating

    def _sync_button(self) -> None:
        has_draft = bool(self._edit.toPlainText().strip())
        stopping = self._generating and not has_draft
        icon = (
            ElaIconType.IconName.CircleStop
            if stopping
            else ElaIconType.IconName.ArrowUp
        )
        color = "danger" if stopping else "primary"
        tooltip = self._stop_text if stopping else self._send_text
        if self._button_icon != icon:
            self._button.setElaIcon(icon, 16)
            self._button_icon = icon
        if self._button.color() != color:
            self._button.setColor(color)
        if self._button.toolTip() != tooltip:
            self._button.setToolTip(tooltip)
            set_tooltip(self._button, tooltip, ElaToolTipPositionType.Top)
        # 空草稿且非「停止」态时置灰；生成中禁用排队时提交会被 submit() 拒绝，
        # 按钮必须跟着置灰（否则就是点了没反应的「发送」）
        blocked = self._generating and not self._queue_enabled
        self._button.setEnabled(stopping or (has_draft and not blocked))

    def setSendOnEnter(self, on: bool) -> None:
        """设置回车是否发送（关闭后仅按钮发送）。"""
        self._send_on_enter = bool(on)

    def sendOnEnter(self) -> bool:
        """回车是否发送。"""
        return self._send_on_enter

    def setSendText(self, text: str) -> None:
        """设置发送按钮提示文案（图标按钮，文案用于 tooltip）。"""
        self._send_text = text or "发送"
        self._sync_button()

    def sendText(self) -> str:
        """获取发送按钮提示文案。"""
        return self._send_text

    def setStopText(self, text: str) -> None:
        """设置停止按钮提示文案（图标按钮，文案用于 tooltip）。"""
        self._stop_text = text or "停止"
        self._sync_button()

    def stopText(self) -> str:
        """获取停止按钮提示文案。"""
        return self._stop_text

    def setMaxLines(self, lines: int) -> None:
        """设置最大行数（超出后输入框内部滚动）。"""
        self._max_lines = max(self._min_lines, _as_int(lines, self._max_lines))
        self._sync_height()

    def maxLines(self) -> int:
        """获取最大行数。"""
        return self._max_lines

    def setMinLines(self, lines: int) -> None:
        """设置最小行数（空输入时的可见高度，默认 3）。"""
        self._min_lines = max(1, _as_int(lines, self._min_lines))
        if self._max_lines < self._min_lines:
            self._max_lines = self._min_lines
        self._sync_height()

    def minLines(self) -> int:
        """获取最小行数。"""
        return self._min_lines

    # -- 高度自适应 --------------------------------------------------------

    def _line_height(self) -> int:
        """行高（编辑框字体固定，取构造时的常规字体行距）。"""
        return QFontMetrics(self._normal_font).lineSpacing()

    def _sync_height(self) -> None:
        """把行数预算同步给编辑框（``setLineBudget`` 内部会 ``updateGeometry``）。

        自增高由 ``_ChatPlainTextEdit.sizeHint()`` 驱动，槽内改几何会重入布局。
        """
        self._edit.setLineBudget(self._min_lines, self._max_lines)

    def _on_text_changed(self) -> None:
        self._sync_height()
        self._sync_button()
        self._update_popup()
        if not self._history_applying and self._history is not None:
            self._history.reset(self._historyMode())
        self._draft_timer.start()
        self.textChanged.emit(self._edit.toPlainText())

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        self._sync_height()

    # -- 拖放（拖到卡片 / 工具栏：文件与图片都收） --------------------------

    def acceptsMime(self, mime) -> bool:
        """mime 里是否有本组件能收下的内容（本地文件 / 图片）。"""
        return bool(localFiles(mime) or mimeImage(mime) is not None)

    def attachMime(self, mime) -> bool:
        """把 mime 里的文件 / 图片收进附件；实际收下了才返回 ``True``。

        文件走 :meth:`addAttachments` + ``filesAdded``，图片走
        :meth:`_on_image_pasted`（与粘贴图片同一处去重）。
        """
        files = localFiles(mime)
        if files:
            return self._add_files(files)
        image = mimeImage(mime)
        if image is not None:
            return self._on_image_pasted(image)
        return False

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if self.acceptsMime(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if self.acceptsMime(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if not self.attachMime(event.mimeData()):
            super().dropEvent(event)
            return
        event.acceptProposedAction()

    # -- 键盘 --------------------------------------------------------------

    def _on_preedit_changed(self, text: str) -> None:
        """记录输入法组合文本（``inputMethod().isVisible()`` 焦点在框内即恒真，不能用作判据）。"""
        self._preedit = text

    def _on_edit_focus_changed(self, focused: bool) -> None:
        self._surface.setFocused(focused)
        if not focused:
            # 失焦时系统会取消组合：清掉残留，否则之后回车会被当成组合中
            self._preedit = ""

    def _handle_edit_key(self, event) -> bool:
        """编辑框按键处理器（由 ``_ChatPlainTextEdit.keyPressEvent`` 调用）。

        返回 ``True`` 表示已消费。
        """
        key = event.key()
        modifiers = event.modifiers()

        # 补全导航
        if self._popup.isOpen() and not (
            modifiers & Qt.KeyboardModifier.ControlModifier
        ):
            if key == Qt.Key.Key_Escape:
                self._close_popup()
                return True
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                self._popup.moveSelection(1 if key == Qt.Key.Key_Down else -1)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
                self._popup.activateCurrent()
                return True

        if (
            self._history is not None
            and key in (Qt.Key.Key_Up, Qt.Key.Key_Down)
            and not (modifiers & ~Qt.KeyboardModifier.KeypadModifier)
            and not self._preedit
        ):
            cursor = self._edit.textCursor()
            if not cursor.hasSelection():
                if key == Qt.Key.Key_Up and cursor.blockNumber() == 0:
                    entry = self._history.previous(
                        self._historyMode(), self._edit.toPlainText()
                    )
                    if entry is not None:
                        self._applyHistoryEntry(entry)
                        return True
                if (
                    key == Qt.Key.Key_Down
                    and cursor.blockNumber() == self._edit.document().blockCount() - 1
                ):
                    entry = self._history.next(self._historyMode())
                    if entry is not None:
                        self._applyHistoryEntry(entry)
                        return True

        if key == Qt.Key.Key_U and modifiers & Qt.KeyboardModifier.ControlModifier:
            self._on_add_file_clicked()
            return True

        if key == Qt.Key.Key_G and modifiers & Qt.KeyboardModifier.ControlModifier:
            if self._generating:
                self.stopRequested.emit()
                return True

        if key == Qt.Key.Key_Escape:
            if self._popup.isOpen():
                self._close_popup()
                return True
            if self._shell_mode:
                self.setShellMode(False)
                return True
            if self._generating:
                self.stopRequested.emit()
                return True

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if modifiers & Qt.KeyboardModifier.ControlModifier:
                text = self._edit.toPlainText().strip()
                if not text or self._preedit:
                    return False
                self.alternateSubmitted.emit(text, self.attachments())
                self._edit.clear()
                self._attachments.clear()
                self.clearMentions()
                self._close_popup()
                return True
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                return False
            if not self._send_on_enter:
                return False
            # 输入法组合期间回车用于上屏候选
            if self._preedit:
                return False
            if self._generating and not self._edit.toPlainText().strip():
                return False
            # 提交被拒（生成中 + 禁用排队）时把事件还给编辑器：插入换行，
            # 而不是静默吃掉这次回车
            return bool(self.submit())
        return False
