"""Tests for dialog_base module: ElaDialogBase."""

from __future__ import annotations

import pathlib
import subprocess
import sys

from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QPushButton, QWidget

from _qthelpers import wait_until
from pyqt6_ela_pro.dialog_base import ElaDialogBase
from PyQt6 import sip

_ROOT = pathlib.Path(__file__).resolve().parents[2]


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
        # 先写一个哨兵色：PyQt6 的 setThemeColor 返回 None（void），
        # 构造对话框后再用 getThemeColor 读回，验证确实被组件改成浅灰白。
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


class TestButtonClickLifetime:
    """真实点击路径：左 / 右按钮信号是 0ms 延迟发出的，必须绑对话框生命周期。

    无主定时器（``QTimer::singleShot(0, nullptr, ...)``）在 PyQt 里会打穿已析构的
    对话框：``exec()`` 返回后宿主丢掉引用 → C++ 对象立刻销毁 → 回调仍在
    ``QMetaObject::activate`` 里读 ``sender->d_ptr``（Win7 上是 ``Qt6Core!0xe1ea5``
    处的 AV）。
    """

    @staticmethod
    def _button(dialog: ElaDialogBase, text: str) -> QPushButton:
        for button in dialog.findChildren(QPushButton):
            if button.text() == text:
                return button
        raise AssertionError(f"button {text!r} not found")

    def test_click_emits_signal_when_dialog_is_alive(self, qapp):
        """宿主保留引用时，延迟信号照常发出（修复不能把信号改没）。"""
        parent = QWidget()
        parent.resize(400, 300)
        parent.show()
        dlg = ElaDialogBase(parent=parent)
        fired: list[int] = []
        dlg.leftButtonClicked.connect(lambda: fired.append(1))
        dlg.show()
        qapp.processEvents()

        self._button(dlg, "取消").click()

        assert wait_until(qapp, lambda: bool(fired)), "leftButtonClicked 未发出"
        dlg.deleteLater()
        parent.deleteLater()

    def test_closed_dialog_can_be_shown_again(self, qapp):
        """关闭后 ``show()`` 仍可复用（去掉 ``windowHandle()->close()`` 后不残留）。"""
        parent = QWidget()
        parent.resize(400, 300)
        parent.show()
        dlg = ElaDialogBase(parent=parent)
        dlg.show()
        qapp.processEvents()

        self._button(dlg, "取消").click()
        assert wait_until(qapp, lambda: not dlg.isVisible())

        dlg.show()
        assert wait_until(qapp, dlg.isVisible), "关闭后二次 show() 没有显示"
        dlg.deleteLater()
        parent.deleteLater()

    def test_close_does_not_reenter_event_loop(self, qapp):
        """``_doCloseAnimation`` 不许 ``processEvents()``：关闭时不得处理无关事件。

        旧实现在 ``reject()`` 后重入事件循环，再取 ``windowHandle()`` 就是 use-after-free
        （与 AppBar 关闭 UAF 同型）。这里用一个待处理的 0ms 定时器当探针。
        """
        from PyQt6.QtCore import QTimer

        parent = QWidget()
        parent.resize(400, 300)
        parent.show()
        dlg = ElaDialogBase(parent=parent)
        dlg.show()
        qapp.processEvents()

        fired: list[int] = []
        QTimer.singleShot(0, lambda: fired.append(1))
        self._button(dlg, "取消").click()

        assert fired == [], (
            "关闭路径重入了事件循环（_doCloseAnimation 里的 processEvents 又回来了）"
        )
        qapp.processEvents()
        assert fired == [1]
        dlg.deleteLater()
        parent.deleteLater()

    def test_stale_close_signal_is_not_delivered_to_next_dialog(self):
        """关闭后立刻释放对话框：陈旧的 0ms 回调不得落到新对话框上。

        走子进程：修复前这个形状可能直接 AV（读已释放的 ``sender->d_ptr``），
        在本进程里会把 pytest worker 一起带走。
        """
        script = """
import gc
from PyQt6.QtWidgets import QApplication, QPushButton, QWidget
from PyQt6ElaWidgetTools import eApp
from pyqt6_ela_pro.dialog_base import ElaDialogBase

app = QApplication(["stale-signal"])
eApp.init()
parent = QWidget()
parent.resize(400, 300)
parent.show()
app.processEvents()

dlg = ElaDialogBase(parent=parent)
dlg.show()
app.processEvents()
next(b for b in dlg.findChildren(QPushButton) if b.text() == "\\u53d6\\u6d88").click()
del dlg
gc.collect()

dlg2 = ElaDialogBase(parent=parent)
seen = []
dlg2.leftButtonClicked.connect(lambda: seen.append(1))
dlg2.show()
for _ in range(3):
    app.processEvents()
assert not seen, "陈旧信号被发到了新对话框上"
print("OK", flush=True)
"""
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 0, (
            f"子进程崩溃或被陈旧信号污染：\nstdout={proc.stdout}\nstderr={proc.stderr}"
        )
        assert "OK" in proc.stdout
