"""``ElaTimeline`` 测试：初值 / TimelineItem / 增删 / 当前节点 / 方向 / sizeHint / 主题。"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QSize
from PyQt6ElaWidgetTools import ElaIconType, ElaThemeType

from pyqt6_ela_pro.ela_timeline import ElaTimeline


@pytest.fixture
def t(make):
    return make(ElaTimeline)


def _item(**kwargs) -> ElaTimeline.TimelineItem:
    return ElaTimeline.TimelineItem(**kwargs)


class TestElaTimelineInit:
    @pytest.mark.parametrize(
        ("attr", "expected"),
        [
            ("_items", []),
            ("_current_step", 0),
        ],
    )
    def test_initialization_with_defaults(self, t, attr, expected):
        assert getattr(t, attr) == expected

    def test_object_name(self, t):
        assert t.objectName() == "ElaTimeline"


class TestElaTimelineItem:
    @pytest.mark.parametrize(
        ("attr", "expected"),
        [
            ("title", ""),
            ("content", ""),
            ("timestamp", ""),
            ("icon", ElaIconType.IconName.None_),
        ],
    )
    def test_timeline_item_defaults(self, attr, expected):
        assert getattr(_item(), attr) == expected

    @pytest.mark.parametrize(
        ("attr", "expected"),
        [
            ("title", "事件"),
            ("content", "描述"),
            ("timestamp", "2024-01-01"),
            ("icon", ElaIconType.IconName.Check),
        ],
    )
    def test_timeline_item_with_values(self, attr, expected):
        item = _item(
            title="事件",
            content="描述",
            timestamp="2024-01-01",
            icon=ElaIconType.IconName.Check,
        )
        assert getattr(item, attr) == expected


class TestElaTimelineAddItem:
    @pytest.mark.parametrize("titles", [["A"], ["A", "B", "C"]], ids=["one", "three"])
    def test_add_item(self, t, titles):
        for title in titles:
            t.addItem(_item(title=title))
        assert t.itemCount() == len(titles)


class TestElaTimelineClearItems:
    def test_clear_items(self, t):
        t.addItem(_item(title="A"))
        t.addItem(_item(title="B"))
        t.clearItems()
        assert t.itemCount() == 0


class TestElaTimelineItemCount:
    def test_item_count_default(self, t):
        assert t.itemCount() == 0

    def test_item_count_after_add(self, t):
        t.addItem(_item())
        assert t.itemCount() == 1


class TestElaTimelineCurrentStep:
    def test_current_step_default(self, t):
        assert t.currentStep() == 0

    @pytest.mark.parametrize(
        ("item_count", "requested", "expected"),
        [
            (2, 1, 1),
            (1, -1, 0),
            (1, 10, 0),
            (0, 5, 0),
        ],
        ids=["in-range", "below-min", "above-max", "empty-items"],
    )
    def test_set_current_step(self, t, item_count, requested, expected):
        for _ in range(item_count):
            t.addItem(_item())
        t.setCurrentStep(requested)
        assert t.currentStep() == expected


class TestElaTimelineSizeHint:
    def test_size_hint_empty(self, t):
        assert t.sizeHint() == QSize(400, 0)

    def test_size_hint_with_items(self, t):
        t.addItem(_item(title="事件"))
        assert t.sizeHint().height() > 0


class TestElaTimelineOrientation:
    def test_default_is_vertical(self, t):
        assert t.orientation() == "vertical"

    @pytest.mark.parametrize("orientation", ["vertical", "horizontal"])
    def test_round_trip(self, t, orientation):
        t.setOrientation(orientation)
        assert t.orientation() == orientation

    def test_invalid_orientation_raises(self, t):
        with pytest.raises(ValueError, match="orientation"):
            t.setOrientation("diagonal")

    @pytest.mark.parametrize("orientation", ["vertical", "horizontal"])
    def test_size_hint_with_items(self, t, orientation):
        t.setOrientation(orientation)
        t.addItem(_item(title="事件", content="描述"))
        assert t.sizeHint().height() > 0

    @pytest.mark.parametrize("orientation", ["vertical", "horizontal"])
    def test_paint_smoke(self, qapp, t, orientation):
        t.setOrientation(orientation)
        t.addItem(
            _item(
                title="创建项目",
                content="项目框架初始化完成",
                timestamp="2024-01-01",
                icon=ElaIconType.IconName.FloppyDisk,
            )
        )
        t.addItem(
            _item(title="开发阶段", content="核心功能开发中", timestamp="2024-02-15")
        )
        t.setCurrentStep(1)
        t.resize(480, 200)
        t.show()
        qapp.processEvents()
        assert not t.grab().isNull()


class TestElaTimelineTheme:
    def test_on_theme_changed_updates_mode(self, t):
        t._onThemeChanged(ElaThemeType.ThemeMode.Dark)
        assert t._theme_mode == ElaThemeType.ThemeMode.Dark


class TestElaTimelineDeleteLater:
    def test_delete_later_cleans_up(self, t):
        t.deleteLater()
