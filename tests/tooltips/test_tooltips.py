"""Tests for tooltips module: ElaToolTip, ElaStateToolTip, set_tooltip, remove_tooltip."""

from __future__ import annotations

from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent, QObject, QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QHelpEvent, QPalette
from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
from PyQt6ElaWidgetTools import ElaThemeType, eTheme

import pyqt6_ela_pro.tooltips as tooltips_module
from pyqt6_ela_pro.tooltips import (
    TOOLTIP_BORDER_RADIUS,
    ElaStateToolTip,
    ElaToolTip,
    ElaToolTipPositionType,
    _filter_dict,
    _tooltip_dict,
    remove_tooltip,
    set_tooltip,
)


class TestToolTip:
    """Test cases for ElaToolTip class."""

    def test_tooltip_initialization(self):
        """Test ElaToolTip initializes with text."""
        tooltip = ElaToolTip("Test tooltip")

        assert tooltip._text == "Test tooltip"

        tooltip.deleteLater()

    def test_tooltip_has_frameless_window_flag(self):
        """Test ElaToolTip uses frameless window."""
        tooltip = ElaToolTip()

        flags = tooltip.windowFlags()
        assert flags & Qt.WindowType.FramelessWindowHint

        tooltip.deleteLater()

    def test_tooltip_has_tool_window_flag(self):
        """Test ElaToolTip uses Tool window type."""
        tooltip = ElaToolTip()

        flags = tooltip.windowFlags()
        assert flags & Qt.WindowType.Tool

        tooltip.deleteLater()

    def test_tooltip_has_stays_on_top_flag(self):
        """Test ElaToolTip stays on top of other windows."""
        tooltip = ElaToolTip()

        flags = tooltip.windowFlags()
        assert flags & Qt.WindowType.WindowStaysOnTopHint

        tooltip.deleteLater()

    def test_tooltip_set_text(self):
        """Test setText updates tooltip text."""
        tooltip = ElaToolTip()
        tooltip.setText("New text")

        assert tooltip._text == "New text"
        assert tooltip._label.text() == "New text"

        tooltip.deleteLater()

    def test_set_content_widget_switches_to_custom_content(self, qapp):
        """自定义内容控件：隐藏文本标签、弹体尺寸跟随控件。"""
        tooltip = ElaToolTip("文本")
        content = QWidget()
        content.setFixedSize(80, 40)

        tooltip.setContentWidget(content)

        assert tooltip.contentWidget() is content
        assert content.parent() is tooltip
        assert tooltip._label.isHidden()
        assert tooltip.size().width() == 80 + 24
        assert tooltip.size().height() == 40 + 16

        tooltip.deleteLater()
        qapp.processEvents()

    def test_set_content_widget_replaces_and_deletes_old(self, qapp):
        """替换时旧控件与上游一致被 deleteLater（所有权归提示框）。"""
        tooltip = ElaToolTip("文本")
        first = QWidget()
        first.setFixedSize(80, 40)
        second = QWidget()
        second.setFixedSize(60, 30)

        tooltip.setContentWidget(first)
        tooltip.setContentWidget(second)

        assert tooltip.contentWidget() is second
        assert tooltip.size().width() == 60 + 24
        assert first.parent() is None
        QCoreApplication.sendPostedEvents(first, QEvent.Type.DeferredDelete)
        assert sip.isdeleted(first)

        tooltip.deleteLater()
        qapp.processEvents()

    def test_set_content_widget_ignores_none_and_self(self, qapp):
        """None / 传自身都是空操作，文本模式不受影响（与上游语义一致）。"""
        tooltip = ElaToolTip("文本")

        tooltip.setContentWidget(None)
        tooltip.setContentWidget(tooltip)

        assert tooltip.contentWidget() is None
        assert not tooltip._label.isHidden()

        tooltip.deleteLater()
        qapp.processEvents()

    def test_fixed_size_content_wins_over_layout_hint(self, qapp):
        """显式 ``setFixedSize`` 的内容控件以固定尺寸为准。

        回归：只按 layout 的 ``sizeHint`` 定弹体时，固定尺寸的大于 hint 的内容
        会溢出被裁（实测两行卡片尾字被切）。
        """
        tooltip = ElaToolTip("文本")
        content = QWidget()
        content.setFixedSize(200, 56)
        layout = QVBoxLayout(content)
        layout.addWidget(QLabel("短"))
        assert content.sizeHint().width() < 200  # 前提：hint 确实小于固定尺寸

        tooltip.setContentWidget(content)

        assert tooltip.size().width() == 200 + 24
        assert tooltip.size().height() == 56 + 16

        tooltip.deleteLater()
        qapp.processEvents()

    def test_tooltip_has_translucent_background(self):
        """Test ElaToolTip has translucent background."""
        tooltip = ElaToolTip()

        assert tooltip.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        tooltip.deleteLater()

    def test_tooltip_border_radius_constant(self):
        """Test TOOLTIP_BORDER_RADIUS is 8."""
        assert TOOLTIP_BORDER_RADIUS == 8


class TestToolTipParentShowOrder:
    """提示框在父窗口 show 之前创建时，不得跟着父窗口一起显示。

    回归：``set_tooltip`` 把提示框挂在顶层窗口下，而宿主常在窗口 ``show()``
    之前就建好页面 / 工具栏 —— 未 ``showAt`` 定位的提示框会以 (0, 0) 画在
    窗口左上角，压住正文（``llm_test/render_opencode_session.py`` 实测）。
    """

    def _child(self, window_widget, qapp):
        child = QWidget(window_widget)
        child.setGeometry(10, 10, 60, 24)
        set_tooltip(child, "提示")
        window_widget.show()
        qapp.processEvents()
        return child

    def test_tooltip_stays_hidden_when_parent_window_shows(self, qapp, window_widget):
        child = self._child(window_widget, qapp)

        tooltip = _tooltip_dict[child]
        assert not tooltip.isVisible()
        assert tooltip.isHidden()

    def test_show_at_still_displays_tooltip(self, qapp, window_widget):
        child = self._child(window_widget, qapp)

        tooltip = _tooltip_dict[child]
        tooltip.showAt(child, ElaToolTipPositionType.Top)
        assert tooltip.isVisible()
        tooltip.hide()

    def test_remove_tooltip_kills_hidden_instance(self, qapp, window_widget):
        child = self._child(window_widget, qapp)

        remove_tooltip(child)
        qapp.processEvents()

        assert child not in _tooltip_dict
        assert child not in _filter_dict


class TestElaToolTipPosition:
    """Test cases for ElaToolTipPositionType enum."""

    def test_ela_tool_tip_position_has_top(self):
        """Test ElaToolTipPositionType.Top exists."""
        assert ElaToolTipPositionType.Top is not None

    def test_ela_tool_tip_position_has_bottom(self):
        """Test ElaToolTipPositionType.Bottom exists."""
        assert ElaToolTipPositionType.Bottom is not None

    def test_ela_tool_tip_position_has_left(self):
        """Test ElaToolTipPositionType.Left exists."""
        assert ElaToolTipPositionType.Left is not None

    def test_ela_tool_tip_position_has_right(self):
        """Test ElaToolTipPositionType.Right exists."""
        assert ElaToolTipPositionType.Right is not None

    def test_ela_tool_tip_position_has_all_8_positions(self):
        """Test all 8 positions exist."""
        assert len(ElaToolTipPositionType) == 8

        positions = [
            ElaToolTipPositionType.Top,
            ElaToolTipPositionType.Bottom,
            ElaToolTipPositionType.Left,
            ElaToolTipPositionType.Right,
            ElaToolTipPositionType.TopLeft,
            ElaToolTipPositionType.TopRight,
            ElaToolTipPositionType.BottomLeft,
            ElaToolTipPositionType.BottomRight,
        ]

        for pos in positions:
            assert pos is not None


class TestSetTooltip:
    """Test cases for set_tooltip function."""

    def test_set_tooltip_accepts_widget_and_text(self, qapp):
        """Test set_tooltip accepts widget and text parameters."""
        widget = QWidget()

        set_tooltip(widget, "Test tooltip")

        widget.deleteLater()
        qapp.processEvents()

    def test_set_tooltip_accepts_position_parameter(self, qapp):
        """Test set_tooltip accepts position parameter."""
        widget = QWidget()

        set_tooltip(widget, "Test", position=ElaToolTipPositionType.Top)

        widget.deleteLater()
        qapp.processEvents()

    def test_set_tooltip_does_not_crash_on_widget_destroyed(self, qapp):
        """Test tooltip cleanup does not crash when widget is destroyed."""
        widget = QWidget()
        set_tooltip(widget, "No crash test")

        # deleteLater + defer should not raise
        widget.deleteLater()
        qapp.processEvents()

    def test_remove_tooltip_cleans_up_entries(self, qapp):
        """Test remove_tooltip cleans up global dict entries."""

        widget = QWidget()
        set_tooltip(widget, "Cleanup test")

        assert widget in _tooltip_dict
        assert widget in _filter_dict

        remove_tooltip(widget)

        assert widget not in _tooltip_dict
        assert widget not in _filter_dict

        widget.deleteLater()

    def test_set_tooltip_supports_content_widget(self, qapp):
        """``contentWidget`` 透传到 ElaToolTip.setContentWidget。"""
        widget = QWidget()
        content = QWidget()
        content.setFixedSize(50, 20)

        set_tooltip(widget, "", contentWidget=content)

        tooltip = _tooltip_dict[widget]
        assert tooltip.contentWidget() is content
        assert tooltip.size().width() == 50 + 24

        remove_tooltip(widget)
        widget.deleteLater()
        qapp.processEvents()

    def test_custom_tooltip_suppresses_native_tooltip(self, qapp):
        """绑定自定义提示后吞掉 QEvent.Type.ToolTip，避免原生 QToolTip 双提示。"""

        widget = QWidget()
        widget.setToolTip("提示")
        set_tooltip(widget, "提示")
        tooltip = _filter_dict[widget]

        enter = QHelpEvent(QEvent.Type.ToolTip, QPoint(1, 1), QPoint(10, 10))
        assert tooltip.eventFilter(widget, enter) is True

        remove_tooltip(widget)
        widget.deleteLater()


class TestSetTooltipReuse:
    """重复绑定时复用同一个提示框（bug #17：恢复一次会话曾建 4609 个）。"""

    def test_reuses_existing_instance_and_updates_text(self, qapp):
        widget = QWidget()
        set_tooltip(widget, "a")
        first = _tooltip_dict[widget]

        set_tooltip(widget, "b", ElaToolTipPositionType.Bottom)

        assert _tooltip_dict[widget] is first
        assert first._text == "b"
        assert _filter_dict[widget]._position == ElaToolTipPositionType.Bottom

        remove_tooltip(widget)
        widget.deleteLater()
        qapp.processEvents()

    def test_recreates_when_leaving_content_mode(self, qapp):
        widget = QWidget()
        set_tooltip(widget, "a")
        first = _tooltip_dict[widget]
        content = QWidget()
        content.setFixedSize(40, 20)

        set_tooltip(widget, "", contentWidget=content)
        assert _tooltip_dict[widget] is first
        assert first.contentWidget() is content

        # 没有「清空内容控件」的 API：退回纯文本只能重建
        set_tooltip(widget, "b")
        assert _tooltip_dict[widget] is not first
        assert _tooltip_dict[widget]._text == "b"

        remove_tooltip(widget)
        widget.deleteLater()
        qapp.processEvents()


class TestRemoveTooltip:
    """Test cases for remove_tooltip function."""

    def test_remove_tooltip_accepts_widget(self, qapp):
        """Test remove_tooltip accepts widget parameter."""
        widget = QWidget()

        remove_tooltip(widget)

        widget.deleteLater()
        qapp.processEvents()

    def test_remove_tooltip_does_not_raise_on_unregistered_widget(self, qapp):
        """Test remove_tooltip doesn't raise on widget without tooltip."""
        widget = QWidget()

        remove_tooltip(widget)

        widget.deleteLater()
        qapp.processEvents()


class TestToolTipClamp:
    """提示框越界收敛 / 翻转测试。"""

    def _child(self, qapp):
        parent = QWidget()
        parent.setWindowFlags(Qt.WindowType.Window)
        parent.setGeometry(320, 240, 260, 200)
        parent.show()
        child = QWidget(parent)
        child.setGeometry(20, 20, 60, 24)
        qapp.processEvents()
        return parent, child

    def test_show_at_keeps_inside_screen(self, qapp):

        area = QApplication.primaryScreen().availableGeometry()
        parent, child = self._child(qapp)
        for position in (
            ElaToolTipPositionType.Top,
            ElaToolTipPositionType.Bottom,
            ElaToolTipPositionType.Left,
            ElaToolTipPositionType.Right,
        ):
            tooltip = ElaToolTip("提示")
            tooltip.showAt(child, position)
            assert area.contains(tooltip.frameGeometry())
            tooltip.hide()
            tooltip.deleteLater()
        parent.close()
        parent.deleteLater()
        qapp.processEvents()

    def test_flip_below_when_no_room_above(self, qapp):

        area = QApplication.primaryScreen().availableGeometry()
        parent, child = self._child(qapp)
        tooltip = ElaToolTip("提示")
        y = area.top() - 50
        _, clamped = tooltip._clamp_to_screen(area.left() + 100, y, child, above=True)
        assert clamped >= area.top()
        assert clamped >= child.mapToGlobal(QPoint(0, 0)).y()
        tooltip.deleteLater()
        parent.close()
        parent.deleteLater()
        qapp.processEvents()

    def test_flip_above_when_no_room_below(self, qapp):

        area = QApplication.primaryScreen().availableGeometry()
        parent, child = self._child(qapp)
        tooltip = ElaToolTip("提示")
        y = area.bottom() - 5
        _, clamped = tooltip._clamp_to_screen(area.left() + 100, y, child, above=False)
        assert clamped <= area.bottom() - tooltip.height() + 1
        assert clamped + tooltip.height() <= child.mapToGlobal(QPoint(0, 0)).y() + 1
        tooltip.deleteLater()
        parent.close()
        parent.deleteLater()
        qapp.processEvents()

    def test_horizontal_clamped_to_right_edge(self, qapp):

        area = QApplication.primaryScreen().availableGeometry()
        parent, child = self._child(qapp)
        tooltip = ElaToolTip("提示")
        x, _ = tooltip._clamp_to_screen(
            area.right() + 200, area.top() + 50, child, above=False
        )
        assert x + tooltip.width() <= area.right() + 1
        assert x >= area.left()
        tooltip.deleteLater()
        parent.close()
        parent.deleteLater()
        qapp.processEvents()


class TestToolTipTheme:
    """提示框文字颜色跟随主题（深色背景下必须变亮）。"""

    def test_label_text_color_follows_theme(self, qapp):

        light = eTheme.getThemeColor(
            ElaThemeType.ThemeMode.Light, ElaThemeType.ThemeColor.BasicText
        ).name()
        dark = eTheme.getThemeColor(
            ElaThemeType.ThemeMode.Dark, ElaThemeType.ThemeColor.BasicText
        ).name()
        assert light != dark

        tooltip = ElaToolTip("提示")
        tooltip._onThemeChanged(ElaThemeType.ThemeMode.Light)
        assert (
            tooltip._label.palette().color(QPalette.ColorRole.WindowText).name()
            == light
        )
        tooltip._onThemeChanged(ElaThemeType.ThemeMode.Dark)
        assert (
            tooltip._label.palette().color(QPalette.ColorRole.WindowText).name() == dark
        )
        assert tooltip._currentTheme == ElaThemeType.ThemeMode.Dark
        assert tooltip._label.font().pixelSize() == 12
        tooltip.deleteLater()
        qapp.processEvents()

    def test_label_heals_palette_reset_on_paint(self, qapp):
        """原生顶层窗 / 平台样式把 palette 刷回时，绘制前要恢复显式色。"""
        dark = eTheme.getThemeColor(
            ElaThemeType.ThemeMode.Dark, ElaThemeType.ThemeColor.BasicText
        ).name()
        tooltip = ElaToolTip("提示")
        tooltip._onThemeChanged(ElaThemeType.ThemeMode.Dark)
        label = tooltip._label

        palette = label.palette()
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#123456"))
        label.setPalette(palette)
        assert label.palette().color(QPalette.ColorRole.WindowText).name() == "#123456"

        label.grab()  # 触发 paintEvent
        assert label.palette().color(QPalette.ColorRole.WindowText).name() == dark
        tooltip.deleteLater()
        qapp.processEvents()

    def test_theme_signal_reconnects_text_color(self, qapp, monkeypatch):

        class _FakeTheme(QObject):
            themeModeChanged = pyqtSignal(object)

            def getThemeMode(self):
                return ElaThemeType.ThemeMode.Light

            def getThemeColor(self, mode, _role):
                return (
                    QColor("#ff0000")
                    if mode == ElaThemeType.ThemeMode.Dark
                    else QColor("#00ff00")
                )

        fake = _FakeTheme()
        monkeypatch.setattr(tooltips_module, "eTheme", fake)
        tooltip = tooltips_module.ElaToolTip("提示")
        assert (
            tooltip._label.palette().color(QPalette.ColorRole.WindowText).name()
            == "#00ff00"
        )

        fake.themeModeChanged.emit(ElaThemeType.ThemeMode.Dark)
        assert (
            tooltip._label.palette().color(QPalette.ColorRole.WindowText).name()
            == "#ff0000"
        )
        tooltip.deleteLater()
        qapp.processEvents()


class TestStateToolTip:
    """Test cases for ElaStateToolTip class."""

    def test_state_tooltip_initialization(self):
        """Test ElaStateToolTip initializes with title and content."""
        st = ElaStateToolTip("Title", "Content")

        assert st._title == "Title"
        assert st._content == "Content"

        st.deleteLater()

    def test_state_tooltip_has_closed_signal(self):
        """Test ElaStateToolTip has closed signal (was closedSignal)."""
        st = ElaStateToolTip()
        assert hasattr(st, "closed")
        st.deleteLater()

    def test_state_tooltip_has_title_and_content_labels(self):
        """Test ElaStateToolTip has title and content labels."""
        st = ElaStateToolTip("Title", "Content")

        assert hasattr(st, "_titleLabel")
        assert hasattr(st, "_contentLabel")

        st.deleteLater()


class TestStateToolTipTimerLifecycle:
    """复用同一个 tooltip（hide 之后再 show）必须重启 loading spinner。"""

    def test_rotate_timer_restarts_after_hide_show(self, qapp):
        tip = ElaStateToolTip()
        tip.resize(200, 60)
        tip.show()
        qapp.processEvents()
        assert tip._rotateTimer.isActive() is True

        tip.hide()
        qapp.processEvents()
        assert tip._rotateTimer.isActive() is False

        tip.show()
        qapp.processEvents()
        assert tip._rotateTimer.isActive() is True, "hide -> show 后 spinner 必须重启"

        tip.close()
        tip.deleteLater()
        qapp.processEvents()

    def test_rotate_timer_stays_off_after_real_close(self, qapp):
        tip = ElaStateToolTip()
        tip.show()
        qapp.processEvents()
        tip.close()
        qapp.processEvents()
        assert tip._rotateTimer.isActive() is False
        tip.deleteLater()
        qapp.processEvents()
