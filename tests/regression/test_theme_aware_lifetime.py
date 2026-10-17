"""``_ThemeAwareMixin`` 的连接 / 清理契约。

两个真实 bug 的回归守护，都是「Qt 回调内异常 → 0xC0000409 静默终止」那一类：

1. **``destroyed`` 连的是绑方法就等于没连**。PyQt5 不会调用「绑定到自身」的
   ``destroyed`` 槽（实测 ``sip.delete()``：绑方法 0 次、lambda / 模块级函数
   各 1 次）。原实现正是 ``self.destroyed.connect(self._theme_cleanup)``，
   于是**清理从来没发生过** —— 控件销毁后 ``eTheme.themeModeChanged`` 仍会
   打进已释放的包装器。
2. **不能依赖 ``destroyed`` 一定送达**。所以主题槽本身还带 ``sip.isdeleted()``
   自愈：命中就顺手把自己断开。

外加一条 ``ElaPlainTextEdit`` 的 API 事实：它**没有** ``setTextColor``。在主题
切换的信号链上写那行等于「切一次主题崩一次」（``AttributeError`` 穿过 C++ 边界）。
"""

from __future__ import annotations

import gc

import pytest
from PyQt6 import sip
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6ElaWidgetTools import ElaPlainTextEdit, ElaThemeType, eTheme

from pyqt6_ela_pro import _internal
from pyqt6_ela_pro._internal import _ThemeAwareMixin


class Probe(_ThemeAwareMixin, QWidget):
    """最小探针：记录 ``_onThemeChanged`` 被调用了几次。"""

    def __init__(self, parent=None):
        self.hits = 0
        super().__init__(parent)

    def _onThemeChanged(self, mode) -> None:
        self.hits += 1
        self._theme_mode = mode


@pytest.fixture
def restore_mode():
    previous = eTheme.getThemeMode()
    yield
    eTheme.setThemeMode(previous)


def _flip(mode) -> None:
    eTheme.setThemeMode(mode)
    QApplication.instance().processEvents()


class TestThemeSlotLifetime:
    def test_slot_is_stored_on_instance(self, qapp):
        """槽必须是**同一个对象**，否则 ``disconnect`` 对不上身份。"""
        probe = Probe()
        assert probe._theme_slot is not None
        assert probe._theme_connected
        probe._theme_cleanup()

    def test_receives_theme_changes(self, qapp, restore_mode):
        probe = Probe()
        _flip(ElaThemeType.ThemeMode.Dark)
        assert probe.hits == 1
        _flip(ElaThemeType.ThemeMode.Light)
        assert probe.hits == 2

    def test_destroyed_disconnects(self, qapp, make, restore_mode):
        """销毁后**不该**再收到主题变化。"""
        probe = make(Probe)
        probe.setParent(None)
        sip.delete(probe)
        assert sip.isdeleted(probe)
        _flip(ElaThemeType.ThemeMode.Dark)  # 命中自愈分支，不该崩
        _flip(ElaThemeType.ThemeMode.Light)

    def test_survives_stale_wrapper(self, qapp, make, restore_mode):
        """包装器还活着、C++ 已销毁的情形（lambda 闭包持有引用时的常态）。"""
        probe = make(Probe)
        probe.setParent(None)
        sip.delete(probe)
        gc.collect()
        # 显式再触发一次：自愈槽应当安静地把自己断开
        probe._theme_slot(ElaThemeType.ThemeMode.Dark)
        assert probe._theme_slot is not None or not probe._theme_connected

    def test_explicit_cleanup_is_idempotent(self, qapp, make):
        probe = make(Probe)
        probe._theme_cleanup()
        probe._theme_cleanup()
        assert not probe._theme_connected

    def test_init_theme_aware_is_idempotent(self, qapp, make):
        """重复 init 不得连两次（否则一次切主题触发两遍）。"""
        probe = make(Probe)
        probe._init_theme_aware()
        _flip(ElaThemeType.ThemeMode.Dark)
        assert probe.hits == 1

    def test_class_level_defaults_exist(self, qapp):
        """``_init_theme_aware`` 在 ``__init__`` 链最上游就要读它们。"""
        assert _ThemeAwareMixin._theme_connected is False
        assert _ThemeAwareMixin._theme_slot is None

    def test_trampoline_is_module_level(self):
        """``destroyed`` 槽必须是模块级函数（绑方法 PyQt5 不调）。"""
        assert callable(_internal._disconnect_theme_on_destroy)
        assert not hasattr(_internal._disconnect_theme_on_destroy, "__self__")


class TestElaPlainTextEditApi:
    """``ElaPlainTextEdit`` 的 API 事实（别再写 ``setTextColor``）。"""

    @staticmethod
    def _editor(qapp, make):
        """挂在宿主上建：裸的顶层 ``ElaPlainTextEdit`` 析构时会踩 access
        violation（``qt_cleanup`` 的 ``deleteLater`` 赶不上它的 C++ 析构）。"""
        host = make(QWidget)
        editor = make(ElaPlainTextEdit, host)
        editor.resize(300, 40)
        return host, editor

    def test_has_no_set_text_color(self, qapp, make):
        """它**没有** ``setTextColor`` —— 写上去就是主题切换必崩。"""
        _, editor = self._editor(qapp, make)
        assert not hasattr(editor, "setTextColor")

    def test_palette_color_survives_text_change(self, qapp, make):
        """用 palette 上色且**能留住**（不像 ``ElaText`` 会重置 palette）。"""
        _, editor = self._editor(qapp, make)
        palette = editor.palette()
        role = editor.foregroundRole()
        palette.setColor(role, QColor("#ff0000"))
        editor.setPalette(palette)
        editor.setPlainText("hello")
        assert editor.palette().color(role) == QColor("#ff0000")
