"""划词动作条浮窗（``pyqt6_ela_pro.selection_assistant``）。

:class:`ElaSelectionPopup` 是划词助手弹出的横向动作条：

- 无边框 / 置顶 / 不接受焦点（``WA_ShowWithoutActivating``），不抢源应用
  焦点、不塌陷选区；
- 按 :class:`~pyqt6_ela_pro.menu_item.ElaMenuItem`
  列表渲染按钮（紧凑模式仅图标，否则图标 + 文字），主题感知；
- :meth:`popupAt` 以落点为锚（默认右下方偏移），越界自动翻转并收敛到
  屏幕工作区；
- 点击按钮后自动隐藏并发出 ``actionTriggered(actionId)``。

命名规范与库内一致（``camelCase``）。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from PyQt6.QtCore import QPoint, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QWidget
from PyQt6ElaWidgetTools import ElaIconButton, ElaThemeType, eTheme

from .._styles import SHADOW_MARGIN, paintOverlayShadow
from ..ela_button import ElaButton
from ..tooltips import ElaToolTipPositionType, set_tooltip
from ..widget_base import ElaThemeWidget
from ..menu_item import ElaMenuItem

#: 圆角半径
_RADIUS = 8
#: 水平 / 垂直内边距
_PADDING_H = 6
_PADDING_V = 4
#: 紧凑模式图标按钮边长
_ICON_BUTTON_SIZE = 26
#: 默认锚点偏移（落点 → 弹窗左上角）
_DEFAULT_OFFSET = QPoint(12, 16)


class ElaSelectionPopup(ElaThemeWidget):
    """划词动作条（可独立复用；组件内部由助手驱动）。"""

    #: 点击动作（参数：动作 id）
    actionTriggered = pyqtSignal(str)
    #: 弹窗隐藏
    hidden = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._theme_mode = eTheme.getThemeMode()
        self._actions: List[ElaMenuItem] = []
        self._buttons: Dict[str, QWidget] = {}
        self._compact = False
        self._offset = QPoint(_DEFAULT_OFFSET)
        #: 最近一次 popupAt 的锚点（可见期间重建 / 改尺寸后据此重新收敛屏幕）
        self._anchor: Optional[QPoint] = None

        self._layout = QHBoxLayout(self)
        # 阴影边距统一预留（paintEvent 里 translate 同值；别各写魔数）
        self._layout.setContentsMargins(
            _PADDING_H + SHADOW_MARGIN,
            _PADDING_V + SHADOW_MARGIN,
            _PADDING_H + SHADOW_MARGIN,
            _PADDING_V + SHADOW_MARGIN,
        )
        self._layout.setSpacing(2)
        self.hide()

    # -- 配置 --------------------------------------------------------------

    def setActions(self, actions: List[ElaMenuItem]) -> None:
        """整体替换动作列表（仅渲染 ``enabled`` 的动作）。"""
        self._actions = list(actions or [])
        self._rebuild()

    def actions(self) -> List[ElaMenuItem]:
        """动作列表快照。"""
        return list(self._actions)

    def setCompactMode(self, on: bool) -> None:
        """紧凑模式：仅图标不显示文字。"""
        on = bool(on)
        if on == self._compact:
            return
        self._compact = on
        self._rebuild()

    def compactMode(self) -> bool:
        """是否紧凑模式。"""
        return self._compact

    def setOffset(self, offset: QPoint) -> None:
        """设置锚点偏移（落点 → 弹窗左上角，默认 (12, 16)）。"""
        self._offset = QPoint(offset)

    def offset(self) -> QPoint:
        """锚点偏移。"""
        return QPoint(self._offset)

    def button(self, actionId: str) -> Optional[QWidget]:
        """获取指定动作的按钮（不存在返回 ``None``）。"""
        return self._buttons.get(actionId)

    def hasActions(self) -> bool:
        """是否存在可显示的动作。"""
        return bool(self._buttons)

    # -- 显示 --------------------------------------------------------------

    def popupAt(self, pos: QPoint) -> None:
        """在指定全局坐标附近弹出（越界翻转并收敛到屏幕工作区）。"""
        if not self.hasActions():
            return
        self._anchor = QPoint(pos)
        self.adjustSize()
        width, height = self.width(), self.height()
        screen = QApplication.screenAt(pos) or QApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else None

        x = pos.x() + self._offset.x()
        y = pos.y() + self._offset.y()
        if area is not None:
            if x + width > area.right() + 1:
                x = pos.x() - width - self._offset.x()
            if y + height > area.bottom() + 1:
                y = pos.y() - height - self._offset.y()
            x = max(area.left(), min(x, area.right() - width + 1))
            y = max(area.top(), min(y, area.bottom() - height + 1))
        self.move(x, y)
        self.show()
        self.raise_()

    # -- 内部 --------------------------------------------------------------

    def _rebuild(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self._buttons.clear()
        for action in self._actions:
            if not action.enabled:
                continue
            button = self._build_button(action)
            self._layout.addWidget(button)
            # 新建子控件默认是 hidden 状态，会被 QLayout 排除在 sizeHint 之外
            # （可见期重建时拿到「只剩边距」的假尺寸，收敛算错）→ 显式 show
            button.show()
            self._buttons[action.id] = button
        if not self._buttons:
            # 动作被清空 / 全部禁用：不能把没有按钮的空盒子留在屏幕上
            if self.isVisible():
                self.hide()
            return
        self.adjustSize()
        self.update()
        if self.isVisible() and self._anchor is not None:
            # 可见期间尺寸变了（紧凑切换 / 换动作）→ 按原锚点重新收敛屏幕
            self.popupAt(self._anchor)

    def _build_button(self, action: ElaMenuItem) -> QWidget:
        tooltip = action.tooltip or action.label
        if self._compact and action.icon is not None:
            button: QWidget = ElaIconButton(
                action.icon,
                _ICON_BUTTON_SIZE - 10,
                _ICON_BUTTON_SIZE,
                _ICON_BUTTON_SIZE,
                self,
            )
            button.setBorderRadius(6)
        else:
            # 紧凑模式下无图标动作回退为文字按钮
            button = ElaButton(
                action.label,
                icon=action.icon,
                iconSize=14,
                variant="text",
                size="small",
                parent=self,
            )
        # 只使用库内 ElaToolTip（不设置 setToolTip，避免任何原生提示框），
        # 位置放在动作条下方，避免遮挡上方选中的文字
        set_tooltip(button, tooltip, ElaToolTipPositionType.Bottom)
        button.clicked.connect(
            lambda _checked=False, actionId=action.id: self._on_clicked(actionId)
        )
        return button

    def _on_clicked(self, actionId: str) -> None:
        self.hide()
        self.actionTriggered.emit(actionId)

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().hideEvent(event)
        self.hidden.emit()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 阴影按整窗 rect 画，盒子坐标整体 translate 一次（别逐个加偏移）
        sm = SHADOW_MARGIN
        paintOverlayShadow(painter, self.rect(), margin=sm, radius=_RADIUS)
        painter.translate(sm, sm)
        rect = QRectF(0.5, 0.5, self.width() - 2 * sm - 1, self.height() - 2 * sm - 1)
        path = QPainterPath()
        path.addRoundedRect(rect, _RADIUS, _RADIUS)
        painter.fillPath(
            path,
            eTheme.getThemeColor(self._theme_mode, ElaThemeType.ThemeColor.PopupBase),
        )
        painter.setPen(
            QPen(
                eTheme.getThemeColor(
                    self._theme_mode, ElaThemeType.ThemeColor.PopupBorder
                ),
                1,
            )
        )
        painter.drawPath(path)
        painter.end()

    def _onThemeChanged(self, mode) -> None:
        super()._onThemeChanged(mode)
        self.update()


__all__ = ["ElaSelectionPopup"]
