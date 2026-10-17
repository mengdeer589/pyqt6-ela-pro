"""
幽灵下拉框组件。

透明无边框触发器 + 可分组选项 + 弹层底部固定区域，派生自 ``ElaSearchBox``
（因此自带弹窗搜索与拼音过滤）：

- **幽灵外观**：触发器完全自绘，无边框、无底色，hover / 展开态只有一层
  半透明叠加；可选前置图标与占位文本；
- **分组选项**：``addGroup(label)`` 插入分组标题行（不可选中、不可点击），
  搜索过滤时标题行随「组内是否还有可见项」自动显隐；
- **弹层底部固定区**：``addPopupFooterButton`` 追加多个固定按钮，
  ``setPopupFooterWidget`` 可放任意自定义控件；底栏停靠在列表下方，
  不随列表滚动移动。

用法::

    box = ElaGhostBox(parent)
    box.setLeadingIcon(ElaIconType.IconName.Gear)
    box.addGroup("Anthropic")
    box.addItems(["Claude 3.7 Sonnet", "Claude 3.5 Haiku"])
    box.addPopupFooterButton("管理模型", key="manage")
    box.footerTriggered.connect(on_footer)
"""

from __future__ import annotations

from functools import partial
from typing import Optional, Union

from PyQt6.QtCore import (
    QEvent,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QEnterEvent,
    QFont,
    QFontMetrics,
    QIcon,
    QPainter,
    QPaintEvent,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)
from PyQt6ElaWidgetTools import ElaIcon, ElaIconType, ElaThemeType, eTheme

from ._internal import POPUP_FOOTER_OBJECT_NAME, hideComboboxPopup
from ._motion import Duration, Easing, start_transition
from .combo_box import ElaSearchBox, _match_item, _split_keyword

_GROUP_HEADER_ROLE = Qt.ItemDataRole.UserRole + 100

_IconSource = Optional[Union[ElaIconType.IconName, QIcon, QPixmap]]


def _theme_color(name: ElaThemeType.ThemeColor) -> QColor:
    """按当前主题取色（每次绘制时现取，自动跟随亮 / 暗切换）。"""
    return eTheme.getThemeColor(eTheme.getThemeMode(), name)


def _icon_pixmap(icon: _IconSource, size: int, color: QColor) -> Optional[QPixmap]:
    """把 ``ElaIconType`` / ``QIcon`` / ``QPixmap`` 统一转成指定尺寸的位图。"""
    if icon is None:
        return None
    if isinstance(icon, QPixmap):
        return icon.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    if isinstance(icon, QIcon):
        return icon.pixmap(size, size)
    try:
        ela_icon = ElaIcon.getInstance().getElaIcon(icon, color)  # type: ignore[arg-type]
    except (TypeError, RuntimeError):
        return None
    if ela_icon is None:
        return None
    return ela_icon.pixmap(size, size)


class _GhostHeaderDelegate(QStyledItemDelegate):
    """分组标题行绘制：弱化小字；普通行仍交给 Ela 原生样式。

    注意：``setItemDelegate`` 不转移所有权，宿主必须保 Python 引用。
    """

    _HEADER_FONT_SIZE = 11

    def paint(  # noqa: N802 (Qt 命名)
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index,
    ) -> None:
        if not index.data(_GROUP_HEADER_ROLE):
            super().paint(painter, option, index)
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        font = QFont(option.font)
        font.setPixelSize(self._HEADER_FONT_SIZE)
        painter.setFont(font)
        painter.setPen(_theme_color(ElaThemeType.ThemeColor.BasicTextCategory))
        rect = QRect(option.rect)
        rect.setLeft(rect.left() + 15)
        rect.setRight(rect.right() - 15)
        painter.drawText(
            rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            str(index.data(Qt.ItemDataRole.DisplayRole) or ""),
        )
        painter.restore()


class _GhostSeparator(QWidget):
    """1px 主题色分隔线。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(1)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 (Qt 命名)
        painter = QPainter(self)
        painter.fillRect(
            self.rect(), _theme_color(ElaThemeType.ThemeColor.BasicBaseLine)
        )


class _GhostFooterButton(QWidget):
    """底栏按钮：自绘、无焦点，hover 显示半透明底色。"""

    clicked = pyqtSignal()

    def __init__(
        self,
        text: str,
        icon: _IconSource = None,
        key: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._text = text
        self._icon = icon
        self._key = key
        self._hovered = False
        self.setFixedHeight(28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)

    def text(self) -> str:
        """返回按钮文字。"""
        return self._text

    def setText(self, text: str) -> None:
        """设置按钮文字。"""
        if text != self._text:
            self._text = text
            self.updateGeometry()
            self.update()

    def icon(self) -> _IconSource:
        """返回按钮图标。"""
        return self._icon

    def setIcon(self, icon: _IconSource) -> None:
        """设置按钮图标（``ElaIconType.IconName`` / ``QIcon`` / ``QPixmap``）。"""
        self._icon = icon
        self.updateGeometry()
        self.update()

    def footerKey(self) -> str:
        """返回点击上报用的 key。"""
        return self._key

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt 命名)
        width = 16
        if self._icon is not None:
            width += 14 + 6
        width += QFontMetrics(self.font()).horizontalAdvance(self._text)
        return QSize(width, self.height())

    def enterEvent(self, _event: QEnterEvent) -> None:  # noqa: N802 (Qt 命名)
        self._hovered = True
        self.update()

    def leaveEvent(self, _event: QEvent) -> None:  # noqa: N802 (Qt 命名)
        self._hovered = False
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.clicked.emit()
        event.accept()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 (Qt 命名)
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
        )
        text_color = (
            _theme_color(ElaThemeType.ThemeColor.BasicText)
            if self.isEnabled()
            else _theme_color(ElaThemeType.ThemeColor.BasicTextDisable)
        )
        if self.isEnabled() and self._hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_theme_color(ElaThemeType.ThemeColor.BasicHoverAlpha))
            painter.drawRoundedRect(QRectF(self.rect()), 4, 4)

        rect = self.rect()
        pixmap = _icon_pixmap(self._icon, 14, text_color)
        text_width = QFontMetrics(self.font()).horizontalAdvance(self._text)
        content_width = text_width + (pixmap.width() + 6 if pixmap is not None else 0)
        # 底栏按钮会被布局拉伸到整行宽：内容整体水平居中
        x = rect.left() + max(0, (rect.width() - content_width) // 2)
        if pixmap is not None:
            painter.drawPixmap(
                x, rect.top() + (rect.height() - pixmap.height()) // 2, pixmap
            )
            x += pixmap.width() + 6
        painter.setPen(text_color)
        painter.drawText(
            QRect(x, rect.top(), max(0, rect.right() - x), rect.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self._text,
        )


class _GhostPopupFooter(QWidget):
    """弹层底部固定区：1px 分隔线 + 一行按钮 / 自定义控件。"""

    _ROW_HEIGHT = 35

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName(POPUP_FOOTER_OBJECT_NAME)
        self.setFixedHeight(1 + self._ROW_HEIGHT)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(_GhostSeparator(self))

        self._row_widget = QWidget(self)
        self._row_widget.setFixedHeight(self._ROW_HEIGHT)
        self._row = QHBoxLayout(self._row_widget)
        self._row.setContentsMargins(6, 3, 6, 4)
        self._row.setSpacing(4)
        outer.addWidget(self._row_widget)

        self._buttons: list[_GhostFooterButton] = []
        self._custom_widget: Optional[QWidget] = None

    def hasContent(self) -> bool:
        """底栏是否还有内容（按钮或自定义控件）。"""
        return bool(self._buttons) or self._custom_widget is not None

    def buttons(self) -> list[_GhostFooterButton]:
        """返回当前全部底栏按钮。"""
        return list(self._buttons)

    def findButton(self, item: Union[QWidget, str]) -> Optional[_GhostFooterButton]:
        """按按钮句柄或 key 查找按钮。"""
        if isinstance(item, _GhostFooterButton):
            return item if item in self._buttons else None
        if isinstance(item, str):
            for button in self._buttons:
                if button.footerKey() == item:
                    return button
        return None

    def addButton(self, button: _GhostFooterButton) -> None:
        self._buttons.append(button)
        button.setParent(self._row_widget)
        self._row.addWidget(button)

    def removeButton(self, button: _GhostFooterButton) -> bool:
        if button not in self._buttons:
            return False
        self._buttons.remove(button)
        self._row.removeWidget(button)
        button.setParent(None)
        button.deleteLater()
        return True

    def customWidget(self) -> Optional[QWidget]:
        """返回当前自定义底栏控件。"""
        return self._custom_widget

    def setCustomWidget(self, widget: Optional[QWidget]) -> None:
        if self._custom_widget is not None and self._custom_widget is not widget:
            old = self._custom_widget
            self._custom_widget = None
            self._row.removeWidget(old)
            old.setParent(None)
            old.deleteLater()
        self._custom_widget = widget
        if widget is not None:
            widget.setParent(self._row_widget)
            self._row.addWidget(widget, 1)


class ElaGhostBox(ElaSearchBox):
    """幽灵下拉框（透明无边框 + 分组选项 + 弹层底部固定区）。

    继承 ``ElaSearchBox``，弹窗顶部搜索框、拼音过滤、``items`` 属性等能力
    全部可用（搜索框可用 ``setSearchVisible(False)`` 关闭）。触发器完全自绘：
    无边框、无底色，hover / 展开态只有半透明叠加。

    :param parent: 父级 widget。
    :type parent: QWidget, optional

    Example::

        box = ElaGhostBox(parent)
        box.addGroup("Anthropic")
        box.addItems(["Claude 3.7 Sonnet", "Claude 3.5 Haiku"])
        box.addPopupFooterButton("管理模型", key="manage")
        box.footerTriggered.connect(lambda key: print("footer:", key))
    """

    footerTriggered = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._placeholder: str = ""
        self._leading_icon: _IconSource = None
        self._popup_open: bool = False
        self._expand_icon_rotate: float = 0.0
        self._footer: Optional[_GhostPopupFooter] = None
        self._footer_close_on_click: bool = True

        # setItemDelegate 不转移所有权：必须保 Python 引用，否则 GC 后崩溃
        self._delegate = _GhostHeaderDelegate(self)
        self.setItemDelegate(self._delegate)
        # 与上游 ElaComboBox V3.0（35→30）的触发框同高，整套组合框族统一 30
        self.setFixedHeight(30)

        # 第三参（parent）**不传 self**：让动画成为「自己动的对象」的子对象，等于让
        # 目标销毁连带销毁仍在运行的动画，针对它的 finished 发射可能还挂在队列里 ——
        # 槽随后跑在已释放对象上（shake_window 实测 0xC0000005）。守卫见
        # tests/regression/test_animation_parenting.py。
        self._expand_animation = QPropertyAnimation(self, b"expandIconRotate")
        self._expand_animation.setEasingCurve(Easing.type_name(Easing.Standard))

        self._container = self.findChild(QWidget, "ElaComboBoxContainer")
        view = self.view()
        self._viewport = view.viewport() if view is not None else None
        if self._viewport is not None:
            self._viewport.installEventFilter(self)
        if self._container is not None:
            self._container.installEventFilter(self)

        # 底栏排到 view 之后的兜底定时器（挂在 self 上，随控件销毁）
        self._footer_retry = QTimer(self)
        self._footer_retry.setSingleShot(True)
        self._footer_retry.timeout.connect(self._ensure_footer_last)

    # ── 外观 ─────────────────────────────────────────────────────

    def setPlaceholderText(self, text: str) -> None:  # noqa: N802 (Qt 命名)
        """设置未选中时的占位文本。"""
        self._placeholder = text
        self.update()

    def placeholderText(self) -> str:  # noqa: N802 (Qt 命名)
        """返回占位文本。"""
        return self._placeholder

    def setLeadingIcon(self, icon: _IconSource) -> None:  # noqa: N802 (Qt 命名)
        """设置触发器前置图标（``ElaIconType.IconName`` / ``QIcon`` / ``QPixmap``）。"""
        self._leading_icon = icon
        self.update()

    def leadingIcon(self) -> _IconSource:  # noqa: N802 (Qt 命名)
        """返回触发器前置图标。"""
        return self._leading_icon

    def _onThemeChanged(self, mode=None) -> None:  # type: ignore[override]
        # 不调 super()：MRO 上的 _ThemeAwareMixin._onThemeChanged 是空实现
        self._applySearchEditPalette()
        self.update()
        if self._footer is not None:
            self._footer.update()

    @pyqtProperty(float)
    def expandIconRotate(self) -> float:
        return self._expand_icon_rotate

    @expandIconRotate.setter
    def expandIconRotate(self, rotate: float) -> None:
        if self._expand_icon_rotate != rotate:
            self._expand_icon_rotate = rotate
            self.update()

    # ── 分组建模 ─────────────────────────────────────────────────

    def addGroup(self, label: str) -> int:
        """追加一个分组标题行（不可选中、不可点击），返回其行号。"""
        super().addItem(str(label))
        row = self.count() - 1
        model = self.model()
        if model is not None:
            item = model.item(row) if hasattr(model, "item") else None
            if item is not None:
                item.setFlags(Qt.ItemFlag.NoItemFlags)
            model.setData(model.index(row, 0), True, _GROUP_HEADER_ROLE)
        # 空组合框加首行时 Qt 会把标题行设为当前项，这里复位
        if self.currentIndex() == row:
            super().setCurrentIndex(-1)
        self.update()
        return row

    def isGroupHeader(self, row: int) -> bool:  # noqa: N802 (Qt 命名)
        """判断某一行是否为分组标题行。"""
        if not 0 <= row < self.count():
            return False
        model = self.model()
        if model is None:
            return False
        return bool(model.index(row, 0).data(_GROUP_HEADER_ROLE))

    def groupOf(self, row: int) -> Optional[str]:  # noqa: N802 (Qt 命名)
        """返回某一行所属分组的标题；行本身是标题时返回它自己；无分组返回 ``None``。"""
        if not 0 <= row < self.count():
            return None
        if self.isGroupHeader(row):
            return self.itemText(row)
        for i in range(row - 1, -1, -1):
            if self.isGroupHeader(i):
                return self.itemText(i)
        return None

    def groupLabels(self) -> list[str]:  # noqa: N802 (Qt 命名)
        """返回所有分组标题文本（按行序）。"""
        return [self.itemText(i) for i in range(self.count()) if self.isGroupHeader(i)]

    @property
    def items(self) -> list[str]:
        """返回所有可选（不含分组标题）选项文本。"""
        return [
            self.itemText(i) for i in range(self.count()) if not self.isGroupHeader(i)
        ]

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802 (Qt 命名)
        """设置当前项；落到分组标题行时自动跳到邻近的可选项。"""
        if self.isGroupHeader(index):
            index = self._nearest_item_row(index)
        super().setCurrentIndex(index)

    def setCurrentText(self, text: str) -> None:  # noqa: N802 (Qt 命名)
        """按文本设置当前项；标题文本不参与选择。"""
        for i in range(self.count()):
            if not self.isGroupHeader(i) and self.itemText(i) == text:
                super().setCurrentIndex(i)
                return
        if self.findText(text) < 0:
            super().setCurrentText(text)

    def _nearest_item_row(self, row: int) -> int:
        for i in range(row + 1, self.count()):
            if not self.isGroupHeader(i):
                return i
        for i in range(row - 1, -1, -1):
            if not self.isGroupHeader(i):
                return i
        return -1

    # ── 弹层 ─────────────────────────────────────────────────────

    def showPopup(self) -> None:  # noqa: N802 (Qt 命名)
        """显示弹窗（搜索框 + 列表 + 底部固定区）。"""
        if self.count() == 0:
            return
        self._popup_open = True
        self._sync_footer_visibility()
        super().showPopup()
        self._attach_footer()
        self._animate_expand(True)
        self._footer_retry.start(450)

    def hidePopup(self) -> None:  # noqa: N802 (Qt 命名)
        """关闭弹窗。"""
        self._popup_open = False
        self._animate_expand(False)
        if hideComboboxPopup(self):
            return
        super().hidePopup()

    # ── 底部固定区 ───────────────────────────────────────────────

    def addPopupFooterButton(  # noqa: N802 (Qt 命名)
        self,
        text: str,
        icon: _IconSource = None,
        key: str = "",
    ) -> QWidget:
        """在弹层底部固定区追加按钮，返回按钮句柄；``key`` 是点击时随
        ``footerTriggered`` 上报的标识。
        """
        footer = self._ensure_footer()
        button = _GhostFooterButton(text, icon, key, footer)
        button.clicked.connect(partial(self._on_footer_button_clicked, key))
        footer.addButton(button)
        self._sync_footer_visibility()
        return button

    def removePopupFooterButton(self, item: Union[QWidget, str]) -> bool:  # noqa: N802
        """按按钮句柄或 key 移除底栏按钮，返回是否移除成功（按钮会被销毁）。"""
        footer = self._footer
        if footer is None:
            return False
        button = footer.findButton(item)
        if button is None:
            return False
        footer.removeButton(button)
        self._sync_footer_visibility()
        return True

    def setPopupFooterButtonVisible(  # noqa: N802 (Qt 命名)
        self, item: Union[QWidget, str], on: bool = True
    ) -> bool:
        """按按钮句柄或 key 显示 / 隐藏底栏按钮，返回是否命中。"""
        footer = self._footer
        if footer is None:
            return False
        button = footer.findButton(item)
        if button is None:
            return False
        button.setVisible(on)
        return True

    def setPopupFooterWidget(self, widget: Optional[QWidget]) -> None:  # noqa: N802
        """设置底栏自定义控件（放在按钮之后；传 ``None`` 移除，旧控件会被销毁）。"""
        footer = self._ensure_footer()
        footer.setCustomWidget(widget)
        self._sync_footer_visibility()

    def popupFooter(self) -> QWidget:  # noqa: N802 (Qt 命名)
        """返回弹层底部固定区容器（无内容时不会出现在弹层里）。"""
        return self._ensure_footer()

    def setPopupFooterCloseOnClick(self, on: bool = True) -> None:  # noqa: N802
        """设置点击底栏按钮后是否先关闭弹窗（默认 ``True``）。"""
        self._footer_close_on_click = on

    def popupFooterCloseOnClick(self) -> bool:  # noqa: N802 (Qt 命名)
        """返回点击底栏按钮后是否先关闭弹窗。"""
        return self._footer_close_on_click

    def _ensure_footer(self) -> _GhostPopupFooter:
        if self._footer is None:
            parent = self._container if self._container is not None else self
            self._footer = _GhostPopupFooter(parent)
            self._footer.hide()
        return self._footer

    def _sync_footer_visibility(self) -> None:
        footer = self._footer
        if footer is None:
            return
        if footer.hasContent():
            footer.show()
        else:
            footer.hide()
        if self._popup_open:
            self._attach_footer()

    def _attach_footer(self) -> None:
        footer = self._footer
        container = self._container
        if (
            footer is None
            or container is None
            or not footer.hasContent()
            or footer.isHidden()
        ):
            return
        layout = container.layout()
        if layout is None:
            return
        if layout.indexOf(footer) == -1:
            layout.addWidget(footer)
        self._ensure_footer_last()

    def _ensure_footer_last(self) -> None:
        """把底栏幂等地挪到弹层布局末尾（view 由 C++ 动画结束后追加）。"""
        footer = self._footer
        container = self._container
        if (
            footer is None
            or container is None
            or not self._popup_open
            or not footer.hasContent()
            or footer.isHidden()
        ):
            return
        layout = container.layout()
        if layout is None:
            return
        index = layout.indexOf(footer)
        if index == layout.count() - 1:
            return
        if index >= 0:
            layout.removeWidget(footer)
        layout.addWidget(footer)

    def _on_footer_button_clicked(self, key: str) -> None:
        if self._footer_close_on_click:
            self.hidePopup()
        self.footerTriggered.emit(key)

    # ── 过滤 / 事件 ──────────────────────────────────────────────

    def _apply_row_filter(self, keyword: str) -> None:
        """过滤列表：普通行按关键词匹配，标题行随组内可见项显隐。"""
        view = self.view()
        if view is None:
            return
        tokens = _split_keyword(keyword)
        if not tokens:
            self._reset_row_filter()
            return
        count = self.count()
        hidden = [False] * count
        header_rows: list[int] = []
        for i in range(count):
            if self.isGroupHeader(i):
                hidden[i] = True
                header_rows.append(i)
            else:
                hidden[i] = not _match_item(
                    self.itemText(i), tokens, self._pinyin_cache
                )
        for idx, header in enumerate(header_rows):
            end = header_rows[idx + 1] if idx + 1 < len(header_rows) else count
            hidden[header] = all(hidden[i] for i in range(header + 1, end))

        first_match = -1
        for i in range(count):
            if not hidden[i] and not self.isGroupHeader(i):
                first_match = i
                break
        for i in range(count):
            if view.isRowHidden(i) != hidden[i]:
                view.setRowHidden(i, hidden[i])
        if first_match >= 0:
            model = self.model()
            if model is not None:
                view.scrollTo(model.index(first_match, 0))

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt 命名)
        event_type = event.type()
        if obj is self._viewport and event_type in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseButtonDblClick,
        ):
            view = self.view()
            if view is not None:
                index = view.indexAt(event.position().toPoint())
                if index.isValid() and self.isGroupHeader(index.row()):
                    # 禁用行点击会被 QComboBox 容器当成「选中当前高亮项」，
                    # 必须在这里吞掉
                    return True
        elif obj is self._container and event_type == QEvent.Type.LayoutRequest:
            self._ensure_footer_last()
        return super().eventFilter(obj, event)

    def _animate_expand(self, expanded: bool) -> None:
        self._expand_animation.setStartValue(self._expand_icon_rotate)
        self._expand_animation.setEndValue(-180.0 if expanded else 0.0)
        start_transition(self._expand_animation, Duration.Fast)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 (Qt 命名)
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        enabled = self.isEnabled()
        rect = self.rect()
        radius = self.getBorderRadius()

        if enabled and (self._popup_open or self.underMouse()):
            color = (
                _theme_color(ElaThemeType.ThemeColor.BasicSelectedAlpha)
                if self._popup_open
                else _theme_color(ElaThemeType.ThemeColor.BasicHoverAlpha)
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(rect), radius, radius)

        text_color = (
            _theme_color(ElaThemeType.ThemeColor.BasicText)
            if enabled
            else _theme_color(ElaThemeType.ThemeColor.BasicTextDisable)
        )

        content_left = rect.left() + 8
        chevron_rect = QRect(rect.right() - 24, rect.top(), 20, rect.height())
        text = self.currentText()
        is_placeholder = False
        if self.currentIndex() < 0 or not text:
            text = self._placeholder
            is_placeholder = bool(text)

        x = content_left
        pixmap = _icon_pixmap(self._leading_icon, 16, text_color)
        if pixmap is not None:
            painter.setOpacity(1.0 if (self._popup_open or self.underMouse()) else 0.6)
            painter.drawPixmap(
                x, rect.top() + (rect.height() - pixmap.height()) // 2, pixmap
            )
            painter.setOpacity(1.0)
            x += pixmap.width() + 6

        painter.setPen(
            _theme_color(ElaThemeType.ThemeColor.BasicTextCategory)
            if is_placeholder
            else text_color
        )
        text_rect = QRect(
            x, rect.top(), max(0, chevron_rect.left() - 4 - x), rect.height()
        )
        elided = QFontMetrics(self.font()).elidedText(
            text, Qt.TextElideMode.ElideRight, text_rect.width()
        )
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            elided,
        )

        arrow = _icon_pixmap(ElaIconType.IconName.AngleDown, 17, text_color)
        if arrow is not None:
            painter.save()
            painter.translate(
                chevron_rect.center().x() + 0.5, chevron_rect.center().y() + 0.5
            )
            painter.rotate(self._expand_icon_rotate)
            painter.translate(-arrow.width() / 2, -arrow.height() / 2)
            painter.drawPixmap(0, 0, arrow)
            painter.restore()
