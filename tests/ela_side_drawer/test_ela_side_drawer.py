"""``ela_side_drawer`` 测试：位置枚举 / 面板 / 蒙层 / 抽屉本体。"""

from __future__ import annotations

import pytest
from PyQt6 import sip
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QWidget

from pyqt6_ela_pro._ownership import ElaWidgetOwnershipType
from pyqt6_ela_pro.ela_side_drawer import (
    ElaDrawerPositionType,
    ElaDrawerPanel,
    ElaDrawerDim,
    ElaDrawer,
)


@pytest.fixture
def parent(make):
    """抽屉的宿主控件。"""
    return make(QWidget)


@pytest.fixture
def panel(make):
    return make(ElaDrawerPanel)


@pytest.fixture
def dim(make):
    return make(ElaDrawerDim)


@pytest.fixture
def drawer(make, parent):
    """挂在 *parent* 上的默认抽屉。"""
    return make(ElaDrawer, parent=parent)


class TestElaDrawerPosition:
    """Test cases for ElaDrawerPositionType enum."""

    @pytest.mark.parametrize(
        ("position", "value"),
        [
            (ElaDrawerPositionType.Left, 0),
            (ElaDrawerPositionType.Right, 1),
            (ElaDrawerPositionType.Top, 2),
            (ElaDrawerPositionType.Bottom, 3),
        ],
        ids=["left", "right", "top", "bottom"],
    )
    def test_enum_value(self, position, value):
        assert position == value


class TestElaDrawerPanel:
    """Test cases for ElaDrawerPanel class."""

    @pytest.mark.parametrize(
        ("attr", "expected"),
        [("_corner_radius", 12), ("_position", ElaDrawerPositionType.Right)],
        ids=["corner-radius", "position"],
    )
    def test_initialization_with_defaults(self, panel, attr, expected):
        assert getattr(panel, attr) == expected

    def test_initialization_with_custom_values(self, make):
        panel = make(ElaDrawerPanel, position=ElaDrawerPositionType.Left, corner_radius=8)
        assert panel._corner_radius == 8
        assert panel._position == ElaDrawerPositionType.Left

    def test_set_bg_color(self, panel):
        color = QColor(255, 0, 0)
        panel.setBgColor(color)
        assert panel._bg_color == color

    def test_set_position(self, panel):
        panel.setPosition(ElaDrawerPositionType.Top)
        assert panel._position == ElaDrawerPositionType.Top


class TestElaDrawerDim:
    """Test cases for ElaDrawerDim class."""

    def test_initialization(self, dim):
        assert dim._bg_color == QColor(0, 0, 0, 102)

    def test_set_bg_color(self, dim):
        color = QColor(255, 0, 0, 128)
        dim.setBgColor(color)
        assert dim._bg_color == color


class TestElaDrawer:
    """Test cases for ElaDrawer class."""

    @pytest.mark.parametrize(
        ("attr", "expected"),
        [
            ("_position", ElaDrawerPositionType.Right),
            ("_drawer_size", 360),
            ("_is_opened", False),
            ("_close_on_dim_clicked", True),
            ("_animation_duration", 250),
        ],
        ids=[
            "position",
            "drawer-size",
            "is-opened",
            "close-on-dim-clicked",
            "animation-duration",
        ],
    )
    def test_initialization_with_defaults(self, drawer, attr, expected):
        assert getattr(drawer, attr) == expected

    def test_initialization_with_custom_values(self, make, parent):
        drawer = make(
            ElaDrawer, position=ElaDrawerPositionType.Left, drawer_size=400, parent=parent
        )
        assert drawer._position == ElaDrawerPositionType.Left
        assert drawer._drawer_size == 400

    @pytest.mark.parametrize("signal", ["closed", "opened"])
    def test_has_signal(self, drawer, signal):
        assert hasattr(drawer, signal)
        assert callable(getattr(drawer, signal))

    def test_initial_state_is_hidden(self, drawer):
        assert not drawer.isVisible()

    def test_initial_opened_is_false(self, drawer):
        assert drawer.isOpened() is False

    def test_set_content_widget(self, make, drawer):
        assert drawer.setContentWidget(make(QWidget)) is drawer

    def test_content_widget_is_readable_back(self, make, drawer):
        content = make(QWidget)
        drawer.setContentWidget(content)
        assert drawer.contentWidget() is content

    def test_default_ownership_is_borrowed(self, make, drawer):
        assert drawer.contentOwnership() == ElaWidgetOwnershipType.Borrowed

    def test_set_content_widget_accepts_ownership(self, make, drawer):
        content = make(QWidget)
        drawer.setContentWidget(content, ElaWidgetOwnershipType.Owned)
        assert drawer.contentOwnership() == ElaWidgetOwnershipType.Owned

    def test_replacing_content_removes_previous_from_layout(self, make, drawer):
        """换内容时旧的要从布局里摘掉，否则两个内容叠在一起。"""
        first = make(QWidget)
        second = make(QWidget)
        drawer.setContentWidget(first)
        drawer.setContentWidget(second)
        assert drawer._main_layout.count() == 1
        assert drawer._main_layout.itemAt(0).widget() is second

    def test_take_content_widget_returns_parentless(self, make, drawer):
        content = make(QWidget)
        drawer.setContentWidget(content, ElaWidgetOwnershipType.Owned)
        got = drawer.takeContentWidget()
        assert got is content
        assert got.parentWidget() is None
        assert drawer.contentWidget() is None
        assert drawer._main_layout.count() == 0

    def test_take_content_widget_never_deletes(self, make, drawer, qapp):
        from PyQt6.QtCore import QCoreApplication, QEvent

        content = make(QWidget)
        drawer.setContentWidget(content, ElaWidgetOwnershipType.Owned)
        drawer.takeContentWidget()
        QCoreApplication.sendPostedEvents(content, QEvent.Type.DeferredDelete)
        assert sip.isdeleted(content) is False

    def test_content_destroyed_externally_is_dropped(self, make, drawer, qapp):
        """内容被外部销毁后 ``contentWidget()`` 要返回 None，不能留悬空包装器。"""
        from PyQt6.QtCore import QCoreApplication, QEvent

        content = make(QWidget)
        drawer.setContentWidget(content)
        content.deleteLater()
        QCoreApplication.sendPostedEvents(content, QEvent.Type.DeferredDelete)
        assert drawer.contentWidget() is None
        assert drawer._main_layout.count() == 0

    def test_set_drawer_size(self, drawer):
        drawer.setDrawerSize(500)
        assert drawer._drawer_size == 500

    def test_set_corner_radius(self, drawer):
        drawer.setCornerRadius(20)
        assert drawer._corner_radius == 20

    def test_set_close_on_dim_clicked(self, drawer):
        drawer.setCloseOnDimClicked(False)
        assert drawer._close_on_dim_clicked is False

    def test_set_animation_duration(self, drawer):
        drawer.setAnimationDuration(500)
        assert drawer._animation_duration == 500

    def test_delete_later_disconnects_theme_signal(self, drawer):
        """析构要断开主题信号。"""
        drawer.deleteLater()

    def test_show_drawer_without_parent_returns_immediately(self, make):
        """Regression: parentless showDrawer must not setParent(self) and hang."""
        drawer = make(ElaDrawer)
        drawer.setContentWidget(make(QWidget))

        drawer.showDrawer()

        assert drawer.isOpened() is False

    def test_show_drawer_with_parent_opens(self, make, drawer):
        """Test showDrawer with a parent widget opens the drawer."""
        drawer.setContentWidget(make(QWidget))

        drawer.showDrawer()

        assert drawer.isOpened() is True
