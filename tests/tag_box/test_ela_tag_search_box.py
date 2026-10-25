"""``ElaTagSearchBox`` 测试：构造接线 / 展开属性 / 标题 / 拼音搜索。"""

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
    def test_ctor_wiring(self, box, motion_full):
        """一次钉住构造期接线 + 继承来的搜索能力没被 tag 外观盖掉。"""
        assert box._title_text == ""
        assert box._title_font_size == 13
        # 与上游 ElaComboBox V3.0（35→30）的触发框同高。
        assert box.height() == 30
        for attr in ("_mark_animation", "_rotate_animation"):
            anim = getattr(box, attr)
            assert isinstance(anim, QPropertyAnimation)
            assert anim.duration() == Duration.Normal
        assert isinstance(box, ElaSearchBox)

    def test_initialization_with_title(self, make):
        assert make(ElaTagSearchBox, title="语言")._title_text == "语言"


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
    def test_title_roundtrip(self, box):
        box.setTitle("新标题")
        assert box.title() == "新标题"
        assert box._title_text == "新标题"


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
