"""
ElaDrawerArea 折叠面板增强组件。

基于 PyQt6ElaWidgetTools 的原生 ``ElaDrawerArea``，修复其设置自定义
标题栏组件后点击标题栏无法展开/收起的问题：

原生 ``ElaDrawerHeader`` 仅在 ``childAt(pos)`` 为空白（无子控件或子控件
objectName 为空）时才切换状态，而自定义标题栏组件（如 ``ElaThemeWidget``、
``ElaText``）通常都带有非空 objectName，导致点击标题栏没有任何响应。

本组件通过事件过滤器在标题栏收到冒泡的鼠标释放事件时补上切换逻辑，
同时避让原生已处理的空白区域，保证不会双重切换；标题栏内的交互控件
（按钮、开关、输入框等）自行处理点击，不会被当成"点击标题栏"。
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QEvent, QObject, QPoint, Qt
from PyQt6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QAbstractSlider,
    QAbstractSpinBox,
    QCalendarWidget,
    QComboBox,
    QDial,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QTabBar,
    QTextEdit,
    QWidget,
)

from PyQt6ElaWidgetTools import ElaDrawerArea as _ElaDrawerArea

#: 非 Qt 交互基类但会自行处理点击的原生控件（事件仍会 ignore 冒泡）
_INTERACTIVE_ELA_CLASSES = frozenset({"ElaToggleSwitch"})

_INTERACTIVE_QT_TYPES = (
    QAbstractButton,
    QAbstractItemView,
    QAbstractSlider,
    QAbstractSpinBox,
    QCalendarWidget,
    QComboBox,
    QDial,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QTabBar,
    QTextEdit,
)


class ElaDrawerArea(_ElaDrawerArea):
    """可折叠面板。

    与上游 ``ElaDrawerArea`` API 完全一致（``setDrawerHeader`` / ``addDrawer``
    / ``removeDrawer`` / ``expand`` / ``collapse`` / ``getIsExpand`` /
    ``expandStateChanged``），并额外保证：

    - 设置任意自定义标题栏组件后，点击标题栏非交互区域可展开/收起；
    - ``toggle()`` 便捷切换展开状态。

    :param parent: 父控件
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._header: Optional[QWidget] = self.findChild(QWidget, "ElaDrawerHeader")
        if self._header is not None:
            self._header.installEventFilter(self)

    def toggle(self) -> None:
        """切换展开/收起状态。"""
        if self.getIsExpand():
            self.collapse()
        else:
            self.expand()

    def expand(self) -> None:
        """展开面板（已展开时不重复触发动画与信号）。"""
        if self.getIsExpand():
            return
        super().expand()

    def collapse(self) -> None:
        """收起面板（已收起时不重复触发动画与信号）。"""
        if not self.getIsExpand():
            return
        super().collapse()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._header and event.type() == QEvent.Type.MouseButtonRelease:
            # 只认左键。基类 _ElaDrawerArea 自己在 header 上按任意键切换，
            # 所以非左键必须**吞掉事件**，否则仍会被基类切换。
            if event.button() != Qt.MouseButton.LeftButton:
                event.accept()
                return True
            if self._should_toggle_on(event.position().toPoint()):
                self.toggle()
        return super().eventFilter(watched, event)

    def _should_toggle_on(self, pos: QPoint) -> bool:
        """是否应由本组件补做切换。

        原生实现在 ``childAt`` 为 ``None`` 或 objectName 为空时自行切换，
        此处避让这些情况以防双重切换；命中带 objectName 的交互控件
        （开关 / 按钮 / 输入框等）时也不切换，避免与控件自身行为冲突。
        """
        if self._header is None:
            return False
        child = self._header.childAt(pos)
        if child is None or not child.objectName():
            return False
        node: Optional[QWidget] = child
        while node is not None and node is not self._header:
            if isinstance(node, _INTERACTIVE_QT_TYPES) or (
                node.metaObject().className() in _INTERACTIVE_ELA_CLASSES
            ):
                return False
            node = node.parentWidget()
        return True
