"""问答型工具审批的自绘控件（``pyqt6_ela_pro.chat`` 内部模块）。

逐题向导 + 进度段 + 两行候选卡（标题 + 说明）+ 「输入自己的答案」行。
配色一律走主题令牌，勾选标记用 Ela 的 CheckBox / RadioButton，不自绘。
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPalette
from PyQt6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from PyQt6ElaWidgetTools import (
    ElaCheckBox,
    ElaPlainTextEdit,
    ElaRadioButton,
    ElaThemeType,
    eTheme,
)

from .._internal import _ThemeAwareMixin, is_deleted, single_shot_on
from .._styles import ColorText, paintRoundedCard
from ._theme import (
    accent_color,
    base_color,
    blend,
    border_color,
    card_color,
    muted_color,
    surface_color,
    text_color,
)

#: 标记与文字的间距
MARK_GAP = 8
#: 卡片内边距（左, 上, 右, 下）；纵向压到 4px，候选行是列表不是卡片
CARD_PADDING = (8, 4, 8, 4)
#: 候选卡圆角
CARD_RADIUS = 6.0
#: 候选卡之间的间距（对齐 ``gap: 6px``）
OPTION_GAP = 6
#: 进度段的条形尺寸与命中盒；圆角取高度一半（1px）才是胶囊，不是方头短横
SEGMENT_BAR = (16, 2)
SEGMENT_HIT = 16
#: 外发光透明度（对齐 opencode ``rgba(3,76,255,.24)``）
GLOW_ALPHA = 61
#: 「输入自己的答案」的固定文案（对齐 ``ui.messagePart.option.typeOwnAnswer``）
CUSTOM_ANSWER_LABEL = "输入自己的答案"
#: 自定义答案输入框的占位符（对齐 ``ui.question.custom.placeholder``）
CUSTOM_ANSWER_PLACEHOLDER = "输入你的答案…"


def question_colors(mode) -> dict:
    """一次性算出问答型用到的全部颜色。

    刻意没有「标记色」：勾选标记是 Ela 子控件，自己从 ``eTheme`` 取色。
    """
    ink = text_color(mode)
    accent = accent_color(mode)
    glow = QColor(accent)
    glow.setAlpha(GLOW_ALPHA)
    return {
        "card": surface_color(mode),
        "card_hover": card_color(mode),
        "picked": blend(base_color(mode), accent, 0.10),
        "border": border_color(mode, 0.16),
        "neutral_border": border_color(mode, 0.18),
        "glow": glow,
        "accent": accent,
        "ink": ink,
        "muted": muted_color(mode, 0.7),
        "hint": muted_color(mode, 0.62),
        "surface": card_color(mode),
        "overlay": blend(base_color(mode), ink, 0.06),
        "overlay_press": blend(base_color(mode), ink, 0.12),
        "focus": blend(accent, ink, 0.35),
    }


def globalKeyAction(key, mods) -> Optional[str]:
    """把卡片级快捷键 ``(key, mods)`` 映射成动作串；不匹配返回 ``None``。

    动作串：``"next"``（Ctrl+Enter）/ ``"back"``（Alt+←）/ ``"dismiss"``（Esc）/
    ``"digit:N"``（1–9，按整组候选卡下标）。行内与卡片本体共用这一份。
    """
    ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
    alt = bool(mods & Qt.KeyboardModifier.AltModifier)
    plain = not (
        ctrl
        or alt
        or mods & (Qt.KeyboardModifier.MetaModifier | Qt.KeyboardModifier.ShiftModifier)
    )
    if ctrl and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
        return "next"
    if alt and key == Qt.Key.Key_Left:
        return "back"
    if plain and key == Qt.Key.Key_Escape:
        return "dismiss"
    if plain and Qt.Key.Key_1 <= key <= Qt.Key.Key_9:
        return f"digit:{key - Qt.Key.Key_1}"
    return None


class _AutoGrowEditor(ElaPlainTextEdit):
    """按文档高度自增高的编辑器。

    必须覆写 ``sizeHint``（上游硬编码 ``(256, 192)``）；在 ``textChanged`` 里改
    几何会重入布局 = 0xC0000409。按键语义走信号，不装事件过滤器（子控件随行
    销毁，过滤器会在父窗口树析构时踩 0xC0000409）。
    """

    #: 按 Enter（非 Shift / Ctrl）：提交这一题
    submitRequested = pyqtSignal()
    #: 按 Esc：退出编辑（**保留文本**）
    dismissRequested = pyqtSignal()
    #: 按 Ctrl+Enter：整卡「下一步 / 提交」
    advanceRequested = pyqtSignal()

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.dismissRequested.emit()
            event.accept()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            mods = event.modifiers()
            if mods & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)  # 换行
                return
            if mods & Qt.KeyboardModifier.ControlModifier:
                self.advanceRequested.emit()
            else:
                self.submitRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def sizeHint(self) -> QSize:  # noqa: N802
        hint = super().sizeHint()
        return QSize(hint.width(), self._document_height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(60, 24)

    def _document_height(self) -> int:
        """排版后的像素高度（含折行）。

        别用 ``document().size().height()`` —— 那是逻辑单位（块数）；
        ``blockBoundingRect`` 才是布局后的真实高度。
        """
        document = self.document()
        # 文档宽度必须跟视口同步，否则 blockBoundingRect 按旧宽（或不定宽）
        # 排版，折行高度会被低估（长单段只报一两行）。
        width = self.viewport().width()
        if width > 0 and document.textWidth() != width:
            document.setTextWidth(width)
        layout = document.documentLayout()
        total = 0.0
        block = document.begin()
        while block.isValid():
            total += layout.blockBoundingRect(block).height()
            block = block.next()
        if total <= 0:
            total = max(1, document.blockCount()) * self.fontMetrics().lineSpacing()
        return int(total + 0.5) + 2 * self.frameWidth() + 4


class QuestionSegment(_ThemeAwareMixin, QWidget):
    """进度段（opencode 的 ``question-progress-segment``）。

    16×2px 圆角条 + 16px 命中盒，三态：**未答**（弱化）/ **已答**（强调）/
    **当前**（主文本色，最强 —— 对齐 opencode 的 CSS 覆盖顺序）。可点击跳题。
    """

    #: 用户点了第 ``index`` 道题
    jumped = pyqtSignal(int)

    def __init__(self, index: int, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme_mode = eTheme.getThemeMode()
        self._index = int(index)
        self._active = False
        self._answered = False
        self.setFixedSize(SEGMENT_HIT, SEGMENT_HIT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"第 {index + 1} 个问题")

    def setState(self, active: bool, answered: bool) -> None:  # noqa: N802
        """设置三态。"""
        self._active = bool(active)
        self._answered = bool(answered)
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.jumped.emit(self._index)
        super().mousePressEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._active:
            color = text_color(self._theme_mode)
        elif self._answered:
            color = accent_color(self._theme_mode)
        else:
            color = muted_color(self._theme_mode, 0.45)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        # 圆角 = 高度的一半 = 全圆角胶囊（``border-radius: 999px`` 的直译）
        radius = SEGMENT_BAR[1] / 2.0
        painter.drawRoundedRect(
            QRectF(
                0,
                (self.height() - SEGMENT_BAR[1]) / 2.0,
                SEGMENT_BAR[0],
                SEGMENT_BAR[1],
            ),
            radius,
            radius,
        )
        painter.end()

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:  # noqa: N802
        self._theme_mode = mode
        self.update()


class QuestionOptionCard(QAbstractButton):
    """候选卡：左侧勾选标记 + 右侧两行文字（标题 + 弱化说明）。

    整卡是点击目标，选中态 = 底变色 + 外发光。``isCustom`` 时是「输入自己的
    答案」那一行，点标记 / 点整行 / ``Space`` 都是选中并展开编辑器。

    本控件是纯输入面：不持单选 / 多选状态机，勾选状态由外层
    ``PermissionCard`` 用 :meth:`setPicked` 灌回来。
    """

    #: 整行被激活（鼠标点行、Space；参数为选项 label，自定义行为空串）
    activate = pyqtSignal(str)
    #: 只点了左侧标记（自定义行用它「选中但不展开」；普通行与整行等价）
    markClicked = pyqtSignal(str)
    #: 自定义答案提交（参数：文本）
    editCommitted = pyqtSignal(str)
    #: 该行获得键盘焦点（参数：行号）
    rowFocused = pyqtSignal(int)
    #: 请求把焦点移到相邻行（``-1`` 上一行 / ``+1`` 下一行 / ``0`` 首行 / ``2`` 末行）
    moveFocus = pyqtSignal(int)
    #: 卡片级快捷键（``"next"`` / ``"back"`` / ``"dismiss"`` / ``"digit:<n>"``）；
    #: 用信号而非事件过滤器：给行装 Python 过滤器在析构期会踩 0xC0000409
    globalKey = pyqtSignal(str)
    #: 本行内容高度变了（自定义答案编辑器展开 / 收起），外层据此重算选项区
    contentChanged = pyqtSignal()

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        value: str = "",
        description: str = "",
        multi: bool = False,
        isCustom: bool = False,
    ) -> None:
        super().__init__(parent)
        self._value = value or ""
        self._description = description or ""
        self._multi = bool(multi)
        self._is_custom = bool(isCustom)
        self._picked = False
        self._editing = False
        #: 本次按下是否落在勾选标记区（决定 release 是否再发 activate）
        self._press_on_mark = False
        self._row_index = 0
        self._theme_mode = eTheme.getThemeMode()
        self._colors = question_colors(self._theme_mode)

        # 刻意不开 checkable：勾选真相只有 _picked 一份，开 checkable 会多出永远
        # 为 False 的 checked、每次点击发 toggled(True)，多选「再点取消」直接失效
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # 高度锁成内容高：Minimum 会让父布局灌满剩余空间，Fixed 才是「要多高给多高」。
        # 说明文案可换行，而 QAbstractButton 不转发 heightForWidth，故 sizeHint
        # 自己折行算高度、resizeEvent 里 updateGeometry 让布局按新宽度重问。
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        row = QHBoxLayout(self)
        row.setContentsMargins(*CARD_PADDING)
        row.setSpacing(MARK_GAP)
        # 勾选标记用 Ela 控件（多选 ElaCheckBox / 单选 ElaRadioButton）：不抢焦点、
        # 不吃鼠标（点击统一由卡片判断），配色自己从 eTheme 取
        self._mark = ElaCheckBox(self) if self._multi else ElaRadioButton(self)
        self._mark.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._mark.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._mark.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self._mark.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        row.addWidget(self._mark, 0, Qt.AlignmentFlag.AlignVCenter)
        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(1)
        self._label = ColorText(self)
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._label.setWordWrap(True)
        self._label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        texts.addWidget(self._label)
        self._desc = ColorText(self)
        self._desc.setTextFormat(Qt.TextFormat.PlainText)
        self._desc.setWordWrap(True)
        self._desc.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        texts.addWidget(self._desc)
        row.addLayout(texts, 1)
        self._editor = None
        #: 编辑器尚未创建时的待回填文本（否则每次重建都会静默丢掉草稿）
        self._pending_editor_text = ""
        self._texts_layout = texts
        self._apply_content()
        self._apply_theme()

    # -- 数据 --------------------------------------------------------------

    def value(self) -> str:
        """选项 label（自定义行为空串）。"""
        return self._value

    def description(self) -> str:
        """选项说明。"""
        return self._description

    def isCustom(self) -> bool:  # noqa: N802
        """是否是「输入自己的答案」那一行。"""
        return self._is_custom

    def isMulti(self) -> bool:  # noqa: N802
        """是否多选（决定 radio / checkbox）。"""
        return self._multi

    def isPicked(self) -> bool:  # noqa: N802
        """是否选中。"""
        return self._picked

    def isEditing(self) -> bool:  # noqa: N802
        """是否处于自定义答案编辑态。"""
        return self._editing

    def rowIndex(self) -> int:  # noqa: N802
        """行号（供方向键导航）。"""
        return self._row_index

    def setRowIndex(self, index: int) -> None:  # noqa: N802
        """设置行号。"""
        self._row_index = int(index)

    def setPicked(self, picked: bool) -> None:  # noqa: N802
        """设置选中态（不发 ``activate``，避开自检回环）。"""
        if self._picked == bool(picked):
            return
        self._picked = bool(picked)
        self._mark.setChecked(self._picked)
        self.update()
        self._apply_theme()

    def setEditing(self, editing: bool) -> None:  # noqa: N802
        """进入 / 退出自定义答案编辑态（编辑中**保持选中卡样式**）。"""
        if not self._is_custom:
            return
        editing = bool(editing)
        if editing and self._editor is None:
            self._editor = _AutoGrowEditor(self)
            self._editor.setFrameShape(QFrame.Shape.NoFrame)
            self._editor.setPlaceholderText(CUSTOM_ANSWER_PLACEHOLDER)
            self._editor.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            self._editor.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            self._editor.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
            )
            self._editor.textChanged.connect(self._on_editor_changed)
            # 文档排版完成（折行高度变化）后再同步一次：textChanged 触发时布局
            # 往往还没更新，只靠那一次会把行高压在旧值上
            self._editor.document().documentLayout().documentSizeChanged.connect(
                lambda *_: self._schedule_height_sync()
            )
            # 按键语义走编辑器自己的信号（见 _AutoGrowEditor），不装事件过滤器
            self._editor.submitRequested.connect(self.commitEdit)
            self._editor.dismissRequested.connect(self._on_editor_dismissed)
            self._editor.advanceRequested.connect(self._on_editor_advance)
            self._texts_layout.addWidget(self._editor)
            if self._pending_editor_text:
                self._editor.setPlainText(self._pending_editor_text)
        self._editing = editing
        if self._editor is not None:
            self._editor.setVisible(editing)
            # 首次 show 时 Qt 会把 ElaPlainTextEdit 的 palette 重置成 app 调色板
            # （本地轮在 showEvent 补回主题色），这里再按卡片配色补一次 muted 色
            self._apply_editor_theme(self._colors)
        if editing:
            self._editor.setFocus()
        self._apply_content()
        self.updateGeometry()
        self._schedule_height_sync()
        self.contentChanged.emit()

    def editorText(self) -> str:  # noqa: N802
        """自定义答案当前文本（编辑器未创建时返回待回填文本）。"""
        if self._editor is not None:
            return self._editor.toPlainText()
        return self._pending_editor_text

    def setEditorText(self, text: str) -> None:  # noqa: N802
        """回填自定义答案（切题回来时恢复草稿；编辑器懒创建前先暂存）。"""
        text = text or ""
        self._pending_editor_text = text
        if self._editor is None:
            return
        if self._editor.toPlainText() != text:
            self._editor.setPlainText(text)

    def commitEdit(self) -> None:  # noqa: N802
        """提交自定义答案（Enter；卡片在「下一步 / 提交 / 切题」前也会先调它）。

        空文本什么都不做；非空文本不要求行处于编辑态 —— Esc 退出编辑但保留了
        文本，此时点「下一步 / 提交」也必须把它算成答案。
        """
        if self._editor is None:
            return
        text = self.editorText().strip()
        if not text:
            return
        self.editCommitted.emit(text)

    def _on_editor_dismissed(self) -> None:
        """编辑器按 Esc：退出编辑但保留文本（不能冒泡成「忽略整个问题」）。"""
        self.setEditing(False)
        self.setFocus()

    def _on_editor_advance(self) -> None:
        """编辑器按 Ctrl+Enter：转成整卡的「下一步 / 提交」。"""
        self.globalKey.emit("next")

    # -- 交互 --------------------------------------------------------------

    def _mark_rect(self) -> QRectF:
        """标记的命中区（直接取子控件几何，标记尺寸变了也不用改这里）。"""
        return QRectF(self._mark.geometry())

    def markWidget(self) -> QWidget:  # noqa: N802
        """勾选标记控件（``ElaRadioButton`` / ``ElaCheckBox``）。"""
        return self._mark

    def mousePressEvent(self, event) -> None:  # noqa: N802
        """点左侧标记 = 只切勾选；点其余 = 整行激活（自定义行即展开编辑器）。

        编辑态下标记仍可点（多选要能「再点一次 = 取消并收起」）；行内其它位置
        把焦点还给编辑器，走 ``super()`` 会让 ``QAbstractButton`` 抢走焦点。
        """
        if self._mark_rect().contains(event.position()):
            self._press_on_mark = True
            self.markClicked.emit(self._value)
            event.accept()
            return
        if self._editing:
            if self._editor is not None:
                self._editor.setFocus()
            event.accept()
            return
        self._press_on_mark = False
        QAbstractButton.mousePressEvent(self, event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        # 不用 super：它只会发 clicked，且要求 press 走过 super（标记区是故意
        # 截断的），否则没 press 过也算一次点击，白白多发一轮 activate。
        if self._press_on_mark:
            # 标记区按下已发过 markClicked，同一手势的 release 不能再发 activate
            self._press_on_mark = False
            return
        if not self._editing and self.rect().contains(event.position().toPoint()):
            self.activate.emit(self._value)

    def focusInEvent(self, event) -> None:  # noqa: N802
        super().focusInEvent(event)
        self.rowFocused.emit(self._row_index)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """键盘操作（编辑态一律让给编辑器）。

        ``Ctrl+⏎`` / ``Alt+←`` / ``Esc`` / ``1``–``9`` 转成 :attr:`globalKey` 交给
        外层；方向键 / Home / End 在行间移动焦点；``Space`` 切换勾选。
        """
        key = event.key()
        if self._editing:
            return QAbstractButton.keyPressEvent(self, event)
        mods = event.modifiers()
        if self._emit_global_key(key, mods):
            event.accept()
            return
        if mods & (
            Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.MetaModifier
        ):
            return QAbstractButton.keyPressEvent(self, event)
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Right):
            self.moveFocus.emit(1)
        elif key in (Qt.Key.Key_Up, Qt.Key.Key_Left):
            self.moveFocus.emit(-1)
        elif key == Qt.Key.Key_Home:
            self.moveFocus.emit(0)
        elif key == Qt.Key.Key_End:
            self.moveFocus.emit(2)
        elif key == Qt.Key.Key_Space:
            # 自定义行：Space 走「切勾选」而不是「展开编辑器」，Enter 才展开
            self.markClicked.emit(self._value)
        else:
            return QAbstractButton.keyPressEvent(self, event)
        event.accept()

    def _emit_global_key(self, key, mods) -> bool:
        """把卡片级快捷键转成 :attr:`globalKey`；返回是否消费。"""
        action = globalKeyAction(key, mods)
        if action is None:
            return False
        self.globalKey.emit(action)
        return True

    def _on_editor_changed(self) -> None:
        """编辑器内容变化：收起占位文案 + 请布局重新问一次高度。

        绝不能在这里直接改控件几何（``setFixedHeight`` 之类）—— 那是
        ``textChanged`` 槽里重入布局，Qt 会 0xC0000409 静默终止。
        """
        if self._editor is None:
            return
        self._apply_content()
        self.updateGeometry()
        # 行高由内容决定，但嵌套布局不会自己重问 sizeHint；延到下一轮事件循环
        self._schedule_height_sync()
        self.contentChanged.emit()

    # -- 外观 --------------------------------------------------------------

    def _apply_content(self) -> None:
        if self._is_custom:
            self._label.setText(CUSTOM_ANSWER_LABEL)
            # 编辑态下让位给输入框（它自带 placeholder），不再重复显示一遍
            if self._editing:
                self._desc.setText("")
            else:
                self._desc.setText(
                    CUSTOM_ANSWER_PLACEHOLDER
                    if not self.editorText()
                    else self.editorText()
                )
        else:
            self._label.setText(self._value)
            self._desc.setText(self._description)
        self._desc.setVisible(bool(self._desc.text()))

    def applyTheme(self, mode) -> None:  # noqa: N802
        """换主题（由 ``PermissionCard`` 派发）；只改颜色，不碰内容。

        ``_apply_content()`` 会连带写编辑器文本，在「行已销毁但包装器还在」时
        会踩进已释放的编辑器（0xC0000409 静默终止）。
        """
        self._theme_mode = mode
        self._colors = question_colors(mode)
        self._apply_theme()
        self.update()

    def _apply_theme(self) -> None:
        colors = self._colors
        self._label.setTextColor(colors["ink"])
        self._label.setTextPixelSize(13)
        # 常规字重：题面才是该被强调的那一行，候选标题再加粗会抢层级
        self._label.setTextWeight(QFont.Weight.Normal)
        self._desc.setTextColor(colors["muted"])
        self._desc.setTextPixelSize(12)
        self._apply_editor_theme(colors)

    def _apply_editor_theme(self, colors: dict) -> None:
        """给自定义答案输入框上色（只能走 palette）。

        ``ElaPlainTextEdit`` 没有 ``setTextColor``，且在主题信号链上抛异常 =
        0xC0000409 静默终止。``QPlainTextEdit`` 不像 ``ElaText`` 那样在
        ``paintEvent`` 重置 palette，这里设的色能留住。
        """
        if self._editor is None:
            return
        palette = self._editor.palette()
        # **必须显式写 ``Text``**：``QPlainTextEdit.foregroundRole()`` 是
        # ``WindowText``（Qt 默认），写它不会影响正文颜色。
        palette.setColor(QPalette.ColorRole.Text, colors["muted"])
        self._editor.setPalette(palette)

    def paintEvent(self, _event) -> None:  # noqa: N802
        """自绘卡片底 / 描边 / 外发光。

        标记与文字都交给子控件（Ela 勾选控件 / ``ColorText``），这里只管壳。
        """
        colors = self._colors
        enabled = self.isEnabled()
        if self._picked:
            background = colors["picked"]
            border = QColor(0, 0, 0, 0)
            glow = colors["glow"]
        elif self.underMouse():
            # opencode 语义：hover 未选中项用 bg-base
            background = colors["card_hover"]
            border = colors["border"]
            glow = None
        else:
            # 默认态保留一圈极淡描边：全去掉几行底色会连成一片灰带，没有分隔
            background = colors["card"]
            border = colors["border"]
            glow = None
        if not enabled:
            background = QColor(background)
            background.setAlphaF(background.alphaF() * 0.5)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        paintRoundedCard(
            painter,
            QRectF(self.rect()),
            background=background,
            border=border,
            radius=CARD_RADIUS,
            glow=glow,
        )
        painter.end()

    def _comfortable_minimum(self) -> int:
        """单行候选行的舒适高度下限（从字体度量算，不写死像素）。

        只有标题时自然高偏小，点选目标太窄；两行时内容自己够高，不需要下限。
        字体度量平台相关，写死像素会让卡片比 ``sizeHint`` 矮一截。
        """
        if self._desc.isVisible() or self._description:
            return 0
        fm = self._label.fontMetrics()
        return round(fm.height() * 2.0) + CARD_PADDING[1] + CARD_PADDING[3]

    def _text_width(self) -> int:
        """候选行文字的可用宽度（扣掉卡片内边距 + 标记 + 间距）。"""
        width = self.width()
        if width <= 0:
            width = self._label.width()
        if width <= 0:
            width = 320
        mark = self._mark.sizeHint().width() or self._mark.width()
        return max(
            1,
            int(width) - CARD_PADDING[0] - CARD_PADDING[2] - int(mark) - MARK_GAP,
        )

    def _content_height(self) -> int:
        """按当前文字宽度算自然内容高度（不读取当前控件高度）。

        不能用 ``super().sizeHint()`` / 布局当前尺寸：行被钉高后标签会被拉伸，
        再读一次就永远缩不回去。
        """
        width = self._text_width()
        label_height = self._label.heightForWidth(width)
        if label_height <= 0:
            label_height = self._label.sizeHint().height()
        content = label_height
        if self._desc.isVisible() or self._description:
            desc_height = self._desc.heightForWidth(width)
            if desc_height <= 0:
                desc_height = self._desc.sizeHint().height()
            content += self._texts_layout.spacing() + desc_height
        content = max(content, self._mark.sizeHint().height())
        content += CARD_PADDING[1] + CARD_PADDING[3]
        if self._editor is not None and self._editing:
            content += self._editor.sizeHint().height()
        return max(content, self._comfortable_minimum())

    def sizeHint(self) -> QSize:  # noqa: N802
        """行高 = 按当前文字宽度折行后的自然高（有下限保底）+ 编辑器高度。

        ``QAbstractButton`` 不转发 ``heightForWidth``，也不能用布局当前高度反推
        内容高度（行被钉高后标签会被拉伸，再读就缩不回去）。
        """
        hint = super().sizeHint()
        return QSize(hint.width(), self._content_height())

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        # 宽度变了 → 折行行数可能变 → 下一轮按新宽度重算行高。
        self.updateGeometry()
        self._schedule_height_sync()

    def _schedule_height_sync(self) -> None:
        """下一轮事件循环把行高钉到 ``sizeHint``（布局不会自己重问）。"""
        single_shot_on(self, 0, self._sync_height)

    def _sync_height(self) -> None:
        if is_deleted(self):
            return
        if self._editor is not None:
            if self._editing:
                # 外层布局不会把编辑器撑到它的 sizeHint（Minimum 策略只保证
                # 下限），必须显式钉住；否则多行 / 折行答案只露出一部分。
                editor_height = max(24, self._editor.sizeHint().height())
                if self._editor.height() != editor_height or (
                    self._editor.minimumHeight() != editor_height
                ):
                    self._editor.setFixedHeight(editor_height)
            else:
                self._editor.setMinimumHeight(0)
                self._editor.setMaximumHeight(16777215)
        target = max(1, self.sizeHint().height())
        if target == self.height() and self.minimumHeight() == target:
            return
        self.setFixedHeight(target)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        # 宽度给 0：候选行要能换行（说明文案长度不定），横向上不许比 sizeHint 更宽
        return QSize(0, self.sizeHint().height())
