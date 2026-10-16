"""
聊天工具栏组件（``pyqt6_ela_pro.chat``）。

实现件全部基于 Ela 原生组件封装：

- 纯图标按钮：:class:`ElaChatToolButton`（``ElaIconButton`` 子类，
  原生方形 / hover / ``IsSelected`` 选中态）；
- 带文字按钮：``ElaButton``；
- ``+`` 菜单：``ElaButton`` 触发 + ``ElaMenu`` 弹出（见 ``ElaChatInput``）。

:class:`ElaChatToolBar` 提供两段式（``leading`` / ``trailing``）容器与
三种追加入口（:meth:`addButton` / :meth:`addWidget` / :meth:`addSeparator`），
以及对应插入版本（``insertButton`` / ``insertWidget`` / ``insertSeparator``，
指定参照项插到它前面）和动态状态（``setItemVisible`` / ``setItemEnabled``）；
事件 ``toolTriggered(key)`` 与 ``toolToggled(key, checked)``。

命名规范与库内一致（``camelCase``）。
"""

from __future__ import annotations

from typing import Callable, Optional, Union

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QWidget
from PyQt6ElaWidgetTools import ElaIconButton, ElaIconType, ElaThemeType

from .._styles import setSolidBackground
from ..ela_button import ElaButton
from ..tooltips import ElaToolTipPositionType, set_tooltip
from ..widget_base import ElaThemeWidget
from ._theme import border_color

#: 普通模式间距
_SPACING = 6
#: 紧凑模式间距
_COMPACT_SPACING = 2
#: 分隔线高度
_SEPARATOR_HEIGHT = 16
#: 图标按钮默认边长
_ICON_BUTTON_SIZE = 28
#: 工具栏分区取值（左右两段）
_ZONES = ("leading", "trailing")


class ElaChatToolButton(ElaIconButton):
    """工具栏图标按钮（``ElaIconButton`` 子类，可选选中态）。"""

    #: 选中态变化（参数：是否选中）
    toggled = pyqtSignal(bool)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        icon: Optional[ElaIconType.IconName] = None,
        pixelSize: int = 16,
        size: int = _ICON_BUTTON_SIZE,
        tooltip: str = "",
        checkable: bool = False,
    ) -> None:
        super().__init__(
            icon or ElaIconType.IconName.CircleInfo,
            pixelSize,
            size,
            size,
            parent,
        )
        self.setBorderRadius(6)
        self._size = int(size)
        self._checkable = bool(checkable)
        self._checked = False
        if tooltip:
            self.setToolTip(tooltip)
            set_tooltip(self, tooltip, ElaToolTipPositionType.Top)
        self.clicked.connect(self._on_clicked)

    # -- 选中态 ------------------------------------------------------------

    def setCheckable(self, on: bool) -> None:
        """设置是否可选中。"""
        self._checkable = bool(on)
        if not self._checkable and self._checked:
            self.setChecked(False)

    def isCheckable(self) -> bool:
        """是否可选中。"""
        return self._checkable

    def setChecked(self, on: bool) -> None:
        """设置选中态（同步 ``ElaIconButton`` 的 ``IsSelected`` 视觉）。"""
        on = bool(on) and self._checkable
        if on == self._checked:
            return
        self._checked = on
        self.setIsSelected(on)
        self.toggled.emit(on)

    def isChecked(self) -> bool:
        """是否选中。"""
        return self._checked

    def _on_clicked(self) -> None:
        if self._checkable:
            self.setChecked(not self._checked)

    # -- 图标 --------------------------------------------------------------

    def isIconOnly(self) -> bool:
        """是否纯图标按钮（``ElaIconButton`` 恒为 True）。"""
        return True

    def setIcon(self, icon: ElaIconType.IconName) -> None:
        """设置图标。"""
        self.setAwesome(icon)

    def icon(self) -> ElaIconType.IconName:
        """获取图标。"""
        return self.getAwesome()

    def sizeHint(self) -> QSize:
        """返回固定方形尺寸。"""
        return QSize(self._size, self._size)


class ElaChatToolBar(ElaThemeWidget):
    """水平工具栏（leading / trailing 两段，支持自定义工具按钮）。"""

    #: 工具按钮被点击（参数：按钮 key）
    toolTriggered = pyqtSignal(str)
    #: 可选中的工具按钮状态变化（参数：按钮 key、选中态）
    toolToggled = pyqtSignal(str, bool)

    def __init__(self, parent: Optional[QWidget] = None, compact: bool = False) -> None:
        super().__init__(parent)
        self._compact = bool(compact)
        self._items: dict = {}
        self._separators: list = []
        #: 已登记的弹簧 ``(layout, spacer)``：``clear`` 要能一并移除
        self._stretches: list = []
        self._seq = 0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(_COMPACT_SPACING if self._compact else _SPACING)
        self._leading = QHBoxLayout()
        self._leading.setContentsMargins(0, 0, 0, 0)
        self._leading.setSpacing(layout.spacing())
        self._trailing = QHBoxLayout()
        self._trailing.setContentsMargins(0, 0, 0, 0)
        self._trailing.setSpacing(layout.spacing())
        layout.addLayout(self._leading)
        layout.addStretch(1)
        layout.addLayout(self._trailing)

        self._apply_theme()

    # -- 扩展入口 ----------------------------------------------------------

    def addButton(
        self,
        icon: Optional[ElaIconType.IconName] = None,
        text: str = "",
        tooltip: str = "",
        callback: Optional[Callable[[], None]] = None,
        key: Optional[str] = None,
        zone: str = "leading",
        checkable: bool = False,
        variant: str = "text",
        color: str = "default",
        size: int = _ICON_BUTTON_SIZE,
    ) -> QPushButton:
        """添加工具按钮，返回按钮句柄。

        有 ``text`` 时返回 ``ElaButton``（图标 + 文案）；无 ``text`` 时返回
        :class:`ElaChatToolButton`（``ElaIconButton``，正方形图标按钮）。

        :param key: 按钮标识（默认自动生成），用于 ``toolTriggered`` 信号；
            **显式传重复 key 抛 ``ValueError``**（此前静默覆盖登记，旧控件留在
            布局里但再也无法用公开 API 找到 / 移除）
        :param zone: ``"leading"``（左）或 ``"trailing"``（右）；非法值抛
            ``ValueError``（不再静默落到左侧）
        :param checkable: 是否可选中
        """
        zone = self._normalize_zone(zone)
        key = key or self._next_key("tool")
        if key in self._items:
            raise ValueError(f"工具栏 key 已存在：{key!r}（显式 key 不可重复）")
        if (text or "").strip():
            button = ElaButton(
                text=text,
                icon=icon,
                variant=variant,
                color=color,
                size="small",
                parent=self,
            )
            if tooltip:
                button.setToolTip(tooltip)
                set_tooltip(button, tooltip, ElaToolTipPositionType.Top)
            if checkable:
                button.setCheckable(True)
                button.toggled.connect(
                    lambda checked, k=key: self.toolToggled.emit(k, bool(checked))
                )
        else:
            button = ElaChatToolButton(
                icon=icon,
                tooltip=tooltip,
                checkable=checkable,
                size=size,
                parent=self,
            )
            button.toggled.connect(
                lambda checked, k=key: self.toolToggled.emit(k, bool(checked))
            )
        button.clicked.connect(lambda _checked=False, k=key: self.toolTriggered.emit(k))
        if callback is not None:
            button.clicked.connect(lambda _checked=False: callback())
        self._items[key] = button
        self._zone_layout(zone).addWidget(button)
        return button

    def addWidget(
        self, widget: QWidget, zone: str = "leading", key: Optional[str] = None
    ) -> QWidget:
        """插入任意控件（如 ``ElaToggleButton``、自定义组合控件）。

        :param zone: ``"leading"``（左）或 ``"trailing"``（右）；非法值抛
            ``ValueError``
        """
        zone = self._normalize_zone(zone)
        key = key or self._next_key("widget")
        if key in self._items:
            raise ValueError(f"工具栏 key 已存在：{key!r}（显式 key 不可重复）")
        widget.setParent(self)
        self._items[key] = widget
        self._zone_layout(zone).addWidget(widget)
        return widget

    def addSeparator(self, zone: str = "leading") -> QWidget:
        """添加分隔线（主题切换自动换色），返回分隔线句柄。

        需要**单独移除**时把返回值交给 :meth:`removeSeparator`（或通用的
        :meth:`removeItem`）；只想整段清空用 :meth:`clear`。

        :param zone: ``"leading"``（左）或 ``"trailing"``（右）；非法值抛
            ``ValueError``
        """
        zone = self._normalize_zone(zone)
        line = QWidget(self)
        line.setFixedSize(1, _SEPARATOR_HEIGHT)
        line.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._separators.append(line)
        self._zone_layout(zone).addWidget(line)
        self._apply_theme()
        return line

    def addStretch(self, zone: str = "trailing") -> None:
        """在指定分段末尾追加弹簧（非法 ``zone`` 抛 ``ValueError``）。

        弹簧会登记句柄，:meth:`clear` 能一并移除 —— 否则每次
        ``addStretch`` + ``clear`` 都会留下一个永久弹簧。
        """
        layout = self._zone_layout(self._normalize_zone(zone))
        layout.addStretch(1)
        item = layout.itemAt(layout.count() - 1) if layout.count() else None
        spacer = item.spacerItem() if item is not None else None
        if spacer is not None:
            self._stretches.append((layout, spacer))

    # -- 插入（在已有项之前） ----------------------------------------------

    def insertButton(
        self,
        before: Union[str, QWidget],
        icon: Optional[ElaIconType.IconName] = None,
        text: str = "",
        tooltip: str = "",
        callback: Optional[Callable[[], None]] = None,
        key: Optional[str] = None,
        checkable: bool = False,
        variant: str = "text",
        color: str = "default",
        size: int = _ICON_BUTTON_SIZE,
    ) -> QPushButton:
        """在已有项之前插入工具按钮（其余参数同 :meth:`addButton`）。

        :param before: 参照项（key 或已添加控件）；新按钮落在其所在分区，
            不存在时抛 ``ValueError``
        """
        reference = self._require_item(before)
        button = self.addButton(
            icon=icon,
            text=text,
            tooltip=tooltip,
            callback=callback,
            key=key,
            checkable=checkable,
            variant=variant,
            color=color,
            size=size,
            zone=self._zone_of(reference),
        )
        self._move_before(button, reference)
        return button

    def insertWidget(
        self,
        before: Union[str, QWidget],
        widget: QWidget,
        key: Optional[str] = None,
    ) -> QWidget:
        """在已有项之前插入任意控件（其余参数同 :meth:`addWidget`）。"""
        reference = self._require_item(before)
        item = self.addWidget(widget, zone=self._zone_of(reference), key=key)
        self._move_before(item, reference)
        return item

    def insertSeparator(self, before: Union[str, QWidget]) -> QWidget:
        """在已有项之前插入分隔线（落在参照项所在分区）。

        返回值同样可交给 :meth:`removeSeparator` 单独移除。
        """
        reference = self._require_item(before)
        line = self.addSeparator(zone=self._zone_of(reference))
        self._move_before(line, reference)
        return line

    # -- 显隐与启用 --------------------------------------------------------

    def setItemVisible(self, item: Union[str, QWidget], on: bool = True) -> bool:
        """显示 / 隐藏已添加项（接受 key 或控件）；不存在返回 ``False``。

        与 :meth:`removeItem` 的区别：隐藏不销毁控件，之后可再显示。
        """
        widget = self._resolve_item(item)
        if widget is None:
            return False
        widget.setVisible(bool(on))
        return True

    def itemVisible(self, item: Union[str, QWidget]) -> bool:
        """项是否显式可见（不受父链是否已显示影响）；不存在返回 ``False``。"""
        widget = self._resolve_item(item)
        return widget is not None and not widget.isHidden()

    def setItemEnabled(self, item: Union[str, QWidget], on: bool = True) -> bool:
        """启用 / 禁用已添加项（接受 key 或控件）；不存在返回 ``False``。"""
        widget = self._resolve_item(item)
        if widget is None:
            return False
        widget.setEnabled(bool(on))
        return True

    def itemEnabled(self, item: Union[str, QWidget]) -> bool:
        """项是否启用；不存在返回 ``False``。"""
        widget = self._resolve_item(item)
        return widget is not None and widget.isEnabled()

    # -- 查询与移除 --------------------------------------------------------

    def toolButton(self, key: str) -> Optional[QPushButton]:
        """按 key 获取工具按钮（不存在或非按钮返回 ``None``）。"""
        item = self._items.get(key)
        return item if isinstance(item, QPushButton) else None

    def item(self, key: str) -> Optional[QWidget]:
        """按 key 获取已添加控件。"""
        return self._items.get(key)

    def keys(self) -> list:
        """全部已添加项的 key 列表（按添加顺序）。"""
        return list(self._items.keys())

    def count(self) -> int:
        """已添加项数量（不含分隔线）。"""
        return len(self._items)

    def removeItem(self, item: Union[str, QWidget]) -> bool:
        """移除按钮 / 控件 / 分隔线（接受句柄或 key），返回是否移除成功。

        注意：会销毁控件（句柄随即失效）；只想临时隐藏请用
        :meth:`setItemVisible`。分隔线没有 key，用句柄移除（见
        :meth:`removeSeparator`）。
        """
        if isinstance(item, str):
            if item not in self._items:
                return False
            self._detach(self._items.pop(item))
            return True
        key = self._key_of(item)
        if key is not None:
            self._detach(self._items.pop(key))
            return True
        return self.removeSeparator(item)

    def removeSeparator(self, separator: QWidget) -> bool:
        """单独移除一条分隔线（接受 :meth:`addSeparator` / :meth:`insertSeparator`
        的返回值），返回是否移除成功。

        分隔线**没有 key**（不进 :meth:`keys` / :meth:`count` 的项空间），
        所以只能用句柄；与 :meth:`clear`（按分区整段清空）相对。
        """
        if separator not in self._separators:
            return False
        self._separators.remove(separator)
        self._detach(separator)
        return True

    def clear(self, zone: Optional[str] = None) -> None:
        """移除已添加的全部按钮与控件（``zone`` 为 ``None`` 时两段都清）。

        ``zone`` 非法时抛 ``ValueError``。
        """
        if zone is not None:
            zone = self._normalize_zone(zone)
        for key, widget in list(self._items.items()):
            if zone is not None and not self._in_zone(widget, zone):
                continue
            self._items.pop(key, None)
            self._detach(widget)
        for line in list(self._separators):
            if zone is not None and not self._in_zone(line, zone):
                continue
            self._separators.remove(line)
            self._detach(line)
        for layout, spacer in list(self._stretches):
            if zone is not None and layout is not self._zone_layout(zone):
                continue
            layout.removeItem(spacer)
            self._stretches.remove((layout, spacer))

    # -- 外观 --------------------------------------------------------------

    def setCompact(self, compact: bool) -> None:
        """切换紧凑模式（消息底部操作栏使用）。"""
        self._compact = bool(compact)
        spacing = _COMPACT_SPACING if self._compact else _SPACING
        self.layout().setSpacing(spacing)
        self._leading.setSpacing(spacing)
        self._trailing.setSpacing(spacing)

    def compact(self) -> bool:
        """是否紧凑模式。"""
        return self._compact

    # -- 内部 --------------------------------------------------------------

    def _next_key(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}-{self._seq}"

    def _zone_layout(self, zone: str) -> QHBoxLayout:
        return self._trailing if zone == "trailing" else self._leading

    @staticmethod
    def _normalize_zone(zone: str) -> str:
        """校验分区名；非法值抛 ``ValueError``（避免静默落到左侧）。"""
        if zone not in _ZONES:
            raise ValueError(
                f"未知工具栏分区：{zone!r}（可选：'leading' / 'trailing'）"
            )
        return zone

    def _resolve_item(self, item: Union[str, QWidget]) -> Optional[QWidget]:
        """接受 key 或控件，返回已登记控件 / 分隔线（未找到返回 ``None``）。"""
        if isinstance(item, str):
            return self._items.get(item)
        if self._key_of(item) is not None:
            return item
        return item if item in self._separators else None

    def _require_item(self, item: Union[str, QWidget]) -> QWidget:
        """同 :meth:`_resolve_item`，未找到抛 ``ValueError``。"""
        widget = self._resolve_item(item)
        if widget is None:
            raise ValueError(f"工具栏中不存在该项：{item!r}")
        return widget

    def _zone_of(self, widget: QWidget) -> str:
        """控件所在分区（不在右侧即视为左侧）。"""
        return "trailing" if self._in_zone(widget, "trailing") else "leading"

    def _move_before(self, widget: QWidget, reference: QWidget) -> None:
        """把已登记控件移到参照项之前（保持参照项所在分区）。"""
        layout = self._zone_layout(self._zone_of(reference))
        if layout.indexOf(widget) >= 0:
            layout.removeWidget(widget)
        else:
            self._zone_layout(self._zone_of(widget)).removeWidget(widget)
        index = layout.indexOf(reference)
        if index < 0:
            raise ValueError("参照项不在工具栏布局中")
        layout.insertWidget(index, widget)

    def _key_of(self, widget: QWidget) -> Optional[str]:
        for key, item in self._items.items():
            if item is widget:
                return key
        return None

    def _in_zone(self, widget: QWidget, zone: str) -> bool:
        layout = self._zone_layout(zone)
        for index in range(layout.count()):
            item = layout.itemAt(index)
            if item is not None and item.widget() is widget:
                return True
        return False

    def _detach(self, widget: QWidget) -> None:
        layout = widget.parentWidget().layout() if widget.parentWidget() else None
        if layout is not None:
            layout.removeWidget(widget)
        widget.setParent(None)
        widget.deleteLater()

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        super()._onThemeChanged(mode)
        self._apply_theme()

    def _apply_theme(self) -> None:
        color = border_color(self._theme_mode)
        for line in self._separators:
            setSolidBackground(line, color)
