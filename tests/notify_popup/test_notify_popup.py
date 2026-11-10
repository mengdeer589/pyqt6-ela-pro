"""Tests for notify_popup module: ElaNotifyPopup and show_notify."""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QAbstractAnimation, QRect, Qt

from pyqt6_ela_pro import ElaSeverity
from pyqt6_ela_pro.notify_popup import (
    ElaNotifyManager,
    ElaNotifyPopup,
    show_notify,
)


class TestElaNotifyPopup:
    """Test cases for ElaNotifyPopup class."""

    def test_ela_notify_popup_initialization(self):
        """Test ElaNotifyPopup initializes with correct default values."""
        popup = ElaNotifyPopup(title="Test", content="Content", timeout=5000)

        assert popup._title == "Test"
        assert popup._content == "Content"
        assert popup._timeout == 5000
        assert popup.severity() == ElaSeverity.Info

        popup.deleteLater()

    def test_ela_notify_popup_has_closed_signal(self):
        """Test ElaNotifyPopup has closed signal."""
        popup = ElaNotifyPopup()
        assert hasattr(popup, "closed")
        popup.deleteLater()

    def test_ela_notify_popup_set_title(self):
        """Test setTitle method updates title."""
        popup = ElaNotifyPopup()
        popup.setTitle("New Title")

        assert popup._title == "New Title"

        popup.deleteLater()

    def test_ela_notify_popup_set_content(self):
        """Test setContent method updates content."""
        popup = ElaNotifyPopup()
        popup.setContent("New Content")

        assert popup._content == "New Content"

        popup.deleteLater()

    def test_ela_notify_popup_set_timeout(self):
        """Test setTimeout method updates timeout."""
        popup = ElaNotifyPopup()
        popup.setTimeout(3000)

        assert popup._timeout == 3000

        popup.deleteLater()

    def test_ela_notify_popup_has_width_constraint(self):
        """Test ElaNotifyPopup has width constraint."""
        popup = ElaNotifyPopup()
        popup.show()
        # 300 是**内容**宽；窗口还要让出两侧各一格阴影边距。
        assert popup.width() == 300 + popup._shadow_margin * 2
        popup.deleteLater()

    def test_ela_notify_popup_has_frameless_window(self):
        """Test ElaNotifyPopup uses frameless window flags."""
        popup = ElaNotifyPopup()

        flags = popup.windowFlags()
        assert flags & Qt.WindowType.FramelessWindowHint

        popup.deleteLater()

    def test_ela_notify_popup_has_translucent_background(self):
        """Test ElaNotifyPopup has translucent background attribute."""
        popup = ElaNotifyPopup()

        assert popup.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        popup.deleteLater()


class TestElaNotifySeverity:
    """等级归一化与非法值。"""

    def test_set_severity_from_enum(self):
        popup = ElaNotifyPopup()
        popup.setSeverity(ElaSeverity.Error)
        assert popup.severity() == ElaSeverity.Error
        popup.deleteLater()

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("info", ElaSeverity.Info),
            ("SUCCESS", ElaSeverity.Success),
            (" Warning ", ElaSeverity.Warning),
            ("error", ElaSeverity.Error),
        ],
    )
    def test_set_severity_from_string(self, text, expected):
        popup = ElaNotifyPopup()
        popup.setSeverity(text)
        assert popup.severity() == expected
        popup.deleteLater()

    def test_invalid_severity_raises(self):
        popup = ElaNotifyPopup()
        with pytest.raises(ValueError):
            popup.setSeverity("fatal")
        popup.deleteLater()

    def test_show_notification_accepts_severity(self):
        popup = ElaNotifyPopup(timeout=0)
        popup.showNotification(title="t", content="c", severity=ElaSeverity.Warning)
        assert popup.severity() == ElaSeverity.Warning
        popup._close_animation()
        popup.deleteLater()


class TestElaNotifyLayout:
    """高度自适应与堆叠间距。"""

    def test_height_grows_with_long_content(self):
        short = ElaNotifyPopup(title="t", content="短", timeout=0)
        long = ElaNotifyPopup(title="t", content="很长的一段通知文字。" * 20, timeout=0)
        try:
            assert long.height() > short.height()
        finally:
            short.deleteLater()
            long.deleteLater()

    def test_stack_gap_excludes_shadow_margin(self, qapp, monkeypatch):
        manager = ElaNotifyManager()
        manager._popups.clear()
        monkeypatch.setattr(
            ElaNotifyPopup,
            "_get_screen_geometry",
            staticmethod(lambda: QRect(0, 0, 1920, 1080)),
        )

        manager.showNotification(title="a", content="b", timeout=0)
        manager.showNotification(title="c", content="d", timeout=0)
        first, second = manager._popups
        try:
            expected = first.height() - 2 * first._shadow_margin + 10
            assert first._end_pos.y() - second._end_pos.y() == expected
        finally:
            for popup in (first, second):
                popup._close_animation()
                popup.deleteLater()
            manager._popups.clear()

    def test_progress_runs_for_timeout(self):
        popup = ElaNotifyPopup(timeout=1000)
        popup.showNotification()
        try:
            assert popup._progress_anim.duration() == 1000
            assert popup._progress_anim.startValue() == 1.0
            assert popup._progress_anim.endValue() == 0.0
            assert popup._progress_anim.state() == QAbstractAnimation.State.Running
            popup._progress_anim.setCurrentTime(500)
            assert popup._progress == pytest.approx(0.5, abs=0.01)
        finally:
            popup._close_animation()
            popup.deleteLater()

    def test_no_progress_when_timeout_zero(self):
        popup = ElaNotifyPopup(timeout=0)
        popup.showNotification()
        try:
            assert popup._progress == -1.0
        finally:
            popup._close_animation()
            popup.deleteLater()

    def test_reflow_moves_remaining_popup_down(self, qapp, monkeypatch):
        manager = ElaNotifyManager()
        manager._popups.clear()
        monkeypatch.setattr(
            ElaNotifyPopup,
            "_get_screen_geometry",
            staticmethod(lambda: QRect(0, 0, 1920, 1080)),
        )

        manager.showNotification(title="a", content="b", timeout=0)
        manager.showNotification(title="c", content="d", timeout=0)
        first, second = manager._popups
        old_y = second._end_pos.y()

        manager._onPopupClosed(first)
        try:
            assert second._end_pos.y() > old_y
        finally:
            second._close_animation()
            second.deleteLater()
            manager._popups.clear()


class TestElaNotifyManager:
    """Test cases for ElaNotifyManager singleton."""

    def test_ela_notify_manager_is_singleton(self):
        """Test ElaNotifyManager returns same instance."""
        manager1 = ElaNotifyManager()
        manager2 = ElaNotifyManager()

        assert manager1 is manager2

    def test_ela_notify_manager_show_creates_popup(self):
        """Test show method creates and shows popup."""
        manager = ElaNotifyManager()
        manager._popups.clear()

        manager.showNotification(title="Test", content="Message", timeout=100)

        assert len(manager._popups) == 1
        popup = manager._popups[0]
        assert isinstance(popup, ElaNotifyPopup)

        popup.deleteLater()

    def test_manager_passes_severity(self):
        manager = ElaNotifyManager()
        manager._popups.clear()

        manager.showNotification(
            title="Test", content="Message", timeout=100, severity=ElaSeverity.Error
        )

        assert manager._popups[0].severity() == ElaSeverity.Error

        manager._popups[0].deleteLater()

    def test_show_notify_passes_severity(self):
        manager = ElaNotifyManager()
        manager._popups.clear()

        show_notify(title="Test", content="Message", timeout=100, severity="success")

        assert manager._popups[0].severity() == ElaSeverity.Success

        manager._popups[0].deleteLater()

    def test_ela_notify_manager_removes_closed_popup(self):
        """Test _onPopupClosed removes popup from list."""
        manager = ElaNotifyManager()
        manager._popups.clear()

        popup = ElaNotifyPopup(title="Test", timeout=100)
        manager._popups.append(popup)

        manager._onPopupClosed(popup)

        assert popup not in manager._popups

        popup.deleteLater()


class TestNotifyPopupScreenOrigin:
    """availableGeometry() 带原点，定位必须叠加 x()/y()（多显示器场景）。"""

    def _positions_for(self, geometry):
        popup = ElaNotifyPopup()
        popup.resize(300, 80)
        popup._get_screen_geometry = lambda: QRect(*geometry)
        popup._update_positions()
        start = (popup._start_pos.x(), popup._start_pos.y())
        end = (popup._end_pos.x(), popup._end_pos.y())
        width = popup.width()
        popup.deleteLater()
        return start, end, width

    def test_primary_screen_at_origin(self, qapp):
        start, end, w = self._positions_for((0, 0, 1920, 1080))
        assert start == (1920 - w - 5, 1080)
        assert end[0] == start[0]

    def test_secondary_monitor_right(self, qapp):
        start, _, w = self._positions_for((1920, 0, 1920, 1080))
        assert start[0] == 1920 + 1920 - w - 5

    def test_secondary_monitor_left_negative_origin(self, qapp):
        start, _, w = self._positions_for((-1920, 0, 1920, 1080))
        assert start[0] == -1920 + 1920 - w - 5
        assert start[0] < 0, "负原点屏幕下弹窗起点应在负坐标区"

    def test_secondary_monitor_above_negative_origin(self, qapp):
        start, end, _ = self._positions_for((0, -1080, 1920, 1080))
        assert start[1] == -1080 + 1080
        assert end[1] >= -1080, (
            "\u7ed3\u675f\u4f4d\u7f6e\u4e0d\u80fd\u8dd1\u5230\u76ee\u6807\u5c4f\u5e55\u4e0a\u8fb9\u754c\u4e4b\u5916"
        )

    def test_end_position_never_above_screen_top(self, qapp):
        # 屏幕高度不足以容下弹窗时，结束位置必须被夹在屏幕内。
        for geom in ((0, -1080, 1920, 108), (0, 0, 1920, 40), (0, 0, 1920, 80)):
            _, end, _ = self._positions_for(geom)
            assert end[1] >= geom[1], f"geom={geom} end_y={end[1]}"
