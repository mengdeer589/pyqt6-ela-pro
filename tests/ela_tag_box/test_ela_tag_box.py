"""``ElaTagBox`` 测试：初值 / 动画 / 展开属性 / 标题。"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPropertyAnimation

from pyqt6_ela_pro._motion import Duration
from pyqt6_ela_pro.ela_tag_box import ElaTagBox


@pytest.fixture
def box(make):
    """默认构造的 tag box（空标题）。"""
    return make(ElaTagBox)


class TestElaTagBoxInit:
    @pytest.mark.parametrize(
        ("attr", "expected"),
        [
            ("_title_text", ""),
            ("_expand_mark_width", 0.0),
            ("_expand_icon_rotate", 0.0),
            ("_title_font_size", 13),
        ],
        ids=["title", "mark-width", "icon-rotate", "title-font-size"],
    )
    def test_initialization_with_defaults(self, box, attr, expected):
        assert getattr(box, attr) == expected

    def test_initialization_with_title(self, make):
        assert make(ElaTagBox, title="语言")._title_text == "语言"

    def test_fixed_height_is_30(self, box):
        """与上游 ElaComboBox V3.0（35→30）的触发框同高。"""
        assert box.height() == 30


class TestElaTagBoxAnimations:
    @pytest.mark.parametrize(
        "attr", ["_mark_animation", "_rotate_animation"], ids=["mark", "rotate"]
    )
    def test_has_animation(self, box, attr):
        assert hasattr(box, attr)
        assert isinstance(getattr(box, attr), QPropertyAnimation)

    @pytest.mark.parametrize(
        "attr", ["_mark_animation", "_rotate_animation"], ids=["mark", "rotate"]
    )
    def test_animation_duration_uses_normal_token(self, box, attr, motion_full):
        assert getattr(box, attr).duration() == Duration.Normal


class TestElaTagBoxExpandProperties:
    @pytest.mark.parametrize(
        ("prop", "value"),
        [
            ("expandMarkWidth", 50.0),
            ("expandMarkWidth", 0.0),
            ("expandIconRotate", -180.0),
            ("expandIconRotate", 0.0),
        ],
        ids=["mark-width-50", "mark-width-0", "icon-rotate-minus180", "icon-rotate-0"],
    )
    def test_expand_property_roundtrip(self, box, prop, value):
        setattr(box, prop, value)
        assert getattr(box, prop) == value


class TestElaTagBoxTitle:
    def test_set_title(self, box):
        box.setTitle("新标题")
        assert box._title_text == "新标题"

    def test_title_returns_current_title(self, make):
        assert make(ElaTagBox, title="测试").title() == "测试"


class TestElaTagBoxDeleteLater:
    """析构路径本身就是被测行为：``_mark_animation`` / ``_rotate_animation``
    的 finished 信号在析构时要被解绑，漏解绑会抛 ``TypeError``。"""

    def test_delete_later_cleans_up(self, box):
        box.deleteLater()

    def test_delete_later_disconnects_index_changed(self, make):
        make(ElaTagBox, title="test").deleteLater()
