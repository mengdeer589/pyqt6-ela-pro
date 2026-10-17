"""``ElaTagSearchBox`` 测试：初值 / 动画 / 展开属性 / 标题 / 拼音搜索。"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPropertyAnimation

from pyqt6_ela_pro._motion import Duration
from pyqt6_ela_pro.combo_box import ElaSearchBox
from pyqt6_ela_pro.ela_tag_search_box import ElaTagSearchBox


@pytest.fixture
def box(make):
    """默认构造的 tag search box（空标题）。"""
    return make(ElaTagSearchBox)


class TestElaTagSearchBoxInit:
    @pytest.mark.parametrize(
        ("attr", "expected"),
        [("_title_text", ""), ("_title_font_size", 13)],
        ids=["title", "title-font-size"],
    )
    def test_initialization_with_defaults(self, box, attr, expected):
        assert getattr(box, attr) == expected

    def test_initialization_with_title(self, make):
        assert make(ElaTagSearchBox, title="语言")._title_text == "语言"

    def test_fixed_height_is_30(self, box):
        """与上游 ElaComboBox V3.0（35→30）的触发框同高。"""
        assert box.height() == 30

    def test_inherits_from_search_box(self, box):
        """继承的搜索能力不能被 tag 外观盖掉。"""
        assert isinstance(box, ElaSearchBox)


class TestElaTagSearchBoxAnimations:
    @pytest.mark.parametrize(
        "attr", ["_mark_animation", "_rotate_animation"], ids=["mark", "rotate"]
    )
    def test_has_animation(self, box, attr):
        assert hasattr(box, attr)
        assert isinstance(getattr(box, attr), QPropertyAnimation)

    def test_mark_animation_duration_uses_normal_token(self, box, motion_full):
        assert box._mark_animation.duration() == Duration.Normal


class TestElaTagSearchBoxExpandProperties:
    @pytest.mark.parametrize(
        ("prop", "value"),
        [("expandMarkWidth", 50.0), ("expandIconRotate", -180.0)],
        ids=["mark-width", "icon-rotate"],
    )
    def test_expand_property_roundtrip(self, box, prop, value):
        setattr(box, prop, value)
        assert getattr(box, prop) == value


class TestElaTagSearchBoxTitle:
    def test_set_title(self, box):
        box.setTitle("新标题")
        assert box._title_text == "新标题"

    def test_title_returns_current_title(self, make):
        assert make(ElaTagSearchBox, title="测试").title() == "测试"


class TestElaTagSearchBoxDeleteLater:
    def test_delete_later_disconnects_index_changed(self, make):
        # 析构时断连 currentIndexChanged 不应抛 TypeError。
        make(ElaTagSearchBox, title="test").deleteLater()


class TestElaTagSearchBoxPinyinSearch:
    def test_search_matches_pinyin_initials(self, make):
        """继承来的搜索按拼音首字母过滤行。"""
        box = make(ElaTagSearchBox, title="语言")
        box.addItems(["北京", "上海"])

        box._onSearchTextChanged("bj")
        view = box.view()

        assert view.isRowHidden(0) is False
        assert view.isRowHidden(1) is True
