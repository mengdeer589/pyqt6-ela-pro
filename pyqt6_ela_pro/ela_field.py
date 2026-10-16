"""表单字段外壳：标题 + 必填标记 + 编辑器槽 + 辅助文字 + 校验状态行。

搬运自 ``Fluent-Qt/src/components/layout/Field.*``（注意它在 Fluent 的 ``layout/``
目录下，**不是** ``input/``）。这是一个**纯组合壳**：从不碰编辑器的文本、不做任何校验，
只负责把「这个字段现在的状态」表达出来。

四行竖排（间距一律 4px）::

    ┌ 标题  *                                    ← 标题行
    ├ [编辑器]                                     ← 编辑器槽（ContentSlot 托管）
    ├ 辅助文字（弱化色，**永远不被校验状态改色**）
    └ ⚠ 校验信息（图标 + 状态色文字）              ← 状态行

三条从 Fluent 搬来但**必须知道原因**的规则
----------------------------------------
1. **状态图标要求「有文字」且「状态非 None」两者同时成立**。只设状态不给文字时状态行
   整行隐藏 —— 一个没有文案的红三角没有信息量，只是个噪音像素。
2. **辅助文字与状态行是两条独立的行**，可以同时出现；辅助文字**永远**是弱化色。
   把辅助文字跟着状态染色是常见错误：字段同时有「说明」和「错误」时，说明被染红会让
   用户以为说明本身是错的。
3. **``*`` 必填标记永远是错误色**，与 ``status()`` 无关 —— 它表达的是「这栏必填」，
   不是「这栏当前有错」。

禁 QSS
------
Fluent 用 ``setStyleSheet("color: rgba(...)")`` 上色，本库全局禁 QSS，走
``_styles.ColorText``（**每个都必须显式 ``setTextPixelSize``**，否则落到 ElaText 的
默认 28px）。
"""

from __future__ import annotations

from enum import IntEnum
from typing import Optional

from PyQt6.QtCore import QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from PyQt6ElaWidgetTools import ElaIconType

from ._ownership import ContentSlot, ElaWidgetOwnershipType
from ._styles import ColorText, drawElaIcon
from ._theme import ElaStatusRoleType, currentMode, statusColor, text, textMuted
from .widget_base import ElaThemeWidget

__all__ = ["ElaField", "ElaFieldStatusType"]


#: 行间距（标题↔编辑器、图标↔文字、标题↔``*``）一律 4px。
_GAP = 4

#: 标题字号 / 辅助文字与状态文字字号。辅助行比标题小两号 —— 这是层级，不是随手定的。
_LABEL_PX = 14
_DETAIL_PX = 12

#: 状态图标的宿主边长（16）：ElaAwesome 字形按 16px 请求后视觉约 12px，四周留 2px 余量，
#: 图标才不会顶着行高把整行撑高。
_ICON_HOST = 16

#: 图标与文字的垂直对齐。Fluent 用 ``AlignBaseline``（让 ``*`` 坐在文字基线上），
#: 本库用 ``AlignTop``：``ColorText`` 的 ``sizeHint`` 高度受平台字体度量影响很大
#: （实测 windows 43px / offscreen 36px，见 AGENTS.md），基线对齐在两套度量下分别偏移
#: 不同的量，钉不住。顶对齐在两套度量下都是「图标与首行文字顶齐」，稳定。
_ICON_ALIGN = Qt.AlignmentFlag.AlignTop


class ElaFieldStatusType(IntEnum):
    """校验状态。"""

    None_ = 0
    """无状态（默认）。状态行仍可显示文字，但**不显示图标**、文字用弱化色。"""

    Error = 1
    Warning = 2
    Success = 3


#: 状态 → ElaAwesome 图标。**按语义挑，不按 codepoint 对齐** —— Fluent 用的是自带的
#: FluentIcons 字体字形（``ErrorBadge12`` 等），本库用 ElaAwesome，名字对不上是必然的。
_STATUS_ICONS = {
    ElaFieldStatusType.Error: ElaIconType.IconName.CircleXmark,
    ElaFieldStatusType.Warning: ElaIconType.IconName.TriangleExclamation,
    ElaFieldStatusType.Success: ElaIconType.IconName.CircleCheck,
}

_ROLE_BY_STATUS = {
    ElaFieldStatusType.Error: ElaStatusRoleType.Error,
    ElaFieldStatusType.Warning: ElaStatusRoleType.Warning,
    ElaFieldStatusType.Success: ElaStatusRoleType.Success,
}


class _StatusIcon(QWidget):
    """状态图标：一个 16×16 的透明控件，内画 12px 的 ElaAwesome 字形。

    刻意不用 ``ElaIconButton``（那是有悬浮/按下底色的按钮，语义不对）、也不用
    ``QLabel``（QLabel 画不了 QIcon 的字形）。上游 ``eTheme`` 只暴露了
    ``drawEffectShadow``、**没有** ``drawElaIcon(painter, pos, size, icon, color)``，
    所以走 ``ElaIcon.getInstance().getElaIcon(name, color)`` 拿上好色的 QIcon。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._icon: Optional[ElaIconType.IconName] = None
        self._color = QColor(0, 0, 0, 0)
        self.setFixedSize(_ICON_HOST, _ICON_HOST)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def setIcon(self, icon: Optional[ElaIconType.IconName]) -> None:  # noqa: N802
        self._icon = icon
        self.update()

    def setIconColor(self, color) -> None:  # noqa: N802
        self._color = QColor(color)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        if self._icon is None or not self._color.alpha():
            return
        painter = QPainter(self)
        try:
            drawElaIcon(
                painter,
                QRect(0, 0, _ICON_HOST, _ICON_HOST),
                self._icon,
                self._color,
                ratio=self.devicePixelRatioF(),
            )
        finally:
            painter.end()


class ElaField(ElaThemeWidget):
    """表单字段外壳。典型用法::

    field = ElaField(parent)
    field.setLabel("用户名")
    field.setRequired(True)
    field.setHelperText("2-16 个字符")
    field.setEditor(ElaLineEdit(parent))          # 或 setEditor(w, ElaWidgetOwnershipType.Owned)

    # 校验失败时：
    field.setStatus(ElaFieldStatusType.Error)
    field.setStatusText("该用户名已被占用")
    """

    statusChanged = pyqtSignal(object)
    statusTextChanged = pyqtSignal(str)
    labelChanged = pyqtSignal(str)
    helperTextChanged = pyqtSignal(str)
    requiredChanged = pyqtSignal(bool)
    editorChanged = pyqtSignal(object)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._label = ""
        self._helper_text = ""
        self._status_text = ""
        self._status = ElaFieldStatusType.None_
        self._required = False

        # 本控件**不是 tab stop**：tab 序列属于编辑器。显式 setFocus() 走 focusProxy 转发。
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(_GAP)

        self._caption_row = QWidget(self)
        caption_layout = QHBoxLayout(self._caption_row)
        caption_layout.setContentsMargins(0, 0, 0, 0)
        caption_layout.setSpacing(_GAP)
        self._caption = ColorText(self._caption_row)
        self._caption.setTextPixelSize(_LABEL_PX)
        self._caption.setWordWrap(False)
        self._required_mark = ColorText("*", self._caption_row)
        self._required_mark.setTextPixelSize(_LABEL_PX)
        self._required_mark.setVisible(False)
        caption_layout.addWidget(self._caption)
        caption_layout.addWidget(self._required_mark)
        caption_layout.addStretch(1)
        root.addWidget(self._caption_row)

        self._editor_host = QWidget(self)
        self._editor_host_layout = QVBoxLayout(self._editor_host)
        self._editor_host_layout.setContentsMargins(0, 0, 0, 0)
        self._editor_host_layout.setSpacing(0)
        root.addWidget(self._editor_host)

        self._helper = ColorText(self)
        self._helper.setTextPixelSize(_DETAIL_PX)
        self._helper.setWordWrap(True)
        self._helper.setVisible(False)
        root.addWidget(self._helper)

        self._status_row = QWidget(self)
        status_layout = QHBoxLayout(self._status_row)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(_GAP)
        self._status_icon = _StatusIcon(self._status_row)
        self._status_icon.setVisible(False)
        self._status_label = ColorText(self._status_row)
        self._status_label.setTextPixelSize(_DETAIL_PX)
        self._status_label.setWordWrap(True)
        self._status_label.setVisible(False)
        status_layout.addWidget(self._status_icon, 0, _ICON_ALIGN)
        status_layout.addWidget(self._status_label, 1)
        self._status_row.setVisible(False)
        root.addWidget(self._status_row)

        self._slot = ContentSlot(self._editor_host, "field-editor")
        # 编辑器被外部销毁时**不动布局**（Qt 自己会把项摘掉，重入 = 0xC0000005）。
        self._slot.widgetChanged.connect(self._onEditorChanged)

        self._applyTheme()

    # -- 标题 ---------------------------------------------------------------

    def label(self) -> str:
        return self._label

    def setLabel(self, text_: str) -> None:  # noqa: N802
        value = "" if text_ is None else str(text_)
        if value == self._label:
            return
        self._label = value
        self._caption.setText(value)
        self.labelChanged.emit(value)
        self._applyTheme()

    def isRequired(self) -> bool:
        return self._required

    def setRequired(self, required: bool) -> None:  # noqa: N802
        required = bool(required)
        if required == self._required:
            return
        self._required = required
        self._required_mark.setVisible(required)
        self.requiredChanged.emit(required)
        self._applyTheme()

    # -- 辅助文字 -----------------------------------------------------------

    def helperText(self) -> str:
        return self._helper_text

    def setHelperText(self, text_: str) -> None:  # noqa: N802
        value = "" if text_ is None else str(text_)
        if value == self._helper_text:
            return
        self._helper_text = value
        self._helper.setText(value)
        self._helper.setVisible(bool(value))
        self.helperTextChanged.emit(value)
        self._applyTheme()

    # -- 校验状态 -----------------------------------------------------------

    def status(self) -> ElaFieldStatusType:
        return self._status

    def setStatus(self, status) -> None:  # noqa: N802
        """设校验状态（**不**改状态文字；两件事分开，宿主可以只改色或只改文案）。"""
        value = ElaFieldStatusType(status)
        if value == self._status:
            return
        self._status = value
        self.statusChanged.emit(value)
        self._applyStatus()

    def statusText(self) -> str:
        return self._status_text

    def setStatusText(self, text_: str) -> None:  # noqa: N802
        """设校验文案。空串会整行隐藏状态行（见模块 docstring 的规则 1）。"""
        value = "" if text_ is None else str(text_)
        if value == self._status_text:
            return
        self._status_text = value
        self._status_label.setText(value)
        self.statusTextChanged.emit(value)
        self._applyStatus()

    def statusColor(self) -> QColor:  # noqa: N802
        """当前状态的呈现色（``None_`` 状态给弱化文字色）。"""
        if self._status is ElaFieldStatusType.None_:
            return textMuted(currentMode())
        return statusColor(currentMode(), _ROLE_BY_STATUS[self._status])

    def hasStatusRow(self) -> bool:
        """状态行是否可见（= 有文案）。"""
        return bool(self._status_text)

    # -- 编辑器槽（走共享所有权协议） ------------------------------------------

    def editor(self) -> Optional[QWidget]:
        """当前编辑器（已被外部销毁时返回 ``None``）。"""
        return self._slot.widget()

    def editorOwnership(self) -> ElaWidgetOwnershipType:  # noqa: N802
        return self._slot.ownership()

    def setEditor(  # noqa: N802
        self, widget: Optional[QWidget], ownership=ElaWidgetOwnershipType.Borrowed
    ) -> bool:
        """挂载编辑器。返回是否成功（自挂 / 挂祖先会被拒）。

        :param ownership: 释放策略，见 ``_ownership.ElaWidgetOwnershipType``。默认
            ``Borrowed``（字段不管生命周期，宿主自己管）。
        """
        current = self._slot.widget()
        if current is not None:
            self._editor_host_layout.removeWidget(current)
        ok = self._slot.setWidget(widget, ownership)
        hosted = self._slot.widget()
        if hosted is not None:
            self._editor_host_layout.addWidget(hosted)
            self.setFocusProxy(hosted)
            # ``*`` 的快捷键指向编辑器（QLabel.setBuddy 是 QLabel 上的 API，
            # ColorText 是 ElaText 子类 → 是 QLabel → 可用）。
            self._caption.setBuddy(hosted)
        elif widget is None:
            self.setFocusProxy(None)
            self._caption.setBuddy(None)
        self.editorChanged.emit(hosted)
        return ok

    def takeEditor(self) -> Optional[QWidget]:  # noqa: N802
        """取回编辑器：**无父**返回、**从不删除**（哪怕策略是 ``Owned``）。"""
        current = self._slot.widget()
        if current is not None:
            self._editor_host_layout.removeWidget(current)
        widget = self._slot.takeWidget()
        self.setFocusProxy(None)
        self._caption.setBuddy(None)
        self.editorChanged.emit(None)
        return widget

    def releaseEditor(self, *, deleteOwned: bool = True) -> None:  # noqa: N802
        """按当前所有权策略处置编辑器（换编辑器 / 析构前用）。"""
        current = self._slot.widget()
        if current is not None:
            self._editor_host_layout.removeWidget(current)
        self._slot.releaseWidget(deleteOwned=deleteOwned)
        self.setFocusProxy(None)
        self._caption.setBuddy(None)
        self.editorChanged.emit(None)

    # -- 内部 ---------------------------------------------------------------

    def _onEditorChanged(self, widget) -> None:
        """``ContentSlot`` 发的 ``widgetChanged``。

        **收到 ``None``（编辑器被外部销毁）时绝不动布局** —— ``destroyed`` 是在
        ``~QWidget`` 内部发出的，此刻重入 QLayout 就是 0xC0000005。
        """
        if widget is None:
            return
        if self._editor_host_layout.indexOf(widget) < 0:
            self._editor_host_layout.addWidget(widget)

    def _applyStatus(self) -> None:
        has_text = bool(self._status_text)
        show_icon = has_text and self._status is not ElaFieldStatusType.None_
        self._status_row.setVisible(has_text)
        self._status_label.setVisible(has_text)
        self._status_icon.setVisible(show_icon)
        color = self.statusColor()
        self._status_label.setTextColor(color)
        self._status_icon.setIconColor(color)
        self._status_icon.setIcon(_STATUS_ICONS.get(self._status))

    def _onThemeChanged(self, mode) -> None:  # noqa: N802 (基类钩子)
        """主题切换：重刷三处颜色。

        ``ColorText`` 的颜色是**快照**，``ElaText`` 在 C++ 构造里连了
        ``themeModeChanged`` 会把 palette 刷回 BasicText，所以这里必须重设
        ``setTextColor``（不重设的话切完主题标题 / 说明就变成主题默认色了）。
        """
        super()._onThemeChanged(mode)
        self._applyTheme()

    def _applyTheme(self) -> None:  # noqa: N802
        mode = currentMode()
        self._caption.setTextColor(text(mode))
        self._helper.setTextColor(textMuted(mode))
        self._required_mark.setTextColor(statusColor(mode, ElaStatusRoleType.Error))
        self._applyStatus()
