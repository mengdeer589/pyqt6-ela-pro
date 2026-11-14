"""幽灵下拉框：透明触发器 + 分组选项 + 弹层底部固定区。

派生自 ``ElaSearchBox``，自带搜索与拼音过滤。"""

from __future__ import annotations

from functools import partial
from typing import Optional, Union

from PyQt6.QtCore import (
    QEvent,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QTimer,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
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

from ._internal import (
    POPUP_FOOTER_OBJECT_NAME,
    hideComboboxPopup,
    is_deleted,
    safe_connect,
)
from ._motion import Duration, Easing, start_transition
from ._ownership import ElaWidgetOwnershipType, releaseWidget
from .combo_box import ElaSearchBox, _match_item, _split_keyword
from .ela_button import ElaButton

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


class _GhostFooterButton(ElaButton):
    """底栏按钮：复用 ElaButton 的 ``text`` 样式，只补 footer key。"""

    def __init__(
        self,
        text: str,
        icon: Optional[ElaIconType.IconName] = None,
        key: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(
            text,
            icon,
            14,
            variant="text",
            size="small",
            parent=parent,
        )
        self._key = key
        self.setBorderRadius(4)
        self.setFixedHeight(28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def icon(self) -> Optional[ElaIconType.IconName]:
        """返回按钮图标。"""
        return self._icon_name

    def setIcon(self, icon: Optional[ElaIconType.IconName]) -> None:  # noqa: N802
        """设置按钮图标（``ElaIconType.IconName``）。"""
        self.setElaIcon(icon, 14)

    def footerKey(self) -> str:
        """返回点击上报用的 key。"""
        return self._key


def _release_custom_widget(widget, ownership, original) -> None:
    """安全释放自定义控件（原 parent 可能已经先被销毁）。"""
    try:
        releaseWidget(widget, ownership, original)
    except (RuntimeError, TypeError):
        pass


def _release_footer_custom_on_destroy(widget, ownership, original, _obj=None) -> None:
    """footer 析构前把 Borrowed / Reparented 的自定义控件摘出来。
    用 ``partial`` 把控件信息带进槽：footer 析构时 PyQt 给的是新包装器
    （Python 属性已丢），不能靠 ``obj._custom_widget`` 读。
    """
    if widget is None or is_deleted(widget):
        return
    if ownership == ElaWidgetOwnershipType.Owned:
        # 本来就会随父控件删除，不要在这里再碰
        return
    _release_custom_widget(widget, ownership, original)


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
        self._custom_ownership = ElaWidgetOwnershipType.Borrowed
        self._custom_original_parent: Optional[QWidget] = None
        self._destroy_slot = None

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
        # 自定义控件约定排在按钮之后：先设 custom widget 再补按钮时，
        # 直接 addWidget 会把按钮塞到它后面（顺序反了）
        index = (
            self._row.indexOf(self._custom_widget)
            if self._custom_widget is not None
            else -1
        )
        if index >= 0:
            self._row.insertWidget(index, button)
        else:
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

    def _update_destroy_slot(self) -> None:
        """按当前控件 / 所有权重挂 footer 析构前的释放回调（partial 持控件引用）。"""
        if self._destroy_slot is not None:
            try:
                self.destroyed.disconnect(self._destroy_slot)
            except (TypeError, RuntimeError):
                pass
            self._destroy_slot = None
        if (
            self._custom_widget is not None
            and self._custom_ownership != ElaWidgetOwnershipType.Owned
        ):
            slot = partial(
                _release_footer_custom_on_destroy,
                self._custom_widget,
                self._custom_ownership,
                self._custom_original_parent,
            )
            # 用**局部名**连接：`self.destroyed.connect(self._x)` 是「永不触发的
            # 自绑槽」形状，机器守卫会拦（这里的槽是 partial + 模块级函数，功能上
            # 没问题，但别给守卫开后门）。
            self._destroy_slot = slot
            self.destroyed.connect(slot)

    def setCustomWidget(
        self,
        widget: Optional[QWidget],
        ownership=ElaWidgetOwnershipType.Borrowed,
    ) -> None:
        try:
            ownership = ElaWidgetOwnershipType(ownership)
        except ValueError:
            ownership = ElaWidgetOwnershipType.Borrowed

        if widget is self._custom_widget:
            # 同一个控件只换所有权策略，不重复 reparent
            self._custom_ownership = ownership
            self._update_destroy_slot()
            return

        if self._custom_widget is not None:
            old = self._custom_widget
            old_ownership = self._custom_ownership
            old_parent = self._custom_original_parent
            self._custom_widget = None
            self._custom_ownership = ElaWidgetOwnershipType.Borrowed
            self._custom_original_parent = None
            self._update_destroy_slot()
            self._row.removeWidget(old)
            _release_custom_widget(old, old_ownership, old_parent)

        if widget is not None:
            self._custom_original_parent = widget.parentWidget()
            self._custom_ownership = ownership
            if widget.isWindow():
                widget.setWindowFlags(widget.windowFlags() | Qt.WindowType.Widget)
            widget.setParent(self._row_widget)
            self._row.addWidget(widget, 1)
            self._custom_widget = widget
            self._update_destroy_slot()


class ElaGhostBox(ElaSearchBox):
    """幽灵下拉框：透明无边框触发器 + 分组选项 + 弹层底部固定区。
    继承 ``ElaSearchBox``，搜索框 / 拼音过滤 / ``items`` 均可用
    （``setSearchVisible(False)`` 可关）；触发器自绘，仅 hover / 展开时叠半透明色。
    """

    footerTriggered = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._placeholder: str = ""
        self._leading_icon: _IconSource = None
        self._popup_open: bool = False
        self._footer_pending: bool = False
        self._expand_icon_rotate: float = 0.0
        self._footer: Optional[_GhostPopupFooter] = None
        self._footer_close_on_click: bool = True

        # setItemDelegate 不转移所有权：必须保 Python 引用，否则 GC 后崩溃
        self._delegate = _GhostHeaderDelegate(self)
        self.setItemDelegate(self._delegate)
        # 与上游 ElaComboBox V3.0（35→30）的触发框同高，整套组合框族统一 30
        self.setFixedHeight(30)

        # 第三参（parent）**不传 self**：那会让目标销毁连带删掉仍在运行的动画，
        # 槽随后跑在已释放对象上 = 0xC0000005。守卫见
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
        self._footer_retry.timeout.connect(self._on_footer_retry)

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
        self._footer_pending = True
        self._sync_footer_visibility()
        super().showPopup()
        self._animate_expand(True)
        # 底栏必须等 C++ 的 400ms 动画把 view 放回布局后再插入：
        # 提前 addWidget 会让 C++ 的 addWidget(view()) 落到它后面，列表被挤走。
        self._footer_retry.start(450)

    def hidePopup(self) -> None:  # noqa: N802 (Qt 命名)
        """关闭弹窗。"""
        self._popup_open = False
        self._footer_pending = False
        self._footer_retry.stop()
        self._animate_expand(False)
        if hideComboboxPopup(self):
            return
        super().hidePopup()

    def _popup_extra_heights(self) -> tuple[int, int]:
        """返回搜索框 / 底栏占用的高度（底栏只在有内容时计入）。"""
        top, _ = super()._popup_extra_heights()
        footer = self._footer
        if footer is not None and footer.hasContent():
            return (top, footer.height() or footer.sizeHint().height() or 36)
        return (top, 0)

    # ── 底部固定区 ───────────────────────────────────────────────

    def addPopupFooterButton(  # noqa: N802 (Qt 命名)
        self,
        text: str,
        icon: Optional[ElaIconType.IconName] = None,
        key: str = "",
    ) -> QWidget:
        """在弹层底部固定区追加按钮，返回按钮句柄；``key`` 是点击时随
        ``footerTriggered`` 上报的标识，``icon`` 只接受 ``ElaIconType.IconName``。
        """
        footer = self._ensure_footer()
        button = _GhostFooterButton(text, icon, key, footer)
        safe_connect(
            button,
            "clicked",
            lambda _checked=False, k=key: self._on_footer_button_clicked(k),
            "ghost.footer",
        )
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

    def setPopupFooterWidget(  # noqa: N802
        self,
        widget: Optional[QWidget],
        *,
        ownership=ElaWidgetOwnershipType.Borrowed,
    ) -> None:
        """设置底栏自定义控件（放在按钮之后；传 ``None`` 移除）。
        ``ownership`` 与库内 ``_ownership`` 协议一致：默认 **Borrowed**
        ``Owned`` 才 ``deleteLater()``；``Reparented`` 放回原 parent。
        """
        footer = self._ensure_footer()
        footer.setCustomWidget(widget, ownership)
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
        if not footer.hasContent():
            footer.hide()
            return
        if self._popup_open and self._footer_pending:
            # 展开动画期间底栏不进布局、也不显示：等 _footer_retry 在动画结束后插入。
            footer.hide()
            return
        footer.show()
        if self._popup_open:
            self._attach_footer()

    def _attach_footer(self) -> None:
        footer = self._footer
        container = self._container
        if (
            footer is None
            or container is None
            or self._footer_pending
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

    def _attach_footer_after_view(self) -> bool:
        """view 已进布局时把底栏追加到它后面，返回是否已处理。
        只在 C++ 动画结束、view 被 ``addWidget`` 后调用；与 view 的加入落在同一
        趟布局激活里，列表不会被短暂撑高再压回。
        """
        footer = self._footer
        container = self._container
        view = self.view()
        if (
            footer is None
            or container is None
            or view is None
            or not footer.hasContent()
        ):
            return False
        layout = container.layout()
        if layout is None or layout.indexOf(view) < 0:
            return False
        self._footer_pending = False
        if layout.indexOf(footer) == -1:
            layout.addWidget(footer)
        footer.show()
        return True

    def _on_footer_retry(self) -> None:
        """C++ 展开动画结束后再插入底栏（提前插入会被 view 的 addWidget 挤到前面）。"""
        if self._footer is None or not self._footer.hasContent():
            self._footer_pending = False
            return
        if self._attach_footer_after_view():
            self._ensure_footer_last()

    def _ensure_footer_last(self) -> None:
        """把底栏幂等地挪到弹层布局末尾（view 由 C++ 动画结束后追加）。"""
        footer = self._footer
        container = self._container
        if (
            footer is None
            or container is None
            or self._footer_pending
            or not self._popup_open
            or not footer.hasContent()
        ):
            return
        layout = container.layout()
        if layout is None:
            return
        index = layout.indexOf(footer)
        if index == layout.count() - 1:
            footer.show()
            return
        if index >= 0:
            layout.removeWidget(footer)
        layout.addWidget(footer)
        footer.show()

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
            if self._footer_pending:
                # C++ 动画结束 addWidget(view()) 会投递 LayoutRequest；在同一趟
                # 布局激活前把底栏追加到 view 后面，避免 view 先撑满再被底栏压回。
                self._attach_footer_after_view()
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
