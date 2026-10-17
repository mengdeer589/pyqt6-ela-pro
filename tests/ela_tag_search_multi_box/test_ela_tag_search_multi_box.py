"""``ElaTagSearchMultiBox`` 测试：初值 / 动画 / 展开属性 / 标题 / 弹层辅助 / 拼音搜索。"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPropertyAnimation

from pyqt6_ela_pro._motion import Duration
from pyqt6_ela_pro.combo_box import ElaSearchMultiBox
from pyqt6_ela_pro.ela_tag_combo_base import _get_target_mark_width, _pre_init_popup
from pyqt6_ela_pro.ela_tag_search_multi_box import ElaTagSearchMultiBox


@pytest.fixture
def box(make):
    """默认构造的 tag search multi box（空标题）。"""
    return make(ElaTagSearchMultiBox)


class TestElaTagSearchMultiBoxInit:
    @pytest.mark.parametrize(
        ("attr", "expected"),
        [("_title_text", ""), ("_title_font_size", 13)],
        ids=["title", "title-font-size"],
    )
    def test_initialization_with_defaults(self, box, attr, expected):
        assert getattr(box, attr) == expected

    def test_initialization_with_title(self, make):
        assert make(ElaTagSearchMultiBox, title="语言")._title_text == "语言"

    def test_fixed_height_is_30(self, box):
        """与上游 ElaComboBox V3.0（35→30）的触发框同高。"""
        assert box.height() == 30

    def test_max_visible_items_is_10(self, box):
        assert box.maxVisibleItems() == 10

    def test_inherits_from_search_multi_box(self, box):
        """继承的搜索 + 多选能力不能被 tag 外观盖掉。"""
        assert isinstance(box, ElaSearchMultiBox)


class TestElaTagSearchMultiBoxAnimations:
    @pytest.mark.parametrize(
        "attr", ["_mark_animation", "_rotate_animation"], ids=["mark", "rotate"]
    )
    def test_has_animation(self, box, attr):
        assert hasattr(box, attr)
        assert isinstance(getattr(box, attr), QPropertyAnimation)

    def test_mark_animation_duration_uses_normal_token(self, box, motion_full):
        assert box._mark_animation.duration() == Duration.Normal


class TestElaTagSearchMultiBoxExpandProperties:
    @pytest.mark.parametrize(
        ("prop", "value"),
        [("expandMarkWidth", 50.0), ("expandIconRotate", -180.0)],
        ids=["mark-width", "icon-rotate"],
    )
    def test_expand_property_roundtrip(self, box, prop, value):
        setattr(box, prop, value)
        assert getattr(box, prop) == value


class TestElaTagSearchMultiBoxTitle:
    def test_set_title(self, box):
        box.setTitle("新标题")
        assert box._title_text == "新标题"

    def test_title_returns_current_title(self, make):
        assert make(ElaTagSearchMultiBox, title="测试").title() == "测试"


class TestElaTagSearchMultiBoxHelpers:
    def test_get_target_mark_width_empty(self, box):
        """没有选项时标记宽度应为 0。"""
        assert _get_target_mark_width(box) == 0.0

    def test_pre_init_popup_runs_safely(self, box):
        """_pre_init_popup 必须在未创建弹层时也不报错。"""
        _pre_init_popup(box)


class TestElaTagSearchMultiBoxSelection:
    """``setCurrentSelection`` 与 :class:`ElaTagMultiBox` 同款：吃 str 或 list。"""

    @pytest.fixture
    def filled(self, make):
        box = make(ElaTagSearchMultiBox, title="语言")
        box.addItems(["Python", "C++", "北京"])
        return box

    def test_single_string_is_one_selection(self, filled):
        filled.setCurrentSelection("Python")
        assert filled.currentSelection() == ["Python"]

    def test_list_selection(self, filled):
        filled.setCurrentSelection(["Python", "北京"])
        assert sorted(filled.currentSelection()) == sorted(["Python", "北京"])

    def test_string_is_not_split_into_characters(self, filled):
        """回归：基类 ``list(selection)`` 会把 "Python" 拆成 6 个字母。"""
        filled.setCurrentSelection("C++")
        assert filled.currentSelection() == ["C++"]


class TestElaTagSearchMultiBoxPinyinSearch:
    def test_search_matches_pinyin_initials(self, make):
        """继承来的搜索按拼音首字母过滤行。"""
        box = make(ElaTagSearchMultiBox, title="语言")
        box.addItems(["北京", "上海"])

        box._onSearchTextChanged("bj")
        view = box.view()

        assert view.isRowHidden(0) is False
        assert view.isRowHidden(1) is True
