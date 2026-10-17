"""``ElaDrawerArea`` 测试：click-to-toggle 修复 —— 点标题栏开合、交互控件不误触发。"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent, QPoint, Qt, QPointF
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QWidget
from PyQt6ElaWidgetTools import ElaDrawerArea as NativeDrawerArea
from PyQt6ElaWidgetTools import ElaText, ElaToggleSwitch

from pyqt6_ela_pro.ela_drawer_area import ElaDrawerArea
from pyqt6_ela_pro.widget_base import ElaThemeWidget


def _click(qapp, widget: QWidget, pos: QPoint) -> None:
    """向 *widget* 发送一次左键点击（按下 + 释放）。"""
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(pos),
        QPointF(widget.mapToGlobal(pos)),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(pos),
        QPointF(widget.mapToGlobal(pos)),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    qapp.sendEvent(widget, press)
    qapp.sendEvent(widget, release)
    qapp.processEvents()


@pytest.fixture
def drawer(qapp, make):
    """已 ``show()`` 的抽屉：``(parent, area, 默认标题栏)``，用完自动回收。"""
    parent = make(QWidget)
    parent.resize(400, 300)
    area = make(ElaDrawerArea, parent)
    area.setGeometry(0, 0, 400, 300)
    area.addDrawer(make(QWidget, area))
    parent.show()
    qapp.processEvents()
    header = area.findChild(QWidget, "ElaDrawerHeader")
    assert header is not None
    yield parent, area, header
    if parent.isVisible():
        parent.close()
        qapp.processEvents()


@pytest.fixture
def custom_header(qapp, make, drawer):
    """把自定义标题栏挂上去；``(area, header_widget)``。"""
    _, area, _ = drawer
    header = make(ElaThemeWidget, area)
    return area, header


@pytest.fixture
def make_switch_header(qapp, make):
    """在标题栏里放一个 ``ElaToggleSwitch`` 并挂到抽屉上，返回 ``(area, switch)``。"""

    def build(area: ElaDrawerArea) -> ElaToggleSwitch:
        header = make(ElaThemeWidget, area)
        layout = QHBoxLayout(header)
        switch = make(ElaToggleSwitch, header)
        layout.addWidget(switch)
        layout.addStretch()
        area.setDrawerHeader(header)
        qapp.processEvents()
        return switch

    return build


class TestElaDrawerAreaApi:
    def test_is_native_subclass(self):
        assert issubclass(ElaDrawerArea, NativeDrawerArea)

    def test_toggle_method(self, drawer):
        _, area, _ = drawer

        area.toggle()
        assert area.getIsExpand() is True
        area.toggle()
        assert area.getIsExpand() is False

    def test_expand_collapse_idempotent(self, drawer):
        """Regression: 重复 expand/collapse 不重复发信号（开关回声防护）。"""
        _, area, _ = drawer
        states = []
        area.expandStateChanged.connect(states.append)

        area.expand()
        area.expand()
        assert states == [True]

        area.collapse()
        area.collapse()
        assert states == [True, False]


class TestElaDrawerAreaClickToggle:
    def test_click_empty_header_toggles_once(self, qapp, drawer):
        _, area, header = drawer
        states = []
        area.expandStateChanged.connect(states.append)

        _click(qapp, header, header.rect().center())

        assert area.getIsExpand() is True
        assert states == [True]

    def test_click_empty_header_twice_collapses(self, qapp, drawer):
        _, area, header = drawer

        _click(qapp, header, header.rect().center())
        _click(qapp, header, header.rect().center())

        assert area.getIsExpand() is False

    def test_click_custom_header_label_toggles(self, qapp, make, custom_header):
        """标题栏里的 ElaText 本身可点。"""
        area, header = custom_header
        layout = QHBoxLayout(header)
        label = make(ElaText, "抽屉标题", header)
        layout.addWidget(label)
        layout.addStretch()
        area.setDrawerHeader(header)
        qapp.processEvents()

        _click(qapp, label, label.rect().center())

        assert area.getIsExpand() is True

    def test_click_custom_header_background_toggles(self, qapp, make, custom_header):
        """标题栏空白处（无子控件的区域）也要能点开。"""
        area, header = custom_header
        layout = QHBoxLayout(header)
        layout.addWidget(make(ElaText, "抽屉标题", header))
        layout.addStretch()
        area.setDrawerHeader(header)
        qapp.processEvents()

        _click(qapp, header, QPoint(header.width() - 5, 5))

        assert area.getIsExpand() is True

    def test_click_interactive_button_does_not_toggle(self, qapp, make, custom_header):
        """回归: 交互控件自己吃掉点击，不能顺带把抽屉展开。"""
        area, header = custom_header
        layout = QHBoxLayout(header)
        button = make(QPushButton, "点我", header)
        layout.addWidget(button)
        layout.addStretch()
        area.setDrawerHeader(header)
        qapp.processEvents()

        _click(qapp, button, button.rect().center())

        assert area.getIsExpand() is False


class TestElaDrawerAreaHeaderClickSyncsSwitch:
    def test_header_click_syncs_toggle_switch(self, qapp, drawer, make_switch_header):
        """Regression: 示例中标题栏点击后右侧开关必须跟随切换。"""
        _, area, _ = drawer
        switch = make_switch_header(area)
        area.expandStateChanged.connect(switch.setIsToggled)
        qapp.processEvents()

        _click(
            qapp, switch.parentWidget(), QPoint(switch.parentWidget().width() - 5, 5)
        )
        assert area.getIsExpand() is True
        assert switch.getIsToggled() is True

        _click(
            qapp, switch.parentWidget(), QPoint(switch.parentWidget().width() - 5, 5)
        )
        assert area.getIsExpand() is False
        assert switch.getIsToggled() is False

    def test_click_toggle_switch_does_not_toggle_drawer(
        self, qapp, drawer, make_switch_header
    ):
        """Regression: 交互开关自处理点击，不应被当成「点击标题栏」。"""
        _, area, _ = drawer
        switch = make_switch_header(area)

        _click(qapp, switch, switch.rect().center())

        assert switch.getIsToggled() is True
        assert area.getIsExpand() is False

    def test_switch_click_with_bidirectional_wiring_no_flap(
        self, qapp, drawer, make_switch_header
    ):
        """Regression: 示例双向接线（开关↔抽屉）下单击开关只切换一次。"""
        _, area, _ = drawer
        switch = make_switch_header(area)

        switch.toggled.connect(
            lambda state: area.expand() if state else area.collapse()
        )
        area.expandStateChanged.connect(switch.setIsToggled)
        qapp.processEvents()

        _click(qapp, switch, switch.rect().center())

        assert switch.getIsToggled() is True
        assert area.getIsExpand() is True
