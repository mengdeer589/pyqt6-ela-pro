"""Tests for dialog_base module: ElaDialogBase."""

from __future__ import annotations

from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QWidget

from pyqt6_ela_pro.dialog_base import ElaDialogBase
from PyQt6 import sip


class TestElaDialogBase:
    """Test cases for ElaDialogBase class."""

    def test_dialog_base_module_imports(self):
        """Test that dialog_base module can be imported."""
        assert ElaDialogBase is not None

    def test_import_does_not_mutate_global_theme(self, qapp):
        """import 本库不得改宿主的全局主题槽位。

        浅色 ``DialogBase`` 的调整原先写在模块级，等于「import pyqt6_ela_pro 就
        覆盖宿主配色」，而且没有 NOTIFY 信号、宿主还原不回去（``resetAccentColor``
        只管强调色）。现在写在 ``__init__`` 里，作用域限于用了本组件的对话框。
        """
        from PyQt6ElaWidgetTools import ElaThemeType, eTheme

        before = QColor(eTheme.getThemeColor(ElaThemeType.ThemeMode.Light,
                                             ElaThemeType.ThemeColor.DialogBase))
        import importlib

        importlib.reload(importlib.import_module("pyqt6_ela_pro.dialog_base"))
        after = QColor(eTheme.getThemeColor(ElaThemeType.ThemeMode.Light,
                                            ElaThemeType.ThemeColor.DialogBase))
        assert after.name() == before.name()

    def test_instance_sets_light_dialog_base(self, qapp):
        """构造本组件的对话框时，浅色 DialogBase 应被调到本组件要的浅灰白。"""
        from PyQt6ElaWidgetTools import ElaThemeType, eTheme

        parent = QWidget()
        # PyQt6 ? setThemeColor ?? None?void????? getThemeColor ??
        eTheme.setThemeColor(
            ElaThemeType.ThemeMode.Light,
            ElaThemeType.ThemeColor.DialogBase,
            QColor("#123456"),
        )
        dlg = ElaDialogBase(parent=parent)
        color = eTheme.getThemeColor(
            ElaThemeType.ThemeMode.Light, ElaThemeType.ThemeColor.DialogBase
        )
        assert QColor(color).name() == "#fafafa"
        dlg.deleteLater()
        parent.deleteLater()

    def test_create_with_default_buttons(self, qapp):
        parent = QWidget()
        dlg = ElaDialogBase(parent=parent)
        assert dlg is not None
        dlg.deleteLater()
        parent.deleteLater()

    def test_create_with_middle_text(self, qapp):
        parent = QWidget()
        dlg = ElaDialogBase(parent=parent, middleText="稍后提醒")
        assert dlg is not None
        dlg.deleteLater()
        parent.deleteLater()

    def test_set_title(self, qapp):
        parent = QWidget()
        dlg = ElaDialogBase(parent=parent)
        dlg.setTitle("测试标题")
        parent.deleteLater()

    def test_confirm_button_emits_signal(self, qapp):
        parent = QWidget()
        dlg = ElaDialogBase(parent=parent)
        fired = False

        def on_confirm():
            nonlocal fired
            fired = True

        dlg.rightButtonClicked.connect(on_confirm)
        dlg.rightButtonClicked.emit()
        assert fired
        dlg.deleteLater()
        parent.deleteLater()

    def test_middle_button_emits_signal(self, qapp):
        parent = QWidget()
        dlg = ElaDialogBase(parent=parent, middleText="稍后提醒")
        fired = False

        def on_middle():
            nonlocal fired
            fired = True

        dlg.middleButtonClicked.connect(on_middle)
        dlg.middleButtonClicked.emit()
        assert fired
        dlg.deleteLater()
        parent.deleteLater()

    def test_cancel_button_emits_signal(self, qapp):
        parent = QWidget()
        dlg = ElaDialogBase(parent=parent)
        fired = False

        def on_cancel():
            nonlocal fired
            fired = True

        dlg.leftButtonClicked.connect(on_cancel)
        dlg.leftButtonClicked.emit()
        assert fired
        dlg.deleteLater()
        parent.deleteLater()

    def test_delete_later_disconnects_middle_button(self, qapp):
        parent = QWidget()
        dlg = ElaDialogBase(parent=parent, middleText="稍后提醒")
        dlg.deleteLater()
        parent.deleteLater()

    def test_delete_later_disconnects_right_button(self, qapp):
        parent = QWidget()
        dlg = ElaDialogBase(parent=parent)
        dlg.deleteLater()
        parent.deleteLater()

    def test_multiple_dialogs_created_and_destroyed(self, qapp):
        parent = QWidget()
        dialogs = [ElaDialogBase(parent=parent) for _ in range(5)]
        for d in dialogs:
            d.deleteLater()
        parent.deleteLater()

    def test_set_param_widget_twice_keeps_widget_alive(self, qapp):
        """Regression: re-setting the same widget must not deleteLater it."""

        parent = QWidget()
        dlg = ElaDialogBase(parent=parent)
        content = QWidget()

        dlg.setParamWidget(content)
        dlg.setParamWidget(content)
        QCoreApplication.sendPostedEvents(content, QEvent.Type.DeferredDelete)
        qapp.processEvents()

        assert not sip.isdeleted(content)
        assert dlg._paramLay.indexOf(content) != -1
        dlg.deleteLater()
        parent.deleteLater()
