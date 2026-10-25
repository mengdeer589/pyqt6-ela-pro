from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget

from pyqt6_ela_pro.ela_toast import ElaToast, ElaToastType


class TestElaToastInit:
    def test_initialization_with_defaults(self):
        toast = ElaToast(ElaToastType.Info, "提示信息", 2000)
        assert toast._border_radius == 8
        assert toast._display_msec == 2000
        assert toast._toast_type == ElaToastType.Info
        assert toast._text == "提示信息"
        assert toast._shadow_border == 4
        toast.close()
        toast.deleteLater()

    def test_frameless_window_hint(self):
        toast = ElaToast(ElaToastType.Success, "成功", 2000)
        flags = toast.windowFlags()
        assert flags & Qt.WindowType.FramelessWindowHint
        toast.close()
        toast.deleteLater()

    def test_translucent_background(self):
        toast = ElaToast(ElaToastType.Success, "成功", 2000)
        assert toast.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        toast.close()
        toast.deleteLater()

    def test_delete_on_close(self):
        toast = ElaToast(ElaToastType.Success, "成功", 2000)
        assert toast.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        toast.close()
        toast.deleteLater()

    def test_fixed_size(self):
        toast = ElaToast(ElaToastType.Success, "成功", 2000)
        assert toast.height() == 48
        toast.close()
        toast.deleteLater()


class TestElaToastType:
    def test_success_type_enum(self):
        assert ElaToastType.Success == 0

    def test_info_type_enum(self):
        assert ElaToastType.Info == 1

    def test_warning_type_enum(self):
        assert ElaToastType.Warning == 2

    def test_error_type_enum(self):
        assert ElaToastType.Error == 3


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
        toast = ElaToast(ElaToastType.Info, "测试", 2000)
        toast._run_animation()
        assert toast._fade_in is not None
        toast.close()
        toast.deleteLater()
