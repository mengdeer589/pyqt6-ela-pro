"""``ElaSpotlight`` 测试：初值 / 步骤 / 导航 / 目标矩形 / 主题。"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QWidget
from PyQt6ElaWidgetTools import ElaThemeType, eTheme

from pyqt6_ela_pro.ela_spotlight import ElaSpotlight


@pytest.fixture
def parent(make):
    return make(QWidget)


@pytest.fixture
def s(make, parent):
    return make(ElaSpotlight, parent)


@pytest.fixture
def steps(make):
    """两个已配好的步骤对象（target 挂在独立 parent 上）。"""
    return [ElaSpotlight.SpotlightStep(make(QWidget)) for _ in range(2)]


class TestElaSpotlightInit:
    @pytest.mark.parametrize(
        ("attr", "expected"),
        [
            ("_border_radius", 8),
            ("_padding", 8),
            ("_overlay_alpha", 120),
            ("_is_circle", False),
            ("_title", ""),
            ("_content", ""),
            ("_is_active", False),
            ("_current_step", -1),
            ("_steps", []),
        ],
    )
    def test_initialization_with_defaults(self, s, attr, expected):
        assert getattr(s, attr) == expected

    def test_hidden_by_default(self, s):
        assert s.isVisible() is False

    @pytest.mark.parametrize("name", ["stepChanged", "finished"])
    def test_declares_signal(self, s, name):
        assert callable(getattr(s, name))

    def test_spotlight_step_dataclass(self, make):
        target = make(QWidget)
        step = ElaSpotlight.SpotlightStep(
            target, title="标题", content="内容", is_circle=True
        )
        assert step.target is target
        assert step.title == "标题"
        assert step.content == "内容"
        assert step.is_circle is True


class TestElaSpotlightSteps:
    def test_show_spotlight_sets_single_step(self, make, s):
        target = make(QWidget, s.parent())
        with pytest.MonkeyPatch.context() as m:
            m.setattr(s, "start", lambda: None)
            s.showSpotlight(target, "知道了")
            assert len(s._steps) == 1
            assert s._prev_btn.isVisible() is False
            assert s._next_btn.text() == "知道了"

    def test_set_steps(self, s, steps):
        s.setSteps(steps)
        assert len(s._steps) == 2

    def test_step_count(self, s, steps):
        s.setSteps(steps)
        assert s.stepCount() == 2


class TestElaSpotlightNavigation:
    def test_current_step_initially_negative_one(self, s):
        assert s.currentStep() == -1

    @pytest.mark.parametrize("method", ["next", "previous"])
    def test_navigation_noop_when_not_started(self, s, method):
        getattr(s, method)()
        assert s.currentStep() == -1

    def test_finish_emits_finished(self, s):
        received = []
        s.finished.connect(lambda: received.append(True))
        s.finish()
        assert received == [True]

    def test_finish_hides_widget(self, s):
        s.finish()
        assert s.isVisible() is False

    def test_finish_clears_active(self, s):
        s._is_active = True
        s.finish()
        assert s._is_active is False


class TestElaSpotlightTargetRect:
    def test_get_target_rect_none_target(self, s):
        assert s._getTargetRect(None).isNull()

    def test_get_target_rect_no_parent(self, make):
        """无 parent 的 target 拿不到几何信息。"""
        target = make(QWidget)
        assert make(ElaSpotlight)._getTargetRect(target).isEmpty()


class TestElaSpotlightTheme:
    def test_on_theme_changed_updates_mode(self, s):
        s._onThemeChanged(ElaThemeType.ThemeMode.Dark)
        assert s._theme_mode == ElaThemeType.ThemeMode.Dark

    def test_tip_card_repaints_on_theme_switch(self, s, make, qapp):
        """回归：卡片配色原先缓存、只在重定位时刷新，开着遮罩切主题会停在旧色。

        判据读**落地像素**（重构后卡片没有内部缓存可断言）：实心圆角卡片在
        windows / offscreen 都会真实渲染，不像文字像素那样需要 skip。
        """
        parent = s.parent()
        parent.resize(800, 600)
        target = make(QWidget, parent)
        s.setSteps([ElaSpotlight.SpotlightStep(target, "标题", "内容")])
        s.start()

        previous = eTheme.getThemeMode()
        try:
            eTheme.setThemeMode(ElaThemeType.ThemeMode.Light)
            qapp.processEvents()
            image = s._tip_widget.grab().toImage()
            light = image.pixelColor(image.width() // 2, 6)  # 顶边内侧，避开文字
            eTheme.setThemeMode(ElaThemeType.ThemeMode.Dark)
            qapp.processEvents()
            image = s._tip_widget.grab().toImage()
            dark = image.pixelColor(image.width() // 2, 6)
        finally:
            eTheme.setThemeMode(previous)

        assert light.name() != dark.name(), "卡片没有跟着主题重绘"
        assert dark.lightness() < light.lightness()


class TestElaSpotlightDeleteLater:
    def test_delete_later_cleans_up(self, make, parent):
        make(ElaSpotlight, parent).deleteLater()
