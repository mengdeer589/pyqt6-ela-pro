"""
聊天输入区组件：补全浮层 + 输入卡片（附件条 / 编辑框 / 工具栏）。

``Enter`` 发送、``Shift+Enter`` 换行；大段粘贴自动转附件；IME 组合期间回车
不会误发送。附件快照见 :meth:`ElaChatInput.attachments`。
"""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import (
    QTimer,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QFont,
    QFontMetrics,
    QImage,
)
from PyQt6.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QWidget,
)
from PyQt6ElaWidgetTools import (
    ElaIconType,
    ElaPlainTextEdit,
)

from .._internal import safe_connect, system_cjk_font_family
from .._styles import editBorderlessStyle
from ..ela_button import ElaButton
from ..tooltips import ElaToolTipPositionType, set_tooltip
from ..widget_base import ElaThemeWidget
from .blocks import AttachmentStrip
from .input_attachments import _InputAttachmentsMixin
from .input_completion import _InputCompletionMixin
from .input_history import _InputHistoryMixin
from .input_parts import (
    _INPUT_CARD_PADDING,
    _INPUT_CARD_SPACING,
    _ChatPlainTextEdit,
    _ContextUsageRing,
    _InputSurface,
)
from .input_toolbar import _InputToolbarMixin
from .message import _as_int
from .suggestions import SuggestionPopup
from .toolbar import ElaChatToolBar

#: 输入区外边距（左、上、右、下）
_OUTER_MARGIN = (12, 6, 12, 12)
#: 行间距
_ROW_SPACING = 6
#: 默认最小行数（空输入时的可见高度）
_DEFAULT_MIN_LINES = 3
#: 默认最大行数
_DEFAULT_MAX_LINES = 8
#: 发送 / 停止图标按钮边长
_SEND_BUTTON_SIZE = 32


class ElaChatInput(
    _InputCompletionMixin,
    _InputAttachmentsMixin,
    _InputHistoryMixin,
    _InputToolbarMixin,
    ElaThemeWidget,
):
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
        safe_connect(
            self._popup,
            "suggestionActivated",
            self._on_suggestion_activated,
            "input.suggestion",
        )
        layout.addWidget(self._popup)

        # 层 1：输入卡片（附件条 / 编辑框 / 工具栏都在卡片内）
        self._surface = _InputSurface(self)
        surface_layout = QVBoxLayout(self._surface)
        surface_layout.setContentsMargins(*_INPUT_CARD_PADDING)
        surface_layout.setSpacing(_INPUT_CARD_SPACING)
        layout.addWidget(self._surface)

        # 卡片内 ①：附件条
        self._attachments = AttachmentStrip(self._surface)
        self._attachments.setVisible(False)
        safe_connect(
            self._attachments,
            "changed",
            self._on_attachments_changed,
            "input.attachments",
        )
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
        safe_connect(
            self._edit, "preeditChanged", self._on_preedit_changed, "input.preedit"
        )
        safe_connect(
            self._edit, "focusChanged", self._on_edit_focus_changed, "input.focus"
        )
        safe_connect(self._edit, "textChanged", self._on_text_changed, "input.text")
        safe_connect(
            self._edit, "imagePasted", self._on_image_pasted, "input.image_paste"
        )
        safe_connect(
            self._edit, "filesAdded", self._on_files_added, "input.files_added"
        )
        safe_connect(
            self._edit,
            "largeTextPasted",
            self._on_large_text_pasted,
            "input.large_text",
        )
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
        safe_connect(
            self._draft_timer,
            "timeout",
            lambda: self.draftChanged.emit(self.draftState()),
            "input.draft",
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
        safe_connect(self._button, "clicked", self._on_button_clicked, "input.send")
        #: 已写入按钮的图标枚举 —— ``QIcon`` 无值相等语义，每次比较都会重建图标
        self._button_icon = ElaIconType.IconName.ArrowUp
        #: 当前发送 / 停止提示文案（避免重复重建 ElaToolTip）
        self._button_tooltip = ""
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

    def popup(self) -> SuggestionPopup:
        """获取补全浮层控件。"""
        return self._popup

    def text(self) -> str:
        """获取输入文本。"""
        return self._edit.toPlainText()

    def setText(self, text: str) -> None:
        """设置输入文本（光标移到末尾；旧 ``@`` 引用失效）。"""
        self.clearMentions()
        self._set_edit_text(text or "")

    def clear(self) -> None:
        """清空草稿（文本 / ``@`` 引用 / 附件）与补全浮层。"""
        self._edit.clear()
        self.clearMentions()
        self._attachments.clear()
        self._close_popup()

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
                self.mentionSpans(text),
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
        if self._button_tooltip != tooltip:
            self._button_tooltip = tooltip
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
