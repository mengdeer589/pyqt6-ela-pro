from __future__ import annotations

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QEnterEvent
from PyQt6.QtWidgets import QWidget

from pyqt6_ela_pro import ElaSeverity
from pyqt6_ela_pro._styles import SHADOW_MARGIN
from pyqt6_ela_pro.ela_toast import _LIVE_TOASTS, _TOAST_GAP, ElaToast


class TestElaToastInit:
    def test_initialization_with_defaults(self):
        toast = ElaToast(ElaSeverity.Info, "提示信息", 2000)
        assert toast._border_radius == 8
        assert toast._display_msec == 2000
        assert toast._severity == ElaSeverity.Info
        assert toast._text == "提示信息"
        assert toast._shadow_border == 4
        toast.close()
        toast.deleteLater()

    def test_frameless_window_hint(self):
        toast = ElaToast(ElaSeverity.Success, "成功", 2000)
        flags = toast.windowFlags()
        assert flags & Qt.WindowType.FramelessWindowHint
        toast.close()
        toast.deleteLater()

    def test_translucent_background(self):
        toast = ElaToast(ElaSeverity.Success, "成功", 2000)
        assert toast.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        toast.close()
        toast.deleteLater()

    def test_delete_on_close(self):
        toast = ElaToast(ElaSeverity.Success, "成功", 2000)
        assert toast.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        toast.close()
        toast.deleteLater()

    def test_fixed_size(self):
        toast = ElaToast(ElaSeverity.Success, "成功", 2000)
        assert toast.height() == 48
        toast.close()
        toast.deleteLater()


class TestElaSeverity:
    def test_info_enum(self):
        assert ElaSeverity.Info == 0

    def test_success_enum(self):
        assert ElaSeverity.Success == 1

    def test_warning_enum(self):
        assert ElaSeverity.Warning == 2

    def test_error_enum(self):
        assert ElaSeverity.Error == 3


class TestElaToastStaticMethods:
    def test_success_creates_instance(self):
        ElaToast.success("操作成功", display_msec=100)
        # Just verify no exception; the toast auto-closes after display_msec

    def test_info_creates_instance(self):
        ElaToast.info("提示信息", display_msec=100)

    def test_warning_creates_instance(self):
        ElaToast.warning("警告", display_msec=100)

    def test_error_creates_instance(self):
        ElaToast.error("发生错误", display_msec=100)

    def test_success_with_parent(self):
        parent = QWidget()
        ElaToast.success("成功", display_msec=100, parent=parent)
        parent.deleteLater()

    def test_info_with_parent(self):
        parent = QWidget()
        ElaToast.info("信息", display_msec=100, parent=parent)
        parent.deleteLater()


class TestElaToastAnimation:
    def test_run_animation_creates_fade_in(self):
        toast = ElaToast(ElaSeverity.Info, "测试", 2000)
        toast._run_animation()
        assert toast._fade_in is not None
        toast.close()
        toast.deleteLater()


class TestElaToastLayout:
    def test_long_text_is_elided(self, qapp):
        long_text = "很长的通知文字" * 20
        toast = ElaToast(ElaSeverity.Info, long_text, 1000)
        try:
            assert toast._elided_text.endswith("…")
            assert len(toast._elided_text) < len(long_text)
        finally:
            toast.close()
            toast.deleteLater()

    def test_stack_gap_excludes_shadow_margin(self, qapp):
        _LIVE_TOASTS.clear()
        first = ElaToast(ElaSeverity.Info, "a", 1000)
        second = ElaToast(ElaSeverity.Info, "b", 1000)
        try:
            assert second.pos().y() - first.pos().y() == (
                first.height() - 2 * SHADOW_MARGIN + _TOAST_GAP
            )
        finally:
            first.close()
            second.close()
            first.deleteLater()
            second.deleteLater()
            _LIVE_TOASTS.clear()


class TestElaToastHover:
    def test_hover_pauses_and_resumes_dwell_timer(self, qapp):
        toast = ElaToast(ElaSeverity.Info, "提示", 1000)
        toast._present()
        toast._dwell_timer.start(1000)
        toast.enterEvent(QEnterEvent(QPointF(0, 0), QPointF(0, 0), QPointF(0, 0)))
        assert not toast._dwell_timer.isActive()
        toast.leaveEvent(QEvent(QEvent.Type.Leave))
        assert toast._dwell_timer.isActive()
        toast._dwell_timer.stop()
        toast.close()
        toast.deleteLater()
