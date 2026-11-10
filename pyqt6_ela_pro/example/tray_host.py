"""托盘常驻宿主骨架（``pyqt6_ela_pro.example``）。"""

from __future__ import annotations

from typing import Optional, Sequence

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon
from PyQt6ElaWidgetTools import ElaMenu

from ..ela_tray_icon import ElaTrayIcon
from ..menu_item import ElaMenuItem
from ..tooltip_targets import set_action_tooltip

#: 分隔符哨兵（``setItems`` 里识别，作用于菜单项之间的空位）
SEPARATOR = "-"

TOGGLE_WINDOW_ID = "toggleWindow"
QUIT_ID = "quit"


class ElaTrayHost(QObject):
    """托盘常驻宿主：托盘图标 + 菜单 + 主窗口显隐 + 退出。"""

    actionTriggered = pyqtSignal(str)
    windowVisibilityRequested = pyqtSignal(bool)
    quitRequested = pyqtSignal()

    def __init__(
        self,
        window=None,  # noqa: ANN001 - 目标窗口（任意 QWidget）
        icon: Optional[QIcon] = None,
        toolTip: str = "",
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent or window)
        self._window = window
        self._items: list = []
        self._tray = ElaTrayIcon(icon or QIcon(), toolTip, self)
        # ElaMenu 的构造函数只接受 QWidget 父对象（QObject 不行），所以这里
        # 挂到目标窗口上；没有窗口时就是无父菜单，由 _menu_obj 持引用保活。
        self._menu_obj = ElaMenu(window) if window is not None else ElaMenu()
        self._tray.setMenu(self._menu_obj)
        self._tray.activated.connect(self._on_activated)

    def trayIcon(self) -> ElaTrayIcon:  # noqa: N802 (Qt 命名)
        """取底层托盘图标（三态 / 通知 / 显隐都走它）。"""
        return self._tray

    def setIcon(self, icon: QIcon) -> None:  # noqa: N802 (Qt 命名)
        """设置托盘图标。"""
        self._tray.setIcon(icon)

    def setToolTip(self, text: str) -> None:  # noqa: N802 (Qt 命名)
        """设置托盘悬停提示。"""
        self._tray.setToolTip(text)

    def show(self) -> None:
        """显示托盘图标。"""
        self._tray.show()

    def hide(self) -> None:
        """隐藏托盘图标。"""
        self._tray.hide()

    def setItems(self, items: Sequence) -> None:  # noqa: N802 (Qt 命名)
        """整体替换托盘菜单项（``"-"`` 为分隔符）。

        :param items: :class:`~pyqt6_ela_pro.menu_item.ElaMenuItem` 列表。
        """
        self._items = list(items or [])
        self._rebuild()

    def items(self) -> list:
        """菜单项快照。"""
        return list(self._items)

    def updateItem(self, actionId: str, **changes) -> None:  # noqa: N802
        """改某个菜单项的字段并重建菜单（用于回写文案 / 图标等状态）。"""
        updated = []
        for item in self._items:
            if isinstance(item, str) and item == SEPARATOR:
                updated.append(item)
            elif getattr(item, "id", None) == actionId:
                updated.append(
                    ElaMenuItem(
                        id=item.id,
                        label=changes.get("label", item.label),
                        icon=changes.get("icon", item.icon),
                        tooltip=changes.get("tooltip", item.tooltip),
                        enabled=changes.get("enabled", item.enabled),
                    )
                )
            else:
                updated.append(item)
        self._items = updated
        self._rebuild()

    def _rebuild(self) -> None:
        menu = self._menu()
        menu.clear()
        for item in self._items:
            if isinstance(item, str) and item == SEPARATOR:
                menu.addSeparator()
                continue
            if not item.enabled:
                continue
            if item.icon is None:
                action = menu.addAction(item.label)
            else:
                action = menu.addElaIconAction(item.icon, item.label)
            action.setData(item.id)
            if item.tooltip and item.tooltip != item.label:
                set_action_tooltip(action, item.tooltip)
            action.triggered.connect(
                lambda _checked=False, actionId=item.id: self._on_action(actionId)
            )
        self._tray.setMenu(menu)

    def _menu(self) -> ElaMenu:
        menu = self._tray.menu()
        if menu is None:
            menu = self._menu_obj
            self._tray.setMenu(menu)
        return menu

    def toggleWindow(self) -> None:
        """按当前可见性请求翻转主窗口显隐。"""
        self.requestWindowVisibility(not self.isWindowVisible())

    def requestWindowVisibility(self, visible: bool) -> None:  # noqa: N802
        """请求显示 / 隐藏主窗口（只发信号，宿主自己操作窗口）。"""
        self._syncToggleItem(visible)
        self.windowVisibilityRequested.emit(bool(visible))

    def isWindowVisible(self) -> bool:  # noqa: N802 (Qt 命名)
        """主窗口当前是否可见。"""
        return bool(self._window is not None and self._window.isVisible())

    def _syncToggleItem(self, visible: bool) -> None:
        """把「显隐主窗口」项的文案回写成与目标状态一致。"""
        for item in self._items:
            if isinstance(item, str) or item.id != TOGGLE_WINDOW_ID:
                continue
            label = "隐藏主窗口" if visible else "显示主窗口"
            if item.label != label:
                self.updateItem(TOGGLE_WINDOW_ID, label=label)
            return

    def quit(self) -> None:
        """请求退出：先发 ``quitRequested``（宿主可拦），再真正退出。"""
        self.quitRequested.emit()

    def shutdown(self) -> None:
        """真退出（``quitRequested`` 无人拦截时由宿主调用）。"""
        self._tray.hide()
        QApplication.quit()

    def _on_action(self, actionId: str) -> None:  # noqa: N802 (Qt 命名)
        if actionId == TOGGLE_WINDOW_ID:
            self.toggleWindow()
        elif actionId == QUIT_ID:
            self.quit()
        else:
            self.actionTriggered.emit(actionId)

    def _on_activated(self, reason) -> None:  # noqa: ANN001
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggleWindow()


__all__ = ["QUIT_ID", "SEPARATOR", "TOGGLE_WINDOW_ID", "ElaTrayHost"]
