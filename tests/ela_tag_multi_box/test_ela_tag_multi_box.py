"""``ElaTagMultiBox`` 测试：初值 / 动画 / 展开属性 / 标题 / 弹层辅助函数。"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPropertyAnimation

from pyqt6_ela_pro._motion import Duration
from pyqt6_ela_pro.ela_tag_combo_base import _get_target_mark_width, _pre_init_popup
from pyqt6_ela_pro.ela_tag_multi_box import ElaTagMultiBox


@pytest.fixture
def box(make):
    """默认构造的 tag multi box（空标题）。"""
    return make(ElaTagMultiBox)


class TestElaTagMultiBoxInit:
    @pytest.mark.parametrize(
        ("attr", "expected"),
        [
            ("_title_text", ""),
            ("_expand_mark_width", 0.0),
            ("_title_font_size", 13),
        ],
        ids=["title", "mark-width", "title-font-size"],
    )
    def test_initialization_with_defaults(self, box, attr, expected):
        assert getattr(box, attr) == expected

    def test_initialization_with_title(self, make):
        assert make(ElaTagMultiBox, title="语言")._title_text == "语言"

    def test_fixed_height_is_30(self, box):
        """与上游 ElaComboBox V3.0（35→30）的触发框同高。"""
        assert box.height() == 30

    def test_max_visible_items_is_10(self, box):
        assert box.maxVisibleItems() == 10


class TestElaTagMultiBoxAnimations:
    def test_has_mark_animation(self, box):
        assert hasattr(box, "_mark_animation")
        assert isinstance(box._mark_animation, QPropertyAnimation)

    def test_mark_animation_duration_uses_normal_token(self, box, motion_full):
        assert box._mark_animation.duration() == Duration.Normal


class TestElaTagMultiBoxExpandProperties:
    @pytest.mark.parametrize(
        ("prop", "value"),
        [("expandMarkWidth", 50.0), ("expandIconRotate", -180.0)],
        ids=["mark-width", "icon-rotate"],
    )
    def test_expand_property_roundtrip(self, box, prop, value):
        setattr(box, prop, value)
        assert getattr(box, prop) == value


class TestElaTagMultiBoxTitle:
    def test_set_title(self, box):
        box.setTitle("新标题")
        assert box._title_text == "新标题"

    def test_title_returns_current_title(self, make):
        assert make(ElaTagMultiBox, title="测试").title() == "测试"


class TestElaTagMultiBoxHelpers:
    def test_get_target_mark_width_empty(self, box):
        """没有选项时标记宽度应为 0。"""
        assert _get_target_mark_width(box) == 0.0

    def test_pre_init_popup_runs_safely(self, box):
        """_pre_init_popup 必须在未创建弹层时也不报错。"""
        _pre_init_popup(box)
