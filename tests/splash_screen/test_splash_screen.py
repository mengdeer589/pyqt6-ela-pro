"""Tests for splash_screen module: ElaSplashScreen."""

from __future__ import annotations

import pytest
from PyQt6.QtGui import QPixmap

from pyqt6_ela_pro.splash_screen import ElaSplashScreen


@pytest.fixture
def splash(make):
    """受 ``qt_cleanup`` 统一回收，测试体内不再写 ``deleteLater()``。"""
    return make(ElaSplashScreen)


def test_import_and_instantiate(splash):
    assert isinstance(splash, ElaSplashScreen)


def test_default_values(splash):
    assert splash.borderRadius() == 12
    assert splash.minimum() == 0
    assert splash.maximum() == 100
    assert splash.value() == 0


# 数值型 setter/getter 形状一致，参数化掉四条一模一样的用例
@pytest.mark.parametrize(
    ("setter", "getter", "value"),
    [
        (ElaSplashScreen.setValue, ElaSplashScreen.value, 50),
        (ElaSplashScreen.setMinimum, ElaSplashScreen.minimum, 10),
        (ElaSplashScreen.setMaximum, ElaSplashScreen.maximum, 200),
        (ElaSplashScreen.setBorderRadius, ElaSplashScreen.borderRadius, 24),
    ],
)
def test_numeric_setter_roundtrip(splash, setter, getter, value):
    setter(splash, value)
    assert getter(splash) == value


# 开关型同理：两个方向都断言，不依赖默认值（默认值另有 test_default_values 守着）
@pytest.mark.parametrize(
    ("setter", "getter"),
    [
        (ElaSplashScreen.setShowProgressBar, ElaSplashScreen.isShowProgressBar),
        (ElaSplashScreen.setShowProgressRing, ElaSplashScreen.isShowProgressRing),
        (ElaSplashScreen.setClosable, ElaSplashScreen.isClosable),
    ],
)
def test_flag_toggles_both_directions(splash, setter, getter):
    setter(splash, False)
    assert getter(splash) is False
    setter(splash, True)
    assert getter(splash) is True


# 这四个只有写没有读（源码里没有对应的 getter），能测的只有「调用不抛」。
# 参数里传工厂而不是 QPixmap 实例：parametrize 在 collection 期求值，
# 那时 QApplication 还没建，构造 QPixmap 会直接把进程带崩。
@pytest.mark.parametrize(
    ("setter", "make_arg"),
    [
        (ElaSplashScreen.setTitle, lambda: "Test App"),
        (ElaSplashScreen.setSubTitle, lambda: "Version 1.0"),
        (ElaSplashScreen.setStatusText, lambda: "正在加载..."),
        (ElaSplashScreen.setLogo, QPixmap),
    ],
    ids=["title", "subtitle", "status", "logo"],
)
def test_write_only_setters_do_not_raise(splash, setter, make_arg):
    setter(splash, make_arg())


def test_delete_later_cleans_up(splash):
    """显式销毁路径仍要能用（与 make() 的统一回收互不干扰）。"""
    splash.deleteLater()


class TestWarmTextStack:
    """Qt6 ???????????splash ?????????????? docs/performance.md??"""

    def test_show_schedules_warm_once(self, splash, qapp, monkeypatch):
        from _qthelpers import wait_until as _wait_until
        from pyqt6_ela_pro import splash_screen as splash_module

        calls: list[int] = []
        monkeypatch.setattr(splash_module, "_warmTextStack", lambda: calls.append(1))

        splash.show()

        _wait_until(qapp, lambda: len(calls) == 1, timeout_ms=1000)
        assert len(calls) == 1

    def test_warm_is_idempotent(self, monkeypatch):
        """????????????????? 0.0x ms??"""
        from pyqt6_ela_pro import splash_screen as splash_module

        counts = {"n": 0}

        class _FakeFont:
            def defaultFamily(self):
                counts["n"] += 1
                return "Fake"

        monkeypatch.setattr(splash_module, "QFont", lambda: _FakeFont())
        monkeypatch.setattr(splash_module, "_TEXT_STACK_WARMED", False)

        splash_module._warmTextStack()
        splash_module._warmTextStack()

        assert counts["n"] == 1
