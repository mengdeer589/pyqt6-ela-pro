"""
Windows 托盘图标（系统通知区）。

薄封装 ``QSystemTrayIcon``：管图标 / 提示 / 通知 / 右键菜单，**不管主窗口显隐**
（那是应用级宿主的事，见 ``example/tray_host.py``）。

三条实现约束：

1. **内部必须持 ``QSystemTrayIcon`` 引用**并重写 ``deleteLater()`` 先 ``hide()``
   再析构 —— 否则组件析构后托盘区会留一个灰图标（点不动也收不掉）；
2. **``notify()`` 必须守 ``QSystemTrayIcon.supportsMessages()``** —— Win7 等环境
   可能返回 ``False``，此时降级为不发气泡、改发 ``errorOccurred``，绝不崩；
3. **托盘由 Explorer 绘制，``QIcon`` 不吃 ``eTheme``** —— 组件不做主题自动适配
   （深浅两版图标由宿主准备），只在 ``themeModeChanged`` 时顺手 ``show()``
   复位：Explorer 重启会吞掉托盘图标，这是唯一的低成本自愈点。

右键菜单直接收 ``QMenu``（``ElaMenu`` 是其子类，天然兼容）；托盘菜单由系统绘制，
**不适用** ``_styles.py`` 里的自绘原语。
"""

from __future__ import annotations

from enum import IntEnum
from typing import Optional

from ._internal import is_deleted
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon
from PyQt6ElaWidgetTools import ElaThemeType, eTheme

#: 默认气泡通知时长（毫秒）
_DEFAULT_NOTIFY_MS = 3000


class ElaTrayIcon(QObject):
    """Windows 托盘图标。

    :param icon: 初始图标
    :param toolTip: 悬停提示
    :param parent: 父对象

    信号：

    * ``activated(QSystemTrayIcon.ActivationReason)`` —— 单击 / 双击 / 中键
    * ``messageClicked()`` —— 用户点开了气泡通知
    * ``visibilityChanged(bool)`` —— 托盘图标显隐变化
    * ``errorOccurred(str)`` —— 气泡通知不可用等降级情形
    """

    class ElaTrayStateType(IntEnum):
        """三态图标：托盘唯一值得由组件代劳的状态表达。"""

        Normal = 0
        Warning = 1
        Critical = 2

    #: 全部合法状态
    All = (ElaTrayStateType.Normal, ElaTrayStateType.Warning, ElaTrayStateType.Critical)

    #: 托盘被激活（单击 / 双击 / 中键 / 右键）
    activated = pyqtSignal(int)
    #: 用户点开了气泡通知
    messageClicked = pyqtSignal()
    #: 托盘图标显隐变化
    visibilityChanged = pyqtSignal(bool)
    #: 降级 / 失败提示（气泡不可用等）
    errorOccurred = pyqtSignal(str)

    def __init__(
        self,
        icon: Optional[QIcon] = None,
        toolTip: str = "",
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ElaTrayIcon")
        self._tray = QSystemTrayIcon(icon or QIcon(), self)
        self._tray.activated.connect(self._on_activated)
        self._tray.messageClicked.connect(self.messageClicked.emit)
        self._state_icons: dict = {}
        self._state = self.ElaTrayStateType.Normal
        self._visible = False
        if toolTip:
            self._tray.setToolTip(toolTip)
        # 必须把绑定方法**存下来**：disconnect 要拿到**同一个可调用对象**
        # （lambda / ``functools.partial`` 断不掉；bound method 也统一走这条，
        # 换绑定层 / 传自定义槽时不会失效）。
        self._theme_slot = self._onThemeChanged
        eTheme.themeModeChanged.connect(self._theme_slot)

    # -- 图标 / 提示 -------------------------------------------------------

    def setIcon(self, icon: QIcon) -> None:  # noqa: N802 (Qt 命名)
        """设置托盘图标。"""
        self._tray.setIcon(QIcon(icon))

    def icon(self) -> QIcon:
        """获取当前托盘图标。"""
        return QIcon(self._tray.icon())

    def setToolTip(self, text: str) -> None:  # noqa: N802 (Qt 命名)
        """设置悬停提示（托盘只能用原生提示，Ela 自绘 tooltip 对它无效）。"""
        self._tray.setToolTip(text or "")

    def toolTip(self) -> str:  # noqa: N802 (Qt 命名)
        """获取悬停提示。"""
        return self._tray.toolTip()

    # -- 菜单 --------------------------------------------------------------

    def setMenu(self, menu: Optional[QMenu]) -> None:  # noqa: N802 (Qt 命名)
        """设置右键菜单（传 ``ElaMenu`` 可得 Ela 外观；传 ``None`` 摘掉菜单）。"""
        self._tray.setContextMenu(menu)

    def menu(self) -> Optional[QMenu]:
        """获取当前右键菜单（未设置时为 ``None``）。"""
        return self._tray.contextMenu()

    # -- 三态 --------------------------------------------------------------

    def setIcons(  # noqa: N802 (Qt 命名)
        self,
        normal: Optional[QIcon] = None,
        warning: Optional[QIcon] = None,
        critical: Optional[QIcon] = None,
    ) -> None:
        """注册三态图标（``setState`` 据此切换；未注册的态回落到 normal）。"""
        if normal is not None:
            self._state_icons[self.ElaTrayStateType.Normal] = QIcon(normal)
        if warning is not None:
            self._state_icons[self.ElaTrayStateType.Warning] = QIcon(warning)
        if critical is not None:
            self._state_icons[self.ElaTrayStateType.Critical] = QIcon(critical)
        self._applyState()

    def setState(self, state: int) -> None:  # noqa: N802 (Qt 命名)
        """切换三态图标（非法值回落 ``Normal``）。"""
        value = self.ElaTrayStateType(state) if state in self.All else self.ElaTrayStateType.Normal
        if value == self._state:
            return
        self._state = value
        self._applyState()

    def state(self) -> int:  # noqa: N802 (Qt 命名)
        """获取当前状态。"""
        return self._state

    def _applyState(self) -> None:
        if is_deleted(self._tray):
            return
        icon = self._state_icons.get(self._state) or self._state_icons.get(
            self.ElaTrayStateType.Normal
        )
        if icon is not None:
            self._tray.setIcon(icon)

    # -- 通知 --------------------------------------------------------------

    def notify(
        self,
        title: str,
        text: str,
        icon: int = 0,  # noqa: N803 (Qt 命名)
        msecs: int = _DEFAULT_NOTIFY_MS,
    ) -> bool:
        """弹一条系统气泡通知。

        Win7 等环境可能不支持气泡（``supportsMessages()`` 为 ``False``），
        此时**不发也不抛**，改发 ``errorOccurred`` 并返回 ``False``。
        """
        if not QSystemTrayIcon.supportsMessages():
            self.errorOccurred.emit("当前系统不支持气泡通知（已跳过）")
            return False
        level = (
            QSystemTrayIcon.MessageIcon(icon)
            if icon in (0, 1, 2, 3)
            else QSystemTrayIcon.MessageIcon.Information
        )
        self._tray.showMessage(title or "", text or "", level, int(msecs))
        return True

    # -- 显隐 --------------------------------------------------------------

    def show(self) -> None:
        """显示托盘图标。"""
        if self._visible:
            return
        self._tray.show()
        self._visible = True
        self.visibilityChanged.emit(True)

    def hide(self) -> None:
        """隐藏托盘图标（幂等）。"""
        if not self._visible:
            return
        self._tray.hide()
        self._visible = False
        self.visibilityChanged.emit(False)

    def isVisible(self) -> bool:  # noqa: N802 (Qt 命名)
        """托盘图标当前是否处于显示态。"""
        return self._visible

    @staticmethod
    def isSystemTrayAvailable() -> bool:  # noqa: N802 (Qt 命名)
        """系统是否支持托盘（无桌面环境可能为 ``False``）。"""
        return QSystemTrayIcon.isSystemTrayAvailable()

    # -- 内部 --------------------------------------------------------------

    def _on_activated(self, reason) -> None:  # noqa: ANN001
        """转发为 int。

        PyQt6 的 ``QSystemTrayIcon.ActivationReason`` 是普通 ``Enum``（不是
        ``IntEnum``），直接 ``int(reason)`` 抛 TypeError —— 在 Qt 回调里就是
        0xC0000409 静默终止。
        """
        self.activated.emit(int(getattr(reason, "value", reason)))

    def _onThemeChanged(self, _mode: ElaThemeType.ThemeMode) -> None:  # noqa: N802
        # 托盘图标不吃主题色，这里只在切主题时顺手 show() 一次：
        # Explorer 重启会吞掉托盘图标，这是唯一的低成本自愈点。
        if self._visible and not is_deleted(self._tray):
            self._tray.show()

    def deleteLater(self) -> None:  # noqa: N802 (Qt 命名)
        # 必须先 hide()：否则析构后托盘区留一个点不动的灰图标
        if not is_deleted(self._tray):
            self._tray.hide()
        slot = self._theme_slot
        if slot is not None:
            try:
                eTheme.themeModeChanged.disconnect(slot)
            except (TypeError, RuntimeError):
                pass  # 信号已断
            # 置空保证幂等：deleteLater 可能被调用两次（宿主 + 测试 teardown）
            self._theme_slot = None
        super().deleteLater()


__all__ = ["ElaTrayIcon"]
