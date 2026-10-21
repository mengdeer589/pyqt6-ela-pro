"""Tests for splash_screen module: ElaSplashScreen."""

from __future__ import annotations

import pytest
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QWidget

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
    """Qt6 字体栈冷启动（首次 ~190ms）由 splash 预热付掉，见 docs/performance.md。"""

    def test_show_schedules_warm_once(self, splash, qapp, monkeypatch):
        from _qthelpers import wait_until as _wait_until
        from pyqt6_ela_pro import splash_screen as splash_module

        calls: list[int] = []
        monkeypatch.setattr(splash_module, "_warmTextStack", lambda: calls.append(1))

        splash.show()

        _wait_until(qapp, lambda: len(calls) == 1, timeout_ms=1000)
        assert len(calls) == 1

    def test_warm_is_idempotent(self, monkeypatch):
        """重复调用只真正预热一次（第二次起近乎 0 开销）。"""
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

    def test_warm_covers_icon_font(self, monkeypatch):
        """首个 ``getElaIcon`` 要加载图标字体（未预热时 ~216ms / 已预热 ~29ms）。"""
        from pyqt6_ela_pro import splash_screen as splash_module

        calls: list = []

        class _IconSpy:
            @classmethod
            def getInstance(cls):
                return cls

            @classmethod
            def getElaIcon(cls, icon, color):
                calls.append((icon, color))
                return None

        monkeypatch.setattr(splash_module, "ElaIcon", _IconSpy)
        monkeypatch.setattr(splash_module, "_TEXT_STACK_WARMED", False)

        splash_module._warmTextStack()

        assert len(calls) == 1

    def test_warm_survives_missing_optional_deps(self, monkeypatch):
        """图标失败 / 未装 pygments 都不得让启动路径抛异常。"""
        import builtins

        from pyqt6_ela_pro import splash_screen as splash_module

        class _IconBoom:
            @classmethod
            def getInstance(cls):
                raise RuntimeError("icon unavailable")

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "pygments.lexers" or name.startswith("pygments"):
                raise ImportError("no pygments")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(splash_module, "ElaIcon", _IconBoom)
        monkeypatch.setattr(builtins, "__import__", fake_import)
        monkeypatch.setattr(splash_module, "_TEXT_STACK_WARMED", False)

        splash_module._warmTextStack()  # 不抛即通过


class TestFadeReuse:
    """F8 回归：淡出「一次性语义」的两个边界。

    旧实现把 ``_fade_timer.timeout`` 的连接放在 ``finish()`` 里（close() 之后
    再次 finish 会重复 connect → 收尾跑两遍）；且 ``show()`` 不复位
    ``_fade_settled``（复用同一实例时第二次 finish 被静默吞掉，主窗口永不显示）。
    """

    def test_finish_reusable_after_close_and_show(self, make, monkeypatch):
        # snap 路径（Reduced/Disabled 语义）→ _settleFadeOut 同步执行，免等淡出
        monkeypatch.setattr(
            "pyqt6_ela_pro.splash_screen.start_transition_timer",
            lambda timer: False,
        )
        splash = make(ElaSplashScreen)
        target1 = make(QWidget)
        target2 = make(QWidget)
        closed: list = []
        splash.closed.connect(lambda: closed.append(1))

        splash.show()
        splash.finish(target1)
        assert splash._fade_settled is True

        splash.close()
        before = len(closed)
        splash.show()  # 复用：必须复位 _fade_settled
        assert splash._fade_settled is False

        splash.finish(target2)

        assert splash._fade_settled is True
        assert len(closed) == before + 1, "第二次 finish 被上一次的 _fade_settled 吞掉"

    def test_timer_connects_once_across_finish_cycles(self, make, monkeypatch):
        monkeypatch.setattr(
            "pyqt6_ela_pro.splash_screen.start_transition_timer",
            lambda timer: True,
        )
        splash = make(ElaSplashScreen)
        target = make(QWidget)

        splash.show()
        splash.finish(target)  # 未走完的淡出
        splash.close()
        splash.show()
        splash.finish(target)  # 旧实现：这里会第二次 connect

        assert splash._fade_timer.receivers(splash._fade_timer.timeout) == 1
