"""``ElaSteps`` 测试：初值 / 当前步夹取 / 标题列表 / 前进后退 / 方向 / 主题。"""

from __future__ import annotations

import pytest
from PyQt6ElaWidgetTools import ElaThemeType

from pyqt6_ela_pro.ela_steps import ElaSteps

_FIVE = ["A", "B", "C", "D", "E"]
_THREE = ["A", "B", "C"]


@pytest.fixture
def s(make):
    return make(ElaSteps)


class TestElaStepsInit:
    @pytest.mark.parametrize(
        ("attr", "expected"),
        [
            ("_current_step", 0),
            ("_step_titles", []),
        ],
    )
    def test_initialization_with_defaults(self, s, attr, expected):
        assert getattr(s, attr) == expected

    def test_step_count_defaults_to_one(self, s):
        assert s.step_count == 1

    def test_has_current_step_changed_signal(self, s):
        assert hasattr(s, "currentStepChanged")
        assert callable(s.currentStepChanged)

    def test_fixed_height(self, s):
        assert s.height() == 70


class TestElaStepsCurrentStep:
    def test_current_step_default(self, s):
        assert s.currentStep() == 0

    def test_set_current_step(self, s):
        s.step_titles = _THREE
        s.setCurrentStep(1)
        assert s.currentStep() == 1

    @pytest.mark.parametrize(
        ("requested", "expected"),
        [(-1, 0), (10, 2)],
        ids=["below-min", "above-max"],
    )
    def test_set_current_step_clamps(self, s, requested, expected):
        s.step_titles = _THREE
        s.setCurrentStep(requested)
        assert s.currentStep() == expected

    def test_set_current_step_emits_signal(self, s):
        s.step_titles = _THREE
        received = []
        s.currentStepChanged.connect(lambda v: received.append(v))
        s.setCurrentStep(2)
        assert 2 in received

    def test_set_current_step_same_value_no_emit(self, s):
        s.step_titles = _THREE
        s.setCurrentStep(0)
        received = []
        s.currentStepChanged.connect(lambda v: received.append(v))
        s.setCurrentStep(0)
        assert len(received) == 0


class TestElaStepsStepTitles:
    def test_step_titles_default(self, s):
        assert s.step_titles == []

    def test_set_step_titles(self, s):
        s.step_titles = ["步骤一", "步骤二", "步骤三"]
        assert s.step_titles == ["步骤一", "步骤二", "步骤三"]

    @pytest.mark.parametrize(
        ("titles", "expected"),
        [([], 1), (["A", "B"], 2)],
        ids=["empty", "two-titles"],
    )
    def test_step_count_derives_from_titles(self, s, titles, expected):
        s.step_titles = titles
        assert s.step_count == expected

    def test_set_step_titles_corrects_current_step(self, s):
        s.step_titles = _THREE
        s.setCurrentStep(2)
        s.step_titles = ["X"]
        assert s.currentStep() == 0

    def test_step_titles_returns_copy(self, s):
        s.step_titles = ["A", "B"]
        titles = s.step_titles
        titles.append("C")
        assert s.step_titles == ["A", "B"]


class TestElaStepsNavigation:
    @pytest.mark.parametrize(
        ("titles", "start", "navs", "expected"),
        [
            (_FIVE, None, ["next"], 1),
            (["A", "B"], None, ["next", "next"], 1),
            (_FIVE, 3, ["previous"], 2),
            ([], None, ["previous"], 0),
        ],
        ids=["next", "next-clamped-at-max", "previous", "previous-clamped-at-min"],
    )
    def test_navigation(self, s, titles, start, navs, expected):
        s.step_titles = titles
        if start is not None:
            s.setCurrentStep(start)
        for name in navs:
            getattr(s, name)()
        assert s.currentStep() == expected

    @pytest.mark.parametrize(
        ("start", "nav", "emitted"),
        [(None, "next", 1), (3, "previous", 2)],
        ids=["next", "previous"],
    )
    def test_navigation_emits_signal(self, s, start, nav, emitted):
        s.step_titles = _FIVE
        if start is not None:
            s.setCurrentStep(start)
        received = []
        s.currentStepChanged.connect(received.append)
        getattr(s, nav)()
        assert emitted in received


class TestElaStepsOrientation:
    def test_default_is_horizontal(self, s):
        assert s.orientation() == "horizontal"
        assert s.height() == 70

    @pytest.mark.parametrize("orientation", ["horizontal", "vertical"])
    def test_round_trip(self, s, orientation):
        s.step_titles = _THREE
        s.setOrientation(orientation)
        assert s.orientation() == orientation

    def test_invalid_orientation_raises(self, s):
        with pytest.raises(ValueError, match="orientation"):
            s.setOrientation("diagonal")

    def test_vertical_height_grows_with_steps(self, s):
        s.setOrientation("vertical")
        heights = []
        for count in (1, 2, 3):
            s.step_titles = ["标题"] * count
            heights.append(s.height())
        assert heights[0] < heights[1] < heights[2]
        # 行距恒定：每多一步加的高度相同
        assert heights[1] - heights[0] == heights[2] - heights[1]

    def test_switching_back_restores_horizontal_height(self, s):
        s.step_titles = _THREE
        s.setOrientation("vertical")
        assert s.height() > 70
        s.setOrientation("horizontal")
        assert s.orientation() == "horizontal"
        assert s.height() == 70

    @pytest.mark.parametrize("orientation", ["horizontal", "vertical"])
    def test_paint_smoke(self, qapp, s, orientation):
        s.step_titles = _THREE
        s.setCurrentStep(1)
        s.setOrientation(orientation)
        s.resize(320, s.height())
        s.show()
        qapp.processEvents()
        assert not s.grab().isNull()


class TestElaStepsTheme:
    def test_on_theme_changed_updates_mode(self, s):
        s._onThemeChanged(ElaThemeType.ThemeMode.Dark)
        assert s._theme_mode == ElaThemeType.ThemeMode.Dark


class TestElaStepsDeleteLater:
    def test_delete_later_cleans_up(self, s):
        s.deleteLater()
